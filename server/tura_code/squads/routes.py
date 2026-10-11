"""HTTP API routes for Squads, Issues, and Engram Bus coordination."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..tenancy import Tenant


def router(app_state) -> APIRouter:
    api = APIRouter(prefix="/api")
    tenant_of = app_state.auth.tenant

    def service_of(tenant: Tenant):
        service = getattr(tenant, "squads", None)
        if service is None:
            from .service import SquadService

            service = SquadService(tenant)
            tenant.squads = service
        return service

    # ── Squads ──

    @api.get("/squads")
    async def list_squads(tenant: Tenant = Depends(tenant_of)) -> dict[str, Any]:
        service = service_of(tenant)
        return {"squads": service.list_squads()}

    @api.post("/squads")
    async def create_squad(body: dict[str, Any], tenant: Tenant = Depends(tenant_of)) -> dict[str, Any]:
        service = service_of(tenant)
        name = str(body.get("name") or "").strip()
        description = str(body.get("description") or "").strip()
        lead_agent_id = str(body.get("lead_agent_id") or "agent-lead").strip()
        if not name:
            raise HTTPException(400, "Squad name is required")
        squad = service.create_squad(name, description, lead_agent_id, body.get("members"))
        return {"squad": squad}

    @api.get("/squads/bus/state")
    async def bus_state(tenant: Tenant = Depends(tenant_of)) -> dict[str, Any]:
        service = service_of(tenant)
        return service.bus_state()

    @api.get("/squads/{squad_id}")
    async def get_squad(squad_id: str, tenant: Tenant = Depends(tenant_of)) -> dict[str, Any]:
        service = service_of(tenant)
        squad = service.get_squad(squad_id)
        if not squad:
            raise HTTPException(404, "Squad not found")
        return {"squad": squad}

    @api.post("/squads/{squad_id}/members")
    async def add_squad_member(squad_id: str, body: dict[str, Any], tenant: Tenant = Depends(tenant_of)) -> dict[str, Any]:
        service = service_of(tenant)
        user_name = str(body.get("user_name") or body.get("name") or "").strip()
        if not user_name:
            raise HTTPException(400, "Teammate name is required")
        user_id = str(body.get("user_id") or user_name.lower().replace(" ", "-")).strip()
        squad = service.add_member(squad_id, {
            "user_id": user_id,
            "user_name": user_name,
            "role": str(body.get("role") or "Developer"),
            "status": "idle",
            "current_activity": "Ready for tasks",
        })
        return {"squad": squad}

    @api.delete("/squads/{squad_id}/members/{user_id}")
    async def remove_squad_member(squad_id: str, user_id: str, tenant: Tenant = Depends(tenant_of)) -> dict[str, Any]:
        service = service_of(tenant)
        squad = service.remove_member(squad_id, user_id)
        return {"squad": squad}

    @api.post("/squads/{squad_id}/connect")
    async def connect_agent(squad_id: str, body: dict[str, Any], tenant: Tenant = Depends(tenant_of)) -> dict[str, Any]:
        service = service_of(tenant)
        user_name = str(body.get("user_name") or "Developer").strip()
        agent_name = str(body.get("agent_name") or "Coding Agent").strip()
        user_id = str(body.get("user_id") or user_name.lower().replace(" ", "-")).strip()
        squad = service.add_member(squad_id, {
            "user_id": user_id,
            "user_name": user_name,
            "agent_name": agent_name,
            "role": "Developer",
            "status": "working",
            "current_activity": f"{agent_name} connected to shared workspace",
        })
        service.bus.signal("agent.connected", {
            "squad_id": squad_id,
            "user_id": user_id,
            "user_name": user_name,
            "agent_name": agent_name,
        })
        return {
            "squad": squad,
            "connected": True,
            "user_name": user_name,
            "agent_name": agent_name,
            "workspace_url": "http://localhost:8787",
            "message": f"Successfully connected {agent_name} for {user_name} to {squad_id}.",
        }

    # ── Issues ──

    @api.get("/issues")
    async def list_issues(
        squad_id: str | None = None,
        workspace_scope: str | None = None,
        status: str | None = None,
        tenant: Tenant = Depends(tenant_of),
    ) -> dict[str, Any]:
        service = service_of(tenant)
        return {"issues": service.list_issues(squad_id=squad_id, workspace_scope=workspace_scope, status=status)}

    @api.post("/issues")
    async def create_issue(body: dict[str, Any], tenant: Tenant = Depends(tenant_of)) -> dict[str, Any]:
        service = service_of(tenant)
        title = str(body.get("title") or "").strip()
        description = str(body.get("description") or "").strip()
        if not title:
            raise HTTPException(400, "Issue title is required")
        issue = service.create_issue(
            title=title,
            description=description,
            squad_id=body.get("squad_id", "team-product"),
            priority=body.get("priority", "medium"),
            workspace_scope=body.get("workspace_scope", "shared"),
            workspace_path=body.get("workspace_path", ""),
            verification_command=body.get("verification_command", ""),
            created_by=body.get("created_by", "Chitranjan"),
            collaborators=body.get("collaborators"),
        )
        return {"issue": issue}

    @api.get("/issues/{issue_id}")
    async def get_issue(issue_id: str, tenant: Tenant = Depends(tenant_of)) -> dict[str, Any]:
        service = service_of(tenant)
        issue = service.get_issue(issue_id)
        if not issue:
            raise HTTPException(404, "Issue not found")
        return {"issue": issue}

    @api.patch("/issues/{issue_id}")
    async def update_issue(issue_id: str, body: dict[str, Any], tenant: Tenant = Depends(tenant_of)) -> dict[str, Any]:
        service = service_of(tenant)
        try:
            issue = service.update_issue(issue_id, **body)
            return {"issue": issue}
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @api.post("/issues/{issue_id}/dispatch")
    async def dispatch_issue(issue_id: str, body: dict[str, Any] = {}, tenant: Tenant = Depends(tenant_of)) -> dict[str, Any]:
        service = service_of(tenant)
        try:
            issue = await service.dispatch_issue(issue_id, target_agent=body.get("target_agent"))
            return {"issue": issue}
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @api.post("/issues/{issue_id}/messages")
    async def send_message(issue_id: str, body: dict[str, Any], tenant: Tenant = Depends(tenant_of)) -> dict[str, Any]:
        service = service_of(tenant)
        content = str(body.get("content") or "").strip()
        if not content:
            raise HTTPException(400, "Message content required")
        try:
            issue = service.add_intercom_message(
                issue_id,
                sender_id=str(body.get("sender_id") or "user"),
                sender_name=str(body.get("sender_name") or "Chitranjan"),
                sender_type=str(body.get("sender_type") or "human"),
                agent_name=str(body.get("agent_name") or "Antigravity"),
                recipient=str(body.get("recipient") or "@all-agents"),
                content=content,
                action_type=str(body.get("action_type") or "message"),
                files_mentioned=body.get("files_mentioned"),
            )
            return {"issue": issue}
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @api.post("/issues/{issue_id}/collaborators")
    async def update_collaborators(issue_id: str, body: dict[str, Any], tenant: Tenant = Depends(tenant_of)) -> dict[str, Any]:
        service = service_of(tenant)
        collabs = body.get("collaborators")
        if not isinstance(collabs, list):
            raise HTTPException(400, "collaborators must be a list")
        try:
            issue = service.update_collaborators(issue_id, collabs)
            return {"issue": issue}
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @api.post("/issues/{issue_id}/leases/claim")
    async def claim_lease(issue_id: str, body: dict[str, Any], tenant: Tenant = Depends(tenant_of)) -> dict[str, Any]:
        service = service_of(tenant)
        file_path = str(body.get("file_path") or body.get("filepath") or "").strip()
        agent_name = str(body.get("agent_name") or body.get("agent_tag") or "Antigravity").strip()
        if not file_path:
            raise HTTPException(400, "file_path required")
        try:
            issue = service.claim_file_lease(issue_id, file_path, agent_name)
            return {"issue": issue}
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @api.post("/issues/{issue_id}/leases/release")
    async def release_lease(issue_id: str, body: dict[str, Any], tenant: Tenant = Depends(tenant_of)) -> dict[str, Any]:
        service = service_of(tenant)
        file_path = str(body.get("file_path") or body.get("filepath") or "").strip()
        if not file_path:
            raise HTTPException(400, "file_path required")
        try:
            issue = service.release_file_lease(issue_id, file_path)
            return {"issue": issue}
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    # ── Local Agent Cloud Bridge & Telemetry ──

    @api.post("/issues/{issue_id}/bridge/pulse")
    async def agent_pulse(issue_id: str, body: dict[str, Any], tenant: Tenant = Depends(tenant_of)) -> dict[str, Any]:
        service = service_of(tenant)
        agent_name = str(body.get("agent_name") or "Antigravity").strip()
        user_name = str(body.get("user_name") or "Chitranjan").strip()
        activity = str(body.get("activity") or "Active coding").strip()
        status = str(body.get("status") or "working").strip()
        active_file = str(body.get("active_file") or "").strip() or None
        last_tool = str(body.get("last_tool") or "").strip() or None
        phase = str(body.get("phase") or "").strip() or None
        output_snippet = str(body.get("output_snippet") or body.get("output") or "").strip() or None
        try:
            issue = service.record_agent_pulse(
                issue_id,
                agent_name=agent_name,
                user_name=user_name,
                activity=activity,
                status=status,
                active_file=active_file,
                last_tool=last_tool,
                phase=phase,
                output_snippet=output_snippet,
            )
            return {"issue": issue}
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @api.post("/issues/{issue_id}/bridge/step")
    async def trigger_agent_step(issue_id: str, body: dict[str, Any] = {}, tenant: Tenant = Depends(tenant_of)) -> dict[str, Any]:
        service = service_of(tenant)
        agent_name = str(body.get("agent_name") or "Claude Code").strip()
        user_name = str(body.get("user_name") or "Nitin").strip()
        try:
            issue = service.trigger_agent_step(issue_id, agent_name=agent_name, user_name=user_name)
            return {"issue": issue}
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @api.post("/issues/{issue_id}/bridge/discuss")
    async def autonomous_agent_discussion(issue_id: str, body: dict[str, Any], tenant: Tenant = Depends(tenant_of)) -> dict[str, Any]:
        service = service_of(tenant)
        topic = str(body.get("topic") or "Synchronize interfaces and test suite").strip()
        agent_a = str(body.get("agent_a") or "Antigravity").strip()
        user_a = str(body.get("user_a") or "Chitranjan").strip()
        agent_b = str(body.get("agent_b") or "Claude Code").strip()
        user_b = str(body.get("user_b") or "Nitin").strip()
        try:
            issue = service.run_autonomous_agent_discussion(
                issue_id,
                topic=topic,
                agent_a=agent_a,
                user_a=user_a,
                agent_b=agent_b,
                user_b=user_b,
            )
            return {"issue": issue}
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @api.post("/issues/{issue_id}/review")
    async def submit_review(issue_id: str, body: dict[str, Any], tenant: Tenant = Depends(tenant_of)) -> dict[str, Any]:
        service = service_of(tenant)
        diff = str(body.get("diff") or "")
        verification_output = str(body.get("verification_output") or "")
        passed = bool(body.get("passed", True))
        try:
            issue = service.submit_for_review(issue_id, diff=diff, verification_output=verification_output, passed=passed)
            return {"issue": issue}
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @api.post("/issues/{issue_id}/approve")
    async def approve_issue(issue_id: str, tenant: Tenant = Depends(tenant_of)) -> dict[str, Any]:
        service = service_of(tenant)
        try:
            issue = service.approve_issue(issue_id, reviewer=tenant.id)
            return {"issue": issue}
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @api.post("/issues/{issue_id}/reject")
    async def reject_issue(issue_id: str, body: dict[str, Any], tenant: Tenant = Depends(tenant_of)) -> dict[str, Any]:
        service = service_of(tenant)
        feedback = str(body.get("feedback") or "Changes requested.")
        try:
            issue = service.reject_issue(issue_id, feedback=feedback, reviewer=tenant.id)
            return {"issue": issue}
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @api.post("/issues/{issue_id}/comments")
    async def add_comment(issue_id: str, body: dict[str, Any], tenant: Tenant = Depends(tenant_of)) -> dict[str, Any]:
        service = service_of(tenant)
        content = str(body.get("content") or "").strip()
        if not content:
            raise HTTPException(400, "Comment content required")
        author_type = str(body.get("author_type") or "human")
        author_id = str(body.get("author_id") or tenant.id)
        try:
            issue = service.add_comment(issue_id, author_type, author_id, content)
            return {"issue": issue}
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    return api
