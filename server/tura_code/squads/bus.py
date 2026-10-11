"""Engram Bus adapter for multi-agent coordination, handoff lanes, and file leases."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SquadBus:
    """Provides real-time coordination across agents and teams using Dhee's Engram Bus."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._bus = None
        self._init_bus()

    def _init_bus(self) -> None:
        try:
            from engram_bus.bus import Bus

            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._bus = Bus(db_path=str(self.db_path))
            logger.info("Engram Bus initialized at %s", self.db_path)
        except Exception as error:  # noqa: BLE001
            logger.warning("Could not initialize native engram-bus (%s), using fallback in-memory state", error)
            self._bus = None

    @property
    def ready(self) -> bool:
        return self._bus is not None

    # ── Handoff Lanes ──

    def open_lane(self, session_id: str, from_agent: str, to_agent: str, context: dict[str, Any] | None = None) -> str:
        with self._lock:
            if self._bus is not None:
                store = self._bus._ensure_store()
                with store._lock:
                    exists = store._conn.execute("SELECT id FROM handoff_sessions WHERE id = ?", (session_id,)).fetchone()
                    if not exists:
                        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                        store._conn.execute(
                            "INSERT INTO handoff_sessions (id, agent_id, repo, status, task_summary, decisions, files_touched, todos, metadata, created, updated) VALUES (?, ?, ?, 'active', ?, '[]', '[]', '[]', '{}', ?, ?)",
                            (session_id, from_agent, context.get("repo", "") if context else "", context.get("title", "") if context else "", now, now),
                        )
                        store._conn.commit()
                lane_id = self._bus.open_lane(session_id, from_agent, to_agent, context=context)
                self.signal("lane.opened", {"lane_id": lane_id, "from": from_agent, "to": to_agent}, agent=from_agent)
                return lane_id
            return f"lane-{int(time.time()*1000)}"

    def get_lane(self, lane_id: str) -> dict[str, Any] | None:
        with self._lock:
            if self._bus is not None:
                return self._bus.get_lane(lane_id)
            return None

    def list_lanes(self, session_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if self._bus is not None:
                return self._bus.list_lanes(session_id=session_id)
            return []

    def close_lane(self, lane_id: str) -> None:
        with self._lock:
            if self._bus is not None:
                self._bus.close_lane(lane_id)
                self.signal("lane.closed", {"lane_id": lane_id})

    # ── Checkpoints ──

    def checkpoint(self, session_id: str, agent_id: str, snapshot: dict[str, Any], lane_id: str | None = None) -> str:
        with self._lock:
            if self._bus is not None:
                cid = self._bus.checkpoint(session_id, agent_id, snapshot, lane_id=lane_id)
                self.signal("checkpoint.created", {"checkpoint_id": cid, "agent": agent_id, "lane_id": lane_id}, agent=agent_id)
                return cid
            return f"chk-{int(time.time()*1000)}"

    def list_checkpoints(self, session_id: str | None = None, lane_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if self._bus is not None:
                return self._bus.list_checkpoints(session_id=session_id, lane_id=lane_id)
            return []

    # ── Signals & PubSub ──

    def signal(self, topic: str, data: Any, agent: str | None = None) -> None:
        with self._lock:
            if self._bus is not None:
                self._bus.publish(topic, data, agent=agent)

    def recent_signals(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock:
            if self._bus is not None:
                return self._bus.signals(limit=limit)
            return []

    # ── Agent Registry ──

    def register_agent(self, agent_id: str, metadata: dict[str, Any] | None = None) -> None:
        with self._lock:
            if self._bus is not None:
                self._bus.register(agent_id, metadata=metadata)

    def list_agents(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._bus is not None:
                return self._bus.agents()
            return []

    # ── Active State & File Leases ──

    def acquire_file_lease(self, file_path: str, agent_id: str, ttl: int = 180) -> bool:
        """Optimistic concurrency lease for shared files."""
        with self._lock:
            if self._bus is None:
                return True
            key = f"lease:{file_path}"
            existing = self._bus.get(key, namespace="leases")
            if existing is not None and existing.get("agent_id") != agent_id:
                return False
            self._bus.put(key, {"agent_id": agent_id, "acquired_at": time.time()}, agent=agent_id, namespace="leases", ttl=ttl)
            self.signal("file.leased", {"path": file_path, "agent": agent_id, "ttl": ttl}, agent=agent_id)
            return True

    def release_file_lease(self, file_path: str, agent_id: str) -> None:
        with self._lock:
            if self._bus is not None:
                key = f"lease:{file_path}"
                existing = self._bus.get(key, namespace="leases")
                if existing is not None and existing.get("agent_id") == agent_id:
                    self._bus.delete(key, namespace="leases")
                    self.signal("file.released", {"path": file_path, "agent": agent_id}, agent=agent_id)

    def active_leases(self) -> dict[str, Any]:
        with self._lock:
            if self._bus is not None:
                return self._bus.all(namespace="leases")
            return {}
