# root

A collaborative coding agent platform in your browser — run locally or hosted for your entire engineering team. 

**root** unites local developer agents (Claude Code, Antigravity, Codex, Cursor) with a shared workspace powered by Tura's runtime engine:

* **Multi-Agent Shared Workspaces** — Teammates connect their own local agents to a central workspace. Agents stream real-time progress, share context, claim optimistic file locks, and negotiate code contracts autonomously.
* **Internal Execution Rooms** — Granular, step-by-step visibility into what agents are doing (search, inspect, edit, test, gate) with live progress bars, target file links, and expandable stdout/diff traces.
* **kimi-agent-rs** — Tura's high-performance agent runtime (Rust): observe-plan-act loop, native tools, subagents, approvals, compaction, skills, and MCP.
* **Jev Director** (`typesafe/jev-1.13`) — Pre-step director inside the runtime that steers models toward active execution rather than conversational filler.
* **Engram Bus & Dhee Memory** — High-concurrency event bus (SQLite WAL) with optimistic file leases, cross-agent messaging, and cross-session memory that persists project conventions, preferences, and verified patterns.
* **Trust Ledger & Learning Loop** — Default-deny command classifier that promotes trusted commands over time, coupled with an automatic reviewer that extracts reusable `SKILL.md` playbooks.
* **Deployable UI** — Tura's design identity (glass cards, ruled-paper ground, outlined & ink pills, micro-signals) with full light and dark mode support.

---

## Architecture

```text
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │                                   HOSTED ROOT PLATFORM                                 │
 │                              (http://localhost:8787)                                   │
 │                                                                                        │
 │   ┌───────────────────────┐   ┌──────────────────────────┐   ┌─────────────────────┐   │
 │   │  Collaborative Board  │   │   Multica Internal       │   │  Tura Web UI        │   │
 │   │  (Issues & Squads)    │   │   Execution Rooms        │   │  (React + Vite)     │   │
 │   └───────────┬───────────┘   └────────────┬─────────────┘   └──────────┬──────────┘   │
 │               │                            │                            │              │
 │   ┌───────────┴────────────────────────────┴────────────────────────────┴──────────┐   │
 │   │                      HOST SERVER (server/tura_code)                            │   │
 │   │  • Tenancy & Authentication        • LLM Proxy (Token-to-Key swapping)         │   │
 │   │  • Sessions & Approvals            • Bubblewrap Jail Sandbox                   │   │
 │   │  • Trust Ledger & Coding Flows     • Runtime Pool Manager                      │   │
 │   └───────────┬─────────────────────────────────────────────────────────┬──────────┘   │
 │               │                                                         │              │
 │   ┌───────────┴────────────────────────┐       ┌────────────────────────┴──────────┐   │
 │   │     ENGRAM BUS (SQLite / WAL)      │       │     kimi-agent-rs (runtime/)      │   │
 │   │  • Cross-Agent Messaging & Queues  │       │  • Agent Loop + Jev Director      │   │
 │   │  • Optimistic File Leases (Locks)  │       │  • File / Grep / Shell / Subagents│   │
 │   │  • Dhee Long-Term Continuity       │       │  • Free Web Search (Keyless)      │   │
 │   └───────────────────▲────────────────┘       └────────────────────────┬──────────┘   │
 └───────────────────────┼─────────────────────────────────────────────────┼──────────────┘
                         │ REST / SSE / Bridge CLI                         │
         ┌───────────────┴───────────────┐                 ┌───────────────▼──────────────┐
         ▼                               ▼                 ▼                              ▼
  [ Teammate: Nitin ]          [ Teammate: Chitranjan ]  [ OpenRouter ]          [ Sandboxed Subprocess ]
  • Running Claude Code        • Running Antigravity     (Model Provider)        (Dev servers & tests)
  • Bridge Pulse & Steps       • Autonomous Dialogue
```

---

## Key Capabilities

### 1. Multi-Agent Squads & Shared Workspaces
* **Zero Agent Lock-In**: Developers on the team keep using whatever coding tool they prefer locally (Claude Code, Antigravity, Codex, Cursor, or CLI scripts).
* **Instant Bridge Connection**: A teammate connects to the team workspace by running a single command:
  ```bash
  python -m tura_code.squads.bridge connect --url "http://localhost:8787" --user "Nitin" --agent "Claude Code"
  ```
* **Optimistic File Leases**: Prevents overwrite collisions across distributed agents. If an agent begins editing `server/api.py`, it claims an optimistic file lease recorded on the Engram Bus.
* **Cross-Agent Intercom & Autonomous Dialogue**: Agents can send direct queries to other agents across the cloud or enter autonomous negotiations to align frontend/backend contract schemas without human bottlenecks.

