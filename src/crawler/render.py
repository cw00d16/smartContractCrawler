from __future__ import annotations

import json
import re
from pathlib import Path

_LABEL_UNSAFE = re.compile(r'["\[\]]')


def _sanitize(text: str) -> str:
    return _LABEL_UNSAFE.sub("", text)


def _short_address(address: str) -> str:
    return f"{address[:6]}...{address[-4:]}" if len(address) > 12 else address


def render_mermaid(graph_json_path: Path) -> str:
    """Render a graph.json (or snapshot) as a Mermaid flowchart for quick
    human eyeballing. Edge targets that fall outside the exported node set
    (e.g. cut off by --max-nodes) are still shown, as minimal 'external'
    nodes -- exactly the "here's what's still opaque" signal the crawler is
    meant to surface, not silently dropped."""
    data = json.loads(graph_json_path.read_text())
    nodes = data["nodes"]
    edges = data["edges"]

    node_id: dict[str, str] = {}
    declarations: list[str] = []

    for n in nodes:
        nid = f"n{len(node_id)}"
        node_id[n["address"]] = nid
        name = n.get("name") or "?"
        css_class = ""
        if n.get("status") == "unresolved":
            css_class = ":::unresolved"
        elif n.get("is_proxy"):
            css_class = ":::proxy"
        label = f"{_sanitize(name)}<br/>{_short_address(n['address'])}"
        declarations.append(f'    {nid}["{label}"]{css_class}')

    edge_lines: list[str] = []
    for e in edges:
        for addr in (e["from_address"], e["to_address"]):
            if addr not in node_id:
                nid = f"n{len(node_id)}"
                node_id[addr] = nid
                declarations.append(f'    {nid}["{_short_address(addr)}"]:::external')

        arrow = "-.->" if e.get("confidence") == "low" else "-->"
        edge_label = _sanitize(e["edge_type"])
        edge_lines.append(f'    {node_id[e["from_address"]]} {arrow}|"{edge_label}"| {node_id[e["to_address"]]}')

    lines = ["flowchart LR"]
    lines.extend(declarations)
    lines.extend(edge_lines)
    lines.append("    classDef proxy fill:#e0d4ff,stroke:#7a4fd6")
    lines.append("    classDef unresolved fill:#f0f0f0,stroke:#999,stroke-dasharray: 4 3")
    lines.append("    classDef external fill:#fff3cd,stroke:#d4a017,stroke-dasharray: 2 2")
    return "\n".join(lines)
