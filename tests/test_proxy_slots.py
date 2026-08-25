from __future__ import annotations

from crawler.models import Node
from crawler.resolvers.base import CrawlContext
from crawler.resolvers.proxy_slots import KNOWN_SLOTS, ProxySlotResolver

PROXY = "0xAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAa"
IMPL = "0xBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBb"


def test_known_slots_are_well_formed_32_byte_hex_values():
    assert len(KNOWN_SLOTS) == 4
    for name, slot in KNOWN_SLOTS.items():
        assert slot.startswith("0x"), name
        assert len(slot) == 66, f"{name} slot is not 32 bytes: {slot}"  # "0x" + 64 hex chars
        int(slot, 16)  # doesn't raise


def test_known_slots_are_all_distinct():
    assert len(set(KNOWN_SLOTS.values())) == len(KNOWN_SLOTS)


def test_discovers_edge_for_populated_slot(fake_rpc):
    fake_rpc.storage[(PROXY.lower(), KNOWN_SLOTS["legacy_zos_implementation"])] = IMPL
    resolver = ProxySlotResolver(fake_rpc)
    node = Node(chain_id=1, address=PROXY)

    edges = resolver.discover(node, CrawlContext(chain=None, source=None))

    assert len(edges) == 1
    assert edges[0].to_address == IMPL
    assert edges[0].edge_type == "proxy:legacy_zos_implementation"
    assert node.is_proxy is True


def test_no_edges_when_all_slots_empty(fake_rpc):
    resolver = ProxySlotResolver(fake_rpc)
    node = Node(chain_id=1, address=PROXY)

    edges = resolver.discover(node, CrawlContext(chain=None, source=None))

    assert edges == []
    assert node.is_proxy is False


def test_ignores_slot_pointing_at_self(fake_rpc):
    fake_rpc.storage[(PROXY.lower(), KNOWN_SLOTS["eip1967_implementation"])] = PROXY
    resolver = ProxySlotResolver(fake_rpc)
    node = Node(chain_id=1, address=PROXY)

    edges = resolver.discover(node, CrawlContext(chain=None, source=None))

    assert edges == []


def test_checks_all_known_slots(fake_rpc):
    resolver = ProxySlotResolver(fake_rpc)
    node = Node(chain_id=1, address=PROXY)
    resolver.discover(node, CrawlContext(chain=None, source=None))

    checked_slots = {slot for _, slot in fake_rpc.storage_calls}
    assert checked_slots == set(KNOWN_SLOTS.values())


def test_resolver_error_does_not_propagate_to_caller(fake_rpc):
    fake_rpc.get_storage_at = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("rpc down"))
    resolver = ProxySlotResolver(fake_rpc)
    node = Node(chain_id=1, address=PROXY)

    edges = resolver.discover(node, CrawlContext(chain=None, source=None))

    assert edges == []
