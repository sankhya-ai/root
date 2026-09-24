"""What a session persists, and what one turn accumulates while it runs."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

MODES: tuple[str, ...] = ("default", "accept_edits", "plan", "yolo")


@dataclass
class SessionRecord:
    id: str
    workspace: str
    title: str = "New session"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    permission_mode: str = "default"
    turns: int = 0
    last_status: str = ""
    #: Action classes the owner allowed "for this session" (trust keys).
    grants: list[str] = field(default_factory=list)
    #: "session", or "candidate" for a coding-flow candidate run unattended.
    kind: str = "session"
    #: For a candidate: the session that owns its flow, and which candidate it is.
    parent: str = ""
    role: str = ""

    @classmethod
    def load(cls, path: Path) -> "SessionRecord":
        data = json.loads(path.read_text("utf-8"))
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        tmp = directory / "session.tmp"
        tmp.write_text(json.dumps(asdict(self), indent=2), "utf-8")
        tmp.replace(directory / "session.json")


@dataclass
class TurnState:
    id: str
    prompt: str
    started_at: float = field(default_factory=time.time)
    tool_calls: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_call_id: str = ""
    files_touched: list[str] = field(default_factory=list)
    text: list[str] = field(default_factory=list)
    tool_count: int = 0
    #: Tool calls that came back as errors, and approvals the owner refused.
    errors: int = 0
    rejections: int = 0
    #: Commands this turn that ran something (tests, a script, a build) rather
    #: than only read, and whether an edit has come after the last of them.
    checks: int = 0
    unchecked_edits: bool = False

    def note_edit(self) -> None:
        self.unchecked_edits = True

    def note_check(self) -> None:
        self.checks += 1
        self.unchecked_edits = False

    def note_command(self, command: str) -> None:
        """A command that exercises code checks the edits made before it."""
        from ..trust import classify_command

        if command.strip() and classify_command(command).tier != "read":
            self.note_check()

    @property
    def verified(self) -> bool:
        """No edit this turn is left without a check run after it."""
        return not self.unchecked_edits

    def reply(self) -> str:
        return " ".join("".join(self.text).split())

    def trace(self, limit: int = 40) -> list[dict[str, Any]]:
        """The tool calls of this turn, compact, in order: for reviewers."""
        out = []
        for call in list(self.tool_calls.values())[:limit]:
            out.append(
                {
                    "tool": call["name"],
                    "arguments": call["arguments"][:300],
                    "status": call.get("status", "no result"),
                    "result": call.get("brief", "")[:200],
                }
            )
        return out
