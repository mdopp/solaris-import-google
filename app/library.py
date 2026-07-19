"""Scan the existing on-disk music library so we know what the user already
owns — no Jellyfin login needed (Jellyfin mounts the very same tree read-only).

Builds, from audio tags (falling back to the ``Artist/Album/Track`` folder
layout), two structures used to decide ownership:
- an exact set of normalized ``(artist, title)`` keys, and
- a per-artist index of owned titles for **fuzzy** matching, because real
  libraries are full of tag typos ("Failling", "Music Of The Wind") and
  "The …" prefix differences that an exact match would miss.
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path

from . import config
from .textnorm import normalize, track_key

_AUDIO_EXTS = {
    ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus",
    ".wav", ".wma", ".aiff", ".alac", ".mp4",
}

# Similarity at/above which two same-artist titles are treated as the same song.
_FUZZY = 0.86
# Don't fuzzy-scan pathologically large artist buckets (e.g. untagged blobs).
_FUZZY_MAX = 400

_cache: dict = {"sig": None, "keys": set(), "by_artist": {}, "count": 0}


def list_audio_files() -> list[Path]:
    root = config.MUSIC_DIR
    if not root.exists():
        return []
    out: list[Path] = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if os.path.splitext(f)[1].lower() in _AUDIO_EXTS:
                out.append(Path(dirpath) / f)
    return out


def signature_of(files: list[Path]) -> tuple[int, float]:
    newest = 0.0
    for p in files:
        try:
            newest = max(newest, p.stat().st_mtime)
        except OSError:
            pass
    return len(files), newest


def artist_bucket(artist: str) -> str:
    """Normalized artist with a leading 'the ' dropped, so 'The Smashing
    Pumpkins' and 'Smashing Pumpkins' land in the same bucket."""
    a = normalize(artist)
    return a[4:] if a.startswith("the ") else a


def tags(path: Path) -> tuple[str, str]:
    """Return (artist, title) from tags, or from the path as a fallback."""
    try:
        import mutagen

        audio = mutagen.File(str(path), easy=True)
        if audio and audio.tags:
            artist = (audio.tags.get("artist") or audio.tags.get("albumartist") or [""])[0]
            title = (audio.tags.get("title") or [""])[0]
            if artist and title:
                return artist, title
    except Exception:
        pass
    try:
        parts = path.relative_to(config.MUSIC_DIR).parts
    except ValueError:
        parts = path.parts
    artist = parts[0] if len(parts) >= 2 else ""
    title = os.path.splitext(path.name)[0]
    for sep in (" - ", " "):
        if title[:2].isdigit() and sep in title:
            title = title.split(sep, 1)[1]
            break
    return artist, title


def add_owned(keys: set, by_artist: dict, artist: str, title: str) -> None:
    """Record one owned track into the exact-key set and the fuzzy index."""
    if not title:
        return
    keys.add(track_key(artist, title))
    by_artist.setdefault(artist_bucket(artist), set()).add(normalize(title))


def owns(keys: set, by_artist: dict, artist: str, title: str) -> bool:
    """True if the library already has this track — exact, or a same-artist
    title that's a near-match (catches tag typos and 'The' prefix diffs)."""
    if track_key(artist, title) in keys:
        return True
    titles = by_artist.get(artist_bucket(artist))
    if not titles:
        return False
    tn = normalize(title)
    if tn in titles:
        return True
    if len(titles) > _FUZZY_MAX:
        return False
    return any(difflib.SequenceMatcher(None, tn, ot).ratio() >= _FUZZY for ot in titles)


def cached_index(sig: tuple[int, float]):
    if _cache["sig"] == sig:
        return _cache["keys"], _cache["by_artist"]
    return None


def set_cache(sig, keys: set, by_artist: dict, count: int) -> None:
    _cache.update(sig=sig, keys=keys, by_artist=by_artist, count=count)


def owned_keys() -> set:
    """Exact owned-key set (also (re)builds the fuzzy index). Used by tests."""
    files = list_audio_files()
    sig = signature_of(files)
    if _cache["sig"] == sig:
        return _cache["keys"]
    keys: set = set()
    by_artist: dict = {}
    for p in files:
        a, t = tags(p)
        add_owned(keys, by_artist, a, t)
    set_cache(sig, keys, by_artist, len(files))
    return keys


def owned_index():
    owned_keys()
    return _cache["keys"], _cache["by_artist"]


def library_size() -> int:
    return _cache.get("count", 0)
