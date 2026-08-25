from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


class SourceCache:
    """Disk cache of raw getsourcecode responses, keyed by (chain_id, address).
    Never refetch a contract already pulled in a prior run."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, chain_id: int, address: str) -> Path:
        chain_dir = self.root / str(chain_id)
        chain_dir.mkdir(parents=True, exist_ok=True)
        return chain_dir / f"{address.lower()}.json"

    def get(self, chain_id: int, address: str) -> Optional[dict]:
        path = self._path(chain_id, address)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def set(self, chain_id: int, address: str, data: dict) -> None:
        self._path(chain_id, address).write_text(json.dumps(data))
