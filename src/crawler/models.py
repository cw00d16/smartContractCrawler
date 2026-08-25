from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ChainConfig:
    name: str
    chain_id: int
    rpc_url: str
    explorer_api_base: str
    explorer_api_key: str
    rate_limit_per_sec: float = 4.0  # Etherscan free tier caps at 5/s; keep margin for clock jitter
    request_timeout: int = 15


@dataclass
class Node:
    chain_id: int
    address: str
    depth: int = 0
    name: Optional[str] = None
    verified: bool = False
    is_proxy: bool = False
    status: str = "pending"  # pending | resolved | unresolved
    notes: list[str] = field(default_factory=list)


@dataclass
class Edge:
    chain_id: int
    from_address: str
    to_address: str
    edge_type: str  # e.g. "proxy:eip1967_implementation", "abi:processor", "diamond:facet"
    source: str      # the slot name or function name that produced this edge
    confidence: str = "medium"  # "high" | "medium" | "low" -- see confidence.py


@dataclass
class ContractSource:
    chain_id: int
    address: str
    contract_name: str
    abi: list[dict]
    source_files: dict[str, str]  # filename -> content
    compiler_version: str
    source_provider: str = "etherscan"  # "etherscan" | "sourcify" -- provenance for downstream trust/diffing
