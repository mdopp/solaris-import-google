import json
import time

from fastapi.testclient import TestClient

CAL_ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//t//EN
BEGIN:VEVENT
UID:x@t
DTSTART;VALUE=DATE:20260301
SUMMARY:Probe
END:VEVENT
END:VCALENDAR
"""

KEEP_JSON = json.dumps({"title": "N", "textContent": "hi",
                        "createdTimestampUsec": 1590000000000000}).encode()

HIST = json.dumps([
    {"header": "YouTube Music", "title": "Song angesehen",
     "titleUrl": "https://music.youtube.com/watch?v=q",
     "subtitles": [{"name": "Band - Topic"}], "time": "2026-07-15T10:00:00.000Z"},
]).encode()


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_whoami(client):
    assert client.get("/api/whoami").json()["user"] == "mdopp"


def test_calendar_preview_and_import(client):
    r = client.post("/api/calendar/preview", files={"file": ("c.ics", CAL_ICS, "text/calendar")})
    assert r.status_code == 200 and r.json()["items"] >= 1
    r = client.post("/api/calendar/import", files={"file": ("c.ics", CAL_ICS, "text/calendar")})
    assert r.json()["written"] >= 1


def test_bad_input_returns_400(client):
    r = client.post("/api/calendar/preview", files={"file": ("c.ics", b"nope", "text/calendar")})
    assert r.status_code == 400 and "error" in r.json()


def test_keep_import_multi(client):
    r = client.post("/api/keep/import", files=[("files", ("n.json", KEEP_JSON, "application/json"))])
    assert r.json()["written"] == 1


def test_music_job_lifecycle(client):
    r = client.post("/api/music/analyze",
                    files={"file": ("h.json", HIST, "application/json")},
                    data={"resolve": "false", "min_plays": "1"})
    jid = r.json()["jobId"]
    st = {"status": "running"}
    for _ in range(250):
        st = client.get(f"/api/music/job/{jid}").json()
        if st["status"] != "running":
            break
        time.sleep(0.02)
    assert st["status"] == "done" and st["result"]["type"] == "music"


def test_music_job_unknown_404(client):
    assert client.get("/api/music/job/nope").status_code == 404


def test_music_analyze_requires_file(client):
    assert client.post("/api/music/analyze").status_code == 422


def test_music_cancel_returns_bool(client):
    r = client.post("/api/music/analyze",
                    files={"file": ("h.json", HIST, "application/json")},
                    data={"resolve": "false"})
    jid = r.json()["jobId"]
    assert isinstance(client.post(f"/api/music/job/{jid}/cancel").json()["canceled"], bool)


def test_music_exports(client):
    albums = [{"album": "A", "artist": "B", "heard_tracks": 2, "total_plays": 5, "resolved": True}]
    assert client.post("/api/music/export/csv", json={"albums": albums}).text.startswith("Album,Artist,")
    assert "| Album | Artist |" in client.post("/api/music/export/md", json={"albums": albums}).text


def test_missing_header_rejected(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "REQUIRE_REMOTE_USER", True)
    monkeypatch.setattr(config, "DEV_FALLBACK_USER", "")
    from app.main import app
    c = TestClient(app)  # no default Remote-User header
    assert c.get("/api/whoami").status_code == 401
