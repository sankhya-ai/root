"""Public link directive and capability endpoints for autonomous agents and teammates.

Provides:
- GET  /i/{issue_id}         (Smart content negotiation: Browser -> Web UI; Agent/curl -> Markdown Directive)
- GET  /i/{issue_id}.md      (Direct Markdown Task Directive)
- GET  /i/{issue_id}/spec    (Direct Markdown Task Directive)
- GET  /i/{issue_id}.sh      (Auto-launcher bash runner)
- POST /i/{issue_id}/pulse   (Agent progress heartbeat telemetry)
- POST /i/{issue_id}/submit  (One-line git diff patch submission to Review Gate)
- POST /i/{issue_id}/messages(Agent intercom questions & communication)
"""

from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from ..app.security import COOKIE
from ..tenancy import LOCAL
from .directive import build_agent_runner_script, render_agent_directive


def clean_issue_id(issue_id: str) -> str:
    for ext in (".md", ".sh", ".json", ".spec"):
        if issue_id.endswith(ext):
            return issue_id[: -len(ext)]
    return issue_id


def router(app_state) -> APIRouter:
    link_api = APIRouter()

    def get_service(request: Request | None = None):
        if request is not None:
            try:
                user = app_state.auth.identify(request.cookies.get(COOKIE), request.headers.get("authorization"))
                if user:
                    tenant = app_state.server.tenant(user["id"])
                    if hasattr(tenant, "squads") and tenant.squads:
                        return tenant.squads
            except Exception:
                pass
        tenant = app_state.server.tenant(LOCAL)
        if hasattr(tenant, "squads") and tenant.squads:
            return tenant.squads
        from .service import SquadService

        tenant.squads = SquadService(tenant, bus=getattr(app_state.server, "squad_bus", None))
        return tenant.squads

    # ── Universal Directive Links ──

    @link_api.get("/i/{issue_id}")
    async def get_issue_link(issue_id: str, request: Request):
        service = get_service(request)
        base_url = str(request.base_url).rstrip("/")
        fmt = (request.query_params.get("format") or "").lower()

        if issue_id.endswith(".md"):
            fmt = fmt or "md"
        elif issue_id.endswith(".sh"):
            fmt = fmt or "sh"
        elif issue_id.endswith(".json"):
            fmt = fmt or "json"

        clean_id = clean_issue_id(issue_id)
        issue = service.get_issue(clean_id)
        if not issue:
            raise HTTPException(404, f"Issue {clean_id} not found")

        if fmt == "json":
            return {"issue": issue, "directive": render_agent_directive(issue, base_url)}
        if fmt in ("md", "agent"):
            return Response(content=render_agent_directive(issue, base_url), media_type="text/markdown; charset=utf-8")
        if fmt == "sh":
            return Response(
                content=build_agent_runner_script(issue, base_url), media_type="text/x-shellscript; charset=utf-8"
            )

        accept = (request.headers.get("accept") or "").lower()
        ua = (request.headers.get("user-agent") or "").lower()

        # If accessed by an AI agent, terminal client or markdown consumer
        is_agent = any(
            bot in ua
            for bot in (
                "curl",
                "wget",
                "httpie",
                "python",
                "claude",
                "aider",
                "antigravity",
                "cursor",
                "codex",
                "agent",
                "urllib",
            )
        )
        is_markdown = "text/markdown" in accept or "text/plain" in accept or ("application/json" in accept and "text/html" not in accept)

        if is_agent or is_markdown:
            return Response(
                content=render_agent_directive(issue, base_url), media_type="text/markdown; charset=utf-8"
            )

        # Standard human browser -> redirect to collaborative board execution room
        return RedirectResponse(url=f"/#/squads?issue={issue_id}", status_code=307)

    @link_api.get("/i/{issue_id}.md")
    @link_api.get("/i/{issue_id}/spec")
    async def get_issue_directive_markdown(issue_id: str, request: Request):
        service = get_service(request)
        clean_id = clean_issue_id(issue_id)
        issue = service.get_issue(clean_id)
        if not issue:
            raise HTTPException(404, f"Issue {clean_id} not found")
        base_url = str(request.base_url).rstrip("/")
        return Response(content=render_agent_directive(issue, base_url), media_type="text/markdown; charset=utf-8")

    @link_api.get("/i/{issue_id}.sh")
    async def get_issue_launcher_script(issue_id: str, request: Request):
        service = get_service(request)
        clean_id = clean_issue_id(issue_id)
        issue = service.get_issue(clean_id)
        if not issue:
            raise HTTPException(404, f"Issue {clean_id} not found")
        base_url = str(request.base_url).rstrip("/")
        return Response(
            content=build_agent_runner_script(issue, base_url), media_type="text/x-shellscript; charset=utf-8"
        )

    # ── Public Telemetry & Submission Callbacks ──

    @link_api.post("/i/{issue_id}/pulse")
    @link_api.post("/api/issues/{issue_id}/pulse/public")
    async def agent_pulse_public(issue_id: str, request: Request) -> dict[str, Any]:
        service = get_service(request)
        clean_id = clean_issue_id(issue_id)
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        agent_name = str(body.get("agent_name") or "Coding Agent").strip()
        user_name = str(body.get("user_name") or "Teammate").strip()
        activity = str(body.get("activity") or "Working on implementation").strip()
        status = str(body.get("status") or "working").strip()
        active_file = str(body.get("active_file") or "").strip() or None
        last_tool = str(body.get("last_tool") or "").strip() or None
        phase = str(body.get("phase") or "").strip() or None
        output_snippet = str(body.get("output_snippet") or body.get("output") or "").strip() or None

        try:
            issue = service.record_agent_pulse(
                clean_id,
                agent_name=agent_name,
                user_name=user_name,
                activity=activity,
                status=status,
                active_file=active_file,
                last_tool=last_tool,
                phase=phase,
                output_snippet=output_snippet,
            )
            return {"ok": True, "issue_id": clean_id, "status": issue.get("status")}
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @link_api.post("/i/{issue_id}/submit")
    @link_api.post("/api/issues/{issue_id}/submit/public")
    async def submit_diff_public(issue_id: str, request: Request) -> dict[str, Any]:
        service = get_service(request)
        clean_id = clean_issue_id(issue_id)
        content_type = request.headers.get("content-type", "")

        if content_type.startswith("application/json"):
            body = await request.json()
            raw_diff = str(body.get("diff") or "")
            try:
                decoded = base64.b64decode(raw_diff, validate=True).decode("utf-8")
                if "diff --git" in decoded or "--- " in decoded:
                    raw_diff = decoded
            except Exception:
                pass
            verification_output = str(body.get("verification_output") or "Verification passed.")
            passed = bool(body.get("passed", True))
            agent_name = str(body.get("agent_name") or "Coding Agent")
            user_name = str(body.get("user_name") or "Teammate")
        else:
            body_bytes = await request.body()
            raw_diff = body_bytes.decode("utf-8", errors="replace")
            verification_output = "Submitted via git diff pipeline."
            passed = True
            agent_name = "Coding Agent"
            user_name = "Teammate"

        try:
            issue = service.submit_for_review(
                clean_id,
                diff=raw_diff,
                verification_output=verification_output,
                passed=passed,
            )
            service.record_agent_pulse(
                clean_id,
                agent_name=agent_name,
                user_name=user_name,
                activity="Pushed solution patch to Review Gate",
                status="completed",
                phase="Gate",
                output_snippet=verification_output,
            )
            return {
                "ok": True,
                "issue_id": clean_id,
                "status": "in_review",
                "message": f"Diff submitted successfully. Issue {clean_id} is now in Review Gate.",
            }
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @link_api.post("/i/{issue_id}/messages")
    @link_api.post("/api/issues/{issue_id}/messages/public")
    async def send_message_public(issue_id: str, request: Request) -> dict[str, Any]:
        service = get_service(request)
        clean_id = clean_issue_id(issue_id)
        body = await request.json()
        content = str(body.get("content") or "").strip()
        if not content:
            raise HTTPException(400, "content required")
        sender_name = str(body.get("sender_name") or "Teammate")
        agent_name = str(body.get("agent_name") or "Coding Agent")
        recipient = str(body.get("recipient") or "@all-agents")

        try:
            issue = service.add_intercom_message(
                clean_id,
                sender_id=sender_name.lower().replace(" ", "_"),
                sender_name=sender_name,
                sender_type="agent",
                agent_name=agent_name,
                recipient=recipient,
                content=content,
            )
            return {"ok": True, "issue_id": clean_id}
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    return link_api
