"""The self-extension arcs as coherent user scenarios through the real app (scripted echo model, no provider, no cost).

Each scenario walks one loop end to end instead of asserting pieces in isolation:
A. discovery miss -> compose a tool -> use it in the same turn
B. generated-code proposal -> owner review -> refusal on a host without proven cgroup limits (or activation on one with them)
C. changed code after review -> activation refused
D. role adoption -> same-turn narrowing -> revocation keeps the narrowed snapshot
E. new-session isolation -> explicit owner promotion -> then usable
"""

from __future__ import annotations

import json

from conftest import of_type, requires_runtime, run_turn, text, tool_call

from tura_code import genplugins

MATH_SOURCE = (
    "import statistics\n\n\n"
    "def stats_summary(numbers):\n"
    "    values = [float(n) for n in numbers]\n"
    "    if not values:\n"
    "        raise ValueError('no numbers')\n"
    "    return {'mean': statistics.fmean(values)}\n"
)
MANIFEST = [{
    "name": "stats_summary",
    "description": "Mean of a list of numbers.",
    "parameters": {"type": "object", "properties": {"numbers": {"type": "array", "items": {"type": "number"}}},
                   "required": ["numbers"], "additionalProperties": False},
}]
MATH_TESTS = "from plugin import stats_summary\n\n\ndef test_mean():\n    assert stats_summary([2.0, 4.0])['mean'] == 3.0\n"


def _turn_results(client, workspace, script, session_id, prompt):
    with client.websocket_connect(f"/api/sessions/{session_id}/ws") as ws:
        ws.receive_json()
        events = run_turn(ws, prompt)
    return events, {e["payload"]["tool_call_id"]: e["payload"]["return_value"] for e in of_type(events, "ToolResult")}


@requires_runtime
def test_scenario_a_miss_compose_use_same_turn(client, workspace, script):
    """The loop Ashish asked for, composed-tools branch: the search misses (signal recorded, hint given), the agent
    composes a tool from existing ones, and uses it in the SAME turn through the gateway."""
    client.put("/api/settings", json={"dynamic_tools": True})
    script([
        tool_call("m", "find_tools", {"query": "zzzqqq xylophone tuning"}),
        tool_call("c", "create_tool", {
            "name": "process_digest",
            "description": "List background processes.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            "steps": [{"tool": "process", "arguments": {"action": "list"}}],
        }),
        tool_call("u", "use_tool", {"name": "process_digest", "arguments": {}}),
        text("done"),
    ])
    session_id = client.post("/api/sessions", json={"workspace": str(workspace)}).json()["id"]
    events, results = _turn_results(client, workspace, script, session_id, "find or make a process digest")
    assert "create_tool" in results["m"]["output"] and "propose_tool" in results["m"]["output"]  # the miss teaches the extension paths
    assert results["c"]["is_error"] is False
    assert results["u"]["is_error"] is False and "step 0" in results["u"]["output"]
    record = client.get(f"/api/sessions/{session_id}").json()
    assert record["capability_misses"] and record["capability_misses"][0]["query"] == "zzzqqq xylophone tuning"


@requires_runtime
def test_scenario_b_generated_code_respects_the_host_gate(client, workspace, script):
    """Generated branch, honest per host: where aggregate cgroup limits cannot be PROVEN (this environment),
    propose refuses before anything is stored and there is nothing to review; where they can, the candidate is
    verified-inert and the owner activates the reviewed hash. Both branches assert real behavior; the skip-labeled
    bounded-execution suite covers the supported-host path when such a host runs it."""
    prefix, reason = genplugins.execution_policy()
    script([tool_call("p", "propose_tool", {"name": "numstats", "tools": MANIFEST, "source": MATH_SOURCE, "tests": MATH_TESTS}), text("done")])
    session_id = client.post("/api/sessions", json={"workspace": str(workspace)}).json()["id"]
    _, results = _turn_results(client, workspace, script, session_id, "build the stats tool")
    if reason:
        assert results["p"]["is_error"] is True and "proven aggregate resource limits" in results["p"]["message"] + results["p"]["output"]
        assert client.get("/api/registry/plugins").json() == {}
        assert client.get("/api/registry/plugins/numstats/review").status_code == 404
    else:  # a host with proven limits: the full owner-gated arc
        assert results["p"]["is_error"] is False
        review = client.get("/api/registry/plugins/numstats/review").json()
        assert review["status"] == "verified" and review["hash_matches_record"] is True
        ok = client.post("/api/registry/plugins/numstats/activate", json={"version": 1, "sha256": review["sha256"]})
        assert ok.status_code == 200


