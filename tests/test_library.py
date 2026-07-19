from app import library
from app.textnorm import track_key


def test_owned_keys_from_path_fallback(music_dir):
    music_dir.add("Taylor Swift", "Midnights", "Anti-Hero")
    keys = library.owned_keys()
    assert track_key("Taylor Swift", "Anti-Hero") in keys
    assert library.library_size() == 1


def test_cache_reused_when_unchanged(music_dir):
    music_dir.add("A", "B", "C")
    first = library.owned_keys()
    sig = library.signature_of(library.list_audio_files())
    assert library.cached_keys(sig) is first  # same object → cache hit


def test_track_number_prefix_stripped(music_dir):
    music_dir.add("Band", "Album", "03 - Real Title")
    keys = library.owned_keys()
    assert track_key("Band", "Real Title") in keys


def test_empty_library(music_dir):
    assert library.owned_keys() == set()
