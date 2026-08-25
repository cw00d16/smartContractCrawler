from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from ..models import ChainConfig, ContractSource, Edge, Node
from ..rpc_client import RpcClient


@dataclass
class CrawlContext:
    chain: ChainConfig
    source: Optional[ContractSource]


class Resolver(ABC):
    """One discovery strategy. Each resolver runs independently against every
    visited node; edges from all resolvers feed the same traversal queue."""

    name: str = "resolver"

    def __init__(self, rpc: RpcClient):
        self.rpc = rpc

    @abstractmethod
    def discover(self, node: Node, ctx: CrawlContext) -> list[Edge]:
        ...
