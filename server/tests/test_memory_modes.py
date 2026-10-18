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


# ----- EmbeddingGemma 2: local memory that ranks by meaning ------------------

from tura_code.memory.local_embedder import LocalEmbedder  # noqa: E402

gemma_ready = pytest.mark.skipif(not LocalEmbedder().ready(), reason="EmbeddingGemma 2 is not installed and downloaded (dhee models download gemma)")


def _run(coro):
    import asyncio

    return asyncio.new_event_loop().run_until_complete(coro)


@gemma_ready
def test_local_memory_finds_by_meaning_and_leaves_out_the_unrelated(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    gateway, ws = _gateway(tmp_path), tmp_path / "ws"
    for fact in ("The project runs its tests with `make test`.", "Deploys go out from the release branch every Thursday."):
        _run(gateway.remember(fact, ws))
    assert gateway.status()["embedder"] == "embeddinggemma-2"
    hits = _run(gateway.recall("when do we ship to production", ws))
    assert hits and "Thursday" in hits[0]["memory"], hits  # no word in common with the memory
    assert _run(gateway.recall("a recipe for banana bread", ws)) == []
    gateway._close_current()


@gemma_ready
def test_what_was_stored_before_the_model_arrived_moves_to_it(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    gateway, ws = _gateway(tmp_path), tmp_path / "ws"
    monkeypatch.setattr(LocalEmbedder, "ready", lambda self: False)
    monkeypatch.setattr(LocalEmbedder, "fetch", lambda self: None)
    _run(gateway.remember("Deploys go out from the release branch every Thursday.", ws))
    assert gateway.status()["embedder"] == "hash"

    monkeypatch.setattr(LocalEmbedder, "ready", lambda self: True)  # the download finished
    hits = _run(gateway.recall("when do we ship to production", ws))
    assert gateway.status()["embedder"] == "embeddinggemma-2"
    assert hits and "Thursday" in hits[0]["memory"], hits
    assert (tmp_path / "dhee" / ".gemma-reembedded").exists()
    gateway._close_current()


def test_offline_local_memory_never_downloads(monkeypatch):
    monkeypatch.setenv("TURA_CODE_OFFLINE", "1")
    local = LocalEmbedder()
    monkeypatch.setattr(LocalEmbedder, "ready", lambda self: False)
    local.fetch()
    assert local._thread is None
    if local.supported():
        assert local.state() == "unavailable: offline"
