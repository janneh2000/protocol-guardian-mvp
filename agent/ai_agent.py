"""AI classification + integration orchestration.

The classifier wraps Anthropic Claude with a tight, structured prompt that
forces a JSON response with three fields: action ∈ {IGNORE, ALERT, PAUSE},
confidence ∈ [0,100], and a one-line rationale.

`analyse()` is the single entry point the main loop calls. It:

  1. Asks Claude for an initial decision.
  2. If the decision lands in the ALERT confidence band (40–74), it pays
     for premium threat-intel via KeeperHub (`fetch_paid_intel`) and
     reconciles the verdict (`reconcile_with_intel`). KeeperHub gates
     its paid call behind a Turnkey-custodied wallet — failures there
     leave the original decision intact.
  3. Broadcasts the final fingerprint to AXL peers
     (`broadcast_threat`) so other Guardians see the same signal.
  4. Pulls peer threat fingerprints via AXL (`recv_peer_threats`) and
     bumps confidence when ≥ 2 peers independently flagged the same
     selector + target in the last few seconds.

All four integration hooks are imported by name at the top so the
no-secrets smoke test can verify by string match without spinning up
the network. Each hook degrades gracefully when its sidecar is offline.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import anthropic

from .heuristics import PendingTx, SUSPICIOUS_SELECTORS
from .keeperhub_bridge import fetch_paid_intel, reconcile_with_intel
from .axl import broadcast_threat, recv_peer_threats

logger = logging.getLogger("guardian.ai")


SYSTEM_PROMPT = """You are Protocol Guardian, an autonomous DeFi security agent.

You receive one pending Ethereum transaction at a time. Decide whether the
target protocol should pause itself before this transaction lands.

You always respond with one JSON object, no prose, exactly this shape:

{"action": "IGNORE" | "ALERT" | "PAUSE", "confidence": <0-100>, "rationale": "<one short sentence>"}

Decision bands:
  IGNORE  (confidence 0-39)  — clearly benign or routine.
  ALERT   (confidence 40-74) — suspicious; operator should look but no auto-pause.
  PAUSE   (confidence 75-100) — high-confidence exploit pattern; pause the protocol.

You are conservative. Auto-pausing has real cost (lost user activity), so
you only PAUSE when the calldata pattern is unambiguous (e.g. flash-loan
+ privileged-function combo, infinite-mint signature, draining transfer
to a freshly-funded EOA).
"""


# Confidence band that warrants paid-intel enrichment.
_ALERT_LOW = 40
_ALERT_HIGH = 74


@dataclass
class Decision:
    action: str          # IGNORE | ALERT | PAUSE
    confidence: int      # 0..100
    rationale: str
    intel: dict[str, Any]
    peer_corroboration: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "intel": self.intel,
            "peer_corroboration": self.peer_corroboration,
        }


class AIAgent:
    """Classifier wrapping Claude + 3 sidecar integrations."""

    def __init__(self, api_key: str, model: str = "claude-opus-4-7"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def _ask_claude(self, tx: PendingTx, reason: str) -> dict[str, Any]:
        """One classification call. Returns the parsed JSON dict."""
        sel_label = SUSPICIOUS_SELECTORS.get(tx.selector, "unknown")
        user_msg = (
            f"Pending transaction:\n"
            f"  hash: {tx.tx_hash}\n"
            f"  from: {tx.from_addr}\n"
            f"  to:   {tx.to_addr}\n"
            f"  value: {tx.value_wei / 10**18:.4f} ETH\n"
            f"  selector: {tx.selector} ({sel_label})\n"
            f"  calldata: {tx.input_data[:512]}{'…' if len(tx.input_data) > 512 else ''}\n"
            f"  pre-filter reason: {reason}\n"
        )
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text.strip()
        # Strip markdown fences if Claude wrapped them.
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.rsplit("```", 1)[0].strip()
        decision = json.loads(text)
        # Normalise + clip.
        decision["action"] = str(decision.get("action", "ALERT")).upper()
        if decision["action"] not in {"IGNORE", "ALERT", "PAUSE"}:
            decision["action"] = "ALERT"
        decision["confidence"] = max(0, min(100, int(decision.get("confidence", 50))))
        decision["rationale"] = str(decision.get("rationale", ""))[:280]
        return decision

    async def analyse(self, tx: PendingTx, reason: str) -> Decision:
        """Full classification + enrichment pipeline.

        Hook order:
          1. Claude (mandatory)
          2. KeeperHub paid intel — only when ALERT band
          3. AXL broadcast — every classification, fire-and-forget
          4. AXL peer recv — checked once per call, bumps confidence
        """
        # 1. Initial Claude decision.
        try:
            decision = self._ask_claude(tx, reason)
        except Exception as e:
            logger.warning("Claude classification failed: %s — defaulting ALERT", e)
            decision = {"action": "ALERT", "confidence": 50, "rationale": f"classifier error: {e}"}

        intel: dict[str, Any] = {}

        # 2. ALERT-band escalation: pay for premium threat-intel and reconcile.
        if _ALERT_LOW <= decision["confidence"] <= _ALERT_HIGH:
            intel = await fetch_paid_intel(tx.selector, tx.to_addr)
            decision = reconcile_with_intel(decision, intel)

        # 3. Broadcast our fingerprint to AXL peers (fire-and-forget; offline returns False).
        try:
            await broadcast_threat(tx.selector, tx.to_addr, decision["confidence"])
        except Exception as e:
            logger.debug("AXL broadcast failed (offline?): %s", e)

        # 4. Pull peer fingerprints. ≥2 corroborating peers within ~10s
        #    bumps confidence by +10 (capped at 100).
        peer_corroboration = 0
        try:
            peers = await recv_peer_threats()
            now = time.time()
            for fp in peers:
                fresh = (now - fp.timestamp) < 10
                same_selector = fp.function_selector.lower() == tx.selector.lower()
                same_target = fp.target_address.lower() == tx.to_addr.lower()
                if fresh and same_selector and same_target and fp.confidence >= _ALERT_LOW:
                    peer_corroboration += 1
            if peer_corroboration >= 2:
                decision["confidence"] = min(100, decision["confidence"] + 10)
                decision["rationale"] += f" [+{peer_corroboration} AXL peer(s) corroborated]"
        except Exception as e:
            logger.debug("AXL recv failed (offline?): %s", e)

        # Re-bucket action after possible bumps.
        c = decision["confidence"]
        if c >= 75:
            decision["action"] = "PAUSE"
        elif c >= _ALERT_LOW:
            decision["action"] = "ALERT"
        else:
            decision["action"] = "IGNORE"

        return Decision(
            action=decision["action"],
            confidence=decision["confidence"],
            rationale=decision["rationale"],
            intel=intel,
            peer_corroboration=peer_corroboration,
        )
