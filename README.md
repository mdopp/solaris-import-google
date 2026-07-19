# solaris-import-google

Web-Tool, das die wichtigsten Daten aus einem **Google-Takeout-Export** in die
selbstgehosteten ServiceBay-Dienste übernimmt — immer für den **aktuell via
Authelia angemeldeten Benutzer** (`Remote-User`), nie einen festen Account.

## Umfang (V1)

| Google Takeout | Ziel | Weg |
| --- | --- | --- |
| `Calendar/*.ics` | Radicale-Kalender des Users | Dateisystem (`collection-root/<user>/`) |
| `Contacts/*.vcf` | Radicale-Adressbuch (`<user>/contacts`) | Dateisystem |
| `Keep/*.json` (+ Anhänge, oder ganzer Ordner als `.zip`) | Obsidian-Vault `notes/users/<user>/Google Keep/` | Dateisystem |
| `history/watch-history.json` (YouTube Music) | **Einkaufsliste fehlender Alben** (CSV/MD) | Bibliotheks-Abgleich + Export |

Bewusst **nicht** in V1: Jellyfin-Playlists anlegen (braucht Jellyfin-Write),
Gmail, Fotos, Drive.

## Warum kein Passwort / kein API-Key

- **Radicale & Notizen**: Radicale läuft mit `rights = owner_only`, d. h. es gibt
  keinen Admin-DAV-Weg in fremde Collections. SSO liefert die Identität, aber kein
  Backend-Passwort — also schreiben wir direkt in den Dateisystem-Pfad des
  `Remote-User`.
- **Musik**: die vorhandene Bibliothek wird read-only vom selben Baum gelesen, den
  Jellyfin als `/media` mountet (`file-share/data/music`) — kein Jellyfin-Login.
- **Album-Auflösung**: exakt über die YouTube-Music-`videoId` aus der Historie via
  `ytmusicapi` (gecacht), nicht über einen Fuzzy-Match.

## Projektstruktur

```
app/
  config.py            # Env-Pfade (RADICALE_DATA, FILESHARE_DATA, …)
  identity.py          # Remote-User → Zielpfade
  radicale_store.py    # On-Disk-Write in Radicale (Lock + .Radicale.props)
  importers/
    calendar.py        # ICS → je UID ein VCALENDAR-Item
    contacts.py        # vCard-Split → CardDAV-Adressbuch
    keep.py            # Keep-JSON → Obsidian-Markdown + Anhänge
  library.py           # Musik-Scan (mutagen) → owned keys
  music_shopping.py    # Historie → fehlende Alben (ytmusicapi) → CSV/MD
  textnorm.py          # Normalisierung fürs Matching
  jobs.py              # Durable Job-Runner (langlaufende Analyse, reload-fest)
  main.py              # FastAPI-Routen
  static/index.html    # Web-UI
tests/                 # pytest-Suite (Unit + API via TestClient)
Dockerfile
deploy/servicebay-template/solaris-import-google/   # ServiceBay-Local-Template
```

## Lokal entwickeln

```bash
pip install -r requirements-dev.txt

# Auf eine (Test-)Kopie der echten Datenbäume zeigen und den User simulieren:
export RADICALE_DATA=./testmounts/radicale/data
export FILESHARE_DATA=./testmounts/file-share/data
export IMPORT_DATA_DIR=./testmounts/data
export REQUIRE_REMOTE_USER=false
export DEV_FALLBACK_USER=mdopp

uvicorn app.main:app --reload --port 8097
# UI: http://localhost:8097  (Header 'Remote-User: mdopp' wird via DEV_FALLBACK_USER simuliert)
```

## Tests

```bash
pytest --cov=app --cov-report=term-missing --cov-fail-under=85
```

Die CI (`publish.yml`) führt diese Suite als **Gate** aus: das Image wird nur
gebaut/gepusht, wenn die Tests grün sind und die Coverage ≥ 85 % liegt
(`build-and-push` → `needs: test`). Aktuell ~90 % über `app/`.

## Deployment (ServiceBay)

1. Image bauen/pushen (GitHub Actions `publish.yml` → `ghcr.io/mdopp/solaris-import-google:latest`).
2. Template unter `deploy/servicebay-template/solaris-import-google/` als lokales
   ServiceBay-Template registrieren und via `install_template` (Quelle `Local`)
   deployen. Es erscheint unter `import.<PUBLIC_DOMAIN>` hinter Authelia.

Abhängigkeiten: `nginx`, `auth`, `radicale`, `file-share`.
