"""Resolve the acting user from the Authelia forward-auth header and map that
user to the on-disk locations we write into.

Everything this tool writes is scoped to the *currently logged-in* user — never
a fixed account. The user comes from the `Remote-User` header that Authelia
injects (see config.REMOTE_USER_HEADER); requests without it are rejected so a
direct LAN hit can't bypass SSO.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import config

# LLDAP uids are simple; allow letters, digits, dot, dash, underscore only.
_SAFE_USER = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class IdentityError(Exception):
    """Raised when no valid acting user can be determined."""


def resolve_user(headers) -> str:
    """Return the sanitized acting username from request headers.

    `headers` is anything supporting case-insensitive `.get()` (Starlette's
    Headers does). Falls back to DEV_FALLBACK_USER when the header is absent and
    REQUIRE_REMOTE_USER is off.
    """
    raw = headers.get(config.REMOTE_USER_HEADER) if headers is not None else None
    if not raw and not config.REQUIRE_REMOTE_USER:
        raw = config.DEV_FALLBACK_USER
    if not raw:
        raise IdentityError(
            f"Missing {config.REMOTE_USER_HEADER} header — not authenticated."
        )
    user = raw.strip()
    if not _SAFE_USER.match(user):
        raise IdentityError(f"Invalid username: {raw!r}")
    return user


def radicale_user_root(user: str) -> Path:
    """The user's Radicale principal collection dir (created on demand)."""
    return config.RADICALE_DATA / "collections" / "collection-root" / user


def notes_user_dir(user: str) -> Path:
    """The user's Obsidian note dir inside the file-share vault."""
    return config.NOTES_DIR / "users" / user


def keep_target_dir(user: str) -> Path:
    """Where Keep notes are written for this user."""
    return notes_user_dir(user) / config.KEEP_SUBDIR
