# Google-Import

Web-App unter `import.<PUBLIC_DOMAIN>`, die nach der Authelia-SSO-Anmeldung Daten
aus einem **Google-Takeout-Export** in die selbstgehosteten Dienste übernimmt —
immer für den **eingeloggten Benutzer** (`Remote-User`), nie einen festen Account.

Version 1 deckt ab:

- **Kalender** (`Calendar/*.ics`) → Radicale-Kalender des Users (`caldav.<domain>`).
- **Kontakte** (`Contacts/*.vcf`) → Radicale-Adressbuch (`<user>/contacts`).
- **Google Keep** (Ordner als `.zip` oder einzelne `.json`) → Obsidian-Notiz-Vault
  unter `notes/users/<user>/Google Keep/` (Anhänge inklusive).
- **Musik-Einkaufsliste**: aus `history/watch-history.json` (YouTube Music) wird
  gegen die vorhandene Jellyfin-Musikbibliothek abgeglichen und eine nach
  Häufigkeit sortierte Liste **fehlender Alben** erzeugt (CSV/Markdown-Export).

Kalender, Kontakte und Notizen werden direkt ins Dateisystem der jeweiligen
User-Ablage geschrieben (Radicale `owner_only` lässt keinen Admin-DAV-Override zu).
Die Musikbibliothek wird read-only vom selben Dateibaum gelesen, den Jellyfin als
`/media` mountet — kein Jellyfin-Login nötig.

Image: `ghcr.io/mdopp/solaris-import-google:latest` (Quelle: `mdopp/solaris-import-google`).

## Voraussetzungen / Abhängigkeiten

`nginx`, `auth`, `radicale`, `file-share` müssen installiert sein — deren
Datenverzeichnisse sind die Schreib-/Lese-Ziele.
