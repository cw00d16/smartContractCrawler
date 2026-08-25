from __future__ import annotations

import os

from .models import ChainConfig

ETHERSCAN_V2_BASE = "https://api.etherscan.io/v2/api"

# Static per-chain metadata only -- no env reads at import time, so this
# module can be imported before .env is loaded without baking in an empty key.
_CHAIN_META = {
    "mainnet": {"chain_id": 1, "rpc_env": "MAINNET_RPC_URL", "rpc_default": "https://ethereum.publicnode.com"},
    "gnosis": {"chain_id": 100, "rpc_env": "GNOSIS_RPC_URL", "rpc_default": "https://rpc.gnosischain.com"},
    "polygon": {"chain_id": 137, "rpc_env": "POLYGON_RPC_URL", "rpc_default": "https://polygon.publicnode.com"},
}

CHAIN_NAMES: tuple[str, ...] = tuple(_CHAIN_META)


def get_chain(name: str) -> ChainConfig:
    """Build a ChainConfig from current env vars. Call this only after
    load_dotenv() has run, since it reads os.environ at call time."""
    meta = _CHAIN_META[name]
    return ChainConfig(
        name=name,
        chain_id=meta["chain_id"],
        rpc_url=os.getenv(meta["rpc_env"], meta["rpc_default"]),
        explorer_api_base=ETHERSCAN_V2_BASE,
        explorer_api_key=os.getenv("ETHERSCAN_API_KEY", ""),
    )
