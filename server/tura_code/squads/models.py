"""Data models for multi-human and multi-agent squads, issues, and handoffs."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

IssueStatus = Literal["backlog", "in_progress", "blocked", "in_review", "done"]
IssuePriority = Literal["low", "medium", "high", "urgent"]
WorkspaceScope = Literal["personal", "shared"]
AgentType = Literal["antigravity", "claude_code", "codex", "root", "cursor"]


@dataclass
class Collaborator:
    user_id: str  # e.g. "chitranjan", "nitin", "ashish"
    user_name: str  # e.g. "Chitranjan", "Nitin", "Ashish"
    agent_id: str  # e.g. "antigravity", "claude_code", "codex", "root"
    agent_name: str  # e.g. "Antigravity", "Claude Code", "Codex", "Root"
    status: str = "active"  # "active", "working", "idle", "waiting_on_human"
    current_activity: str = ""  # e.g. "Editing server/auth.py", "Running pytest"
    last_active: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IntercomMessage:
    id: str
    sender_id: str
    sender_name: str
    sender_type: Literal["human", "agent"]
    agent_name: str  # e.g. "Antigravity", "Claude Code", "Codex"
    recipient: str  # "@all", "@antigravity", "@claude_code", etc.
    content: str
    action_type: str = "message"  # "message", "instruction", "lease_notice", "handoff"
    files_mentioned: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionStep:
    id: str
    run_id: str
    timestamp: float
    agent_name: str
    user_name: str
    phase: str  # "Search", "Inspect", "Edit", "Test", "Verify", "Gate"
    tool: str  # e.g. "read_file", "edit_file", "pytest", "grep_text"
    target_file: str
    activity: str
    output_snippet: str = ""
    status: str = "completed"  # "completed", "running", "failed"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionRun:
    id: str
    issue_id: str
    agent_name: str
    user_name: str
    status: str = "running"  # "running", "completed", "failed", "paused"
    phase: str = "Edit"
    step_count: int = 0
    current_step: int = 0
    current_activity: str = ""
    active_file: str = ""
    last_tool: str = ""
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Squad:
    id: str
    name: str
    description: str
    members: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Issue:
    id: str
    title: str
    description: str
    status: IssueStatus = "backlog"
    priority: IssuePriority = "medium"
    squad_id: str = "team-dev"
    workspace_scope: WorkspaceScope = "shared"
    workspace_path: str = "shared:repo"
    branch: str = ""
    flow_id: str | None = None
    diff: str | None = None
    verification_command: str = ""
    verification_output: str | None = None
    verification_passed: bool | None = None
    blocker_reason: str | None = None
    collaborators: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    active_leases: dict[str, str] = field(default_factory=dict)  # file_path -> agent_name
    active_run: dict[str, Any] | None = None
    runs: list[dict[str, Any]] = field(default_factory=list)
    execution_timeline: list[dict[str, Any]] = field(default_factory=list)
    lane_id: str | None = None  # Engram Bus handoff lane
    created_by: str = "Chitranjan"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


