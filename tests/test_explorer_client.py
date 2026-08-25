from __future__ import annotations

import pytest

from crawler import explorer_client as explorer_client_module
from crawler.cache import SourceCache
from crawler.explorer_client import ExplorerClient, ExplorerRateLimitError, _split_source_files
from crawler.models import ChainConfig

ADDRESS = "0xAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAa"


def _chain() -> ChainConfig:
    return ChainConfig(
        name="test", chain_id=1, rpc_url="", explorer_api_base="http://fake",
        explorer_api_key="x", rate_limit_per_sec=1000,
    )


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400 and self.status_code != 429:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _client(tmp_path, get_impl):
    client = ExplorerClient(_chain(), SourceCache(tmp_path))
    client.rate_limiter.wait = lambda: None  # skip real pacing in unit tests
    return client, get_impl


# --- _split_source_files: Etherscan's several source-format quirks

def test_single_file_source_passthrough():
    files = _split_source_files("pragma solidity ^0.8.0; contract Foo {}", "Foo")
    assert files == {"Foo.sol": "pragma solidity ^0.8.0; contract Foo {}"}


def test_double_brace_wrapped_multi_file_source():
    raw = '{{"sources": {"Foo.sol": {"content": "contract Foo {}"}}}}'
    files = _split_source_files(raw, "Foo")
    assert files == {"Foo.sol": "contract Foo {}"}


def test_single_brace_multi_file_source():
    raw = '{"sources": {"Foo.sol": {"content": "contract Foo {}"}}}'
    files = _split_source_files(raw, "Foo")
    assert files == {"Foo.sol": "contract Foo {}"}


def test_malformed_json_falls_back_to_single_file():
    raw = "{not valid json"
    files = _split_source_files(raw, "Foo")
    assert files == {"Foo.sol": raw}


# --- rate-limit detection: the real gap found testing against Etherscan,
# which often signals rejection as HTTP 200 + NOTOK rather than a real 429.

def test_http_429_raises_rate_limit_error(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, None)
    monkeypatch.setattr(explorer_client_module.requests, "get", lambda *a, **k: _Resp(status_code=429))

    with pytest.raises(ExplorerRateLimitError):
        client.get_source(ADDRESS)


def test_soft_notok_rate_limit_message_raises(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, None)
    payload = {"status": "0", "message": "NOTOK", "result": "Max rate limit reached"}
    monkeypatch.setattr(explorer_client_module.requests, "get", lambda *a, **k: _Resp(payload=payload))

    with pytest.raises(ExplorerRateLimitError):
        client.get_source(ADDRESS)


def test_notok_for_other_reasons_does_not_raise_rate_limit(tmp_path, monkeypatch):
    payload = {"status": "0", "message": "NOTOK", "result": "Invalid API Key"}
    monkeypatch.setattr(explorer_client_module.requests, "get", lambda *a, **k: _Resp(payload=payload))
    client, _ = _client(tmp_path, None)

    # Should not raise -- falls through to normal parsing, which returns None
    # (no usable result), not a fatal abort.
    assert client.get_source(ADDRESS) is None


def test_rate_limited_response_is_never_cached(tmp_path, monkeypatch):
    payload = {"status": "0", "message": "NOTOK", "result": "Max rate limit reached"}
    monkeypatch.setattr(explorer_client_module.requests, "get", lambda *a, **k: _Resp(payload=payload))
    client, _ = _client(tmp_path, None)

    with pytest.raises(ExplorerRateLimitError):
        client.get_source(ADDRESS)

    assert client.cache.get(1, ADDRESS) is None


# --- normal parsing + caching behavior

def test_unverified_contract_returns_none(tmp_path, monkeypatch):
    payload = {"status": "1", "message": "OK", "result": [{"SourceCode": "", "ABI": "Contract source code not verified"}]}
    monkeypatch.setattr(explorer_client_module.requests, "get", lambda *a, **k: _Resp(payload=payload))
    client, _ = _client(tmp_path, None)

    assert client.get_source(ADDRESS) is None


def test_verified_contract_is_parsed(tmp_path, monkeypatch):
    payload = {
        "status": "1", "message": "OK",
        "result": [{
            "SourceCode": "contract Foo {}",
            "ABI": '[{"type": "function", "name": "owner"}]',
            "ContractName": "Foo",
            "CompilerVersion": "v0.8.20",
        }],
    }
    monkeypatch.setattr(explorer_client_module.requests, "get", lambda *a, **k: _Resp(payload=payload))
    client, _ = _client(tmp_path, None)

    source = client.get_source(ADDRESS)

    assert source is not None
    assert source.contract_name == "Foo"
    assert source.abi == [{"type": "function", "name": "owner"}]


def test_second_call_uses_cache_not_network(tmp_path, monkeypatch):
    payload = {
        "status": "1", "message": "OK",
        "result": [{"SourceCode": "contract Foo {}", "ABI": "[]", "ContractName": "Foo", "CompilerVersion": "v0.8.20"}],
    }
    call_count = {"n": 0}

    def fake_get(*a, **k):
        call_count["n"] += 1
        return _Resp(payload=payload)

    monkeypatch.setattr(explorer_client_module.requests, "get", fake_get)
    client, _ = _client(tmp_path, None)

    client.get_source(ADDRESS)
    client.get_source(ADDRESS)

    assert call_count["n"] == 1
