from __future__ import annotations

from .models import Edge

# Function names commonly used for access-control pointers rather than
# meaningful business-logic dependencies. Matched as a substring, case
# insensitive, against the getter name that produced an ABI-sweep edge --
# deliberately loose, since the goal is to de-emphasize likely noise for a
# downstream reader, not to silently drop it (the edge is still recorded).
_LOW_CONFIDENCE_NAME_PATTERNS = (
    "owner",
    "admin",
    "guardian",
    "pauser",
    "minter",
    "blacklist",
    "governance",
    "deployer",
)


def classify_edge_confidence(edge: Edge) -> str:
    """high: protocol-standard discovery (proxy slot, Diamond Loupe) -- not a
    name guess, so it's as certain as the on-chain data itself.
    medium: ABI-sweep getter whose name doesn't look like an access-control
    pointer -- plausible real dependency, still a heuristic.
    low: ABI-sweep getter whose name looks like an access-control pointer
    (owner/admin/etc.), or a bytecode PUSH20 constant -- the two least
    certain signals in the whole pipeline."""
    family = edge.edge_type.split(":", 1)[0]

    if family == "proxy" or edge.edge_type == "diamond:facet":
        return "high"
    if family == "bytecode":
        return "low"
    if family in ("abi", "abi_via_proxy"):
        fn_name = edge.source.lower()
        if any(pattern in fn_name for pattern in _LOW_CONFIDENCE_NAME_PATTERNS):
            return "low"
        return "medium"
    return "medium"
