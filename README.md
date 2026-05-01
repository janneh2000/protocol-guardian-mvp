# Protocol Guardian

Autonomous on-chain security agent for DeFi protocols. Watches the Ethereum
mempool for transactions targeting protocols on its watchlist, classifies
each suspect tx with Claude, and — if the verdict is high-confidence
exploit — flips an on-chain pause flag *before* the tx lands.

Built for ETHGlobal Open Agents 2026.

---

## What it does

```
Alchemy WebSocket  →  pre-filter  →  Claude classifier  →  pause()  →  alert
                          ↑               ↑     ↑     ↑
                     watchlist       KeeperHub  AXL  AXL
                                       paid    bcst  recv
                                       intel
```

Every pending transaction targeting a watched protocol is decoded and
pre-filtered by selector / value / calldata heuristics. Anything that
clears the filter goes to a Claude classifier with a strict JSON-only
prompt that returns `{action, confidence, rationale}`.

When the verdict lands in the **ALERT band** (confidence 40–74), the agent
pays for premium threat-intel via the **KeeperHub** Turnkey-custodied
wallet (x402 / Base USDC) and reconciles the verdict with the upstream
feed. This catches exploits whose calldata patterns don't yet exist in
Claude's training set.

Every classification is broadcast to a **Gensyn AXL** P2P swarm of peer
Guardians. When ≥ 2 peers independently flag the same selector + target
within a 10-second window, confidence is bumped — protecting against a
single-node false negative.

When confidence ≥ 75, the agent calls `pause(reason)` on the
`ProtocolGuardian` contract. Target protocols read the flag in their own
critical paths and revert until an operator unpauses.

---

## Hackathon-window deliverables

| Layer | What's in this repo |
|---|---|
| **Smart contracts** | `ProtocolGuardian.sol` (role-gated pause registry) + `MockLendingPool.sol` (demo target). OpenZeppelin AccessControl boilerplate. |
| **Agent runtime** | `agent/` — ingestion (Alchemy WS) → heuristics → AI classifier → on-chain action → operator report. ~600 LOC of Python. |
| **KeeperHub bridge** | `agent/keeperhub_bridge.py` (Python) ↔ `agent/keeperhub_intel.mjs` (Node). Auto-pays the 402 challenge for premium threat-intel. Degrades gracefully without provisioning. |
| **AXL P2P swarm** | `agent/axl/` — 73-byte threat fingerprint wire format, 3-node docker-compose demo, bit-exact encode/decode round-trip. |
| **ENS identity** | `dashboard/ens.js` (viem-based resolver) + `scripts/register_ens.mjs` (Sepolia ENS helper). The guardian wallet gets a human-readable name. |
| **Marketing site** | Landing + login + team + get-started pages. Light/dark theme. Logo system. Hero illustration. |
| **Verify infra** | `scripts/smoke_test.py` — 18 zero-secret static checks that run in 30s. `make verify` or `npm run verify`. |

Live demo: <https://protocol-guardian.vercel.app/dashboard>

---

## Step-by-step setup

### 1. Install

```bash
git clone https://github.com/janneh2000/protocol-guardian-mvp.git
cd protocol-guardian-mvp
make install-deps        # npm install + pip install
```

### 2. Configure

```bash
cp .env.example .env
$EDITOR .env             # fill in Alchemy + Anthropic + wallet keys
```

