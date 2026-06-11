# Hub / multi-machine mode (experimental — roadmap)

> **Status: UNVERIFIED.** This multi-machine Hub + Agent path predates the
> current single-machine tool and has **not** been tested end-to-end. It is kept
> here as a starting point for future work, not as a supported mode. Use the
> single-machine `cc-remote` CLI (see the top-level README) for anything real.

## Idea

One Hub connects to Feishu and relays commands to multiple remote Agent machines,
switching the active machine with `/use <name>`.

```
飞书 → Hub (hub.py) ←WebSocket→ Agent A (agent.py)
                    ←WebSocket→ Agent B (agent.py)
```

- `hub.py` — connects to Feishu, registers agents, routes `/use` / `/list` / `/read`.
- `agent.py` — runs on each remote machine, connects to the Hub, drives local tmux.
- `.env.hub.example` / `.env.agent.example` — config templates.

## Before relying on this

It needs: end-to-end testing, reconciliation with the single-machine signal/
screenshot/reaction design (which it predates), and a security review of the
Hub↔Agent `HUB_TOKEN` auth. Until then, treat it as a sketch.
