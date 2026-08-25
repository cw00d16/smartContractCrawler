from __future__ import annotations

import json
from typing import Optional

import requests

from .cache import SourceCache
from .models import ChainConfig, ContractSource
from .ratelimit import RateLimiter


class ExplorerRateLimitError(Exception):
    """Raised when Etherscan rejects a request for being rate-limited. This
    is fatal for the crawl (see crawl.py) rather than a per-node failure --
    once the API starts rejecting us, hammering the rest of the queue at the
    same pace helps no one."""


class ExplorerClient:
    def __init__(self, chain: ChainConfig, cache: SourceCache, rate_limiter: Optional[RateLimiter] = None):
        self.chain = chain
        self.cache = cache
        self.rate_limiter = rate_limiter or RateLimiter(chain.rate_limit_per_sec)

    def get_source(self, address: str) -> Optional[ContractSource]:
        cached = self.cache.get(self.chain.chain_id, address)
        if cached is None:
            cached = self._fetch(address)
            # Only cache once we know it's a real answer, not a rate-limit
            # rejection -- caching the latter would permanently poison the
            # cache into believing a real, verified contract is unverified.
            self.cache.set(self.chain.chain_id, address, cached)
        return self._parse(address, cached)

    def _fetch(self, address: str) -> dict:
        self.rate_limiter.wait()
        params = {
            "chainid": self.chain.chain_id,
            "module": "contract",
            "action": "getsourcecode",
            "address": address,
            "apikey": self.chain.explorer_api_key,
        }
        resp = requests.get(self.chain.explorer_api_base, params=params, timeout=self.chain.request_timeout)
        if resp.status_code == 429:
            raise ExplorerRateLimitError(f"HTTP 429 from explorer API for {address}")
        resp.raise_for_status()
        payload = resp.json()
        # Etherscan often signals rate-limiting as HTTP 200 with a NOTOK
        # body instead of a real 429 -- must check the body, not just status.
        if payload.get("message") == "NOTOK" and "rate limit" in str(payload.get("result", "")).lower():
            raise ExplorerRateLimitError(f"Explorer API rate limit reached while fetching {address}: {payload.get('result')}")
        return payload

    def _parse(self, address: str, payload: dict) -> Optional[ContractSource]:
        results = payload.get("result")
        if not results or not isinstance(results, list):
            return None
        result = results[0]
        raw_source = result.get("SourceCode", "")
        if not raw_source:
            return None
        try:
            abi = json.loads(result.get("ABI", ""))
        except (json.JSONDecodeError, TypeError):
            return None
        contract_name = result.get("ContractName", "") or "Contract"
        return ContractSource(
            chain_id=self.chain.chain_id,
            address=address,
            contract_name=contract_name,
            abi=abi,
            source_files=_split_source_files(raw_source, contract_name),
            compiler_version=result.get("CompilerVersion", ""),
        )


def _split_source_files(raw_source: str, fallback_name: str) -> dict[str, str]:
    """Etherscan wraps multi-file (standard-json-input) sources in an extra
    pair of braces; single-file contracts come back as plain Solidity text."""
    text = raw_source.strip()
    if text.startswith("{{") and text.endswith("}}"):
        text = text[1:-1]
    if not text.startswith("{"):
        return {f"{fallback_name}.sol": raw_source}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {f"{fallback_name}.sol": raw_source}
    sources = parsed.get("sources", parsed)
    files = {
        name: (content.get("content", "") if isinstance(content, dict) else str(content))
        for name, content in sources.items()
    }
    return files or {f"{fallback_name}.sol": raw_source}
