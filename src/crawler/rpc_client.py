from __future__ import annotations

from typing import Optional

from web3 import Web3


class RpcClient:
    """Wraps eth_getStorageAt / eth_call. Uses web3.py Contract objects (with
    a minimal single-function ABI built on the fly) for calls, so selector
    encoding and return decoding are handled by web3 rather than by hand."""

    def __init__(self, rpc_url: str, timeout: int = 15):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": timeout}))

    @staticmethod
    def checksum(address: str) -> str:
        return Web3.to_checksum_address(address)

    def get_storage_at(self, address: str, slot: str) -> Optional[str]:
        raw = self.w3.eth.get_storage_at(self.checksum(address), int(slot, 16))
        value = int.from_bytes(raw, "big")
        if value == 0:
            return None
        addr_int = value & ((1 << 160) - 1)
        if addr_int == 0:
            return None
        return Web3.to_checksum_address(addr_int.to_bytes(20, "big"))

    def call_zero_arg_address_getter(self, address: str, fn_name: str) -> Optional[str]:
        abi = [{
            "inputs": [],
            "name": fn_name,
            "outputs": [{"name": "", "type": "address"}],
            "stateMutability": "view",
            "type": "function",
        }]
        contract = self.w3.eth.contract(address=self.checksum(address), abi=abi)
        return getattr(contract.functions, fn_name)().call()

    def get_code(self, address: str) -> bytes:
        return bytes(self.w3.eth.get_code(self.checksum(address)))

    def call_diamond_facets(self, address: str) -> list[tuple[str, list[bytes]]]:
        abi = [{
            "inputs": [],
            "name": "facets",
            "outputs": [{
                "components": [
                    {"name": "facetAddress", "type": "address"},
                    {"name": "functionSelectors", "type": "bytes4[]"},
                ],
                "name": "facets_",
                "type": "tuple[]",
            }],
            "stateMutability": "view",
            "type": "function",
        }]
        contract = self.w3.eth.contract(address=self.checksum(address), abi=abi)
        return contract.functions.facets().call()
