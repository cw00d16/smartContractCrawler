from __future__ import annotations

import json

import pytest

from crawler.crawl import run_crawl
from crawler.explorer_client import ExplorerRateLimitError
from crawler.graph_store import GraphStore
from crawler.models import ChainConfig
from crawler.resolvers.proxy_slots import KNOWN_SLOTS

from conftest import FakeExplorer, FakeRpc, FakeSourcify, make_source

ROOT = "0x000000000000000000000000000000000000Aa"
CHILD = "0x000000000000000000000000000000000000Bb"
IMPL = "0x000000000000000000000000000000000000Cc"
REAL_OWNER = "0x000000000000000000000000000000000000Dd"


def _chain() -> ChainConfig:
    return ChainConfig(name="test", chain_id=1, rpc_url="", explorer_api_base="", explorer_api_key="x")


def test_happy_path_discovers_child_via_abi_sweep(tmp_path):
    rpc = FakeRpc(getters={(ROOT.lower(), "processor"): CHILD})
    explorer = FakeExplorer(sources={ROOT.lower(): make_source(ROOT, "Root", fn_names=("processor",))})
    store = GraphStore(tmp_path / "graph.db")

    run_crawl(ROOT, _chain(), rpc, explorer, store, max_depth=3, max_nodes=10)

    nodes = {n["address"]: n for n in store.all_nodes()}
    assert nodes[ROOT.lower()]["status"] == "resolved"
    assert nodes[CHILD.lower()]["status"] == "unresolved"  # never given a source -> unverified

    edges = store.all_edges()
    assert any(e["edge_type"] == "abi:processor" and e["to_address"] == CHILD.lower() for e in edges)


def test_respects_max_nodes_cap(tmp_path):
    # A root with many distinct getters, each pointing to a distinct address.
    fn_names = tuple(f"getChild{i}" for i in range(10))
    getters = {(ROOT.lower(), fn): f"0x{i:040x}" for i, fn in enumerate(fn_names, start=1)}
    rpc = FakeRpc(getters=getters)
    explorer = FakeExplorer(sources={ROOT.lower(): make_source(ROOT, "Root", fn_names=fn_names)})
    store = GraphStore(tmp_path / "graph.db")

    run_crawl(ROOT, _chain(), rpc, explorer, store, max_depth=3, max_nodes=3)

    assert len(store.all_nodes()) == 3


def test_resume_continues_from_persisted_frontier_instead_of_restarting(tmp_path):
    fn_names = tuple(f"getChild{i}" for i in range(10))
    getters = {(ROOT.lower(), fn): f"0x{i:040x}" for i, fn in enumerate(fn_names, start=1)}
    rpc = FakeRpc(getters=getters)
    explorer = FakeExplorer(sources={ROOT.lower(): make_source(ROOT, "Root", fn_names=fn_names)})
    store = GraphStore(tmp_path / "graph.db")

    run_crawl(ROOT, _chain(), rpc, explorer, store, max_depth=3, max_nodes=3)
    assert len(store.all_nodes()) == 3
    assert len(store.load_frontier(1, ROOT)) == 8  # 10 children discovered, 2 processed so far

    run_crawl(ROOT, _chain(), rpc, explorer, store, max_depth=3, max_nodes=3, resume=True)
    assert len(store.all_nodes()) == 6  # 3 more processed -- not a repeat of the first 3
    assert len(store.load_frontier(1, ROOT)) == 5

    run_crawl(ROOT, _chain(), rpc, explorer, store, max_depth=3, max_nodes=100, resume=True)
    assert len(store.all_nodes()) == 11  # root + all 10 children, fully explored
    assert store.load_frontier(1, ROOT) == []  # nothing left to resume


