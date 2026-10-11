"""Thread-safe persistent storage for squads and issues."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from .models import Issue, Squad

logger = logging.getLogger(__name__)

DEFAULT_MEMBERS = [
    {
        "user_id": "chitranjan",
        "user_name": "Chitranjan",
        "role": "Developer",
        "status": "idle",
        "current_activity": "Active in workspace",
    },
    {
        "user_id": "nitin",
        "user_name": "Nitin",
        "role": "Developer",
        "status": "idle",
        "current_activity": "Active in workspace",
    },
    {
        "user_id": "ashish",
        "user_name": "Ashish",
        "role": "Developer",
        "status": "idle",
        "current_activity": "Active in workspace",
    },
]

DEFAULT_SQUADS = [
    {
        "id": "team-product",
        "name": "Product Development Team",
        "description": "Collaborative development team",
        "members": DEFAULT_MEMBERS,
    },
]

DEFAULT_ISSUES = [
    {
        "id": "iss-001",
        "title": "Establish cross-agent API contract for authentication",
        "description": "Define TypeScript/Pydantic schemas and mock fixtures for session auth tokens so backend and frontend can develop concurrently.",
        "status": "in_review",
        "priority": "high",
        "squad_id": "team-product",
        "workspace_scope": "shared",
        "workspace_path": "shared:auth-service",
        "branch": "feat/auth-contract",
        "verification_command": "pytest -q tests/test_auth.py",
        "verification_passed": True,
        "verification_output": "5 passed in 0.12s",
        "diff": "--- a/auth/schema.py\n+++ b/auth/schema.py\n@@ -10,3 +10,12 @@\n+class AuthToken(BaseModel):\n+    access_token: str\n+    expires_in: int\n",
        "created_by": "Chitranjan",
        "collaborators": [
            {
                "user_id": "chitranjan",
                "user_name": "Chitranjan",
                "agent_id": "antigravity",
                "agent_name": "Antigravity",
                "status": "holding_lease",
                "current_activity": "Lease held on auth/schema.py",
            },
            {
                "user_id": "nitin",
                "user_name": "Nitin",
                "agent_id": "claude_code",
                "agent_name": "Claude Code",
                "status": "working",
                "current_activity": "Integrating client.ts parser",
            },
        ],
        "active_leases": {
            "auth/schema.py": "Antigravity (Chitranjan)",
            "auth/client.ts": "Claude Code (Nitin)",
        },
        "active_run": {
            "id": "run-101",
            "issue_id": "iss-001",
            "agent_name": "Antigravity",
            "user_name": "Chitranjan",
            "status": "completed",
            "phase": "Gate",
            "step_count": 5,
            "current_step": 5,
            "current_activity": "All verifications passed; submitted to Review Gate",
            "active_file": "auth/schema.py",
            "last_tool": "pytest",
            "started_at": time.time() - 420,
            "completed_at": time.time() - 60,
            "updated_at": time.time() - 60,
        },
        "runs": [
            {
                "id": "run-101",
                "issue_id": "iss-001",
                "agent_name": "Antigravity",
                "user_name": "Chitranjan",
                "status": "completed",
                "phase": "Gate",
                "step_count": 5,
                "current_step": 5,
                "current_activity": "All verifications passed; submitted to Review Gate",
                "active_file": "auth/schema.py",
                "last_tool": "pytest",
                "started_at": time.time() - 420,
                "completed_at": time.time() - 60,
                "updated_at": time.time() - 60,
            }
        ],
        "execution_timeline": [
            {
                "id": "step-101",
                "run_id": "run-101",
                "timestamp": time.time() - 400,
                "agent_name": "Claude Code",
                "user_name": "Nitin",
                "phase": "Search",
                "tool": "glob_files",
                "target_file": "auth/**/*.py",
                "activity": "Discovered authentication models and mock fixtures in auth directory",
                "output_snippet": "Found 3 matching files:\n- auth/schema.py\n- auth/client.ts\n- tests/test_auth.py",
                "status": "completed",
            },
            {
                "id": "step-102",
                "run_id": "run-101",
                "timestamp": time.time() - 310,
                "agent_name": "Antigravity",
                "user_name": "Chitranjan",
                "phase": "Inspect",
                "tool": "read_file",
                "target_file": "auth/schema.py",
                "activity": "Reading auth/schema.py: Lines 1-30 to verify Pydantic BaseModel inheritance",
                "output_snippet": "class AuthToken(BaseModel) currently defines only token: str without expiration timestamp.",
                "status": "completed",
            },
            {
                "id": "step-103",
                "run_id": "run-101",
                "timestamp": time.time() - 210,
                "agent_name": "Antigravity",
                "user_name": "Chitranjan",
                "phase": "Edit",
                "tool": "edit_file",
                "target_file": "auth/schema.py",
                "activity": "Added access_token: str and expires_in: int (UNIX epoch seconds) to AuthToken",
                "output_snippet": "+class AuthToken(BaseModel):\n+    access_token: str\n+    expires_in: int\nApplied diff cleanly.",
                "status": "completed",
            },
            {
                "id": "step-104",
                "run_id": "run-101",
                "timestamp": time.time() - 110,
                "agent_name": "Antigravity",
                "user_name": "Chitranjan",
                "phase": "Test",
                "tool": "pytest",
                "target_file": "tests/test_auth.py",
                "activity": "Ran verification suite: pytest -q tests/test_auth.py",
                "output_snippet": "============================= test session starts ==============================\n5 passed in 0.12s\nPASSED tests/test_auth.py::test_token_serialization\nPASSED tests/test_auth.py::test_token_expiry",
                "status": "completed",
            },
            {
                "id": "step-105",
                "run_id": "run-101",
                "timestamp": time.time() - 60,
                "agent_name": "Claude Code",
                "user_name": "Nitin",
                "phase": "Gate",
                "tool": "submit_review",
                "target_file": "auth/schema.py",
                "activity": "Synchronized client.ts parser and submitted diff to Review Gate for human sign-off",
                "output_snippet": "Review Gate: Verification PASS. Ready for human merge.",
                "status": "completed",
            },
        ],
        "messages": [
            {
                "id": "msg-101",
                "sender_id": "nitin",
                "sender_name": "Nitin",
                "sender_type": "human",
                "agent_name": "Claude Code",
                "recipient": "@Antigravity",
                "content": "Hey Antigravity, I'm refactoring the token parser in client.ts. Keep access_token and expires_in as top-level fields.",
                "action_type": "instruction",
                "files_mentioned": ["client.ts", "schema.py"],
                "created_at": time.time() - 320,
            },
            {
                "id": "msg-102",
                "sender_id": "antigravity",
                "sender_name": "Antigravity",
                "sender_type": "agent",
                "agent_name": "Antigravity",
                "recipient": "@Nitin",
                "content": "Acknowledged @Nitin. Updated auth/schema.py and verified with pytest. Acquired optimistic lease for 180s.",
                "action_type": "lease_notice",
                "files_mentioned": ["schema.py"],
                "created_at": time.time() - 210,
            },
            {
                "id": "msg-103",
                "sender_id": "claude_code",
                "sender_name": "Claude Code",
                "sender_type": "agent",
                "agent_name": "Claude Code",
                "recipient": "@all-agents",
                "content": "Running test suite against updated contract: pytest -q passed with 5 tests green. Ready for Review Gate.",
                "action_type": "broadcast",
                "files_mentioned": ["tests/test_auth.py"],
                "created_at": time.time() - 60,
            },
        ],
    },
    {
        "id": "iss-002",
        "title": "Build optimistic concurrency file lease adapter on Engram Bus",
        "description": "Allow agents to claim transient TTL leases before editing shared repository files, preventing concurrent write collisions.",
        "status": "in_progress",
        "priority": "urgent",
        "squad_id": "team-product",
        "workspace_scope": "shared",
        "workspace_path": "shared:core-infra",
        "branch": "feat/engram-lease",
        "verification_command": "python3 -m unittest -q",
        "created_by": "Nitin",
        "collaborators": [
            {
                "user_id": "nitin",
                "user_name": "Nitin",
                "agent_id": "claude_code",
                "agent_name": "Claude Code",
                "status": "working",
                "current_activity": "Implementing lease eviction TTL in bus/lease.py",
                "active_file": "bus/lease.py",
                "last_tool": "edit_file",
            },
            {
                "user_id": "chitranjan",
                "user_name": "Chitranjan",
                "agent_id": "antigravity",
                "agent_name": "Antigravity",
                "status": "working",
                "current_activity": "Testing cross-agent IPC signals",
                "active_file": "server/tura_code/squads/service.py",
                "last_tool": "read_file",
            },
        ],
        "active_leases": {
            "bus/lease.py": "Claude Code (Nitin)",
        },
        "active_run": {
            "id": "run-202",
            "issue_id": "iss-002",
            "agent_name": "Claude Code",
            "user_name": "Nitin",
            "status": "running",
            "phase": "Edit",
            "step_count": 6,
            "current_step": 4,
            "current_activity": "Implementing lease eviction TTL in bus/lease.py",
            "active_file": "bus/lease.py",
            "last_tool": "edit_file",
            "started_at": time.time() - 145,
            "updated_at": time.time() - 8,
        },
        "runs": [
            {
                "id": "run-201",
                "issue_id": "iss-002",
                "agent_name": "Claude Code",
                "user_name": "Nitin",
                "status": "failed",
                "phase": "Inspect",
                "step_count": 2,
                "current_step": 2,
                "current_activity": "Initial schema inspection failed: FileNotFoundError for test fixture",
                "active_file": "tests/fixtures.py",
                "last_tool": "read_file",
                "started_at": time.time() - 3600,
                "completed_at": time.time() - 3540,
                "updated_at": time.time() - 3540,
            },
            {
                "id": "run-202",
                "issue_id": "iss-002",
                "agent_name": "Claude Code",
                "user_name": "Nitin",
                "status": "running",
                "phase": "Edit",
                "step_count": 6,
                "current_step": 4,
                "current_activity": "Implementing lease eviction TTL in bus/lease.py",
                "active_file": "bus/lease.py",
                "last_tool": "edit_file",
                "started_at": time.time() - 145,
                "updated_at": time.time() - 8,
            },
        ],
        "execution_timeline": [
            {
                "id": "step-201",
                "run_id": "run-202",
                "timestamp": time.time() - 140,
                "agent_name": "Claude Code",
                "user_name": "Nitin",
                "phase": "Search",
                "tool": "grep_text",
                "target_file": "bus/lease.py",
                "activity": "Locating existing acquire_file_lease implementation and lease table schema",
                "output_snippet": "Matched in bus/lease.py:28:\ndef acquire_file_lease(self, file_path: str, agent_id: str, ttl: int = 180):\n    cursor.execute('SELECT agent, expires_at FROM leases WHERE file_path = ?', (file_path,))",
                "status": "completed",
            },
            {
                "id": "step-202",
                "run_id": "run-202",
                "timestamp": time.time() - 105,
                "agent_name": "Claude Code",
                "user_name": "Nitin",
                "phase": "Inspect",
                "tool": "read_file",
                "target_file": "bus/lease.py",
                "activity": "Reading lines 1-60 to check SQLite WAL transaction lock semantics and timeout",
                "output_snippet": "Read 60 lines. Database connection configured with PRAGMA journal_mode=WAL and busy_timeout=5000.",
                "status": "completed",
            },
            {
                "id": "step-203",
                "run_id": "run-202",
                "timestamp": time.time() - 65,
                "agent_name": "Antigravity",
                "user_name": "Chitranjan",
                "phase": "Inspect",
                "tool": "read_file",
                "target_file": "server/tura_code/squads/service.py",
                "activity": "Inspected SquadService file lease delegates to verify auto-renewal hooks",
                "output_snippet": "Confirmed claim_file_lease and release_file_lease delegates correctly handle TTL expiration timestamp.",
                "status": "completed",
            },
            {
                "id": "step-204",
                "run_id": "run-202",
                "timestamp": time.time() - 12,
                "agent_name": "Claude Code",
                "user_name": "Nitin",
                "phase": "Edit",
                "tool": "edit_file",
                "target_file": "bus/lease.py",
                "activity": "Modifying bus/lease.py: Adding background asyncio task to periodically purge expired leases",
                "output_snippet": "Replaced lines 35-52 with background TTL renewer. Status: Clean replacement (1 hunk applied).",
                "status": "running",
            },
        ],
        "messages": [
            {
                "id": "msg-201",
                "sender_id": "chitranjan",
                "sender_name": "Chitranjan",
                "sender_type": "human",
                "agent_name": "Antigravity",
                "recipient": "@Claude-Code",
                "content": "Make sure file lease TTLs are 180 seconds and renew automatically while agent has a pending turn.",
                "action_type": "instruction",
                "files_mentioned": ["bus/lease.py"],
                "created_at": time.time() - 150,
            },
            {
                "id": "msg-202",
                "sender_id": "claude_code",
                "sender_name": "Claude Code",
                "sender_type": "agent",
                "agent_name": "Claude Code",
                "recipient": "@Chitranjan",
                "content": "Implementing TTL heartbeat renewer in bus/lease.py now. Lease locked.",
                "action_type": "message",
                "files_mentioned": ["bus/lease.py"],
                "created_at": time.time() - 45,
            },
        ],
    },
    {
        "id": "iss-003",
        "title": "Real-time collaborative squad board with inter-agent intercom",
        "description": "Render multiplayer board where Chitranjan, Nitin, and Ashish can coordinate their respective coding agents (Antigravity, Claude Code, Codex).",
        "status": "in_review",
        "priority": "medium",
        "squad_id": "team-product",
        "workspace_scope": "shared",
        "workspace_path": "shared:root-ui",
        "branch": "feat/collaborative-board",
        "verification_command": "npm run typecheck && npm run build",
        "verification_passed": True,
        "verification_output": "Built successfully in 1.93s",
        "diff": "--- a/ui/src/components/pages/SquadsPage.tsx\n+++ b/ui/src/components/pages/SquadsPage.tsx\n@@ -0,0 +1,60 @@\n+// Real-time multiplayer board for Antigravity, Claude Code, Codex\n",
        "created_by": "Chitranjan",
        "collaborators": [
            {
                "user_id": "chitranjan",
                "user_name": "Chitranjan",
                "agent_id": "antigravity",
                "agent_name": "Antigravity",
                "status": "working",
                "current_activity": "Building multi-agent intercom UI",
            },
            {
                "user_id": "ashish",
                "user_name": "Ashish",
                "agent_id": "codex",
                "agent_name": "Codex",
                "status": "idle",
                "current_activity": "Observing UI build outputs",
            },
        ],
        "active_leases": {},
        "active_run": {
            "id": "run-301",
            "issue_id": "iss-003",
            "agent_name": "Antigravity",
            "user_name": "Chitranjan",
            "status": "completed",
            "phase": "Gate",
            "step_count": 4,
            "current_step": 4,
            "current_activity": "Compiled UI components cleanly, pushed to review gate",
            "active_file": "ui/src/components/pages/SquadsPage.tsx",
            "last_tool": "npm run build",
            "started_at": time.time() - 600,
            "completed_at": time.time() - 90,
            "updated_at": time.time() - 90,
        },
        "runs": [
            {
                "id": "run-301",
                "issue_id": "iss-003",
                "agent_name": "Antigravity",
                "user_name": "Chitranjan",
                "status": "completed",
                "phase": "Gate",
                "step_count": 4,
                "current_step": 4,
                "current_activity": "Compiled UI components cleanly, pushed to review gate",
                "active_file": "ui/src/components/pages/SquadsPage.tsx",
                "last_tool": "npm run build",
                "started_at": time.time() - 600,
                "completed_at": time.time() - 90,
                "updated_at": time.time() - 90,
            }
        ],
        "execution_timeline": [
            {
                "id": "step-301",
                "run_id": "run-301",
                "timestamp": time.time() - 550,
                "agent_name": "Antigravity",
                "user_name": "Chitranjan",
                "phase": "Inspect",
                "tool": "read_file",
                "target_file": "ui/src/components/pages/SquadsPage.tsx",
                "activity": "Reading SquadsPage.tsx layout components",
                "output_snippet": "Examined Kanban column containers and drawer components.",
                "status": "completed",
            },
            {
                "id": "step-302",
                "run_id": "run-301",
                "timestamp": time.time() - 320,
                "agent_name": "Antigravity",
                "user_name": "Chitranjan",
                "phase": "Edit",
                "tool": "edit_file",
                "target_file": "ui/src/components/pages/SquadsPage.tsx",
                "activity": "Added real-time agent activity badges and intercom stream",
                "output_snippet": "Patched SquadsPage.tsx with live pulse stream and connection modals.",
                "status": "completed",
            },
            {
                "id": "step-303",
                "run_id": "run-301",
                "timestamp": time.time() - 110,
                "agent_name": "Antigravity",
                "user_name": "Chitranjan",
                "phase": "Test",
                "tool": "npm test",
                "target_file": "ui/src",
                "activity": "Ran TypeScript typecheck and Vitest suite",
                "output_snippet": "npm run typecheck passed with 0 errors. Vitest 12 tests passed.",
                "status": "completed",
            },
            {
                "id": "step-304",
                "run_id": "run-301",
                "timestamp": time.time() - 90,
                "agent_name": "Antigravity",
                "user_name": "Chitranjan",
                "phase": "Gate",
                "tool": "npm run build",
                "target_file": "ui/dist",
                "activity": "Built production bundle and submitted to Review Gate",
                "output_snippet": "vite build completed in 1.93s. Bundle size: 412kB.",
                "status": "completed",
            },
        ],
        "messages": [
            {
                "id": "msg-301",
                "sender_id": "ashish",
                "sender_name": "Ashish",
                "sender_type": "human",
                "agent_name": "Codex",
                "recipient": "@all-agents",
                "content": "Loving the real-time visibility. My Codex agent can see your Antigravity edits immediately.",
                "action_type": "message",
                "files_mentioned": [],
                "created_at": time.time() - 90,
            },
        ],
    },
    {
        "id": "iss-004",
        "title": "Shared workspace git branch isolation and lock arbiter",
        "description": "Ensure personal workspaces remain strictly scoped to individual users while shared workspaces allow team-wide read/write.",
        "status": "backlog",
        "priority": "low",
        "squad_id": "team-product",
        "workspace_scope": "shared",
        "workspace_path": "shared:platform-security",
        "created_by": "Nitin",
        "collaborators": [
            {
                "user_id": "nitin",
                "user_name": "Nitin",
                "agent_id": "claude_code",
                "agent_name": "Claude Code",
                "status": "idle",
                "current_activity": "Awaiting assignment",
            },
        ],
        "active_leases": {},
        "active_run": None,
        "runs": [],
        "execution_timeline": [],
        "messages": [],
    },
]


class SquadStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.squads_file = root / "squads.json"
        self.issues_file = root / "issues.json"
        self._lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        self._init_defaults()

    def _init_defaults(self) -> None:
        with self._lock:
            needs_seed = False
            if not self.squads_file.exists():
                needs_seed = True
            else:
                existing = self._load_json(self.squads_file)
                if not any(s.get("id") == "team-product" for s in existing):
                    needs_seed = True
            if needs_seed:
                self._save_json(self.squads_file, DEFAULT_SQUADS)
                self._save_json(self.issues_file, DEFAULT_ISSUES)
            elif self.issues_file.exists():
                curr_issues = self._load_json(self.issues_file)
                modified = False
                def_by_id = {d["id"]: d for d in DEFAULT_ISSUES}
                for iss in curr_issues:
                    d = def_by_id.get(iss.get("id"))
                    if d:
                        if "execution_timeline" not in iss or not iss["execution_timeline"]:
                            iss["execution_timeline"] = d.get("execution_timeline", [])
                            modified = True
                        if "active_run" not in iss:
                            iss["active_run"] = d.get("active_run")
                            modified = True
                        if "runs" not in iss:
                            iss["runs"] = d.get("runs", [])
                            modified = True
                if modified:
                    self._save_json(self.issues_file, curr_issues)

    def _load_json(self, path: Path) -> list[dict[str, Any]]:
        try:
            return json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            return []

    def _save_json(self, path: Path, data: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".tmp.{os.getpid()}")
        tmp.write_text(json.dumps(data, indent=2), "utf-8")
        tmp.replace(path)

    # ── Squads ──

    def list_squads(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._load_json(self.squads_file)

    def get_squad(self, squad_id: str) -> dict[str, Any] | None:
        with self._lock:
            for s in self.list_squads():
                if s.get("id") == squad_id:
                    return s
            return None

    def save_squad(self, squad: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            squads = self.list_squads()
            idx = next((i for i, s in enumerate(squads) if s.get("id") == squad["id"]), None)
            squad["updated_at"] = time.time()
            if idx is not None:
                squads[idx] = squad
            else:
                squad["created_at"] = squad.get("created_at") or time.time()
                squads.append(squad)
            self._save_json(self.squads_file, squads)
            return squad

    # ── Issues ──

    def list_issues(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._load_json(self.issues_file)

    def get_issue(self, issue_id: str) -> dict[str, Any] | None:
        with self._lock:
            for iss in self.list_issues():
                if iss.get("id") == issue_id:
                    return iss
            return None

    def save_issue(self, issue: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            issues = self.list_issues()
            idx = next((i for i, item in enumerate(issues) if item.get("id") == issue["id"]), None)
            issue["updated_at"] = time.time()
            if idx is not None:
                issues[idx] = issue
            else:
                issue["created_at"] = issue.get("created_at") or time.time()
                issues.append(issue)
            self._save_json(self.issues_file, issues)
            return issue

    def delete_issue(self, issue_id: str) -> bool:
        with self._lock:
            issues = self.list_issues()
            new_issues = [i for i in issues if i.get("id") != issue_id]
            if len(new_issues) < len(issues):
                self._save_json(self.issues_file, new_issues)
                return True
            return False
