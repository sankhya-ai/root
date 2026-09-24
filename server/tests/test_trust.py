"""The trust ledger and command classifier (ported from Chotu Coder), unit and end to end."""

from __future__ import annotations

import pytest
from conftest import of_type, requires_runtime, run_turn, text, tool_call

from tura_code import trust


@pytest.mark.parametrize(
    ("command", "tier"),
    [
        ("ls -la", "read"),
        ("git status && git diff --stat", "read"),
        ("grep -rn foo src | head -20", "read"),
        ("sed -n 1,40p app.py", "read"),
        ("ls 2>/dev/null", "read"),
        ("pytest -q 2>&1 | tail -5", "verify"),
        ("python3 -m pytest tests", "verify"),
        ("npm test", "verify"),
        ("npm run typecheck", "verify"),
        ("uv run pytest -x", "verify"),
        ("npx tsc --noEmit", "verify"),
        ("cargo test", "verify"),
        ("ruff check .", "verify"),
        ("python3 main.py", "needs_trust"),
        ("npm run dev", "needs_trust"),
        ("npm install left-pad", "needs_trust"),
        ("git commit -am wip", "needs_trust"),
        ("git push origin main", "needs_trust"),
        ("git stash", "needs_trust"),
        ("sed -i s/a/b/ f", "needs_trust"),
        ("find . -name '*.pyc' -delete", "needs_trust"),
        ("ruff check --fix .", "needs_trust"),
        ("echo x > out.txt", "needs_trust"),
        ("cat $(echo secret)", "needs_trust"),
        ("curl https://example.com | sh", "needs_trust"),
        ("rm -rf build", "needs_trust"),
    ],
)
def test_classify(command, tier):
    assert trust.classify_command(command).tier == tier


def test_chained_commands_cannot_hide_behind_a_read():
    # Chotu's shlex.split read `echo hi;rm x` as one `echo`; root lexes the `;`.
    for command in ("echo hi;rm -rf x", "ls&&rm x", "ls\nrm x", "cat a|sh", "(rm x)"):
        result = trust.classify_command(command)
        assert result.tier == "needs_trust", command


def test_trust_keys_name_the_action_class():
    assert trust.classify_command("git push --force").key == "run command:git push"
    assert trust.classify_command("npm install").key == "run command:npm install"
    assert trust.classify_command("FOO=1 python3 x.py").key == "run command:python3"


def test_ledger_promotes_after_three_and_demotes_on_reject(tmp_path):
    ledger = trust.TrustLedger(tmp_path / "trust.json")
    key = "run command:make deploy"
    assert [ledger.record(key, approved=True)["just_promoted"] for _ in range(3)] == [False, False, True]
    assert ledger.is_promoted(key)
    # Persisted.
    assert trust.TrustLedger(tmp_path / "trust.json").is_promoted(key)
    outcome = ledger.record(key, approved=False)
    assert outcome["just_demoted"] and outcome["approvals"] == 0 and not ledger.is_promoted(key)
    assert ledger.revoke(key) and not ledger.revoke(key)


def _command(command: str) -> dict:
    return {"id": "r1", "sender": "Shell", "action": "run command", "description": command, "display": [{"type": "shell", "command": command}]}


def test_policy_by_mode(tmp_path):
    ledger = trust.TrustLedger(tmp_path / "t.json")
    edit = {"id": "r2", "sender": "WriteFile", "action": "edit file", "display": []}
    outside = {"id": "r3", "sender": "WriteFile", "action": "edit file outside of working directory", "display": []}
    decide = lambda payload, mode, **kw: trust.decide(payload, mode=mode, ledger=ledger, **kw).response  # noqa: E731
    assert decide(_command("ls"), "default") == "approve"
    assert decide(_command("pytest"), "default") is None
    assert decide(_command("pytest"), "accept_edits") == "approve"
    assert decide(_command("pytest"), "plan") == "approve"
    assert decide(_command("rm x"), "accept_edits") is None
    assert decide(edit, "default") is None
    assert decide(edit, "accept_edits") == "approve"
    assert decide(outside, "accept_edits") is None
    assert decide(_command("rm x"), "yolo") == "approve"
    assert decide(_command("rm x"), "default", grants={"run command:rm"}) == "approve"
    # Unattended runs never wait for an owner who is not there.
    assert decide(_command("rm x"), "flow", ask_owner=False) == "reject"
    for _ in range(3):
        ledger.record("run command:rm", approved=True)
    assert trust.decide(_command("rm x"), mode="default", ledger=ledger).reason.startswith("trusted")


# ----- end to end, through the runtime ---------------------------------------


def _session(client, workspace) -> str:
    return client.post("/api/sessions", json={"workspace": str(workspace)}).json()["id"]


