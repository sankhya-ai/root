"""Lesson candidates waiting for (or past) the owner's decision.

One JSON file per tenant, bounded: decided candidates beyond the newest
:data:`KEEP_DECIDED` are dropped, and rejected fingerprints are kept apart so
a lesson the owner turned down is not proposed again.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

KEEP_DECIDED = 200


class CandidateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            data = {}
        data.setdefault("candidates", [])
        data.setdefault("rejected", [])
        return data

    def _save(self, data: dict[str, Any]) -> None:
        pending = [c for c in data["candidates"] if c["status"] == "candidate"]
        decided = [c for c in data["candidates"] if c["status"] != "candidate"][-KEEP_DECIDED:]
        data["candidates"] = pending + decided
        data["rejected"] = data["rejected"][-1000:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), "utf-8")
        tmp.replace(self.path)

    def add(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Store new candidates; skip any lesson already pending, promoted, or rejected."""
        with self._lock:
            data = self._load()
            known = {c["fingerprint"] for c in data["candidates"]} | set(data["rejected"])
            added = []
            for item in items:
                if item["fingerprint"] in known:
                    continue
                known.add(item["fingerprint"])
                record = {"id": uuid.uuid4().hex[:12], "status": "candidate", "created_at": time.time(), **item}
                data["candidates"].append(record)
                added.append(record)
            if added:
                self._save(data)
            return added

    def get(self, candidate_id: str) -> dict[str, Any] | None:
        return next((c for c in self._load()["candidates"] if c["id"] == candidate_id), None)

    def decide(self, candidate_id: str, status: str, result: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            record = next((c for c in data["candidates"] if c["id"] == candidate_id), None)
            if record is None:
                raise KeyError(candidate_id)
            if record["status"] != "candidate":
                raise ValueError(f"already {record['status']}")
            record.update(status=status, decided_at=time.time(), result=result or {})
            if status == "rejected":
                data["rejected"].append(record["fingerprint"])
            self._save(data)
            return record

    def list(self) -> list[dict[str, Any]]:
        return sorted(self._load()["candidates"], key=lambda c: (c["status"] != "candidate", -c["created_at"]))
