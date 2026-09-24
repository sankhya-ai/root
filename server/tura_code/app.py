"""The HTTP + WebSocket API, and the static UI.

Local-only by default, and hardened like one: the agent can run commands on
this machine, so a web page the owner happens to have open must not be able to
drive it.

* **Host check.** Requests must name an allowed host (localhost by default),
  which defeats DNS rebinding.
* **Same-site token.** ``/api/auth/bootstrap`` sets an HttpOnly
  ``SameSite=Strict`` cookie; every other API call and the WebSocket require it
  (or ``Authorization: Bearer <token>`` for scripts). A cross-site page can
  neither read the token nor get the browser to send it.
* **Origin check** on the WebSocket, which browsers do not guard with CORS.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from . import __version__, launcher, workspace
from .memory import MemoryGateway
from .models import ModelCatalog
from .sessions import MODES, SessionManager
from .settings import SettingsStore, data_dir
from .wire import WireError

logger = logging.getLogger(__name__)

COOKIE = "tura_code_token"
UI_DIST = launcher.REPO_ROOT / "ui" / "dist"


class CreateSession(BaseModel):
    workspace: str
    title: str | None = None


class UpdateSession(BaseModel):
    title: str | None = None
    permission_mode: str | None = None


class Services:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.settings = SettingsStore(root)
        self.memory = MemoryGateway(root, self.settings.get)
        self.sessions = SessionManager(root, self.settings, self.memory)
        self.catalog = ModelCatalog()
        self.token = _load_token(root)

    async def refresh_capabilities(self) -> None:
        if os.environ.get(launcher.SCRIPTED_ECHO_ENV) or os.environ.get("TURA_CODE_OFFLINE"):
            return
        items = await self.catalog.models(self.settings.get().base_url)
        self.sessions.model_capabilities = {m["id"]: m["capabilities"] for m in items}


def _load_token(root: Path) -> str:
    explicit = os.environ.get("TURA_CODE_TOKEN", "").strip()
    if explicit:
        return explicit
    path = root / "token"
    if path.exists():
        token = path.read_text("utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(token)
    return token


def _allowed_hosts() -> set[str]:
    extra = {h.strip().lower() for h in os.environ.get("TURA_CODE_ALLOWED_HOSTS", "").split(",") if h.strip()}
    return {"localhost", "127.0.0.1", "[::1]", "::1", "testserver", *extra}


def _host_ok(host_header: str | None) -> bool:
    if not host_header:
        return False
    host = host_header.strip().lower()
    if host.startswith("["):
        name = host.split("]")[0] + "]"
    else:
        name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return name in _allowed_hosts()


def _token_ok(services: Services, cookie: str | None, authorization: str | None) -> bool:
    candidates = [cookie or ""]
    if authorization and authorization.lower().startswith("bearer "):
        candidates.append(authorization[7:].strip())
    return any(c and hmac.compare_digest(c, services.token) for c in candidates)


def create_app(root: Path | None = None) -> FastAPI:
    services = Services(root or data_dir())

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        services.sessions.start()
        warm = asyncio.create_task(services.memory.warm())
        catalog = asyncio.create_task(services.refresh_capabilities())
        yield
        for task in (warm, catalog):
            task.cancel()
        await services.sessions.close()
        await services.memory.close()

    app = FastAPI(title="root", version=__version__, lifespan=lifespan)
    app.state.services = services

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if not _host_ok(request.headers.get("host")):
            return JSONResponse({"detail": "Host not allowed."}, status_code=403)
        path = request.url.path
        if path.startswith("/api/") and path not in ("/api/auth/bootstrap", "/api/health"):
            if not _token_ok(services, request.cookies.get(COOKIE), request.headers.get("authorization")):
                return JSONResponse({"detail": "Not authorized. Reload the page."}, status_code=401)
        return await call_next(request)

    # ----- auth & health -------------------------------------------------

    @app.post("/api/auth/bootstrap")
    async def bootstrap(response: Response) -> dict:
        response.set_cookie(COOKIE, services.token, httponly=True, samesite="strict", path="/")
        return {"ok": True}

    @app.get("/api/health")
    async def health() -> dict:
        try:
            binary = str(launcher.find_runtime_binary())
            runtime_error = ""
        except launcher.RuntimeNotFound as error:
            binary, runtime_error = "", str(error)
        settings = services.settings.get()
        return {
            "version": __version__,
            "runtime": {"binary": binary, "error": runtime_error},
            "memory": services.memory.status(),
            "api_key_set": bool(settings.api_key()),
            "scripted": bool(os.environ.get(launcher.SCRIPTED_ECHO_ENV)),
        }

    # ----- settings & models ---------------------------------------------

    @app.get("/api/settings")
    async def get_settings() -> dict:
        return services.settings.get().public()

    @app.put("/api/settings")
    async def put_settings(changes: dict[str, Any]) -> dict:
        try:
            updated = services.settings.update(changes)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        if "model" in changes or "base_url" in changes:
            asyncio.create_task(services.refresh_capabilities())
            context = services.catalog.context_length(updated.model)
            if context and "max_context_size" not in changes:
                updated = services.settings.update({"max_context_size": max(8_000, min(int(context), 4_000_000))})
        if {"memory_mode", "memory_llm_model", "memory_embedding_model", "memory_embedding_dims"} & changes.keys():
            asyncio.create_task(services.memory.warm())
        return updated.public()

    @app.get("/api/models")
    async def models(refresh: bool = False) -> dict:
        settings = services.settings.get()
        items = await services.catalog.models(settings.base_url, refresh=refresh)
        services.sessions.model_capabilities = {m["id"]: m["capabilities"] for m in items}
        return {"models": items, "error": services.catalog.error}

    # ----- sessions ------------------------------------------------------

    @app.get("/api/sessions")
    async def list_sessions() -> dict:
        return {"sessions": services.sessions.list()}

    @app.post("/api/sessions")
    async def create_session(body: CreateSession) -> dict:
        try:
            runtime = services.sessions.create(body.workspace, body.title)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return runtime.public()

    def _session(session_id: str):
        try:
            return services.sessions.get(session_id)
        except KeyError as error:
            raise HTTPException(404, "Session not found.") from error

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str) -> dict:
        return _session(session_id).public()

    @app.patch("/api/sessions/{session_id}")
    async def update_session(session_id: str, body: UpdateSession) -> dict:
        runtime = _session(session_id)
        if body.title is not None:
            runtime.record.title = body.title.strip()[:120] or runtime.record.title
            runtime.save_record()
        if body.permission_mode is not None:
            if body.permission_mode not in MODES:
                raise HTTPException(400, "Unknown permission mode.")
            await runtime.set_mode(body.permission_mode)
        return runtime.public()

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str) -> dict:
        _session(session_id)
        await services.sessions.delete(session_id)
        return {"ok": True}

    @app.get("/api/sessions/{session_id}/director")
    async def director(session_id: str, limit: int = 100) -> dict:
        return {"decisions": _session(session_id).director_log(max(1, min(limit, 1000)))}

    @app.websocket("/api/sessions/{session_id}/ws")
    async def session_socket(websocket: WebSocket, session_id: str) -> None:
        origin = websocket.headers.get("origin")
        host = websocket.headers.get("host")
        origin_host = origin.split("://", 1)[-1] if origin else None
        if (
            not _host_ok(host)
            or (origin_host is not None and not _host_ok(origin_host))
            or not _token_ok(services, websocket.cookies.get(COOKIE), websocket.headers.get("authorization"))
        ):
            await websocket.close(code=4401)
            return
        try:
            runtime = services.sessions.get(session_id)
        except KeyError:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        queue, snapshot = runtime.subscribe()
        await websocket.send_json({"type": "hello", **snapshot})

        async def pump() -> None:
            while True:
                event = await queue.get()
                await websocket.send_json({"type": "event", "event": event})

        sender = asyncio.create_task(pump())
        try:
            while True:
                message = await websocket.receive_json()
                await _handle_client(runtime, message, websocket)
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001
            logger.exception("websocket handler failed")
        finally:
            sender.cancel()
            runtime.unsubscribe(queue)

    async def _handle_client(runtime, message: dict, websocket: WebSocket) -> None:
        kind = message.get("type")
        try:
            if kind == "prompt":
                await runtime.prompt(str(message.get("text") or ""), message.get("attachments") or None)
            elif kind == "cancel":
                await runtime.cancel()
            elif kind == "approval":
                runtime.resolve_approval(str(message.get("request_id") or ""), str(message.get("response") or "reject"))
            elif kind == "set_mode":
                await runtime.set_mode(str(message.get("mode") or "default"))
                await websocket.send_json({"type": "session", "session": runtime.public()})
            elif kind == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json({"type": "error", "message": f"Unknown message type {kind!r}."})
        except (ValueError, WireError, launcher.RuntimeNotFound) as error:
            await websocket.send_json({"type": "error", "message": str(error)})

    # ----- workspace -----------------------------------------------------

    def _workspace(path: str) -> Path:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_dir():
            raise HTTPException(400, "Workspace not found.")
        return resolved

    @app.get("/api/workspace/files")
    async def files(path: str) -> dict:
        return await asyncio.to_thread(workspace.list_files, _workspace(path))

    @app.get("/api/workspace/file")
    async def file(path: str, file: str) -> dict:
        try:
            return await asyncio.to_thread(workspace.read_file, _workspace(path), file)
        except (workspace.WorkspaceError, OSError) as error:
            raise HTTPException(400, str(error)) from error

    @app.get("/api/workspace/changes")
    async def changes(path: str) -> dict:
        return await asyncio.to_thread(workspace.git_changes, _workspace(path))

    @app.get("/api/fs/dirs")
    async def dirs(path: str | None = None) -> dict:
        try:
            return await asyncio.to_thread(workspace.list_dirs, path)
        except (workspace.WorkspaceError, OSError) as error:
            raise HTTPException(400, str(error)) from error

    # ----- memory --------------------------------------------------------

    @app.get("/api/memory")
    async def memories(path: str, q: str | None = None) -> dict:
        root = _workspace(path)
        try:
            if q:
                items = await services.memory.recall(q, root, limit=20)
            else:
                items = await services.memory.list_memories(root)
        except Exception as error:  # noqa: BLE001
            return {"items": [], "status": services.memory.status(), "error": str(error)}
        return {"items": items, "status": services.memory.status()}

    @app.delete("/api/memory/{memory_id}")
    async def forget(memory_id: str) -> dict:
        try:
            await services.memory.forget(memory_id)
        except Exception as error:  # noqa: BLE001
            raise HTTPException(400, str(error)) from error
        return {"ok": True}

    # ----- the UI --------------------------------------------------------

    @app.get("/{rest:path}", include_in_schema=False)
    async def ui(rest: str):
        if rest.startswith("api/"):
            raise HTTPException(404)
        if not UI_DIST.is_dir():
            return JSONResponse(
                {"detail": "The UI is not built. Run `npm install && npm run build` in ui/, or use `npm run dev` there."},
                status_code=404,
            )
        candidate = (UI_DIST / rest).resolve()
        if rest and candidate.is_file() and candidate.is_relative_to(UI_DIST.resolve()):
            return FileResponse(candidate)
        return FileResponse(UI_DIST / "index.html", headers={"Cache-Control": "no-cache"})

    return app
