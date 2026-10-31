"""Jobs: one unattended piece of work with a role, a tool scope, limits and an output contract.

``POST /api/jobs`` runs a goal in a workspace as an unattended session (what would ask the owner is
declined). The same entry serves a local Root (the owner's OpenRouter key) and a Root on a managed VM:
nothing here depends on where Root runs.

What each limit can and cannot enforce:

* ``max_steps`` - model steps in the turn; the runtime's loop stops at it. A step cap, not a time or cost cap.
* ``timeout_seconds`` - wall-clock time. The runtime's own budget stops the turn before its next model step
  (``CHOTU_MAX_TURN_WALL_SECONDS``); the host cancels 30 s later as a backstop for a hung tool. Not spend.
* ``max_tokens`` / ``max_cost_usd`` - the runtime's own budget, from what the PROVIDER reports for each call,
  checked before the next model step (one call can overshoot). Cost is blind unless the provider reports it
  (OpenRouter does); tokens are blind to a provider that reports no usage. Nothing is estimated. The host's
  LLM proxy keeps its own provider-reported tally as an independent check when it is on.
* After a restart a job that was running is marked ``interrupted`` (its session is kept); it is never lost silently.
* ``role`` - a tool scope preset. Honest about what it bounds: see ``catalogue.guarantee``; any role with a
  shell or Python is not an isolation boundary.
* ``contract`` - keys the final reply's JSON block must have. Checked after the fact; it does not make the
  work correct.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import time
import uuid
from types import SimpleNamespace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from . import broker, catalogue, guides

if TYPE_CHECKING:
    from .tenancy import Tenant

#: Scope presets by name (native tool short names and host tool names). Roles with a code runner
#: (Shell, process, run_python) report ``scope_guarantee.level == "none"``.
ROLES: dict[str, list[str]] = {
    "explorer": ["ReadFile", "Glob", "Grep"],
    "reviewer": ["ReadFile", "Glob", "Grep"],
    "developer": ["ReadFile", "ReadMediaFile", "Glob", "Grep", "WriteFile", "StrReplaceFile", "Shell", "run_python", "process", "find_tools", "use_tool"],
    # Look at a running page (inspect_page: localhost only, executes the page's JS; see tura_code/visual). No code runner,
    # so they cannot start the app themselves: the owner or a developer/tester job runs it first.
    "designer": ["ReadFile", "ReadMediaFile", "Glob", "Grep", "find_tools", "use_tool", "inspect_page", "interact_page", "inspect_deployed", "role_guide", "design_scan"],
    "pm": ["ReadFile", "ReadMediaFile", "Glob", "Grep", "find_tools", "use_tool", "inspect_page", "interact_page", "inspect_deployed", "role_guide"],
    "tester": ["ReadFile", "ReadMediaFile", "Glob", "Grep", "Shell", "process", "find_tools", "use_tool"],
}
#: Roles that return a verdict by default. Skye (or a person) decides what a "block" does; the host only checks shape.
VERDICT_ROLES = {"designer": ["verdict", "reasons"], "pm": ["verdict", "reasons"]}
MAX_JOBS_KEPT = 200
HANDOFF_CHARS = 4000
BACKSTOP_SECONDS = 30


class JobError(ValueError):
    pass


class Budget(BaseModel):
    max_steps: int = Field(default=0, ge=0, le=1000)
    timeout_seconds: int = Field(default=900, ge=1, le=6 * 3600)
    max_tokens: int = Field(default=0, ge=0)
    max_cost_usd: float = Field(default=0.0, ge=0.0, le=1000.0)


class Serve(BaseModel):
    """An app the HOST starts for the job, so a role without ``process`` (designer, pm) can look at it.

    Naming this in the job IS the owner's authorization to run that command in the workspace (an unattended job cannot
    ask). It runs as the host user, not sandboxed, with the host's scrubbed environment (no API keys). The host cannot
    force it to bind to localhost only; ``inspect_page`` only reaches localhost, but the app may listen wider.
    """

    command: str  # split like a shell would, run WITHOUT a shell: no pipes, no &&
    port: int = Field(ge=1024, le=65535)
    ready_seconds: int = Field(default=30, ge=1, le=120)
    path: str = "/"


class Interact(BaseModel):
    """Permission to operate (click, type) a LOCAL app in the browser. See ``visual.act``."""

    origin: str = ""  # e.g. http://localhost:5173; empty with ``serve`` means the served app
    #: Let the page's own POST/PUT/DELETE requests reach the app. Naming this says the app runs on synthetic or throwaway
    #: state: Root cannot see what the app's backend does with a write.
    allow_writes: bool = False


class Deployed(BaseModel):
    """Permission to LOOK at public https pages (GET only, no sign-in, no typing). See ``visual.act``."""

    urls: list[str] = Field(min_length=1, max_length=5)


class NewJob(BaseModel):
    goal: str
    workspace: str
    role: str = "developer"
    budget: Budget = Budget()
    #: Keys the final JSON block must contain, e.g. ["summary", "files_changed"].
    contract: list[str] = []
    #: Earlier jobs whose contract data this one receives (their JSON result only, never their transcript).
    handoff_from: list[str] = []
    #: Names of registered credentials (``broker``) this job may use through ``credentialed_request``.
    credentials: list[str] = []
    #: Start this app before the job and stop it after (see ``Serve``). The job's goal is told the URL.
    serve: Serve | None = None
    #: designer/pm only: operate a local app / look at deployed pages. Absent means the tool does not exist for the job.
    interact: Interact | None = None
    deployed: Deployed | None = None
    #: Required to give credentials to a role that can run code (Shell, process, run_python), which can read the store.
    accept_unprotected_credentials: bool = False
    #: Run the job's runtime (and so its Shell, process and run_python) in a bubblewrap jail. "bwrap": files only, the host's
    #: network is shared. "bwrap-model-only": files and network; only the LLM proxy is reachable. Fails closed.
    isolation: Literal["", "bwrap", "bwrap-model-only"] = ""


def check_contract(reply: str, required: list[str]) -> dict[str, Any]:
    """The last fenced or bare JSON object in the reply and which required keys it lacks.

    Checks SHAPE only (``checked == "shape"``): keys present and, for a ``verdict`` key, ``pass``/``block`` with a
    non-empty ``reasons`` list on a block. It cannot tell whether the work or the verdict is right, so it is not a
    quality gate; whatever acts on a verdict still has to decide how far to trust it.
    """
    if not required:
        return {"ok": True, "missing": [], "data": None, "checked": "shape"}
    candidates = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", reply, flags=re.S) or re.findall(r"(\{.*\})", reply, flags=re.S)
    for text in reversed(candidates):
        try:
            data = json.loads(text)
        except ValueError:
            continue
        if isinstance(data, dict):
            missing = [k for k in required if k not in data]
            if "verdict" in required and "verdict" in data:
                reasons = data.get("reasons")
                if data["verdict"] not in ("pass", "block") or (data["verdict"] == "block" and not (isinstance(reasons, list) and reasons)):
                    missing.append("verdict (must be pass or block; a block needs reasons)")
            return {"ok": not missing, "missing": missing, "data": data, "checked": "shape"}
    return {"ok": False, "missing": list(required), "data": None, "checked": "shape"}


def which_limit(used: dict[str, Any]) -> str:
    """Which of the runtime's own limits a ``budget_exhausted`` turn hit, from its reported accounting."""
    def over(spent: str, cap: str) -> bool:
        return used.get(cap) is not None and (used.get(spent) or 0) >= used[cap]

    if over("tokens_used", "max_tokens"):
        return "token_budget"
    if over("cost_used_usd", "max_cost_usd"):
        return "cost_budget"
    if over("elapsed_millis", "max_wall_clock_millis"):
        return "timeout"
    return "budget"


