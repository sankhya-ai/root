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
* ``recommend_job`` (registry toolset) lets a SESSION propose a job. It only stores an owner-visible request:
  the owner-authenticated ``POST /api/job-requests/{id}/accept`` is the sole start path, and it builds the
  ``NewJob`` exclusively from the stored record (role version pinned at proposal time). A session can never
  start a job, and nothing in the accept call can alter what the session proposed.
"""

from __future__ import annotations

import asyncio
import functools
import json
import os
import re
import signal
import time
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

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
    #: Pin a registry role's version (0 = the version active at start). A session-lifetime role is never promoted
    #: silently: using it means naming it - and optionally its exact version - in this owner-authenticated request.
    role_version: int = 0
    #: Required when the named role is SESSION-LIFETIME (private to the session that created it): the id of that
    #: session. Owner authentication proves WHO is asking; this proves WHICH private role they mean, so a job can
    #: never silently pick up another session's role by an ambiguous name.
    source_session: str = ""
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
    #: Set ONLY by the job-request accept route: the proposal this job fulfills. Recorded on the item so an accept
    #: retried after a host crash adopts the already-created job instead of launching a duplicate.
    request_id: str = ""


def resolve_role(tenant: "Tenant", name: str, version: int = 0, source_session: str = "") -> dict[str, Any]:
    """A role's effective scope: the built-in presets plus ACTIVE registry roles (``registry.py``), re-validated at use time.

    A registry role is data created through ``create_role``; using it still needs this owner-authenticated job start.
    If a composite tool the role names was revoked since the role was created, the job fails here, not mid-job:
    validation at creation time is not treated as a permanent fact.
    """
    if name in ROLES:
        return {"scope": list(ROLES[name]), "version": None, "verdict": name in VERDICT_ROLES, "contract": VERDICT_ROLES.get(name, []), "description": "built-in preset"}
    registry = getattr(tenant, "registry", None)
    record = registry.active_role(name, version=version or None) if registry is not None else None
    if record is None:
        known = sorted(ROLES) + sorted(registry.roles if registry is not None else [])
        raise JobError(f"Unknown role `{name}`" + (f" v{version}." if version else f". Roles: {', '.join(known)}."))
    if record.get("lifetime") == "session" and record.get("session") and source_session != record.get("session"):
        raise JobError(
            f"Role `{name}` v{record['version']} is private to the session that created it. To run a job with it, pass "
            f"source_session='<that session id>' so the choice is explicit, or promote the role into the durable catalogue. "
            "The job was not started."
        )
    inactive = [t for t in record["tools"] if t in registry.tool_names() and registry.active_tool(t) is None]
    if inactive:
        raise JobError(f"Role `{name}` v{record['version']} names registry tool(s) {', '.join(inactive)}, which are no longer active. The job was not started.")
    return {"scope": list(record["tools"]), "version": record["version"], "verdict": bool(record.get("verdict")),
            "contract": list(record.get("contract") or []), "description": record.get("description", "")}


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


#: Owner-reviewed job proposals kept per tenant (bounded; the oldest RESOLVED requests drop first).
MAX_REQUESTS_KEPT = 50
#: Recursion bounds for job-proposed sub-jobs (deterministic, not model judgment): how deep a proposal chain may
#: nest and how many PENDING proposals one job may have open. The owner's accept stays the only start path either way.
MAX_PROPOSAL_DEPTH = 3
MAX_PENDING_PER_PARENT = 5


class JobRequestStore:
    """Owner-reviewed job proposals (``recommend_job`` in ``registry.py``): a session proposes, the owner decides.

    Same multi-process discipline as ``registry.Registry``: mutations run under an exclusive flock on
    ``requests.lock``, re-read the store after acquiring it, and write atomically (tmp file + rename); plain
    reads take a lock-free fresh snapshot, which is consistent because writes are atomic. A stored request is
    inert data - only the owner-authenticated ``accept`` route turns one into ``tenant.jobs.start``, building
    the ``NewJob`` exclusively from the stored fields.
    """

    def __init__(self, tenant: "Tenant") -> None:
        self.dir = Path(tenant.root) / "jobs"
        self.path = self.dir / "requests.json"
        self.items: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data, dict):
            self.items = {str(k): v for k, v in data.items() if isinstance(v, dict)}

    def _save(self) -> None:
        from .registry import _atomic_write  # local import: registry imports jobs only inside functions

        self.dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.path, self.items)

    @contextmanager
    def _exclusive(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / "requests.lock", "a+b") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                self._load()
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def create(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._exclusive():
            self.items[record["id"]] = record
            while len(self.items) > MAX_REQUESTS_KEPT:
                resolved = [r for r in self.items.values() if r.get("status") != "pending"]
                drop = min(resolved or list(self.items.values()), key=lambda r: r.get("created_at", 0))
                del self.items[drop["id"]]
            self._save()
        return record

    def list(self, status: str = "") -> list[dict[str, Any]]:
        self._load()  # fresh snapshot; writes are atomic
        items = sorted(self.items.values(), key=lambda r: r.get("created_at", 0), reverse=True)
        return [r for r in items if not status or r.get("status") == status]

    def get(self, request_id: str) -> dict[str, Any] | None:
        self._load()
        return self.items.get(request_id)

    def accept(self, request_id: str, start, find_existing=None) -> tuple[dict[str, Any], dict[str, Any]]:
        """Claim AND resolve a pending request under one lock: a double accept, or accept racing dismiss, has exactly
        one winner. ``start(record)`` runs while the lock is held, so a concurrent mutation waits and then sees the
        outcome. A FAILED start leaves the request PENDING - nothing ran, the error says why, the owner can still
        dismiss or fix the cause and retry.

        ``find_existing(request_id)`` closes the crash window: the host died AFTER the job was created and persisted
        but BEFORE the accepted state was saved, so the request reads pending while its job exists. The retried
        accept ADOPTS that job instead of starting a duplicate. A crash before the job was persisted is a failure
        before job creation: nothing was recorded, and the retry starts fresh."""
        with self._exclusive():
            record = self.items.get(request_id)
            if record is None:
                raise JobError("No such job request.")
            if record.get("status") != "pending":
                raise JobError(f"Job request {request_id} is already {record.get('status')}; it will not change again.")
            existing = find_existing(request_id) if find_existing is not None else None
            item = existing if existing is not None else start(record)
            record["status"] = "accepted"
            record["resolved_at"] = time.time()
            record["job_id"] = item["id"]
            self._save()
            return record, item

    def mark(self, request_id: str, status: str, job_id: str = "") -> dict[str, Any]:
        """Resolve a PENDING request once. A second resolve (accept after dismiss, double-accept) is an error."""
        with self._exclusive():
            record = self.items.get(request_id)
            if record is None:
                raise JobError("No such job request.")
            if record.get("status") != "pending":
                raise JobError(f"Job request {request_id} is already {record.get('status')}; it will not change again.")
            record["status"] = status
            record["resolved_at"] = time.time()
            if job_id:
                record["job_id"] = job_id
            self._save()
            return record


def request_job(tenant: "Tenant", runtime: Any, arguments: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Validate and store a session's job proposal. Starts NOTHING: the owner's accept route is the only start path.

    The role is resolved and its version PINNED now, so the owner reviews exactly what the session asked for; the
    accept route re-resolves the pinned role (a role revoked in between fails there, not mid-job). The session may
    name a built-in role, a durable registry role, or a session-lifetime role IT created - never another session's
    private role (``resolve_role`` refuses).
    """
    goal = str(arguments.get("goal") or "").strip()
    if not goal:
        return None, "A recommendation needs a goal: what the job should do."
    role = str(arguments.get("role") or "developer").strip()
    version = int(arguments.get("version") or 0)
    session = str(getattr(runtime.record, "id", "") or "")
    try:
        resolved = resolve_role(tenant, role, version, source_session=session)
    except JobError as error:
        return None, str(error)
    # Lineage: is the proposer itself a job? Its item is keyed by the session it created.
    parent = next((j for j in getattr(tenant, "jobs", {}).items.values() if j.get("session") == session), None) if hasattr(tenant, "jobs") else None
    depth = int(parent.get("depth", 0)) + 1 if parent is not None else 0
    if parent is not None and depth > MAX_PROPOSAL_DEPTH:
        return None, (f"This job sits at proposal depth {MAX_PROPOSAL_DEPTH}; a chain may not nest deeper. "
                      "Report the need in your contract data so the owner can start the work directly.")
    if parent is not None:
        pending = sum(1 for r in tenant.job_requests.list(status="pending") if r.get("parent_job_id") == parent["id"])
        if pending >= MAX_PENDING_PER_PARENT:
            return None, (f"This job already has {MAX_PENDING_PER_PARENT} proposals waiting for the owner; that is the cap. "
                          "Do the parts your own tools allow, or report the rest in your contract data.")
    # Attenuation flag: does the proposed child ask for tools the PARENT job does not have? The owner sees this at
    # review. (A chat session proposes from the owner's full scope, so the flag applies to job proposers only.)
    escalation = bool(parent is not None and not set(resolved["scope"]) <= set(parent.get("scope") or []))
    record = {
        "id": uuid.uuid4().hex[:12],
        "goal": goal,
        "role": role,
        "role_version": resolved["version"] or 0,  # pinned at proposal time; built-in presets have no version
        "workspace": str(getattr(runtime.record, "workspace", "") or tenant.workspace_root or tenant.root),
        "reason": str(arguments.get("reason") or "").strip(),
        "requested_by": session,
        "source_session": session,  # lets the owner accept a job on the session's own private role explicitly
        # What the owner is being asked to authorize, resolved NOW: the role's effective tool scope and default
        # contract. Display-only - the accept route re-resolves the pinned role, so this snapshot can never smuggle
        # a wider scope past the owner; it exists so the review shows the actual requested permissions, not a label.
        "scope": list(resolved["scope"]),
        "contract": list(resolved.get("contract") or []),
        "parent_job_id": parent["id"] if parent is not None else "",
        "depth": depth,
        "escalation": escalation,
        # The job-specific limits, PINNED at proposal time (a session cannot set them; these are the defaults).
        # The accept applies exactly these, so a default changed between review and accept cannot silently alter
        # what the owner saw and approved.
        "budget": Budget().model_dump(),
        "status": "pending",
        "created_at": time.time(),
    }
    tenant.job_requests.create(record)
    payload = dict(record)
    payload["what_happens_now"] = ("Nothing started. The owner sees this recommendation and decides; their accept is "
                                   "the only way the job runs, and it runs with exactly the fields stored here.")
    if parent is not None:
        payload["what_happens_now"] += (" Your turn continues without waiting for it, and nothing comes back to you "
                                        "automatically: result handoff to a waiting parent is not built yet. Report "
                                        "what you still need in your own contract data when you finish.")
    return payload, None


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
        resolved = resolve_role(self.tenant, spec.role, spec.role_version, source_session=spec.source_session)
        if not spec.goal.strip():
            raise JobError("A job needs a goal.")
        if not spec.contract and resolved["contract"]:
            spec = spec.model_copy(update={"contract": resolved["contract"]})  # a role's default contract applies when the job doesn't set one
        elif not spec.contract and resolved["verdict"]:
            spec = spec.model_copy(update={"contract": ["verdict", "reasons"]})
        handoff = self._handoff(spec.handoff_from)
        for name in spec.credentials:
            if not self.tenant.broker.has(name):
                raise JobError(f"credentials: `{name}` is not registered.")
        if (spec.credentials or spec.serve) and overlaps(Path(spec.workspace), Path(self.tenant.root)):
            raise JobError("A job with credentials or a served app cannot use a workspace that contains or sits inside the data directory.")
        runs_code = spec.serve or any(t in ("Shell", "process", "run_python") for t in resolved["scope"])
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
        scope = resolved["scope"] + ([broker.TOOL_NAME] if spec.credentials else [])
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
            "id": job_id, "role": spec.role, "role_version": resolved["version"], "goal": spec.goal, "session": runtime.record.id, "status": "running",
            "started": time.time(), "budget": b.model_dump(), "scope": list(scope), "scope_guarantee": catalogue.guarantee(self.tenant, runtime.record),
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
        if spec.request_id:
            item["request_id"] = spec.request_id
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
        prompt += guides.index_for(spec.role, self.tenant)
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
            if guides.guides_for(spec.role, self.tenant):
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
        tenant.job_requests = JobRequestStore(tenant)
        tenant.closers.append(tenant.jobs.close)

    server.extensions.append(extend)


