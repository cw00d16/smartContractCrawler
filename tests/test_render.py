from __future__ import annotations

import json

from crawler.render import render_mermaid

ROOT = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
IMPL = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
EXTERNAL = "0xccccccccccccccccccccccccccccccccccccccc"[:42]


def _node(address, **kwargs):
    base = {"address": address, "name": None, "status": "resolved", "is_proxy": 0}
    base.update(kwargs)
    return base


def _write_graph(tmp_path, nodes, edges):
    path = tmp_path / "graph.json"
    path.write_text(json.dumps({"nodes": nodes, "edges": edges}))
    return path


def test_renders_flowchart_header(tmp_path):
    path = _write_graph(tmp_path, [_node(ROOT)], [])
    output = render_mermaid(path)
    assert output.startswith("flowchart LR")


def test_includes_node_name_and_short_address(tmp_path):
    path = _write_graph(tmp_path, [_node(ROOT, name="FiatTokenProxy")], [])
    output = render_mermaid(path)
    assert "FiatTokenProxy" in output
    assert ROOT[:6] in output


def test_proxy_node_gets_proxy_class(tmp_path):
    path = _write_graph(tmp_path, [_node(ROOT, is_proxy=1)], [])
    output = render_mermaid(path)
    assert ":::proxy" in output


def test_unresolved_node_gets_unresolved_class(tmp_path):
    path = _write_graph(tmp_path, [_node(ROOT, status="unresolved")], [])
    output = render_mermaid(path)
    assert ":::unresolved" in output


def test_edge_renders_between_declared_nodes(tmp_path):
    path = _write_graph(
        tmp_path,
        [_node(ROOT), _node(IMPL)],
        [{"from_address": ROOT, "to_address": IMPL, "edge_type": "proxy:eip1967_implementation", "confidence": "high"}],
    )
    output = render_mermaid(path)
    assert "-->" in output
    assert "eip1967_implementation" in output


def test_low_confidence_edge_uses_dotted_arrow(tmp_path):
    path = _write_graph(
        tmp_path,
        [_node(ROOT), _node(IMPL)],
        [{"from_address": ROOT, "to_address": IMPL, "edge_type": "abi:owner", "confidence": "low"}],
    )
    output = render_mermaid(path)
    assert "-.->" in output


def test_edge_to_address_outside_node_set_gets_external_node(tmp_path):
    path = _write_graph(
        tmp_path,
        [_node(ROOT)],
        [{"from_address": ROOT, "to_address": EXTERNAL, "edge_type": "abi:pool", "confidence": "medium"}],
    )
    output = render_mermaid(path)
    assert ":::external" in output
    assert EXTERNAL[:6] in output


def test_quotes_and_brackets_in_names_are_stripped(tmp_path):
    path = _write_graph(tmp_path, [_node(ROOT, name='Weird"Name[x]')], [])
    output = render_mermaid(path)
    assert 'WeirdNamex' in output
    assert '"Weird"Name[x]"' not in output


def test_empty_graph_still_produces_valid_header(tmp_path):
    path = _write_graph(tmp_path, [], [])
    output = render_mermaid(path)
    assert output.startswith("flowchart LR")