def test_without_resume_flag_restarts_from_root_each_time(tmp_path):
    """Contrast case: omitting --resume deliberately re-walks from the root
    (needed so periodic re-crawls can detect drift anywhere in the graph),
    so repeated calls without it make no forward progress past max_nodes."""
    fn_names = tuple(f"getChild{i}" for i in range(10))
    getters = {(ROOT.lower(), fn): f"0x{i:040x}" for i, fn in enumerate(fn_names, start=1)}
    rpc = FakeRpc(getters=getters)
    explorer = FakeExplorer(sources={ROOT.lower(): make_source(ROOT, "Root", fn_names=fn_names)})
    store = GraphStore(tmp_path / "graph.db")

    run_crawl(ROOT, _chain(), rpc, explorer, store, max_depth=3, max_nodes=3)
    first_run_addresses = {n["address"] for n in store.all_nodes()}

    run_crawl(ROOT, _chain(), rpc, explorer, store, max_depth=3, max_nodes=3)  # no resume=True
    second_run_addresses = {n["address"] for n in store.all_nodes()}

    assert second_run_addresses == first_run_addresses  # same subset, no progress


def test_respects_max_depth(tmp_path):
    # ROOT -> CHILD -> (would go deeper, but depth cap stops it)
    grandchild = "0x000000000000000000000000000000000000Ee"
    rpc = FakeRpc(getters={
        (ROOT.lower(), "next"): CHILD,
        (CHILD.lower(), "next"): grandchild,
    })
    explorer = FakeExplorer(sources={
        ROOT.lower(): make_source(ROOT, "Root", fn_names=("next",)),
        CHILD.lower(): make_source(CHILD, "Child", fn_names=("next",)),
    })
    store = GraphStore(tmp_path / "graph.db")

    run_crawl(ROOT, _chain(), rpc, explorer, store, max_depth=1, max_nodes=10)

    addresses = {n["address"] for n in store.all_nodes()}
    assert grandchild.lower() not in addresses


def test_proxy_forwarding_resolves_real_value_not_sentinel(tmp_path):
    sentinel = "0x0000000000000000000000000000000000000001"
    rpc = FakeRpc(
        storage={(ROOT.lower(), KNOWN_SLOTS["legacy_zos_implementation"]): IMPL},
        getters={
            (ROOT.lower(), "owner"): REAL_OWNER,   # called through the proxy -> real value
            (IMPL.lower(), "owner"): sentinel,      # called directly on impl -> uninitialized sentinel
        },
    )
    explorer = FakeExplorer(sources={IMPL.lower(): make_source(IMPL, "Impl", fn_names=("owner",))})
    store = GraphStore(tmp_path / "graph.db")

    run_crawl(ROOT, _chain(), rpc, explorer, store, max_depth=3, max_nodes=10)

    edges = store.all_edges()
    via_proxy = [e for e in edges if e["edge_type"] == "abi_via_proxy:owner"]
    direct = [e for e in edges if e["edge_type"] == "abi:owner"]

    assert len(via_proxy) == 1
    assert via_proxy[0]["to_address"] == REAL_OWNER.lower()
    assert len(direct) == 1
    assert direct[0]["to_address"] == sentinel  # old noisy edge still preserved, not replaced


def test_beacon_proxy_edges_are_not_forwarded(tmp_path):
    """Beacon proxies are excluded from proxy-forwarding: the beacon address
    is called directly, not delegatecalled, so forwarding would be wrong."""
    beacon = IMPL
    rpc = FakeRpc(storage={(ROOT.lower(), KNOWN_SLOTS["eip1967_beacon"]): beacon})
    explorer = FakeExplorer(sources={beacon.lower(): make_source(beacon, "Beacon", fn_names=("owner",))})
    store = GraphStore(tmp_path / "graph.db")

    run_crawl(ROOT, _chain(), rpc, explorer, store, max_depth=3, max_nodes=10)

    edges = store.all_edges()
    assert not any(e["edge_type"] == "abi_via_proxy:owner" for e in edges)


def test_rate_limit_error_stops_crawl_immediately(tmp_path):
    rpc = FakeRpc()
    explorer = FakeExplorer(raise_on=[ROOT])
    store = GraphStore(tmp_path / "graph.db")

    with pytest.raises(ExplorerRateLimitError):
        run_crawl(ROOT, _chain(), rpc, explorer, store, max_depth=3, max_nodes=200)

    # Must not have continued on to fetch anything else.
    assert explorer.calls == [ROOT]
    # The interrupted node was never actually resolved either way -- it must
    # not be recorded as a permanent "unresolved" node...
    assert store.all_nodes() == []
    # ...it goes back into the resumable frontier instead, to retry first.
    assert store.load_frontier(1, ROOT) == [(ROOT.lower(), 0)]


