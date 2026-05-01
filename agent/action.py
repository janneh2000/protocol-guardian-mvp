"""On-chain action layer — flips the ProtocolGuardian pause flag.

When the classifier returns a PAUSE decision (confidence >= 75), this
module sends a real transaction calling `pause(string)` on the deployed
ProtocolGuardian contract. The agent's hot wallet must hold GUARDIAN_ROLE
on that contract — granted at deploy-time by the admin (operator).

We keep the API tiny: `pause(reason)` and `unpause()`. Both are awaitable
and never raise on RPC errors — they return a result dict the report
layer can include in the operator alert.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from web3 import Web3
from web3.exceptions import ContractLogicError

logger = logging.getLogger("guardian.action")


# Minimal ABI — only what we call. Full ABI lives in abi/ after `npm run compile`.
_GUARDIAN_ABI = [
    {
        "type": "function",
        "name": "pause",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "reason", "type": "string"}],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "unpause",
        "stateMutability": "nonpayable",
        "inputs": [],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "paused",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "bool"}],
    },
]


class GuardianContract:
    """Thin wrapper around the deployed ProtocolGuardian contract."""

    def __init__(
        self,
        rpc_url: str,
        contract_address: str,
        hot_wallet_private_key: str,
        chain_id: int = 11155111,  # Sepolia
    ):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.account = self.w3.eth.account.from_key(hot_wallet_private_key)
        self.contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(contract_address),
            abi=_GUARDIAN_ABI,
        )
        self.chain_id = chain_id

    async def is_paused(self) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.contract.functions.paused().call)

    async def pause(self, reason: str) -> dict[str, Any]:
        return await self._send("pause", reason)

    async def unpause(self) -> dict[str, Any]:
        return await self._send("unpause")

    async def _send(self, fn_name: str, *args) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        try:
            fn = getattr(self.contract.functions, fn_name)(*args)
            tx = await loop.run_in_executor(
                None,
                lambda: fn.build_transaction({
                    "from": self.account.address,
                    "nonce": self.w3.eth.get_transaction_count(self.account.address),
                    "chainId": self.chain_id,
                    "gas": 200_000,
                    "maxFeePerGas": self.w3.to_wei("30", "gwei"),
                    "maxPriorityFeePerGas": self.w3.to_wei("2", "gwei"),
                }),
            )
            signed = self.account.sign_transaction(tx)
            tx_hash = await loop.run_in_executor(
                None, lambda: self.w3.eth.send_raw_transaction(signed.raw_transaction)
            )
            receipt = await loop.run_in_executor(
                None, lambda: self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            )
            return {
                "ok": receipt.status == 1,
                "tx_hash": tx_hash.hex(),
                "block": receipt.blockNumber,
                "gas_used": receipt.gasUsed,
            }
        except ContractLogicError as e:
            logger.warning("guardian.%s reverted: %s", fn_name, e)
            return {"ok": False, "error": f"revert: {e}"}
        except Exception as e:
            logger.exception("guardian.%s failed: %s", fn_name, e)
            return {"ok": False, "error": str(e)}
