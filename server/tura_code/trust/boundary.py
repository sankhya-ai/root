"""The workspace boundary: what a request reaches outside the session's folder.

A session works in one folder. Reading, listing, or changing anything outside
it — a sibling project, the home directory, another run's files — is the
owner's call in every mode, "Auto-approve all" included: that mode means
"don't ask about work in this project", not "roam the machine". Hosted mode
also confines runtimes with bubblewrap; this is the policy half, and the only
half on a local install.

Commands are read for paths the way a reviewer would: absolute and home paths,
`..` that climbs out, and `cd` changing where later relative paths land. It
is a best effort — code can build a path at run time — so it catches the
ordinary case of an agent wandering off, not a determined one; the sandbox is
what stops that.

Toolchain and system locations every build reads are allowed without asking.
"""

from __future__ import annotations

import os
import re
import shlex

#: Read-only system and toolchain locations any build may touch.
ALLOWED_PREFIXES = (
    "/usr/",
    "/bin/",
    "/sbin/",
    "/lib/",
    "/lib64/",
    "/opt/homebrew/",
    "/usr/local/",
    "/System/",
    "/Library/Developer/",
    "/Library/Frameworks/",
    "/Applications/Xcode.app/",
    "/nix/store/",
    "/proc/self/",
)
ALLOWED_EXACT = {"/dev/null", "/dev/stdin", "/dev/stdout", "/dev/stderr", "/dev/tty", "/dev/urandom", "/dev/random"}
#: Dependency caches and toolchains under the home directory.
ALLOWED_HOME = (".cargo/registry", ".cargo/git", ".rustup", ".npm", ".nvm", ".pyenv", ".cache/pip", ".cache/uv", ".m2", ".gradle", "go/pkg", ".local/share/uv", ".bun")

GRANT_PREFIX = "outside workspace: "

_ABSOLUTE = re.compile(r"(?<![\w.:/$~-])(?:~|\$HOME|\$\{HOME\})?/[\w.@%+=,:-][\w.@%+=,:/-]*|(?<![\w.:/$-])~(?=/|\s|$)")
_PARENT = re.compile(r"(?<![\w./-])\.\.(?:/[\w.@%+=,:-]*)*")
_SPLIT = re.compile(r"&&|\|\||[;|\n]")


def _real(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path))


def inside(path: str, root: str) -> bool:
    real, base = _real(path), _real(root)
    return real == base or real.startswith(base.rstrip("/") + "/")


def allowed(path: str) -> bool:
    """A system or toolchain location, fine to read without asking."""
    real = _real(path)
    if real in ALLOWED_EXACT or path in ALLOWED_EXACT:
        return True
    if any(real.startswith(p) or path.startswith(p) for p in ALLOWED_PREFIXES):
        return True
    home = os.path.realpath(os.path.expanduser("~"))
    return any(real.startswith(os.path.join(home, rel) + "/") or real == os.path.join(home, rel) for rel in ALLOWED_HOME)


def _expand(word: str) -> str:
    return os.path.expanduser(word.replace("${HOME}", "~").replace("$HOME", "~"))


def outside_paths(command: str, workspace: str) -> list[str]:
    """Paths this command reaches outside ``workspace``, resolved, in order.

    Relative paths resolve against the folder the command is in at that point:
    the workspace, or wherever an earlier ``cd`` in the same command went.
    """
    cwd = _real(workspace)
    found: list[str] = []
    for segment in _SPLIT.split(command):
        words = segment.strip()
        if not words:
            continue
        try:
            argv = shlex.split(words)
        except ValueError:
            argv = words.split()
        candidates = [_expand(m) for m in _ABSOLUTE.findall(words)]
        candidates += [os.path.join(cwd, m) for m in _PARENT.findall(words)]
        candidates += ["/" for word in argv[1:] if word == "/"]
        if argv and argv[0] == "cd":
            target = _expand(argv[1]) if len(argv) > 1 else os.path.expanduser("~")
            cwd = _real(os.path.join(cwd, target))
            candidates.append(cwd)
        for candidate in candidates:
            resolved = _real(candidate)
            if not inside(resolved, workspace) and not allowed(resolved) and resolved not in found:
                found.append(resolved)
    return found


def granted(path: str, grants: set[str] | frozenset[str]) -> bool:
    """Whether "Allow for this session" already covers ``path``."""
    for grant in grants:
        if grant.startswith(GRANT_PREFIX) and inside(path, grant[len(GRANT_PREFIX) :]):
            return True
    return False


def grant_key(path: str) -> str:
    """The session grant for this path: its folder, so siblings are covered too."""
    real = _real(path)
    folder = real if os.path.isdir(real) else os.path.dirname(real)
    return GRANT_PREFIX + folder


def path_in(description: str) -> str:
    """The path in a runtime approval description ("Read `x`", "Write file `x`")."""
    match = re.search(r"`([^`]+)`", description or "")
    return match.group(1) if match else ""
