from __future__ import annotations

from crawler.bytecode_scan import scan_push20_addresses


def _push(opcode: int, data: bytes) -> bytes:
    return bytes([opcode]) + data


def test_finds_push20_address_constant():
    addr = bytes.fromhex("11" * 20)
    code = _push(0x73, addr)  # PUSH20

    result = scan_push20_addresses(code)

    assert result == ["0x" + "11" * 20]


def test_skips_all_zero_push20():
    code = _push(0x73, bytes(20))
    assert scan_push20_addresses(code) == []


def test_ignores_non_push_opcodes():
    code = bytes([0x01, 0x02, 0x60, 0x05, 0x00])  # ADD, MUL, PUSH1 0x05, STOP
    assert scan_push20_addresses(code) == []


def test_correctly_skips_immediate_data_of_other_push_sizes():
    """A PUSH32 argument that happens to contain the byte 0x73 (PUSH20's
    opcode) must not be misinterpreted as a real PUSH20 instruction -- this
    is the core correctness property of skipping declared immediate lengths
    rather than scanning byte-by-byte."""
    fake_push20_byte_inside_data = bytes([0x00] * 10 + [0x73] + [0x00] * 21)
    assert len(fake_push20_byte_inside_data) == 32
    code = _push(0x7F, fake_push20_byte_inside_data)  # PUSH32 with embedded 0x73 byte

    assert scan_push20_addresses(code) == []


def test_finds_push20_after_other_push_instructions():
    addr = bytes.fromhex("22" * 20)
    code = _push(0x60, bytes([0x01])) + _push(0x73, addr) + bytes([0x00])  # PUSH1 1; PUSH20 addr; STOP

    result = scan_push20_addresses(code)

    assert result == ["0x" + "22" * 20]


def test_finds_multiple_distinct_push20_constants():
    addr_a = bytes.fromhex("aa" * 20)
    addr_b = bytes.fromhex("bb" * 20)
    code = _push(0x73, addr_a) + _push(0x73, addr_b)

    result = scan_push20_addresses(code)

    assert result == ["0x" + "aa" * 20, "0x" + "bb" * 20]


def test_truncated_push_at_end_of_bytecode_does_not_crash():
    # PUSH20 opcode with fewer than 20 bytes remaining (malformed/truncated).
    code = bytes([0x73]) + bytes([0x01, 0x02])
    assert scan_push20_addresses(code) == []


def test_empty_bytecode():
    assert scan_push20_addresses(b"") == []
