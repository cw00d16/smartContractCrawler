from __future__ import annotations

import json
from pathlib import Path

from crawler.graph_store import GraphStore
from crawler.models import Edge, Node
from crawler.snapshot import diff_snapshots, format_diff_report, save_snapshot

ROOT = "0xAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAa"
IMPL_OLD = "0xBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBb"
IMPL_NEW = "0xCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCc"
NEW_DEP = "0xDdDdDdDdDdDdDdDdDdDdDdDdDdDdDdDdDdDdDdDd"


def test_save_snapshot_writes_current_store_state(tmp_path):
    store = GraphStore(tmp_path / "graph.db")
    store.upsert_node(Node(chain_id=1, address=ROOT, name="Proxy", status="resolved"))
    store.add_edge(Edge(chain_id=1, from_address=ROOT, to_address=IMPL_OLD, edge_type="proxy:eip1967_implementation", source="eip1967_implementation"))

    path = save_snapshot(store, tmp_path / "snapshots", chain_id=1, root_address=ROOT)

    assert path.exists()
    data = json.loads(path.read_text())
    assert data["root_address"] == ROOT.lower()
    assert data["chain_id"] == 1
    assert len(data["nodes"]) == 1
    assert data["nodes"][0]["notes"] == []  # decoded from JSON string, not left as raw text
    assert len(data["edges"]) == 1


def test_save_snapshot_filename_includes_root_and_timestamp(tmp_path):
    store = GraphStore(tmp_path / "graph.db")
    path = save_snapshot(store, tmp_path / "snapshots", chain_id=1, root_address=ROOT)
    assert ROOT.lower() in path.name
    assert path.name.endswith(".json")


def _snapshot(tmp_path, name, nodes, edges, root=ROOT, chain_id=1, taken_at="20260101T000000Z") -> Path:
    data = {"root_address": root.lower(), "chain_id": chain_id, "taken_at": taken_at, "nodes": nodes, "edges": edges}
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return path


def _node(address, **kwargs):
    base = {"chain_id": 1, "address": address.lower(), "depth": 0, "name": None, "verified": 0, "is_proxy": 0, "status": "pending", "notes": []}
    base.update(kwargs)
    return base


def _edge(from_addr, to_addr, edge_type, **kwargs):
    base = {"chain_id": 1, "from_address": from_addr.lower(), "to_address": to_addr.lower(), "edge_type": edge_type, "source": edge_type, "confidence": "high"}
    base.update(kwargs)
    return base


def test_diff_detects_implementation_change(tmp_path):
    old = _snapshot(
        tmp_path, "old.json",
        nodes=[_node(ROOT, name="Proxy", is_proxy=1, status="resolved")],
        edges=[_edge(ROOT, IMPL_OLD, "proxy:eip1967_implementation")],
        taken_at="2026-08-01",
    )
    new = _snapshot(
        tmp_path, "new.json",
        nodes=[_node(ROOT, name="Proxy", is_proxy=1, status="resolved")],
        edges=[_edge(ROOT, IMPL_NEW, "proxy:eip1967_implementation")],
        taken_at="2026-08-20",
    )

    diff = diff_snapshots(old, new)

    assert diff["edges_removed"] == [_edge(ROOT, IMPL_OLD, "proxy:eip1967_implementation")]
    assert diff["edges_added"] == [_edge(ROOT, IMPL_NEW, "proxy:eip1967_implementation")]
    assert diff["nodes_added"] == []
    assert diff["nodes_removed"] == []


def test_diff_detects_new_and_removed_nodes(tmp_path):
    old = _snapshot(tmp_path, "old.json", nodes=[_node(ROOT)], edges=[])
    new = _snapshot(tmp_path, "new.json", nodes=[_node(ROOT), _node(NEW_DEP, name="NewDep")], edges=[])

    diff = diff_snapshots(old, new)

    assert diff["nodes_added"] == [{"address": NEW_DEP.lower(), "name": "NewDep"}]
    assert diff["nodes_removed"] == []


def test_diff_detects_node_field_changes(tmp_path):
    old = _snapshot(tmp_path, "old.json", nodes=[_node(ROOT, status="unresolved", verified=0)], edges=[])
    new = _snapshot(tmp_path, "new.json", nodes=[_node(ROOT, status="resolved", verified=1, name="NowVerified")], edges=[])

    diff = diff_snapshots(old, new)

    assert len(diff["nodes_changed"]) == 1
    changes = diff["nodes_changed"][0]["changes"]
    assert changes["status"] == ["unresolved", "resolved"]
    assert changes["verified"] == [0, 1]
    assert changes["name"] == [None, "NowVerified"]


def test_diff_reports_nothing_when_identical(tmp_path):
    nodes = [_node(ROOT, name="Proxy")]
    edges = [_edge(ROOT, IMPL_OLD, "proxy:eip1967_implementation")]
    old = _snapshot(tmp_path, "old.json", nodes=nodes, edges=edges)
    new = _snapshot(tmp_path, "new.json", nodes=nodes, edges=edges)

    diff = diff_snapshots(old, new)

    assert diff["nodes_added"] == []
    assert diff["nodes_removed"] == []
    assert diff["nodes_changed"] == []
    assert diff["edges_added"] == []
    assert diff["edges_removed"] == []


def test_format_diff_report_is_human_readable(tmp_path):
    old = _snapshot(tmp_path, "old.json", nodes=[_node(ROOT)], edges=[_edge(ROOT, IMPL_OLD, "proxy:eip1967_implementation")], taken_at="A")
    new = _snapshot(tmp_path, "new.json", nodes=[_node(ROOT), _node(NEW_DEP, name="NewDep")], edges=[_edge(ROOT, IMPL_NEW, "proxy:eip1967_implementation")], taken_at="B")

    report = format_diff_report(diff_snapshots(old, new))

    assert "A -> B" in report
    assert NEW_DEP.lower() in report
    assert IMPL_OLD.lower() in report
    assert IMPL_NEW.lower() in report