def test_rate_limit_during_proxy_forward_fetch_also_stops(tmp_path):
    rpc = FakeRpc(storage={(ROOT.lower(), KNOWN_SLOTS["legacy_zos_implementation"]): IMPL})
    explorer = FakeExplorer(sources={ROOT.lower(): make_source(ROOT, "Proxy")}, raise_on=[IMPL])
    store = GraphStore(tmp_path / "graph.db")

    with pytest.raises(ExplorerRateLimitError):
        run_crawl(ROOT, _chain(), rpc, explorer, store, max_depth=3, max_nodes=200)

    assert explorer.calls == [ROOT, IMPL]
    # ROOT itself WAS resolved (its own source fetch succeeded) -- only the
    # proxy-forwarding sub-step failed, so ROOT is recorded normally, and
    # the already-discovered proxy edge's target (IMPL) is left in the
    # frontier so --resume continues exploring from there.
    nodes = store.all_nodes()
    assert len(nodes) == 1 and nodes[0]["status"] == "resolved"
    assert store.load_frontier(1, ROOT) == [(IMPL.lower(), 1)]


def test_unverified_root_is_flagged_not_crashed(tmp_path):
    rpc = FakeRpc()
    explorer = FakeExplorer()  # no sources at all
    store = GraphStore(tmp_path / "graph.db")

    run_crawl(ROOT, _chain(), rpc, explorer, store, max_depth=1, max_nodes=5)

    nodes = store.all_nodes()
    assert len(nodes) == 1
    assert nodes[0]["status"] == "unresolved"
    assert nodes[0]["verified"] == 0


def test_sourcify_fallback_used_when_etherscan_has_nothing(tmp_path):
    rpc = FakeRpc()
    explorer = FakeExplorer()  # unverified on Etherscan
    sourcify = FakeSourcify(sources={ROOT.lower(): make_source(ROOT, "FooFromSourcify")})
    store = GraphStore(tmp_path / "graph.db")

    run_crawl(ROOT, _chain(), rpc, explorer, store, max_depth=1, max_nodes=5, sourcify=sourcify)

    nodes = store.all_nodes()
    assert nodes[0]["status"] == "resolved"
    assert nodes[0]["verified"] == 1
    assert nodes[0]["name"] == "FooFromSourcify"
    assert any("Sourcify" in note for note in json.loads(nodes[0]["notes"]))
    assert sourcify.calls == [(1, ROOT)]


def test_sourcify_not_consulted_when_etherscan_already_verified(tmp_path):
    rpc = FakeRpc()
    explorer = FakeExplorer(sources={ROOT.lower(): make_source(ROOT, "FooFromEtherscan")})
    sourcify = FakeSourcify(sources={ROOT.lower(): make_source(ROOT, "ShouldNotBeUsed")})
    store = GraphStore(tmp_path / "graph.db")

    run_crawl(ROOT, _chain(), rpc, explorer, store, max_depth=1, max_nodes=5, sourcify=sourcify)

    nodes = store.all_nodes()
    assert nodes[0]["name"] == "FooFromEtherscan"
    assert sourcify.calls == []  # never consulted -- Etherscan already had it


def test_unverified_everywhere_falls_through_to_bytecode_scan(tmp_path):
    candidate = "0x" + "00" * 19 + "ff"
    code = bytes([0x73]) + bytes.fromhex(candidate[2:])  # PUSH20 <candidate>
    rpc = FakeRpc(code={ROOT.lower(): code, candidate.lower(): b"\x60\x00"})
    explorer = FakeExplorer()  # unverified on Etherscan
    sourcify = FakeSourcify()  # and unverified on Sourcify
    store = GraphStore(tmp_path / "graph.db")

    run_crawl(ROOT, _chain(), rpc, explorer, store, max_depth=1, max_nodes=5, sourcify=sourcify)

    nodes = {n["address"]: n for n in store.all_nodes()}
    assert nodes[ROOT.lower()]["status"] == "unresolved"  # still no real source for the root itself
    edges = store.all_edges()
    assert any(e["edge_type"] == "bytecode:push20_constant" and e["to_address"] == candidate.lower() for e in edges)
