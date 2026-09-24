# root

A coding agent in your browser — as a local app, or hosted for many people — built from Tura's own parts:

- **kimi-agent-rs** — Tura's agent runtime (Rust): the observe-plan-act loop, file/search/shell/web/todo/subagent tools, approvals, compaction, sessions, skills, MCP.
- **Jev** (`typesafe/jev-1.13`) — the step director inside that runtime. Before each step it decides whether the model should reply or which tool to call, so smaller models stop *describing* work and start *doing* it.
- **Dhee** — the memory layer: project conventions, commands, decisions and your preferences persist across sessions and come back when relevant.
- **Chotu Coder's machinery, working** — the trust ledger, the Hermes-style learning loop, background processes, and native coding flows, ported and tested end to end.
- **The Tura UI** — Tura's deployed identity (mark, ruled-paper grounds, glass cards, outlined and ink pills) and Chotu's coding-mode transcript.

Every model call goes through **OpenRouter**. Web search is **free**: keyless Parallel and Firecrawl search, no key needed.

```text
 browser (ui/) ──WebSocket──► host (server/tura_code) ──JSON-RPC/stdio──► kimi-agent (runtime/)  [in a bubblewrap jail when hosted]
   transcript, approvals,       tenants · sessions · trust policy           agent loop + Jev director
   flows, learning, trust       Dhee · learning loop · coding flows         Read/Edit/Glob/Grep/Shell/Web/Todo/Task
                                processes · LLM proxy · runtime pool               │
                                      │                                             ├─► host tools: memory_*, process, coding_flow
                                      └──── OpenRouter ◄── /llm/api (token → key) ──┘
```

## Built for weaker, cheaper models

The default model is `deepseek/deepseek-v4-flash`. The harness carries what a small model gets wrong:

- **Jev** picks reply-or-tool before each step.
- **Argument repair** — almost-JSON tool arguments (code fences, raw newlines in a `WriteFile` string, trailing commas, double encoding) are recovered losslessly; cut-off arguments are completed only for read-only tools, never for writes or commands.
- **Whitespace-tolerant edits** — a `StrReplaceFile` whose `old` text is right but mis-indented is matched line by line (uniquely) and the replacement re-indented to the file.
- **Repeat nudge** — the third identical call with an identical result gets a note to change approach, instead of looping to the step limit.
- **`Glob("**/*.py")` works** — recursive patterns walk the tree and skip `node_modules`, `.git`, build and cache directories, instead of being refused.
- **Dhee** attaches the relevant memories and learned skills, so the model does not have to rediscover the project each session.

## What it does

