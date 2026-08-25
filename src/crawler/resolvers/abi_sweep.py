from __future__ import annotations

from ..models import Edge, Node
from .base import CrawlContext, Resolver

_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


class AbiSweepResolver(Resolver):
    """Heuristic child-contract discovery: call every zero-arg view/pure
    function that returns a single address, and follow whatever comes back.
    Over-collects (owner(), etc.) by design -- filtering noise is cheaper
    than missing a real dependency."""

    name = "abi_sweep"

    def discover(self, node: Node, ctx: CrawlContext) -> list[Edge]:
        if not ctx.source or not ctx.source.abi:
            return []
        return self.sweep_via(node.chain_id, node.address, ctx.source.abi)

    def sweep_via(
        self,
        chain_id: int,
        call_address: str,
        abi: list[dict],
        namespace: str = "abi",
    ) -> list[Edge]:
        """Call every zero-arg address-returning getter in `abi` AT
        `call_address`. Split out from discover() so a proxy's delegatecalled
        implementation ABI can be swept against the *proxy's* address --
        storage-reliant getters like owner() only return a meaningful value
        when invoked through the proxy, since that's whose storage they read."""
        edges = []
        for fn in abi:
            if fn.get("type") != "function" or fn.get("inputs"):
                continue
            outputs = fn.get("outputs") or []
            if len(outputs) != 1 or outputs[0].get("type") != "address":
                continue
            if fn.get("stateMutability") not in ("view", "pure"):
                continue

            fn_name = fn["name"]
            try:
                target = self.rpc.call_zero_arg_address_getter(call_address, fn_name)
            except Exception:
                continue
            if not target or target == _ZERO_ADDRESS or target.lower() == call_address.lower():
                continue

            edges.append(Edge(
                chain_id=chain_id,
                from_address=call_address,
                to_address=target,
                edge_type=f"{namespace}:{fn_name}",
                source=fn_name,
            ))
        return edges
