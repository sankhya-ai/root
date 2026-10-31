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
  - `driver/` is Mac apps: the agent's `mac_*` tools over root-driver (its own signed app, found on PATH or in /Applications), on a local root on a Mac only. Looking never asks; operating an app asks as "operate apps", closing or quitting as "close windows or quit apps"; plan-mode and answering sessions only look. The `mac-apps` runtime skill teaches the loop.
  - `keiki/` is root behind Keiki (WhatsApp, iMessage, Telegram, SMS, email, Slack): its external harness in inbox mode — root claims a turn by polling, runs it in that conversation's `kind="keiki"` read-only, unattended session, and answers and settles it through the turn's API (idempotent sends, lease kept alive). Local mode only.
  - `maritime.py` is Maritime's contract for a custom agent (`GET /health`, `POST /chat` answered within 30 s, a long turn returned on `status`), on only with `TURA_CODE_MARITIME=1`; those two routes skip the host check because the VM is reachable only through Maritime's front door. The repo-root `Dockerfile` and `scripts/maritime-start.py` build and start it with state in `/data`. Slack and Keiki also read their keys from the environment there (`SLACK_BOT_TOKEN`/`SLACK_APP_TOKEN`, `KEIKI_API_KEY`).
  - `catalogue.py` is the dynamic tool catalogue (`dynamic_tools`: documents/GitHub/Gmail/schedules/history/Mac tools found with `find_tools`, run with `use_tool`) and the tool scope (`tool_scope` on settings and on a session). Discovery is not permission: every call passes `allowed`. `guarantee()` states what a scope bounds; a scope that leaves Shell, `process` or `run_python` in is not a boundary.
  - `jobs.py` is `POST /api/jobs`: one unattended session with a role preset, a step cap, the runtime's own per-turn budget (`CHOTU_MAX_TURN_TOKENS`/`_WALL_SECONDS`/`_COST_USD`, from provider-reported usage, checked before each model step), an output contract and `handoff_from` (earlier jobs' contract data, never transcripts). Jobs persist in `jobs/`; one running at a restart becomes `interrupted`. Timeouts and token/cost caps are different things; cost needs a provider that reports it.
  - `registry.py` is the runtime-created tool and role registry (`create_tool`, `create_role`, `registry_list`). A created tool is DECLARATIVE: a fixed pipeline of existing host tools with `${param}` templates - never generated code (specs carrying `code`/`command`/`shell`/`script`/`url` are refused; a new capability is a reviewed plugin). Static validation is deterministic; a valid tool is active in the creating session only (mid-turn through `use_tool` when `dynamic_tools` is on - the gateway dispatches it without any runtime change; otherwise from the next turn, when the runtime refreshes its tool list), and the owner promotes it (`POST /api/registry/tools/{name}/promote`) to offer it to future sessions. Every pipeline step re-passes the calling session's scope and approvals at execution time; composites can never call composites, the gateway or registry tools. A scoped session can author neither a tool nor a role more powerful than its own scope (the creator ceiling). Roles are versioned compositions of existing tools and guides; using one still needs the owner-authenticated job start, and the standing catalogue (`GET /api/jobs/roles`) shows only promoted roles.
  - `visual/` is `inspect_page`: headless Chromium (optional Playwright) on a localhost page or a workspace HTML file; screenshot + page text (untrusted data) + console errors + layout facts. Network limited to the page's own origin, non-GET blocked, viewport/time capped. Not read-only (the page's JS runs), so only the `designer` and `pm` job roles list it. It does not start the app (`process` does, and asks). The screenshot goes to the model only when the model reads images. A role's `verdict` is shape-checked, never a quality gate.
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


## Generated plugins (`propose_tool`, server/tura_code/genplugins.py)

When no pipeline of existing tools can do the job, a session may PROPOSE a generated plugin: model-written Python
that implements a genuinely new tool. The rules, enforced by ordinary code:

* The candidate runs nowhere except a throwaway bubblewrap jail (`--unshare-net`, read-only system and source,
  private scratch workspace, scrubbed environment) until the owner activates one exact SHA-256 content hash via
  `POST /api/registry/plugins/{name}/activate`. Activation re-runs the candidate's own declared tests in the jail
  first; a tampered file or wrong hash refuses.
* The static AST screen (whitelisted stdlib imports, no eval/exec/getattr/dunder escapes) is a FILTER, never a
  safety judgment; the jailed test pass is EVIDENCE, never proof. The trust decision is the owner's.
* No network, packages or secrets for generated code in v1. Needing those means hand-reviewed built-in plugin.
* Every call after activation is a fresh jailed process; revocation takes effect on the next call.
* Lifecycle: draft -> verified -> active -> revoked (terminal). Files are immutable per version; identity is content.

The registry store serializes multi-process read-modify-write with an flock on `registry/.lock` plus atomic
tmp-file writes; parallel creators lose no versions (tested with 6 OS processes).

### Current public practice, primary sources (checked 2026-10-31)

* Anthropic's sandbox-runtime (github.com/anthropics/sandbox-runtime): an open-source wrapper that enforces
  filesystem and network restrictions on arbitrary processes with OS primitives - bubblewrap on Linux, sandbox-exec
  on macOS - and proxy-based network filtering, built for Claude Code and documented for local MCP servers. Root's
  generated-plugin jail uses the same Linux primitive (bubblewrap) with the same default-deny shape: minimal mounts,
  no network. Difference to note: srt adds a domain-allowlisting network proxy; generated plugins get no network at
  all, so no proxy is needed.
* Claude Code sandboxing docs (code.claude.com/docs/en/sandboxing) describe the same model for agent-initiated bash:
  OS-level sandbox with network denied by default, approval gates outside it.
