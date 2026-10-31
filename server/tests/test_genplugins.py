"""Generated plugins: candidate code, static screen, jailed verification, owner activation of the exact hash.

The jail tests run real bubblewrap processes (no network namespace, read-only system) and skip where bwrap cannot
run - the same fail-closed rule the feature itself follows.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from tura_code import catalogue, genplugins, registry
from tura_code.genplugins import GeneratedToolset, PluginStore, ProposeToolset


def run(coro):
    return asyncio.run(coro)


def make(tmp_path):
    reg = registry.Registry(tmp_path)
    store = PluginStore(tmp_path)
    holder = SimpleNamespace(value=SimpleNamespace(tool_scope=[], dynamic_tools=False, disabled_plugins=[]))
    tenant = SimpleNamespace(settings=SimpleNamespace(get=lambda: holder.value), registry=reg, plugin_store=store)
    tenant.toolsets = [catalogue.GatewayToolset(), registry.RegistryToolset(), registry.CompositeToolset(reg),
                       GeneratedToolset(store), ProposeToolset(store)]
    tenant.active_toolsets = lambda: tenant.toolsets
    runtime = SimpleNamespace(tenant=tenant, record=SimpleNamespace(job_role="", id="s1", tool_scope=[]), emit=None)
    return tenant, runtime, store


MATH_SOURCE = '''
import math
import statistics


def handle(tool, arguments):
    if tool == "stats_summary":
        numbers = arguments["numbers"]
        return {"mean": statistics.mean(numbers), "stdev": statistics.pstdev(numbers), "root_mean": math.sqrt(statistics.mean(n * n for n in numbers))}
    raise ValueError(f"unknown tool {tool}")
'''

MATH_TESTS = '''
import math

import plugin


def test_stats_summary():
    out = plugin.handle("stats_summary", {"numbers": [2.0, 4.0]})
    assert out["mean"] == 3.0
    assert abs(out["stdev"] - 1.0) < 1e-9


def test_unknown_tool_rejected():
    try:
        plugin.handle("nope", {})
    except ValueError:
        return
    raise AssertionError("expected ValueError")
'''

MANIFEST = [{"name": "stats_summary", "description": "Mean and spread of a number list.",
             "parameters": {"type": "object", "properties": {"numbers": {"type": "array", "items": {"type": "number"}}},
                            "required": ["numbers"], "additionalProperties": False}}]

needs_bwrap = pytest.mark.skipif(bool(genplugins.sandbox_problem()), reason=genplugins.sandbox_problem() or "bwrap available")


def propose(runtime, source=MATH_SOURCE, tests=MATH_TESTS, tools=MANIFEST, name="numstats"):
    toolset = next(t for t in runtime.tenant.toolsets if isinstance(t, ProposeToolset))
    return run(toolset.call(runtime, "c1", "propose_tool", {"name": name, "tools": tools, "source": source, "tests": tests}))


# ----- the static screen: a filter, never a safety pass ---------------------------------------------------------


def test_screen_refuses_os_network_and_interpreter_access():
    assert genplugins.screen_source("import os\nprint(os.getcwd())", "plugin.py")
    assert genplugins.screen_source("import socket", "plugin.py")
    assert genplugins.screen_source("import subprocess", "plugin.py")
    assert genplugins.screen_source("from urllib import request", "plugin.py")
    assert genplugins.screen_source("eval('1+1')", "plugin.py")
    assert genplugins.screen_source("getattr(x, '__globals__')", "plugin.py")
    assert genplugins.screen_source("().__class__", "plugin.py")
    assert genplugins.screen_source("x.__globals__", "plugin.py")
    assert genplugins.screen_source("compile('1', 'f', 'eval')", "plugin.py")
    assert genplugins.screen_source("not python at all {", "plugin.py")


def test_screen_allows_whitelisted_stdlib():
    assert genplugins.screen_source(MATH_SOURCE, "plugin.py") == []
    assert genplugins.screen_source("import json\nimport re\nfrom collections import Counter", "plugin.py") == []


def test_screen_is_not_claimed_as_safety():
    doc = genplugins.__doc__ + genplugins.screen_source.__doc__
    assert "filter" in doc and "not" in doc.lower()


# ----- proposal and lifecycle ------------------------------------------------------------------------------------


def test_refused_candidate_leaves_nothing_behind(tmp_path):
    tenant, runtime, store = make(tmp_path)
    result = propose(runtime, source="import os\n" + MATH_SOURCE)
    assert result["is_error"]
    assert "whitelist" in result["output"] + result["message"]
    assert store.state == {}
    assert not (store.dir / "numstats").exists()


def test_manifest_collisions_and_schema_errors_refused(tmp_path):
    tenant, runtime, store = make(tmp_path)
    result = propose(runtime, tools=[{"name": "create_tool", "description": "shadow", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}])
    assert result["is_error"] and "collides" in result["output"] + result["message"]
    result = propose(runtime, tools=[{"name": "bad name!", "description": "x", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}])
    assert result["is_error"]
    assert store.state == {}


@needs_bwrap
def test_proposal_verifies_in_jail_but_stays_inert(tmp_path):
    tenant, runtime, store = make(tmp_path)
    result = propose(runtime)
    assert not result["is_error"], result["output"]
    payload = json.loads(result["output"])
    assert payload["status"] == "verified"
    assert payload["verification"]["ok"] is True
    assert len(payload["verification"]["results"]) == 2
    # Verified is NOT callable: activation is the owner's API act, not a side effect of proposing.
    generated = next(t for t in tenant.toolsets if isinstance(t, GeneratedToolset))
    assert generated.definitions(runtime) == []
    call = run(generated.call(runtime, "c2", "stats_summary", {"numbers": [1.0]}))
    assert call["is_error"] and "not an active generated tool" in call["output"] + call["message"]


@needs_bwrap
def test_failing_tests_keep_the_candidate_a_draft(tmp_path):
    tenant, runtime, store = make(tmp_path)
    result = propose(runtime, tests="def test_wrong():\n    assert 1 == 2\n")
    payload = json.loads(result["output"])
    assert payload["status"] == "draft"
    assert payload["verification"]["ok"] is False
    with pytest.raises(genplugins.PluginError, match="verified"):
        store.activate("numstats", 1, payload["sha256"])


@needs_bwrap
def test_activation_requires_the_exact_hash_and_owner_api(tmp_path):
    tenant, runtime, store = make(tmp_path)
    payload = json.loads(propose(runtime)["output"])
    with pytest.raises(genplugins.PluginError, match="hash mismatch"):
        store.activate("numstats", 1, "0" * 64)
    record = store.activate("numstats", 1, payload["sha256"])
    assert record["status"] == "active"
    # Now the tool exists and every call runs jailed.
    generated = next(t for t in tenant.toolsets if isinstance(t, GeneratedToolset))
    defs = generated.definitions(runtime)
    assert [d["name"] for d in defs] == ["stats_summary"]
    assert "owner-activated" in defs[0]["description"] and "jail" in defs[0]["description"]
    call = run(generated.call(runtime, "c3", "stats_summary", {"numbers": [2.0, 4.0]}))
    assert not call["is_error"], call
    assert json.loads(call["output"])["mean"] == 3.0


@needs_bwrap
def test_tampered_files_refuse_activation_and_calls(tmp_path):
    tenant, runtime, store = make(tmp_path)
    payload = json.loads(propose(runtime)["output"])
    plugin_py = store.dir / "numstats" / "1" / "plugin.py"
    plugin_py.write_text(plugin_py.read_text() + "\n# tampered\n")
    with pytest.raises(genplugins.PluginError, match="no longer match"):
        store.activate("numstats", 1, payload["sha256"])
    # Restore and activate, then tamper again: calls refuse too.
    plugin_py.write_text(MATH_SOURCE)
    store.activate("numstats", 1, payload["sha256"])
    plugin_py.write_text(plugin_py.read_text() + "\n# tampered\n")
    generated = next(t for t in tenant.toolsets if isinstance(t, GeneratedToolset))
    call = run(generated.call(runtime, "c4", "stats_summary", {"numbers": [1.0]}))
    assert call["is_error"] and "no longer match" in call["message"]


@needs_bwrap
def test_revocation_is_immediate_and_terminal(tmp_path):
    tenant, runtime, store = make(tmp_path)
    payload = json.loads(propose(runtime)["output"])
    store.activate("numstats", 1, payload["sha256"])
    store.revoke("numstats")
    generated = next(t for t in tenant.toolsets if isinstance(t, GeneratedToolset))
    assert generated.definitions(runtime) == []
    call = run(generated.call(runtime, "c5", "stats_summary", {"numbers": [1.0]}))
    assert call["is_error"]
    with pytest.raises(genplugins.PluginError, match="terminal"):
        store.activate("numstats", 1, payload["sha256"])


# ----- the jail is the boundary ----------------------------------------------------------------------------------


@needs_bwrap
def test_the_jail_has_no_network_at_all(tmp_path):
    """Even code that somehow reached the socket module cannot get a packet out: no network namespace."""
    tenant, runtime, store = make(tmp_path)
    reply = run(genplugins.run_jailed(store, ".", 0, {"mode": "probe"}, timeout=10))  # placeholder store paths unused below
    # run_jailed needs a real plugin dir; probe the sandbox directly instead:
    from tura_code.sandbox import Bubblewrap, Mounts
    import shutil, subprocess, tempfile
    scratch = tempfile.mkdtemp()
    sandbox = Bubblewrap(network=False)
    argv = sandbox.wrap([shutil.which("python3"), "-c",
                         "import socket\ntry:\n    socket.create_connection(('127.0.0.1', 9), timeout=2)\n    print('NETWORK_REACHABLE')\nexcept OSError as e:\n    print('NO_NETWORK', type(e).__name__)"],
                        Mounts(workspace=__import__("pathlib").Path(scratch)))
    out = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    assert "NO_NETWORK" in out.stdout and "NETWORK_REACHABLE" not in out.stdout


@needs_bwrap
def test_a_runaway_candidate_is_killed(tmp_path):
    tenant, runtime, store = make(tmp_path)
    payload = json.loads(propose(runtime, tests="def test_ok():\n    pass\n")["output"])
    store.activate("numstats", 1, payload["sha256"])
    plugin_py = store.dir / "numstats" / "1" / "plugin.py"
    original = plugin_py.read_text()
    store.state["numstats"]["versions"][0]["sha256"]  # keep honest state; rewrite files + hash together below
    loop_source = original + "\n"
    loop_source = loop_source.replace('raise ValueError(f"unknown tool {tool}")',
                                      'raise ValueError(f"unknown tool {tool}")\n\n\ndef handle_loop(tool, arguments):\n    while True:\n        pass')
    # rewrite manifest + source and recompute the hash, as a new version would
    plugin_py.write_text(loop_source)
    manifest = json.loads((store.dir / "numstats" / "1" / "plugin.json").read_text())
    manifest["tools"].append({"name": "spin_forever", "description": "never returns", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}})
    (store.dir / "numstats" / "1" / "plugin.json").write_text(json.dumps(manifest))
    files = genplugins.read_files(store.dir / "numstats" / "1")
    store.state["numstats"]["versions"][0]["manifest"] = manifest
    store.state["numstats"]["versions"][0]["sha256"] = genplugins.content_hash(files)
    store._save()
    # replace handle to spin: the candidate maps the new tool to the loop
    plugin_py.write_text(loop_source.replace("def handle(tool, arguments):", "def handle(tool, arguments):\n    if tool == 'spin_forever':\n        return handle_loop(tool, arguments)"))
    files = genplugins.read_files(store.dir / "numstats" / "1")
    store.state["numstats"]["versions"][0]["sha256"] = genplugins.content_hash(files)
    store._save()
    generated = next(t for t in tenant.toolsets if isinstance(t, GeneratedToolset))
    call = run(generated.call(runtime, "c6", "spin_forever", {}))
    assert call["is_error"] and "killed" in call["output"] + call["message"]


@needs_bwrap
def test_oversized_output_is_capped(tmp_path):
    tenant, runtime, store = make(tmp_path)
    big = MATH_SOURCE.replace('return {"mean": statistics.mean(numbers), "stdev": statistics.pstdev(numbers), "root_mean": math.sqrt(statistics.mean(n * n for n in numbers))}',
                              'return "x" * 100000')
    payload = json.loads(propose(runtime, source=big, tests="def test_ok():\n    pass\n")["output"])
    store.activate("numstats", 1, payload["sha256"])
    generated = next(t for t in tenant.toolsets if isinstance(t, GeneratedToolset))
    call = run(generated.call(runtime, "c7", "stats_summary", {"numbers": [1.0]}))
    assert not call["is_error"]
    assert len(call["output"]) <= genplugins.MAX_RESULT_CHARS


# ----- fail closed -----------------------------------------------------------------------------------------------


def test_no_bwrap_means_no_verification_no_activation(tmp_path, monkeypatch):
    monkeypatch.setattr(genplugins, "sandbox_problem", lambda: "bubblewrap (`bwrap`) is not installed.")
    tenant, runtime, store = make(tmp_path)
    reply = run(genplugins.run_jailed(store, "numstats", 1, {"mode": "test"}, timeout=5))
    assert reply["ok"] is False and "unavailable" in reply["error"]


def test_listing_reports_status_and_hashes(tmp_path):
    tenant, runtime, store = make(tmp_path)
    if genplugins.sandbox_problem():
        pytest.skip("bwrap unavailable")
    propose(runtime)
    listing = store.listing()
    assert listing["numstats"]["versions"][0]["status"] == "verified"
    assert len(listing["numstats"]["versions"][0]["sha256"]) == 64
