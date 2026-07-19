import io
import json
import zipfile

from app import identity
from app.importers import keep

TEXT = json.dumps({
    "title": "Einkauf", "textContent": "Milch\nBrot", "isPinned": True,
    "labels": [{"name": "Haushalt"}],
    "createdTimestampUsec": 1590000000000000, "userEditedTimestampUsec": 1600000000000000,
}).encode()
LIST = json.dumps({
    "title": "Todo", "color": "RED",
    "listContent": [{"text": "A", "isChecked": False}, {"text": "B", "isChecked": True}],
    "createdTimestampUsec": 1591000000000000,
}).encode()
TRASH = json.dumps({"title": "Weg", "textContent": "x", "isTrashed": True,
                    "createdTimestampUsec": 1592000000000000}).encode()


def test_preview_skips_trashed():
    p = keep.preview([("a.json", TEXT), ("b.json", LIST), ("c.json", TRASH)])
    assert p["notes"] == 2
    assert p["trashed_skipped"] == 1


def test_import_markdown_frontmatter_and_checkboxes():
    rep = keep.do_import("keepu1", [("a.json", TEXT), ("b.json", LIST), ("c.json", TRASH)])
    assert rep["written"] == 2
    kdir = identity.keep_target_dir("keepu1")
    texts = [p.read_text() for p in kdir.glob("*.md")]
    joined = "\n".join(texts)
    assert 'tags: ["Haushalt"]' in joined
    assert "- [ ] A" in joined and "- [x] B" in joined
    assert "pinned: true" in joined


def test_zip_expands_and_copies_attachment():
    buf = io.BytesIO()
    note = json.dumps({
        "title": "Foto", "textContent": "hi", "createdTimestampUsec": 1593000000000000,
        "attachments": [{"filePath": "img.png", "mimetype": "image/png"}],
    })
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Takeout/Keep/foto.json", note)
        z.writestr("Takeout/Keep/img.png", b"PNGDATA")
    rep = keep.do_import("keepu2", [("keep.zip", buf.getvalue())])
    assert rep["written"] == 1
    assert rep["attachments_copied"] == 1
    kdir = identity.keep_target_dir("keepu2")
    assert (kdir / "attachments" / "img.png").read_bytes() == b"PNGDATA"
    assert "![[attachments/img.png]]" in "\n".join(p.read_text() for p in kdir.glob("*.md"))


def test_missing_attachment_reported():
    note = json.dumps({
        "title": "NoImg", "textContent": "hi", "createdTimestampUsec": 1594000000000000,
        "attachments": [{"filePath": "gone.jpg"}],
    }).encode()
    rep = keep.do_import("keepu3", [("n.json", note)])
    assert rep["attachments_missing"] == 1