- **Multi-file changes** with diffs, verified by the project's own tests or build.
- **Chotu-style turns** — your message, then root's answer with quiet trace lines (“Read 2 files, searched code”, “Edited 2 files”) that open to diffs and output; approval cards inline; a working orb with elapsed time; time and Copy under each turn.
- **Permission modes** (Shift+Tab): *Ask before acting* · *Accept edits* · *Plan* (read-only, ends with an **Approve plan** bar) · *Auto-approve all*.
- **Trust ledger** — read-only commands run at once; project checks (tests, lint, type checks) run in *Accept edits*; anything that can change state asks. Approve a command class three times in a row and root stops asking; one rejection takes the trust back. The classifier is default-deny and splits shell punctuation, so `echo hi;rm x` is two commands. See **Trust** in the sidebar.
- **Learning loop** — after a turn that did real work, failed, or stated a preference, a reviewer proposes **skills** (written as `SKILL.md`, loaded into every later session) and **memories** (Dhee). Lessons tied to one task are filtered out; secrets are redacted. *Ask me* (default) queues them on the **Learning** page; *Automatic* keeps them. Skills keep their history and roll back.
- **Coding flows** — for a substantial change, root builds 1–3 candidates in isolated Git worktrees, each with its own agent, runs your verification commands on every candidate, repairs failures from the exact test output, and a judge picks the best verified patch. You review the diff and apply it (bound to its hash) as a merge; rollback reverts exactly that merge.
- **Background processes** — the `process` tool starts dev servers and watchers, polls them, reads their logs, sends stdin, and stops them; the **Processes** panel shows them.
- **Memory**, **subagents** (`explorer`, `coder`), **skills**, **slash commands** (`/init`, `/compact`, `/clear`, `/yolo`, `/skill:…`), **`@file` mentions**, image and file attachments, **web search and fetch**, **MCP servers** from `~/.tura-code/mcp.json` (never a project's own `.mcp.json`).

## Quick start (local app)

Prerequisites: Rust (stable), Python 3.11+, Node 22.

```bash
make build                         # runtime (cargo), host (venv + pip), UI (vite)
export OPENROUTER_API_KEY=sk-or-…  # or paste it in Settings
make run                           # http://localhost:8787
```

Type what you want on the home page, choose a folder, press Enter. `make doctor` checks the runtime, the agent spec, Dhee, the sandbox and the key.

### Try it without a key

```bash
TURA_CODE_SCRIPTED_ECHO=script.json TURA_CODE_SCRIPTED_LLM=answers.json server/.venv/bin/tura-code
```

`script.json` holds the model's replies in the runtime's echo DSL (`text: …`, `tool_call: {…}`), as a list — or an object mapping a process role (`main`, `candidate_1`…) to a list. `answers.json` maps `review`/`judge` to the reviewer's and judge's answers. See `server/tests/`.

## Hosting it

On a Linux host with bubblewrap (`apt install bubblewrap`), from a clone after `make build`:

```bash
server/.venv/bin/tura-code user add alice --name "Alice"   # prints Alice's sign-in token once
TURA_CODE_ALLOWED_HOSTS=root.example.com \
OPENROUTER_API_KEY=sk-or-… \
  server/.venv/bin/tura-code serve --hosted --host 0.0.0.0  # behind an HTTPS reverse proxy
```

(`make build` installs the host in editable mode, so it finds `agent/` and the runtime binary in the clone; a packaged install sets `TURA_CODE_AGENT` and `TURA_CODE_RUNTIME`.)

Each person gets a private tenant: their own sessions, settings (and optionally their own key), trust ledger, learned skills, Dhee owner scope, and a workspace folder they can create or `git clone` into. In hosted mode:

- **Every runtime, background process, coding-flow check and clone runs in bubblewrap**: the system read-only, only the session's workspace, runtime directory and the person's home writable; other people's data and the server's own directory do not exist inside. The server refuses to start hosted without a working sandbox.
- **No runtime holds an API key.** Runtimes talk to the model through the host's LLM proxy (`/llm/api`) with a per-launch token; the proxy swaps it for the person's key or the operator's.
- **Runtimes are pooled**: per-person and total caps, least-recently-active idle runtimes are stopped to make room (their conversations resume on the next prompt), and idle ones are reaped.
- Sign-in is a token in an `HttpOnly`, `SameSite=Strict`, `Secure` cookie. `tura-code user list|rotate|remove` manage people.

Web search's keyless tiers are limited per IP address, so a shared server should set Parallel and Firecrawl keys in Settings.

## Configuration

Settings live in the UI and in `settings.json` (0600) under the data directory.

| Setting | Default | Notes |
| --- | --- | --- |
| Coding model | `deepseek/deepseek-v4-flash` | Any OpenRouter model with tool support. |
| Jev director | on | `on`, `shadow` (record only), `off`. |
| Dhee memory | local | `local` (offline, lexical), `openrouter` (embeddings), `off`. |
| Web search | on, keyless | Parallel, then Firecrawl; optional keys; optional paid OpenRouter fallback. |
| Learning | Ask me | `review`, `auto`, `off`; the reviewer and judge use the coding model unless set. |
| New sessions start in | Ask before acting | Default permission mode. |

| Variable | Purpose |
| --- | --- |
| `OPENROUTER_API_KEY` | The key (local: overrides settings; hosted: the operator's default). |
| `TURA_CODE_HOME` | Data directory (default `~/.tura-code`). |
| `TURA_CODE_HOST`, `TURA_CODE_PORT` | Listen address (default `127.0.0.1:8787`). |
| `TURA_CODE_MODE`, `TURA_CODE_SANDBOX` | `hosted` / `bwrap`, as the CLI flags. |
| `TURA_CODE_ALLOWED_HOSTS` | Hostnames to accept; required to listen beyond localhost. |
| `TURA_CODE_TOKEN` | Fixed local API token for scripts. |
| `TURA_CODE_RUNTIME`, `TURA_CODE_AGENT` | A `kimi-agent` binary / agent spec other than the repository's. |
| `TURA_CODE_SCRIPTED_ECHO`, `TURA_CODE_SCRIPTED_LLM` | Scripted model and reviewer/judge, for tests and demos. |

## Security model

- Local-only by default: the `Host` header is checked (DNS rebinding), the API and WebSocket need the same-site cookie, and the WebSocket checks `Origin`.
- No credential in any runtime's environment or file (the LLM proxy); `*_API_KEY`, `KIMI_*`, `OPENROUTER_*` are scrubbed from every command's environment.
- Approvals as above; edits outside the workspace and coding-flow applies always ask; unattended flow candidates can only edit, read and run checks.
- Hosted: bubblewrap per runtime and command, confined workspaces, per-person memory scopes.

## Repository layout

```text
agent/            the agent spec: tools, subagents, system prompt
runtime/          kimi-agent-rs, vendored from Tura (runtime/VENDORED.md lists every change)
server/tura_code/
  app/              HTTP + WebSocket API (routes split by area), auth
  sessions/         a session: runtime process, turns, approvals, host tools, prompts
  tenancy.py        local vs hosted: the server and each person's tenant
  trust/            command classifier, trust ledger, approval policy
  memory/           Dhee gateway, per-person views, memory tools
  learning/         the reviewer, candidate store, skill library
  flows/            coding flows: worktrees, runner, judge, apply/rollback, tool
  processes.py      background processes (the `process` tool)
  sandbox.py        bubblewrap
  llm_proxy.py      runtimes reach the model with a token, not a key
  pool.py           runtime caps and eviction
  events.py         the event log, read in bounded pages
server/tests/     unit + end-to-end tests against the real runtime binary
ui/               React + Vite + TypeScript
```

## Development

```bash
make test     # runtime (cargo test), host (pytest, end to end), UI (node --test + tsc)
make dev      # host on :8787 + Vite on :5173
```

The end-to-end tests drive the real runtime with scripted replies: multi-file edits and approvals, every permission mode, the trust ledger (promotion, session grants, revocation), background processes, the learning loop (a promoted skill loaded by the next runtime), coding flows (repair, judging, apply, rollback), hosted isolation inside a real bubblewrap jail, the LLM proxy, runtime eviction, Dhee across sessions, and paging. `TURA_CODE_LIVE_SEARCH=1` also runs a real keyless web search.

## Where the parts come from

- `runtime/` — `subsystems/sankhya/third_party/kimi-agent-rs` from `tura-learn/tura` (Moonshot AI's Kimi Code CLI in Rust, Apache-2.0; `runtime/LICENSE`, `runtime/NOTICE`) with Tura's Jev director, completion gate and Dhee continuity hook.
- Trust ledger, learning reviewer, coding flows — ported from Chotu (`apps/hub/chotu_hub/agent_core/coder_approvals.py`, `assistant_runtime/self_improvement.py`, `assistant_runtime/native_coding.py`), with the fixes noted in each module.
- Dhee — the `dhee` package (7.4.x), in-process through a typed gateway.
- UI identity — the Tura mark, palette, textures and GeistPixel (Vercel, SIL OFL 1.1) from `apps/dashboard`.

## Not there yet

- No file-level checkpoints to rewind edits outside coding flows (use git; the Changes panel shows everything).
- No terminal UI; no lifecycle hooks.
- Jev needs an OpenRouter-shaped endpoint; elsewhere the model steers alone.
- Local memory recall is lexical; switch Dhee to `openrouter` for semantic recall.
