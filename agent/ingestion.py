"""Mempool ingestion via Alchemy WebSocket.

Subscribes to `alchemy_pendingTransactions` filtered to the operator's
watchlist, decodes each pending tx into the `PendingTx` shape `heuristics`
expects, and yields one tx at a time. The caller (main loop) is
responsible for backpressure — if a classifier call is in flight, drop
incoming tx rather than buffering.

Why WebSocket and not polling: pending tx live for 200-2000 ms before
mining. We need to react before inclusion, not after.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Iterable

import aiohttp

from .heuristics import PendingTx

logger = logging.getLogger("guardian.ingestion")


async def stream_pending(
    ws_url: str,
    watchlist: Iterable[str],
    *,
    reconnect_delay_s: float = 2.0,
) -> AsyncIterator[PendingTx]:
    """Yield pending transactions targeting any address on `watchlist`.

    Uses Alchemy's `alchemy_pendingTransactions` subscription with a
    `toAddress` filter so we don't pay bandwidth for tx that aren't ours.
    Reconnects with backoff on disconnect; the agent loop is meant to
    run for days, so resilience matters more than latency on errors.
    """
    targets = [a.lower() for a in watchlist]
    if not targets:
        logger.warning("watchlist empty — nothing to monitor")
        return

    sub_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_subscribe",
        "params": [
            "alchemy_pendingTransactions",
            {"toAddress": targets, "hashesOnly": False},
        ],
    }

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(ws_url, heartbeat=30) as ws:
                    await ws.send_json(sub_payload)
                    logger.info(
                        "subscribed alchemy_pendingTransactions for %d targets",
                        len(targets),
                    )

                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue
                        try:
                            payload = json.loads(msg.data)
                        except json.JSONDecodeError:
                            continue

                        # The first message is the subscribe ack; later
                        # messages carry params.result with the tx body.
                        result = (payload.get("params") or {}).get("result")
                        if not isinstance(result, dict):
                            continue

                        try:
                            yield PendingTx(
                                tx_hash=result.get("hash", ""),
                                from_addr=result.get("from", ""),
                                to_addr=result.get("to", "") or "",
                                value_wei=int(result.get("value", "0x0"), 16),
                                input_data=result.get("input", "0x"),
                            )
                        except (ValueError, TypeError) as e:
                            logger.warning("malformed pending tx: %s", e)
                            continue

        except aiohttp.ClientError as e:
            logger.warning("ws disconnected: %s — reconnecting in %.1fs", e, reconnect_delay_s)
            await asyncio.sleep(reconnect_delay_s)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("unexpected ws error: %s", e)
            await asyncio.sleep(reconnect_delay_s)
