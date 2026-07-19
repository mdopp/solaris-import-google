import json
from datetime import datetime, timezone

from app import config
from app import music_shopping as m


def _entry(title, artist, vid, time="2026-07-15T10:00:00.000Z", topic=True):
    name = f"{artist} - Topic" if topic else artist
    return {
        "header": "YouTube Music",
        "title": title + " angesehen",
        "titleUrl": f"https://music.youtube.com/watch?v={vid}",
        "subtitles": [{"name": name}],
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


def _seed_cache(mapping):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    (config.DATA_DIR / "ytmusic_album_cache.json").write_text(json.dumps(mapping))


def test_aggregate_filters_nonmusic_and_counts():
    plays = m.aggregate_plays(HIST)
    assert len(plays) == 4
    ah = next(p for p in plays.values() if p["title"] == "Anti-Hero")
    assert ah["count"] == 2 and ah["topic"] is True


def test_since_drops_old_plays():
    since = datetime(2020, 1, 1, tzinfo=timezone.utc)
    titles = {p["title"] for p in m.aggregate_plays(HIST, since=since).values()}
    assert "Old Track" not in titles and "Anti-Hero" in titles


def _songs(res):
    return {s["title"] for g in res["groups"] for s in g["songs"]}


def test_owned_excluded_from_missing(music_dir):
    music_dir.add("Taylor Swift", "Midnights", "Anti-Hero")
    res = m.analyze(HIST)
    assert "Anti-Hero" not in _songs(res)
    assert res["owned_matches"] >= 1


def test_min_plays_filter(music_dir):
    assert m.analyze(HIST, min_plays=2)["unique_tracks"] == 1


def test_resolve_off_groups_by_artist(music_dir):
    res = m.analyze(HIST, resolve=False)
    assert all(g["album"] == m.UNRESOLVED_LABEL for g in res["groups"])
    assert res["resolved_tracks"] == 0


def test_resolve_uses_cache_no_network(music_dir):
    _seed_cache({"vidX": {"album": "Album A", "artist": "Artist A"}})
    res = m.analyze(HIST, resolve=True, cap=0)
    assert "Album A" in {g["album"] for g in res["groups"]}
    assert res["resolved_tracks"] >= 1


def test_set_cover_minimises_albums(music_dir):
    hist = json.dumps([
        _entry("Dup Song", "Art", "vd1"),   # appears on AlbumX ...
        _entry("Dup Song", "Art", "vd2"),   # ... and on AlbumY
        _entry("Solo Song", "Art", "vd3"),  # only on AlbumX
    ]).encode()
    _seed_cache({
        "vd1": {"album": "AlbumX", "artist": "Art"},
        "vd2": {"album": "AlbumY", "artist": "Art"},
        "vd3": {"album": "AlbumX", "artist": "Art"},
    })
    res = m.analyze(hist, resolve=True, cap=0)
    # AlbumX covers both songs, so AlbumY is dropped — fewest albums to buy.
    assert {g["album"] for g in res["groups"]} == {"AlbumX"}
    x = next(g for g in res["groups"] if g["album"] == "AlbumX")
    assert len(x["songs"]) == 2


def test_categories_topic_vs_other(music_dir):
    hist = json.dumps([
        _entry("Music Song", "Bandy", "m1"),                  # "- Topic" → Musik
        _entry("Pod Ep", "Some Show", "p1", topic=False),     # not Topic → Sonstiges
    ]).encode()
    res = m.analyze(hist, resolve=False)
    cats = {g["category"] for g in res["groups"]}
    assert "Musik" in cats and "Sonstiges" in cats
    assert set(res["categories"]) >= {"Musik", "Sonstiges"}


def test_exports(music_dir):
    res = m.analyze(HIST, resolve=False)
    assert m.to_csv(res["groups"]).startswith("Kategorie,Artist,Album,Song,Abspielungen")
    md = m.to_markdown(res["groups"])
    assert md.startswith("# Musik-Einkaufsliste") and "### " in md


def test_progress_events(music_dir):
    evs = list(m.analyze_iter(HIST, resolve=False))
    assert {"parse", "match", "done"} <= {e["stage"] for e in evs}
    assert evs[-1]["pct"] == 100 and "result" in evs[-1]
