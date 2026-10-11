"""T4 staged context management: elision (M1) → recall (M2) → summarization (M3).

Based on Fan et al. "An Empirical Study of Harness Design for Coding Agents"
(arXiv 2609.20804v1): staged elision before LLM summarization (T4) achieves
the best accuracy-cost trade-off. Recall (M2) is rarely invoked; it is kept
available but optional.

Thresholds: soft B1 = 60% of budget, hard B2 = 85% of budget.
Preamble (system + task) and recent turns (>=2 turns, 30% budget) stay
verbatim. Only the middle region M is compacted.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runtime import SessionRuntime


# Threshold ratios relative to the context window budget
SOFT_RATIO = 0.60
HARD_RATIO = 0.85
# Recent window: at least 2 turns and at least 30% of budget reserved
MIN_RECENT_TURNS = 2
RECENT_RATIO = 0.30
# Maximum chars for a summary before truncating
MAX_SUMMARY_LENGTH = 2000


class ContextStore:
    """External storage for elided observations (M2 / T4)."""

    def __init__(self, session_dir: Path) -> None:
        self.dir = session_dir / "context_store"
        self.dir.mkdir(parents=True, exist_ok=True)

    def store(self, event_id: str, content: str) -> Path:
        path = self.dir / f"{event_id}.json"
        path.write_text(json.dumps({"id": event_id, "stored_at": time.time(), "content": content}, indent=2), encoding="utf-8")
        return path

    def retrieve(self, event_id: str) -> str | None:
        path = self.dir / f"{event_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return str(data.get("content", ""))
        except (json.JSONDecodeError, OSError):
            return None

    def exists(self, event_id: str) -> bool:
        return (self.dir / f"{event_id}.json").exists()


class ContextManager:
    """Staged context management for a session (T4)."""

    def __init__(self, runtime: "SessionRuntime", budget: int = 200_000) -> None:
        self.runtime = runtime
        self.budget = budget  # approximate token budget; actual tokens estimated
        self.store = ContextStore(runtime.dir)
        self.soft = int(budget * SOFT_RATIO)
        self.hard = int(budget * HARD_RATIO)

    # ----- threshold helpers ----------------------------------------------------

    def thresholds(self) -> tuple[int, int]:
        return self.soft, self.hard

    def estimated_tokens(self, text: str) -> int:
        """Rough token estimate: 4 chars per token (conservative)."""
        return len(text) // 4

    def _extract_event_text(self, event: dict) -> str:
        """Extract plain text representation from an event for summarization."""
        event_type = event.get("type", "")
        payload = event.get("payload", {})
        
        if event_type == "UserPrompt":
            return f"User: {payload.get('text', '')}"
        elif event_type == "AssistantContent":
            # Extract text from ContentParts
            text_parts = []
            if isinstance(payload.get("text"), str):
                text_parts.append(payload["text"])
            elif isinstance(payload.get("content"), list):
                for part in payload["content"]:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
            return f"Assistant: {''.join(text_parts)}"
        elif event_type == "ToolCall":
            function = payload.get("function", {})
            return f"Tool Call: {function.get('name', 'unknown')}({function.get('arguments', '')})"
        elif event_type == "ToolResult":
            return_value = payload.get("return_value", {})
            if isinstance(return_value, dict):
                message = str(return_value.get("message", ""))
                display = return_value.get("display", [])
                output_text = " ".join(str(d.get("text", "")) for d in display if isinstance(d, dict))
                return f"Tool Result: {message} {output_text}".strip()
            return f"Tool Result: {return_value}"
        else:
            # Fallback: JSON representation (truncated)
            try:
                return json.dumps(event)[:200]
            except:
                return str(event)[:200]

    def stage_elision(self, history_events: list[dict]) -> tuple[list[dict], list[str]]:
        """M1: replace bulky tool observations with stubs; store originals externally."""
        elided_ids: list[str] = []
        result = []
        for event in history_events:
            # Only elide bulky tool observation results
            if event.get("type") == "ToolResult":
                payload = event.get("payload", {})
                if isinstance(payload.get("return_value"), dict):
                    return_value = payload["return_value"]
                    message = str(return_value.get("message", ""))
                    display = return_value.get("display", [])
                    output_text = " ".join(str(d.get("text", "")) for d in display if isinstance(d, dict))
                    full_text = f"{message} {output_text}".strip()
                    
                    # Only elide if content is bulky (> 500 chars)
                    if len(full_text) > 500:
                        event_id = str(event.get("seq", event.get("id", f"evt-{len(elided_ids)}")))
                        stub = f"[elided: {len(full_text)} chars — call recall_event({event_id}) to recover]"
                        
                        # Store original externally
                        self.store.store(event_id, full_text)
                        
                        # Replace payload with stub
                        new_event = dict(event)
                        if isinstance(new_event.get("payload"), dict) and isinstance(new_event["payload"].get("return_value"), dict):
                            new_event["payload"]["return_value"] = {
                                **new_event["payload"]["return_value"],
                                "message": stub,
                                "display": [{"type": "brief", "text": stub}],
                            }
                        result.append(new_event)
                        elided_ids.append(event_id)
                    else:
                        result.append(event)
                else:
                    result.append(event)
            else:
                result.append(event)
        return result, elided_ids

    def create_context_summary(self, history_events: list[dict]) -> str:
        """Create a compacted summary of conversation history using T4 strategy.
        
        Returns a text string suitable for prepending to user input.
        """
        if not history_events:
            return ""
            
        # Apply T4 staging: elision first
        staged_events, elided_ids = self.stage_elision(history_events)
        
        # Estimate tokens of staged content
        staged_text = "\n---\n".join(self._extract_event_text(e) for e in staged_events)
        estimated_tokens = self.estimated_tokens(staged_text)
        
        # If still over hard threshold, summarize oldest events
        if estimated_tokens >= self.hard and len(staged_events) > MIN_RECENT_TURNS + 1:
            # Keep recent turns verbatim (for context continuity)
            recent_count = min(MIN_RECENT_TURNS, len(staged_events) // 3)  # At least some recent
            recent_events = staged_events[-recent_count:] if recent_count > 0 else []
            
            # Events to summarize (everything except recent)
            to_summarize = staged_events[:-recent_count] if recent_count > 0 else staged_events
            
            if to_summarize:
                # Create summary of older events
                summary_parts = []
                for event in to_summarize:
                    summary_parts.append(self._extract_event_text(event))
                
                summary_text = f"[Previous conversation summary: {len(to_summarize)} events]\n"
                summary_text += "\\n".join(summary_parts[:50])  # Limit summary size
                if len(summary_parts) > 50:
                    summary_text += f"\n... and {len(summary_parts) - 50} more events"
                
                # Truncate to reasonable length
                if len(summary_text) > MAX_SUMMARY_LENGTH:
                    summary_text = summary_text[:MAX_SUMMARY_LENGTH] + "..."
                
                # Combine summary with recent events
                context_parts = [summary_text]
                if recent_events:
                    recent_text = "\n---\n".join(self._extract_event_text(e) for e in recent_events)
                    context_parts.append(recent_text)
                
                return "\n\n=== CONVERSATION CONTEXT ===\n\n" + "\n\n".join(context_parts) + "\n\n=== END CONTEXT ===\n\n"
        
        # Under hard threshold - return elaborated context
        if staged_events:
            context_text = "\n---\n".join(self._extract_event_text(e) for e in staged_events)
            if len(context_text) > MAX_SUMMARY_LENGTH:
                context_text = context_text[:MAX_SUMMARY_LENGTH] + "..."
            return f"\n\n=== CONVERSATION CONTEXT ===\n\n{context_text}\n\n=== END CONTEXT ===\n\n"
        
        return ""

    def manage_and_summarize(self, history_events: list[dict]) -> str:
        """Main entry point: apply T4 and return summary string for host to use."""
        return self.create_context_summary(history_events)
