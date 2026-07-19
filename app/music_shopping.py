"""Turn a YouTube Music listening history into a shopping list of albums the
user does NOT yet have in their library.

Pipeline:
  1. Parse ``watch-history.json`` — keep only ``header == "YouTube Music"``
     entries; extract artist/title/videoId and count plays.
  2. Subtract what the library already owns (``library.owned_keys``).
  3. Resolve each missing track's album from YouTube Music itself via the exact
     videoId (``ytmusicapi``), cached on disk. Unresolved tracks are grouped
     under "(unbekannt)" per artist — never silently dropped.
  4. Aggregate per album: distinct heard tracks + summed play counts, sorted by
     total plays. Exportable as CSV or Markdown.
"""

from __future__ import annotations

import csv
import io
import json
import os
from urllib.parse import parse_qs, urlparse

from . import config, library
from .textnorm import normalize, track_key

# Resolve albums for at most this many missing tracks per run (most-played
# first). The rest still appear, grouped as unresolved — see UNRESOLVED_LABEL.
MAX_RESOLVE = int(os.environ.get("MUSIC_MAX_RESOLVE", "400"))
UNRESOLVED_LABEL = "(unbekannt / Single)"

_ANGESEHEN = " angesehen"
_WATCHED = "watched "


# ---------------------------------------------------------------------------
# History parsing
# ---------------------------------------------------------------------------

def _clean_title(raw: str) -> str:
    t = (raw or "").strip()
    if t.endswith(_ANGESEHEN):
        t = t[: -len(_ANGESEHEN)]
    elif t.lower().startswith(_WATCHED):
        t = t[len(_WATCHED):]
    return t.strip()


def _clean_artist(raw: str) -> str:
    a = (raw or "").strip()
    if a.endswith(" - Topic"):
        a = a[: -len(" - Topic")]
    return a.strip()


def _video_id(url: str) -> str | None:
    try:
        qs = parse_qs(urlparse(url).query)
        return qs.get("v", [None])[0]
    except Exception:
        return None


def aggregate_plays(history_bytes: bytes) -> dict[str, dict]:
    """Return videoId(or synthetic key) -> {artist, title, videoId, count}."""
    data = json.loads(history_bytes)
    plays: dict[str, dict] = {}
    for entry in data:
        if entry.get("header") != "YouTube Music":
            continue
        subs = entry.get("subtitles") or []
        if not subs:
            continue
        artist = _clean_artist(subs[0].get("name", ""))
        title = _clean_title(entry.get("title", ""))
        if not title:
            continue
        vid = _video_id(entry.get("titleUrl", "")) or ""
        key = vid or track_key(artist, title)
        rec = plays.setdefault(
            key, {"artist": artist, "title": title, "videoId": vid, "count": 0}
        )
        rec["count"] += 1
    return plays


# ---------------------------------------------------------------------------
# Album resolution (ytmusicapi, cached)
# ---------------------------------------------------------------------------

def _cache_path():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return config.DATA_DIR / "ytmusic_album_cache.json"


def _load_cache() -> dict:
    p = _cache_path()
    if p.exists():
        try:
            return json.loads(p.read_text("utf-8"))
        except ValueError:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    try:
        _cache_path().write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass


_yt = None


def _yt_client():
    global _yt
    if _yt is None:
        from ytmusicapi import YTMusic

        _yt = YTMusic()  # unauthenticated — song lookups don't need auth
    return _yt


def _lookup_album(video_id: str) -> tuple[str | None, str | None]:
    try:
        wp = _yt_client().get_watch_playlist(videoId=video_id, limit=1)
        track = (wp.get("tracks") or [{}])[0]
        album = (track.get("album") or {}).get("name")
        artists = track.get("artists") or []
        artist = artists[0]["name"] if artists else None
        return album, artist
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze(history_bytes: bytes) -> dict:
    plays = aggregate_plays(history_bytes)
    owned = library.owned_keys()

    total_plays = sum(p["count"] for p in plays.values())
    missing = [
        p for p in plays.values()
        if track_key(p["artist"], p["title"]) not in owned
    ]
    owned_matches = len(plays) - len(missing)

    # Resolve albums for the most-played missing tracks first.
    missing.sort(key=lambda p: p["count"], reverse=True)
    cache = _load_cache()
    resolved = 0
    for i, p in enumerate(missing):
        vid = p["videoId"]
        if not vid:
            p["album"], p["album_artist"], p["resolved"] = None, p["artist"], False
            continue
        if vid in cache:
            album, art = cache[vid].get("album"), cache[vid].get("artist")
        elif i < MAX_RESOLVE:
            album, art = _lookup_album(vid)
            cache[vid] = {"album": album, "artist": art}
        else:
            album, art = None, None  # over the cap — stays unresolved, not dropped
        if album:
            resolved += 1
        p["album"] = album
        p["album_artist"] = art or p["artist"]
        p["resolved"] = bool(album)
    _save_cache(cache)

    albums = _group_albums(missing)
    return {
        "type": "music",
        "library_size": library.library_size(),
        "history_plays": total_plays,
        "unique_tracks": len(plays),
        "owned_matches": owned_matches,
        "missing_tracks": len(missing),
        "resolved_tracks": resolved,
        "unresolved_tracks": len(missing) - resolved,
        "resolve_cap": MAX_RESOLVE if len(missing) > MAX_RESOLVE else None,
        "albums": albums,
    }


def _group_albums(missing: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], dict] = {}
    for p in missing:
        album = p.get("album") or UNRESOLVED_LABEL
        artist = p.get("album_artist") or p["artist"]
        gkey = (normalize(artist), normalize(album))
        g = groups.setdefault(
            gkey,
            {
                "album": album,
                "artist": artist,
                "heard_tracks": 0,
                "total_plays": 0,
                "resolved": p.get("resolved", False),
                "tracks": [],
            },
        )
        g["heard_tracks"] += 1
        g["total_plays"] += p["count"]
        g["tracks"].append({"title": p["title"], "plays": p["count"]})
    ordered = sorted(
        groups.values(),
        key=lambda g: (g["total_plays"], g["heard_tracks"]),
        reverse=True,
    )
    return ordered


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def to_csv(albums: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Album", "Artist", "Gehörte Tracks", "Gesamt-Abspielungen", "Aufgelöst"])
    for a in albums:
        w.writerow([
            a["album"], a["artist"], a["heard_tracks"], a["total_plays"],
            "ja" if a.get("resolved") else "nein",
        ])
    return buf.getvalue()


def to_markdown(albums: list[dict]) -> str:
    lines = [
        "# Musik-Einkaufsliste (fehlende Alben)",
        "",
        "| Album | Artist | Gehörte Tracks | Gesamt-Abspielungen |",
        "| --- | --- | ---: | ---: |",
    ]
    for a in albums:
        album = a["album"].replace("|", "\\|")
        artist = a["artist"].replace("|", "\\|")
        lines.append(f"| {album} | {artist} | {a['heard_tracks']} | {a['total_plays']} |")
    lines.append("")
    return "\n".join(lines)
