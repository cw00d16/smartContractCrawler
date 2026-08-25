from __future__ import annotations

import json
from pathlib import Path

import pytest

from crawler import export
from crawler.export import _safe_relative_path
from crawler.graph_store import GraphStore
from crawler.models import ContractSource


# --- _safe_relative_path: the fix for the real path-traversal bug found
# testing against USDC's real verified source, which embeds the original
# author's absolute build path ("/Users/x/Repositories/.../Token.sol").
# Path("/base") / "/Users/x/..." silently discards "/base" entirely in
# plain pathlib -- these tests pin down that this can no longer happen.

def test_plain_filename_is_unchanged():
    assert _safe_relative_path("Token.sol") == Path("Token.sol")


def test_absolute_unix_path_is_stripped_to_relative():
    result = _safe_relative_path("/Users/aloysius.chan/Repositories/circlefin/contracts/v2/FiatTokenV2_2.sol")
    assert not result.is_absolute()
    assert str(result) == "Users/aloysius.chan/Repositories/circlefin/contracts/v2/FiatTokenV2_2.sol"


def test_parent_traversal_segments_are_dropped():
    result = _safe_relative_path("../../etc/passwd")
    assert not result.is_absolute()
    assert ".." not in result.parts


def test_windows_style_absolute_path_is_stripped():
    result = _safe_relative_path("C:\\Users\\foo\\Bar.sol")
    assert not result.is_absolute()
    assert "C:" not in result.parts


def test_unsafe_characters_are_replaced():
    result = _safe_relative_path("weird name?.sol")
    assert all(c.isalnum() or c in "_.-/" for c in str(result))


def test_empty_name_falls_back_to_placeholder():
    result = _safe_relative_path("")
    assert str(result) == "_unnamed.sol"


def test_result_never_absolute_regardless_of_input():
    for name in ["/a/b/c.sol", "//weird///double/slash.sol", "\\\\windows\\\\double\\\\.sol", "..", "."]:
        assert not _safe_relative_path(name).is_absolute()


# --- export_source_bundle integration: confirm writes stay inside out_dir
# even given the exact kind of malicious/absolute filename Etherscan served.

def _store_with_source(tmp_path, source_files: dict) -> GraphStore:
    store = GraphStore(tmp_path / "graph.db")
    store.upsert_source(ContractSource(
        chain_id=1, address="0xabc", contract_name="Token",
        abi=[{"type": "function", "name": "owner"}],
        source_files=source_files,
        compiler_version="v0.8.20",
    ))
    return store


def test_export_contains_absolute_path_write_within_out_dir(tmp_path):
    malicious_filename = "/Users/someone/Repositories/private-repo/contracts/Token.sol"
    store = _store_with_source(tmp_path / "db", {malicious_filename: "contract Token {}"})
    out_dir = tmp_path / "out"

    export.export_source_bundle(store, out_dir)

    written_files = list(out_dir.rglob("*.sol"))
    assert len(written_files) == 1
    for f in written_files:
        assert out_dir.resolve() in f.resolve().parents
    assert written_files[0].read_text() == "contract Token {}"


def test_export_writes_abi_and_metadata(tmp_path):
    store = _store_with_source(tmp_path / "db", {"Token.sol": "contract Token {}"})
    out_dir = tmp_path / "out"

    export.export_source_bundle(store, out_dir)

    contract_dir = out_dir / "1" / "0xabc"
    assert (contract_dir / "abi.json").exists()
    assert json.loads((contract_dir / "metadata.json").read_text())["contract_name"] == "Token"
    assert (contract_dir / "src" / "Token.sol").read_text() == "contract Token {}"


def test_export_refuses_write_that_escapes_sandbox(tmp_path, monkeypatch):
    """Defense-in-depth: even if the sanitizer were bypassed, the resolved-path
    containment check must still refuse to write outside the bundle dir."""
    store = _store_with_source(tmp_path / "db", {"whatever.sol": "contract Token {}"})
    out_dir = tmp_path / "out"

    monkeypatch.setattr(export, "_safe_relative_path", lambda name: Path("../../escaped.sol"))

    with pytest.raises(ValueError):
        export.export_source_bundle(store, out_dir)

    assert not any(tmp_path.rglob("escaped.sol"))  # raised before any write occurred


def test_export_graph_json_shape(tmp_path):
    store = GraphStore(tmp_path / "graph.db")
    from crawler.models import Edge, Node
    store.upsert_node(Node(chain_id=1, address="0xabc", depth=0, status="resolved"))
    store.add_edge(Edge(chain_id=1, from_address="0xabc", to_address="0xdef", edge_type="abi:owner", source="owner"))

    out_path = tmp_path / "graph.json"
    export.export_graph_json(store, out_path)

    data = json.loads(out_path.read_text())
    assert len(data["nodes"]) == 1
    assert data["nodes"][0]["notes"] == []  # notes stored as JSON string, decoded back to a list
    assert len(data["edges"]) == 1
