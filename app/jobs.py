"""Server-owned durable jobs for long operations (music analysis).

A job is a **server-side process**, not something the browser owns. The frontend
is only a view + remote control: it starts a job, then reconnects to it by asking
the server (``latest_for`` / ``get``) — so a page reload never loses the job, and
a *different* browser can attach to the same running work.

Durability:
- progress + result are mirrored to disk (``DATA_DIR/jobs/<id>.json``);
- the job's *input* (e.g. the uploaded history) is persisted too, so on process
  startup a job that was still running is **resumed** automatically
  (``resume()``) rather than lost. Album lookups are cached per videoId, so a
  resume is cheap. If the input is gone, the job is reported ``interrupted``.

A job is rebuilt from a JSON-serialisable ``spec`` via a registered ``runner``
(``@runner("music")``), which returns ``factory(is_canceled) -> generator``.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
import uuid
from pathlib import Path

from . import config

_LOCK = threading.Lock()
_JOBS: dict[str, "Job"] = {}
_RUNNERS: dict[str, callable] = {}
_PROGRESS_KEYS = ("pct", "message", "stage", "done", "total")


def runner(kind: str):
    """Register a builder for a job kind: ``fn(spec) -> factory(is_canceled)``."""
    def deco(fn):
        _RUNNERS[kind] = fn
        return fn
    return deco


class Job:
    def __init__(self, jid, owner, spec, created=None):
        self.id = jid
        self.owner = owner
        self.spec = spec
        self.created = created if created is not None else time.time()
        self.status = "running"
        self.progress = {"pct": 0, "message": "Start …", "stage": "start"}
        self.result = None
        self.error = None
        self.cancel = threading.Event()

    def meta(self) -> dict:
        return {
            "id": self.id, "owner": self.owner, "spec": self.spec,
            "created": self.created, "status": self.status,
            "progress": self.progress, "result": self.result, "error": self.error,
        }

    def snapshot(self) -> dict:
        return {"id": self.id, "status": self.status, "progress": self.progress,
                "result": self.result, "error": self.error}


def _dir() -> Path:
    d = config.DATA_DIR / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _persist(job: Job) -> None:
    try:
        (_dir() / f"{job.id}.json").write_text(
            json.dumps(job.meta(), ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _cleanup_input(job: Job) -> None:
    inp = job.spec.get("input")
    if inp:
        with contextlib.suppress(OSError):
            Path(inp).unlink()


def start(owner: str, spec: dict) -> str:
    """Start a job for ``owner``; ``spec['kind']`` selects the registered runner."""
    jid = uuid.uuid4().hex[:16]
    job = Job(jid, owner, spec)
    with _LOCK:
        _JOBS[jid] = job
    _persist(job)
    _spawn(job)
    return jid


def _spawn(job: Job) -> None:
    factory = _RUNNERS[job.spec["kind"]](job.spec)
    threading.Thread(target=_run, args=(job, factory), daemon=True).start()


def _run(job: Job, factory) -> None:
    try:
        for ev in factory(job.cancel.is_set):
            if job.cancel.is_set():
                job.status = "canceled"
                _persist(job)
                _cleanup_input(job)
                return
            if "result" in ev:
                job.result = ev["result"]
            job.progress = {k: ev.get(k) for k in _PROGRESS_KEYS if k in ev}
            _persist(job)
        job.status = "canceled" if job.cancel.is_set() else "done"
    except Exception as exc:  # noqa: BLE001
        job.status = "error"
        job.error = f"{type(exc).__name__}: {exc}"
    _persist(job)
    _cleanup_input(job)


def get(jid: str, owner: str | None = None) -> dict | None:
    with _LOCK:
        job = _JOBS.get(jid)
    if job:
        if owner and job.owner != owner:
            return None
        return job.snapshot()
    p = _dir() / f"{jid}.json"
    if p.exists():
        try:
            d = json.loads(p.read_text("utf-8"))
        except (OSError, ValueError):
            return None
        if owner and d.get("owner") != owner:
            return None
        status = "interrupted" if d.get("status") == "running" else d.get("status")
        return {"id": d["id"], "status": status, "progress": d.get("progress", {}),
                "result": d.get("result"), "error": d.get("error")}
    return None


def cancel(jid: str, owner: str | None = None) -> bool:
    with _LOCK:
        job = _JOBS.get(jid)
    if job and (not owner or job.owner == owner):
        job.cancel.set()
        return True
    return False


def latest_for(owner: str) -> dict | None:
    """The owner's most recent job (running or finished) — the server-side source
    of truth a fresh frontend attaches to."""
    best = None
    for f in _dir().glob("*.json"):
        try:
            d = json.loads(f.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if d.get("owner") != owner:
            continue
        if best is None or d.get("created", 0) > best.get("created", 0):
            best = d
    if not best:
        return None
    live = get(best["id"], owner)
    return {"jobId": best["id"], **live} if live else None


def resume() -> None:
    """Re-spawn jobs that were still running when the process last died."""
    for f in list(_dir().glob("*.json")):
        try:
            d = json.loads(f.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if d.get("status") != "running" or d["id"] in _JOBS:
            continue
        spec = d.get("spec") or {}
        inp = spec.get("input")
        if spec.get("kind") not in _RUNNERS or (inp and not Path(inp).exists()):
            d["status"] = "interrupted"  # can't resume without runner/input
            with contextlib.suppress(OSError):
                f.write_text(json.dumps(d), encoding="utf-8")
            continue
        job = Job(d["id"], d.get("owner"), spec, created=d.get("created"))
        job.progress = d.get("progress", job.progress)
        with _LOCK:
            _JOBS[job.id] = job
        _spawn(job)
