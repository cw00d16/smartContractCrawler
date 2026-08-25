from __future__ import annotations

import json
import time
from pathlib import Path

from .graph_store import GraphStore

_NODE_FIELDS_TO_COMPARE = ("name", "verified", "is_proxy", "status")


def save_snapshot(store: GraphStore, snapshot_dir: Path, chain_id: int, root_address: str) -> Path:
    """Write the current graph state to a timestamped, immutable JSON file --
    separate from the live graph.json -- so a later crawl of the same root
    can be diffed against it to spot drift: a changed implementation
    pointer, a new or vanished dependency, a verification-status change."""
    nodes = store.all_nodes()
    for n in nodes:
        n["notes"] = json.loads(n["notes"])
    edges = store.all_edges()

    taken_at = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    snapshot = {
        "root_address": root_address.lower(),
        "chain_id": chain_id,
        "taken_at": taken_at,
        "nodes": nodes,
        "edges": edges,
    }

    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_dir / f"{chain_id}_{root_address.lower()}_{taken_at}.json"
    path.write_text(json.dumps(snapshot, indent=2))
    return path


def _edge_key(edge: dict) -> tuple:
    return (edge["from_address"], edge["to_address"], edge["edge_type"])


def diff_snapshots(old_path: Path, new_path: Path) -> dict:
    old = json.loads(old_path.read_text())
    new = json.loads(new_path.read_text())

    old_nodes = {n["address"]: n for n in old["nodes"]}
    new_nodes = {n["address"]: n for n in new["nodes"]}
    old_edges = {_edge_key(e): e for e in old["edges"]}
    new_edges = {_edge_key(e): e for e in new["edges"]}

    nodes_added = sorted(set(new_nodes) - set(old_nodes))
    nodes_removed = sorted(set(old_nodes) - set(new_nodes))

    nodes_changed = []
    for addr in sorted(set(old_nodes) & set(new_nodes)):
        old_n, new_n = old_nodes[addr], new_nodes[addr]
        changes = {
            field: [old_n.get(field), new_n.get(field)]
            for field in _NODE_FIELDS_TO_COMPARE
            if old_n.get(field) != new_n.get(field)
        }
        if changes:
            nodes_changed.append({"address": addr, "changes": changes})

    edges_added = sorted(set(new_edges) - set(old_edges))
    edges_removed = sorted(set(old_edges) - set(new_edges))

    return {
        "old_snapshot": {"taken_at": old.get("taken_at"), "root_address": old.get("root_address")},
        "new_snapshot": {"taken_at": new.get("taken_at"), "root_address": new.get("root_address")},
        "nodes_added": [{"address": a, "name": new_nodes[a].get("name")} for a in nodes_added],
        "nodes_removed": [{"address": a, "name": old_nodes[a].get("name")} for a in nodes_removed],
        "nodes_changed": nodes_changed,
        "edges_added": [new_edges[k] for k in edges_added],
        "edges_removed": [old_edges[k] for k in edges_removed],
    }


def format_diff_report(diff: dict) -> str:
    old_meta, new_meta = diff["old_snapshot"], diff["new_snapshot"]
    lines = [f"Diff: {old_meta.get('taken_at')} -> {new_meta.get('taken_at')}", ""]

    lines.append(f"Nodes added ({len(diff['nodes_added'])}):")
    lines += [f"  + {n['address']} ({n.get('name') or '?'})" for n in diff["nodes_added"]]
    lines.append("")

    lines.append(f"Nodes removed ({len(diff['nodes_removed'])}):")
    lines += [f"  - {n['address']} ({n.get('name') or '?'})" for n in diff["nodes_removed"]]
    lines.append("")

    lines.append(f"Nodes changed ({len(diff['nodes_changed'])}):")
    for c in diff["nodes_changed"]:
        change_str = ", ".join(f"{k}: {v[0]!r} -> {v[1]!r}" for k, v in c["changes"].items())
        lines.append(f"  ~ {c['address']}: {change_str}")
    lines.append("")

    lines.append(f"Edges added ({len(diff['edges_added'])}):")
    lines += [f"  + {e['from_address']} -> {e['to_address']} ({e['edge_type']})" for e in diff["edges_added"]]
    lines.append("")

    lines.append(f"Edges removed ({len(diff['edges_removed'])}):")
    lines += [f"  - {e['from_address']} -> {e['to_address']} ({e['edge_type']})" for e in diff["edges_removed"]]

    return "\n".join(lines)
