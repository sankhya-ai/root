# root

A coding agent that gets better the more you use it: a Mac app (or your browser), on cheap models.

**root** is a personal coding agent on Tura's runtime engine:

* **kimi-agent-rs** — Tura's agent runtime (Rust): observe-plan-act loop, native tools, subagents, approvals, compaction, skills, and MCP.
* **Jev Director** (`typesafe/jev-1.13`) — a pre-step director inside the runtime that steers the model toward acting rather than chatting.
* **Dhee Memory** — cross-session memory of project conventions, preferences, and verified patterns.
* **Learning Loop** — a reviewer turns finished work into `SKILL.md` playbooks, and a learned skill stays only while the turns that read it go at least as cleanly as before.
* **Undo any turn** — root snapshots the workspace before each turn (in its own shadow Git, never yours); “Restore files” or `/rollback` puts it back, and the restore can be undone too.
* **Installs what a task needs** — root's own Python toolbox: the agent asks for pandas, reportlab or matplotlib, root installs it (once, never into your system or project), runs the code, and hands you the file it made.
* **Documents** — reads PDF, Word, Excel, PowerPoint and CSV; edits spreadsheets and PDFs.
* **Plugins** — GitHub (issues, PRs, reviews, checks) and Gmail (read, draft — never send), session search, schedules, and your own MCP servers, each switchable in Settings → Plugins.
* **Schedules** — prompts root runs by itself on a timetable (`weekdays 09:00`), unattended and undoable.
* **Coding Flows** — on request, a change built and tested in an isolated git worktree and applied by hash after review (more parallel attempts only up to your limit).
* **Trust Ledger** — a default-deny command classifier that learns which checks are safe as you approve them.
* **On your team's chamber** (optional) — root joins as `<you>/root` and answers teammates' agents read-only from your repository.
* **Tura's UI** — glass cards, ruled-paper ground, outlined and ink pills, light and dark.

---

## Architecture

```text
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │                         root  (http://localhost:8787)                        │
 │                                                                              │
 │   ┌──────────────────────────────────────────────────────────────────────┐   │
 │   │  Web UI (React + Vite): sessions, approvals, inspector, settings     │   │
 │   └───────────────────────────────────┬──────────────────────────────────┘   │
 │                                       │ REST / WebSocket                     │
 │   ┌───────────────────────────────────┴──────────────────────────────────┐   │
 │   │  HOST SERVER (server/tura_code)                                      │   │
 │   │  • Sessions & approvals          • LLM proxy (token-to-key swapping) │   │
 │   │  • Trust ledger & coding flows   • Bubblewrap sandbox (hosted)       │   │
 │   │  • Learning loop & Dhee memory   • Runtime pool, tenancy             │   │
 │   └───────────────┬───────────────────────────────────────┬──────────────┘   │
 │                   │ stdio wire                            │ wss (optional)   │
 │   ┌───────────────┴────────────────────┐   ┌──────────────┴──────────────┐   │
 │   │  kimi-agent-rs (runtime/)          │   │  line/: root on chamber     │   │
 │   │  • Agent loop + Jev director       │   │  (answers teammates' agents │   │
 │   │  • File / grep / shell / subagents │   │   read-only)                │   │
 │   │  • Keyless web search              │   └─────────────────────────────┘   │
 │   └───────────────┬────────────────────┘                                     │
 └───────────────────┼──────────────────────────────────────────────────────────┘
                     ▼
            [ OpenRouter ]  (model provider, reached through the host's proxy)
```

---

## Key Capabilities

### 1. Built for Cheaper, Faster Models
The default model is `deepseek/deepseek-v4.1-flash`. The harness carries the edge cases that smaller models typically struggle with:
* **Jev Director**: Evaluates tool-vs-reply decisions before each turn so the model acts rather than chatting.
* **Lossless Argument Repair**: Fixes almost-valid JSON (code fences, unescaped newlines in strings, trailing commas) without discarding turns.
* **Whitespace-Tolerant Edits**: Re-indents search blocks to match file indentation cleanly.
* **Repeat Nudge**: Detects repetitive identical tool calls and nudges the agent to adopt a different approach.
* **Recursive Globbing**: Intelligently walks trees while pruning `.git`, `node_modules`, and build artifacts.

