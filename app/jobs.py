"""In-process durable job runner for long operations (music analysis).

Long jobs (the YouTube-Music analysis can run minutes-to-hours) must survive a
page reload — so they run server-side in a background thread, not inside the
request. Progress and the final result are mirrored to disk under
``DATA_DIR/jobs/<id>.json`` so the client can reconnect by job id after a reload,
and a *completed* result survives a service restart. A job still in-flight when
the process dies is reported as ``interrupted`` (the per-videoId album cache makes
a re-run fast).

The generator a job runs is passed an ``is_canceled()`` callback so it can stop
promptly when the user cancels.
"""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

from . import config

_LOCK = threading.Lock()
_JOBS: dict[str, "Job"] = {}

# Progress fields we surface to the client.
_PROGRESS_KEYS = ("pct", "message", "stage", "done", "total")


class Job:
    def __init__(self, jid: str):
        self.id = jid
        self.status = "running"  # running | done | error | canceled | interrupted
        self.progress = {"pct": 0, "message": "Start …", "stage": "start"}
        self.result = None
        self.error = None
        self.cancel = threading.Event()

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
        }


def _dir() -> Path:
    d = config.DATA_DIR / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _persist(job: Job) -> None:
    try:
        (_dir() / f"{job.id}.json").write_text(
            json.dumps(job.snapshot(), ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass


def start(gen_factory) -> str:
    """Run ``gen_factory(is_canceled)`` (a progress-yielding generator) in a
    background thread. Returns the job id."""
    jid = uuid.uuid4().hex[:16]
    job = Job(jid)
    with _LOCK:
        _JOBS[jid] = job
    _persist(job)
    threading.Thread(target=_run, args=(job, gen_factory), daemon=True).start()
    return jid


def _run(job: Job, gen_factory) -> None:
    try:
        for ev in gen_factory(job.cancel.is_set):
            if job.cancel.is_set():
                job.status = "canceled"
                _persist(job)
                return
            if "result" in ev:
                job.result = ev["result"]
            job.progress = {k: ev.get(k) for k in _PROGRESS_KEYS if k in ev}
            _persist(job)
        job.status = "canceled" if job.cancel.is_set() else "done"
    except Exception as exc:  # noqa: BLE001 — carry the error to the client
        job.status = "error"
        job.error = f"{type(exc).__name__}: {exc}"
    _persist(job)


def get(jid: str) -> dict | None:
    with _LOCK:
        job = _JOBS.get(jid)
    if job:
        return job.snapshot()
    # Not in memory — the process may have restarted; read the mirror.
    p = _dir() / f"{jid}.json"
    if p.exists():
        try:
            d = json.loads(p.read_text("utf-8"))
        except (OSError, ValueError):
            return None
        if d.get("status") == "running":
            d["status"] = "interrupted"  # its thread died with the old process
        return d
    return None


def cancel(jid: str) -> bool:
    with _LOCK:
        job = _JOBS.get(jid)
    if job:
        job.cancel.set()
        return True
    return False
