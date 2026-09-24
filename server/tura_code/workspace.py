"""Read-only views of a workspace for the UI: files, git changes, folders.

Nothing here writes. Edits belong to the agent, behind its approvals.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

IGNORED_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "target", "dist", "build",
    ".next", ".turbo", ".cache", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".idea",
}
MAX_FILES = 5_000
MAX_READ_BYTES = 1_000_000
MAX_DIFF_BYTES = 400_000


class WorkspaceError(ValueError):
    pass


def resolve_inside(workspace: Path, relative: str) -> Path:
    root = workspace.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise WorkspaceError("Path is outside the workspace.")
    return target


def _git(workspace: Path, *args: str, limit: int = MAX_DIFF_BYTES) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(workspace), *args],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout[:limit].decode("utf-8", errors="replace")


def is_git_repo(workspace: Path) -> bool:
    return _git(workspace, "rev-parse", "--is-inside-work-tree") is not None


def list_files(workspace: Path) -> dict:
    root = workspace.resolve()
    if is_git_repo(root):
        out = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", limit=20_000_000) or ""
        files = sorted({line for line in out.splitlines() if line})
        return {"files": files[:MAX_FILES], "truncated": len(files) > MAX_FILES, "git": True}
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            files.append(str((Path(dirpath) / name).relative_to(root)))
            if len(files) >= MAX_FILES:
                return {"files": files, "truncated": True, "git": False}
    return {"files": files, "truncated": False, "git": False}


def read_file(workspace: Path, relative: str) -> dict:
    path = resolve_inside(workspace, relative)
    if not path.is_file():
        raise WorkspaceError("Not a file.")
    raw = path.read_bytes()[: MAX_READ_BYTES + 1]
    binary = b"\x00" in raw[:8192]
    return {
        "path": relative,
        "binary": binary,
        "truncated": len(raw) > MAX_READ_BYTES,
        "content": "" if binary else raw[:MAX_READ_BYTES].decode("utf-8", errors="replace"),
    }


def git_changes(workspace: Path) -> dict:
    root = workspace.resolve()
    if not is_git_repo(root):
        return {"git": False, "branch": "", "files": [], "diff": ""}
    branch = (_git(root, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all") or ""
    files = []
    for line in status.splitlines():
        if len(line) < 4:
            continue
        code, path = line[:2], line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append({"path": path.strip('"'), "status": code.strip() or "M"})
    diff = _git(root, "diff", "HEAD", "--no-color", "--no-ext-diff") or _git(root, "diff", "--no-color") or ""
    # Untracked files have no diff against HEAD; show them as additions.
    for item in files:
        if item["status"] != "??":
            continue
        try:
            path = resolve_inside(root, item["path"])
            raw = path.read_bytes()[:20_000]
        except (OSError, WorkspaceError):
            continue
        if b"\x00" in raw:
            continue
        body = raw.decode("utf-8", errors="replace").splitlines()
        diff += (
            f"diff --git a/{item['path']} b/{item['path']}\nnew file mode 100644\n--- /dev/null\n+++ b/{item['path']}\n"
            f"@@ -0,0 +1,{len(body)} @@\n" + "".join(f"+{line}\n" for line in body)
        )
        if len(diff) > MAX_DIFF_BYTES:
            break
    return {"git": True, "branch": branch, "files": files, "diff": diff[:MAX_DIFF_BYTES]}


def list_dirs(path: str | None) -> dict:
    """Subdirectories of ``path`` (default: home), for the workspace picker."""
    base = Path(path).expanduser() if path else Path.home()
    base = base.resolve()
    if not base.is_dir():
        raise WorkspaceError("Not a directory.")
    entries = []
    try:
        for child in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            if child.name.startswith(".") or not child.is_dir():
                continue
            entries.append({"name": child.name, "path": str(child), "git": (child / ".git").exists()})
    except PermissionError as error:
        raise WorkspaceError("Permission denied.") from error
    return {
        "path": str(base),
        "parent": str(base.parent) if base.parent != base else None,
        "git": (base / ".git").exists(),
        "entries": entries[:500],
    }
