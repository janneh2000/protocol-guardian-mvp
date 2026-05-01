"""Attack simulator — fires a suspicious tx at the deployed MockLendingPool
so we can demo the agent reacting end-to-end.

The "attack" itself is a withdraw() call from a non-depositor. The pool
will revert it for that reason alone; the point of the demo is that the
*pending* tx already trips the agent's heuristics + classifier and the
agent flips the pause flag *before* the tx mines. After that, every
subsequent legitimate call also reverts (PoolPaused), demonstrating the
circuit-breaker.

Usage:
    python3 scripts/attack_simulator.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from web3 import Web3


def main() -> int:
    load_dotenv()

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

    # withdraw(uint256) selector = 0x2e1a7d4d. We pass an absurd amount so
    # any humble depositor (0 balance) trips InsufficientBalance — which
    # is fine, the *pending* tx is already what the agent reacts to.
    selector = "0x2e1a7d4d"
    amount_wei = w3.to_wei("9999", "ether")
    calldata = selector + amount_wei.to_bytes(32, "big").hex()

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
    print("→ broadcasting attack tx (withdraw 9999 ETH from empty position)…")
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"  tx_hash: {tx_hash.hex()}")
    print(f"  selector: {selector}  target: {pool}")
    print()
    print("watch the agent log + dashboard — pause() should fire shortly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
