"""Reset the demo to a clean slate for the next take.

Calls `unpause()` on the ProtocolGuardian contract (using the hot wallet,
which holds GUARDIAN_ROLE) and clears dashboard/events.json.

Usage:
    python3 scripts/reset_demo.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from web3 import Web3


def main() -> int:
    load_dotenv(".env")
    rpc = os.getenv("ALCHEMY_HTTP_RPC")
    hot_key = os.getenv("GUARDIAN_HOT_WALLET_PRIVATE_KEY")
    if not rpc or not hot_key:
        print("error: ALCHEMY_HTTP_RPC and GUARDIAN_HOT_WALLET_PRIVATE_KEY required")
        return 2

    addrs = json.loads(Path("addresses.json").read_text())
    guardian_addr = addrs["ProtocolGuardian"]

    w3 = Web3(Web3.HTTPProvider(rpc))
    hot = w3.eth.account.from_key(hot_key)
    abi = [
        {"type":"function","name":"paused","stateMutability":"view","inputs":[],"outputs":[{"type":"bool"}]},
        {"type":"function","name":"unpause","stateMutability":"nonpayable","inputs":[],"outputs":[]},
    ]
    g = w3.eth.contract(address=Web3.to_checksum_address(guardian_addr), abi=abi)

    is_paused = g.functions.paused().call()
    print(f"  current state: paused={is_paused}")

    if is_paused:
        print("  -> sending unpause()...")
        nonce = w3.eth.get_transaction_count(hot.address)
        tx = g.functions.unpause().build_transaction({
            "from": hot.address,
            "nonce": nonce,
            "chainId": w3.eth.chain_id,
            "gas": 100_000,
            "maxFeePerGas": w3.to_wei("30", "gwei"),
            "maxPriorityFeePerGas": w3.to_wei("2", "gwei"),
        })
        signed = hot.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"     tx: {tx_hash.hex()}")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        print(f"     status: {'ok' if receipt.status == 1 else 'FAIL'}  block: {receipt.blockNumber}")
    else:
        print("  -> already unpaused, nothing to do")

    events = Path("dashboard/events.json")
    if events.exists():
        events.unlink()
        print("  -> cleared dashboard/events.json")

    status = Path("dashboard/status.json")
    if status.exists():
        status.unlink()
        print("  -> cleared dashboard/status.json")

    print()
    print("ready for next take.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
