"""Where the agent's commands run: directly (the local app) or in a bubblewrap jail.

A hosted install runs other people's agents on one machine, and an agent can
run any shell command it is allowed to. So in hosted mode every runtime
process — and with it every ``Shell`` call, every background process, every
coding-flow check — runs under `bubblewrap <https://github.com/containers/bubblewrap>`_:

* the system (``/usr``, ``/etc``, ``/opt``…) is visible read-only;
* the session's workspace, its runtime directory and the person's home are
  the only writable places; other people's files and the server's own data
  directory are simply not there;
* ``/tmp`` is private, and the process, IPC and hostname namespaces are new;
* the network is shared, because the runtime must reach the model (through
  the host's LLM proxy — the real API key never enters the jail, see
  ``llm_proxy``) and the web.

The wire protocol is stdio, so a wrapped runtime is indistinguishable from a
direct one to the host.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

SYSTEM_PATHS = ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32", "/etc", "/opt", "/nix", "/snap")


@dataclass(frozen=True)
class Mounts:
    workspace: Path
    writable: tuple[Path, ...] = ()
    readable: tuple[Path, ...] = ()
    home: Path | None = None


class Sandbox:
    """No isolation: the local app, where the agent works on the owner's own machine."""

    name = "none"

    def problem(self) -> str:
        return ""

    def wrap(self, argv: list[str], mounts: Mounts) -> list[str]:
        return list(argv)

    def environment(self, env: dict[str, str], mounts: Mounts) -> dict[str, str]:
        return env


class Bubblewrap(Sandbox):
    name = "bwrap"

    def __init__(self, binary: str | None = None, network: bool = True) -> None:
        self.binary = binary or shutil.which("bwrap") or "bwrap"
        self.network = network

    def problem(self) -> str:
        if not shutil.which(self.binary):
            return "bubblewrap (`bwrap`) is not installed."
        try:
            probe = subprocess.run(
                [self.binary, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--unshare-pid", "--die-with-parent", "true"],
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return f"bubblewrap cannot run: {error}"
        if probe.returncode != 0:
            return f"bubblewrap cannot create namespaces here: {probe.stderr.decode(errors='replace').strip()[:300]}"
        return ""

    def wrap(self, argv: list[str], mounts: Mounts) -> list[str]:
        args = [self.binary, "--die-with-parent", "--new-session", "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--unshare-cgroup-try"]
        if not self.network:
            args.append("--unshare-net")
        for path in SYSTEM_PATHS:
            if os.path.islink(path):
                args += ["--symlink", os.readlink(path), path]
            elif os.path.isdir(path):
                args += ["--ro-bind", path, path]
        args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/run"]
        # A resolv.conf that is a symlink into /run must survive the tmpfs.
        resolv = Path("/etc/resolv.conf")
        if resolv.is_symlink():
            target = resolv.resolve()
            if target.exists():
                args += ["--ro-bind", str(target), str(target)]
        for path in mounts.readable:
            if path.exists():
                args += ["--ro-bind", str(path), str(path)]
        writable = [mounts.workspace, *mounts.writable]
        if mounts.home is not None:
            writable.append(mounts.home)
        for path in writable:
            path.mkdir(parents=True, exist_ok=True)
            args += ["--bind", str(path), str(path)]
        args += ["--chdir", str(mounts.workspace)]
        return [*args, "--", *argv]

    def environment(self, env: dict[str, str], mounts: Mounts) -> dict[str, str]:
        env = dict(env)
        if mounts.home is not None:
            env["HOME"] = str(mounts.home)
        env["TMPDIR"] = "/tmp"
        return env


def from_name(name: str) -> Sandbox:
    name = (name or "none").strip().lower()
    if name in ("", "none", "off"):
        return Sandbox()
    if name in ("bwrap", "bubblewrap"):
        return Bubblewrap()
    raise ValueError(f"Unknown sandbox {name!r}; use `bwrap` or `none`.")
