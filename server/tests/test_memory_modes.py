"""Which Dhee memory root builds: real (OpenRouter, with decisions) once there is a key, local before."""

from __future__ import annotations

import pytest

from tura_code.memory.gateway import MemoryGateway
from tura_code.settings import Settings

pytest.importorskip("dhee")


def _gateway(tmp_path, **settings) -> MemoryGateway:
    return MemoryGateway(tmp_path, lambda: Settings(**settings))


def test_default_without_a_key_is_local_and_quiet(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    gateway = _gateway(tmp_path)
    assert gateway._settings().memory_mode == "openrouter"
    assert gateway._ensure() is not None
    assert gateway.status()["active_mode"] == "local" and gateway.status()["error"] == ""
    gateway._close_current()


def test_with_a_key_memory_is_real_and_decides_before_storing(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    gateway = _gateway(tmp_path, openrouter_api_key="sk-or-test")
    dhee = gateway._ensure()
    assert gateway.status()["active_mode"] == "openrouter", gateway.status()
    config = dhee._engram.memory.config
    assert config.decisions.enabled and config.decisions.provider == "openrouter"
    assert config.decisions.fact_subjects == [], "project memory is not filtered to facts about a person"
    gateway._close_current()


def test_a_non_openrouter_endpoint_gets_no_decisions(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    gateway = _gateway(tmp_path, openrouter_api_key="k", base_url="https://llm.internal/v1")
    dhee = gateway._ensure()
    assert gateway.status()["active_mode"] == "openrouter"
    assert not dhee._engram.memory.config.decisions.enabled
    gateway._close_current()
