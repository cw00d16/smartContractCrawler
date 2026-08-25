from __future__ import annotations

from ..bytecode_scan import scan_push20_addresses
from ..models import Edge, Node
from .base import CrawlContext, Resolver

_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
_MAX_CANDIDATES_TO_VERIFY = 25  # bound worst-case RPC calls for a single node


class BytecodeConstantResolver(Resolver):
    """Last-resort fallback for a contract with no ABI available from any
    source (neither Etherscan nor Sourcify): scan its raw runtime bytecode
    for PUSH20 <address> constants. Only runs when ctx.source is None, since
    a real ABI is always a strictly better signal when one exists.

    Low-confidence by design -- a PUSH20 constant might be a real dependency
    address, an interface-ID-adjacent value, or unrelated data that happens
    to be 20 bytes. Candidates are kept only if they resolve to an address
    that itself has code on-chain, which filters out most non-address noise
    cheaply (an extra eth_getCode per candidate, capped to bound worst-case
    RPC volume on large, constant-heavy bytecode)."""

    name = "bytecode_constants"

    def discover(self, node: Node, ctx: CrawlContext) -> list[Edge]:
        if ctx.source is not None:
            return []

        try:
            code = self.rpc.get_code(node.address)
        except Exception:
            return []
        if not code:
            return []

        edges: list[Edge] = []
        seen: set[str] = set()
        for candidate in scan_push20_addresses(code)[:_MAX_CANDIDATES_TO_VERIFY]:
            key = candidate.lower()
            if key in seen or key == _ZERO_ADDRESS or key == node.address.lower():
                continue
            seen.add(key)

            try:
                has_code = bool(self.rpc.get_code(candidate))
            except Exception:
                continue
            if not has_code:
                continue

            edges.append(Edge(
                chain_id=node.chain_id,
                from_address=node.address,
                to_address=candidate,
                edge_type="bytecode:push20_constant",
                source="push20_scan",
            ))
        return edges
