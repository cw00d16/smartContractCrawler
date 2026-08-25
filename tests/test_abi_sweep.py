from __future__ import annotations

from crawler.models import ContractSource, Node
from crawler.resolvers.abi_sweep import AbiSweepResolver
from crawler.resolvers.base import CrawlContext

CONTRACT = "0xAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAa"
CHILD = "0xBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBb"
SELF_ADDR = CONTRACT
ZERO = "0x0000000000000000000000000000000000000000"


def _abi_fn(name, inputs=(), outputs=(("", "address"),), mutability="view"):
    return {
        "type": "function",
        "name": name,
        "inputs": list(inputs),
        "outputs": [{"name": n, "type": t} for n, t in outputs],
        "stateMutability": mutability,
    }


def test_follows_zero_arg_address_getter(fake_rpc):
    fake_rpc.getters[(CONTRACT.lower(), "processor")] = CHILD
    resolver = AbiSweepResolver(fake_rpc)
    node = Node(chain_id=1, address=CONTRACT)
    ctx = CrawlContext(chain=None, source=ContractSource(
        chain_id=1, address=CONTRACT, contract_name="Root", abi=[_abi_fn("processor")],
        source_files={}, compiler_version="",
    ))

    edges = resolver.discover(node, ctx)

    assert len(edges) == 1
    assert edges[0].to_address == CHILD
    assert edges[0].edge_type == "abi:processor"


def test_skips_functions_with_inputs(fake_rpc):
    resolver = AbiSweepResolver(fake_rpc)
    abi = [_abi_fn("getChild", inputs=[{"name": "id", "type": "uint256"}])]
    edges = resolver.sweep_via(1, CONTRACT, abi)
    assert edges == []
    assert fake_rpc.getter_calls == []


def test_skips_non_address_outputs(fake_rpc):
    resolver = AbiSweepResolver(fake_rpc)
    abi = [_abi_fn("totalSupply", outputs=[("", "uint256")])]
    edges = resolver.sweep_via(1, CONTRACT, abi)
    assert edges == []


def test_skips_multi_output_functions(fake_rpc):
    resolver = AbiSweepResolver(fake_rpc)
    abi = [_abi_fn("pair", outputs=[("a", "address"), ("b", "address")])]
    edges = resolver.sweep_via(1, CONTRACT, abi)
    assert edges == []


def test_skips_non_view_pure_functions(fake_rpc):
    resolver = AbiSweepResolver(fake_rpc)
    abi = [_abi_fn("setProcessor", mutability="nonpayable")]
    edges = resolver.sweep_via(1, CONTRACT, abi)
    assert edges == []


def test_skips_zero_address_result(fake_rpc):
    resolver = AbiSweepResolver(fake_rpc)
    # fake_rpc returns ZERO_ADDRESS by default for unconfigured getters
    edges = resolver.sweep_via(1, CONTRACT, [_abi_fn("processor")])
    assert edges == []


def test_skips_self_referencing_result(fake_rpc):
    fake_rpc.getters[(CONTRACT.lower(), "self")] = SELF_ADDR
    resolver = AbiSweepResolver(fake_rpc)
    edges = resolver.sweep_via(1, CONTRACT, [_abi_fn("self")])
    assert edges == []


def test_call_error_is_skipped_not_raised(fake_rpc):
    fake_rpc.getters[(CONTRACT.lower(), "processor")] = RuntimeError("reverted")
    resolver = AbiSweepResolver(fake_rpc)
    edges = resolver.sweep_via(1, CONTRACT, [_abi_fn("processor")])
    assert edges == []


def test_sweep_via_namespaces_edge_type(fake_rpc):
    fake_rpc.getters[(CONTRACT.lower(), "owner")] = CHILD
    resolver = AbiSweepResolver(fake_rpc)
    edges = resolver.sweep_via(1, CONTRACT, [_abi_fn("owner")], namespace="abi_via_proxy")
    assert edges[0].edge_type == "abi_via_proxy:owner"


def test_discover_returns_empty_when_no_source(fake_rpc):
    resolver = AbiSweepResolver(fake_rpc)
    node = Node(chain_id=1, address=CONTRACT)
    edges = resolver.discover(node, CrawlContext(chain=None, source=None))
    assert edges == []
