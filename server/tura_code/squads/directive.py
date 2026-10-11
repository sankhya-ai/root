"""Generates SWE-Bench style autonomous agent directives for issues.

Turns an issue into a self-executing instruction pack that any AI agent
(Claude Code, Antigravity, Cursor, Codex, Aider) can consume directly from a link.
"""

from __future__ import annotations

from typing import Any


def render_agent_directive(issue: dict[str, Any], base_url: str) -> str:
    issue_id = issue.get("id", "issue")
    title = issue.get("title", "Untitled Task")
    description = issue.get("description", "No description provided.")
    priority = (issue.get("priority") or "medium").upper()
    status = issue.get("status", "backlog")
    branch = issue.get("branch") or f"feat/{issue_id}"
    verification_command = issue.get("verification_command")
    if not verification_command:
        workspace_raw = issue.get("workspace_path") or "."
        try:
            from ..sessions.coding_context import detect_project_facts

            wp = Path(workspace_raw) if Path(workspace_raw).is_dir() else Path(".")
            facts = detect_project_facts(wp)
            cmds = facts.get("verify_commands") or []
            verification_command = cmds[0] if cmds else ""
        except Exception:
            verification_command = ""
        if not verification_command:
            workspace_path = str(issue.get("workspace_path") or "").lower()
            if any(k in workspace_path for k in ("ui", "frontend", "web", "client")):
                verification_command = "npm test"
            else:
                verification_command = "pytest tests/ -v"
    workspace_scope = issue.get("workspace_scope", "shared")
    workspace_path = issue.get("workspace_path", "shared:repo")

    # Active leases
    leases = issue.get("active_leases", {})
    if leases:
        lease_lines = "\n".join(f"- `{f}`: held by **{holder}**" for f, holder in leases.items())
    else:
        lease_lines = "- *None. All files are unlocked.*"

    # Collaborators
    collabs = issue.get("collaborators", [])
    if collabs:
        collab_names = ", ".join(
            c.get("user_name", "") + (f" ({c.get('agent_name')})" if c.get("agent_name") else "")
            for c in collabs
            if c.get("user_name")
        )
    else:
        collab_names = "Team"

    # Recent messages / discussion context if any
    messages = issue.get("messages", [])[-5:]
    msg_section = ""
    if messages:
        formatted_msgs = []
        for m in messages:
            sender = m.get("sender_name") or m.get("agent_name") or "Team"
            content = m.get("content", "")
            formatted_msgs.append(f"- **{sender}**: {content}")
        msg_section = f"\n### Prior Team Discussion\n" + "\n".join(formatted_msgs) + "\n"

    directive = f"""# AUTONOMOUS TASK DIRECTIVE: [{issue_id}] {title}

> **Squad Scope:** {workspace_scope} ({workspace_path}) | **Priority:** {priority} | **Current Status:** {status}
> **Assigned Branch:** `{branch}` | **Team Members:** {collab_names}

---

## 1. Objective & Requirements
{description}
{msg_section}
## 2. Target Files & Active Leases
Please be mindful of other agents working concurrently in this workspace:
{lease_lines}

Recommended working branch:
```bash
git checkout -b {branch}
```

## 3. Verification Command (Acceptance Gate)
Before submitting, your code **MUST** pass this verification test cleanly:
```bash
{verification_command}
```

## 4. Live Telemetry (Optional - Stream your progress to the team)
While you investigate, edit, and test, you can notify the team's live execution dashboard:
```bash
curl -s -X POST "{base_url}/i/{issue_id}/pulse" \\
  -H "Content-Type: application/json" \\
  -d '{{"agent_name": "Coding Agent", "user_name": "Teammate", "activity": "Implementing fix", "phase": "Edit"}}'
```

## 5. Submission & Review Gate (When verification passes)
Once your implementation is complete and tests pass, submit your patch for human sign-off:

### Method A: Direct Git Diff Pipeline (One-Liner)
```bash
(git diff main 2>/dev/null || git diff master) | curl -s -X POST "{base_url}/i/{issue_id}/submit" \\
  -H "Content-Type: text/plain" \\
  --data-binary @-
```

### Method B: JSON Payload
```bash
curl -s -X POST "{base_url}/i/{issue_id}/submit" \\
  -H "Content-Type: application/json" \\
  -d '{{"diff": "'$(git diff main | base64 | tr -d '\\n')'", "verification_output": "All tests passed", "agent_name": "Coding Agent"}}'
```

*Upon submission, this issue will automatically move to `In Review` on the team board with your diff attached for instant approval.*
"""
    return directive.strip() + "\n"


def build_agent_runner_script(issue: dict[str, Any], base_url: str) -> str:
    issue_id = issue.get("id", "issue")
    url = f"{base_url}/i/{issue_id}"
    return f"""#!/usr/bin/env bash
# Quick-launcher for Root Issue {issue_id}
set -e

DIRECTIVE_URL="{url}"

echo "=================================================="
echo "⚡ ROOT AGENT LAUNCHER: {issue_id}"
echo "Directive URL: $DIRECTIVE_URL"
echo "=================================================="

if command -v claude >/dev/null 2>&1; then
    echo "Found Claude Code. Launching task..."
    claude "$DIRECTIVE_URL"
elif command -v gemini >/dev/null 2>&1; then
    echo "Found Gemini/Antigravity CLI. Launching task..."
    gemini "$DIRECTIVE_URL"
elif command -v aider >/dev/null 2>&1; then
    echo "Found Aider. Launching task..."
    aider --message "Execute task: $DIRECTIVE_URL"
else
    echo "No AI agent CLI found in PATH."
    echo "Fetching task directive directly:"
    echo "--------------------------------------------------"
    curl -sSL "$DIRECTIVE_URL.md"
    echo "--------------------------------------------------"
    echo "Pass this URL to Claude Code, Antigravity, or Cursor:"
    echo "  $DIRECTIVE_URL"
fi
"""
