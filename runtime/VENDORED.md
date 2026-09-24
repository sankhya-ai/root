# Vendored runtime

This is `subsystems/sankhya/third_party/kimi-agent-rs` from `tura-learn/tura`
at commit `9bca303bb0d02f3189582ef72e17f488dacc984d`, copied without its
`target/`, `.github/`, `_/` planning notes, and the `kimi-cli` submodule
reference.

Keep local changes small and listed here so upstream updates stay mergeable.

## Local changes

1. **Web search backends** (`kimi-agent/src/tools/web/search/`,
   `kimi-agent/src/config.rs`). `search.rs` became a module with one file per
   backend. `services.web_search` adds the keyless **Parallel** (anonymous MCP
   endpoint, one stateless `tools/call`) and **Firecrawl Keyless** backends,
   tried in order with fallback; keys are optional. `services.openrouter_search`
   (OpenRouter's paid `web` plugin) is the last resort when configured; an
   empty `base_url`/`api_key` falls back to the main provider's. Moonshot's
   service, when configured, is used alone as before.
2. **`CLAUDE.md` as project instructions** (`kimi-agent/src/soul/agent.rs`).
   Read after `AGENTS.md` and `agents.md`, so a repository set up for Claude
   Code works unchanged.
3. **Model-facing wording** (`kimi-agent/src/tools/file/*.rs`,
   `kimi-agent/src/tools/desc/file/*.md`). "Chotu coding runtimes" became
   "workspace-scoped runtimes" in tool descriptions and one error message.
4. **Removed the `kimi-cli-help` builtin skill**, which documents the Kimi CLI
   rather than this product.
5. **Extra skill roots** (`kimi-agent/src/skill/mod.rs`).
   `KIMI_EXTRA_SKILLS_DIRS` (path-list) adds roots after the built-in skills
   and before the user's and project's, so the host's learned skills load and
   an owner's own skill wins on a name clash.
6. **Tool-argument repair for weaker models** (`kimi-agent/src/soul/args_repair.rs`,
   moved out of `toolset.rs`). Lossless repairs (code fences, raw control
   characters in strings, trailing commas, double encoding) for every tool;
   completing cut-off arguments only for read-only tools, and `Shell` only
   with a closed command string.
7. **Whitespace-tolerant `StrReplaceFile`** (`kimi-agent/src/tools/file/tolerant.rs`).
   When `old` is not found exactly, a unique line-by-line match ignoring
   trailing (then surrounding) whitespace is applied, re-indenting the
   replacement; the result says so.
8. **Repeat nudge** (`kimi-agent/src/soul/repeat_guard.rs`, wired in
   `kimisoul.rs`). The third identical call with an identical result this
   turn gets a note in the model's context; wire events are unchanged.
9. **Recursive `Glob`** (`kimi-agent/src/tools/file/walk.rs`, `glob.rs`,
   `desc/file/glob.md`). Patterns starting with `**` walk the tree, pruning
   dependency, VCS, build and cache directories and bounding the walk, instead
   of being refused (local workspaces only).

Tests: `search/tests.rs` (backends and fallback against a mock server) and
`tests/load_agents_md.rs` for 1–2; the tool schema and description tests were
updated for 3 and 9; `tests/extra_skills_dirs.rs` for 5; unit tests in
`args_repair.rs`, `tolerant.rs`, `repeat_guard.rs` and `walk.rs`, and
`tests/tool_glob.rs` (rewritten for the pruned walk) for 6–9.

## Updating from Tura

```bash
# from a tura checkout
diff -ru subsystems/sankhya/third_party/kimi-agent-rs /path/to/root/runtime \
  -x target -x .github -x _ -x .gitmodules -x .pre-commit-config.yaml -x VENDORED.md
```

Re-apply the changes above, then `cargo test --workspace`.