### 2. Security, Trust & Sandboxing
* **Workspace Boundary**: Reaching outside the workspace folder asks the owner, except in Auto-approve all on a local install (hosted mode always asks).
* **Credential Scrubbing**: No API key is ever exposed to runtimes or commands. The LLM proxy swaps transient launch tokens for operator keys on the fly.
* **Bubblewrap Jail**: In hosted mode, every runtime, process, and test run executes inside an isolated `bwrap` container.
* **Trust Ledger**: Automatically learns safe check commands over time through continuous developer usage.

---

## The Mac app

`scripts/package-macos.sh` builds `build/macos/root.app` and a drag-to-Applications disk image. The app bundles everything — the runtime, its own Python, the server and the UI — so it needs nothing installed. It behaves like a Mac app:

* closing the window keeps root (and any agent at work) running; the Dock brings it back; quitting asks while a session is working;
* notifications and the Dock badge when root finishes or needs your approval;
* a native folder picker (⌘N, ⌘O), Settings at ⌘,, zoom, Install Command Line Tool… (`root` on your PATH);
* keys and tokens in the macOS Keychain; offers to move itself to Applications; Sparkle updates.

Releases: a `v*` tag runs `.github/workflows/release.yml` — Apple silicon and Intel builds, Developer ID signing, notarization, stapling, and per-architecture Sparkle feeds. Locally, `SIGN_IDENTITY="Developer ID Application: …" NOTARY_PROFILE=<notarytool profile> scripts/package-macos.sh` does the same.

---

## Run it from a clone

