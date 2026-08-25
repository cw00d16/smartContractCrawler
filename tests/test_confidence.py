from __future__ import annotations

from crawler.confidence import classify_edge_confidence
from crawler.models import Edge


def _edge(edge_type: str, source: str = "someName") -> Edge:
    return Edge(chain_id=1, from_address="0xAaa", to_address="0xBbb", edge_type=edge_type, source=source)


def test_proxy_edges_are_high_confidence():
    assert classify_edge_confidence(_edge("proxy:eip1967_implementation")) == "high"
    assert classify_edge_confidence(_edge("proxy:legacy_zos_implementation")) == "high"
    assert classify_edge_confidence(_edge("proxy:eip1967_beacon")) == "high"


def test_diamond_facet_is_high_confidence():
    assert classify_edge_confidence(_edge("diamond:facet")) == "high"


def test_bytecode_constant_is_low_confidence():
    assert classify_edge_confidence(_edge("bytecode:push20_constant")) == "low"


def test_abi_sweep_with_business_logic_name_is_medium():
    for name in ("processor", "ruleEngine", "underlyingAsset", "pool", "getRealTokenWrapper"):
        edge = _edge("abi:" + name, source=name)
        assert classify_edge_confidence(edge) == "medium", name


def test_abi_sweep_with_access_control_name_is_low():
    for name in ("owner", "admin", "pendingAdmin", "guardian", "pauser", "minter", "blacklister", "governance", "deployer"):
        edge = _edge("abi:" + name, source=name)
        assert classify_edge_confidence(edge) == "low", name


def test_access_control_pattern_match_is_case_insensitive():
    edge = _edge("abi:OWNER", source="OWNER")
    assert classify_edge_confidence(edge) == "low"


def test_abi_via_proxy_uses_same_classification_as_abi():
    assert classify_edge_confidence(_edge("abi_via_proxy:owner", source="owner")) == "low"
    assert classify_edge_confidence(_edge("abi_via_proxy:pool", source="pool")) == "medium"


def test_unknown_edge_type_defaults_to_medium():
    assert classify_edge_confidence(_edge("something:unexpected")) == "medium"
