from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import ContractSource, Edge, Node

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    chain_id INTEGER NOT NULL,
    address TEXT NOT NULL,
    depth INTEGER NOT NULL,
    name TEXT,
    verified INTEGER NOT NULL,
    is_proxy INTEGER NOT NULL,
    status TEXT NOT NULL,
    notes TEXT NOT NULL,
    PRIMARY KEY (chain_id, address)
);

CREATE TABLE IF NOT EXISTS edges (
    chain_id INTEGER NOT NULL,
    from_address TEXT NOT NULL,
    to_address TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'medium',
    PRIMARY KEY (chain_id, from_address, to_address, edge_type)
);

CREATE TABLE IF NOT EXISTS sources (
    chain_id INTEGER NOT NULL,
    address TEXT NOT NULL,
    contract_name TEXT,
    abi TEXT,
    source_files TEXT,
    compiler_version TEXT,
    source_provider TEXT NOT NULL DEFAULT 'etherscan',
    PRIMARY KEY (chain_id, address)
);

-- Persisted BFS queue: addresses discovered as edge targets but not yet
-- visited. Lets a crawl resume exactly where a prior invocation stopped
-- (max_nodes cutoff, rate-limit abort, Ctrl-C) instead of restarting the
-- traversal from the root every time. Keyed by root_address too, since one
-- GraphStore/out-dir can hold crawls of several different roots (batch mode).
CREATE TABLE IF NOT EXISTS frontier (
    chain_id INTEGER NOT NULL,
    root_address TEXT NOT NULL,
    address TEXT NOT NULL,
    depth INTEGER NOT NULL,
    queue_order INTEGER NOT NULL,
    PRIMARY KEY (chain_id, root_address, address)
);
"""


class GraphStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def upsert_node(self, node: Node) -> None:
        self.conn.execute(
            """
            INSERT INTO nodes (chain_id, address, depth, name, verified, is_proxy, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chain_id, address) DO UPDATE SET
                depth=excluded.depth, name=excluded.name, verified=excluded.verified,
                is_proxy=excluded.is_proxy, status=excluded.status, notes=excluded.notes
            """,
            (
                node.chain_id, node.address.lower(), node.depth, node.name,
                int(node.verified), int(node.is_proxy), node.status, json.dumps(node.notes),
            ),
        )
        self.conn.commit()

    def add_edge(self, edge: Edge) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO edges (chain_id, from_address, to_address, edge_type, source, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                edge.chain_id, edge.from_address.lower(), edge.to_address.lower(),
                edge.edge_type, edge.source, edge.confidence,
            ),
        )
        self.conn.commit()

    def upsert_source(self, source: ContractSource) -> None:
        self.conn.execute(
            """
            INSERT INTO sources (chain_id, address, contract_name, abi, source_files, compiler_version, source_provider)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chain_id, address) DO UPDATE SET
                contract_name=excluded.contract_name, abi=excluded.abi,
                source_files=excluded.source_files, compiler_version=excluded.compiler_version,
                source_provider=excluded.source_provider
            """,
            (
                source.chain_id, source.address.lower(), source.contract_name,
                json.dumps(source.abi), json.dumps(source.source_files), source.compiler_version,
                source.source_provider,
            ),
        )
        self.conn.commit()

    def all_nodes(self) -> list[dict]:
        return self._all("nodes")

    def all_edges(self) -> list[dict]:
        return self._all("edges")

    def all_sources(self) -> list[dict]:
        return self._all("sources")

    def known_addresses(self, chain_id: int) -> set[str]:
        """Every address already visited (present in the nodes table) for
        this chain -- used to seed the BFS 'seen' set on a resumed crawl."""
        cur = self.conn.execute("SELECT address FROM nodes WHERE chain_id = ?", (chain_id,))
        return {row[0] for row in cur.fetchall()}

    def save_frontier(self, chain_id: int, root_address: str, queue: list[tuple[str, int]]) -> None:
        """Replace the persisted BFS queue for (chain_id, root_address) with
        the given contents, preserving order."""
        root = root_address.lower()
        self.conn.execute(
            "DELETE FROM frontier WHERE chain_id = ? AND root_address = ?", (chain_id, root)
        )
        self.conn.executemany(
            """
            INSERT INTO frontier (chain_id, root_address, address, depth, queue_order)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(chain_id, root, address.lower(), depth, i) for i, (address, depth) in enumerate(queue)],
        )
        self.conn.commit()

    def load_frontier(self, chain_id: int, root_address: str) -> list[tuple[str, int]]:
        cur = self.conn.execute(
            """
            SELECT address, depth FROM frontier
            WHERE chain_id = ? AND root_address = ?
            ORDER BY queue_order
            """,
            (chain_id, root_address.lower()),
        )
        return [(row[0], row[1]) for row in cur.fetchall()]

    def _all(self, table: str) -> list[dict]:
        cur = self.conn.execute(f"SELECT * FROM {table}")
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def close(self) -> None:
        self.conn.close()
