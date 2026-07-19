"""FastAPI surface for solaris-import-google.

Every write is scoped to the acting user resolved from the Authelia
``Remote-User`` header (see app.identity). The UI is a single static page that
POSTs uploaded Takeout files to the per-type endpoints below.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from . import __version__, identity, music_shopping
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

@app.post("/api/music/analyze")
async def music_analyze(request: Request, file: UploadFile = File(...)):
    _user(request)
    _, data = await _one_file(file)
    return _safe(lambda: music_shopping.analyze(data))


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
