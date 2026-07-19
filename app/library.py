"""Scan the existing on-disk music library so we know what the user already
owns — no Jellyfin login needed (Jellyfin mounts the very same tree read-only).

Builds a set of normalized ``(artist, title)`` keys from audio tags, falling
back to the ``Artist/Album/Track`` folder layout when a file is untagged. The
result is cached in-process and invalidated when the library's file set changes.
Scanning thousands of files is slow, so the scan is driven file-by-file by the
caller (``music_shopping``) which reports progress.
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


def list_audio_files() -> list[Path]:
    """All audio files under the library root (one walk)."""
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
    """A cheap invalidation signature (file count + newest mtime)."""
    newest = 0.0
    for p in files:
        try:
            newest = max(newest, p.stat().st_mtime)
        except OSError:
            pass
    return len(files), newest


def cached_keys(sig: tuple[int, float]) -> set[str] | None:
    """Return the cached owned-key set if the signature still matches."""
    if _cache["sig"] == sig:
        return _cache["keys"]
    return None


def set_cache(sig: tuple[int, float], keys: set[str], count: int) -> None:
    _cache.update({"sig": sig, "keys": keys, "count": count})


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
    # Fallback: <library>/<artist>/<album>/<track>.<ext>
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


def owned_keys() -> set[str]:
    """Non-streaming convenience: full owned-key set (used by tests)."""
    files = list_audio_files()
    sig = signature_of(files)
    cached = cached_keys(sig)
    if cached is not None:
        return cached
    keys = {track_key(*tags(p)) for p in files if tags(p)[1]}
    set_cache(sig, keys, len(files))
    return keys


def library_size() -> int:
    return _cache.get("count", 0)
