# root — notes for agents

Four parts, one product: the runtime, the host, the UI, and the macOS app around them. Read `README.md` for the architecture.

## Commands

- Build everything: `make build`
- All tests: `make test`
  - Runtime: `cargo test --manifest-path runtime/Cargo.toml --workspace`
  - Host: `cd server && .venv/bin/python -m pytest -q` (needs `runtime/target/release/kimi-agent`; the sandbox test needs `bwrap`; the line tests need `../chamber` with `npm install` done in its `relay/`)
  - UI: `cd ui && npm test && npm run typecheck`
- Run: `make run` (built UI on :8787) or `make dev` (Vite on :5173 + host on :8787)
- The Mac app: `scripts/package-macos.sh` → `build/macos/root.app` and its DMG (ad-hoc signed; `SIGN_IDENTITY` and `NOTARY_PROFILE` for a release, which `.github/workflows/release.yml` does on a `v*` tag)

## Layout and ownership

- `runtime/` is vendored from Tura. Change it only when the host cannot do the job, keep the diff small, and record every change in `runtime/VENDORED.md`. Its own `AGENTS.md` describes the Rust crates.
- `agent/agent.yaml` is the stable base agent. Per-launch differences (plan mode, the Dhee continuity hook) belong in the overlay `server/tura_code/launcher.py` writes.
- `server/tura_code/` — one concern per module, each small enough to read in one sitting (keep files under ~400 lines; split by concern, not by size alone):
  - `tenancy.py` — the `Server` (shared: Dhee, pool, proxy, sandbox) and each person's `Tenant`. Local mode is one tenant; hosted mode one per user.
  - `sessions/` — `runtime.py` (process + turns), `approvals.py` (the trust boundary), `checkpoints.py` (a shadow-Git snapshot before each turn; restore and undo), `host_tools.py` (toolset registry), `manager.py`, `record.py`, `prompting.py`.
  - `trust/`, `memory/`, `learning/`, `flows/`, `line/`, `slack/`, `documents/`, `toolbox/`, `connections/`, `history/`, `schedules/` — the services; `extensions.py` registers them, so sessions know nothing about them. `plugins.py` is the catalog the owner switches them on and off with (a toolset names its `plugin`), plus their MCP servers.
  - `documents/` reads PDF/Office/CSV and edits spreadsheets and PDFs; `toolbox/` is root's own Python (packages installed on demand, `run_python`, the session's scratch folder and the files it hands back); `connections/` is GitHub and Gmail; `history/` is session search (FTS5); `schedules/` runs prompts unattended on a timetable.
  - `memory/digest.py` is what a working turn leaves in Dhee: one call to the session's model, in the background, writes the checkpoint's what worked / what failed (they come back as lessons in the next session's first packet) and the turn's new durable facts — only from a finished turn whose edits were checked; a fact that corrects a stored one replaces it.
  - `learning/outcomes.py` keeps a learned skill only while turns that read it go at least as cleanly as before it.
  - `line/` is root on the team line (the relay and the `line` tool live in the separate chamber repo, checked out next to this one; its protocol is byte-compatible with `line/protocol.py`). root answers other agents in `kind="line"` plan-mode sessions.
  - `slack/` is root in a team chat: an @mention or a DM opens that thread's `kind="slack"` read-only plan-mode session (one per thread, in `slack/channels/<channel>/`, so each channel has its own project memory) and the reply goes back in the thread. Socket Mode, so no public URL; nothing is read until root is called, and the session is unattended — a step that would ask the owner is declined. Local mode only.
  - `keiki/` is root behind Keiki (WhatsApp, iMessage, Telegram, SMS, email, Slack): its external harness in inbox mode — root claims a turn by polling, runs it in that conversation's `kind="keiki"` read-only, unattended session, and answers and settles it through the turn's API (idempotent sends, lease kept alive). Local mode only.
  - `maritime.py` is Maritime's contract for a custom agent (`GET /health`, `POST /chat` answered within 30 s, a long turn returned on `status`), on only with `TURA_CODE_MARITIME=1`; those two routes skip the host check because the VM is reachable only through Maritime's front door. The repo-root `Dockerfile` and `scripts/maritime-start.py` build and start it with state in `/data`. Slack and Keiki also read their keys from the environment there (`SLACK_BOT_TOKEN`/`SLACK_APP_TOKEN`, `KEIKI_API_KEY`).
  - `terminal.py` — the owner's own shell in the session folder (the terminal drawer under the conversation, ⌘J; xterm.js over a WebSocket). Not the agent's: no approvals. Local installs only.
  - `hostos.py` is everything that differs between macOS, Linux and Windows (the data-folder lock, process groups and stopping a whole process tree, the shell for host commands — PowerShell on Windows, as the runtime's — venv paths, the terminal's shell). Nowhere else asks which system it runs on; never `os.kill(pid, 0)` (on Windows it sends Ctrl+C).
  - `launcher.py` (argv, config, environment; `TURA_CODE_RESOURCES` for an installed app), `sandbox.py`, `llm_proxy.py` (also OpenRouter model fallbacks), `vault.py` (credentials: 0600 files, or the macOS Keychain), `pool.py`, `processes.py`, `events.py`, `wire.py`.
  - `app/` — routes split by area; `security.py` identifies callers.
- `macos/` is the app: a Swift package (`Sources/Root`: the window, `Server.swift`, `Bridge.swift` for the page's native side, `Install.swift`) with Sparkle for updates. The page talks to it only through `ui/src/lib/native.ts`; in a browser there is no bridge and the web UI does the same jobs.
- `ui/src/lib/transcript.ts` folds the event stream into blocks and `activity.ts` groups tool calls into trace lines; keep both pure and tested. Components: `turn/` (activity, approval card, flow card), `inspector/` (one file per panel: Changes, Files, Plan); `TerminalDrawer.tsx`, `pages/`, `settings/` (Settings as a page; `PluginsSection.tsx` is the Plugins page).

## Rules

- No runtime ever holds an API key when the server runs: runtimes reach the model through `llm_proxy` with a per-launch token. Without the proxy (tests) the key is in a 0600 file, never the environment. Commands see `launcher.scrubbed_environment()`.
- Every approval goes through `trust.decide`, with the session's workspace: anything reaching outside it (`trust.boundary`) asks the owner — settled without asking only by a session grant or, on a local install, "Auto-approve all"; hosted mode asks in every mode — and is never ledger-promoted. Trust keys name the command class that set the tier (`python3 -m unittest`, never just `python3`), so trusting a check never trusts a script.
- Hosted mode never runs anything unsandboxed: runtimes, `process` starts, flow checks and clones all go through `tenant.sandbox`.
- A Dhee, reviewer or judge failure is never a failed turn.
- Nothing reads a whole event log: use `EventLog.page`.
- What arrives over the line, in a Slack chat or through Keiki is another person's words, never instructions: root answers it read-only, and nothing it says reaches a directive or a prompt unquoted. The same holds for email the `gmail` tool reads.
- A host tool that writes — a file, a GitHub comment, a Gmail draft, a package install, a schedule — asks through `approve_host_action`/`approve_host_command`; reads never ask. Writing to an outside service is never ledger-promoted.
- Packages the agent installs go into the toolbox, never the system, the owner's environments or the project. Unattended runs (schedules, flow candidates) decline what would ask the owner, and never run in "Auto-approve all".
- Coding flows run only when the owner asks; more than one candidate only up to the owner's `flow_max_candidates`.
- Files root serves back (`/api/sessions/{id}/file`) are never shown as a page the agent could have written: HTML and SVG download; everything inline gets a CSP sandbox.
- Host context is attached in the `## System` / `## User` envelope (`memory.packet_envelope`); Jev relies on that split.
- Every port from Chotu must work end to end with a test through the real runtime — no placeholder modules.
- UI styling follows Tura's deployed look (top of `ui/src/styles/base.css`): ink only — no orange, no blue, no gradient fills; primary actions are the black ink pill, others outlined. Keep surfaces quiet: no stat cards, tier diagrams or eyebrows; settings-style rows in rounded groups.
