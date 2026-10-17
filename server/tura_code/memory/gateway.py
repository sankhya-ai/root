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
import logging
from pathlib import Path
from typing import Any, Callable

from ..settings import Settings
from .errors import MemoryUnavailableError
from .scopes import OWNER_SCOPE, PACKET_CHAR_LIMIT, Packet, clip, project_scope, words

logger = logging.getLogger(__name__)

CONTEXT_TIMEOUT_SECONDS = 6.0


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
        # Real memory (extraction, embeddings, decisions) needs the OpenRouter key; until
        # there is one, local memory is the honest default rather than an error.
        if mode == "openrouter" and self._settings().api_key():
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

        Dhee's facade picks providers from its own environment detection and
        takes no config, so — as Tura's hub does — the memory is rebuilt here
        with explicit OpenRouter lanes: the one place root reaches past Dhee's
        public API (``_engram``, ``_memory``). A separate vector collection per
        embedding width keeps vectors from two models from ever being compared.

        Decisions (Dhee 7.4, Jev through OpenRouter) gate the write path: a fact
        that restates a stored one reaffirms it instead of adding a duplicate.
        No ``fact_subjects``: project memory is about the code, not a person.
        """
        key = settings.api_key()
        if not key:
            raise RuntimeError("no OpenRouter API key is configured")
        from dhee.configs.base import DecisionConfig, EmbedderConfig, LLMConfig, VectorStoreConfig
        from dhee.memory.main import FullMemory

        engram = dhee._engram
        base = engram.memory.config
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
        if "openrouter.ai" in settings.base_url:
            config.decisions = DecisionConfig(enabled=True, provider="openrouter", api_key=key)
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
                raise MemoryUnavailableError(self._error or "Memory is switched off.")
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

    def _search(self, dhee: Any, query: str, scopes: list[str], limit: int, owner: str) -> list[dict[str, Any]]:
        query_words = words(query)
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
                overlap = len(query_words & words(text))
                # Local mode embeds by hashing, so its similarity alone ranks
                # unrelated facts highly. Shared words are the honest floor.
                if self._active_mode == "local" and query_words and overlap == 0:
                    continue
                score = float(row.get("score") or 0.0) + 0.15 * overlap
                item = {
                    "id": str(row.get("id") or ""),
                    "memory": text,
                    "scope": "owner" if scope == owner else "project",
                    "score": round(score, 3),
                }
                key = item["id"] or text
                if key not in found or found[key]["score"] < score:
                    found[key] = item
        ranked = sorted(found.values(), key=lambda item: item["score"], reverse=True)
        return ranked[:limit]

    async def recall(self, query: str, workspace: Path, *, scope: str = "all", limit: int = 6, owner: str = OWNER_SCOPE) -> list[dict[str, Any]]:
        scopes = {
            "project": [project_scope(workspace)],
            "owner": [owner],
        }.get(scope, [project_scope(workspace), owner])
        return await self._run(lambda dhee: self._search(dhee, query, scopes, limit, owner))

    async def list_memories(self, workspace: Path, limit: int = 200, owner: str = OWNER_SCOPE) -> list[dict[str, Any]]:
        def work(dhee: Any) -> list[dict[str, Any]]:
            items: list[dict[str, Any]] = []
            for scope in (project_scope(workspace), owner):
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
                            "scope": "owner" if scope == owner else "project",
                            "created_at": row.get("created_at"),
                            "metadata": row.get("metadata") or {},
                        }
                    )
            return items

        return await self._run(work)

    async def forget(self, memory_id: str) -> None:
        await self._run(lambda dhee: dhee._engram.delete(memory_id))

    async def compile_packet(self, prompt: str, workspace: Path, *, seen: set[str], first_turn: bool, owner: str = OWNER_SCOPE) -> Packet | None:
        """The memory worth attaching to this request, or ``None``.

        Only memories not yet shown in this session are attached, so a long
        session does not pay for the same facts on every turn. Lessons from
        earlier work (Dhee's insights and warnings) come with the first turn.
        """
        if not self.enabled or not prompt.strip():
            return None
        scope = project_scope(workspace)

        def work(dhee: Any) -> Packet | None:
            hits = [item for item in self._search(dhee, prompt, [scope, owner], 8, owner) if item["id"] not in seen]
            lessons: list[str] = []
            if first_turn:
                try:
                    context = dhee.context(task_description=prompt, user_id=scope) or {}
                except Exception:  # noqa: BLE001
                    context = {}
                for warning in (context.get("warnings") or [])[:3]:
                    lessons.append(f"Warning: {clip(warning, 240)}")
                for insight in (context.get("insights") or [])[:4]:
                    content = insight.get("content") if isinstance(insight, dict) else insight
                    if content and f"Warning: {clip(content, 240)}" not in lessons:
                        lessons.append(clip(content, 240))
                for intention in (context.get("intentions") or [])[:2]:
                    text = intention.get("description") if isinstance(intention, dict) else intention
                    if text:
                        lessons.append(f"Reminder: {clip(text, 240)}")
            if not hits and not lessons:
                return None
            lines = ["Memory from earlier sessions (Dhee). Advisory: the request below wins if they conflict."]
            project = [h for h in hits if h["scope"] == "project"]
            preferences = [h for h in hits if h["scope"] == "owner"]
            if project:
                lines.append("Project memory:")
                lines += [f"- {clip(h['memory'], 300)}" for h in project]
            if preferences:
                lines.append("Owner preferences:")
                lines += [f"- {clip(h['memory'], 300)}" for h in preferences]
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
        except MemoryUnavailableError:
            pass
        except Exception:  # noqa: BLE001
            logger.warning("Dhee packet failed", exc_info=True)
        return None

    # ----- writes --------------------------------------------------------

    async def remember(self, content: str, workspace: Path, *, scope: str = "project", kind: str = "fact", session_id: str = "", owner: str = OWNER_SCOPE) -> dict[str, Any]:
        user_id = owner if scope == "owner" else project_scope(workspace)
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


class MemoryView:
    """The gateway bound to one person's owner scope; what a tenant uses.

    One Dhee instance serves every tenant (one SQLite store, one embedder, one
    worker thread) instead of one per user; the scope keeps them apart.
    """

    def __init__(self, gateway: MemoryGateway, owner: str = OWNER_SCOPE) -> None:
        self.gateway = gateway
        self.owner = owner

    @property
    def enabled(self) -> bool:
        return self.gateway.enabled

    def status(self) -> dict[str, Any]:
        return self.gateway.status()

    async def recall(self, query: str, workspace: Path, *, scope: str = "all", limit: int = 6) -> list[dict[str, Any]]:
        return await self.gateway.recall(query, workspace, scope=scope, limit=limit, owner=self.owner)

    async def list_memories(self, workspace: Path, limit: int = 200) -> list[dict[str, Any]]:
        return await self.gateway.list_memories(workspace, limit, owner=self.owner)

    async def forget(self, memory_id: str, workspace: Path) -> bool:
        """Forget a memory, but only one this person can see."""
        visible = {item["id"] for item in await self.list_memories(workspace, limit=1000)}
        if memory_id not in visible:
            return False
        await self.gateway.forget(memory_id)
        return True

    async def compile_packet(self, prompt: str, workspace: Path, *, seen: set[str], first_turn: bool) -> Packet | None:
        return await self.gateway.compile_packet(prompt, workspace, seen=seen, first_turn=first_turn, owner=self.owner)

    async def remember(self, content: str, workspace: Path, *, scope: str = "project", kind: str = "fact", session_id: str = "") -> dict[str, Any]:
        return await self.gateway.remember(content, workspace, scope=scope, kind=kind, session_id=session_id, owner=self.owner)

    async def checkpoint(self, workspace: Path, *, summary: str, status: str = "paused", **fields: Any) -> dict[str, Any]:
        return await self.gateway.checkpoint(workspace, summary=summary, status=status, **fields)

    async def handle_tool(self, name: str, arguments: dict[str, Any], *, workspace: Path, session_id: str) -> dict[str, Any]:
        from .tools import handle_tool

        return await handle_tool(self, name, arguments, workspace=workspace, session_id=session_id)
