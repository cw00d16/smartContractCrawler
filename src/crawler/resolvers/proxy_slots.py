from __future__ import annotations

from web3 import Web3

from ..models import Edge, Node
from .base import CrawlContext, Resolver


def _eip1967_slot(label: str) -> str:
    """EIP-1967 slots are keccak256(label) - 1, to land outside any range
    a Solidity compiler would derive for a normal storage variable."""
    digest = int.from_bytes(Web3.keccak(text=label), "big")
    return "0x" + format(digest - 1, "064x")


# The handful of known proxy-pattern storage slots. Reading these works even
# on unverified contracts, since it's a raw eth_getStorageAt, not an ABI call.
KNOWN_SLOTS: dict[str, str] = {
    "eip1967_implementation": _eip1967_slot("eip1967.proxy.implementation"),
    "eip1967_beacon": _eip1967_slot("eip1967.proxy.beacon"),
    "eip1822_uups": Web3.to_hex(Web3.keccak(text="PROXIABLE")),
    "legacy_zos_implementation": Web3.to_hex(Web3.keccak(text="org.zeppelinos.proxy.implementation")),
}


class ProxySlotResolver(Resolver):
    name = "proxy_slots"

    def discover(self, node: Node, ctx: CrawlContext) -> list[Edge]:
        edges = []
        for slot_name, slot in KNOWN_SLOTS.items():
            try:
                target = self.rpc.get_storage_at(node.address, slot)
            except Exception:
                continue
            if not target or target.lower() == node.address.lower():
                continue
            node.is_proxy = True
            edges.append(Edge(
                chain_id=node.chain_id,
                from_address=node.address,
                to_address=target,
                edge_type=f"proxy:{slot_name}",
                source=slot_name,
            ))
        return edges