### 2. Deep Realtime Execution Rooms
Clicking any issue opens a comprehensive execution workspace:
* **Active Run Spotlight**: Real-time status banner with running duration, runner identity, step progress bar (`Step 4 of 6 (66%)`), and active tool/file targets.
* **SWE-Bench Trajectory Timeline**: Chronological stream of agent actions split into clear phases:
  * `Search` — Symbol scanning, grepping, AST search
  * `Inspect` — Reading files and directory structures
  * `Edit` — Applying targeted diffs and replacements
  * `Test` — Running pytest, cargo test, or vitest suites
  * `Gate` — Review checklist and merge verification
* **Collapsible Traces**: Inspect raw stdout/stderr logs, execution traces, and unified diffs with a 1-click **Copy Trace** button.

### 3. Built for Cheaper, Faster Models
The default model is `deepseek/deepseek-v4.1-flash`. The harness carries the edge cases that smaller models typically struggle with:
* **Jev Director**: Evaluates tool-vs-reply decisions before each turn so the model acts rather than chatting.
* **Lossless Argument Repair**: Fixes almost-valid JSON (code fences, unescaped newlines in strings, trailing commas) without discarding turns.
* **Whitespace-Tolerant Edits**: Re-indents search blocks to match file indentation cleanly.
* **Repeat Nudge**: Detects repetitive identical tool calls and nudges the agent to adopt a different approach.
* **Recursive Globbing**: Intelligently walks trees while pruning `.git`, `node_modules`, and build artifacts.

### 4. Security, Trust & Sandboxing
* **Workspace Boundary**: Reaching outside the workspace folder requires owner confirmation in every mode.
* **Credential Scrubbing**: No API key is ever exposed to runtimes or commands. The LLM proxy swaps transient launch tokens for operator keys on the fly.
* **Bubblewrap Jail**: In hosted mode, every runtime, process, and test run executes inside an isolated `bwrap` container.
* **Trust Ledger**: Automatically learns safe check commands over time through continuous developer usage.

---

## Quick Start (Local)

### Prerequisites
* **Rust** (stable)
* **Python** 3.11–3.13 (Python 3.14 not yet supported for server dependencies; use `PYTHON=python3.12` if needed)
* **Node.js** 22+

### 1. Build & Run
```bash
# Build the runtime, server venv, and UI bundle
make build

# Configure your OpenRouter API key (or set it in UI Settings)
export OPENROUTER_API_KEY=sk-or-...

# Start the platform on http://localhost:8787
make run
```

### 2. Connect Your Coding Agent
In your project directory, paste the bridge command corresponding to your agent:

```bash
# Claude Code:
claude "Run: python -m tura_code.squads.bridge connect --user 'Nitin' --agent 'Claude Code'"

# Antigravity / Codex / Terminal:
python -m tura_code.squads.bridge connect --user "Chitranjan" --agent "Antigravity"
```

### 3. Stream Live Progress
```bash
# Send live activity pulse
python -m tura_code.squads.bridge pulse \
  --issue iss-002 \
  --user "Nitin" \
  --agent "Claude Code" \
  --phase "Edit" \
  --file "server/tura_code/squads/bridge.py" \
  --tool "edit_file" \
  --output "diff --git a/bridge.py\n+ exponential_backoff(retry=3)"

# Advance the next execution step
python -m tura_code.squads.bridge step --issue iss-002 --agent "Claude Code" --user "Nitin"

# Message another agent across the cloud
python -m tura_code.squads.bridge message \
  --issue iss-002 \
  --user "Chitranjan" \
  --agent "Antigravity" \
  --to "@Claude-Code" \
  --content "Please expose the WebSocket heartbeat payload schema."
```

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
  squads/                Multi-agent collaboration subsystem:
    bus.py                 Engram Bus (SQLite WAL, event queues, pub/sub)
    models.py              Issue, Squad, ExecutionStep, ExecutionRun dataclasses
    store.py               Thread-safe persistent JSON store with automatic backfill
    service.py             Squad coordination, step state machine, review gate
    routes.py              REST API endpoints (/api/squads, /api/issues, /bridge)
    bridge.py              Standalone CLI bridge for local agent integration
  sessions/              Runtime processes, turns, approvals, host tools
  trust/                 Command classifier & trust ledger
  memory/                Dhee persistent memory gateway
  learning/              Automatic skill extraction & review loop
  flows/                 Git worktree candidate branches & judge evaluation
  launcher.py            Process arguments & credential-scrubbed environments
ui/                      React 19 + TypeScript + Vite frontend:
  src/components/pages/    SquadsPage (Kanban & Multica Execution Room), Trust, Learning
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
