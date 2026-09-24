"""Persistent host settings and the data-directory layout.

Everything root writes lives under one directory (``TURA_CODE_HOME``,
default ``~/.tura-code``):

    settings.json        this module (0600: it may hold the OpenRouter key)
    sessions/<id>/       session.json + events.jsonl, see ``sessions``
    runtime/             per-session agent overlays and runtime config files
    kimi/                the runtime's own share dir (context, wire logs)
    dhee/                Dhee's memory store
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_KEY_ENV = "OPENROUTER_API_KEY"

PermissionMode = Literal["default", "accept_edits", "plan", "yolo"]
DirectorMode = Literal["on", "shadow", "off"]
MemoryMode = Literal["local", "openrouter", "off"]
ReasoningEffort = Literal["", "none", "low", "medium", "high", "xhigh"]


def data_dir() -> Path:
    raw = os.environ.get("TURA_CODE_HOME", "").strip()
    path = Path(raw).expanduser() if raw else Path.home() / ".tura-code"
    path.mkdir(parents=True, exist_ok=True)
    return path


class Settings(BaseModel):
    """What the owner chooses in the settings panel."""

    openrouter_api_key: str = ""
    base_url: str = OPENROUTER_BASE_URL
    model: str = "qwen/qwen3-coder"
    max_context_size: int = Field(default=200_000, ge=8_000, le=4_000_000)
    reasoning_effort: ReasoningEffort = ""
    max_steps_per_turn: int = Field(default=100, ge=1, le=1_000)
    # Jev (`typesafe/jev-1.13`) decides, before each step, whether the model
    # should reply or which tool it should call. See runtime/.../director.rs.
    director_mode: DirectorMode = "on"
    memory_mode: MemoryMode = "local"
    memory_llm_model: str = "openai/gpt-4o-mini"
    memory_embedding_model: str = "openai/text-embedding-3-small"
    memory_embedding_dims: int = Field(default=1536, ge=64, le=8192)
    web_search: bool = True
    search_model: str = "openai/gpt-4o-mini"
    default_permission_mode: PermissionMode = "default"
    recent_workspaces: list[str] = Field(default_factory=list)

    @field_validator("base_url")
    @classmethod
    def _strip_slash(cls, value: str) -> str:
        return value.strip().rstrip("/") or OPENROUTER_BASE_URL

    def api_key(self) -> str:
        """The key in effect: the environment wins over the stored one."""
        return os.environ.get(OPENROUTER_KEY_ENV, "").strip() or self.openrouter_api_key.strip()

    def key_source(self) -> str:
        if os.environ.get(OPENROUTER_KEY_ENV, "").strip():
            return "environment"
        if self.openrouter_api_key.strip():
            return "settings"
        return "missing"

    def public(self) -> dict:
        """Settings as the UI may see them: never the key itself."""
        data = self.model_dump()
        key = self.api_key()
        data["openrouter_api_key"] = ""
        data["api_key_set"] = bool(key)
        data["api_key_hint"] = f"…{key[-4:]}" if len(key) >= 8 else ""
        data["api_key_source"] = self.key_source()
        return data


class SettingsStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or data_dir()
        self.path = self.root / "settings.json"
        self._lock = threading.Lock()
        self._settings = self._load()

    def _load(self) -> Settings:
        if not self.path.exists():
            return Settings()
        try:
            return Settings.model_validate(json.loads(self.path.read_text("utf-8")))
        except (OSError, ValueError):
            return Settings()

    def get(self) -> Settings:
        with self._lock:
            return self._settings.model_copy(deep=True)

    def update(self, changes: dict) -> Settings:
        with self._lock:
            data = self._settings.model_dump()
            for key, value in changes.items():
                if key not in data:
                    continue
                # An empty key field in the form means "unchanged", not "erase";
                # erasing is an explicit `clear_api_key`.
                if key == "openrouter_api_key" and not str(value or "").strip():
                    continue
                data[key] = value
            if changes.get("clear_api_key"):
                data["openrouter_api_key"] = ""
            self._settings = Settings.model_validate(data)
            self._write()
            return self._settings.model_copy(deep=True)

    def remember_workspace(self, workspace: str) -> None:
        with self._lock:
            recent = [w for w in self._settings.recent_workspaces if w != workspace]
            self._settings.recent_workspaces = [workspace, *recent][:12]
            self._write()

    def _write(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(self._settings.model_dump_json(indent=2))
        os.replace(tmp, self.path)