LOOPBACK_ONLY = {"0100007F", "00000000000000000000000001000000"}
ANSWERS_LOOPBACK = LOOPBACK_ONLY | {"00000000", "00000000000000000000000000000000", "0000000000000000FFFF00000100007F"}


def listener_info(port: int, pgid: int) -> dict[str, Any]:
    """Who listens on a local TCP port, from /proc (Linux): ``owned`` (a socket of a process in ``pgid``) and ``exposed``
    (bound beyond loopback). ``None`` where /proc is unavailable: unknown, not "fine"."""
    inodes: dict[str, str] = {}
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(table).read_text().splitlines()[1:]
        except OSError:
            return {"owned": None, "exposed": None}
        for line in lines:
            fields = line.split()
            addr, _, hexport = fields[1].rpartition(":")
            # Only listeners that answer 127.0.0.1 count: loopback or wildcard. A listener on some other interface address
            # (a forwarder, a VM bridge) cannot serve our connection and is neither ours nor in the way.
            if fields[3] == "0A" and int(hexport, 16) == port and addr in ANSWERS_LOOPBACK:
                inodes[fields[9]] = addr
    if not inodes:
        return {"owned": False, "exposed": False, "listening": False}
    # The app's processes: the group leader's group, plus every descendant (a jailed app is in a new session under bwrap).
    parents: dict[int, int] = {}
    groups: dict[int, int] = {}
    for stat in Path("/proc").glob("[0-9]*/stat"):
        try:
            rest = stat.read_text().rsplit(")", 1)[1].split()
            pid = int(stat.parent.name)
            parents[pid], groups[pid] = int(rest[1]), int(rest[2])
        except (OSError, IndexError, ValueError):
            continue

    def ours(pid: int) -> bool:
        seen = 0
        while pid > 1 and seen < 64:
            if pid == pgid or groups.get(pid) == pgid:
                return True
            pid, seen = parents.get(pid, 0), seen + 1
        return False

    mine = set()
    for pid in parents:
        if ours(pid):
            try:
                for fd in Path(f"/proc/{pid}/fd").iterdir():
                    link = os.readlink(fd)
                    if link.startswith("socket:["):
                        mine.add(link[8:-1])
            except OSError:
                continue
    return {"listening": True, "owned": all(i in mine for i in inodes), "exposed": any(a not in LOOPBACK_ONLY for a in inodes.values())}


