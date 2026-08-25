from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from . import export
from .cache import SourceCache
from .chains import CHAIN_NAMES, get_chain
from .crawl import run_crawl
from .explorer_client import ExplorerClient, ExplorerRateLimitError
from .graph_store import GraphStore
from .models import ChainConfig
from .ratelimit import RateLimiter
from .render import render_mermaid
from .rpc_client import RpcClient
from .snapshot import diff_snapshots, format_diff_report, save_snapshot
from .sourcify_client import SourcifyClient


def _add_crawl_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--chain", choices=sorted(CHAIN_NAMES), default="mainnet")
    parser.add_argument("--depth", type=int, default=5)
    parser.add_argument("--max-nodes", type=int, default=200, help="Budget per root address")
    parser.add_argument("--out-dir", default="./output")
    parser.add_argument(
        "--no-sourcify", action="store_true",
        help="Disable the Sourcify fallback for contracts unverified on Etherscan",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Continue a previously interrupted/capped crawl of this root instead of restarting from it",
    )
    parser.add_argument(
        "--snapshot", action="store_true",
        help="Also save a timestamped snapshot (out-dir/snapshots/) for later `diff`",
    )


class _ChainInfra:
    def __init__(self, chain: ChainConfig, out_dir: Path, use_sourcify: bool):
        self.chain = chain
        self.out_dir = out_dir
        self.rpc = RpcClient(chain.rpc_url, timeout=chain.request_timeout)
        rate_limiter = RateLimiter(chain.rate_limit_per_sec)
        self.explorer = ExplorerClient(chain, SourceCache(out_dir / "cache"), rate_limiter)
        self.store = GraphStore(out_dir / "graph.db")
        self.sourcify: Optional[SourcifyClient] = None
        if use_sourcify:
            # Separate cache root: Sourcify and Etherscan cache entries share
            # the same (chain_id, address) key shape, so they'd collide if
            # they shared a cache directory despite being different sources.
            self.sourcify = SourcifyClient(SourceCache(out_dir / "cache_sourcify"))


def _build_infra(args: argparse.Namespace, parser: argparse.ArgumentParser) -> _ChainInfra:
    chain = get_chain(args.chain)  # built after load_dotenv() so .env is honored
    if not chain.explorer_api_key:
        parser.error("ETHERSCAN_API_KEY is not set (copy .env.example to .env and fill it in)")
    return _ChainInfra(chain, Path(args.out_dir), use_sourcify=not args.no_sourcify)


def _crawl_one(address: str, infra: _ChainInfra, args: argparse.Namespace) -> bool:
    """Runs one root's crawl against shared infra. Returns True if it was
    stopped by a rate limit (fatal for the whole batch, if in one)."""
    try:
        run_crawl(
            root_address=address,
            chain=infra.chain,
            rpc=infra.rpc,
            explorer=infra.explorer,
            store=infra.store,
            max_depth=args.depth,
            max_nodes=args.max_nodes,
            sourcify=infra.sourcify,
            resume=args.resume,
        )
    except ExplorerRateLimitError as exc:
        print(f"\nSTOPPED: {exc}")
        print("Aborting instead of continuing to hit an already-rate-limited API.")
        print("Progress so far is saved and resumable with --resume.\n")
        return True

    if args.snapshot:
        path = save_snapshot(infra.store, infra.out_dir / "snapshots", infra.chain.chain_id, address)
        print(f"Snapshot: {path}")
    return False


def _print_summary(store: GraphStore, out_dir: Path, rate_limited: bool) -> None:
    nodes = store.all_nodes()
    edges = store.all_edges()
    unresolved = [n for n in nodes if n["status"] == "unresolved"]

    status = "STOPPED (rate limited)" if rate_limited else "Crawled"
    print(f"{status}: {len(nodes)} nodes, {len(edges)} edges, {len(unresolved)} unresolved.")
    for n in unresolved:
        notes = ", ".join(json.loads(n["notes"]))
        print(f"  unresolved: {n['address']} ({notes})")
    print(f"Graph:   {out_dir / 'graph.json'}")
    print(f"Sources: {out_dir / 'sources'}")


def _cmd_crawl(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    infra = _build_infra(args, parser)
    rate_limited = _crawl_one(args.address, infra, args)

    export.export_graph_json(infra.store, infra.out_dir / "graph.json")
    export.export_source_bundle(infra.store, infra.out_dir / "sources")
    _print_summary(infra.store, infra.out_dir, rate_limited)
    infra.store.close()


def _cmd_batch(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    addresses = list(dict.fromkeys(args.addresses))  # de-dup, preserve order
    if args.file:
        file_addresses = [line.strip() for line in Path(args.file).read_text().splitlines() if line.strip()]
        addresses = list(dict.fromkeys(addresses + file_addresses))
    if not addresses:
        parser.error("no addresses given (pass them positionally or via --file)")

    infra = _build_infra(args, parser)
    rate_limited = False
    for i, address in enumerate(addresses, start=1):
        print(f"\n=== [{i}/{len(addresses)}] {address} ===")
        rate_limited = _crawl_one(address, infra, args)
        if rate_limited:
            remaining = len(addresses) - i
            if remaining:
                print(f"Stopping batch early -- {remaining} address(es) not yet started (still safe to resume via a later run).")
            break

    export.export_graph_json(infra.store, infra.out_dir / "graph.json")
    export.export_source_bundle(infra.store, infra.out_dir / "sources")
    _print_summary(infra.store, infra.out_dir, rate_limited)
    infra.store.close()


def _cmd_diff(args: argparse.Namespace) -> None:
    diff = diff_snapshots(Path(args.old_snapshot), Path(args.new_snapshot))
    if args.json:
        print(json.dumps(diff, indent=2))
    else:
        print(format_diff_report(diff))


def _cmd_render(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph_json)
    out_path = Path(args.out) if args.out else graph_path.with_suffix(".mmd")
    out_path.write_text(render_mermaid(graph_path))
    print(f"Mermaid diagram: {out_path}")


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        prog="sc-crawl",
        description="Crawl a smart contract and its proxy/child contracts, producing a dependency graph and source bundle.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    crawl_parser = subparsers.add_parser("crawl", help="Crawl a single root contract")
    crawl_parser.add_argument("address", help="Root contract address")
    _add_crawl_options(crawl_parser)

    batch_parser = subparsers.add_parser("batch", help="Crawl multiple root contracts, sharing rate limits and cache")
    batch_parser.add_argument("addresses", nargs="*", help="Root addresses to crawl")
    batch_parser.add_argument("--file", help="Path to a text file with one address per line")
    _add_crawl_options(batch_parser)

    diff_parser = subparsers.add_parser("diff", help="Diff two saved snapshots")
    diff_parser.add_argument("old_snapshot")
    diff_parser.add_argument("new_snapshot")
    diff_parser.add_argument("--json", action="store_true", help="Print the raw diff as JSON instead of a text report")

    render_parser = subparsers.add_parser("render", help="Render a graph.json or snapshot as a Mermaid diagram (.mmd)")
    render_parser.add_argument("graph_json")
    render_parser.add_argument("--out", help="Output .mmd path (default: alongside the input file)")

    args = parser.parse_args()

    if args.command == "crawl":
        _cmd_crawl(args, crawl_parser)
    elif args.command == "batch":
        _cmd_batch(args, batch_parser)
    elif args.command == "diff":
        _cmd_diff(args)
    elif args.command == "render":
        _cmd_render(args)


if __name__ == "__main__":
    main()
