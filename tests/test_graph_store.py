from __future__ import annotations

from crawler.graph_store import GraphStore
from crawler.models import ContractSource, Edge, Node


def _store(tmp_path) -> GraphStore:
    return GraphStore(tmp_path / "graph.db")


def test_upsert_node_inserts(tmp_path):
    store = _store(tmp_path)
    store.upsert_node(Node(chain_id=1, address="0xAbC", depth=0, name="Foo", verified=True))
    nodes = store.all_nodes()
    assert len(nodes) == 1
    assert nodes[0]["address"] == "0xabc"  # stored lowercase
    assert nodes[0]["name"] == "Foo"
    assert nodes[0]["verified"] == 1


def test_upsert_node_updates_existing(tmp_path):
    store = _store(tmp_path)
    store.upsert_node(Node(chain_id=1, address="0xabc", depth=0, status="pending"))
    store.upsert_node(Node(chain_id=1, address="0xabc", depth=0, status="resolved"))
    nodes = store.all_nodes()
    assert len(nodes) == 1
    assert nodes[0]["status"] == "resolved"


def test_add_edge_deduplicates_identical_edges(tmp_path):
    store = _store(tmp_path)
    edge = Edge(chain_id=1, from_address="0xAaa", to_address="0xBbb", edge_type="abi:owner", source="owner")
    store.add_edge(edge)
    store.add_edge(edge)
    assert len(store.all_edges()) == 1


def test_add_edge_keeps_distinct_edge_types_separate(tmp_path):
    store = _store(tmp_path)
    store.add_edge(Edge(chain_id=1, from_address="0xAaa", to_address="0xBbb", edge_type="abi:owner", source="owner"))
    store.add_edge(Edge(chain_id=1, from_address="0xAaa", to_address="0xBbb", edge_type="abi_via_proxy:owner", source="owner"))
    assert len(store.all_edges()) == 2


def test_upsert_source_roundtrips(tmp_path):
    store = _store(tmp_path)
    source = ContractSource(
        chain_id=1, address="0xAbC", contract_name="Foo",
        abi=[{"type": "function", "name": "owner"}],
        source_files={"Foo.sol": "contract Foo {}"},
        compiler_version="v0.8.20",
    )
    store.upsert_source(source)
    sources = store.all_sources()
    assert len(sources) == 1
    assert sources[0]["contract_name"] == "Foo"
    assert sources[0]["address"] == "0xabc"


def test_add_edge_persists_confidence(tmp_path):
    store = _store(tmp_path)
    store.add_edge(Edge(chain_id=1, from_address="0xAaa", to_address="0xBbb", edge_type="proxy:eip1967_implementation", source="eip1967_implementation", confidence="high"))
    assert store.all_edges()[0]["confidence"] == "high"


def test_known_addresses_returns_visited_nodes_for_chain(tmp_path):
    store = _store(tmp_path)
    store.upsert_node(Node(chain_id=1, address="0xAbC"))
    store.upsert_node(Node(chain_id=1, address="0xDeF"))
    store.upsert_node(Node(chain_id=100, address="0x111"))  # different chain

    assert store.known_addresses(1) == {"0xabc", "0xdef"}
    assert store.known_addresses(100) == {"0x111"}
    assert store.known_addresses(999) == set()


def test_frontier_roundtrips_in_order(tmp_path):
    store = _store(tmp_path)
    queue = [("0xAaa", 1), ("0xBbb", 2), ("0xCcc", 2)]

    store.save_frontier(1, "0xRoot", queue)

    assert store.load_frontier(1, "0xRoot") == [("0xaaa", 1), ("0xbbb", 2), ("0xccc", 2)]


def test_frontier_scoped_by_root_and_chain(tmp_path):
    store = _store(tmp_path)
    store.save_frontier(1, "0xRootA", [("0xAaa", 1)])
    store.save_frontier(1, "0xRootB", [("0xBbb", 1)])
    store.save_frontier(100, "0xRootA", [("0xCcc", 1)])

    assert store.load_frontier(1, "0xRootA") == [("0xaaa", 1)]
    assert store.load_frontier(1, "0xRootB") == [("0xbbb", 1)]
    assert store.load_frontier(100, "0xRootA") == [("0xccc", 1)]


def test_save_frontier_replaces_previous_contents(tmp_path):
    store = _store(tmp_path)
    store.save_frontier(1, "0xRoot", [("0xAaa", 1), ("0xBbb", 1)])
    store.save_frontier(1, "0xRoot", [("0xCcc", 2)])

    assert store.load_frontier(1, "0xRoot") == [("0xccc", 2)]


def test_load_frontier_empty_when_never_saved(tmp_path):
    store = _store(tmp_path)
    assert store.load_frontier(1, "0xRoot") == []