def kill_group(pgid: int) -> None:
    try:
        os.killpg(pgid, signal.SIGTERM)
        time.sleep(0.5)
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def overlaps(workspace: Path, root: Path) -> bool:
    """The workspace contains, equals or sits inside the data directory (symlinks resolved): its file tools could reach the store."""
    a, b = Path(workspace).resolve(), Path(root).resolve()
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def credential_guarantee(names: list[str], scope: dict[str, Any], protected: bool = False) -> dict[str, Any] | None:
    if not names:
        return None
    if scope.get("level") == "none" and protected:
        return {"level": "jailed-code-only", "note": "Code the role runs (Shell, process, run_python) is in a bubblewrap jail with no host network: the credential store and owner token are not mounted and the owner API is unreachable, including through the model bridge. This covers THAT code only. The role's host tools (see host_tools_outside_jail) run on the host, outside the jail. It is only as strong as the jail (shared kernel, no seccomp profile of our own) and not an exfiltration boundary: the role can still send any request the grant allows."}
    if scope.get("level") == "none":
        return {"level": "transcript-only", "note": "This role's code can read the 0600 credential store and owner token as the same user, or (in a files-only jail or a served app) reach the owner API's open bootstrap on the host's loopback and get the owner token. The credential stays out of the model's context and the job's outputs; it is NOT protected from the role's own code."}
    return {"level": "host-added", "note": "The host adds the credential to requests to the registered hosts, methods and paths only; no tool in this role is meant to read the store (symlinks out of the workspace and workspaces overlapping the data directory are refused). This is not an exfiltration boundary: the role can still send any request the grant allows, and redaction matches known values and encodings only."}


def launcher_scripted() -> bool:
    from . import launcher

    return launcher.scripted()


