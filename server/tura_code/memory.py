"""The typed Dhee gateway: root's only memory writer.

Dhee ships ~35 MCP tools. Handing all of them to a coding model would bury the
ten tools it actually works with and duplicate several (Dhee has its own read,
grep and shell). So, as in Tura, the host owns Dhee and exposes a small typed
surface instead:

* ``memory_recall``     — search durable memory (project and owner scopes);
* ``memory_remember``   — store one durable fact, preference, or decision;
* ``memory_checkpoint`` — record progress; also the runtime's
  ``context_continuity_tool``, called after context compaction so the
  compacted conversation gets Dhee's durable state back.

Around each turn the host also does what Dhee calls the memory loop:

* before: compile a short packet of relevant memory into the request;
* after: checkpoint turns that did real work (edits or several tool calls).

Two scopes keep memory honest: ``project`` (keyed by workspace path) for
conventions, commands and decisions of one codebase, and ``owner`` for the
person's own preferences, which follow them across projects.

Dhee is synchronous and SQLite-backed, so every call runs on one dedicated
worker thread. Nothing here ever fails a turn: a Dhee error becomes a tool
error the model can read, or an omitted packet.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .settings import Settings

logger = logging.getLogger(__name__)

RECALL_TOOL = "memory_recall"
REMEMBER_TOOL = "memory_remember"
CHECKPOINT_TOOL = "memory_checkpoint"

OWNER_SCOPE = "owner"
PACKET_CHAR_LIMIT = 2_400
CONTEXT_TIMEOUT_SECONDS = 6.0
_KINDS = ("preference", "convention", "command", "decision", "fact", "gotcha")
_WORD = re.compile(r"[a-z0-9_]{3,}")
_STOP = frozenset(
    "the and for with that this from have has was were are you your our can will not "
    "into when then than what which who how why use using used also just only more "
    "some any all its it's they them their there here about after before over under".split()
)

MEMORY_ROLE = """\
You have long-term memory (Dhee) that persists across sessions and projects:
- memory_recall: search it when earlier decisions, project conventions, or the owner's preferences could matter.
- memory_remember: save a durable fact worth knowing next time — an owner preference, a project convention, a build/test command, an architectural decision, a gotcha you hit. One fact per call. Never store secrets, transient task state, or code.
- memory_checkpoint: at a natural stopping point in long work, record what was done, what worked, what failed, and what remains.
Relevant memories are attached automatically at the start of a request in the `## System` section. Treat them as advisory: the owner's current request wins."""


def project_scope(workspace: Path | str) -> str:
    digest = hashlib.sha1(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()[:16]
    return f"project:{digest}"


def tool_definitions() -> list[dict[str, Any]]:
    scope_prop = {
        "type": "string",
        "enum": ["project", "owner"],
        "description": "`project` for facts about this codebase; `owner` for the person's own preferences that apply everywhere.",
    }
    return [
        {
            "name": RECALL_TOOL,
            "description": (
                "Search long-term memory for facts from earlier sessions: project conventions, build and "
                "test commands, architectural decisions, known gotchas, and the owner's preferences. "
                "Returns the most relevant memories with ids."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What you want to know, in plain words."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20, "description": "Maximum results (default 6)."},
                    "scope": {
                        "type": "string",
                        "enum": ["all", "project", "owner"],
                        "description": "Which memory to search (default all).",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": REMEMBER_TOOL,
            "description": (
                "Store ONE durable fact in long-term memory so it is known in future sessions. Use for owner "
                "preferences, project conventions, build/test commands, architectural decisions, and gotchas. "
                "Never store secrets, credentials, transient task state, or code."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The fact, written as a standalone sentence."},
                    "kind": {"type": "string", "enum": list(_KINDS), "description": "What sort of fact this is."},
                    "scope": scope_prop,
                },
                "required": ["content"],
                "additionalProperties": False,
            },
        },
        {
            "name": CHECKPOINT_TOOL,
            "description": (
                "Record progress on the current work in long-term memory: a summary, what worked, what failed, "
                "decisions made, remaining todos, and files touched. Returns the durable context Dhee holds for "
                "this project. Use at a natural stopping point in long, multi-step work."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "What was being worked on and where it stands."},
                    "what_worked": {"type": "string"},
                    "what_failed": {"type": "string"},
                    "decisions": {"type": "array", "items": {"type": "string"}},
                    "todos": {"type": "array", "items": {"type": "string"}},
                    "files_touched": {"type": "array", "items": {"type": "string"}},
                    "session_id": {"type": "string"},
                    "workspace_root": {"type": "string"},
                },
                "required": ["summary"],
                "additionalProperties": True,
            },
        },
    ]


