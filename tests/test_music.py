import json
from datetime import datetime, timezone

from app import config
from app import music_shopping as m


def _entry(title, artist, vid, time="2026-07-15T10:00:00.000Z", header="YouTube Music"):
    return {
        "header": header,
        "title": title + " angesehen",
        "titleUrl": f"https://music.youtube.com/watch?v={vid}",
        "subtitles": [{"name": artist + " - Topic"}],
        "time": time,
    }


HIST = json.dumps([
    _entry("Anti-Hero", "Taylor Swift", "a"),
    _entry("Anti-Hero", "Taylor Swift", "a", "2026-07-14T10:00:00.000Z"),
    _entry("Missing One", "Artist One", "vidX"),
    _entry("Missing Two", "Artist Two", "vidY"),
    {"header": "YouTube", "title": "Ad angesehen", "titleUrl": "https://www.youtube.com/watch?v=z"},
    _entry("Old Track", "Old Artist", "old", "2019-01-01T10:00:00.000Z"),
]).encode()


def test_aggregate_filters_nonmusic_and_counts():
    plays = m.aggregate_plays(HIST)
    assert len(plays) == 4  # non-music entry ignored, Anti-Hero deduped
    ah = next(p for p in plays.values() if p["title"] == "Anti-Hero")
    assert ah["count"] == 2 and ah["artist"] == "Taylor Swift"


def test_since_drops_old_plays():
    since = datetime(2020, 1, 1, tzinfo=timezone.utc)
    titles = {p["title"] for p in m.aggregate_plays(HIST, since=since).values()}
    assert "Old Track" not in titles and "Anti-Hero" in titles


def test_owned_excluded_from_missing(music_dir):
    music_dir.add("Taylor Swift", "Midnights", "Anti-Hero")
    res = m.analyze(HIST)
    titles = {t["title"] for a in res["albums"] for t in a["tracks"]}
    assert "Anti-Hero" not in titles
    assert res["owned_matches"] >= 1


def test_min_plays_filter(music_dir):
    res = m.analyze(HIST, min_plays=2)
    assert res["unique_tracks"] == 1  # only Anti-Hero played twice


def test_resolve_off_groups_by_artist(music_dir):
    res = m.analyze(HIST, resolve=False)
    assert res["resolved_tracks"] == 0
    assert all(a["album"] == m.UNRESOLVED_LABEL for a in res["albums"])


def test_resolve_uses_cache_no_network(music_dir):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    (config.DATA_DIR / "ytmusic_album_cache.json").write_text(
        json.dumps({"vidX": {"album": "Album A", "artist": "Artist A"}})
    )
    res = m.analyze(HIST, resolve=True, cap=0)
    assert "Album A" in {a["album"] for a in res["albums"]}
    assert res["resolved_tracks"] >= 1


def test_exports(music_dir):
    res = m.analyze(HIST, resolve=False)
    assert m.to_csv(res["albums"]).startswith("Album,Artist,")
    assert "| Album | Artist |" in m.to_markdown(res["albums"])


def test_progress_events(music_dir):
    evs = list(m.analyze_iter(HIST, resolve=False))
    assert {"parse", "match", "done"} <= {e["stage"] for e in evs}
    assert evs[-1]["pct"] == 100 and "result" in evs[-1]