class Jobs:
    def __init__(self, tenant: "Tenant") -> None:
        self.tenant = tenant
        self.items: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.dir = Path(tenant.root) / "jobs"
        self._recover()

    # ----- persistence: a job outlives the process that ran it ---------------

    def _save(self, item: dict[str, Any]) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.dir / f"{item['id']}.tmp"
            tmp.write_text(json.dumps(item, default=str), "utf-8")
            tmp.replace(self.dir / f"{item['id']}.json")
        except OSError:
            pass  # in-memory state still answers; a failed write must not fail the job

    def _recover(self) -> None:
        for path in sorted(self.dir.glob("*.json"), key=lambda p: p.stat().st_mtime)[-MAX_JOBS_KEPT:] if self.dir.is_dir() else []:
            try:
                item = json.loads(path.read_text("utf-8"))
            except (OSError, ValueError):
                continue
            serve = item.get("serve") or {}
            if serve.get("pgid") and not serve.get("stopped"):
                # The host died with the app running. Kill it only if that group's leader still has our exact command line
                # (a recycled pid must not be killed).
                try:
                    live = Path(f"/proc/{serve['pgid']}/cmdline").read_bytes().split(b"\0")[:-1]
                except OSError:
                    live = None
                if live is not None and [a.decode(errors="replace") for a in live] == serve.get("argv"):
                    kill_group(int(serve["pgid"]))
                    serve["orphan_killed"] = True
                serve["stopped"] = True
            if item.get("status") == "running":
                # The process that ran it is gone. Say so; the session (and its checkpoint) is still there to inspect.
                item["status"] = "interrupted"
                item["note"] = "The host restarted while this job was running. Inspect its session; nothing was resumed."
                item["finished"] = time.time()
                self._save(item)
            self.items[item["id"]] = item

    # ----- running -----------------------------------------------------------

    def _handoff(self, ids: list[str]) -> str:
        parts = []
        for job_id in ids:
            prior = self.items.get(job_id)
            if prior is None:
                raise JobError(f"handoff_from: no such job `{job_id}`.")
            if prior["status"] == "running":
                raise JobError(f"handoff_from: job `{job_id}` is still running.")
            data = ((prior.get("result") or {}).get("contract") or {}).get("data")
            if data is None:
                raise JobError(f"handoff_from: job `{job_id}` ({prior['role']}) returned no contract data.")
            parts.append(f"From the {prior['role']} job {job_id} (its reported result, unverified):\n{json.dumps(data)[:HANDOFF_CHARS]}")
        return "\n\n".join(parts)

    def _check_isolation(self, spec: NewJob) -> None:
        """Refuse, never downgrade: a jail that cannot be built, or that would hold the real API key, is an error."""
        from . import launcher

        sandbox = self.tenant.sandbox_for(SimpleNamespace(isolation=spec.isolation))
        problem = sandbox.problem()
        if problem:
            raise JobError(f"isolation `{spec.isolation}` is not available here, so the job was not started: {problem}")
        if not launcher.scripted() and not self.tenant.proxy.enabled:
            raise JobError("isolation needs the host's LLM proxy so the real API key stays outside the jail; it is off, so the job was not started.")

    def _visual_authority(self, spec: NewJob) -> dict[str, Any]:
        """What this job may do on pages, validated now so a bad request fails before anything starts."""
        if not (spec.interact or spec.deployed):
            return {}
        from urllib.parse import urlparse

        from .visual import TargetError, host_ports, resolve_target
        from .visual.act import check_deployed_url, resolve_public

        if spec.role not in ("designer", "pm"):
            raise JobError("interact and deployed are for the designer and pm roles only.")
        out: dict[str, Any] = {}
        try:
            if spec.interact:
                origin = spec.interact.origin
                if not origin and spec.serve:
                    origin = f"http://127.0.0.1:{spec.serve.port}"
                if not origin:
                    raise JobError("interact needs an origin (or a serve app to use).")
                _, norm, _ = resolve_target(origin.rstrip("/") + "/", "", Path(spec.workspace))
                port = urlparse(norm).port or 80
                if port in host_ports(None):
                    raise JobError("interact cannot target Root's own server port.")
                out["interact"] = {"origin": norm, "allow_writes": spec.interact.allow_writes}
            if spec.deployed:
                for url in spec.deployed.urls:
                    check_deployed_url(url)
                    resolve_public(urlparse(url).hostname or "")
                out["deployed"] = {"urls": list(spec.deployed.urls), "read_only": True}
        except TargetError as error:
            raise JobError(f"The job was not started: {error}") from error
        return out

    def start(self, spec: NewJob) -> dict[str, Any]:
        if spec.role not in ROLES:
            raise JobError(f"Unknown role `{spec.role}`. Roles: {', '.join(sorted(ROLES))}.")
        if not spec.goal.strip():
            raise JobError("A job needs a goal.")
        if not spec.contract and spec.role in VERDICT_ROLES:
            spec = spec.model_copy(update={"contract": VERDICT_ROLES[spec.role]})
        handoff = self._handoff(spec.handoff_from)
        for name in spec.credentials:
            if not self.tenant.broker.has(name):
                raise JobError(f"credentials: `{name}` is not registered.")
        if (spec.credentials or spec.serve) and overlaps(Path(spec.workspace), Path(self.tenant.root)):
            raise JobError("A job with credentials or a served app cannot use a workspace that contains or sits inside the data directory.")
        runs_code = spec.serve or any(t in ("Shell", "process", "run_python") for t in ROLES[spec.role])
        # Only the model-only jail takes the host network (and so the owner API's open bootstrap) away from the role's code.
        # A served app keeps the shared network even then, so it never counts as protected.
        protected = spec.isolation == "bwrap-model-only" and not spec.serve
        if spec.credentials and runs_code and not protected and not spec.accept_unprotected_credentials:
            raise JobError(f"The {spec.role} role (or the served app) can run code that can read the credential store or fetch the owner token from the host's loopback API. Only isolation `bwrap-model-only` without `serve` protects against that. Pass accept_unprotected_credentials=true to proceed anyway, or use a role without Shell, process or run_python.")
        if spec.isolation:
            if spec.budget.max_cost_usd:
                raise JobError("An isolated job cannot set budget.max_cost_usd: the jail reaches the model through the host proxy, which has no prices and cannot enforce a dollar cap on those requests. Use budget.max_tokens (provider-reported tokens), or run the job without isolation. The job was not started.")
            self._check_isolation(spec)
            if not launcher_scripted() and not spec.budget.max_tokens:
                raise JobError("An isolated job needs budget.max_tokens: the jail's model token is only bounded by that provider-reported token cap (plus request, body, output and model limits). The proxy cannot enforce a dollar cap, so the job was not started.")
        visual_authority = self._visual_authority(spec)
        b = spec.budget
        scope = ROLES[spec.role] + ([broker.TOOL_NAME] if spec.credentials else [])
        runtime = self.tenant.sessions.create(spec.workspace, f"Job · {spec.role}", mode="accept_edits", tool_scope=scope)
        runtime.record.credentials = list(spec.credentials)
        runtime.record.isolation = spec.isolation
        runtime.record.job_role = spec.role
        runtime.record.visual = visual_authority
        runtime.record.unattended = True
        runtime.record.max_steps = b.max_steps
        runtime.record.max_tokens = b.max_tokens
        runtime.record.max_cost_usd = b.max_cost_usd
        runtime.record.max_wall_seconds = b.timeout_seconds
        runtime.save_record()
        job_id = uuid.uuid4().hex[:12]
        item = {
            "id": job_id, "role": spec.role, "goal": spec.goal, "session": runtime.record.id, "status": "running",
            "started": time.time(), "budget": b.model_dump(), "scope_guarantee": catalogue.guarantee(self.tenant, runtime.record),
            "handoff_from": spec.handoff_from, "result": None,
            "credentials": spec.credentials,
        }
        item["credential_guarantee"] = credential_guarantee(spec.credentials, {"level": "none"} if spec.serve else item["scope_guarantee"], protected)
        item["isolation"] = spec.isolation or None
        if visual_authority:
            item["visual_authority"] = visual_authority
        if spec.isolation:
            # These run in the host process, not in the jail, so the jail's network and file limits do not apply to them.
            outside = [t for t in scope if t in ("inspect_page", "interact_page", "inspect_deployed", "credentialed_request", "find_tools", "use_tool", "role_guide", "design_scan")]
            item["host_tools_outside_jail"] = outside
        if spec.isolation:
            item["scope_guarantee"] = {**item["scope_guarantee"], "isolation": spec.isolation, "isolation_note": "Tool names are still not the boundary; the jail is. Shared kernel; no seccomp profile of our own." + (" The host's network is shared: loopback services, including the owner API's open bootstrap (which hands out the owner token), are reachable from the jailed code." if spec.isolation == "bwrap" else " Network for jailed code: only the filtered LLM bridge.") + " Host tools in host_tools_outside_jail (inspect_page, credentialed_request, the find_tools/use_tool gateway) run outside the jail with their own limits."}
        if spec.serve and not spec.isolation:
            item["scope_guarantee"] = {**item["scope_guarantee"], "level": "none", "serve": "The host runs an owner-named command as the host user for this job. The role's tool names do not bound that app's code."}
        self.items[job_id] = item
        self._save(item)
        for old in list(self.items)[:-MAX_JOBS_KEPT]:
            self.items.pop(old, None)
        self.tasks[job_id] = asyncio.create_task(self._drive(item, runtime, spec, handoff))
        return item

    async def _drive(self, item: dict[str, Any], runtime, spec: NewJob, handoff: str) -> None:
        prompt = spec.goal
        if handoff:
            prompt += "\n\nContext from earlier jobs (their own reports; check anything you rely on):\n" + handoff
        prompt += guides.index_for(spec.role)
        if spec.contract:
            prompt += f"\n\nEnd your final reply with one JSON object in a ```json block with the keys: {', '.join(spec.contract)}."
        proxy = self.tenant.proxy
        server = None
        try:
            if spec.serve:
                item["serve"] = {"command": spec.serve.command, "port": spec.serve.port}
                server, url, problem = await self._serve(spec.serve, Path(spec.workspace), item, bool(spec.isolation))
                item["serve"].update({"ready": problem is None, "problem": problem})
                if problem:
                    item["serve"]["stopped"] = True
                if problem:
                    raise JobError(f"The app did not come up: {problem}")
                prompt += f"\n\nThe app is already running for you at {url} (the host started it and will stop it when you finish)."
            await runtime.prompt(prompt)
            deadline = time.monotonic() + spec.budget.timeout_seconds + BACKSTOP_SECONDS
            while not runtime._turn_done.is_set():
                if time.monotonic() > deadline:
                    item["stopped_by"] = "timeout_backstop"
                    await runtime.cancel()
                    break
                await asyncio.sleep(0.2)
            await runtime.wait_turn(30)
            reply = runtime.last_reply
            error = runtime.last_error
            if runtime.record.last_status == "budget_exhausted" and not item.get("stopped_by"):
                item["stopped_by"] = which_limit(runtime.last_budget)
            item["budget_used"] = runtime.last_budget or None  # the runtime's own accounting for the turn
            item["result"] = {"reply": reply, "error": error, "contract": check_contract(reply, spec.contract), "files_touched": runtime.last_files}
            if guides.guides_for(spec.role):
                # Only whether each cited anchor exists; whether a finding is true is not something the host can check.
                data = item["result"]["contract"].get("data") or {}
                if not isinstance(data, dict) or "findings" not in data:
                    parsed = check_contract(reply, ["findings"]).get("data")
                    data = parsed if isinstance(parsed, dict) else {}
                prior = {str(f.get("id")) for jid in spec.handoff_from for f in ((((self.items.get(jid) or {}).get("result") or {}).get("contract") or {}).get("data") or {}).get("findings", []) if isinstance(f, dict) and f.get("id")}
                item["result"]["evidence_check"] = guides.check_findings(data, Path(spec.workspace), runtime.scratch_dir / "inspect", prior)
            if spec.credentials:  # no reply, error or handoff carries a credential value this job could use
                item["result"] = self.tenant.broker.redact_json(item["result"])
            item["status"] = "stopped" if item.get("stopped_by") else (runtime.record.last_status or "finished")
        except Exception as error:  # noqa: BLE001 - a failed job is recorded, never raised
            item["status"] = f"error: {error}"[:300]
        finally:
            if server is not None:
                await asyncio.shield(self._stop(server))  # also when the job was cancelled or the host is closing
                item.setdefault("serve", {})["stopped"] = True
                self._save(item)
            # Provider-reported tokens from the host proxy, when it carried the calls; None otherwise (never estimated).
            item["proxy_tokens_reported"] = proxy.used(runtime.record.id) if proxy.enabled else None
            item["finished"] = time.time()
            self._save(item)
            self.tasks.pop(item["id"], None)

    async def _serve(self, serve: Serve, workspace: Path, item: dict[str, Any], isolated: bool = False):
        import shlex
        import socket

        from .launcher import scrubbed_environment

        argv = shlex.split(serve.command)
        if not argv:
            return None, "", "empty command"
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", serve.port)) == 0 or listener_info(serve.port, -1).get("listening"):
                return None, "", f"port {serve.port} is already in use"
        if isolated:  # files only: the app must stay reachable from the host's browser, so the network is shared
            from .sandbox import Bubblewrap, Mounts

            sandbox = Bubblewrap()
            argv = sandbox.wrap(argv, Mounts(workspace=workspace))
            item["serve"]["jailed"] = "bwrap (files only; host network shared)"
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, cwd=str(workspace), env={**scrubbed_environment(), "PORT": str(serve.port)}, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
            )
        except OSError as error:
            return None, "", str(error)
        item["serve"].update({"argv": argv, "pgid": proc.pid})
        self._save(item)  # recorded before waiting: a host crash now still leaves what to clean up
        deadline = time.monotonic() + serve.ready_seconds
        while time.monotonic() < deadline:
            if proc.returncode is not None:
                return None, "", f"exited with code {proc.returncode} before listening"
            info = listener_info(serve.port, proc.pid)
            if info.get("listening"):
                if info["owned"] is False:
                    await self._stop(proc)
                    return None, "", f"port {serve.port} is held by a process this job did not start"
                item["serve"].update({"port_owned_by_spawned_process": info["owned"], "listens_beyond_loopback": info["exposed"]})
                return proc, f"http://127.0.0.1:{serve.port}{serve.path}", None
            if info.get("owned") is None:  # no /proc: readiness by connect only, ownership unknown
                with socket.socket() as probe:
                    if probe.connect_ex(("127.0.0.1", serve.port)) == 0:
                        item["serve"].update({"port_owned_by_spawned_process": None, "listens_beyond_loopback": None})
                        return proc, f"http://127.0.0.1:{serve.port}{serve.path}", None
            await asyncio.sleep(0.2)
        await self._stop(proc)
        return None, "", f"nothing listening on port {serve.port} after {serve.ready_seconds} s"

    async def _stop(self, proc) -> None:
        """Stop the app's whole process group, including children that outlive the leader."""
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), 3)
        except asyncio.TimeoutError:
            pass
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    async def cancel(self, job_id: str) -> dict[str, Any]:
        item = self.items.get(job_id)
        if item is None:
            raise JobError("No such job.")
        item["stopped_by"] = item.get("stopped_by") or "cancelled"
        await self.tenant.sessions.get(item["session"]).cancel()
        return item

    async def close(self) -> None:
        for task in list(self.tasks.values()):
            task.cancel()


