import json
import threading
import time

from app import config, jobs


def _wait(jid, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = jobs.get(jid)
        if st and st["status"] != "running":
            return st
        time.sleep(0.02)
    return jobs.get(jid)


def test_job_runs_to_done():
    def factory(is_canceled):
        yield {"stage": "a", "pct": 50, "message": "half"}
        yield {"stage": "done", "pct": 100, "message": "done", "result": {"ok": True}}

    st = _wait(jobs.start(factory))
    assert st["status"] == "done"
    assert st["result"] == {"ok": True}


def test_job_error_is_captured():
    def factory(is_canceled):
        yield {"stage": "a", "pct": 10}
        raise ValueError("boom")

    st = _wait(jobs.start(factory))
    assert st["status"] == "error" and "boom" in st["error"]


def test_job_cancel():
    started = threading.Event()

    def factory(is_canceled):
        while not is_canceled():
            started.set()
            yield {"stage": "loop", "pct": 1}
            time.sleep(0.01)

    jid = jobs.start(factory)
    assert started.wait(1)
    assert jobs.cancel(jid) is True
    st = _wait(jid)
    assert st["status"] == "canceled"


def test_get_unknown_returns_none():
    assert jobs.get("does-not-exist") is None


def test_cancel_unknown_returns_false():
    assert jobs.cancel("does-not-exist") is False


def test_interrupted_running_job_from_disk():
    d = config.DATA_DIR / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ghost.json").write_text(json.dumps(
        {"id": "ghost", "status": "running", "progress": {}, "result": None, "error": None}
    ))
    st = jobs.get("ghost")
    assert st["status"] == "interrupted"
