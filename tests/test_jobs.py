import json
import time
from pathlib import Path

from app import config, jobs


@jobs.runner("t-done")
def _r_done(spec):
    n = spec.get("n", 0)

    def f(is_canceled):
        yield {"stage": "a", "pct": 50}
        yield {"stage": "done", "pct": 100, "result": {"ok": True, "n": n}}
    return f


@jobs.runner("t-error")
def _r_error(spec):
    def f(is_canceled):
        yield {"pct": 1}
        raise ValueError("boom")
    return f


@jobs.runner("t-loop")
def _r_loop(spec):
    def f(is_canceled):
        while not is_canceled():
            yield {"pct": 1}
            time.sleep(0.01)
    return f


@jobs.runner("t-resume")
def _r_resume(spec):
    def f(is_canceled):
        yield {"stage": "done", "pct": 100, "result": {"echo": Path(spec["input"]).read_text()}}
    return f


def _wait(jid, owner=None, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = jobs.get(jid, owner=owner)
        if st and st["status"] != "running":
            return st
        time.sleep(0.02)
    return jobs.get(jid, owner=owner)


def test_runs_to_done():
    st = _wait(jobs.start("u1", {"kind": "t-done", "n": 5}))
    assert st["status"] == "done" and st["result"] == {"ok": True, "n": 5}


def test_owner_isolation():
    jid = jobs.start("owner-a", {"kind": "t-done"})
    _wait(jid, owner="owner-a")
    assert jobs.get(jid, owner="owner-b") is None
    assert jobs.get(jid, owner="owner-a")["status"] == "done"


def test_error_captured():
    st = _wait(jobs.start("u1", {"kind": "t-error"}))
    assert st["status"] == "error" and "boom" in st["error"]


def test_cancel():
    jid = jobs.start("u1", {"kind": "t-loop"})
    time.sleep(0.05)
    assert jobs.cancel(jid, owner="u1") is True
    assert _wait(jid)["status"] == "canceled"


def test_cancel_wrong_owner_refused():
    jid = jobs.start("u1", {"kind": "t-loop"})
    time.sleep(0.02)
    assert jobs.cancel(jid, owner="intruder") is False
    jobs.cancel(jid, owner="u1")  # clean up the loop


def test_get_and_cancel_unknown():
    assert jobs.get("does-not-exist") is None
    assert jobs.cancel("does-not-exist") is False


def test_latest_for_returns_recent():
    jid = jobs.start("latest-user", {"kind": "t-done"})
    _wait(jid, owner="latest-user")
    latest = jobs.latest_for("latest-user")
    assert latest["jobId"] == jid and latest["status"] == "done"
    assert jobs.latest_for("nobody-here-at-all") is None


def test_interrupted_running_job_from_disk():
    d = config.DATA_DIR / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ghost-int.json").write_text(json.dumps({
        "id": "ghost-int", "owner": "u1", "spec": {"kind": "nope"}, "created": 1.0,
        "status": "running", "progress": {}, "result": None, "error": None}))
    assert jobs.get("ghost-int")["status"] == "interrupted"


def test_resume_respawns_running_job(tmp_path):
    inp = tmp_path / "in.txt"
    inp.write_text("hello")
    d = config.DATA_DIR / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "resumeme.json").write_text(json.dumps({
        "id": "resumeme", "owner": "u1", "created": 2.0,
        "spec": {"kind": "t-resume", "input": str(inp)},
        "status": "running", "progress": {}, "result": None, "error": None}))
    jobs.resume()
    st = _wait("resumeme")
    assert st["status"] == "done" and st["result"] == {"echo": "hello"}


def test_resume_without_input_marks_interrupted():
    d = config.DATA_DIR / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "noinput.json").write_text(json.dumps({
        "id": "noinput", "owner": "u1", "created": 3.0,
        "spec": {"kind": "t-resume", "input": "/nonexistent/x"},
        "status": "running", "progress": {}, "result": None, "error": None}))
    jobs.resume()
    assert jobs.get("noinput")["status"] == "interrupted"
