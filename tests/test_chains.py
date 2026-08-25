from __future__ import annotations

from crawler.chains import CHAIN_NAMES, get_chain


def test_reads_env_at_call_time_not_import_time(monkeypatch):
    """Regression test: get_chain() must read os.environ when called, not
    when the module is imported. The original CHAINS-as-module-level-dict
    design built ChainConfigs at import time, so a key set via load_dotenv()
    (which necessarily runs after the import) was silently never picked up."""
    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)
    assert get_chain("mainnet").explorer_api_key == ""

    monkeypatch.setenv("ETHERSCAN_API_KEY", "test-key-123")
    assert get_chain("mainnet").explorer_api_key == "test-key-123"


def test_rpc_url_env_override(monkeypatch):
    monkeypatch.setenv("MAINNET_RPC_URL", "https://example-rpc.test")
    assert get_chain("mainnet").rpc_url == "https://example-rpc.test"


def test_rpc_url_default_when_unset(monkeypatch):
    monkeypatch.delenv("MAINNET_RPC_URL", raising=False)
    chain = get_chain("mainnet")
    assert chain.rpc_url  # has some sensible default
    assert chain.rpc_url.startswith("https://")


def test_chain_names_cover_mainnet_gnosis_and_polygon():
    assert set(CHAIN_NAMES) == {"mainnet", "gnosis", "polygon"}


def test_chain_ids_are_correct():
    assert get_chain("mainnet").chain_id == 1
    assert get_chain("gnosis").chain_id == 100
    assert get_chain("polygon").chain_id == 137


def test_polygon_rpc_url_env_override(monkeypatch):
    monkeypatch.setenv("POLYGON_RPC_URL", "https://example-polygon-rpc.test")
    assert get_chain("polygon").rpc_url == "https://example-polygon-rpc.test"


def test_polygon_rpc_url_default_when_unset(monkeypatch):
    monkeypatch.delenv("POLYGON_RPC_URL", raising=False)
    chain = get_chain("polygon")
    assert chain.rpc_url  # has some sensible default
    assert chain.rpc_url.startswith("https://")
