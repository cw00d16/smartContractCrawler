from __future__ import annotations

from crawler.models import ContractSource, Node
from crawler.resolvers.base import CrawlContext
from crawler.resolvers.bytecode import BytecodeConstantResolver

CONTRACT = "0xAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAa"
CANDIDATE = "0xBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBb"


def _push20_code(address_hex: str) -> bytes:
    return bytes([0x73]) + bytes.fromhex(address_hex[2:])


class FakeCodeRpc:
    """Minimal RPC double just for get_code, used by this resolver."""

    def __init__(self, code_by_address: dict[str, bytes]):
        self.code_by_address = {a.lower(): c for a, c in code_by_address.items()}
        self.get_code_calls: list[str] = []

    def get_code(self, address: str) -> bytes:
        self.get_code_calls.append(address)
        return self.code_by_address.get(address.lower(), b"")


def test_skips_entirely_when_source_is_present():
    rpc = FakeCodeRpc({CONTRACT: _push20_code(CANDIDATE)})
    resolver = BytecodeConstantResolver(rpc)
    node = Node(chain_id=1, address=CONTRACT)
    ctx = CrawlContext(chain=None, source=ContractSource(
        chain_id=1, address=CONTRACT, contract_name="Foo", abi=[{"type": "function"}],
        source_files={}, compiler_version="",
    ))

    edges = resolver.discover(node, ctx)

    assert edges == []
    assert rpc.get_code_calls == []  # never even looked at bytecode -- ABI was available


def test_finds_candidate_with_code_when_no_source(monkeypatch):
    rpc = FakeCodeRpc({
        CONTRACT.lower(): _push20_code(CANDIDATE),
        CANDIDATE.lower(): b"\x60\x00",  # candidate has some code -> counts as a real contract
    })
    resolver = BytecodeConstantResolver(rpc)
    node = Node(chain_id=1, address=CONTRACT)

    edges = resolver.discover(node, CrawlContext(chain=None, source=None))

    assert len(edges) == 1
    assert edges[0].to_address.lower() == CANDIDATE.lower()
    assert edges[0].edge_type == "bytecode:push20_constant"


def test_discards_candidate_with_no_code():
    rpc = FakeCodeRpc({
        CONTRACT.lower(): _push20_code(CANDIDATE),
        # CANDIDATE deliberately absent -> get_code returns b"" -> not a contract
    })
    resolver = BytecodeConstantResolver(rpc)
    node = Node(chain_id=1, address=CONTRACT)

    edges = resolver.discover(node, CrawlContext(chain=None, source=None))

    assert edges == []


def test_no_bytecode_at_all_returns_no_edges():
    rpc = FakeCodeRpc({})  # get_code returns b"" for everything
    resolver = BytecodeConstantResolver(rpc)
    node = Node(chain_id=1, address=CONTRACT)

    edges = resolver.discover(node, CrawlContext(chain=None, source=None))

    assert edges == []


def test_rpc_error_is_skipped_not_raised():
    class BoomRpc:
        def get_code(self, address):
            raise RuntimeError("rpc down")

    resolver = BytecodeConstantResolver(BoomRpc())
    node = Node(chain_id=1, address=CONTRACT)

    edges = resolver.discover(node, CrawlContext(chain=None, source=None))

    assert edges == []


def test_deduplicates_repeated_candidate():
    rpc = FakeCodeRpc({
        CONTRACT.lower(): _push20_code(CANDIDATE) + _push20_code(CANDIDATE),
        CANDIDATE.lower(): b"\x60\x00",
    })
    resolver = BytecodeConstantResolver(rpc)
    node = Node(chain_id=1, address=CONTRACT)

    edges = resolver.discover(node, CrawlContext(chain=None, source=None))

    assert len(edges) == 1


def test_ignores_self_referencing_candidate():
    rpc = FakeCodeRpc({CONTRACT.lower(): _push20_code(CONTRACT)})
    resolver = BytecodeConstantResolver(rpc)
    node = Node(chain_id=1, address=CONTRACT)

    edges = resolver.discover(node, CrawlContext(chain=None, source=None))

    assert edges == []
