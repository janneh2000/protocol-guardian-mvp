"""Cheap pre-filter on incoming pending transactions.

Most pending tx in the mempool are uninteresting — ETH transfers, ERC-20
approvals, MEV sandwiches against random LPs. We don't want to spend a
Claude call on every one. This module decides which pending tx are even
worth classifying.

A tx passes the filter when:
  1. It targets one of the protocol contracts the operator is watching
     (the watchlist — kept short and explicit), AND
  2. Its function selector hits a known suspicion bucket OR carries an
     unusually large value / unusual calldata pattern.

Everything else is dropped silently. The classifier never sees it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

# Function selectors that warrant a closer look. Selectors are the first
# four bytes of keccak256("name(types)") and are how the EVM dispatches.
# We don't claim these are exploits — only that they're worth a Claude
# pass when targeted at a protocol on our watchlist.
SUSPICIOUS_SELECTORS: dict[str, str] = {
    "0xa9059cbb": "ERC20.transfer",          # large transfer to/from pool
    "0x23b872dd": "ERC20.transferFrom",      # pulls from a third party
    "0x095ea7b3": "ERC20.approve",           # infinite-approval scams
    "0x5cffe9de": "flashLoan",               # flash-loan exploit pattern
    "0x12aa3caa": "swap",                    # 1inch-style aggregator path
    "0x42842e0e": "safeTransferFrom",        # NFT drainer
    "0xb88d4fde": "safeTransferFrom(bytes)", # NFT drainer w/ data
    "0x40c10f19": "mint",                    # privileged mint — admin-key compromise
    "0x9dc29fac": "burn",                    # privileged burn
    "0x8456cb59": "pause",                   # someone trying to pause us first
}

# Wei threshold above which raw ETH value alone is enough to escalate.
# 100 ETH at typical L1 gas is already operator-attention-worthy.
LARGE_VALUE_WEI = 100 * 10**18


@dataclass
class PendingTx:
    """Subset of a pending tx that we care about."""
    tx_hash: str
    from_addr: str
    to_addr: str
    value_wei: int
    input_data: str  # hex, 0x-prefixed

    @property
    def selector(self) -> str:
        """First four bytes of calldata, lowercased, 0x-prefixed."""
        if not self.input_data or len(self.input_data) < 10:
            return "0x"
        return self.input_data[:10].lower()


def is_on_watchlist(tx: PendingTx, watchlist: Iterable[str]) -> bool:
    """True when the tx targets one of the protocols the operator watches."""
    target = (tx.to_addr or "").lower()
    return target in {w.lower() for w in watchlist}


def is_interesting(tx: PendingTx, watchlist: Iterable[str]) -> tuple[bool, str]:
    """Return (passes_filter, reason). Reason is short label for logging."""
    if not is_on_watchlist(tx, watchlist):
        return False, "off-watchlist"

    sel = tx.selector
    if sel in SUSPICIOUS_SELECTORS:
        return True, f"selector:{SUSPICIOUS_SELECTORS[sel]}"

    if tx.value_wei >= LARGE_VALUE_WEI:
        return True, f"value:{tx.value_wei / 10**18:.0f}eth"

    # Calldata that's much longer than typical (>1KB) often signals a
    # multicall payload or a complex exploit setup. Worth a Claude pass.
    if len(tx.input_data) > 2048:
        return True, f"calldata:{len(tx.input_data)}b"

    return False, "uninteresting"
