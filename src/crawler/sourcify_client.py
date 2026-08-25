from __future__ import annotations

from typing import Optional

import requests

from .cache import SourceCache
from .models import ContractSource
from .ratelimit import RateLimiter

SOURCIFY_API_BASE = "https://sourcify.dev/server"


class SourcifyClient:
    """Fallback verification source, used only when Etherscan has no source
    for an address. Sourcify is free, keyless, and chain-agnostic -- some
    contracts unverified on Etherscan (wrong compiler settings submitted,
    verification never attempted there, etc.) are verified on Sourcify
    because it was populated independently, often by the deploying tooling
    itself (e.g. Hardhat/Foundry plugins that auto-submit on deploy).

    Uses Sourcify's APIv2 (GET /v2/contract/{chainId}/{address}), confirmed
    directly against the live API rather than assumed from memory -- the
    older /files/any/{chain}/{address} endpoint this was first written
    against has since been retired."""

    def __init__(self, cache: SourceCache, rate_limiter: Optional[RateLimiter] = None, timeout: int = 15):
        self.cache = cache
        # No published rate limit for the free Sourcify API, but stay polite
        # to a service we're using without a key rather than assuming no limit.
        self.rate_limiter = rate_limiter or RateLimiter(calls_per_second=5.0)
        self.timeout = timeout

    def get_source(self, chain_id: int, address: str) -> Optional[ContractSource]:
        cached = self.cache.get(chain_id, address)
        if cached is None:
            cached = self._fetch(chain_id, address)
            self.cache.set(chain_id, address, cached)
        return self._parse(chain_id, address, cached)

    def _fetch(self, chain_id: int, address: str) -> dict:
        self.rate_limiter.wait()
        url = f"{SOURCIFY_API_BASE}/v2/contract/{chain_id}/{address}"
        resp = requests.get(url, params={"fields": "abi,compilation,sources"}, timeout=self.timeout)
        if resp.status_code == 404:
            return {"_not_found": True}  # not verified on Sourcify -- a normal, expected outcome
        resp.raise_for_status()
        return resp.json()

    def _parse(self, chain_id: int, address: str, payload: dict) -> Optional[ContractSource]:
        # Parsing is defensive throughout: if Sourcify's response shape ever
        # changes again, degrade to "nothing found" rather than raise -- this
        # is a best-effort fallback, not a required path, so silent
        # non-discovery is the safe failure mode.
        try:
            if payload.get("_not_found") or payload.get("match") is None:
                return None

            sources = payload.get("sources") or {}
            source_files = {
                name: (info.get("content", "") if isinstance(info, dict) else str(info))
                for name, info in sources.items()
            }
            if not source_files:
                return None

            compilation = payload.get("compilation") or {}
            return ContractSource(
                chain_id=chain_id,
                address=address,
                contract_name=compilation.get("name") or "Contract",
                abi=payload.get("abi") or [],
                source_files=source_files,
                compiler_version=compilation.get("compilerVersion", ""),
                source_provider="sourcify",
            )
        except Exception:
            return None
