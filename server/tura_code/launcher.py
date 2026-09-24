"""How one kimi-agent process is started for one session.

The runtime takes its model, endpoint and loop limits from a config file, its
tools and prompt from an agent file, and its session from ``--session``. This
module writes the two files and builds the argv and environment; ``sessions``
owns the process once it runs.

What matters here:

* **No key where the agent can read it.** With the host's LLM proxy (always
  on when the server runs), the config holds a per-launch token, not the key.
  Without it (tests, embedding), the key is in a 0600 file. Either way every
  ``*_API_KEY``, ``KIMI_*`` and ``OPENROUTER_*`` variable is scrubbed from the
  environment, so ``env`` in a ``Shell`` call prints no credential.
* **One base agent, many overlays.** ``agent/agent.yaml`` is the stable base;
  per-launch differences (plan mode, the Dhee continuity hook) go in a small
  overlay that ``extend``s it.
* **What the process can see.** In hosted mode the argv is wrapped by the
  sandbox (see ``sandbox``); locally it is not.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .memory import CHECKPOINT_TOOL as MEMORY_CHECKPOINT_TOOL
from .memory import MEMORY_ROLE
from .sandbox import Mounts, Sandbox
from .settings import PermissionMode, Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ENV = "TURA_CODE_RUNTIME"
AGENT_ENV = "TURA_CODE_AGENT"
#: Point this at a scripted-echo script to run the whole stack without a model.
#: A JSON list scripts every process; a JSON object maps a process role
#: ("main", "candidate_1", …) to its own list. Used by tests and offline demos.
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


def scripted() -> bool:
    """Whether replies come from a scripted-echo script instead of a model."""
    return bool(os.environ.get(SCRIPTED_ECHO_ENV, "").strip())


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] if text else ""


@dataclass
class LaunchSpec:
    """Everything that shapes one runtime process. Equal fingerprints share a process."""

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
    #: The key in effect, resolved by the tenant. Empty: the settings' key.
    api_key: str = ""
    #: (base URL, token) of the host's LLM proxy for this launch, or None to
    #: give the runtime the key directly.
    endpoint: tuple[str, str] | None = None
    #: Extra skill roots: the skills this tenant's learning loop promoted.
    skills_dirs: tuple[Path, ...] = ()
    #: Which list of a scripted-echo object script this process plays.
    script_role: str = "main"
    sandbox: Sandbox = field(default_factory=Sandbox)
    session_dir: Path | None = None
    home: Path | None = None

    def key(self) -> str:
        return self.api_key or self.settings.api_key()

    def fingerprint(self) -> tuple:
        s = self.settings
        return (
            str(self.workspace),
            "proxy" if self.endpoint else _digest(self.key()),
            s.base_url,
            s.model,
            s.max_context_size,
            s.reasoning_effort,
            s.max_steps_per_turn,
            s.director_mode,
            (s.web_search, s.web_search_paid_fallback, _digest(s.parallel_api_key), _digest(s.firecrawl_api_key), s.search_model),
            self.permission_mode == "plan",
            self.memory_enabled,
            tuple(sorted(self.capabilities)),
            _mtime(self.mcp_config),
            os.environ.get(SCRIPTED_ECHO_ENV, ""),
            skills_signature(self.skills_dirs),
            self.sandbox.name,
        )

    def mounts(self, binary: Path) -> Mounts:
        readable = [binary.parent, base_agent_file().parent, REPO_ROOT / "runtime" / "kimi-agent" / "src" / "skills", *self.skills_dirs]
        if self.mcp_config is not None:
            readable.append(self.mcp_config.parent)
        writable = (self.session_dir,) if self.session_dir is not None else ()
        return Mounts(workspace=self.workspace, writable=writable, readable=tuple(readable), home=self.home)


def skills_signature(dirs: tuple[Path, ...]) -> tuple:
    """Changes whenever a skill in these directories is added, edited or removed."""
    entries = []
    for root in dirs:
        for skill in sorted(root.glob("*/SKILL.md")) if root.is_dir() else []:
            try:
                entries.append((str(skill), skill.stat().st_mtime_ns))
            except OSError:
                continue
    return tuple(entries)


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


def runtime_config(spec: LaunchSpec) -> dict:
    settings = spec.settings
    context = settings.max_context_size
    config: dict = {
        "default_model": "main",
        "default_thinking": settings.reasoning_effort not in ("", "none"),
        "loop_control": {
            "max_steps_per_turn": settings.max_steps_per_turn,
            "max_retries_per_step": 3,
            "max_ralph_iterations": 0,
            "reserved_context_size": max(4_096, min(50_000, context // 4)),
        },
        "mcp": {"client": {"tool_call_timeout_ms": 60_000}},
    }
    if scripted():
        config["providers"] = {"scripted": {"type": "_scripted_echo", "base_url": "", "api_key": ""}}
        config["models"] = {"main": {"provider": "scripted", "model": "scripted-echo", "max_context_size": context}}
    else:
        base_url, key = spec.endpoint if spec.endpoint else (settings.base_url, spec.key())
        config["providers"] = {
            # The provider id must be "openrouter": the runtime switches the chat
            # protocol (reasoning, usage accounting) on exactly that name.
            "openrouter": {
                "type": "kimi",
                "base_url": base_url,
                "api_key": key,
                "prompt_cache": True,
                "custom_headers": {"HTTP-Referer": "https://github.com/tura-learn/root", "X-Title": "root"},
            }
        }
        config["models"] = {
            "main": {
                "provider": "openrouter",
                "model": settings.model,
                "max_context_size": context,
                # Explicit, so an image attachment is accepted only by a model that
                # can read it. Thinking is driven by KIMI_MODEL_REASONING_EFFORT.
                "capabilities": sorted(set(spec.capabilities)),
            }
        }
    if settings.web_search:
        services: dict = {
            "web_search": {
                "order": ["parallel", "firecrawl"],
                "parallel_api_key": settings.parallel_api_key,
                "firecrawl_api_key": settings.firecrawl_api_key,
            }
        }
        if settings.web_search_paid_fallback and not scripted():
            services["openrouter_search"] = {"model": settings.search_model}
        config["services"] = services
    return config


def write_runtime_config(spec: LaunchSpec, runtime_dir: Path) -> Path:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    path = runtime_dir / "config.json"
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(runtime_config(spec), handle)
    os.replace(tmp, path)
    return path


def scrubbed_environment() -> dict[str, str]:
    """The host's environment without credentials or host/runtime switches.

    What the agent's commands see: the runtime's ``Shell`` and the host's
    background processes alike.
    """
    return {
        key: value
        for key, value in os.environ.items()
        if not (
            key.endswith("_API_KEY")
            or "_API_KEY_" in key
            or key.startswith(("KIMI_", "CHOTU_", "OPENROUTER_", "TURA_CODE_"))
        )
    }


def _scripted_file(spec: LaunchSpec, runtime_dir: Path) -> str:
    """This process's script, copied next to its config (inside any sandbox)."""
    source = os.environ.get(SCRIPTED_ECHO_ENV, "").strip()
    try:
        data = json.loads(Path(source).read_text("utf-8"))
    except (OSError, ValueError):
        return source
    if isinstance(data, dict):
        fallback = "candidate" if spec.script_role.startswith("candidate") else "main"
        data = data.get(spec.script_role, data.get(fallback, []))
    runtime_dir.mkdir(parents=True, exist_ok=True)
    path = runtime_dir / "script.json"
    path.write_text(json.dumps(data), "utf-8")
    return str(path)


