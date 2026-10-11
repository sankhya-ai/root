"""Tools the host provides to the runtime (``initialize``'s ``external_tools``).

Each toolset contributes definitions for a given session and answers the calls
for its names. The tenant decides which toolsets exist (memory, background
processes, coding flows); a session only dispatches.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from .. import processes
from ..memory import TOOL_NAMES as MEMORY_TOOL_NAMES
from ..memory import CHECKPOINT_TOOL
from ..memory import tool_definitions as memory_tool_definitions

RECALL_EVENT_TOOL = "recall_event"

if TYPE_CHECKING:
    from .runtime import SessionRuntime


class Toolset(Protocol):
    def definitions(self, runtime: "SessionRuntime") -> list[dict[str, Any]]: ...

    def handles(self, name: str) -> bool: ...

    async def call(self, runtime: "SessionRuntime", call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


def tool_error(message: str, brief: str = "Failed") -> dict[str, Any]:
    return {"is_error": True, "output": "", "message": message, "display": [{"type": "brief", "text": brief}]}


class MemoryToolset:
    def definitions(self, runtime: "SessionRuntime") -> list[dict[str, Any]]:
        return memory_tool_definitions() if runtime.tenant.memory.enabled else []

    def handles(self, name: str) -> bool:
        return name in MEMORY_TOOL_NAMES

    async def call(self, runtime: "SessionRuntime", call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        unchecked = name == CHECKPOINT_TOOL and runtime.turn is not None and not runtime.turn.verified
        if unchecked:
            # A checkpoint outlives the session; an unexercised "fixed it" must not come back as a fact.
            arguments = {**arguments, "summary": f"UNVERIFIED (no check ran after the last edit): {arguments.get('summary') or ''}".strip()}
        result = await runtime.tenant.memory.handle_tool(name, arguments, workspace=Path(runtime.record.workspace), session_id=runtime.record.id)
        if unchecked and not result.get("is_error"):
            result["output"] = (
                "Saved as UNVERIFIED: this turn edited files and has run nothing that exercises them. "
                "Run the tests or a script that reproduces the problem before calling it done.\n\n" + str(result.get("output") or "")
            )
        return result


class ProcessToolset:
    def definitions(self, runtime: "SessionRuntime") -> list[dict[str, Any]]:
        return [processes.tool_definition()]

    def handles(self, name: str) -> bool:
        return name == processes.TOOL_NAME

    async def call(self, runtime: "SessionRuntime", call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await processes.handle(
            runtime.processes,
            arguments,
            approve=lambda command: runtime.approve_host_command(call_id, command, "Start in the background"),
        )


class ContextToolset:
    """Context-management tools: recall_event restores elided tool observations (M2)."""

    def handles(self, name: str) -> bool:
        return name == RECALL_EVENT_TOOL

    def definitions(self, runtime: "SessionRuntime") -> list[dict[str, Any]]:
        if runtime.tenant.settings.get().context_strategy not in ("T2", "T4"):
            return []
        return [
            {
                "name": RECALL_EVENT_TOOL,
                "description": (
                    "Recover the verbatim content of an elided tool observation. "
                    "When context grows, bulky tool outputs are replaced by stubs "
                    "like '[elided: N chars]'. Call recall_event with the event id "
                    "to get the full original content back. Only call this when you "
                    "actually need the details of an elided result."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "The event id from the elided stub."},
                    },
                    "required": ["id"],
                    "additionalProperties": False,
                },
            }
        ]

    async def call(self, runtime: "SessionRuntime", call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        event_id = str(arguments.get("id") or "").strip()
        if not event_id:
            return tool_error("Missing `id` argument.", "Missing id")
        result = runtime.context_mgr.store.retrieve(event_id)
        if result is None:
            return tool_error(f"Event id `{event_id}` not found (it may have been pruned).", "Not found")
        return {"is_error": False, "output": "", "message": "", "display": [{"type": "brief", "text": f"Restored {len(result)} chars"}], "return_value": {"content": result}}
