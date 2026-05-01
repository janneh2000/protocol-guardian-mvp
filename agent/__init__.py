"""Protocol Guardian — autonomous DeFi security agent.

Modules:
  ingestion        — mempool subscription via Alchemy WebSocket
  heuristics       — fast pre-filter on pending tx (selector, target, calldata)
  ai_agent         — Claude classifier + 4 integration hooks (KeeperHub / AXL)
  action           — on-chain pause via the ProtocolGuardian contract
  report           — operator notifications (Slack / Discord webhooks + log)
  keeperhub_bridge — Python ↔ Node bridge for paid threat-intel (x402)
  axl              — Gensyn AXL P2P swarm client (peer threat fingerprints)
"""
