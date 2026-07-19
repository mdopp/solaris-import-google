"""Shared pytest fixtures.

Environment is set at import time (before any `app.*` import) because
`app.config` reads env once at import. Everything points at a throwaway data
tree; album resolution is disabled by default (MUSIC_MAX_RESOLVE=0) so tests
never hit the network.
"""

import os
import tempfile
from pathlib import Path

_ROOT = Path(tempfile.mkdtemp(prefix="pytest-import-"))
os.environ.setdefault("RADICALE_DATA", str(_ROOT / "radicale" / "data"))
os.environ.setdefault("FILESHARE_DATA", str(_ROOT / "file-share" / "data"))
os.environ.setdefault("IMPORT_DATA_DIR", str(_ROOT / "data"))
os.environ.setdefault("MUSIC_MAX_RESOLVE", "0")
os.environ.setdefault("REQUIRE_REMOTE_USER", "false")
os.environ.setdefault("DEV_FALLBACK_USER", "mdopp")

(Path(os.environ["RADICALE_DATA"]) / "collections").mkdir(parents=True, exist_ok=True)
(Path(os.environ["FILESHARE_DATA"]) / "notes" / "users").mkdir(parents=True, exist_ok=True)
(Path(os.environ["FILESHARE_DATA"]) / "music").mkdir(parents=True, exist_ok=True)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

USER = "mdopp"


@pytest.fixture()
def user() -> str:
    return USER


@pytest.fixture()
def client() -> TestClient:
    from app.main import app

    return TestClient(app, headers={"Remote-User": USER})


@pytest.fixture()
def music_dir(tmp_path, monkeypatch):
    """An isolated, empty music library for a test, with the scan cache reset."""
    from app import config, library

    d = tmp_path / "music"
    d.mkdir()
    monkeypatch.setattr(config, "MUSIC_DIR", d)
    library._cache.update({"sig": None, "keys": set(), "count": 0})

    def add(artist: str, album: str, title: str):
        p = d / artist / album
        p.mkdir(parents=True, exist_ok=True)
        (p / f"{title}.mp3").write_bytes(b"")  # untagged → path fallback

    return type("Lib", (), {"dir": d, "add": staticmethod(add)})
