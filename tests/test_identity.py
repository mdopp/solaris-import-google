import pytest

from app import config, identity


def test_resolve_valid():
    assert identity.resolve_user({"Remote-User": "mdopp"}) == "mdopp"


def test_resolve_invalid_chars():
    with pytest.raises(identity.IdentityError):
        identity.resolve_user({"Remote-User": "bad user!"})


def test_resolve_missing_uses_fallback(monkeypatch):
    monkeypatch.setattr(config, "REQUIRE_REMOTE_USER", False)
    monkeypatch.setattr(config, "DEV_FALLBACK_USER", "fallbackuser")
    assert identity.resolve_user({}) == "fallbackuser"


def test_resolve_missing_required_raises(monkeypatch):
    monkeypatch.setattr(config, "REQUIRE_REMOTE_USER", True)
    monkeypatch.setattr(config, "DEV_FALLBACK_USER", "")
    with pytest.raises(identity.IdentityError):
        identity.resolve_user({})


def test_target_paths():
    assert identity.radicale_user_root("mdopp").name == "mdopp"
    assert identity.notes_user_dir("mdopp").parent.name == "users"
    assert identity.keep_target_dir("mdopp").name == config.KEEP_SUBDIR