def install(server) -> None:
    def extend(tenant) -> None:
        tenant.jobs = Jobs(tenant)
        tenant.closers.append(tenant.jobs.close)

    server.extensions.append(extend)


def router(app_state):
    from fastapi import APIRouter, Depends, HTTPException

    from .tenancy import Tenant

    api = APIRouter(prefix="/api")

    @api.get("/jobs/roles")
    async def roles() -> dict:
        return {"roles": ROLES}

    @api.post("/jobs")
    async def create(body: NewJob, tenant: Tenant = Depends(app_state.auth.tenant)) -> dict:
        try:
            return tenant.jobs.start(body)
        except (JobError, Exception) as error:  # noqa: BLE001
            raise HTTPException(400, str(error)) from error

    @api.get("/jobs/{job_id}")
    async def get(job_id: str, tenant: Tenant = Depends(app_state.auth.tenant)) -> dict:
        item = tenant.jobs.items.get(job_id)
        if item is None:
            raise HTTPException(404, "No such job.")
        return item

    @api.post("/jobs/{job_id}/cancel")
    async def cancel(job_id: str, tenant: Tenant = Depends(app_state.auth.tenant)) -> dict:
        try:
            return await tenant.jobs.cancel(job_id)
        except JobError as error:
            raise HTTPException(404, str(error)) from error

    return api
