# root

A coding agent in your browser, built from Tura's own parts:

- **kimi-agent-rs** — Tura's agent runtime (Rust). One observe-plan-act loop with file, search, shell, web, todo and subagent tools, approvals, context compaction, sessions, skills, and MCP.
- **Jev** (`typesafe/jev-1.13`) — the step director inside that runtime. Before each step it decides whether the model should reply or which tool it should call, so smaller models stop *describing* work and start *doing* it.
- **Dhee** — the memory layer. Project conventions, commands, decisions, and your preferences persist across sessions and come back when they're relevant.
- **The Tura UI** — Tura's visual identity (mark, charcoal/paper grounds, the one loud gradient) on a coding-agent interface.

Every model call goes through **OpenRouter**: one key covers the agent, Jev, web search, and Dhee's embeddings.

```text
 browser (ui/)  ──WebSocket──►  host (server/tura_code)  ──JSON-RPC over stdio──►  kimi-agent (runtime/)
   transcript, diffs,             sessions, permission modes,                     agent loop + Jev director
   approvals, plan, changes       Dhee memory gateway, API                         tools: Read/Write/Edit/Glob/
                                        │                                           Grep/Shell/Web/Todo/Task
                                        ▼                                                  │
                                      Dhee  ◄──── memory_recall / remember / checkpoint ────┘
                                                                                           │
                                                                    OpenRouter ◄───────────┘
```

## What it does

- **Multi-file changes.** Reads, searches, and edits across the project (batched multi-edit replace, whole-file writes), then runs the tests or build to verify.
- **Approvals with diffs.** Every edit and command shows up for approval with a line diff or the exact command. Approve once, approve for the session, or reject.
- **Permission modes** (Shift+Tab cycles): *Ask before acting* · *Accept edits* (workspace edits auto-approved, commands still ask) · *Plan* (read-only investigation, then a plan) · *Auto-approve all*.
- **Plans.** Multi-step work is tracked in a todo list, shown live in the Plan panel.
- **Subagents.** `explorer` (read-only research) and `coder` (a scoped change, verified) run through the `Task` tool; their steps nest under the call.
- **Memory.** Dhee attaches relevant memories to a request (shown as chips under your message) and restores durable context after compaction. The agent can `memory_recall`, `memory_remember`, and `memory_checkpoint`. Browse and forget memories in the Memory panel.
- **Project instructions.** `AGENTS.md` (or `CLAUDE.md`) at the project root is loaded into the system prompt. `/init` writes one.
- **Skills.** `SKILL.md` packs from `~/.claude/skills`, `~/.agents/skills`, `<project>/.claude/skills`, … are listed as `/skill:<name>` commands.
- **Slash commands.** `/init`, `/compact`, `/clear`, `/yolo`, `/skill:…`, `/flow:…`.
- **`@file` mentions** attach file contents; paste or drop images (for vision models) and text files.
- **Web.** `SearchWeb` through OpenRouter's web plugin, `FetchURL` for pages.
- **Sessions** persist and resume, per workspace. **Changes** shows the git diff of the workspace; **Files** browses it; **Jev** shows the director's per-step decisions.
- **MCP servers.** Put them in `~/.tura-code/mcp.json` (the usual `{"mcpServers": {…}}` format); their tools join the agent's. A project's own `.mcp.json` is not loaded automatically, so opening a repository can't start processes.

## Quick start

Prerequisites: Rust (stable), Python 3.11+, Node 22.

```bash
make build                         # runtime (cargo), host (venv + pip), UI (vite)
export OPENROUTER_API_KEY=sk-or-…  # or paste it in Settings
make run                           # http://localhost:8787
```

Open the UI, click **New session**, pick a project folder, and ask for a change.

`make doctor` checks the runtime binary, the agent spec, Dhee, and the key.

### Try it without a key

The runtime has a scripted model for tests. Point the host at a script and the whole stack runs offline:

```bash
TURA_CODE_SCRIPTED_ECHO=/path/to/script.json server/.venv/bin/tura-code
```

A script is a JSON list of replies, one per model call, in the echo DSL (`text: …`, `tool_call: {"id": …, "name": …, "arguments": "<json>"}`). See `server/tests/test_e2e.py`.

## Configuration

Settings live in the UI (gear icon) and are stored in `~/.tura-code/settings.json` (mode 0600).

