from __future__ import annotations

from crawler import sourcify_client as sourcify_client_module
from crawler.cache import SourceCache
from crawler.sourcify_client import SourcifyClient

ADDRESS = "0xAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAa"

# Shape confirmed live against https://sourcify.dev/server/v2/contract/1/{address}
_VERIFIED_PAYLOAD = {
    "match": "exact_match",
    "abi": [{"type": "function", "name": "owner"}],
    "compilation": {
        "name": "Foo",
        "compilerVersion": "0.8.20+commit.abc123",
    },
    "sources": {
        "contracts/Foo.sol": {"content": "contract Foo {}"},
    },
}

_NOT_FOUND_PAYLOAD = {"match": None, "creationMatch": None, "runtimeMatch": None}


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _client(tmp_path) -> SourcifyClient:
    client = SourcifyClient(SourceCache(tmp_path))
    client.rate_limiter.wait = lambda: None
    return client


def test_verified_contract_is_parsed(tmp_path, monkeypatch):
    monkeypatch.setattr(sourcify_client_module.requests, "get", lambda *a, **k: _Resp(payload=_VERIFIED_PAYLOAD))
    client = _client(tmp_path)

    source = client.get_source(1, ADDRESS)

    assert source is not None
    assert source.contract_name == "Foo"
    assert source.compiler_version == "0.8.20+commit.abc123"
    assert source.abi == [{"type": "function", "name": "owner"}]
    assert source.source_files == {"contracts/Foo.sol": "contract Foo {}"}
    assert source.source_provider == "sourcify"


def test_http_404_returns_none_without_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(sourcify_client_module.requests, "get", lambda *a, **k: _Resp(status_code=404))
    client = _client(tmp_path)

    assert client.get_source(1, ADDRESS) is None


def test_null_match_field_returns_none(tmp_path, monkeypatch):
    """The real API returns HTTP 404 for unverified addresses, but also
    guard on match=None directly in case that ever changes -- a null match
    with a 200 status must never be treated as a verified result."""
    monkeypatch.setattr(sourcify_client_module.requests, "get", lambda *a, **k: _Resp(payload=_NOT_FOUND_PAYLOAD))
    client = _client(tmp_path)

    assert client.get_source(1, ADDRESS) is None


def test_empty_sources_returns_none(tmp_path, monkeypatch):
    payload = {**_VERIFIED_PAYLOAD, "sources": {}}
    monkeypatch.setattr(sourcify_client_module.requests, "get", lambda *a, **k: _Resp(payload=payload))
    client = _client(tmp_path)

    assert client.get_source(1, ADDRESS) is None


def test_unexpected_response_shape_returns_none_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(sourcify_client_module.requests, "get", lambda *a, **k: _Resp(payload={"totally": "different shape"}))
    client = _client(tmp_path)

    assert client.get_source(1, ADDRESS) is None


def test_missing_compilation_name_falls_back_to_placeholder(tmp_path, monkeypatch):
    payload = {**_VERIFIED_PAYLOAD, "compilation": {"compilerVersion": "0.8.20"}}
    monkeypatch.setattr(sourcify_client_module.requests, "get", lambda *a, **k: _Resp(payload=payload))
    client = _client(tmp_path)

    source = client.get_source(1, ADDRESS)

    assert source.contract_name == "Contract"


def test_second_call_uses_cache_not_network(tmp_path, monkeypatch):
    call_count = {"n": 0}

    def fake_get(*a, **k):
        call_count["n"] += 1
        return _Resp(payload=_VERIFIED_PAYLOAD)

    monkeypatch.setattr(sourcify_client_module.requests, "get", fake_get)
    client = _client(tmp_path)

    client.get_source(1, ADDRESS)
    client.get_source(1, ADDRESS)

    assert call_count["n"] == 1


def test_requests_only_the_needed_fields_for_chain_and_address(tmp_path, monkeypatch):
    captured = {}

    def fake_get(url, params=None, **kwargs):
        captured["url"] = url
        captured["params"] = params
        return _Resp(payload=_NOT_FOUND_PAYLOAD, status_code=404)

    monkeypatch.setattr(sourcify_client_module.requests, "get", fake_get)
    client = _client(tmp_path)

    client.get_source(100, ADDRESS)

    assert captured["url"] == f"https://sourcify.dev/server/v2/contract/100/{ADDRESS}"
    assert captured["params"] == {"fields": "abi,compilation,sources"}