@requires_runtime
def test_scenario_c_changed_code_cannot_be_activated(client, workspace, script, home, monkeypatch):
    """The owner reviews v1, the bytes change afterwards, and the reviewed hash no longer activates - at the
    review surface (mismatch reported) and at the activation gate (409). Verification stubbed; hash gates real."""
    monkeypatch.setattr(genplugins, "execution_policy", lambda: (["true"], ""))

    async def fake_jailed(store, name, version, payload, *, timeout, expected_sha256=None):
        return {"ok": True, "results": [{"name": "test_mean", "ok": True}], "isolation": "verification stubbed in this test"}

    monkeypatch.setattr(genplugins, "run_jailed", fake_jailed)
    script([tool_call("p", "propose_tool", {"name": "numstats", "tools": MANIFEST, "source": MATH_SOURCE, "tests": MATH_TESTS}), text("done")])
    session_id = client.post("/api/sessions", json={"workspace": str(workspace)}).json()["id"]
    _, results = _turn_results(client, workspace, script, session_id, "build the stats tool")
    assert json.loads(results["p"]["output"])["status"] == "verified"
    reviewed = client.get("/api/registry/plugins/numstats/review").json()
    (home / "registry" / "plugins" / "numstats" / "1" / "plugin.py").write_text(MATH_SOURCE + "\n# changed after review\n", "utf-8")
    stale = client.get("/api/registry/plugins/numstats/review").json()
    assert stale["hash_matches_record"] is False and stale["on_disk_sha256"] != reviewed["sha256"]
    refused = client.post("/api/registry/plugins/numstats/activate", json={"version": 1, "sha256": reviewed["sha256"]})
    assert refused.status_code == 409 and "no longer match" in refused.text


@requires_runtime
def test_scenario_d_adopt_narrow_revoke(client, workspace, script):
    """Role branch: adopt a durable role (narrowed, pinned, owner-notified), a native command is rejected in the
    SAME turn, and revoking the role afterwards leaves the narrowed snapshot in place."""
    client.put("/api/settings", json={"dynamic_tools": True})
    first = client.post("/api/sessions", json={"workspace": str(workspace)}).json()["id"]
    script([tool_call("r", "create_role", {"name": "reader", "description": "Read-only helper.", "tools": ["find_tools", "use_tool", "ReadFile"]}), text("done")])
    _turn_results(client, workspace, script, first, "make a role")
    assert client.post("/api/registry/roles/reader/promote").status_code == 200

    session_id = client.post("/api/sessions", json={"workspace": str(workspace)}).json()["id"]
    script([
        tool_call("a", "adopt_role", {"name": "reader"}),
        tool_call("s", "Shell", {"command": "echo should-not-run"}),
        text("done"),
    ])
    events, results = _turn_results(client, workspace, script, session_id, "adopt the reader role")
    assert results["a"]["is_error"] is False
    rejections = [e["payload"] for e in of_type(events, "ApprovalResolved") if e["payload"].get("response") == "reject" and e["payload"].get("sender") == "Shell"]
    assert rejections and "outside this session's tool scope" in rejections[0]["reason"]
    assert client.post("/api/registry/roles/reader/revoke").status_code == 200
    record = client.get(f"/api/sessions/{session_id}").json()
    assert record["role"] == "reader" and record["role_version"] == 1  # still pinned
    assert sorted(record["tool_scope"]) == ["ReadFile", "find_tools", "use_tool"]  # the narrowed snapshot stays

    script([tool_call("g", "use_tool", {"name": "process", "arguments": {"action": "list"}}), text("done")])
    _, results = _turn_results(client, workspace, script, session_id, "list processes")
    assert results["g"]["is_error"] is True  # revocation did not widen the session back


@requires_runtime
def test_scenario_e_session_isolation_then_explicit_promotion(client, workspace, script):
    """A tool one session creates is invisible to a fresh session until the owner promotes it - isolation by
    default, durability only by the owner's separate act."""
    client.put("/api/settings", json={"dynamic_tools": True})
    first = client.post("/api/sessions", json={"workspace": str(workspace)}).json()["id"]
    script([
        tool_call("c", "create_tool", {
            "name": "process_digest",
            "description": "List background processes.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            "steps": [{"tool": "process", "arguments": {"action": "list"}}],
        }),
        text("done"),
    ])
    _, results = _turn_results(client, workspace, script, first, "make a digest tool")
    assert results["c"]["is_error"] is False

    second = client.post("/api/sessions", json={"workspace": str(workspace)}).json()["id"]
    script([tool_call("u", "use_tool", {"name": "process_digest", "arguments": {}}), text("done")])
    _, results = _turn_results(client, workspace, script, second, "run the digest")
    assert results["u"]["is_error"] is True and "not an available tool" in results["u"]["message"]

    assert client.post("/api/registry/tools/process_digest/promote").status_code == 200
    script([tool_call("u2", "use_tool", {"name": "process_digest", "arguments": {}}), text("done")])
    _, results = _turn_results(client, workspace, script, second, "run the digest again")
    assert results["u2"]["is_error"] is False and "step 0" in results["u2"]["output"]
