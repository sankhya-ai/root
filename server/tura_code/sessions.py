"""Sessions: one conversation in one workspace, backed by one runtime process.

A session outlives its process. The runtime keeps the conversation context on
disk (``--session <id>`` resumes it), so the host can stop an idle process and
start a new one on the next prompt, or restart it when a setting that shapes
the process changes (model, plan mode, memory).

Every event is fanned out live to the session's subscribers (browser tabs) and
appended to ``events.jsonl``. Streaming deltas are coalesced before they are
written, so a reloaded session replays as whole messages.

Permission modes are enforced here, at the approval boundary:

* ``default``      — every approval the runtime asks for goes to the owner;
* ``accept_edits`` — file edits inside the workspace are approved, the rest asks;
* ``plan``         — file-edit tools are removed from the agent; the rest asks;
* ``yolo``         — everything is approved.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import os
import re
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import launcher
from .memory import CHECKPOINT_TOOL, RECALL_TOOL, REMEMBER_TOOL, MemoryGateway, packet_envelope, tool_definitions
from .settings import PermissionMode, SettingsStore
from .wire import WireError, WireProcess

logger = logging.getLogger(__name__)

IDLE_SECONDS = 20 * 60
MEMORY_TOOLS = {RECALL_TOOL, REMEMBER_TOOL, CHECKPOINT_TOOL}
EDIT_TOOLS = {"WriteFile", "StrReplaceFile"}
AUTO_EDIT_ACTIONS = {"edit file"}
MENTION = re.compile(r"(?<![\w/])@([\w./\-]+[\w\-])")
MENTION_BYTES = 60_000
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

    @classmethod
    def load(cls, path: Path) -> "SessionRecord":
        data = json.loads(path.read_text("utf-8"))
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


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


class SessionRuntime:
    def __init__(self, manager: "SessionManager", record: SessionRecord) -> None:
        self.manager = manager
        self.record = record
        self.dir = manager.sessions_dir / record.id
        self.events_file = self.dir / "events.jsonl"
        self.process: WireProcess | None = None
        self._fingerprint: tuple | None = None
        self._start_lock = asyncio.Lock()
        self.subscribers: set[asyncio.Queue] = set()
        self.pending: dict[str, tuple[asyncio.Future, dict]] = {}
        self.turn: TurnState | None = None
        self._turn_task: asyncio.Task | None = None
        self._seq = self._last_seq()
        self._buffer: dict | None = None
        self.last_activity = time.time()
        self.memory_seen: set[str] = set()
        self.runtime_state = "stopped"
        self.runtime_info: dict[str, Any] = {}

    # ----- persistence ---------------------------------------------------

    def _last_seq(self) -> int:
        if not self.events_file.exists():
            return 0
        last = 0
        with self.events_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    last = max(last, int(json.loads(line).get("seq") or 0))
                except (ValueError, json.JSONDecodeError):
                    continue
        return last

    def save_record(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / "session.tmp"
        tmp.write_text(json.dumps(asdict(self.record), indent=2), "utf-8")
        tmp.replace(self.dir / "session.json")

    def history(self) -> list[dict]:
        events: list[dict] = []
        if self.events_file.exists():
            with self.events_file.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        if self._buffer is not None:
            events.append(json.loads(json.dumps(self._buffer)))
        return events

    def _persist(self, event: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.events_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _flush_buffer(self) -> None:
        if self._buffer is not None:
            self._persist(self._buffer)
            self._buffer = None

    def _record_event(self, event: dict) -> None:
        """Append to the log, merging streaming deltas into whole messages."""
        kind = event["type"]
        if kind == "ContentPart":
            part_type = event["payload"].get("type")
            buffered = self._buffer
            if (
                buffered is not None
                and buffered["type"] == "ContentPart"
                and buffered["payload"].get("type") == part_type
                and part_type in ("text", "think")
            ):
                key = "text" if part_type == "text" else "think"
                buffered["payload"][key] = (buffered["payload"].get(key) or "") + (event["payload"].get(key) or "")
                return
            self._flush_buffer()
            self._buffer = json.loads(json.dumps(event))
            return
        if kind == "ToolCallPart":
            buffered = self._buffer
            if buffered is not None and buffered["type"] == "ToolCall":
                function = buffered["payload"].setdefault("function", {})
                function["arguments"] = (function.get("arguments") or "") + (
                    event["payload"].get("arguments_part") or ""
                )
                return
            self._flush_buffer()
            self._persist(event)
            return
        self._flush_buffer()
        if kind == "ToolCall":
            self._buffer = json.loads(json.dumps(event))
            return
        self._persist(event)

    # ----- fan-out -------------------------------------------------------

    def emit(self, kind: str, payload: dict, *, persist: bool = True) -> dict:
        self._seq += 1
        event = {
            "seq": self._seq,
            "ts": time.time(),
            "turn": self.turn.id if self.turn else None,
            "type": kind,
            "payload": payload,
        }
        if persist:
            self._record_event(event)
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("dropping a slow subscriber of %s", self.record.id)
                self.subscribers.discard(queue)
        self.last_activity = time.time()
        return event

    def snapshot(self) -> dict:
        return {
            "session": self.public(),
            "history": self.history(),
            "pending_approvals": [payload for _, payload in self.pending.values()],
        }

    def subscribe(self) -> tuple[asyncio.Queue, dict]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=10_000)
        # No await between the snapshot and the registration: an event is in
        # exactly one of the two.
        snapshot = self.snapshot()
        self.subscribers.add(queue)
        return queue, snapshot

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.discard(queue)

    def public(self) -> dict:
        data = asdict(self.record)
        data["running"] = self.turn is not None
        data["runtime_state"] = self.runtime_state
        data["runtime"] = self.runtime_info
        return data

    # ----- the runtime process ------------------------------------------

    def _launch_spec(self) -> launcher.LaunchSpec:
        settings = self.manager.settings.get()
        return launcher.LaunchSpec(
            session_id=self.record.id,
            workspace=Path(self.record.workspace),
            settings=settings,
            permission_mode=self.record.permission_mode,  # type: ignore[arg-type]
            memory_enabled=self.manager.memory.enabled,
            capabilities=self.manager.capabilities_for(settings.model),
            mcp_config=launcher.user_mcp_config(self.manager.root),
        )

    async def ensure_process(self) -> WireProcess:
        async with self._start_lock:
            spec = self._launch_spec()
            fingerprint = spec.fingerprint()
            if self.process is not None and self.process.alive and fingerprint == self._fingerprint:
                return self.process
            if self.process is not None:
                await self._stop_process()
            if not spec.settings.api_key() and not os.environ.get(launcher.SCRIPTED_ECHO_ENV):
                raise WireError("No OpenRouter API key is set. Add one in Settings, or set OPENROUTER_API_KEY.")
            binary = launcher.find_runtime_binary()
            runtime_dir = self.dir / "runtime"
            config_file = launcher.write_runtime_config(spec.settings, runtime_dir, spec.capabilities)
            agent_file = launcher.write_agent_overlay(spec, runtime_dir)
            env = launcher.child_environment(spec, self.dir / "kimi")
            argv = launcher.runtime_argv(binary, spec, config_file, agent_file)
            self.runtime_state = "starting"
            self.emit("RuntimeStatus", {"state": "starting"}, persist=False)
            process = WireProcess(
                argv,
                cwd=spec.workspace,
                env=env,
                on_event=self._on_wire_event,
                on_request=self._on_wire_request,
                on_exit=self._on_exit,
            )
            await process.start()
            external = tool_definitions() if spec.memory_enabled else []
            try:
                result = await process.initialize(external)
            except (WireError, asyncio.TimeoutError) as error:
                detail = process.stderr_tail()
                await process.close(grace=1)
                self.runtime_state = "failed"
                self.emit("RuntimeStatus", {"state": "failed", "detail": detail or str(error)}, persist=False)
                raise WireError(f"The agent runtime failed to start: {detail or error}") from error
            self.process = process
            self._fingerprint = fingerprint
            self.runtime_state = "ready"
            self.runtime_info = {
                "server": result.get("server") or {},
                "slash_commands": result.get("slash_commands") or [],
                "model": spec.settings.model if not os.environ.get(launcher.SCRIPTED_ECHO_ENV) else "scripted-echo",
                "director": director_state(spec.settings),
                "memory": self.manager.memory.status()["active_mode"] if spec.memory_enabled else "off",
            }
            self.emit("RuntimeStatus", {"state": "ready", **self.runtime_info}, persist=False)
            return process

    async def _stop_process(self) -> None:
        process, self.process = self.process, None
        self._fingerprint = None
        if process is not None:
            await process.close()
        self.runtime_state = "stopped"

    async def _on_exit(self, returncode: int | None, detail: str) -> None:
        if self.process is not None and not self.process.alive:
            self.process = None
            self._fingerprint = None
        self.runtime_state = "stopped"
        for future, _ in list(self.pending.values()):
            if not future.done():
                future.set_result("reject")
        if self.turn is not None:
            self.emit("RuntimeStatus", {"state": "exited", "code": returncode, "detail": detail[-2000:]}, persist=False)

    # ----- runtime → host -----------------------------------------------

    async def _on_wire_event(self, kind: str, payload: dict) -> None:
        turn = self.turn
        if turn is not None:
            self._observe(turn, kind, payload)
        self.emit(kind, payload)

    def _observe(self, turn: TurnState, kind: str, payload: dict) -> None:
        if kind == "ToolCall":
            call_id = str(payload.get("id") or "")
            function = payload.get("function") or {}
            turn.tool_calls[call_id] = {"name": function.get("name") or "", "arguments": function.get("arguments") or ""}
            turn.last_call_id = call_id
            turn.tool_count += 1
        elif kind == "ToolCallPart" and turn.last_call_id in turn.tool_calls:
            turn.tool_calls[turn.last_call_id]["arguments"] += payload.get("arguments_part") or ""
        elif kind == "ToolResult":
            call = turn.tool_calls.get(str(payload.get("tool_call_id") or ""))
            result = payload.get("return_value") or {}
            if call and call["name"] in EDIT_TOOLS and not result.get("is_error"):
                try:
                    path = str(json.loads(call["arguments"] or "{}").get("path") or "")
                except json.JSONDecodeError:
                    path = ""
                if path and path not in turn.files_touched:
                    turn.files_touched.append(path)
        elif kind == "ContentPart" and payload.get("type") == "text":
            turn.text.append(payload.get("text") or "")
        elif kind == "TurnBegin":
            # The runtime restarts a turn to recover from a bad generation; the
            # abandoned draft is not the answer.
            turn.text.clear()

    async def _on_wire_request(self, request_id: str, kind: str, payload: dict) -> dict:
        if kind == "ApprovalRequest":
            response = await self._approve(payload)
            return {"request_id": payload.get("id") or request_id, "response": response}
        if kind == "ToolCallRequest":
            return await self._external_tool(payload)
        raise WireError(f"Unknown request type {kind}")

    async def _approve(self, payload: dict) -> str:
        mode = self.record.permission_mode
        action = str(payload.get("action") or "")
        auto = mode == "yolo" or (mode == "accept_edits" and action in AUTO_EDIT_ACTIONS)
        if auto:
            self.emit("ApprovalResolved", {"request_id": payload.get("id"), "response": "approve", "auto": True, "mode": mode, **_approval_summary(payload)})
            return "approve"
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        request_id = str(payload.get("id") or uuid.uuid4())
        self.pending[request_id] = (future, payload)
        self.emit("ApprovalRequest", payload)
        try:
            response = await future
        finally:
            self.pending.pop(request_id, None)
        self.emit("ApprovalResolved", {"request_id": request_id, "response": response, "auto": False, **_approval_summary(payload)})
        return response

    def resolve_approval(self, request_id: str, response: str) -> bool:
        entry = self.pending.get(request_id)
        if entry is None or entry[0].done():
            return False
        if response not in ("approve", "approve_for_session", "reject"):
            response = "reject"
        entry[0].set_result(response)
        return True

    async def _external_tool(self, payload: dict) -> dict:
        call_id = str(payload.get("id") or "")
        name = str(payload.get("name") or "")
        try:
            arguments = json.loads(payload.get("arguments") or "{}")
            if not isinstance(arguments, dict):
                raise ValueError("arguments must be a JSON object")
        except (json.JSONDecodeError, ValueError) as error:
            return {"tool_call_id": call_id, "return_value": {"is_error": True, "output": "", "message": f"Invalid arguments: {error}", "display": []}}
        if name in MEMORY_TOOLS:
            result = await self.manager.memory.handle_tool(
                name, arguments, workspace=Path(self.record.workspace), session_id=self.record.id
            )
        else:
            result = {"is_error": True, "output": "", "message": f"Unknown host tool `{name}`.", "display": []}
        return {"tool_call_id": call_id, "return_value": result}

    # ----- turns ---------------------------------------------------------

    async def prompt(self, text: str, attachments: list[dict] | None = None) -> None:
        text = (text or "").strip()
        if not text and not attachments:
            raise ValueError("Empty prompt.")
        if self.turn is not None:
            raise ValueError("A turn is already running in this session.")
        if text in ("/yolo",):
            await self.set_mode("default" if self.record.permission_mode == "yolo" else "yolo")
            return
        workspace = Path(self.record.workspace)
        turn = TurnState(id=uuid.uuid4().hex[:12], prompt=text)
        self.turn = turn
        try:
            process = await self.ensure_process()
        except Exception as error:
            self.emit("UserPrompt", {"text": text, "attachments": _attachment_meta(attachments)})
            self.emit("TurnFinished", {"status": "error", "error": str(error)})
            self.turn = None
            raise
        is_slash = text.startswith("/")
        request_text = text if is_slash else expand_mentions(text, workspace)
        memory_items: list[dict] = []
        if not is_slash and self.manager.memory.enabled:
            packet = await self.manager.memory.compile_packet(
                text, workspace, seen=self.memory_seen, first_turn=self.record.turns == 0
            )
            if packet is not None:
                request_text = packet_envelope(packet.text, request_text, workspace)
                memory_items = packet.items
                self.memory_seen.update(item["id"] for item in packet.items if item.get("id"))
        self.emit(
            "UserPrompt",
            {"text": text, "attachments": _attachment_meta(attachments), "memory": memory_items},
        )
        user_input: str | list = request_text
        if attachments:
            user_input = build_parts(request_text, attachments)
        if self.record.turns == 0 and not is_slash:
            self.record.title = _title(text)
        self.record.turns += 1
        self.record.updated_at = time.time()
        self.save_record()
        self.manager.touch(self.record)
        self.emit("SessionUpdated", self.public(), persist=False)
        self._turn_task = asyncio.create_task(self._run_turn(process, turn, user_input))

    async def _run_turn(self, process: WireProcess, turn: TurnState, user_input: str | list) -> None:
        status, extra = "error", {}
        try:
            result = await process.prompt(user_input)
            status = str(result.get("status") or "finished")
            extra = {k: v for k, v in result.items() if k != "status"}
        except WireError as error:
            extra = {"error": str(error)}
            if error.code == -32001:
                extra["error"] = "No model is configured for the runtime."
        except Exception as error:  # noqa: BLE001
            logger.exception("turn failed")
            extra = {"error": str(error)}
        finally:
            for future, _ in list(self.pending.values()):
                if not future.done():
                    future.set_result("reject")
            self._flush_buffer()
            duration = round(time.time() - turn.started_at, 2)
            self.emit("TurnFinished", {"status": status, "duration": duration, "files_touched": turn.files_touched, **extra})
            self.record.last_status = status
            self.record.updated_at = time.time()
            self.save_record()
            self.turn = None
            self._turn_task = None
        await self._checkpoint_turn(turn, status)

    async def _checkpoint_turn(self, turn: TurnState, status: str) -> None:
        """Checkpoint turns that did real work; a quick answer is not an episode."""
        memory = self.manager.memory
        if not memory.enabled or turn.prompt.startswith("/"):
            return
        if not turn.files_touched and turn.tool_count < 3:
            return
        reply = " ".join("".join(turn.text).split())
        summary = f"Request: {turn.prompt[:400]}\nOutcome ({status}): {reply[:600] or 'no final reply'}"
        try:
            await memory.checkpoint(
                Path(self.record.workspace),
                summary=summary,
                status="completed" if status == "finished" else "paused",
                files_touched=turn.files_touched,
            )
            self.emit("MemoryCheckpoint", {"saved": True, "files_touched": turn.files_touched})
        except Exception as error:  # noqa: BLE001
            logger.info("turn checkpoint skipped: %s", error)

    async def cancel(self) -> None:
        for future, _ in list(self.pending.values()):
            if not future.done():
                future.set_result("reject")
        if self.turn is not None and self.process is not None and self.process.alive:
            await self.process.cancel()

    async def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"Unknown permission mode {mode!r}")
        if mode == self.record.permission_mode:
            return
        self.record.permission_mode = mode
        self.save_record()
        self.emit("ModeChanged", {"mode": mode})
        # Auto modes also settle what is already waiting.
        if mode in ("yolo", "accept_edits"):
            for request_id, (future, payload) in list(self.pending.items()):
                if mode == "yolo" or str(payload.get("action") or "") in AUTO_EDIT_ACTIONS:
                    if not future.done():
                        future.set_result("approve")

    async def close(self) -> None:
        await self.cancel()
        if self._turn_task is not None:
            try:
                await asyncio.wait_for(self._turn_task, 10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        self._flush_buffer()
        await self._stop_process()

    def director_log(self, limit: int = 100) -> list[dict]:
        path = self.dir / "kimi" / "director.jsonl"
        if not path.exists():
            return []
        lines = path.read_text("utf-8", errors="replace").splitlines()[-limit:]
        out = []
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            record.pop("state", None)
            out.append(record)
        return out


class SessionManager:
    def __init__(self, root: Path, settings: SettingsStore, memory: MemoryGateway) -> None:
        self.root = root
        self.sessions_dir = root / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self.memory = memory
        self.runtimes: dict[str, SessionRuntime] = {}
        self.model_capabilities: dict[str, list[str]] = {}
        self._reaper: asyncio.Task | None = None

    def capabilities_for(self, model: str) -> list[str]:
        return list(self.model_capabilities.get(model, []))

    def start(self) -> None:
        if self._reaper is None:
            self._reaper = asyncio.create_task(self._reap_idle())

    async def _reap_idle(self) -> None:
        while True:
            await asyncio.sleep(60)
            now = time.time()
            for runtime in list(self.runtimes.values()):
                if (
                    runtime.process is not None
                    and runtime.turn is None
                    and not runtime.pending
                    and not runtime.subscribers
                    and now - runtime.last_activity > IDLE_SECONDS
                ):
                    logger.info("stopping idle runtime for session %s", runtime.record.id)
                    await runtime._stop_process()

    def list(self) -> list[dict]:
        records = []
        for path in self.sessions_dir.glob("*/session.json"):
            try:
                record = SessionRecord.load(path)
            except (OSError, ValueError, TypeError):
                continue
            runtime = self.runtimes.get(record.id)
            records.append(runtime.public() if runtime else {**asdict(record), "running": False, "runtime_state": "stopped", "runtime": {}})
        records.sort(key=lambda item: item["updated_at"], reverse=True)
        return records

    def create(self, workspace: str, title: str | None = None) -> SessionRuntime:
        path = Path(workspace).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"Workspace does not exist or is not a directory: {path}")
        settings = self.settings.get()
        record = SessionRecord(
            id=uuid.uuid4().hex,
            workspace=str(path),
            title=title or "New session",
            permission_mode=settings.default_permission_mode,
        )
        runtime = SessionRuntime(self, record)
        runtime.save_record()
        self.runtimes[record.id] = runtime
        self.settings.remember_workspace(str(path))
        return runtime

    def get(self, session_id: str) -> SessionRuntime:
        runtime = self.runtimes.get(session_id)
        if runtime is not None:
            return runtime
        if not re.fullmatch(r"[0-9a-f]{8,64}", session_id or ""):
            raise KeyError(session_id)
        path = self.sessions_dir / session_id / "session.json"
        if not path.exists():
            raise KeyError(session_id)
        runtime = SessionRuntime(self, SessionRecord.load(path))
        self.runtimes[session_id] = runtime
        return runtime

    def touch(self, record: SessionRecord) -> None:
        self.settings.remember_workspace(record.workspace)

    async def delete(self, session_id: str) -> None:
        runtime = self.get(session_id)
        await runtime.close()
        self.runtimes.pop(session_id, None)
        shutil.rmtree(runtime.dir, ignore_errors=True)

    async def close(self) -> None:
        if self._reaper is not None:
            self._reaper.cancel()
        for runtime in list(self.runtimes.values()):
            try:
                await runtime.close()
            except Exception:  # noqa: BLE001
                logger.exception("closing session %s", runtime.record.id)


# ----- helpers ---------------------------------------------------------------


def director_state(settings) -> str:
    """Whether Jev can actually steer: it needs an OpenRouter-shaped endpoint and a key."""
    if settings.director_mode == "off" or os.environ.get(launcher.SCRIPTED_ECHO_ENV):
        return "off"
    if not settings.api_key() or "/v1" not in settings.base_url:
        return "off"
    return settings.director_mode


def _title(text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= 60 else line[:57].rstrip() + "…"


def _approval_summary(payload: dict) -> dict:
    return {
        "tool_call_id": payload.get("tool_call_id"),
        "sender": payload.get("sender"),
        "action": payload.get("action"),
        "description": payload.get("description"),
    }


def _attachment_meta(attachments: list[dict] | None) -> list[dict]:
    return [
        {"name": item.get("name") or "attachment", "mime": item.get("mime") or "", "size": len(item.get("data") or "") * 3 // 4}
        for item in attachments or []
    ]


def expand_mentions(text: str, workspace: Path) -> str:
    """Attach the contents of ``@path`` mentions that name files in the workspace."""
    root = workspace.resolve()
    budget = MENTION_BYTES
    blocks: list[str] = []
    seen: set[str] = set()
    for match in MENTION.finditer(text):
        rel = match.group(1)
        if rel in seen:
            continue
        seen.add(rel)
        candidate = (root / rel).resolve()
        if not candidate.is_file() or not candidate.is_relative_to(root):
            continue
        try:
            raw = candidate.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:4096]:
            continue
        body = raw[:budget].decode("utf-8", errors="replace")
        budget -= len(body)
        truncated = "\n… (truncated)" if len(raw) > len(body) else ""
        blocks.append(f"<system>Contents of `{rel}` (mentioned by the user):</system>\n```\n{body}{truncated}\n```")
        if budget <= 0:
            break
    if not blocks:
        return text
    return text + "\n\n" + "\n\n".join(blocks)


def build_parts(text: str, attachments: list[dict]) -> list[dict]:
    """User input as content parts: text, then images; other files inline as text."""
    parts: list[dict] = []
    texts = [text] if text else []
    for item in attachments:
        name = str(item.get("name") or "attachment")
        mime = str(item.get("mime") or mimetypes.guess_type(name)[0] or "application/octet-stream")
        data = str(item.get("data") or "")
        if mime.startswith("image/"):
            parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})
            continue
        try:
            decoded = base64.b64decode(data).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            texts.append(f"<system>Attached file `{name}` is binary ({mime}) and was not included.</system>")
            continue
        texts.append(f"<system>Attached file `{name}`:</system>\n```\n{decoded[:MENTION_BYTES]}\n```")
    return [{"type": "text", "text": "\n\n".join(texts)}] + parts
