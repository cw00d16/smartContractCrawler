from __future__ import annotations

import json
import re
from pathlib import Path

from .graph_store import GraphStore

_UNSAFE_SEGMENT_CHARS = re.compile(r"[^A-Za-z0-9_.\-]")


def _safe_relative_path(name: str) -> Path:
    """Etherscan-supplied filenames are untrusted: real verified contracts
    have shown up with absolute paths baked in from the original author's
    machine (e.g. "/Users/x/Repositories/.../Token.sol"). A naive join lets
    such a string escape the intended output directory entirely -- Path
    joining with a leading "/" discards the base path outright. Sanitize
    per path segment and drop anything that isn't a plain relative component."""
    segments = re.split(r"[\\/]+", name)
    safe_segments = [
        _UNSAFE_SEGMENT_CHARS.sub("_", seg)
        for seg in segments
        if seg not in ("", ".", "..") and not re.fullmatch(r"[A-Za-z]:", seg)
    ]
    return Path(*safe_segments) if safe_segments else Path("_unnamed.sol")


def export_graph_json(store: GraphStore, path: Path) -> None:
    nodes = store.all_nodes()
    for n in nodes:
        n["notes"] = json.loads(n["notes"])
    edges = store.all_edges()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"nodes": nodes, "edges": edges}, indent=2))


def export_source_bundle(store: GraphStore, out_dir: Path) -> None:
    """One directory per contract: abi.json, metadata.json, and the flattened
    source files -- the artifact meant to be handed to the obligation-diff
    tool downstream."""
    for source in store.all_sources():
        contract_dir = out_dir / str(source["chain_id"]) / source["address"]
        contract_dir.mkdir(parents=True, exist_ok=True)

        (contract_dir / "abi.json").write_text(source["abi"])
        metadata = {
            "contract_name": source["contract_name"],
            "compiler_version": source["compiler_version"],
            "address": source["address"],
            "chain_id": source["chain_id"],
            "source_provider": source["source_provider"],
        }
        (contract_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

        files = json.loads(source["source_files"])
        files_dir = (contract_dir / "src").resolve()
        for filename, content in files.items():
            file_path = (files_dir / _safe_relative_path(filename)).resolve()
            # Defense in depth: refuse to write anywhere the sanitizer above
            # didn't intend, even if some future edge case slips past it.
            if files_dir not in file_path.parents:
                raise ValueError(f"refusing to write outside source bundle: {filename!r} -> {file_path}")
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)