def child_environment(spec: LaunchSpec, share_dir: Path, binary: Path | None = None) -> dict[str, str]:
    env = scrubbed_environment()
    share_dir.mkdir(parents=True, exist_ok=True)
    env["KIMI_SHARE_DIR"] = str(share_dir)
    settings = spec.settings
    director = settings.director_mode
    env["CHOTU_DIRECTOR"] = director
    env["CHOTU_DECISIONS_ENABLED"] = "0" if director == "off" else "1"
    if settings.reasoning_effort:
        env["KIMI_MODEL_REASONING_EFFORT"] = settings.reasoning_effort
    if spec.skills_dirs:
        env["KIMI_EXTRA_SKILLS_DIRS"] = os.pathsep.join(str(p) for p in spec.skills_dirs)
    if os.environ.get(SCRIPTED_ECHO_ENV, "").strip():
        env["KIMI_SCRIPTED_ECHO_SCRIPTS"] = _scripted_file(spec, share_dir.parent / "runtime")
    env.setdefault("PYTHONUNBUFFERED", "1")
    if binary is not None:
        env = spec.sandbox.environment(env, spec.mounts(binary))
    return env


def runtime_argv(binary: Path, spec: LaunchSpec, config_file: Path, agent_file: Path) -> list[str]:
    argv = [
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
    return spec.sandbox.wrap(argv, spec.mounts(binary))