You need:
- An [Alchemy](https://dashboard.alchemy.com) Sepolia app (WS + HTTP URLs)
- An [Anthropic](https://console.anthropic.com) API key
- A fresh, low-balance Sepolia private key for the deployer
- A second fresh Sepolia private key for the agent's hot wallet

Optional:
- `SLACK_WEBHOOK_URL` / `DISCORD_WEBHOOK_URL` for live alerts
- KeeperHub Turnkey provisioning for paid-intel enrichment
- Docker for the AXL multi-node swarm demo

### 3. Deploy contracts

```bash
npm run compile
npm run deploy           # writes addresses.json
```

This deploys `ProtocolGuardian` and `MockLendingPool` to Sepolia, then
grants `GUARDIAN_ROLE` on the registry to the agent's hot wallet so the
agent can call `pause()` autonomously.

### 4. Run the agent

```bash
python3 main.py
```

The agent subscribes to pending tx targeting addresses in `addresses.json`
(or `GUARDIAN_WATCHLIST`), classifies anything interesting, and calls
`pause(reason)` when the verdict crosses the threshold.

### 5. Watch the dashboard

```bash
make dashboard
# → http://localhost:8080
```

Or visit the live deploy: <https://protocol-guardian.vercel.app/dashboard>.
The event feed populates as the agent emits incidents.

### 6. Demo the attack

In another terminal:

```bash
python3 scripts/attack_simulator.py
```

This stages a suspicious transaction against the `MockLendingPool`. The
agent should classify it, escalate to KeeperHub if mid-confidence, broadcast
to AXL peers, and (for high-confidence) pause the pool before the tx mines.

---

## Verify (no secrets needed)

```bash
make verify
# or:
python3 scripts/smoke_test.py
# or:
npm run verify
```

The smoke test runs 18 static checks in ~30 seconds — zero API keys, zero
on-chain calls, zero Docker. It verifies the file structure, parses every
HTML/Python/JSON/SVG/YAML asset, round-trips the AXL wire format,
confirms the KeeperHub bridge degrades gracefully when no wallet is
provisioned, and asserts that the AI classifier wires all four
integration hooks. Designed for contributors and hackathon judges to
confirm the codebase is sound without provisioning anything.

---

## Project structure

```
.
├── contracts/              ProtocolGuardian.sol, MockLendingPool.sol
├── agent/
│   ├── ingestion.py        Alchemy WS pending-tx stream
│   ├── heuristics.py       Cheap pre-filter (selector / value / calldata)
│   ├── ai_agent.py         Claude classifier + 4 integration hooks
│   ├── action.py           on-chain pause via web3.py
│   ├── report.py           Slack / Discord / events.json
│   ├── keeperhub_bridge.py Python ↔ Node bridge for paid intel
│   ├── keeperhub_intel.mjs Node-side x402 fetch
│   └── axl/                Gensyn AXL P2P swarm client + docker-compose
├── dashboard/
│   ├── index.html          Live operator dashboard (dark, technical)
│   └── ens.js              viem-based ENS resolver
├── scripts/
│   ├── deploy.js           Hardhat deploy (Pool + Guardian + role grant)
│   ├── attack_simulator.py Stages a suspect tx for the demo
│   ├── smoke_test.py       18-check no-secrets verifier
│   └── register_ens.mjs    Sepolia ENS registration helper
├── assets/                 Logo / cover SVGs
├── index.html              Marketing landing
├── login.html              Marketing login
├── team.html               Marketing team
├── get-started.html        Onboarding page
├── theme.js                Light/dark FOUC-safe theme bootstrap
├── main.py                 Agent entrypoint
├── Makefile                make verify | install-deps | swarm | dashboard
├── package.json            Node dependencies + scripts
├── requirements.txt        Python dependencies
├── hardhat.config.js       Hardhat / Sepolia config
├── vercel.json             /dashboard route + cache headers
├── .env.example            Environment template
└── .gitignore
```

---

## Tech stack

- **Smart contracts**: Solidity 0.8.20, OpenZeppelin v5, Hardhat
- **Agent runtime**: Python 3.10+, web3.py, aiohttp, anthropic
- **AI**: Anthropic Claude (Opus 4.7)
- **Mempool**: Alchemy `alchemy_pendingTransactions` WebSocket
- **Paid intel**: KeeperHub `@keeperhub/wallet` (x402, Base USDC)
- **P2P swarm**: Gensyn AXL (custom 73-byte fingerprint frame)
- **Identity**: viem ENS resolution
- **Frontend**: vanilla HTML/CSS/JS (no framework), Vercel hosting

---

## Author

Built and led by [**Rivaldo Janneh**](https://github.com/janneh2000) — founder & lead dev.

© 2026 Protocol Guardian.
