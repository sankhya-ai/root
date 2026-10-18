"""root on Windows: PowerShell for host commands, process trees, ConPTY, Windows paths.

The first test runs everywhere (it checks the portable layer the rest relies
on); the others run on Windows, where CI runs them against the real runtime.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import of_type, requires_runtime, run_turn, text, tool_call

from tura_code import hostos

windows = pytest.mark.skipif(not hostos.WINDOWS, reason="Windows only")

GRANDCHILD = "import time, sys\nwhile True:\n    open(sys.argv[1], 'a').write('x')\n    time.sleep(0.05)\n"
CHILD = "import subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]])\ntime.sleep(300)\n"


def test_stopping_a_command_stops_what_it_started(tmp_path):
    beat = tmp_path / "beat"
    process = subprocess.Popen([sys.executable, "-c", CHILD, GRANDCHILD, str(beat)], **hostos.spawn_options())
    deadline = time.monotonic() + 15
    while not (beat.exists() and beat.stat().st_size > 2) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert beat.exists(), "the grandchild never started"
    hostos.stop_tree(process.pid)
    process.wait(10)
    time.sleep(0.5)
    size = beat.stat().st_size
    time.sleep(0.5)
    assert beat.stat().st_size == size, "the grandchild outlived its tree"


@windows
def test_host_commands_run_in_powershell(tmp_path):
    async def run() -> str:
        process = await asyncio.create_subprocess_exec(
            *hostos.shell_argv("Write-Output ('ps-' + (40 + 2)); (Get-Location).Path"),
            cwd=str(tmp_path),
            stdout=asyncio.subprocess.PIPE,
            **hostos.spawn_options(),
        )
        out, _ = await process.communicate()
        return out.decode("utf-8", errors="replace")

    out = asyncio.run(run())
    assert "ps-42" in out and str(tmp_path).lower() in out.lower()
    assert hostos.venv_python(Path("v")).name == "python.exe" and hostos.executable("kimi-agent") == "kimi-agent.exe"


@windows
def test_paths_outside_the_workspace_are_seen_the_windows_way(tmp_path):
    from tura_code.trust.boundary import allowed, inside, outside_paths

    workspace = tmp_path / "project"
    (workspace / "src").mkdir(parents=True)
    other = tmp_path / "other"
    other.mkdir()
    ws = str(workspace)
    assert outside_paths(r"Get-Content .\src\a.py", ws) == []
    assert outside_paths("type src/a.py; ls", ws) == []
    assert outside_paths(f"Get-Content {other}\\secret.txt", ws) == [os.path.realpath(other / "secret.txt")]
    assert outside_paths(f'Get-Content "{str(other).replace(chr(92), "/")}/x"', ws)
    assert outside_paths(r"Get-ChildItem ..\..", ws)
    assert outside_paths(r"Set-Location ..; Get-ChildItem", ws)
    assert outside_paths(r"Get-Content $env:USERPROFILE\.ssh\id_rsa", ws)
    assert outside_paths(r"type %USERPROFILE%\.aws\credentials", ws)
    assert outside_paths(r"Get-ChildItem \\server\share\x", ws)
    assert inside(ws.upper(), ws) and inside(ws + r"\SRC\a.py", ws)  # paths compare without case
    assert allowed(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "where.exe"))
    assert outside_paths(r"Get-Content C:\Windows\System32\drivers\etc\hosts", ws) == []


@windows
def test_the_terminal_is_powershell_in_the_session_folder_without_roots_keys(client, workspace, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-must-not-leak")
    session_id = client.post("/api/sessions", json={"workspace": str(workspace)}).json()["id"]
    with client.websocket_connect(f"/api/sessions/{session_id}/terminal") as ws:
        ws.send_json({"type": "resize", "cols": 120, "rows": 40})
        ws.send_json({"type": "input", "data": "Write-Output \"at:$((Get-Location).Path)\"; Write-Output \"key:$($env:OPENROUTER_API_KEY)end\"; Write-Output ('done-' + (40+2))\r"})
        seen = b""
        for _ in range(600):
            seen += ws.receive_bytes()
            if b"done-42" in seen.replace(b"\x1b[", b""):
                break
        else:
            raise AssertionError(f"no prompt output; got {seen[-600:]!r}")
    plain = seen.decode("utf-8", errors="replace").lower()
    assert f"at:{workspace}".lower() in plain
    assert "key:end" in plain and "sk-or-must-not-leak" not in plain


@windows
@requires_runtime
def test_a_turn_runs_powershell_and_a_background_process_on_windows(client, workspace, script):
    script(
        [
            tool_call("sh", "Shell", {"command": "$root_n = 41; Write-Output ('hello-' + ($root_n + 1)); Write-Output \"pid:$PID\""}),
            tool_call("sh2", "Shell", {"command": "Write-Output ('again-' + ($root_n + 1)); Write-Output \"pid:$PID\"; Write-Output \"at:$((Get-Location).Path)\""}),
            tool_call("s", "process", {"action": "start", "command": "Write-Output ready; Start-Sleep -Seconds 60", "label": "sleeper"}),
            tool_call("t", "process", {"action": "wait", "process_id": "p1", "timeout": 2}),
            tool_call("k", "process", {"action": "kill", "process_id": "p1"}),
            text("Done."),
        ]
    )
    session_id = client.post("/api/sessions", json={"workspace": str(workspace)}).json()["id"]
    client.patch(f"/api/sessions/{session_id}", json={"permission_mode": "yolo"})
    with client.websocket_connect(f"/api/sessions/{session_id}/ws") as ws:
        ws.receive_json()
        events = run_turn(ws, "say hello and start a sleeper", timeout=120)
    assert of_type(events, "TurnFinished")[0]["payload"]["status"] == "finished"
    results = {e["payload"]["tool_call_id"]: e["payload"]["return_value"] for e in of_type(events, "ToolResult")}
    assert "hello-42" in results["sh"]["output"], results["sh"]
    # One PowerShell for the session: the variable carried over, the process is the same, and the call began in the workspace.
    assert "again-42" in results["sh2"]["output"], results["sh2"]
    pid = lambda output: output.split("pid:")[1].split()[0]
    assert pid(results["sh"]["output"]) == pid(results["sh2"]["output"])
    assert f"at:{workspace}".lower() in results["sh2"]["output"].lower()
    assert "id: p1" in results["s"]["output"] and "ready" in results["t"]["output"]
    assert "status: killed" in results["k"]["output"]
    listed = client.get(f"/api/sessions/{session_id}/processes").json()["processes"]
    assert listed[0]["status"] == "killed"
