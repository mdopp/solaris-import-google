"""FastAPI surface for solaris-import-google.

Every write is scoped to the acting user resolved from the Authelia
``Remote-User`` header (see app.identity). The UI is a single static page that
POSTs uploaded Takeout files to the per-type endpoints below.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from . import __version__, config, identity, jobs, music_shopping
from .importers import calendar as cal_importer
from .importers import contacts as contacts_importer
from .importers import keep as keep_importer

app = FastAPI(title="solaris-import-google", version=__version__)

_STATIC = Path(__file__).parent / "static"


def _user(request: Request) -> str:
    try:
        return identity.resolve_user(request.headers)
    except identity.IdentityError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


async def _one_file(file: UploadFile) -> tuple[str, bytes]:
    return file.filename or "upload", await file.read()


# --- meta -----------------------------------------------------------------

@app.get("/healthz")
def healthz():
    return {"status": "ok", "version": __version__}


@app.get("/api/whoami")
def whoami(request: Request):
    return {"user": _user(request)}


@app.get("/")
def index():
    return FileResponse(_STATIC / "index.html")


# --- calendar -------------------------------------------------------------

@app.post("/api/calendar/preview")
async def calendar_preview(request: Request, file: UploadFile = File(...)):
    _user(request)
    name, data = await _one_file(file)
    return _safe(lambda: cal_importer.preview(name, data))


@app.post("/api/calendar/import")
async def calendar_import(request: Request, file: UploadFile = File(...)):
    user = _user(request)
    name, data = await _one_file(file)
    return _safe(lambda: cal_importer.do_import(user, name, data))


# --- contacts -------------------------------------------------------------

@app.post("/api/contacts/preview")
async def contacts_preview(request: Request, file: UploadFile = File(...)):
    _user(request)
    name, data = await _one_file(file)
    return _safe(lambda: contacts_importer.preview(name, data))


@app.post("/api/contacts/import")
async def contacts_import(request: Request, file: UploadFile = File(...)):
    user = _user(request)
    name, data = await _one_file(file)
    return _safe(lambda: contacts_importer.do_import(user, name, data))


# --- keep -----------------------------------------------------------------

@app.post("/api/keep/preview")
async def keep_preview(request: Request, files: list[UploadFile] = File(...)):
    _user(request)
    payload = [await _one_file(f) for f in files]
    return _safe(lambda: keep_importer.preview(payload))


@app.post("/api/keep/import")
async def keep_import(request: Request, files: list[UploadFile] = File(...)):
    user = _user(request)
    payload = [await _one_file(f) for f in files]
    return _safe(lambda: keep_importer.do_import(user, payload))


# --- music shopping list --------------------------------------------------

@jobs.runner("music")
def _music_runner(spec: dict):
    """Rebuild the analysis generator from a persisted job spec (used both on
    first start and when resuming after a restart)."""
    data = Path(spec["input"]).read_bytes()
    opts = spec.get("opts", {})

    def factory(is_canceled):
        return music_shopping.analyze_iter(data, is_canceled=is_canceled, **opts)

    return factory


@app.on_event("startup")
def _resume_jobs():
    # Re-spawn any job that was still running when the process last stopped.
    jobs.resume()


@app.post("/api/music/analyze")
async def music_analyze(
    request: Request,
    file: UploadFile = File(...),
    min_plays: int = Form(1),
    months: int = Form(0),
    resolve: bool = Form(True),
    cap: int = Form(400),
):
    """Start a server-side analysis job and return its id. The work runs
    independent of the browser (survives reload; the client reconnects via
    /api/music/latest or /api/music/job/{id}). The input is persisted so the job
    resumes after a service restart. Upfront options bound the runtime."""
    user = _user(request)
    _, data = await _one_file(file)
    jobs_dir = config.DATA_DIR / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    inp = jobs_dir / f"{uuid.uuid4().hex}.input"
    inp.write_bytes(data)
    spec = {
        "kind": "music",
        "input": str(inp),
        "opts": {"min_plays": min_plays, "months": months, "resolve": resolve, "cap": cap},
    }
    return {"jobId": jobs.start(user, spec)}


@app.get("/api/music/latest")
def music_latest(request: Request):
    """The acting user's current/most-recent job, so any fresh page load can
    attach to the running server-side process without client-side state."""
    user = _user(request)
    return jobs.latest_for(user)


@app.get("/api/music/job/{jid}")
def music_job(request: Request, jid: str):
    user = _user(request)
    st = jobs.get(jid, owner=user)
    if not st:
        raise HTTPException(status_code=404, detail="unbekannter Job")
    return st


@app.post("/api/music/job/{jid}/cancel")
def music_job_cancel(request: Request, jid: str):
    user = _user(request)
    return {"canceled": jobs.cancel(jid, owner=user)}


@app.post("/api/music/export/csv")
def music_export_csv(request: Request, payload: dict = Body(...)):
    _user(request)
    csv_text = music_shopping.to_csv(payload.get("albums", []))
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=einkaufsliste.csv"},
    )


@app.post("/api/music/export/md")
def music_export_md(request: Request, payload: dict = Body(...)):
    _user(request)
    md_text = music_shopping.to_markdown(payload.get("albums", []))
    return PlainTextResponse(
        md_text,
        media_type="text/markdown",
        headers={"Content-Disposition": "attachment; filename=einkaufsliste.md"},
    )


def _safe(fn):
    """Run an importer and turn parsing errors into a 400 with a message."""
    try:
        return fn()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — surface a readable error to the UI
        return JSONResponse(status_code=400, content={"error": f"{type(exc).__name__}: {exc}"})
