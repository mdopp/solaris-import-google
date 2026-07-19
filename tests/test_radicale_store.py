import json

from app import radicale_store as rs


def test_sanitize_name():
    assert rs.sanitize_name("A/B C") == "A-B-C"
    assert rs.sanitize_name("") == "item"
    assert rs.sanitize_name("  ..--") == "item"


def test_ensure_user_root_creates_props():
    root = rs.ensure_user_root("rsu1")
    assert (root / ".Radicale.props").exists()
    assert json.loads((root / ".Radicale.props").read_text()) == {}


def test_ensure_collection_tag_and_write():
    coll = rs.ensure_collection("rsu2", "Meine Kal", tag="VCALENDAR", displayname="Meine Kal")
    props = json.loads((coll / ".Radicale.props").read_text())
    assert props["tag"] == "VCALENDAR"
    assert props["D:displayname"] == "Meine Kal"
    href = rs.write_item(coll, "uid-1", "BODY", "ics")
    assert href == "uid-1.ics"
    assert (coll / href).read_text() == "BODY"


def test_addressbook_tag():
    coll = rs.ensure_collection("rsu3", "contacts", tag="VADDRESSBOOK")
    assert json.loads((coll / ".Radicale.props").read_text())["tag"] == "VADDRESSBOOK"


def test_storage_lock_enter_exit():
    with rs.storage_lock():
        pass
