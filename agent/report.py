"""Operator notifications.

When the classifier returns ALERT or PAUSE, send a structured message to
whichever channels the operator has configured (Slack, Discord, plain
log). Each notification includes the tx, the classifier's rationale, the
KeeperHub enrichment if any, and the AXL peer corroboration count.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp

logger = logging.getLogger("guardian.report")


@dataclass
class IncidentReport:
    """One row in the operator's incident feed."""
    tx_hash: str
    target: str
    selector: str
    action: str            # IGNORE | ALERT | PAUSE
    confidence: int        # 0..100
    rationale: str
    intel: dict[str, Any] = field(default_factory=dict)
    peer_corroboration: int = 0
    onchain_tx: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tx_hash": self.tx_hash,
            "target": self.target,
            "selector": self.selector,
            "action": self.action,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "intel": self.intel,
            "peer_corroboration": self.peer_corroboration,
            "onchain_tx": self.onchain_tx,
            "timestamp": self.timestamp,
        }


def _format_slack(r: IncidentReport) -> dict[str, Any]:
    color = {"PAUSE": "#dc2626", "ALERT": "#f59e0b", "IGNORE": "#94a3b8"}.get(r.action, "#94a3b8")
    fields = [
        {"title": "Action", "value": r.action, "short": True},
        {"title": "Confidence", "value": f"{r.confidence}%", "short": True},
        {"title": "Target", "value": r.target, "short": False},
        {"title": "Selector", "value": r.selector, "short": True},
        {"title": "Tx", "value": f"`{r.tx_hash[:18]}…`", "short": True},
    ]
    if r.peer_corroboration:
        fields.append({"title": "Peer corroboration", "value": f"{r.peer_corroboration} peer(s)", "short": True})
    if r.onchain_tx:
        fields.append({"title": "On-chain pause", "value": f"`{r.onchain_tx[:18]}…`", "short": True})
    return {
        "attachments": [{
            "color": color,
            "title": f"Protocol Guardian — {r.action}",
            "text": r.rationale,
            "fields": fields,
            "ts": int(r.timestamp),
        }]
    }


async def _post_webhook(url: str, payload: dict[str, Any]) -> bool:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status >= 300:
                    logger.warning("webhook %s returned %d", url[:40], resp.status)
                    return False
                return True
    except Exception as e:
        logger.warning("webhook post failed: %s", e)
        return False


async def report(r: IncidentReport) -> dict[str, bool]:
    """Send `r` to every configured channel. Returns per-channel success."""
    delivered: dict[str, bool] = {}

    logger.info(
        "incident %s tx=%s target=%s confidence=%d",
        r.action, r.tx_hash[:18], r.target, r.confidence,
    )

    # Append to local JSONL log — used by the dashboard event feed.
    try:
        events_path = os.getenv("GUARDIAN_EVENTS_LOG", "dashboard/events.json")
        os.makedirs(os.path.dirname(events_path) or ".", exist_ok=True)
        with open(events_path, "a") as fh:
            fh.write(json.dumps(r.to_dict()) + "\n")
        delivered["events_log"] = True
    except OSError as e:
        logger.warning("events log write failed: %s", e)
        delivered["events_log"] = False

    slack_url = os.getenv("SLACK_WEBHOOK_URL")
    if slack_url:
        delivered["slack"] = await _post_webhook(slack_url, _format_slack(r))

    discord_url = os.getenv("DISCORD_WEBHOOK_URL")
    if discord_url:
        # Discord accepts a simpler text payload.
        text = (
            f"**Protocol Guardian — {r.action}** ({r.confidence}%)\n"
            f"Target: `{r.target}`  Selector: `{r.selector}`\n"
            f"Tx: `{r.tx_hash}`\n"
            f"{r.rationale}"
        )
        if r.onchain_tx:
            text += f"\nOn-chain pause tx: `{r.onchain_tx}`"
        delivered["discord"] = await _post_webhook(discord_url, {"content": text})

    return delivered
