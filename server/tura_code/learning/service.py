"""The learning loop for one person: review after a turn, then promote or reject.

    turn finishes ─▶ worth a review? ─▶ reviewer (host model call) ─▶ candidates
        candidates ─▶ owner reviews (mode `review`) ─▶ promote ─▶ SKILL.md / Dhee
                   └▶ promoted at once (mode `auto`)          └▶ reject: never proposed again

A promoted skill reaches the agent on its next launch (see ``skills``); a
promoted memory is in Dhee and comes back in memory packets. In `auto` mode a
memory is only saved from a turn that went cleanly, as Chotu did: a failed
turn's "facts" are too often wrong. Nothing at all is promoted on its own from
a turn whose edits were never exercised by a check — "fixed it" without a run
is a claim, not a lesson — so those candidates wait for the owner.

A skill loads into every later session, so `auto` keeps one only once the same
lesson has come from two sessions: seen once it is an anecdote about one task
(often the task's own fix, dressed as a procedure); seen twice it is a pattern.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import llm
from . import review
from .skills import SkillLibrary
from .store import CandidateStore

if TYPE_CHECKING:
    from ..sessions import SessionRuntime, TurnState
    from ..tenancy import Tenant

logger = logging.getLogger(__name__)


class LearningService:
    def __init__(self, tenant: "Tenant") -> None:
        self.tenant = tenant
        self.skills = SkillLibrary(tenant.skills_dir)
        self.store = CandidateStore(tenant.root / "learning.json")

    def mode(self) -> str:
        return self.tenant.settings.get().learning_mode

    async def after_turn(self, runtime: "SessionRuntime", turn: "TurnState", status: str) -> None:
        if self.mode() == "off" or runtime.record.kind != "session" or launcher_scripted_without_llm():
            return
        if not review.should_review(
            prompt=turn.prompt,
            status=status,
            files_touched=len(turn.files_touched),
            tool_count=turn.tool_count,
            errors=turn.errors,
            rejections=turn.rejections,
        ):
            return
        summary = {
            "prompt": turn.prompt,
            "reply": turn.reply(),
            "status": status,
            "files_touched": turn.files_touched,
            "trace": turn.trace(),
            "errors": turn.errors,
            "rejections": turn.rejections,
            "verified": turn.verified,
            "checks": turn.checks,
        }
        settings = self.tenant.settings.get()
        try:
            answer = await llm.complete(
                review.build_messages(summary, self.skills.list()),
                base_url=settings.base_url,
                api_key=self.tenant.api_key(),
                model=settings.learning_model or settings.model,
                purpose="review",
                max_tokens=2_500,
                json_mode=True,
            )
            verdict = review.parse(answer)
        except (llm.LLMError, ValueError) as error:
            logger.info("learning review skipped: %s", error)
            runtime.emit("LearningReviewed", {"ok": False, "error": str(error)[:300], "candidates": []})
            return
        clean = status == "finished" and turn.errors == 0 and turn.rejections == 0 and turn.verified
        items = [self._candidate("skill", s, runtime, verdict) for s in verdict["skills"]]
        items += [self._candidate("memory", m, runtime, verdict) for m in verdict["memories"]]
        added, again = self.store.add(items)
        promoted = []
        if self.mode() == "auto" and turn.verified:
            for record in added + again:
                if record["kind"] == "memory" and not clean:
                    continue
                if record["kind"] == "skill" and len(set(record.get("sessions") or [])) < 2:
                    continue
                promoted.append(await self.promote(record["id"]))
        runtime.emit(
            "LearningReviewed",
            {
                "ok": True,
                "summary": verdict["summary"],
                "mode": self.mode(),
                "candidates": [{"id": r["id"], "kind": r["kind"], "title": r["title"]} for r in added],
                "promoted": [p["id"] for p in promoted],
                "rejected_overfit": len(verdict["rejected_overfit"]),
                "verified": turn.verified,
            },
        )

    def _candidate(self, kind: str, body: dict[str, Any], runtime: "SessionRuntime", verdict: dict[str, Any]) -> dict[str, Any]:
        title = body["name"] if kind == "skill" else body["content"][:120]
        return {
            "kind": kind,
            "title": title,
            "body": body,
            "fingerprint": review.fingerprint(kind, body),
            "session_id": runtime.record.id,
            "workspace": runtime.record.workspace,
            "review_summary": verdict["summary"],
            "updates_existing": kind == "skill" and any(s["name"] == body["name"] for s in self.skills.list()),
        }

    async def promote(self, candidate_id: str) -> dict[str, Any]:
        record = self.store.get(candidate_id)
        if record is None:
            raise KeyError(candidate_id)
        if record["status"] != "candidate":
            raise ValueError(f"already {record['status']}")
        body = record["body"]
        if record["kind"] == "skill":
            result = self.skills.write(body, source=f"session {record['session_id'][:12]}, reviewed {record['review_summary'][:120]}")
        else:
            stored = await self.tenant.memory.remember(
                body["content"], Path(record["workspace"]), scope=body["scope"], kind=body["kind"], session_id=record["session_id"]
            )
            result = {"memory_id": stored.get("id", "") if isinstance(stored, dict) else "", "scope": body["scope"]}
        return self.store.decide(candidate_id, "promoted", result)

    def reject(self, candidate_id: str) -> dict[str, Any]:
        return self.store.decide(candidate_id, "rejected")


def launcher_scripted_without_llm() -> bool:
    """Scripted turns with no scripted reviewer: nothing to review with."""
    import os

    from .. import launcher

    return launcher.scripted() and not os.environ.get(llm.SCRIPTED_LLM_ENV)
