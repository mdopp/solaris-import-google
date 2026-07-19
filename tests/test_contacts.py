from app import identity
from app.importers import contacts as con

VCF = b"""BEGIN:VCARD
VERSION:3.0
FN:Max Mustermann
EMAIL:max@example.com
END:VCARD
BEGIN:VCARD
VERSION:3.0
FN:Erika Mueller
UID:erika-123
END:VCARD
"""


def test_preview():
    p = con.preview("c.vcf", VCF)
    assert p["cards"] == 2
    assert "Max Mustermann" in p["samples"]


def test_import_writes_two_cards_and_props():
    rep = con.do_import("conu1", "c.vcf", VCF)
    assert rep["written"] == 2
    cdir = identity.radicale_user_root("conu1") / "contacts"
    assert len(list(cdir.glob("*.vcf"))) == 2
    import json
    assert json.loads((cdir / ".Radicale.props").read_text())["tag"] == "VADDRESSBOOK"


def test_generated_uid_for_card_without_one():
    con.do_import("conu2", "c.vcf", VCF)
    cdir = identity.radicale_user_root("conu2") / "contacts"
    # the card with an explicit UID keeps it
    assert (cdir / "erika-123.vcf").exists()