| Setting | Default | Notes |
| --- | --- | --- |
| Coding model | `qwen/qwen3-coder` | Any OpenRouter model with tool support; the picker lists them. |
| Context window | from the model | The runtime compacts before it runs out. |
| Reasoning effort | model default | Sent as OpenRouter `reasoning.effort`. |
| Jev director | on | `on` steers each step; `shadow` records decisions only; `off`. |
| Dhee memory | local | `local` works offline (lexical recall); `openrouter` uses `openai/text-embedding-3-small` and `openai/gpt-4o-mini` for enrichment; `off`. |
| Web search | on | OpenRouter web plugin via `openai/gpt-4o-mini`. |
| New sessions start in | Ask before acting | Default permission mode. |

Environment variables:

| Variable | Purpose |
| --- | --- |
| `OPENROUTER_API_KEY` | Overrides the key stored in settings. |
| `TURA_CODE_HOME` | Data directory (default `~/.tura-code`). |
| `TURA_CODE_PORT`, `TURA_CODE_HOST` | Listen address (default `127.0.0.1:8787`). |
| `TURA_CODE_ALLOWED_HOSTS` | Extra hostnames to accept; required to listen beyond localhost. |
| `TURA_CODE_TOKEN` | Fixed API token for scripts (`Authorization: Bearer …`). |
| `TURA_CODE_RUNTIME` | Path to a `kimi-agent` binary (default: `runtime/target/release`). |
| `TURA_CODE_AGENT` | Path to an agent spec (default: `agent/agent.yaml`). |
| `TURA_CODE_SCRIPTED_ECHO` | Scripted model replies for offline runs and tests. |

## Security model

The agent runs commands on your machine, so the host is local-only by default and treats the browser as hostile:

- It listens on `127.0.0.1` and rejects requests whose `Host` isn't allowed (DNS-rebinding defence).
- The API and WebSocket require a token held in an `HttpOnly`, `SameSite=Strict` cookie, so another site can't drive the agent; the WebSocket also checks `Origin`.
- The OpenRouter key reaches the runtime through a 0600 config file, never its environment, and `*_API_KEY` variables are stripped from the runtime's environment — so a `Shell` call can't print a credential into the transcript.
- File and shell tools ask for approval unless you pick a mode that auto-approves them. Edits outside the workspace always ask, even in *Accept edits*.

## Repository layout

```text
agent/          the root agent spec: tools, subagents, system prompt
runtime/        kimi-agent-rs, vendored from Tura (see runtime/VENDORED.md)
  kimi-agent/     agent loop (soul/), Jev director (soul/director.rs, soul/decision.rs),
                  tools, wire protocol, sessions, skills, MCP
  kosong/         LLM abstraction; OpenRouter chat-completions protocol
  kaos/           OS abstraction
server/         the host (Python, FastAPI)
  tura_code/      launcher, wire client, sessions, Dhee gateway, workspace views, API
  tests/          unit tests + end-to-end tests against the real runtime binary
ui/             the web UI (React, Vite, TypeScript)
```

## Development

```bash
make test          # runtime (cargo test), host (pytest, incl. end-to-end), UI (node --test + tsc)
make dev           # host on :8787 + Vite on :5173 with hot reload
```

The host's end-to-end tests drive the real runtime binary with scripted model replies: multi-file edits with approvals, accept-edits and plan modes, Dhee memory across sessions, cancellation, the git changes view, and slash commands.

## Where the parts come from

- `runtime/` — `subsystems/sankhya/third_party/kimi-agent-rs` from `tura-learn/tura`, which is Moonshot AI's Kimi Code CLI rewritten in Rust (Apache-2.0; `runtime/LICENSE`, `runtime/NOTICE`) plus Tura's Jev director, completion gate, and Dhee continuity hook. Local changes are listed in `runtime/VENDORED.md`.
- Dhee — the `dhee` package (7.4.x, same range Tura pins), used in-process through a typed gateway (`server/tura_code/memory.py`), the way Tura's hub owns it.
- UI identity — the Tura mark, palette, ground textures, and the GeistPixel face from `tura-learn/tura` `apps/dashboard`. GeistPixel is from Vercel's Geist family (SIL Open Font License 1.1).

## Not there yet

- No file-level checkpoints to rewind edits (use git; the Changes panel shows everything).
- No lifecycle hooks, no terminal UI.
- Jev needs OpenRouter; with another provider the director stays off and the model steers alone.
- Local memory recall is lexical; switch Dhee to `openrouter` for semantic recall.
