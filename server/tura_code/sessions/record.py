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
