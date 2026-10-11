"""Local Agent Cloud Bridge for Root / Dhee Workspaces.

Connects locally running coding agents (Claude Code, Antigravity, Cursor, Codex)
to shared team issues, synchronizing live progress, telemetry, file leases,
and enabling autonomous cross-agent communication.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from typing import Any


class WorkspaceBridge:
    def __init__(self, base_url: str = "http://localhost:8787", session_cookie: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.cookie = session_cookie or os.environ.get("ROOT_SESSION_COOKIE")
        self.auth_token = os.environ.get("ROOT_AUTH_TOKEN") or os.environ.get("TURA_CODE_TOKEN")
        if not self.auth_token:
            token_path = os.path.expanduser("~/.tura-code/token")
            if os.path.exists(token_path):
                try:
                    with open(token_path, "r", encoding="utf-8") as f:
                        self.auth_token = f.read().strip()
                except Exception:
                    pass
        if not self.cookie and not self.auth_token:
            self._bootstrap()

    def _bootstrap(self) -> None:
        try:
            req = urllib.request.Request(f"{self.base_url}/api/auth/bootstrap", method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp:
                cookie_header = resp.headers.get("Set-Cookie")
                if cookie_header:
                    self.cookie = cookie_header.split(";")[0]
        except Exception:
            # If server not ready yet or already authenticated
            pass

    def _request(self, method: str, endpoint: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        body = json.dumps(data).encode("utf-8") if data else None
        headers = {"Content-Type": "application/json"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                res_body = resp.read().decode("utf-8")
                return json.loads(res_body) if res_body else {}
        except urllib.error.HTTPError as http_err:
            raw = http_err.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP {http_err.code}: {raw}") from http_err
        except Exception as err:
            raise RuntimeError(f"Failed to connect to workspace at {url}: {err}") from err

    def connect(
        self,
        *,
        user_name: str,
        agent_name: str = "Coding Agent",
        squad_id: str = "team-product",
    ) -> dict[str, Any]:
        """Connects this coding agent and developer into the shared workspace."""
        payload = {
            "user_name": user_name,
            "agent_name": agent_name,
        }
        return self._request("POST", f"/api/squads/{squad_id}/connect", payload)

    def pulse(
        self,
        issue_id: str,
        *,
        agent_name: str,
        user_name: str,
        activity: str,
        status: str = "working",
        active_file: str | None = None,
        last_tool: str | None = None,
        phase: str | None = None,
        output: str | None = None,
    ) -> dict[str, Any]:
        """Sends a progress heartbeat from the local agent into the shared workspace."""
        payload = {
            "agent_name": agent_name,
            "user_name": user_name,
            "activity": activity,
            "status": status,
            "active_file": active_file,
            "last_tool": last_tool,
            "phase": phase,
            "output_snippet": output,
        }
        return self._request("POST", f"/api/issues/{issue_id}/bridge/pulse", payload)

    def step(
        self,
        issue_id: str,
        *,
        agent_name: str = "Claude Code",
        user_name: str = "Nitin",
    ) -> dict[str, Any]:
        """Triggers the next logical execution step for this issue."""
        payload = {
            "agent_name": agent_name,
            "user_name": user_name,
        }
        return self._request("POST", f"/api/issues/{issue_id}/bridge/step", payload)

    def send_message(
        self,
        issue_id: str,
        *,
        content: str,
        sender_name: str,
        agent_name: str,
        recipient: str = "@all-agents",
        files_mentioned: list[str] | None = None,
    ) -> dict[str, Any]:
        """Sends an inter-agent message or query across the cloud to another agent."""
        payload = {
            "content": content,
            "sender_name": sender_name,
            "agent_name": agent_name,
            "sender_type": "agent",
            "recipient": recipient,
            "files_mentioned": files_mentioned or [],
        }
        return self._request("POST", f"/api/issues/{issue_id}/messages", payload)

    def start_autonomous_discussion(
        self,
        issue_id: str,
        topic: str,
        agent_a: str = "Antigravity",
        user_a: str = "Chitranjan",
        agent_b: str = "Claude Code",
        user_b: str = "Nitin",
    ) -> dict[str, Any]:
        """Triggers an autonomous discussion between two agents to negotiate contracts or file edits."""
        payload = {
            "topic": topic,
            "agent_a": agent_a,
            "user_a": user_a,
            "agent_b": agent_b,
            "user_b": user_b,
        }
        return self._request("POST", f"/api/issues/{issue_id}/bridge/discuss", payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Root Local Agent Cloud Bridge CLI")
    parser.add_argument("--url", default=os.environ.get("ROOT_WORKSPACE", "http://localhost:8787"), help="Workspace URL")
    subparsers = parser.add_subparsers(dest="command")

    # connect command
    conn_p = subparsers.add_parser("connect", help="Connect coding agent to the shared workspace")
    conn_p.add_argument("--user", default=os.environ.get("USER", "Developer"), help="Developer name (e.g. Nitin)")
    conn_p.add_argument("--agent", default="Claude Code", help="Coding Agent name (e.g. Claude Code, Antigravity, Codex)")
    conn_p.add_argument("--squad", default="team-product", help="Squad ID")

    # pulse command
    pulse_p = subparsers.add_parser("pulse", help="Send heartbeat and current activity")
    pulse_p.add_argument("--issue", required=True, help="Issue ID (e.g. iss-001)")
    pulse_p.add_argument("--user", default="Chitranjan", help="Developer name")
    pulse_p.add_argument("--agent", default="Antigravity", help="Agent name (e.g. Antigravity, Claude Code, Codex)")
    pulse_p.add_argument("--activity", required=True, help="Current task/activity description")
    pulse_p.add_argument("--file", help="File currently being edited")
    pulse_p.add_argument("--tool", help="Last tool executed (e.g. pytest, replace_file)")
    pulse_p.add_argument("--phase", help="SWE-Bench phase (e.g. Inspect, Edit, Test, Verify)")
    pulse_p.add_argument("--output", help="Tool output snippet")

    # step command
    step_p = subparsers.add_parser("step", help="Simulate/Advance next agent execution step")
    step_p.add_argument("--issue", required=True, help="Issue ID")
    step_p.add_argument("--user", default="Nitin", help="Developer name")
    step_p.add_argument("--agent", default="Claude Code", help="Agent name")

    # message command
    msg_p = subparsers.add_parser("message", help="Send message to another agent or workspace")
    msg_p.add_argument("--issue", required=True, help="Issue ID")
    msg_p.add_argument("--user", default="Chitranjan", help="Sender name")
    msg_p.add_argument("--agent", default="Antigravity", help="Sender agent")
    msg_p.add_argument("--to", default="@Claude-Code", help="Recipient (e.g. @Claude-Code, @all-agents)")
    msg_p.add_argument("--content", required=True, help="Message text")

    # discuss command
    disc_p = subparsers.add_parser("discuss", help="Trigger autonomous dialogue between two agents")
    disc_p.add_argument("--issue", required=True, help="Issue ID")
    disc_p.add_argument("--topic", required=True, help="Topic of discussion")
    disc_p.add_argument("--agent-a", default="Antigravity", help="Initiator agent")
    disc_p.add_argument("--user-a", default="Chitranjan", help="Developer A")
    disc_p.add_argument("--agent-b", default="Claude Code", help="Target agent")
    disc_p.add_argument("--user-b", default="Nitin", help="Developer B")

    args = parser.parse_args()
    bridge = WorkspaceBridge(args.url)

    if args.command == "connect":
        res = bridge.connect(
            user_name=args.user,
            agent_name=args.agent,
            squad_id=args.squad,
        )
        print(f"✓ Connected {args.agent} for {args.user} to shared workspace at {args.url}.")
        print(f"  Squad: {args.squad}")
        print(f"  Live telemetry, multi-agent messaging, and workspace coordination active.")
    elif args.command == "pulse":
        res = bridge.pulse(
            args.issue,
            agent_name=args.agent,
            user_name=args.user,
            activity=args.activity,
            active_file=args.file,
            last_tool=args.tool,
            phase=args.phase,
            output=args.output,
        )
        print(f"Pulse recorded successfully for {args.agent} ({args.user}) on issue {args.issue}.")
    elif args.command == "step":
        res = bridge.step(
            args.issue,
            agent_name=args.agent,
            user_name=args.user,
        )
        step_item = (res.get("execution_timeline") or [{}])[-1]
        print(f"⚡ Step executed: [{step_item.get('phase', 'Work')}] {step_item.get('activity', 'Working')}")
        print(f"  Tool: {step_item.get('tool', 'None')} | Target: {step_item.get('target_file', 'None')}")
    elif args.command == "message":
        res = bridge.send_message(
            args.issue,
            content=args.content,
            sender_name=args.user,
            agent_name=args.agent,
            recipient=args.to,
        )
        print(f"Message sent to {args.to} on issue {args.issue}.")
    elif args.command == "discuss":
        res = bridge.start_autonomous_discussion(
            args.issue,
            topic=args.topic,
            agent_a=args.agent_a,
            user_a=args.user_a,
            agent_b=args.agent_b,
            user_b=args.user_b,
        )
        print(f"Autonomous discussion started on issue {args.issue} for topic: {args.topic}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

