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
from datetime import datetime, timedelta, timezone
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


def _entry_time(entry: dict) -> datetime | None:
    ts = entry.get("time")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def aggregate_plays(history_bytes: bytes, since: datetime | None = None) -> dict[str, dict]:
    """Return videoId(or synthetic key) -> {artist, title, videoId, count}.

    ``since`` (if given) drops plays older than that timestamp.
    """
    data = json.loads(history_bytes)
    plays: dict[str, dict] = {}
    for entry in data:
        if entry.get("header") != "YouTube Music":
            continue
        if since is not None:
            t = _entry_time(entry)
            if t is not None and t < since:
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

def analyze_iter(history_bytes: bytes, *, min_plays: int = 1, months: int = 0,
                 resolve: bool = True, cap: int | None = None, is_canceled=None):
    """Generator yielding progress events, terminating with one carrying the full
    ``result``. Upfront options bound the runtime (the caller collects them from
    the user before starting), so we don't spend minutes/hours on unwanted work:

    - ``min_plays``  — ignore tracks played fewer than this many times.
    - ``months``     — only consider plays from the last N months (0 = all).
    - ``resolve``    — resolve albums via YouTube Music (slow); if False, group by
      artist instantly.
    - ``cap``        — resolve at most this many missing tracks (most-played first).
    - ``is_canceled``— polled between items so a user cancel stops promptly.
    """
    is_canceled = is_canceled or (lambda: False)
    cap = MAX_RESOLVE if cap is None else cap
    since = None
    if months and months > 0:
        since = datetime.now(timezone.utc) - timedelta(days=30 * months)

    yield {"stage": "parse", "message": "Historie einlesen …", "pct": 2}
    plays = aggregate_plays(history_bytes, since=since)
    if min_plays and min_plays > 1:
        plays = {k: v for k, v in plays.items() if v["count"] >= min_plays}
    total_plays = sum(p["count"] for p in plays.values())
    scope = []
    if min_plays > 1:
        scope.append(f"≥{min_plays}×")
    if months:
        scope.append(f"letzte {months} Mon.")
    scope_txt = f" ({', '.join(scope)})" if scope else ""
    yield {"stage": "parse",
           "message": f"{len(plays)} Songs · {total_plays} Abspielungen{scope_txt}", "pct": 8}

    # --- library scan (incremental; the slow, Jellyfin-side comparison) -------
    files = library.list_audio_files()
    sig = library.signature_of(files)
    owned = library.cached_keys(sig)
    if owned is None:
        owned = set()
        total = len(files)
        yield {"stage": "library", "message": f"Bibliothek scannen … 0/{total}",
               "done": 0, "total": total, "pct": 10}
        for i, p in enumerate(files, 1):
            if is_canceled():
                return
            artist, title = library.tags(p)
            if title:
                owned.add(track_key(artist, title))
            if i % 200 == 0 or i == total:
                yield {"stage": "library", "message": f"Bibliothek scannen … {i}/{total}",
                       "done": i, "total": total, "pct": 10 + int(20 * i / max(total, 1))}
        library.set_cache(sig, owned, total)
    else:
        library.set_cache(sig, owned, len(files))
        yield {"stage": "library", "message": f"Bibliothek gecacht ({len(files)} Tracks)",
               "pct": 30}

    # --- diff -----------------------------------------------------------------
    missing = [p for p in plays.values()
               if track_key(p["artist"], p["title"]) not in owned]
    owned_matches = len(plays) - len(missing)
    missing.sort(key=lambda p: p["count"], reverse=True)
    yield {"stage": "match", "message": f"{owned_matches} vorhanden · {len(missing)} fehlen",
           "pct": 32}

    # --- album resolution (network, cached; the longest phase) ----------------
    cache = _load_cache()
    resolved = 0
    total_m = len(missing)
    for i, p in enumerate(missing, 1):
        if is_canceled():
            return
        vid = p["videoId"]
        if not resolve or not vid:
            p["album"], p["album_artist"], p["resolved"] = None, p["artist"], False
        else:
            if vid in cache:
                album, art = cache[vid].get("album"), cache[vid].get("artist")
            elif (i - 1) < cap:
                album, art = _lookup_album(vid)
                cache[vid] = {"album": album, "artist": art}
            else:
                album, art = None, None  # over the cap — stays unresolved, not dropped
            if album:
                resolved += 1
            p["album"] = album
            p["album_artist"] = art or p["artist"]
            p["resolved"] = bool(album)
        if i % 10 == 0 or i == total_m:
            yield {"stage": "resolve", "message": f"Alben auflösen … {i}/{total_m}",
                   "done": i, "total": total_m, "pct": 32 + int(60 * i / max(total_m, 1))}
    if resolve:
        _save_cache(cache)

    result = {
        "type": "music",
        "library_size": library.library_size(),
        "history_plays": total_plays,
        "unique_tracks": len(plays),
        "owned_matches": owned_matches,
        "missing_tracks": len(missing),
        "resolved_tracks": resolved,
        "unresolved_tracks": len(missing) - resolved,
        "resolve_cap": cap if (resolve and len(missing) > cap) else None,
        "albums": _group_albums(missing),
    }
    yield {"stage": "done", "message": "fertig", "pct": 100, "result": result}


def analyze(history_bytes: bytes, **opts) -> dict:
    """Non-streaming convenience wrapper (used by tests)."""
    result: dict = {}
    for ev in analyze_iter(history_bytes, **opts):
        if "result" in ev:
            result = ev["result"]
    return result


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