### Prerequisites
* **macOS or Linux**, with `git` and `make`
* **Rust** 1.85 or newer (the runtime is edition 2024): `rustup update stable`
* **Python** 3.11–3.13 — not 3.14 yet (some server dependencies don't build on it)
* **Node.js** 22+ with npm

### 1. Build
```bash
git clone https://github.com/tura-learn/root.git
cd root
git checkout root-agentrouter    # or the branch you were given

make build                       # if `python3` is 3.14 or older than 3.11: make build PYTHON=python3.12
```

`make build` does three things, and you can run them one at a time if one fails:

| Step | Command | Makes |
| :--- | :--- | :--- |
| Runtime | `make runtime` | `runtime/target/release/kimi-agent` (a few minutes the first time) |
| Server | `make server` | `server/.venv`, with root's Python host and its memory layer |
| UI | `make ui` | `ui/dist`, the web page the server serves |

### 2. Run
```bash
make run                         # http://localhost:8787, opens your browser
```

`make doctor` checks the pieces (runtime binary, memory, model key) when something doesn't start. root keeps its settings, sessions and memory in `~/.tura-code`; set `TURA_CODE_HOME` to use another folder, and `TURA_CODE_PORT` (or `server/.venv/bin/tura-code --port 8799`) for another port.

### 3. Connect a model
root needs one OpenAI-compatible chat endpoint. Either:

* **OpenRouter** (the default): paste your key in **Settings → Model**, or `export OPENROUTER_API_KEY=sk-or-...` before `make run`.
* **Any other OpenAI-compatible endpoint** — a local proxy, a self-hosted model, another provider: stop root, then set the endpoint, model and key in `~/.tura-code/settings.json` (create it if it isn't there) and start root again:

  ```json
  {
    "base_url": "http://127.0.0.1:8319/v1",
    "model": "deepseek-v4-flash",
    "openrouter_api_key": "<the key that endpoint expects>"
  }
  ```

  root keeps that file readable only by you (0600); the Mac app moves the key into the Keychain. The runtime never sees it: every model call goes through root's own proxy.

To keep such a setup apart from your normal root, give it its own folder and port: `TURA_CODE_HOME=~/.root-other server/.venv/bin/tura-code --port 8799`.

### 4. Put root on your team's chamber (optional)
Once you have joined a chamber with the `chamber` tool, have root answer your teammates' agents from a repository:

```bash
server/.venv/bin/tura-code chamber answer /path/to/repo   # then restart root
server/.venv/bin/tura-code chamber status
```

root answers in read-only, plan-mode sessions you can watch in the UI. The board for the humans is chamber's own (`chamber board`).

---

## Hosting for Teams

On a Linux server with Bubblewrap installed (`apt install bubblewrap`):

```bash
# 1. Create a tenant user (outputs sign-in token once)
server/.venv/bin/tura-code user add alice --name "Alice"

# 2. Launch the hosted server behind an HTTPS reverse proxy
TURA_CODE_ALLOWED_HOSTS=agents.company.internal \
OPENROUTER_API_KEY=sk-or-... \
  server/.venv/bin/tura-code serve --hosted --host 0.0.0.0 --port 8787
```

In hosted mode:
* Each team member receives their own private tenant, settings, trust ledger, and workspace.
* Runtimes run in Bubblewrap jails with read-only root filesystems.
* Sessions are pooled and idle runtimes are cleanly evicted and restored on demand.

---

## Configuration Reference

Settings can be changed directly in the UI or in `~/.tura-code/settings.json` (0600):

| Setting | Default | Notes |
| :--- | :--- | :--- |
| **Coding Model** | `deepseek/deepseek-v4.1-flash` | Any tool-compatible model on OpenRouter. |
| **Reasoning Effort** | `model default` | `none`, `low`, `medium`, `high`. |
| **Provider Sort** | `balanced` | `throughput` (fastest), `price` (cheapest), or balanced. |
| **Jev Director** | `on` | `on`, `shadow` (log only), `off`. |
| **Dhee Memory** | `local` | `local` (lexical SQLite), `openrouter` (embeddings), `off`. |
| **Web Search** | `on (keyless)` | Free Parallel + Firecrawl search tiers out of the box. |
| **Permission Mode** | `Ask before acting` | `Ask before acting`, `Accept edits`, `Plan`, `Auto-approve all`. |

---

## Repository Layout

```text
agent/                   Base agent spec: tool definitions, subagents, system prompt
runtime/                 kimi-agent-rs runtime vendored from Tura (Rust)
server/tura_code/
  app/                   FastAPI routes (sessions, auth, workspaces, health)
  sessions/              Runtime processes, turns, approvals, host tools
  trust/                 Command classifier & trust ledger
  memory/                Dhee persistent memory gateway
  documents/             Reading PDF/Office/CSV; editing spreadsheets and PDFs
  toolbox/               root's own Python: install on demand, run_python, scratch files
  connections/           GitHub and Gmail
  history/               Session search (SQLite FTS5)
  schedules/             Prompts run unattended on a timetable
  plugins.py             The plugin catalog and the owner's MCP servers
  learning/              Automatic skill extraction & review loop
  flows/                 Git worktree candidate branches & judge evaluation
  line/                  root on chamber: answering teammates' agents read-only
  launcher.py            Process arguments & credential-scrubbed environments
macos/                   The Mac app: a Swift package (window, server, native bridge) with Sparkle
ui/                      React 19 + TypeScript + Vite frontend:
  src/components/pages/    Learning, Coding flows, Trust
  src/lib/                 API clients, diff parser, transcript folding
server/tests/            End-to-end Python test suites
```

---

## Development & Testing

```bash
# Run all test suites across the stack
make test

# Individual test runners:
cargo test --manifest-path runtime/Cargo.toml --workspace   # Runtime Rust tests
cd server && .venv/bin/python -m pytest -q                 # Host Python tests
cd ui && npm test && npm run typecheck                     # UI tests & TypeScript check

# Run with Vite hot-reloading:
make dev   # UI on :5173, Host on :8787
```

---

## License

* **Runtime**: Apache-2.0 (`runtime/LICENSE`, Moonshot AI / Kimi Code CLI).
* **UI Typography**: GeistPixel (SIL OFL 1.1, Vercel).
