from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from tura_code import launcher
from tura_code.memory import MemoryGateway, packet_envelope, project_scope, split_envelope
from tura_code.sessions import SessionManager, build_parts, expand_mentions
from tura_code.settings import Settings, SettingsStore


def _spec(tmp_path: Path, **kw) -> launcher.LaunchSpec:
    defaults = dict(
        session_id="abc",
        workspace=tmp_path,
        settings=Settings(openrouter_api_key="sk-or-test"),
        permission_mode="default",
        memory_enabled=True,
    )
    defaults.update(kw)
    return launcher.LaunchSpec(**defaults)


def test_config_uses_the_openrouter_protocol_and_keeps_the_key_out_of_env(tmp_path, monkeypatch):
    monkeypatch.delenv(launcher.SCRIPTED_ECHO_ENV, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env")
    monkeypatch.setenv("SOME_OTHER_API_KEY", "secret")
    spec = _spec(tmp_path)
    path = launcher.write_runtime_config(spec.settings, tmp_path / "rt", ["image_in"])
    config = json.loads(path.read_text())
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    provider = config["providers"]["openrouter"]
    assert provider["api_key"] == "sk-or-env"  # the environment wins
    assert config["models"]["main"]["provider"] == "openrouter"
    assert config["models"]["main"]["capabilities"] == ["image_in"]
    assert config["services"]["openrouter_search"]["model"]
    env = launcher.child_environment(spec, tmp_path / "share")
    assert not any(k.endswith("_API_KEY") for k in env)
    assert "OPENROUTER_API_KEY" not in env
    assert env["CHOTU_DIRECTOR"] == "on"
    assert env["KIMI_SHARE_DIR"] == str(tmp_path / "share")


def test_director_off_switches_decisions_off(tmp_path):
    spec = _spec(tmp_path, settings=Settings(director_mode="off"))
    env = launcher.child_environment(spec, tmp_path / "share")
    assert env["CHOTU_DIRECTOR"] == "off" and env["CHOTU_DECISIONS_ENABLED"] == "0"


def test_overlay_for_plan_mode_with_memory(tmp_path):
    spec = _spec(tmp_path, permission_mode="plan")
    overlay = launcher.write_agent_overlay(spec, tmp_path / "rt").read_text()
    assert f'extend: "{launcher.base_agent_file()}"' in overlay
    assert "context_continuity_tool: memory_checkpoint" in overlay
    assert "PLAN MODE" in overlay and "memory_recall" in overlay
    assert '"kimi_cli.tools.file:WriteFile"' in overlay
    assert '"kimi_cli.tools.file:StrReplaceFile"' in overlay


def test_overlay_without_memory_or_plan_is_bare(tmp_path):
    spec = _spec(tmp_path, memory_enabled=False)
    overlay = launcher.write_agent_overlay(spec, tmp_path / "rt").read_text()
    assert "context_continuity_tool" not in overlay
    assert "exclude_tools" not in overlay
    assert "ROLE_ADDITIONAL" not in overlay


def test_fingerprint_changes_with_what_shapes_the_process(tmp_path):
    base = _spec(tmp_path).fingerprint()
    assert _spec(tmp_path, permission_mode="accept_edits").fingerprint() == base
    assert _spec(tmp_path, permission_mode="plan").fingerprint() != base
    assert _spec(tmp_path, settings=Settings(openrouter_api_key="sk-or-test", model="x/y")).fingerprint() != base


def test_settings_never_expose_the_key_and_blank_means_unchanged(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    store = SettingsStore(tmp_path)
    store.update({"openrouter_api_key": "sk-or-v1-abcdefgh"})
    store.update({"openrouter_api_key": "", "model": "a/b"})
    settings = store.get()
    assert settings.openrouter_api_key == "sk-or-v1-abcdefgh" and settings.model == "a/b"
    public = settings.public()
    assert public["openrouter_api_key"] == "" and public["api_key_set"] and public["api_key_hint"] == "…efgh"
    assert oct((tmp_path / "settings.json").stat().st_mode & 0o777) == "0o600"
    store.update({"clear_api_key": True})
    assert store.get().openrouter_api_key == ""


def test_envelope_round_trip(tmp_path):
    wrapped = packet_envelope("Project memory:\n- uses pytest", "fix the bug", tmp_path)
    context, request = split_envelope(wrapped)
    assert request == "fix the bug"
    assert "uses pytest" in context
    assert split_envelope("plain") == ("", "plain")


def test_mentions_attach_workspace_files_only(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n")
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("nope")
    text = expand_mentions("look at @src/app.py and @../secret.txt and email a@b.com", tmp_path)
    assert "print('hi')" in text
    assert "nope" not in text
    assert text.count("<system>Contents of") == 1


def test_build_parts_puts_images_after_text():
    import base64

    parts = build_parts(
        "see",
        [
            {"name": "a.png", "mime": "image/png", "data": base64.b64encode(b"png").decode()},
            {"name": "notes.txt", "mime": "text/plain", "data": base64.b64encode(b"hello").decode()},
        ],
    )
    assert parts[0]["type"] == "text" and "hello" in parts[0]["text"]
    assert parts[1]["type"] == "image_url" and parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_event_log_coalesces_stream_deltas(tmp_path):
    store = SettingsStore(tmp_path)
    manager = SessionManager(tmp_path, store, MemoryGateway(tmp_path, store.get))
    ws = tmp_path / "ws"
    ws.mkdir()
    runtime = manager.create(str(ws))
    for chunk in ("Hel", "lo", "!"):
        runtime.emit("ContentPart", {"type": "text", "text": chunk})
    runtime.emit("ToolCall", {"type": "function", "id": "c1", "function": {"name": "Shell", "arguments": '{"comm'}})
    runtime.emit("ToolCallPart", {"arguments_part": 'and":"ls"}'})
    runtime.emit("ToolResult", {"tool_call_id": "c1", "return_value": {"is_error": False}})
    runtime.emit("ContentPart", {"type": "text", "text": "Done"})
    history = runtime.history()
    assert [e["type"] for e in history] == ["ContentPart", "ToolCall", "ToolResult", "ContentPart"]
    assert history[0]["payload"]["text"] == "Hello!"
    assert history[1]["payload"]["function"]["arguments"] == '{"command":"ls"}'
    runtime._flush_buffer()
    lines = (runtime.dir / "events.jsonl").read_text().splitlines()
    assert len(lines) == 4


@pytest.mark.asyncio
async def test_memory_gateway_local_mode(tmp_path):
    settings = Settings(memory_mode="local")
    gateway = MemoryGateway(tmp_path, lambda: settings)
    ws = tmp_path / "project"
    ws.mkdir()
    try:
        stored = await gateway.handle_tool(
            "memory_remember",
            {"content": "Database migrations live in db/migrations and run with alembic.", "kind": "convention"},
            workspace=ws,
            session_id="s",
        )
        assert stored["is_error"] is False, stored
        await gateway.handle_tool(
            "memory_remember",
            {"content": "Owner prefers tabs over spaces in Go code.", "scope": "owner"},
            workspace=ws,
            session_id="s",
        )
        recalled = await gateway.handle_tool("memory_recall", {"query": "where are database migrations"}, workspace=ws, session_id="s")
        assert "alembic" in recalled["output"]
        assert "tabs" not in recalled["output"]  # no shared words, not relevant

        packet = await gateway.compile_packet("add a database migrations step", ws, seen=set(), first_turn=True)
        assert packet is not None and "alembic" in packet.text
        again = await gateway.compile_packet("add a database migrations step", ws, seen={i["id"] for i in packet.items}, first_turn=False)
        assert again is None  # nothing new to show

        other = tmp_path / "other"
        other.mkdir()
        elsewhere = await gateway.recall("database migrations", other)
        assert elsewhere == []  # project memory stays in its project

        checkpoint = await gateway.handle_tool(
            "memory_checkpoint",
            {"summary": "Wired migrations into CI", "what_worked": "running alembic upgrade head in CI"},
            workspace=ws,
            session_id="s",
        )
        assert checkpoint["is_error"] is False and checkpoint["output"].startswith("Checkpoint saved.")
        assert project_scope(ws) != project_scope(other)
    finally:
        await gateway.close()


@pytest.mark.asyncio
async def test_memory_off_is_a_tool_error_not_a_crash(tmp_path):
    settings = Settings(memory_mode="off")
    gateway = MemoryGateway(tmp_path, lambda: settings)
    try:
        result = await gateway.handle_tool("memory_recall", {"query": "x"}, workspace=tmp_path, session_id="s")
        assert result["is_error"] is True and "unavailable" in result["message"].lower()
        assert await gateway.compile_packet("x", tmp_path, seen=set(), first_turn=True) is None
    finally:
        await gateway.close()


def test_security_guards(home, workspace):
    from fastapi.testclient import TestClient

    from tura_code.app import create_app

    with TestClient(create_app(home)) as client:
        assert client.get("/api/sessions").status_code == 401
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/health", headers={"host": "evil.example:8787"}).status_code == 403
        client.post("/api/auth/bootstrap")
        assert client.get("/api/sessions").status_code == 200
        token = (home / "token").read_text().strip()
        bare = TestClient(client.app)
        assert bare.get("/api/sessions", headers={"authorization": f"Bearer {token}"}).status_code == 200
        created = client.post("/api/sessions", json={"workspace": str(workspace)}).json()
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                f"/api/sessions/{created['id']}/ws", headers={"origin": "https://evil.example"}
            ) as ws:
                ws.receive_json()
        assert client.post("/api/sessions", json={"workspace": str(workspace / "missing")}).status_code == 400


def test_user_mcp_config_is_passed_and_restarts_on_change(tmp_path):
    assert launcher.user_mcp_config(tmp_path) is None
    (tmp_path / "mcp.json").write_text('{"mcpServers": {}}')
    config = launcher.user_mcp_config(tmp_path)
    spec = _spec(tmp_path, mcp_config=config)
    argv = launcher.runtime_argv(Path("/bin/kimi-agent"), spec, tmp_path / "c.json", tmp_path / "a.yaml")
    assert argv[-2:] == ["--mcp-config-file", str(tmp_path / "mcp.json")]
    before = spec.fingerprint()
    import os as _os

    _os.utime(config, (1, 1))
    assert spec.fingerprint() != before
