"""Attack simulator — fires a clearly-malicious tx at the deployed
MockLendingPool so we can demo the agent reacting end-to-end.

We use the `mint(address,uint256)` selector (0x40c10f19) — a textbook
admin-key-compromise pattern. The pool will revert (no such function),
but the *pending* tx is what the agent reacts to. Claude's system
prompt explicitly calls this out as a PAUSE-worthy signature.

Usage:
    python3 scripts/attack_simulator.py
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv
from web3 import Web3


def main() -> int:
    load_dotenv(".env")

    rpc = os.getenv("ALCHEMY_HTTP_RPC")
    attacker_key = os.getenv("ATTACKER_PRIVATE_KEY") or os.getenv("DEPLOYER_PRIVATE_KEY")
    if not rpc or not attacker_key:
        print("error: set ALCHEMY_HTTP_RPC and ATTACKER_PRIVATE_KEY (or DEPLOYER_PRIVATE_KEY) in .env")
        return 2

    addrs_path = Path("addresses.json")
    if not addrs_path.exists():
        print("error: addresses.json missing — run `npm run deploy` first")
        return 2
    addrs = json.loads(addrs_path.read_text())
    pool_addr = addrs.get("MockLendingPool")
    if not pool_addr:
        print("error: addresses.json has no MockLendingPool entry")
        return 2

    w3 = Web3(Web3.HTTPProvider(rpc))
    attacker = w3.eth.account.from_key(attacker_key)
    pool = Web3.to_checksum_address(pool_addr)

    print(f"attacker: {attacker.address}")
    print(f"pool:     {pool}")
    print()

    # mint(address recipient, uint256 amount) selector = 0x40c10f19.
    # We pass the attacker's address as the recipient and an absurd amount.
    # The pool will revert (it has no mint()) but the *pending* tx already
    # trips the agent's heuristics → Claude PAUSE band.
    selector = "0x40c10f19"
    recipient = attacker.address[2:].lower().rjust(64, "0")
    amount_wei = w3.to_wei("1000000000", "ether")  # 1 billion ETH
    amount_hex = amount_wei.to_bytes(32, "big").hex()
    calldata = selector + recipient + amount_hex

    nonce = w3.eth.get_transaction_count(attacker.address)
    chain_id = w3.eth.chain_id

    tx = {
        "to": pool,
        "from": attacker.address,
        "nonce": nonce,
        "gas": 120_000,
        "maxFeePerGas": w3.to_wei("30", "gwei"),
        "maxPriorityFeePerGas": w3.to_wei("2", "gwei"),
        "value": 0,
        "data": calldata,
        "chainId": chain_id,
    }
    signed = attacker.sign_transaction(tx)
    print(f"-> broadcasting attack tx (mint 1,000,000,000 tokens to attacker)...")
    print(f"   pattern: admin-key-compromise / infinite-mint signature")
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"  tx_hash: {tx_hash.hex()}")
    print(f"  selector: {selector}  target: {pool}")
    print()
    print("watch the agent log + dashboard - pause() should fire shortly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
