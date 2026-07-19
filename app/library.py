"""Scan the existing on-disk music library so we know what the user already
owns — no Jellyfin login needed (Jellyfin mounts the very same tree read-only).

Builds a set of normalized ``(artist, title)`` keys from audio tags, falling
back to the ``Artist/Album/Track`` folder layout when a file is untagged. The
result is cached in-process and invalidated when the library's file count or
newest mtime changes.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import config
from .textnorm import track_key

_AUDIO_EXTS = {
    ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus",
    ".wav", ".wma", ".aiff", ".alac", ".mp4",
}

_cache: dict = {"sig": None, "keys": set(), "count": 0}


def _signature(root: Path) -> tuple[int, float]:
    count = 0
    newest = 0.0
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if os.path.splitext(f)[1].lower() in _AUDIO_EXTS:
                count += 1
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(dirpath, f)))
                except OSError:
                    pass
    return count, newest


def _tags(path: Path) -> tuple[str, str]:
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
    # Fallback: <library>/<artist>/<album>/<track>.<ext>
    parts = path.relative_to(config.MUSIC_DIR).parts
    artist = parts[0] if len(parts) >= 2 else ""
    title = os.path.splitext(path.name)[0]
    # Strip a leading track number like "03 - " or "03 ".
    for sep in (" - ", " "):
        if title[:2].isdigit() and sep in title:
            title = title.split(sep, 1)[1]
            break
    return artist, title


def owned_keys() -> set[str]:
    """Set of normalized track keys currently in the library (cached)."""
    root = config.MUSIC_DIR
    if not root.exists():
        return set()
    sig = _signature(root)
    if _cache["sig"] == sig:
        return _cache["keys"]

    keys: set[str] = set()
    count = 0
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if os.path.splitext(f)[1].lower() not in _AUDIO_EXTS:
                continue
            count += 1
            artist, title = _tags(Path(dirpath) / f)
            if title:
                keys.add(track_key(artist, title))

    _cache.update({"sig": sig, "keys": keys, "count": count})
    return keys


def library_size() -> int:
    owned_keys()
    return _cache["count"]
