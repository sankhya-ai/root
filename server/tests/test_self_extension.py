"""The self-extension arcs as coherent user scenarios through the real app (scripted echo model, no provider, no cost).

Each scenario walks one loop end to end instead of asserting pieces in isolation:
A. discovery miss -> compose a tool -> use it in the same turn
B. generated-code proposal -> owner review -> refusal on a host without proven cgroup limits (or activation on one with them)
C. changed code after review -> activation refused
D. role adoption -> same-turn narrowing -> revocation keeps the narrowed snapshot
E. new-session isolation -> explicit owner promotion -> then usable
F. a session PROPOSES a job -> nothing starts -> the owner's accept runs exactly the stored fields (or dismiss ends it)
"""

from __future__ import annotations

import json

import time
from types import SimpleNamespace

import pytest

from conftest import of_type, requires_runtime, run_turn, text, tool_call

from tura_code import genplugins, jobs

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


# ----- Scenario F: a session proposes a job; the owner's decision is the only start path ---------------------------


def _wait_job(client, job_id, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        item = client.get(f"/api/jobs/{job_id}").json()
        if item["status"] != "running":
            return item
        time.sleep(0.2)
    raise AssertionError("job did not finish")


@requires_runtime
def test_scenario_f_session_proposes_owner_decides(client, workspace, script):
    """The loop Ashish asked for, delegation branch: the session recommends a job, NOTHING starts, the owner sees the
    pending request in the transcript and on the API, and their accept runs exactly the stored fields."""
    script([
        tool_call("j", "recommend_job", {"goal": "summarise the repo", "role": "explorer", "reason": "read-only sweep while you sleep"}),
        text("proposed"),
    ])
    session_id = client.post("/api/sessions", json={"workspace": str(workspace)}).json()["id"]
    events, results = _turn_results(client, workspace, script, session_id, "get the repo summarised")
    assert results["j"]["is_error"] is False, results["j"]
    payload = json.loads(results["j"]["output"])
    assert payload["status"] == "pending" and payload["requested_by"] == session_id
    assert "Nothing started" in payload["what_happens_now"]
    # The owner SEES the recommendation in the session transcript, with its goal and role.
    notice = [e for e in events if e["type"] == "JobRecommended"]
    assert notice and notice[0]["payload"]["goal"] == "summarise the repo" and notice[0]["payload"]["role"] == "explorer"
    # Pending for the owner; no job exists yet.
    requests = client.get("/api/job-requests").json()["requests"]
    assert [r["id"] for r in requests] == [payload["id"]] and requests[0]["status"] == "pending"
    # The accept runs EXACTLY the stored fields (the endpoint takes no body that could change them).
    script([text("Looked. All read-only.")])
    accepted = client.post(f"/api/job-requests/{payload['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    job = accepted.json()["job"]
    assert job["goal"] == "summarise the repo" and job["role"] == "explorer"
    item = _wait_job(client, job["id"])
    assert item["status"] != "running"
    assert accepted.json()["request"]["status"] == "accepted" and accepted.json()["request"]["job_id"] == job["id"]
    # A resolved request never resolves again.
    assert client.post(f"/api/job-requests/{payload['id']}/accept").status_code == 409
    assert client.post(f"/api/job-requests/{payload['id']}/dismiss").status_code == 409


@requires_runtime
def test_recommend_job_with_unknown_role_is_refused_and_stores_nothing(client, workspace, script):
    script([tool_call("j", "recommend_job", {"goal": "x", "role": "wizard"}), text("ok")])
    session_id = client.post("/api/sessions", json={"workspace": str(workspace)}).json()["id"]
    _, results = _turn_results(client, workspace, script, session_id, "recommend")
    assert results["j"]["is_error"] is True and "Unknown role" in results["j"]["message"]
    assert client.get("/api/job-requests").json()["requests"] == []


@requires_runtime
def test_recommend_job_cannot_spend_another_sessions_private_role(client, workspace, script):
    """A session-lifetime role is private: only its creator may name it, and the accept carries source_session so the
    owner's start of THAT role stays explicit."""
    script([tool_call("r", "create_role", {"name": "reader", "description": "Read-only helper.", "tools": ["ReadFile"]}), text("done")])
    session_a = client.post("/api/sessions", json={"workspace": str(workspace)}).json()["id"]
    _, results_a = _turn_results(client, workspace, script, session_a, "make a role")
    assert results_a["r"]["is_error"] is False
    script([tool_call("j", "recommend_job", {"goal": "snoop", "role": "reader"}), text("ok")])
    session_b = client.post("/api/sessions", json={"workspace": str(workspace)}).json()["id"]
    _, results_b = _turn_results(client, workspace, script, session_b, "recommend")
    assert results_b["j"]["is_error"] is True and "private" in results_b["j"]["message"]
    assert client.get("/api/job-requests").json()["requests"] == []


@requires_runtime
def test_recommend_job_with_own_private_role_pins_version_and_accepts(client, workspace, script):
    script([
        tool_call("r", "create_role", {"name": "reader", "description": "Read-only helper.", "tools": ["ReadFile"]}),
        tool_call("j", "recommend_job", {"goal": "sweep", "role": "reader", "reason": "my own role"}),
        text("done"),
    ])
    session_id = client.post("/api/sessions", json={"workspace": str(workspace)}).json()["id"]
    _, results = _turn_results(client, workspace, script, session_id, "make a role and recommend a job")
    assert results["j"]["is_error"] is False, results["j"]
    payload = json.loads(results["j"]["output"])
    assert payload["role_version"] == 1 and payload["source_session"] == session_id  # pinned at proposal time
    script([text("Swept.")])
    accepted = client.post(f"/api/job-requests/{payload['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["job"]["role"] == "reader"
    _wait_job(client, accepted.json()["job"]["id"])


@requires_runtime
def test_dismiss_closes_the_request_and_nothing_runs(client, workspace, script):
    script([tool_call("j", "recommend_job", {"goal": "sweep", "role": "explorer"}), text("ok")])
    session_id = client.post("/api/sessions", json={"workspace": str(workspace)}).json()["id"]
    _, results = _turn_results(client, workspace, script, session_id, "recommend")
    payload = json.loads(results["j"]["output"])
    dismissed = client.post(f"/api/job-requests/{payload['id']}/dismiss")
    assert dismissed.status_code == 200 and dismissed.json()["request"]["status"] == "dismissed"
    assert client.post(f"/api/job-requests/{payload['id']}/accept").status_code == 409
    assert client.get(f"/api/job-requests/{payload['id']}/accept".replace(f"/job-requests/{payload['id']}/accept", "/jobs")).status_code != 200  # no jobs endpoint listing; nothing ran


# ----- JobRequestStore unit tests (no runtime) --------------------------------------------------------------------


def _store(tmp_path):
    return jobs.JobRequestStore(SimpleNamespace(root=tmp_path))


def _record(rid, created=1.0):
    return {"id": rid, "goal": "g", "role": "explorer", "role_version": 0, "workspace": "/w", "reason": "",
            "requested_by": "s1", "source_session": "s1", "status": "pending", "created_at": created}


def test_job_request_store_round_trip_and_single_resolve(tmp_path):
    store = _store(tmp_path)
    store.create(_record("r1"))
    assert [r["id"] for r in store.list()] == ["r1"] and store.list(status="pending")[0]["goal"] == "g"
    accepted = store.mark("r1", "accepted", job_id="job-1")
    assert accepted["status"] == "accepted" and accepted["job_id"] == "job-1"
    with pytest.raises(jobs.JobError):
        store.mark("r1", "dismissed")
    with pytest.raises(jobs.JobError):
        store.mark("missing", "accepted")
    fresh = _store(tmp_path)  # survives a restart (same tenant root)
    assert fresh.get("r1")["status"] == "accepted"


def test_job_request_store_caps_and_drops_resolved_first(tmp_path):
    store = _store(tmp_path)
    for i in range(jobs.MAX_REQUESTS_KEPT + 5):
        store.create(_record(f"r{i}", created=float(i)))
    assert len(store.list()) == jobs.MAX_REQUESTS_KEPT
    for i in range(3):
        store.mark(f"r{i + 5}", "dismissed")
    store.create(_record("new", created=999.0))
    ids = [r["id"] for r in store.list()]
    assert len(ids) == jobs.MAX_REQUESTS_KEPT and "new" in ids and "r5" not in ids  # the oldest RESOLVED dropped first


def test_request_job_validates_goal_and_pins(tmp_path):
    tenant = SimpleNamespace(root=tmp_path, registry=None, workspace_root=tmp_path, job_requests=_store(tmp_path))
    runtime = SimpleNamespace(record=SimpleNamespace(id="s1", workspace="/w"))
    payload, problem = jobs.request_job(tenant, runtime, {"goal": "  "})
    assert payload is None and "goal" in problem
    payload, problem = jobs.request_job(tenant, runtime, {"goal": "sweep", "role": "explorer", "reason": "r"})
    assert problem is None
    assert payload["status"] == "pending" and payload["role_version"] == 0 and payload["source_session"] == "s1"
    assert tenant.job_requests.get(payload["id"])["goal"] == "sweep"


# ----- Owner-start edges: one winner, no false start, owner sees the real scope ----------------------------------


@requires_runtime
def test_accept_after_role_revocation_fails_pending_and_dismissable(client, workspace, script):
    """Pinned-version discipline: the role is revoked between proposal and accept, so the accept REFUSES (the
    re-resolution fails), nothing starts, the request stays pending and the owner can still dismiss it."""
    script([
        tool_call("r", "create_role", {"name": "reader", "description": "Read-only helper.", "tools": ["ReadFile"]}),
        tool_call("j", "recommend_job", {"goal": "sweep", "role": "reader"}),
        text("done"),
    ])
    session_id = client.post("/api/sessions", json={"workspace": str(workspace)}).json()["id"]
    _, results = _turn_results(client, workspace, script, session_id, "make a role and recommend a job")
    payload = json.loads(results["j"]["output"])
    assert client.post("/api/registry/roles/reader/revoke").status_code == 200
    refused = client.post(f"/api/job-requests/{payload['id']}/accept")
    assert refused.status_code == 400 and "Unknown role" in refused.text
    still = client.get("/api/job-requests").json()["requests"][0]
    assert still["status"] == "pending" and "job_id" not in still  # no false start, request not lost
    assert client.post(f"/api/job-requests/{payload['id']}/dismiss").status_code == 200


@requires_runtime
def test_a_narrowed_session_cannot_even_propose(client, workspace, script):
    """Adopting a role narrows the MANAGEMENT tools away with everything else: a session narrowed to explorer
    cannot call recommend_job at all. Proposing new work is a management act, not something a focused role does."""
    client.put("/api/settings", json={"dynamic_tools": True})
    script([
        tool_call("a", "adopt_role", {"name": "explorer"}),
        tool_call("j", "recommend_job", {"goal": "build the feature", "role": "developer"}),
        text("done"),
    ])
    session_id = client.post("/api/sessions", json={"workspace": str(workspace)}).json()["id"]
    _, results = _turn_results(client, workspace, script, session_id, "adopt explorer and recommend a developer job")
    assert results["a"]["is_error"] is False  # narrowed
    assert results["j"]["is_error"] is True  # recommend_job is outside the narrowed scope
    assert client.get("/api/job-requests").json()["requests"] == []  # nothing was stored


@requires_runtime
def test_the_owner_sees_the_effective_scope_before_starting(client, workspace, script):
    """The stored request carries the role's resolved tool scope, so the owner reviews the actual permissions
    being authorized - the role label never hides them."""
    script([tool_call("j", "recommend_job", {"goal": "build the feature", "role": "developer", "reason": "needs writes and shell"}), text("done")])
    session_id = client.post("/api/sessions", json={"workspace": str(workspace)}).json()["id"]
    _, results = _turn_results(client, workspace, script, session_id, "recommend a developer job")
    assert results["j"]["is_error"] is False
    payload = json.loads(results["j"]["output"])
    assert "Shell" in payload["scope"]
    stored = client.get("/api/job-requests").json()["requests"][0]
    assert set(stored["scope"]) == set(jobs.ROLES["developer"])


def test_concurrent_accepts_have_exactly_one_winner(tmp_path):
    """Two accepts racing one pending request: the store lock admits one; the other sees the resolved state.
    Exactly one start runs, so exactly one job would exist."""
    import threading

    store = _store(tmp_path)
    store.create(_record("r1"))
    started = []
    outcomes = []

    def slow_start(record):
        time.sleep(0.05)  # widen the race window: the loser must still not enter start()
        started.append(record["id"])
        return {"id": "job-1"}

    def try_accept():
        try:
            store.accept("r1", slow_start)
            outcomes.append("accepted")
        except jobs.JobError as error:
            outcomes.append(str(error))

    threads = [threading.Thread(target=try_accept) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert started == ["r1"]  # start ran ONCE
    assert outcomes.count("accepted") == 1 and sum("already accepted" in o for o in outcomes) == 1
    assert store.get("r1")["status"] == "accepted" and store.get("r1")["job_id"] == "job-1"


def test_failed_start_leaves_the_request_pending_and_dismissable(tmp_path):
    store = _store(tmp_path)
    store.create(_record("r1"))

    def broken_start(record):
        raise jobs.JobError("isolation `bwrap` is not available here, so the job was not started")

    with pytest.raises(jobs.JobError, match="not available"):
        store.accept("r1", broken_start)
    assert store.get("r1")["status"] == "pending" and "job_id" not in store.get("r1")
    dismissed = store.mark("r1", "dismissed")  # the owner can still close it out
    assert dismissed["status"] == "dismissed"
    with pytest.raises(jobs.JobError):
        store.accept("r1", lambda record: {"id": "job-late"})  # and no late accept revives it


def test_accept_racing_dismiss_has_one_winner(tmp_path):
    """Dismiss holds the same lock: an accept that arrives after a dismiss sees the resolved state and starts nothing."""
    store = _store(tmp_path)
    store.create(_record("r1"))
    store.mark("r1", "dismissed")
    with pytest.raises(jobs.JobError, match="already dismissed"):
        store.accept("r1", lambda record: {"id": "job-should-not-exist"})
    assert store.get("r1")["status"] == "dismissed" and "job_id" not in store.get("r1")

def _requests_file(request_id):
    """The tenant's job-request store file that holds this request (several tenants can share /tmp in one pytest run)."""
    import json as _json
    from pathlib import Path
    for candidate in Path("/tmp").glob("**/jobs/requests.json"):
        try:
            data = _json.loads(candidate.read_text())
        except (OSError, ValueError):
            continue
        if request_id in data:
            return candidate, data
    raise AssertionError("requests store file for the tenant not found")


# ----- Crash-window idempotency and pinned limits --------------------------------------------------------------------


@requires_runtime
def test_accept_after_crash_window_adopts_the_existing_job(client, workspace, script):
    """Failure injection: the accept created and persisted the job, then the host 'died' before the accepted state
    was saved - on disk the request reads pending while its job exists. The retried accept ADOPTS that job: same
    job id, no duplicate start, and the job records which request it fulfills."""
    script([tool_call("j", "recommend_job", {"goal": "sweep", "role": "explorer"}), text("ok")])
    session_id = client.post("/api/sessions", json={"workspace": str(workspace)}).json()["id"]
    _, results = _turn_results(client, workspace, script, session_id, "recommend")
    payload = json.loads(results["j"]["output"])
    script([text("Swept.")])
    first = client.post(f"/api/job-requests/{payload['id']}/accept")
    assert first.status_code == 200, first.text
    job_id = first.json()["job"]["id"]
    item = client.get(f"/api/jobs/{job_id}").json()
    assert item.get("request_id") == payload["id"]  # lineage: the job names the request it fulfills
    # Simulate the crash window: the request's accepted state never landed on disk.
    import json as _json
    store_file, data = _requests_file(payload["id"])
    data[payload["id"]]["status"] = "pending"
    del data[payload["id"]]["job_id"]
    del data[payload["id"]]["resolved_at"]
    store_file.write_text(_json.dumps(data))
    # The retried accept must not start a second job.
    second = client.post(f"/api/job-requests/{payload['id']}/accept")
    assert second.status_code == 200, second.text
    assert second.json()["job"]["id"] == job_id  # SAME job adopted
    assert second.json()["request"]["status"] == "accepted"


@requires_runtime
def test_accept_applies_the_pinned_budget_not_fresh_defaults(client, workspace, script):
    """The budget the owner reviewed is what runs: the stored record's pinned values, not defaults re-read at accept."""
    script([tool_call("j", "recommend_job", {"goal": "sweep", "role": "explorer"}), text("ok")])
    session_id = client.post("/api/sessions", json={"workspace": str(workspace)}).json()["id"]
    _, results = _turn_results(client, workspace, script, session_id, "recommend")
    payload = json.loads(results["j"]["output"])
    assert payload["budget"]["timeout_seconds"] == 900 and payload["budget"]["max_steps"] == 0  # defaults pinned at proposal
    # A default changed after review must not leak in: rewrite the pinned budget as the review saw it (tighter).
    import json as _json
    store_file, data = _requests_file(payload["id"])
    data[payload["id"]]["budget"]["max_steps"] = 3
    store_file.write_text(_json.dumps(data))
    script([text("Swept.")])
    accepted = client.post(f"/api/job-requests/{payload['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    item = client.get(f"/api/jobs/{accepted.json()['job']['id']}").json()
    assert item["budget"]["max_steps"] == 3  # the REVIEWED value ran, not a fresh default


def test_store_accept_adopts_existing_job_without_starting(tmp_path):
    """Store-level injection of the same window: a job already exists for the request; accept must not call start."""
    store = _store(tmp_path)
    store.create(_record("r1"))
    calls = []
    record, item = store.accept("r1", lambda rec: calls.append(rec) or {"id": "job-new"},
                                find_existing=lambda rid: {"id": "job-existing"})
    assert calls == [] and item["id"] == "job-existing"
    assert record["job_id"] == "job-existing" and record["status"] == "accepted"
