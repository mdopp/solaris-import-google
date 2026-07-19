"""Runtime configuration, all overridable via environment variables.

The defaults match the paths the ServiceBay template mounts into the container:

  host  /mnt/data/stacks/radicale/data       -> container /radicale
  host  /mnt/data/stacks/file-share/data     -> container /fileshare

For local development, point these at a scratch copy of the real trees, e.g.

  RADICALE_DATA=./testmounts/radicale/data \
  FILESHARE_DATA=./testmounts/file-share/data \
  uvicorn app.main:app --reload
"""

from __future__ import annotations

import os
from pathlib import Path

# Header Authelia injects with the authenticated username (LLDAP uid).
REMOTE_USER_HEADER = os.environ.get("REMOTE_USER_HEADER", "Remote-User")

# When true, a request without the Remote-User header is rejected (401). Set to
# false only for local development behind a simulated header.
REQUIRE_REMOTE_USER = os.environ.get("REQUIRE_REMOTE_USER", "true").lower() == "true"

# For local dev you can pin the acting user instead of sending a header.
DEV_FALLBACK_USER = os.environ.get("DEV_FALLBACK_USER", "").strip()

# Radicale multifilesystem storage root (the dir that contains `collections/`).
RADICALE_DATA = Path(os.environ.get("RADICALE_DATA", "/radicale"))

# file-share data tree — holds both the Obsidian notes vault and the music lib.
FILESHARE_DATA = Path(os.environ.get("FILESHARE_DATA", "/fileshare"))

# Where per-user Obsidian notes live inside the file-share tree.
NOTES_DIR = Path(os.environ.get("NOTES_DIR", str(FILESHARE_DATA / "notes")))

# The existing music library scanned to know what the user already owns.
MUSIC_DIR = Path(os.environ.get("MUSIC_DIR", str(FILESHARE_DATA / "music")))

# Also scanned for ownership so owned audiobooks/Hörspiele aren't shown as
# missing. (Podcasts are intentionally NOT scanned.)
AUDIOBOOKS_DIR = Path(os.environ.get("AUDIOBOOKS_DIR", str(FILESHARE_DATA / "audiobooks")))

# Writable scratch dir for caches (ytmusicapi album cache, uploads staging).
DATA_DIR = Path(os.environ.get("IMPORT_DATA_DIR", "/data"))

# Subfolder under a user's note dir where Keep notes land.
KEEP_SUBDIR = os.environ.get("KEEP_SUBDIR", "Google Keep")
