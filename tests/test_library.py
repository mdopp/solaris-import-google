from app import library
from app.textnorm import track_key


def test_owned_and_owns(music_dir):
    music_dir.add("Taylor Swift", "Midnights", "Anti-Hero")
    keys, by = library.owned_index()
    assert track_key("Taylor Swift", "Anti-Hero") in keys
    assert library.owns(keys, by, "Taylor Swift", "Anti-Hero") is True
    assert library.library_size() == 1


def test_owns_fuzzy_matches_tag_typo(music_dir):
    music_dir.add("Jamiroquai", "Synkronized", "Failling")  # real-world library typo
    keys, by = library.owned_index()
    assert library.owns(keys, by, "Jamiroquai", "Falling") is True
    assert library.owns(keys, by, "Jamiroquai", "Totally Other Song") is False


def test_owns_ignores_the_prefix(music_dir):
    music_dir.add("Smashing Pumpkins", "Adore", "Ava Adore")
    keys, by = library.owned_index()
    assert library.owns(keys, by, "The Smashing Pumpkins", "Ava Adore") is True


def test_owns_compilation_artist_in_title():
    # Bravo-Hits style: artist tag is the compilation, real artist is in the title.
    keys, by = set(), {}
    library.add_owned(keys, by, "Bravo Hits 28", "Dr. Ring-Ding - Ring Of Fire")
    assert library.owns(keys, by, "Dr. Ring-Ding", "Ring Of Fire") is True


def test_track_number_prefix_stripped(music_dir):
    music_dir.add("Band", "Album", "03 - Real Title")
    keys, _by = library.owned_index()
    assert track_key("Band", "Real Title") in keys


def test_cache_reused_when_unchanged(music_dir):
    music_dir.add("A", "B", "C")
    library.owned_keys()
    sig = library.signature_of(library.list_audio_files())
    assert library.cached_index(sig) is not None


def test_empty_library(music_dir):
    assert library.owned_keys() == set()
