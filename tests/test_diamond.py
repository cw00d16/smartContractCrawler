from __future__ import annotations

from crawler.models import ContractSource, Node
from crawler.resolvers.base import CrawlContext
from crawler.resolvers.diamond import DiamondLoupeResolver

DIAMOND = "0xAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAa"
FACET_A = "0xBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBb"
FACET_B = "0xCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCcCc"

FACETS_ABI = [{"type": "function", "name": "facets", "inputs": [], "outputs": [], "stateMutability": "view"}]


def _ctx(abi):
    return CrawlContext(chain=None, source=ContractSource(
        chain_id=1, address=DIAMOND, contract_name="Diamond", abi=abi, source_files={}, compiler_version="",
    ))


def test_discovers_facets_when_loupe_present(fake_rpc):
    fake_rpc.facets[DIAMOND.lower()] = [
        (FACET_A, [b"\x01\x02\x03\x04"]),
        (FACET_B, [b"\x05\x06\x07\x08", b"\x09\x0a\x0b\x0c"]),
    ]
    resolver = DiamondLoupeResolver(fake_rpc)
    node = Node(chain_id=1, address=DIAMOND)

    edges = resolver.discover(node, _ctx(FACETS_ABI))

    assert {e.to_address for e in edges} == {FACET_A, FACET_B}
    assert all(e.edge_type == "diamond:facet" for e in edges)


def test_skips_contracts_without_facets_function(fake_rpc):
    fake_rpc.facets[DIAMOND.lower()] = [(FACET_A, [b"\x01\x02\x03\x04"])]
    resolver = DiamondLoupeResolver(fake_rpc)
    node = Node(chain_id=1, address=DIAMOND)

    non_diamond_abi = [{"type": "function", "name": "owner", "inputs": [], "outputs": [], "stateMutability": "view"}]
    edges = resolver.discover(node, _ctx(non_diamond_abi))

    assert edges == []


def test_skips_facet_pointing_at_self(fake_rpc):
    fake_rpc.facets[DIAMOND.lower()] = [(DIAMOND, [b"\x01\x02\x03\x04"])]
    resolver = DiamondLoupeResolver(fake_rpc)
    node = Node(chain_id=1, address=DIAMOND)

    edges = resolver.discover(node, _ctx(FACETS_ABI))

    assert edges == []


def test_returns_empty_when_no_source(fake_rpc):
    resolver = DiamondLoupeResolver(fake_rpc)
    node = Node(chain_id=1, address=DIAMOND)
    edges = resolver.discover(node, CrawlContext(chain=None, source=None))
    assert edges == []


def test_call_error_is_skipped_not_raised(fake_rpc):
    def boom(address):
        raise RuntimeError("revert")
    fake_rpc.call_diamond_facets = boom
    resolver = DiamondLoupeResolver(fake_rpc)
    node = Node(chain_id=1, address=DIAMOND)

    edges = resolver.discover(node, _ctx(FACETS_ABI))

    assert edges == []