* E2B (e2b.dev/docs) runs agent code in Firecracker microVMs (github.com/firecracker-microvm/firecracker): a
  separate kernel, a stronger boundary than any namespace jail. Root's plugin jail is a namespace sandbox with a
  shared host kernel - the docs in genplugins.py carry that caveat, and a microVM tier is the honest step up if
  generated code ever runs WITHOUT per-hash owner activation.
* Extism (extism.org/docs) and WASI pursue in-process capability isolation via WebAssembly: no ambient authority,
  host-granted functions only. That model constrains plugins to WASM-compilable languages and a host-function ABI;
  Root's candidates are ordinary Python, so this design does not claim the WASM capability model - its whitelist AST
  screen is a FILTER with known bypass surface (dynamic attribute access), and the bubblewrap process is the only
  claimed boundary.
* MCP security best practices (modelcontextprotocol.io/specification/draft/basic/security_best_practices) cover
  confused-deputy and token-passthrough risks for tool servers; the owner-activation gate and per-call scope checks
  here are the local answer, not an equivalence claim.

### Resource limits, stated exactly

Set and tested: in-jail rlimits (CPU 10s, address space 512MB, 16MB per file, 256 fds), a wall-clock kill, a
no-network namespace, minimal read-only mounts (no /etc, /opt, home, tenant root), and hash-pinned snapshot
execution. The GATE is aggregate enforcement: generated code runs only inside a user-scope cgroup whose MemoryMax
(256MB, covering tmpfs scratch writes) and TasksMax (64) are PROBED to be applied - the probe starts a limited scope
and reads back the applied memory.max, and binary presence alone is not accepted. Where that probe fails, candidate
verification, owner activation and invocation all refuse and nothing is stored; there is no unbounded or
experimental execution mode and no override. Hosts without user-scope cgroup support (a plain Linux box without a
systemd user session, macOS) therefore cannot run generated plugins at all: composition tools and roles are
unaffected. RLIMIT_NPROC is per-uid defense-in-depth only. Shared host kernel; a microVM tier is the step up if
generated code ever runs without per-hash owner activation.

### Role selection, grounded in the session's own authority ceiling

"Selecting a role" and "starting a job" are different effects and must not be conflated:

* STARTING a job creates a new unattended session with its own tool scope. That is owner-authenticated
  (POST /api/jobs) and stays so: a session can never widen the system by spawning work.
* SELECTING a role for oneself is a BEHAVIOR choice: which guides load (guides.guides_for / script_role in
  tenancy.py) and which subset of ALREADY-ALLOWED tools are in play. A session's authority ceiling is its tool
  scope, fixed at creation; choosing among capabilities it already holds grants nothing.

Implemented as the `adopt_role` host tool (registry.py), with these exact, tested semantics:

* ELIGIBILITY: built-in presets, durable registry roles, and session-lifetime roles THIS session created - never
  another session's private role (refused with the reason). `version` pins a registry role; a wrong pin refuses.
* NO SELF-GRANT: every tool in the role's scope must already pass `catalogue.allowed` for this session - the
  tenant scope AND the session's own scope, fnmatch patterns included. A role naming a composite is refused
  unless every STEP of that composite is in the ceiling too: naming a composite is not permission for its steps.
* EFFECT, one-way: record.role + record.role_version are pinned and record.tool_scope becomes the role's scope -
  a snapshot copy. Host and gateway calls honor the narrowing in the SAME turn (the gateway re-reads the record
  per call), and native commands, writes, web fetches and outside-workspace reads are rejected from the moment of
  adoption: the approval path (Approvals._approve) checks the sender against the scope BEFORE trust policy, so no
  grant or ledger entry can settle an out-of-scope action. Residual, stated honestly: read-only native tools
  inside the workspace do not ask the host per call, so for them the narrowed native set is guaranteed from the
  NEXT turn, when the launcher spec fingerprint (now including script_role and tool_scope) re-initializes the
  runtime. Same-turn enforcement is therefore NOT claimed for in-workspace read-only native calls. There is no model-side reset: the
  existing owner session endpoint (PATCH /api/sessions/{id}) only supports title and permission mode, so no reset
  was built - a session that needs its wider scope back starts fresh or asks the owner.
* REVOCATION, explicit: revoking the registry role later does NOT widen the session back - the narrowed scope is
  a snapshot and stays; the role's guides simply stop loading (guides_for finds no active role).
* VISIBILITY: the owner sees a `RoleAdopted` notice in the transcript (role, pinned version, narrowed tool count,
  guides) rendered as an info notice. Output contracts of the role are ADVISORY in a chat session and enforced
  only for jobs; both the tool result and the notice say so.
* Adoption that would WIDEN the session refuses and tells the model to ask the owner to start a job with that
  role instead - that is the owner API's effect, not the session's.

### Capability-gap detection (deterministic, not judgment)

The self-extension loop starts with noticing a gap. Detection is ordinary code, never the model validating
itself: every ``find_tools`` miss is tallied on the session record (``capability_misses``, capped at 20), the
miss result itself tells the model the two governed ways to add a capability (``create_tool`` composes,
``propose_tool`` generates code under owner hash activation), and every 3 misses the owner sees a
``CapabilityGap`` transcript notice with the actual queries. A miss is a SIGNAL, not proof that a capability is
missing or that building one succeeds - the model decides what to build, the owner decides what becomes durable.

Decided for adoption (parent steering, 2026-10-31): one-way narrowing for the rest of the session; no reset was
built because the existing owner session endpoint has no safe role/scope control. Still open for Ashish:
1. May a session REQUEST that the owner start a job (a surfaced approval), or is POST /api/jobs strictly
   owner-typed with no agent-initiated approval flow?
2. When a job's role is chosen, may the RECOMMENDING session pick among durable roles, or should recommendations be
   limited to roles the owner has flagged as job-selectable?