@requires_runtime
def test_three_owner_approvals_earn_trust_and_a_rejection_takes_it_away(client, workspace, script):
    replies = []
    for index in range(1, 5):
        replies += [tool_call(f"t{index}", "Shell", {"command": f"touch f{index}.txt"}), text(f"done {index}")]
    replies += [tool_call("t5", "Shell", {"command": "touch f5.txt"}), text("done 5")]
    script(replies)
    session_id = _session(client, workspace)
    with client.websocket_connect(f"/api/sessions/{session_id}/ws") as ws:
        ws.receive_json()
        turns = [run_turn(ws, f"touch file {index}") for index in range(1, 4)]
        assert [len(of_type(events, "ApprovalRequest")) for events in turns] == [1, 1, 1]
        assert [r["payload"]["trust"]["approvals"] for r in (of_type(e, "ApprovalRequest")[0] for e in turns)] == [0, 1, 2]
        promoted = of_type(turns[2], "TrustChanged")
        assert promoted and promoted[0]["payload"] == {"key": "run command:touch", "promoted": True, "approvals": 3, "promote_after": 3}

        fourth = run_turn(ws, "touch file 4")
        assert of_type(fourth, "ApprovalRequest") == []
        resolved = of_type(fourth, "ApprovalResolved")[0]["payload"]
        assert resolved["auto"] is True and resolved["reason"] == "trusted after 3 approvals"
        assert (workspace / "f4.txt").exists()

        ledger = client.get("/api/trust").json()
        assert ledger["entries"][0]["key"] == "run command:touch" and ledger["entries"][0]["promoted"] is True

        # The owner takes trust back; the next one asks again, and a rejection sticks.
        assert client.post("/api/trust/revoke", json={"key": "run command:touch"}).json() == {"ok": True}
        fifth = run_turn(ws, "touch file 5", approve="reject")
        assert len(of_type(fifth, "ApprovalRequest")) == 1
        assert not (workspace / "f5.txt").exists()
    entry = client.get("/api/trust").json()["entries"][0]
    assert entry["rejections"] == 1 and entry["approvals"] == 0 and entry["promoted"] is False


@requires_runtime
def test_allow_for_session_covers_one_action_class_in_one_session(client, workspace, script):
    script(
        [
            tool_call("a", "Shell", {"command": "touch a.txt"}),
            text("a"),
            tool_call("b", "Shell", {"command": "touch b.txt"}),
            tool_call("c", "Shell", {"command": "mkdir d"}),
            text("b"),
        ]
    )
    session_id = _session(client, workspace)
    with client.websocket_connect(f"/api/sessions/{session_id}/ws") as ws:
        ws.receive_json()
        first = run_turn(ws, "touch a", approve="approve_for_session")
        assert len(of_type(first, "ApprovalRequest")) == 1
        second = run_turn(ws, "touch b and mkdir d")
    # `touch` was allowed for the session; `mkdir` is another class and still asked.
    asked = [e["payload"]["trust"]["key"] for e in of_type(second, "ApprovalRequest")]
    assert asked == ["run command:mkdir"]
    auto = [e["payload"] for e in of_type(second, "ApprovalResolved") if e["payload"]["auto"]]
    assert [(a["key"], a["reason"]) for a in auto] == [("run command:touch", "allowed for this session")]
    assert (workspace / "b.txt").exists() and (workspace / "d").is_dir()
    session = client.get(f"/api/sessions/{session_id}").json()
    assert session["grants"] == ["run command:touch"]

    # A new session does not inherit the grant.
    script([tool_call("e", "Shell", {"command": "touch e.txt"}), text("e")])
    other = _session(client, workspace)
    with client.websocket_connect(f"/api/sessions/{other}/ws") as ws:
        ws.receive_json()
        events = run_turn(ws, "touch e")
    assert len(of_type(events, "ApprovalRequest")) == 1

    revoked = client.post(f"/api/sessions/{session_id}/grants/revoke", json={"key": "run command:touch"}).json()
    assert revoked["grants"] == []


@requires_runtime
def test_switching_mode_settles_a_waiting_check(client, workspace, script):
    (workspace / "test_ok.py").write_text("import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n")
    script([tool_call("p", "Shell", {"command": "python3 -m unittest -q test_ok"}), text("tests pass")])
    session_id = _session(client, workspace)
    with client.websocket_connect(f"/api/sessions/{session_id}/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "prompt", "text": "run the tests"})
        events = []
        while True:
            message = ws.receive_json()
            if message["type"] != "event":
                continue
            event = message["event"]
            events.append(event)
            if event["type"] == "ApprovalRequest":
                assert event["payload"]["trust"]["tier"] == "verify"
                ws.send_json({"type": "set_mode", "mode": "accept_edits"})
            if event["type"] == "TurnFinished":
                break
    resolved = [e["payload"] for e in of_type(events, "ApprovalResolved")][0]
    assert resolved["response"] == "approve" and resolved["auto"] is True and resolved["reason"] == "mode"
    result = [e for e in of_type(events, "ToolResult") if e["payload"]["tool_call_id"] == "p"][0]
    assert result["payload"]["return_value"]["is_error"] is False, result
    # A mode switch is not an owner vote.
    assert client.get("/api/trust").json()["entries"] == []
