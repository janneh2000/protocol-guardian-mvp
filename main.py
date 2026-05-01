"""Protocol Guardian — agent entrypoint.

Wires the modules together:

    Alchemy WebSocket  →  ingestion.stream_pending
                              ↓
                       heuristics.is_interesting    (cheap pre-filter)
                              ↓
                       AIAgent.analyse              (Claude + KeeperHub + AXL)
                              ↓
                       GuardianContract.pause       (if PAUSE)
                              ↓
                       report.report                (Slack/Discord/log)

Run:
    python3 main.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from agent.ai_agent import AIAgent
from agent.action import GuardianContract
from agent.heuristics import is_interesting
from agent.ingestion import stream_pending
from agent.report import IncidentReport, report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("guardian.main")


def _load_watchlist() -> list[str]:
    """Watchlist priority: GUARDIAN_WATCHLIST env CSV → addresses.json → []."""
    csv = os.getenv("GUARDIAN_WATCHLIST", "").strip()
    if csv:
        return [a.strip() for a in csv.split(",") if a.strip()]

    addrs = Path("addresses.json")
    if addrs.exists():
        data = json.loads(addrs.read_text())
        return [a for a in data.values() if isinstance(a, str) and a.startswith("0x")]

    return []


async def run() -> int:
    load_dotenv()

    ws_url = os.getenv("ALCHEMY_WS_RPC")
    http_url = os.getenv("ALCHEMY_HTTP_RPC")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    contract = os.getenv("GUARDIAN_CONTRACT_ADDRESS")
    hot_key = os.getenv("GUARDIAN_HOT_WALLET_PRIVATE_KEY")

    missing = [n for n, v in [
        ("ALCHEMY_WS_RPC", ws_url),
        ("ALCHEMY_HTTP_RPC", http_url),
        ("ANTHROPIC_API_KEY", api_key),
        ("GUARDIAN_CONTRACT_ADDRESS", contract),
        ("GUARDIAN_HOT_WALLET_PRIVATE_KEY", hot_key),
    ] if not v]
    if missing:
        logger.error("missing required env vars: %s", ", ".join(missing))
        logger.error("copy .env.example to .env and fill in the values")
        return 2

    watchlist = _load_watchlist()
    if not watchlist:
        logger.error(
            "watchlist empty — set GUARDIAN_WATCHLIST or run `npm run deploy` to "
            "populate addresses.json"
        )
        return 2

    classifier = AIAgent(api_key=api_key)
    guardian = GuardianContract(
        rpc_url=http_url,
        contract_address=contract,
        hot_wallet_private_key=hot_key,
    )

    logger.info("Protocol Guardian online — watching %d address(es)", len(watchlist))

    async for tx in stream_pending(ws_url, watchlist):
        ok, reason = is_interesting(tx, watchlist)
        if not ok:
            continue

        logger.info("classifying tx=%s reason=%s", tx.tx_hash[:18], reason)
        decision = await classifier.analyse(tx, reason)

        incident = IncidentReport(
            tx_hash=tx.tx_hash,
            target=tx.to_addr,
            selector=tx.selector,
            action=decision.action,
            confidence=decision.confidence,
            rationale=decision.rationale,
            intel=decision.intel,
            peer_corroboration=decision.peer_corroboration,
        )

        if decision.action == "PAUSE":
            already = await guardian.is_paused()
            if already:
                logger.info("already paused — skipping pause tx, still reporting")
            else:
                result = await guardian.pause(
                    f"{tx.selector}|{decision.confidence}|{tx.tx_hash[:10]}"
                )
                if result.get("ok"):
                    incident.onchain_tx = result["tx_hash"]
                else:
                    logger.warning("pause tx failed: %s", result.get("error"))

        await report(incident)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(run()))
    except KeyboardInterrupt:
        logger.info("shutting down")
        sys.exit(0)
