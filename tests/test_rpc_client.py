from __future__ import annotations

from web3 import Web3

from crawler.rpc_client import RpcClient

# RpcClient wraps Web3(HTTPProvider(...)), which doesn't touch the network
# until a method is actually called -- so these tests can construct a real
# RpcClient against a bogus URL and just monkeypatch the underlying eth
# methods, exercising RpcClient's own address-decoding logic in isolation.

ADDRESS = "0x" + "11" * 20


def _rpc() -> RpcClient:
    return RpcClient("http://localhost:1")


def test_get_storage_at_decodes_address_from_padded_slot(monkeypatch):
    rpc = _rpc()
    target = "0x0000000000000000000000000000000000000042"
    padded = bytes(12) + bytes.fromhex(target[2:])
    monkeypatch.setattr(rpc.w3.eth, "get_storage_at", lambda addr, slot: padded)

    result = rpc.get_storage_at(ADDRESS, "0x" + "00" * 32)

    assert result == Web3.to_checksum_address(target)


def test_get_storage_at_returns_none_for_all_zero_slot(monkeypatch):
    rpc = _rpc()
    monkeypatch.setattr(rpc.w3.eth, "get_storage_at", lambda addr, slot: bytes(32))

    assert rpc.get_storage_at(ADDRESS, "0x" + "00" * 32) is None


def test_get_storage_at_ignores_high_order_bytes(monkeypatch):
    """Only the low 20 bytes are the address; garbage in the upper 12 bytes
    (as some non-standard proxies leave) must not corrupt the result."""
    rpc = _rpc()
    target = "0x0000000000000000000000000000000000000042"
    garbage_high_bytes = b"\xff" * 12
    padded = garbage_high_bytes + bytes.fromhex(target[2:])
    monkeypatch.setattr(rpc.w3.eth, "get_storage_at", lambda addr, slot: padded)

    result = rpc.get_storage_at(ADDRESS, "0x" + "00" * 32)

    assert result == Web3.to_checksum_address(target)


def test_get_storage_at_passes_slot_as_integer(monkeypatch):
    captured = {}

    def fake_get_storage_at(addr, slot):
        captured["slot"] = slot
        return bytes(32)

    rpc = _rpc()
    monkeypatch.setattr(rpc.w3.eth, "get_storage_at", fake_get_storage_at)

    slot_hex = "0x" + "ab" * 32
    rpc.get_storage_at(ADDRESS, slot_hex)

    assert captured["slot"] == int(slot_hex, 16)


def test_checksum_normalizes_case():
    result = RpcClient.checksum(ADDRESS.lower())
    assert result == Web3.to_checksum_address(ADDRESS)
