# Vendored runtime

This is `subsystems/sankhya/third_party/kimi-agent-rs` from `tura-learn/tura`
at commit `9bca303bb0d02f3189582ef72e17f488dacc984d`, copied without its
`target/`, `.github/`, `_/` planning notes, and the `kimi-cli` submodule
reference.

Keep local changes small and listed here so upstream updates stay mergeable.

## Local changes

1. **OpenRouter web search** (`kimi-agent/src/tools/web/search.rs`,
   `kimi-agent/src/config.rs`). A new `services.openrouter_search` config
   makes `SearchWeb` use OpenRouter's `web` plugin when no Moonshot search
   service is configured. An empty `base_url`/`api_key` falls back to the main
   provider's, so the host never repeats the key.
2. **`CLAUDE.md` as project instructions** (`kimi-agent/src/soul/agent.rs`).
   Read after `AGENTS.md` and `agents.md`, so a repository set up for Claude
   Code works unchanged.
3. **Model-facing wording** (`kimi-agent/src/tools/file/*.rs`,
   `kimi-agent/src/tools/desc/file/*.md`). "Chotu coding runtimes" became
   "workspace-scoped runtimes" in tool descriptions and one error message.
4. **Removed the `kimi-cli-help` builtin skill**, which documents the Kimi CLI
   rather than this product.

Tests for 1 and 2 are in `search.rs` and `tests/load_agents_md.rs`; the tool
schema and description tests were updated for 3.

## Updating from Tura

```bash
# from a tura checkout
diff -ru subsystems/sankhya/third_party/kimi-agent-rs /path/to/root/runtime \
  -x target -x .github -x _ -x .gitmodules -x .pre-commit-config.yaml -x VENDORED.md
```

Re-apply the changes above, then `cargo test --workspace`.
