from __future__ import annotations

from collections import deque
from typing import Optional

from .confidence import classify_edge_confidence
from .explorer_client import ExplorerClient, ExplorerRateLimitError
from .graph_store import GraphStore
from .models import ChainConfig, ContractSource, Edge, Node
from .resolvers import (
    AbiSweepResolver,
    BytecodeConstantResolver,
    CrawlContext,
    DiamondLoupeResolver,
    Resolver,
    ProxySlotResolver,
)
from .rpc_client import RpcClient
from .sourcify_client import SourcifyClient

# Edge types where the target address is executed via delegatecall from the
# proxy -- so its storage-reliant getters (owner(), etc.) only return live
# values when called at the proxy's own address, not the target's. Beacon
# proxies are deliberately excluded: the beacon address is called directly
# (not delegatecalled), so its own ABI sweep already reads its real storage.
_DELEGATED_PROXY_EDGE_TYPES = {
    "proxy:eip1967_implementation",
    "proxy:eip1822_uups",
    "proxy:legacy_zos_implementation",
}


def _run_resolvers(resolvers: list[Resolver], node: Node, ctx: CrawlContext) -> list[Edge]:
    edges: list[Edge] = []
    for resolver in resolvers:
        try:
            edges.extend(resolver.discover(node, ctx))
        except Exception as exc:
            node.notes.append(f"{resolver.name} failed: {exc}")
    return edges


def _forward_delegated_proxy_edges(
    edges: list[Edge],
    node: Node,
    explorer: ExplorerClient,
    abi_sweep_resolver: AbiSweepResolver,
) -> list[Edge]:
    """For each delegatecall-proxy edge just found, fetch the implementation's
    ABI and sweep it against the proxy's own address instead of the
    implementation's -- see _DELEGATED_PROXY_EDGE_TYPES. Raises
    ExplorerRateLimitError to the caller; other fetch/call failures are
    recorded as node notes and skipped."""
    forwarded: list[Edge] = []
    for edge in edges:
        if edge.edge_type not in _DELEGATED_PROXY_EDGE_TYPES:
            continue
        try:
            impl_source = explorer.get_source(edge.to_address)
        except ExplorerRateLimitError:
            raise
        except Exception as exc:
            node.notes.append(f"proxy-forward fetch failed for {edge.to_address}: {exc}")
            continue
        if not impl_source or not impl_source.abi:
            continue
        try:
            forwarded.extend(
                abi_sweep_resolver.sweep_via(
                    node.chain_id, node.address, impl_source.abi, namespace="abi_via_proxy"
                )
            )
        except Exception as exc:
            node.notes.append(f"abi_sweep via proxy failed: {exc}")
    return forwarded


def _fetch_source(
    address: str,
    chain_id: int,
    explorer: ExplorerClient,
    sourcify: Optional[SourcifyClient],
    node: Node,
) -> Optional[ContractSource]:
    """Etherscan first; Sourcify (free, keyless) as a fallback when Etherscan
    has nothing. ExplorerRateLimitError propagates as fatal -- Sourcify
    failures do not, since it's a best-effort secondary source."""
    try:
        source = explorer.get_source(address)
    except ExplorerRateLimitError:
        raise
    except Exception as exc:
        source = None
        node.notes.append(f"explorer fetch failed: {exc}")

    if source is None and sourcify is not None:
        try:
            source = sourcify.get_source(chain_id, address)
            if source is not None:
                node.notes.append("verified via Sourcify (unverified on Etherscan)")
        except Exception as exc:
            node.notes.append(f"sourcify fetch failed: {exc}")

    return source


def _persist_discoveries(
    store: GraphStore,
    edges: list[Edge],
    seen: set[str],
    queue: deque,
    depth: int,
) -> None:
    for edge in edges:
        store.add_edge(edge)
        key = edge.to_address.lower()
        if key not in seen:
            seen.add(key)
            queue.append((edge.to_address, depth + 1))


def _seed_queue_and_seen(
    root_address: str, chain_id: int, rpc: RpcClient, store: GraphStore, resume: bool
) -> tuple[deque, set[str]]:
    frontier = store.load_frontier(chain_id, root_address) if resume else []
    if frontier:
        # Resuming an interrupted crawl of THIS root: skip anything already
        # visited (any root, any prior crawl sharing this store). A fresh
        # (non-resumed) crawl deliberately does NOT do this -- re-crawling the
        # same root from scratch is how snapshot/diff catches drift anywhere
        # in the graph, which requires actually revisiting known nodes.
        seen = store.known_addresses(chain_id) | {a.lower() for a, _ in frontier}
        return deque(frontier), seen

    root = rpc.checksum(root_address)
    return deque([(root, 0)]), {root.lower()}


def run_crawl(
    root_address: str,
    chain: ChainConfig,
    rpc: RpcClient,
    explorer: ExplorerClient,
    store: GraphStore,
    max_depth: int = 5,
    max_nodes: int = 200,
    sourcify: Optional[SourcifyClient] = None,
    resume: bool = False,
) -> None:
    abi_sweep_resolver = AbiSweepResolver(rpc)
    resolvers: list[Resolver] = [
        ProxySlotResolver(rpc),
        abi_sweep_resolver,
        DiamondLoupeResolver(rpc),
        BytecodeConstantResolver(rpc),  # only contributes when ctx.source is None
    ]

    queue, seen = _seed_queue_and_seen(root_address, chain.chain_id, rpc, store, resume)
    visited_count = 0

    try:
        while queue and visited_count < max_nodes:
            address, depth = queue.popleft()
            if depth > max_depth:
                continue
            visited_count += 1

            node = Node(chain_id=chain.chain_id, address=address, depth=depth)

            print(f"[{visited_count}/{max_nodes}] fetching {address} (depth {depth})")
            try:
                source = _fetch_source(address, chain.chain_id, explorer, sourcify, node)
            except ExplorerRateLimitError:
                # This node was never actually resolved either way -- put it
                # back at the front of the queue so --resume retries it first,
                # rather than recording it as a permanent "unresolved" node.
                queue.appendleft((address, depth))
                raise

            if source:
                node.verified = True
                node.name = source.contract_name
                node.status = "resolved"
                store.upsert_source(source)
            else:
                node.status = "unresolved"
                node.notes.append("unverified - bytecode only")

            ctx = CrawlContext(chain=chain, source=source)
            discovered_edges = _run_resolvers(resolvers, node, ctx)

            try:
                forwarded = _forward_delegated_proxy_edges(discovered_edges, node, explorer, abi_sweep_resolver)
                discovered_edges.extend(forwarded)
            except ExplorerRateLimitError as exc:
                node.notes.append(str(exc))
                store.upsert_node(node)
                _persist_discoveries(store, discovered_edges, seen, queue, depth)
                raise

            for edge in discovered_edges:
                edge.confidence = classify_edge_confidence(edge)
            _persist_discoveries(store, discovered_edges, seen, queue, depth)
            store.upsert_node(node)
    finally:
        # Always leave a frontier behind: empty if the graph was fully
        # explored (nothing left to resume), non-empty if max_nodes or a
        # rate limit cut the crawl short (exactly what --resume continues).
        store.save_frontier(chain.chain_id, root_address, list(queue))
