# root — notes for agents

Three parts, one product. Read `README.md` for the architecture.

## Commands

- Build everything: `make build`
- All tests: `make test`
  - Runtime: `cargo test --manifest-path runtime/Cargo.toml --workspace`
  - Host: `cd server && .venv/bin/python -m pytest -q` (needs `runtime/target/release/kimi-agent`)
  - UI: `cd ui && npm test && npm run typecheck`
- Run: `make run` (built UI on :8787) or `make dev` (Vite on :5173 + host on :8787)

## Layout and ownership

- `runtime/` is vendored from Tura. Change it only when the host cannot do the job, keep the diff small, and record every change in `runtime/VENDORED.md`. Its own `AGENTS.md` describes the Rust crates.
- `agent/agent.yaml` is the stable base agent. Per-session differences (plan mode, the Dhee continuity hook, memory guidance) belong in the overlay `server/tura_code/launcher.py` writes, not in the base.
- `server/tura_code/`:
  - `launcher.py` — argv, config file, child environment, agent overlay for one runtime process.
  - `wire.py` — JSON-RPC over stdio client.
  - `sessions.py` — session lifecycle, event log, permission modes, turns.
  - `memory.py` — the only Dhee writer; tools and the per-turn memory loop.
  - `app.py` — HTTP/WebSocket API and its local-only security guards.
- `ui/src/lib/transcript.ts` folds the event stream into render blocks; keep it pure and covered by `transcript.test.ts`.

## Rules

- The OpenRouter key must never enter the runtime's environment or the transcript. It goes in the 0600 runtime config file.
- A Dhee failure is never a failed turn: it becomes a tool error or an omitted packet.
- Host context is attached to a request in the `## System` / `## User` envelope (`memory.packet_envelope`); the Jev director relies on that split.
- UI styling follows Tura's law (see the top of `ui/src/styles/app.css`): no drop shadows, orange only as a micro-signal, one gradient per screen.