@dataclass
class Packet:
    text: str
    items: list[dict[str, Any]] = field(default_factory=list)


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _return(output: str, message: str = "", *, error: bool = False, brief: str = "") -> dict[str, Any]:
    display = [{"type": "brief", "text": brief}] if brief else []
    return {"is_error": error, "output": output, "message": message, "display": display}


class MemoryGateway:
    """Owns the one Dhee instance and every read and write to it."""

    def __init__(self, root: Path, settings_provider: Callable[[], Settings]) -> None:
        self.root = root
        self._settings = settings_provider
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="dhee")
        self._dhee: Any = None
        self._built_for: tuple | None = None
        self._error = ""
        self._active_mode = "off"

    # ----- lifecycle -----------------------------------------------------

    def _wanted(self) -> tuple:
        s = self._settings()
        if s.memory_mode == "openrouter":
            return ("openrouter", s.api_key(), s.base_url, s.memory_llm_model, s.memory_embedding_model, s.memory_embedding_dims)
        return (s.memory_mode,)

    @property
    def enabled(self) -> bool:
        return self._settings().memory_mode != "off"

    def status(self) -> dict[str, Any]:
        try:
            import dhee  # noqa: F401

            installed = True
            version = getattr(dhee, "__version__", "")
        except Exception:  # noqa: BLE001
            installed, version = False, ""
        return {
            "requested_mode": self._settings().memory_mode,
            "active_mode": self._active_mode,
            "installed": installed,
            "version": version,
            "ready": self._dhee is not None,
            "error": self._error,
        }

    def _ensure(self) -> Any:
        """Build (or rebuild after a settings change) the Dhee instance. Worker thread only."""
        wanted = self._wanted()
        if self._dhee is not None and self._built_for == wanted:
            return self._dhee
        self._close_current()
        mode = wanted[0]
        if mode == "off":
            self._built_for, self._active_mode = wanted, "off"
            return None
        try:
            from dhee import Dhee
        except Exception as error:  # noqa: BLE001
            self._error = f"Dhee is not installed ({error}). Install with `pip install 'dhee[openai,zvec]'`."
            self._built_for, self._active_mode = wanted, "off"
            return None
        data_dir = self.root / "dhee"
        data_dir.mkdir(parents=True, exist_ok=True)
        dhee = Dhee(provider="mock", data_dir=data_dir, user_id=OWNER_SCOPE, auto_context=False, auto_checkpoint=False)
        self._error = ""
        self._active_mode = "local"
        if mode == "openrouter":
            try:
                self._use_openrouter(dhee, self._settings())
                self._active_mode = "openrouter"
            except Exception as error:  # noqa: BLE001 - fall back to local memory, loudly
                logger.warning("Dhee OpenRouter lane unavailable; using local memory", exc_info=True)
                self._error = f"OpenRouter memory unavailable, using local memory: {error}"
        self._dhee = dhee
        self._built_for = wanted
        return dhee

    @staticmethod
    def _use_openrouter(dhee: Any, settings: Settings) -> None:
        """Point Dhee's embedder and enrichment LLM at OpenRouter.

        Dhee's facade picks providers from its own environment detection, so —
        as Tura's hub does — the memory is rebuilt here with explicit OpenRouter
        lanes. A separate vector collection per embedding width keeps vectors
        from two models from ever being compared with each other.
        """
        key = settings.api_key()
        if not key:
            raise RuntimeError("no OpenRouter API key is configured")
        from dhee.configs.base import EmbedderConfig, LLMConfig, VectorStoreConfig
        from dhee.memory.main import FullMemory

        engram = dhee._engram
        base = engram._memory.config
        dims = int(settings.memory_embedding_dims)
        config = base.model_copy(deep=True)
        config.llm = LLMConfig(
            provider="openai",
            config={
                "model": settings.memory_llm_model,
                "api_key": key,
                "base_url": settings.base_url,
                "temperature": 0.2,
                "max_tokens": 2048,
            },
        )
        config.embedder = EmbedderConfig(
            provider="openai",
            config={
                "model": settings.memory_embedding_model,
                "api_key": key,
                "base_url": settings.base_url,
                "embedding_dims": dims,
            },
        )
        config.vector_store = VectorStoreConfig(
            provider="zvec",
            config={
                "collection_name": f"tura_openrouter_{dims}",
                "path": str(Path(engram.data_dir) / "zvec"),
                "embedding_model_dims": dims,
            },
        )
        config.embedding_model_dims = dims
        engram._memory = FullMemory(config)
        engram._provider = "openai"

    def _close_current(self) -> None:
        if self._dhee is not None:
            try:
                self._dhee.close()
            except Exception:  # noqa: BLE001
                logger.debug("Dhee close failed", exc_info=True)
        self._dhee = None

    async def _run(self, fn: Callable[[Any], Any], timeout: float | None = None) -> Any:
        def work() -> Any:
            dhee = self._ensure()
            if dhee is None:
                raise MemoryUnavailable(self._error or "Memory is switched off.")
            return fn(dhee)

        future = asyncio.get_running_loop().run_in_executor(self._executor, work)
        if timeout is None:
            return await future
        return await asyncio.wait_for(future, timeout)

    async def warm(self) -> None:
        if not self.enabled:
            return
        try:
            await self._run(lambda dhee: None)
        except Exception:  # noqa: BLE001
            logger.info("Dhee warm-up failed: %s", self._error)

    async def close(self) -> None:
        await asyncio.get_running_loop().run_in_executor(self._executor, self._close_current)
        self._executor.shutdown(wait=False)

    # ----- reads ---------------------------------------------------------

    def _search(self, dhee: Any, query: str, scopes: list[str], limit: int) -> list[dict[str, Any]]:
        query_words = _words(query)
        found: dict[str, dict[str, Any]] = {}
        for scope in scopes:
            try:
                rows = dhee.recall(query, user_id=scope, limit=max(limit * 2, 8))
            except Exception:  # noqa: BLE001
                logger.debug("recall failed for %s", scope, exc_info=True)
                continue
            for row in rows or []:
                text = str(row.get("memory") or "").strip()
                if not text:
                    continue
                overlap = len(query_words & _words(text))
                # Local mode embeds by hashing, so its similarity alone ranks
                # unrelated facts highly. Shared words are the honest floor.
                if self._active_mode == "local" and query_words and overlap == 0:
                    continue
                score = float(row.get("score") or 0.0) + 0.15 * overlap
                item = {
                    "id": str(row.get("id") or ""),
                    "memory": text,
                    "scope": "owner" if scope == OWNER_SCOPE else "project",
                    "score": round(score, 3),
                }
                key = item["id"] or text
                if key not in found or found[key]["score"] < score:
                    found[key] = item
        ranked = sorted(found.values(), key=lambda item: item["score"], reverse=True)
        return ranked[:limit]

    async def recall(self, query: str, workspace: Path, *, scope: str = "all", limit: int = 6) -> list[dict[str, Any]]:
        scopes = {
            "project": [project_scope(workspace)],
            "owner": [OWNER_SCOPE],
        }.get(scope, [project_scope(workspace), OWNER_SCOPE])
        return await self._run(lambda dhee: self._search(dhee, query, scopes, limit))

    async def list_memories(self, workspace: Path, limit: int = 200) -> list[dict[str, Any]]:
        def work(dhee: Any) -> list[dict[str, Any]]:
            items: list[dict[str, Any]] = []
            for scope in (project_scope(workspace), OWNER_SCOPE):
                try:
                    rows = dhee._engram.get_all(user_id=scope, limit=limit)
                except Exception:  # noqa: BLE001
                    logger.debug("get_all failed", exc_info=True)
                    continue
                rows = rows.get("results", rows) if isinstance(rows, dict) else rows
                for row in rows or []:
                    items.append(
                        {
                            "id": str(row.get("id") or ""),
                            "memory": str(row.get("memory") or row.get("content") or ""),
                            "scope": "owner" if scope == OWNER_SCOPE else "project",
                            "created_at": row.get("created_at"),
                            "metadata": row.get("metadata") or {},
                        }
                    )
            return items

        return await self._run(work)

    async def forget(self, memory_id: str) -> None:
        await self._run(lambda dhee: dhee._engram.delete(memory_id))

    async def compile_packet(self, prompt: str, workspace: Path, *, seen: set[str], first_turn: bool) -> Packet | None:
        """The memory worth attaching to this request, or ``None``.

        Only memories not yet shown in this session are attached, so a long
        session does not pay for the same facts on every turn. Lessons from
        earlier work (Dhee's insights and warnings) come with the first turn.
        """
        if not self.enabled or not prompt.strip():
            return None
        scope = project_scope(workspace)

        def work(dhee: Any) -> Packet | None:
            hits = [item for item in self._search(dhee, prompt, [scope, OWNER_SCOPE], 8) if item["id"] not in seen]
            lessons: list[str] = []
            if first_turn:
                try:
                    context = dhee.context(task_description=prompt, user_id=scope) or {}
                except Exception:  # noqa: BLE001
                    context = {}
                for warning in (context.get("warnings") or [])[:3]:
                    lessons.append(f"Warning: {_clip(warning, 240)}")
                for insight in (context.get("insights") or [])[:4]:
                    content = insight.get("content") if isinstance(insight, dict) else insight
                    if content and f"Warning: {_clip(content, 240)}" not in lessons:
                        lessons.append(_clip(content, 240))
                for intention in (context.get("intentions") or [])[:2]:
                    text = intention.get("description") if isinstance(intention, dict) else intention
                    if text:
                        lessons.append(f"Reminder: {_clip(text, 240)}")
            if not hits and not lessons:
                return None
            lines = ["Memory from earlier sessions (Dhee). Advisory: the request below wins if they conflict."]
            project = [h for h in hits if h["scope"] == "project"]
            owner = [h for h in hits if h["scope"] == "owner"]
            if project:
                lines.append("Project memory:")
                lines += [f"- {_clip(h['memory'], 300)}" for h in project]
            if owner:
                lines.append("Owner preferences:")
                lines += [f"- {_clip(h['memory'], 300)}" for h in owner]
            if lessons:
                lines.append("Lessons from earlier work:")
                lines += [f"- {lesson}" for lesson in lessons]
            text = "\n".join(lines)
            if len(text) > PACKET_CHAR_LIMIT:
                text = text[: PACKET_CHAR_LIMIT - 1] + "…"
            return Packet(text=text, items=hits)

        try:
            return await self._run(work, timeout=CONTEXT_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.info("Dhee packet skipped: memory busy for %.0fs", CONTEXT_TIMEOUT_SECONDS)
        except MemoryUnavailable:
            pass
        except Exception:  # noqa: BLE001
            logger.warning("Dhee packet failed", exc_info=True)
        return None

    # ----- writes --------------------------------------------------------

    async def remember(self, content: str, workspace: Path, *, scope: str = "project", kind: str = "fact", session_id: str = "") -> dict[str, Any]:
        user_id = OWNER_SCOPE if scope == "owner" else project_scope(workspace)
        metadata = {"kind": kind, "source": "tura-code", "workspace": str(workspace), "session_id": session_id}
        return await self._run(lambda dhee: dhee.remember(content, user_id=user_id, metadata=metadata))

    async def checkpoint(self, workspace: Path, *, summary: str, status: str = "paused", **fields: Any) -> dict[str, Any]:
        scope = project_scope(workspace)
        allowed = {"what_worked", "what_failed", "decisions", "todos", "files_touched", "task_type", "outcome_score", "key_decision", "remember_to"}
        kwargs = {k: v for k, v in fields.items() if k in allowed and v}
        return await self._run(
            lambda dhee: dhee.checkpoint(
                summary=summary,
                status=status,
                repo=str(workspace),
                user_id=scope,
                agent_id="tura-code",
                **kwargs,
            )
        )

    # ----- the runtime's tool calls --------------------------------------

    async def handle_tool(self, name: str, arguments: dict[str, Any], *, workspace: Path, session_id: str) -> dict[str, Any]:
        try:
            if name == RECALL_TOOL:
                query = str(arguments.get("query") or "").strip()
                if not query:
                    return _return("", "`query` is required.", error=True, brief="Missing query")
                limit = max(1, min(20, int(arguments.get("limit") or 6)))
                hits = await self.recall(query, workspace, scope=str(arguments.get("scope") or "all"), limit=limit)
                if not hits:
                    return _return("No relevant memories found.", "", brief="No memories")
                lines = [f"- [{h['scope']}] {h['memory']} (id: {h['id']})" for h in hits]
                return _return("\n".join(lines), f"{len(hits)} memories", brief=f"Recalled {len(hits)}")
            if name == REMEMBER_TOOL:
                content = str(arguments.get("content") or "").strip()
                if not content:
                    return _return("", "`content` is required.", error=True, brief="Nothing to remember")
                kind = str(arguments.get("kind") or "fact")
                scope = "owner" if arguments.get("scope") == "owner" else "project"
                result = await self.remember(content, workspace, scope=scope, kind=kind, session_id=session_id)
                if isinstance(result, dict) and result.get("stored") is False:
                    reason = result.get("reason") or result.get("event") or "rejected by Dhee's admission policy"
                    return _return(f"Not stored: {reason}", "", brief="Not stored")
                memory_id = result.get("id", "") if isinstance(result, dict) else ""
                return _return(f"Stored in {scope} memory (id: {memory_id}).", "", brief=f"Remembered ({scope})")
            if name == CHECKPOINT_TOOL:
                summary = str(arguments.get("summary") or "").strip() or "Work in progress."
                fields = {k: arguments.get(k) for k in ("what_worked", "what_failed", "decisions", "todos", "files_touched")}
                await self.checkpoint(workspace, summary=summary, **fields)
                restored = await self.compile_packet(summary, workspace, seen=set(), first_turn=True)
                body = restored.text if restored else "No additional durable memory for this project yet."
                return _return(f"Checkpoint saved.\n\n{body}", "", brief="Checkpoint saved")
            return _return("", f"Unknown memory tool `{name}`.", error=True, brief="Unknown tool")
        except MemoryUnavailable as error:
            return _return("", f"Memory is unavailable: {error}", error=True, brief="Memory unavailable")
        except Exception as error:  # noqa: BLE001 - a memory fault is a tool error, not a failed turn
            logger.exception("memory tool %s failed", name)
            return _return("", f"Memory error: {error}", error=True, brief="Memory error")


class MemoryUnavailable(RuntimeError):
    pass


def packet_envelope(packet_text: str, request: str, workspace: Path) -> str:
    """The request with host context in the envelope the runtime's director reads.

    The Jev director splits `## System` from `## User` so it judges the step
    against the actual request, not against the memory attached to it.
    """
    return (
        "## System\n"
        f"You are root working in `{workspace}`.\n\n"
        f"{packet_text}\n\n"
        "## User\n"
        f"{request}"
    )


def split_envelope(text: str) -> tuple[str, str]:
    """(host context, request) for display; the inverse of ``packet_envelope``."""
    stripped = text.lstrip()
    if stripped.startswith("## System") and "\n## User\n" in stripped:
        head, request = stripped.split("\n## User\n", 1)
        return head[len("## System"):].strip(), request
    return "", text


def now() -> float:
    return time.time()
