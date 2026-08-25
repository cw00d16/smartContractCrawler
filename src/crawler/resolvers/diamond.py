from __future__ import annotations

from ..models import Edge, Node
from .base import CrawlContext, Resolver


class DiamondLoupeResolver(Resolver):
    """EIP-2535 Diamonds keep the function-to-facet mapping in a mapping, not
    a fixed slot, so neither other resolver can see it. Detection is cheap:
    if the ABI exposes facets(), call the Diamond Loupe interface directly."""

    name = "diamond_loupe"

    def discover(self, node: Node, ctx: CrawlContext) -> list[Edge]:
        if not ctx.source or not ctx.source.abi:
            return []
        fn_names = {fn.get("name") for fn in ctx.source.abi if fn.get("type") == "function"}
        if "facets" not in fn_names:
            return []

        try:
            facets = self.rpc.call_diamond_facets(node.address)
        except Exception:
            return []

        edges = []
        for facet_address, selectors in facets:
            if facet_address.lower() == node.address.lower():
                continue
            edges.append(Edge(
                chain_id=node.chain_id,
                from_address=node.address,
                to_address=facet_address,
                edge_type="diamond:facet",
                source=f"{len(selectors)} selectors",
            ))
        return edges
