"""Unit and integration tests for multi-human and multi-agent squads, issues, and Engram Bus coordination."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tura_code.app import create_app
from tura_code.squads.bus import SquadBus
from tura_code.squads.models import Issue, Squad
from tura_code.squads.service import SquadService
from tura_code.squads.store import SquadStore


@pytest.fixture
def squads_dir(tmp_path):
    d = tmp_path / "squads_data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_squad_store_and_defaults(squads_dir):
    store = SquadStore(squads_dir)
    squads = store.list_squads()
    assert len(squads) >= 1
    assert any(s["id"] == "team-product" for s in squads)
    assert any(m["user_id"] == "chitranjan" for m in squads[0]["members"])
    assert any(m["user_id"] == "nitin" for m in squads[0]["members"])

    issues = store.list_issues()
    assert len(issues) >= 1
    assert any(iss["id"] == "iss-001" for iss in issues)


def test_engram_bus_lanes_and_leases(tmp_path):
    db_path = tmp_path / "test_bus.db"
    bus = SquadBus(db_path)
    assert bus.ready

    # Handoff Lane
    lane_id = bus.open_lane("sess-1", from_agent="lead", to_agent="worker", context={"feature": "auth"})
    assert lane_id
    lanes = bus.list_lanes("sess-1")
    assert len(lanes) == 1
    assert lanes[0]["from_agent"] == "lead"

    # Checkpoint
    cid = bus.checkpoint("sess-1", "lead", snapshot={"todos": ["step 1"]}, lane_id=lane_id)
    assert cid
    checkpoints = bus.list_checkpoints("sess-1")
    assert len(checkpoints) == 1

    # File lease
    ok = bus.acquire_file_lease("server/models.py", agent_id="agent-1", ttl=60)
    assert ok is True
    # Conflict
    ok2 = bus.acquire_file_lease("server/models.py", agent_id="agent-2", ttl=60)
    assert ok2 is False
    # Release and reacquire
    bus.release_file_lease("server/models.py", agent_id="agent-1")
    ok3 = bus.acquire_file_lease("server/models.py", agent_id="agent-2", ttl=60)
    assert ok3 is True


def test_squad_service_dispatch_and_review_gate(tmp_path):
    class DummyServer:
        home = tmp_path
        shared_workspaces = tmp_path / "shared_workspaces"

    class DummyTenant:
        id = "chitranjan"
        server = DummyServer()

    service = SquadService(DummyTenant(), bus=SquadBus(tmp_path / "bus.db"))
    issue = service.create_issue(
        title="Implement parallel worktree runner",
        description="Run multiple agent worktrees concurrently",
        squad_id="team-product",
        workspace_scope="shared",
        workspace_path="shared:engine",
        verification_command="pytest",
        collaborators=[
            {"user_id": "chitranjan", "user_name": "Chitranjan", "agent_id": "antigravity", "agent_name": "Antigravity", "status": "working", "current_activity": "Initial setup"},
            {"user_id": "nitin", "user_name": "Nitin", "agent_id": "claude_code", "agent_name": "Claude Code", "status": "idle", "current_activity": "Waiting for contract"},
        ],
    )
    assert issue["status"] == "backlog"
    assert issue["workspace_scope"] == "shared"
    assert len(issue["collaborators"]) == 2

    # Intercom message
    updated = service.add_intercom_message(
        issue["id"],
        sender_id="nitin",
        sender_name="Nitin",
        sender_type="human",
        agent_name="Claude Code",
        content="@Antigravity let's align on schemas",
    )
    assert any(m["sender_id"] == "nitin" for m in updated["messages"])

    # File lease claim & release
    claimed = service.claim_file_lease(issue["id"], "engine/runner.py", "Antigravity (Chitranjan)")
    assert "engine/runner.py" in claimed["active_leases"]

    released = service.release_file_lease(issue["id"], "engine/runner.py")
    assert "engine/runner.py" not in released["active_leases"]

    # Submit for review
    reviewed = service.submit_for_review(
        issue["id"],
        diff="--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n",
        verification_output="All 10 tests passed",
        passed=True,
    )
    assert reviewed["status"] == "in_review"
    assert reviewed["verification_passed"] is True

    # Approve (Review Gate)
    approved = service.approve_issue(issue["id"], reviewer="chitranjan")
    assert approved["status"] == "done"


def test_squads_api_endpoints(client):
    # List squads
    resp = client.get("/api/squads")
    assert resp.status_code == 200
    squads = resp.json()["squads"]
    assert len(squads) >= 1

    # Create issue with multiple collaborators
    created = client.post(
        "/api/issues",
        json={
            "title": "Build UI multiplayer board",
            "description": "Collaborative board in Tura styling",
            "squad_id": "team-product",
            "workspace_scope": "shared",
            "workspace_path": "shared:ui",
            "collaborators": [
                {"user_id": "chitranjan", "user_name": "Chitranjan", "agent_id": "antigravity", "agent_name": "Antigravity", "status": "working", "current_activity": "Building UI"},
                {"user_id": "nitin", "user_name": "Nitin", "agent_id": "claude_code", "agent_name": "Claude Code", "status": "working", "current_activity": "Building intercom"},
            ]
        },
    ).json()["issue"]
    assert created["title"] == "Build UI multiplayer board"
    assert created["status"] == "backlog"
    assert len(created["collaborators"]) == 2

    # Send Intercom message
    msg_resp = client.post(
        f"/api/issues/{created['id']}/messages",
        json={
            "sender_id": "nitin",
            "sender_name": "Nitin",
            "sender_type": "human",
            "agent_name": "Claude Code",
            "content": "@Antigravity checking in",
        },
    ).json()["issue"]
    assert any(m["sender_id"] == "nitin" for m in msg_resp["messages"])

    # Claim lease
    lease_resp = client.post(
        f"/api/issues/{created['id']}/leases/claim",
        json={"filepath": "ui/board.tsx", "agent_tag": "Antigravity (Chitranjan)"},
    ).json()["issue"]
    assert "ui/board.tsx" in lease_resp["active_leases"]

    # Submit review
    rev = client.post(
        f"/api/issues/{created['id']}/review",
        json={"diff": "diff here", "verification_output": "OK", "passed": True},
    ).json()["issue"]
    assert rev["status"] == "in_review"

    # Approve
    appr = client.post(f"/api/issues/{created['id']}/approve").json()["issue"]
    assert appr["status"] == "done"

    # Agent pulse & timeline execution step
    pulse_res = client.post(
        f"/api/issues/{created['id']}/bridge/pulse",
        json={
            "agent_name": "Antigravity",
            "user_name": "Chitranjan",
            "activity": "Reading server/auth.py",
            "active_file": "server/auth.py",
            "last_tool": "read_file",
            "phase": "Inspect",
            "output_snippet": "Read 50 lines.",
        },
    ).json()["issue"]
    assert "execution_timeline" in pulse_res
    assert len(pulse_res["execution_timeline"]) >= 1
    assert pulse_res["execution_timeline"][-1]["phase"] == "Inspect"
    assert pulse_res["active_run"] is not None
    assert pulse_res["active_run"]["agent_name"] == "Antigravity"

    # Trigger agent step
    stepped = client.post(
        f"/api/issues/{created['id']}/bridge/step",
        json={"agent_name": "Claude Code", "user_name": "Nitin"},
    ).json()["issue"]
    assert len(stepped["execution_timeline"]) >= 2
    assert stepped["active_run"]["user_name"] == "Nitin"

    # Check bus state endpoint
    bstate = client.get("/api/squads/bus/state").json()
    assert "ready" in bstate
    assert "lanes" in bstate
    assert "signals" in bstate

    # Check workspaces endpoint
    wspaces = client.get("/api/workspaces").json()
    assert "personal" in wspaces
    assert "shared" in wspaces


def test_agent_public_links(client):
    # 1. Browser visit redirects to UI
    browser_resp = client.get(
        "/i/iss-001",
        headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": "Mozilla/5.0"},
        follow_redirects=False,
    )
    assert browser_resp.status_code == 307
    assert browser_resp.headers["location"] == "/#/squads?issue=iss-001"

    # 2. Agent visit returns Markdown directive
    agent_resp = client.get(
        "/i/iss-001",
        headers={"Accept": "*/*", "User-Agent": "Claude-Code/1.0"},
    )
    assert agent_resp.status_code == 200
    assert "text/markdown" in agent_resp.headers["content-type"]
    assert "AUTONOMOUS TASK DIRECTIVE: [iss-001]" in agent_resp.text
    assert "Verification Command" in agent_resp.text
    assert "/i/iss-001/submit" in agent_resp.text

    # 3. Direct .md endpoint
    md_resp = client.get("/i/iss-001.md")
    assert md_resp.status_code == 200
    assert "AUTONOMOUS TASK DIRECTIVE: [iss-001]" in md_resp.text

    # 4. Direct .sh runner script
    sh_resp = client.get("/i/iss-001.sh")
    assert sh_resp.status_code == 200
    assert "#!/usr/bin/env bash" in sh_resp.text
    assert "DIRECTIVE_URL=" in sh_resp.text

    # 5. Public Pulse without authentication
    pulse_resp = client.post(
        "/i/iss-001/pulse",
        json={
            "agent_name": "Claude Code",
            "user_name": "Nitin",
            "activity": "Editing TTL eviction loop",
            "phase": "Edit",
            "active_file": "bus/lease.py",
        },
    )
    assert pulse_resp.status_code == 200
    assert pulse_resp.json()["ok"] is True

    # 6. Public Plain Text Diff Submission via git diff stream
    raw_diff = "diff --git a/bus/lease.py b/bus/lease.py\n--- a/bus/lease.py\n+++ b/bus/lease.py\n@@ -1 +1 @@\n+patched\n"
    submit_resp = client.post(
        "/i/iss-001/submit",
        content=raw_diff,
        headers={"Content-Type": "text/plain"},
    )
    assert submit_resp.status_code == 200
    submit_json = submit_resp.json()
    assert submit_json["ok"] is True
    assert submit_json["status"] == "in_review"

    # Verify issue state updated
    issue_resp = client.get("/i/iss-001?format=json").json()["issue"]
    assert issue_resp["status"] == "in_review"
    assert "diff --git" in issue_resp["diff"]