def router(app_state):
    from fastapi import APIRouter, Depends, HTTPException

    from .tenancy import Tenant

    api = APIRouter(prefix="/api")

    @api.get("/jobs/roles")
    async def roles(tenant: Tenant = Depends(app_state.auth.tenant)) -> dict:
        registry = getattr(tenant, "registry", None)
        catalogue_roles = {}
        if registry is not None:
            for name, record in registry.catalogue_roles().items():
                catalogue_roles[name] = {"version": record["version"], "description": record["description"], "tools": record["tools"], "verdict": record["verdict"]}
        return {"roles": ROLES, "registry_roles": catalogue_roles,
                "note": "registry_roles are the durable catalogue (owner-promoted). A session-lifetime role still starts a job when the owner names it; "
                        "using any role is this same owner-authenticated job start."}

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

    @api.get("/job-requests")
    async def job_requests(status: str = "", tenant: Tenant = Depends(app_state.auth.tenant)) -> dict:
        return {"requests": tenant.job_requests.list(status=status)}

    @api.post("/job-requests/{request_id}/accept")
    async def accept_request(request_id: str, tenant: Tenant = Depends(app_state.auth.tenant)) -> dict:
        """The ONLY path from proposal to running job. Owner-authenticated; the NewJob comes from the stored record
        ALONE, and claim + start happen under the store lock, so a double accept or an accept racing a dismiss has
        exactly one winner and can never launch two jobs."""
        store = tenant.job_requests

        def start(record: dict[str, Any]) -> dict[str, Any]:
            spec = NewJob(goal=record["goal"], workspace=record["workspace"], role=record["role"],
                          role_version=int(record.get("role_version") or 0), source_session=record.get("source_session", ""),
                          budget=Budget(**(record.get("budget") or {})), request_id=request_id)
            return tenant.jobs.start(spec)  # every start() guard still applies; a role revoked since the proposal fails HERE

        def find_existing(rid: str) -> dict[str, Any] | None:
            # A previous accept created and persisted the job, then the host died before saving the accepted state.
            return next((j for j in tenant.jobs.items.values() if j.get("request_id") == rid), None)

        try:
            resolved_record, item = store.accept(request_id, start, find_existing)
            if resolved_record.get("parent_job_id"):
                item["parent_job_id"] = resolved_record["parent_job_id"]
                item["depth"] = int(resolved_record.get("depth") or 0)
                tenant.jobs._save(item)
        except JobError as error:
            message = str(error)
            status = 404 if "No such" in message else 409 if "already" in message else 400
            raise HTTPException(status, message) from error
        return {"request": resolved_record, "job": item}

    @api.post("/job-requests/{request_id}/dismiss")
    async def dismiss_request(request_id: str, tenant: Tenant = Depends(app_state.auth.tenant)) -> dict:
        try:
            return {"request": tenant.job_requests.mark(request_id, "dismissed")}
        except JobError as error:
            raise HTTPException(404 if "No such" in str(error) else 409, str(error)) from error

    @api.post("/jobs/{job_id}/cancel")
    async def cancel(job_id: str, tenant: Tenant = Depends(app_state.auth.tenant)) -> dict:
        try:
            return await tenant.jobs.cancel(job_id)
        except JobError as error:
            raise HTTPException(404, str(error)) from error

    return api
