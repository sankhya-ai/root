"""How one kimi-agent process is started for one session.

The runtime takes its model, key and loop limits from a config file, its tools
and prompt from an agent file, and its session from ``--session``. This module
writes the two files and builds the argv and environment; ``sessions`` owns the
process once it runs.

Two properties matter here:

* **The key never reaches the agent's shell.** It is written to a 0600 config
  file rather than passed in the environment, and every ``*_API_KEY`` and
  ``KIMI_*`` variable is removed from the child environment, so a ``Shell``
  call running ``env`` cannot print a credential into the transcript.
* **One base agent, many overlays.** ``agent/agent.yaml`` in the repository is
  the stable base. Per-launch differences (plan mode, the Dhee continuity hook)
  go in a small overlay that ``extend``s it.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .memory import CHECKPOINT_TOOL as MEMORY_CHECKPOINT_TOOL
from .memory import MEMORY_ROLE
from .settings import PermissionMode, Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ENV = "TURA_CODE_RUNTIME"
AGENT_ENV = "TURA_CODE_AGENT"
#: Point this at a scripted-echo script file to run the whole stack without a
#: model: every reply comes from the script. Used by tests and offline demos.
SCRIPTED_ECHO_ENV = "TURA_CODE_SCRIPTED_ECHO"

MUTATING_FILE_TOOLS = (
    "kimi_cli.tools.file:WriteFile",
    "kimi_cli.tools.file:StrReplaceFile",
)

PLAN_MODE_ROLE = """\
You are in PLAN MODE. The owner wants a plan before any change is made.
- Investigate freely with ReadFile, Glob, Grep, and read-only Shell commands (ls, git log, git diff, running tests is fine).
- Do NOT modify files, install packages, or run commands that change state. File-editing tools are unavailable in this mode.
- Finish with a concrete implementation plan: the files to change and what changes in each, the order of work, risks, and how the result will be verified.
- End by asking the owner to approve the plan; they will switch out of plan mode to let you implement it.
"""


class RuntimeNotFound(RuntimeError):
    pass


def find_runtime_binary() -> Path:
    explicit = os.environ.get(RUNTIME_ENV, "").strip()
    candidates = [Path(explicit).expanduser()] if explicit else []
    candidates += [
        REPO_ROOT / "runtime" / "target" / "release" / "kimi-agent",
        REPO_ROOT / "runtime" / "target" / "debug" / "kimi-agent",
    ]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    on_path = shutil.which("kimi-agent")
    if on_path:
        return Path(on_path)
    raise RuntimeNotFound(
        "The kimi-agent runtime binary was not found. Build it with "
        "`cargo build --release --manifest-path runtime/Cargo.toml --bin kimi-agent` "
        f"or set {RUNTIME_ENV}."
    )


def base_agent_file() -> Path:
    explicit = os.environ.get(AGENT_ENV, "").strip()
    path = Path(explicit).expanduser() if explicit else REPO_ROOT / "agent" / "agent.yaml"
    if not path.is_file():
        raise RuntimeNotFound(f"Agent spec not found at {path}; set {AGENT_ENV}.")
    return path.resolve()


@dataclass
class LaunchSpec:
    """Everything that shapes one runtime process. Equal specs share a process."""

    session_id: str
    workspace: Path
    settings: Settings
    permission_mode: PermissionMode
    memory_enabled: bool
    capabilities: list[str] = field(default_factory=list)
    #: The owner's MCP servers (``{"mcpServers": {...}}``). A project's own
    #: ``.mcp.json`` is deliberately NOT loaded: a cloned repository must not
    #: be able to start processes just by being opened.
    mcp_config: Path | None = None

    def fingerprint(self) -> tuple:
        s = self.settings
        return (
            str(self.workspace),
            s.api_key(),
            s.base_url,
            s.model,
            s.max_context_size,
            s.reasoning_effort,
            s.max_steps_per_turn,
            s.director_mode,
            s.web_search,
            s.search_model,
            self.permission_mode == "plan",
            self.memory_enabled,
            tuple(sorted(self.capabilities)),
            _mtime(self.mcp_config),
            os.environ.get(SCRIPTED_ECHO_ENV, ""),
        )


def _mtime(path: Path | None) -> float:
    try:
        return path.stat().st_mtime if path is not None else 0.0
    except OSError:
        return 0.0


def user_mcp_config(root: Path) -> Path | None:
    path = root / "mcp.json"
    return path if path.is_file() else None


def write_agent_overlay(spec: LaunchSpec, runtime_dir: Path) -> Path:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "version: 1",
        "agent:",
        f"  extend: {json.dumps(str(base_agent_file()))}",
        "  name: root",
    ]
    role: list[str] = []
    if spec.memory_enabled:
        lines.append(f"  context_continuity_tool: {MEMORY_CHECKPOINT_TOOL}")
        role += MEMORY_ROLE.splitlines()
    if spec.permission_mode == "plan":
        role += ["", *PLAN_MODE_ROLE.splitlines()] if role else PLAN_MODE_ROLE.splitlines()
    if role:
        lines += ["  system_prompt_args:", "    ROLE_ADDITIONAL: |"]
        lines += [f"      {line}" if line else "" for line in role]
    if spec.permission_mode == "plan":
        lines += ["  exclude_tools:"]
        lines += [f"    - {json.dumps(name)}" for name in MUTATING_FILE_TOOLS]
    path = runtime_dir / "agent.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def runtime_config(settings: Settings, capabilities: list[str] | None = None) -> dict:
    scripted = os.environ.get(SCRIPTED_ECHO_ENV, "").strip()
    context = settings.max_context_size
    reserved = max(4_096, min(50_000, context // 4))
    config: dict = {
        "default_model": "main",
        "default_thinking": settings.reasoning_effort not in ("", "none"),
        "loop_control": {
            "max_steps_per_turn": settings.max_steps_per_turn,
            "max_retries_per_step": 3,
            "max_ralph_iterations": 0,
            "reserved_context_size": reserved,
        },
        "mcp": {"client": {"tool_call_timeout_ms": 60_000}},
    }
    if scripted:
        config["providers"] = {
            "scripted": {"type": "_scripted_echo", "base_url": "", "api_key": ""}
        }
        config["models"] = {
            "main": {"provider": "scripted", "model": "scripted-echo", "max_context_size": context}
        }
        return config
    config["providers"] = {
        # The provider id must be "openrouter": the runtime switches the chat
        # protocol (reasoning, usage accounting) on exactly that name.
        "openrouter": {
            "type": "kimi",
            "base_url": settings.base_url,
            "api_key": settings.api_key(),
            "prompt_cache": True,
            "custom_headers": {
                "HTTP-Referer": "https://github.com/tura-learn/root",
                "X-Title": "root",
            },
        }
    }
    config["models"] = {
        "main": {
            "provider": "openrouter",
            "model": settings.model,
            "max_context_size": context,
            # Explicit, so an image attachment is accepted only by a model that
            # can read it. Thinking is driven by KIMI_MODEL_REASONING_EFFORT.
            "capabilities": sorted(set(capabilities or [])),
        }
    }
    if settings.web_search:
        config["services"] = {"openrouter_search": {"model": settings.search_model}}
    return config


def write_runtime_config(
    settings: Settings, runtime_dir: Path, capabilities: list[str] | None = None
) -> Path:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    path = runtime_dir / "config.json"
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(runtime_config(settings, capabilities), handle)
    os.replace(tmp, path)
    return path


def child_environment(spec: LaunchSpec, share_dir: Path) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not (
            key.endswith("_API_KEY")
            or "_API_KEY_" in key
            or key.startswith("KIMI_")
            or key.startswith("CHOTU_")
            or key.startswith("OPENROUTER_")
            or key.startswith("TURA_CODE_")
        )
    }
    share_dir.mkdir(parents=True, exist_ok=True)
    env["KIMI_SHARE_DIR"] = str(share_dir)
    settings = spec.settings
    director = settings.director_mode
    env["CHOTU_DIRECTOR"] = director
    env["CHOTU_DECISIONS_ENABLED"] = "0" if director == "off" else "1"
    if settings.reasoning_effort:
        env["KIMI_MODEL_REASONING_EFFORT"] = settings.reasoning_effort
    scripted = os.environ.get(SCRIPTED_ECHO_ENV, "").strip()
    if scripted:
        env["KIMI_SCRIPTED_ECHO_SCRIPTS"] = scripted
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def runtime_argv(binary: Path, spec: LaunchSpec, config_file: Path, agent_file: Path) -> list[str]:
    return [
        str(binary),
        "--work-dir",
        str(spec.workspace),
        "--session",
        spec.session_id,
        "--config-file",
        str(config_file),
        "--agent-file",
        str(agent_file),
        *(["--mcp-config-file", str(spec.mcp_config)] if spec.mcp_config else []),
    ]
