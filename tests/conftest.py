from __future__ import annotations

import pytest

from crawler.explorer_client import ExplorerRateLimitError
from crawler.models import ContractSource

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


class FakeRpc:
    """Test double for RpcClient. Canned answers are keyed by lowercase
    address so tests don't have to worry about checksum casing."""

    def __init__(self, storage=None, getters=None, facets=None, code=None):
        self.storage = storage or {}   # {(address_lower, slot): address_or_None}
        self.getters = getters or {}   # {(address_lower, fn_name): address_or_None}
        self.facets = facets or {}     # {address_lower: [(facet_addr, [selectors])]}
        self.code = code or {}         # {address_lower: bytes}
        self.storage_calls: list[tuple[str, str]] = []
        self.getter_calls: list[tuple[str, str]] = []

    def checksum(self, address: str) -> str:
        return address

    def get_storage_at(self, address: str, slot: str):
        self.storage_calls.append((address, slot))
        return self.storage.get((address.lower(), slot))

    def call_zero_arg_address_getter(self, address: str, fn_name: str):
        self.getter_calls.append((address, fn_name))
        key = (address.lower(), fn_name)
        if key not in self.getters:
            return ZERO_ADDRESS
        value = self.getters[key]
        if isinstance(value, Exception):
            raise value
        return value

    def call_diamond_facets(self, address: str):
        return self.facets.get(address.lower(), [])

    def get_code(self, address: str) -> bytes:
        return self.code.get(address.lower(), b"")


class FakeExplorer:
    """Test double for ExplorerClient. `raise_on` simulates a rate-limit
    rejection for specific addresses, to test the fatal-abort path."""

    def __init__(self, sources=None, raise_on=None):
        self.sources = sources or {}
        self.raise_on = {a.lower() for a in (raise_on or [])}
        self.calls: list[str] = []

    def get_source(self, address: str):
        self.calls.append(address)
        if address.lower() in self.raise_on:
            raise ExplorerRateLimitError(f"simulated rate limit for {address}")
        return self.sources.get(address.lower())


class FakeSourcify:
    """Test double for SourcifyClient."""

    def __init__(self, sources=None):
        self.sources = sources or {}  # {address_lower: ContractSource}
        self.calls: list[tuple[int, str]] = []

    def get_source(self, chain_id: int, address: str):
        self.calls.append((chain_id, address))
        return self.sources.get(address.lower())


def address_getter_abi(*fn_names: str) -> list[dict]:
    return [
        {
            "type": "function",
            "name": name,
            "inputs": [],
            "outputs": [{"name": "", "type": "address"}],
            "stateMutability": "view",
        }
        for name in fn_names
    ]


def make_source(address: str, contract_name: str = "Contract", fn_names: tuple = (), source_files=None) -> ContractSource:
    return ContractSource(
        chain_id=1,
        address=address,
        contract_name=contract_name,
        abi=address_getter_abi(*fn_names),
        source_files=source_files or {f"{contract_name}.sol": f"contract {contract_name} {{}}"},
        compiler_version="v0.8.20",
    )


@pytest.fixture
def fake_rpc():
    return FakeRpc()


@pytest.fixture
def fake_explorer():
    return FakeExplorer()
