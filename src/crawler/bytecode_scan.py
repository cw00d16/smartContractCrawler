from __future__ import annotations

_PUSH1 = 0x60
_PUSH32 = 0x7F
_PUSH20 = 0x73


def scan_push20_addresses(bytecode: bytes) -> list[str]:
    """Linear scan of EVM runtime bytecode for PUSH20 <address> patterns --
    a last-resort way to recover candidate dependency addresses baked in as
    bytecode constants, for contracts with no ABI available anywhere.

    Not a real disassembler: it doesn't track jump destinations or basic
    blocks. But it does correctly skip every PUSH instruction's declared
    immediate-data length (not just PUSH20's), which is the part that
    actually matters for correctness -- without that, a data byte equal to
    0x73 inside some other PUSH's argument (e.g. a PUSH32 hash constant)
    would misalign the scan and desync opcode interpretation for everything
    that follows. Byte-for-byte address recovery for the ordinary case
    (padding between real instructions in reachable code) needs no more
    than this."""
    candidates: list[str] = []
    i = 0
    n = len(bytecode)
    while i < n:
        op = bytecode[i]
        if _PUSH1 <= op <= _PUSH32:
            length = op - _PUSH1 + 1
            data = bytecode[i + 1 : i + 1 + length]
            if op == _PUSH20 and len(data) == 20 and any(data):
                candidates.append("0x" + data.hex())
            i += 1 + length
        else:
            i += 1
    return candidates
