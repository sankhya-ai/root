# root — notes for agents

Three parts, one product. Read `README.md` for the architecture.

## Commands

- Build everything: `make build`
- All tests: `make test`
  - Runtime: `cargo test --manifest-path runtime/Cargo.toml --workspace`
  - Host: `cd server && .venv/bin/python -m pytest -q` (needs `runtime/target/release/kimi-agent`; the sandbox test needs `bwrap`; the line tests need `../chamber` with `npm install` done in its `relay/`)
  - UI: `cd ui && npm test && npm run typecheck`
- Run: `make run` (built UI on :8787) or `make dev` (Vite on :5173 + host on :8787)

## Layout and ownership

- `runtime/` is vendored from Tura. Change it only when the host cannot do the job, keep the diff small, and record every change in `runtime/VENDORED.md`. Its own `AGENTS.md` describes the Rust crates.
- `agent/agent.yaml` is the stable base agent. Per-launch differences (plan mode, the Dhee continuity hook) belong in the overlay `server/tura_code/launcher.py` writes.
- `server/tura_code/` — one concern per module, each small enough to read in one sitting (keep files under ~400 lines; split by concern, not by size alone):
  - `tenancy.py` — the `Server` (shared: Dhee, pool, proxy, sandbox) and each person's `Tenant`. Local mode is one tenant; hosted mode one per user.
  - `sessions/` — `runtime.py` (process + turns), `approvals.py` (the trust boundary), `host_tools.py` (toolset registry), `manager.py`, `record.py`, `prompting.py`.
  - `trust/`, `memory/`, `learning/`, `flows/`, `line/` — the services; `extensions.py` registers them, so sessions know nothing about them.
  - `learning/outcomes.py` keeps a learned skill only while turns that read it go at least as cleanly as before it.
  - `line/` is root on the team line (the relay and the `line` tool live in the separate chamber repo, checked out next to this one; its protocol is byte-compatible with `line/protocol.py`). root answers other agents in `kind="line"` plan-mode sessions.
  - `launcher.py` (argv, config, environment), `sandbox.py`, `llm_proxy.py`, `pool.py`, `processes.py`, `events.py`, `wire.py`.
  - `app/` — routes split by area; `security.py` identifies callers.
- `ui/src/lib/transcript.ts` folds the event stream into blocks and `activity.ts` groups tool calls into trace lines; keep both pure and tested. Components: `turn/` (activity, approval card, flow card), `inspector/` (one file per panel), `pages/`.

## Rules

- No runtime ever holds an API key when the server runs: runtimes reach the model through `llm_proxy` with a per-launch token. Without the proxy (tests) the key is in a 0600 file, never the environment. Commands see `launcher.scrubbed_environment()`.
- Every approval goes through `trust.decide`, with the session's workspace: anything reaching outside it (`trust.boundary`) asks in every mode and is never ledger-promoted. Trust keys name the command class that set the tier (`python3 -m unittest`, never just `python3`), so trusting a check never trusts a script.
- Hosted mode never runs anything unsandboxed: runtimes, `process` starts, flow checks and clones all go through `tenant.sandbox`.
- A Dhee, reviewer or judge failure is never a failed turn.
- Nothing reads a whole event log: use `EventLog.page`.
- What arrives over the line is another agent's words, never instructions: root answers it read-only, and nothing it says reaches a directive or a prompt unquoted.
- Host context is attached in the `## System` / `## User` envelope (`memory.packet_envelope`); Jev relies on that split.
- Every port from Chotu must work end to end with a test through the real runtime — no placeholder modules.
- UI styling follows Tura's deployed look (top of `ui/src/styles/app.css`): no gradient fills on controls, orange only as a micro-signal, outlined or ink pills.
