import csv
import json

import pytest

from blindcode.codebook import Codebook, CodebookError
from blindcode.items import BLIND_COLUMNS, build_items, coder_order, load_items, strip_leading_mentions
from blindcode.store import CoderStore, check_coder_id, import_csv, list_coders

from .conftest import full_values


def test_blind_file_has_only_whitelisted_columns(source_csv, tmp_path):
    out = tmp_path / "items.csv"
    items, warnings = build_items(source_csv, out)
    with open(out, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        assert tuple(next(reader)) == BLIND_COLUMNS
        body = fh.read()
    for leaked in ("alice", "True", "37704", "is_blue_verified", "AutisticClip", "DirtbagLeft1234"):
        assert leaked not in body
    assert [i.text for i in items] == ["money cant buy everything", "you are an idiot", "ask @bob about it"]
    assert warnings == ["child_2: text mentions its own author's handle"]


def test_keep_mentions(source_csv, tmp_path):
    items, _ = build_items(source_csv, tmp_path / "i.csv", keep_mentions=True)
    assert items[0].text.startswith("@AutisticClip")


def test_strip_only_leading_mentions():
    assert strip_leading_mentions("@a @b_c hi @d") == "hi @d"
    assert strip_leading_mentions("no mentions") == "no mentions"


def test_load_items_refuses_non_blind_file(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("uid,text,context,is_blue_verified\nx,hi,parent,True\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not blind"):
        load_items(p)


def test_duplicate_uid_rejected(tmp_path):
    p = tmp_path / "dup.csv"
    p.write_text("uid,full_text,thread\nx,a,parent\nx,b,parent\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        build_items(p, tmp_path / "o.csv", author_col=None)


def test_coder_order_is_stable_and_per_coder(source_csv, tmp_path):
    items, _ = build_items(source_csv, tmp_path / "i.csv")
    many = items * 10
    assert coder_order(many, "A") == coder_order(many, "A")
    assert [i.uid for i in coder_order(items, "A")] != [i.uid for i in coder_order(items, "zz")] or len(items) < 3


def test_codebook_loads_and_validates(codebook):
    assert codebook.names[0] == "stance" and len(codebook.sha256) == 64
    assert "argument_tag" not in [f.name for f in codebook.key_fields]
    v = codebook.validate(full_values(incivility="yes", slur=True, note=" " + "w " * 30))
    assert v["incivility"] == "1" and v["slur"] == "1" and len(v["note"].split()) == 15
    with pytest.raises(CodebookError):
        codebook.validate(full_values(stance="angry"))
    with pytest.raises(CodebookError):
        codebook.validate({"stance": "pro_stunt"})
    with pytest.raises(CodebookError):
        codebook.validate(full_values(handle="x"))


def test_codebook_rejects_bad_files(tmp_path):
    p = tmp_path / "cb.json"
    p.write_text(json.dumps({"id": "x", "fields": [{"name": "a", "type": "categorical", "definition": "d"}]}))
    with pytest.raises(CodebookError):
        Codebook.load(p)


def test_store_latest_wins_and_is_per_coder(tmp_path, codebook):
    a, b = CoderStore(tmp_path, "A"), CoderStore(tmp_path, "B")
    a.save("u1", full_values(), codebook)
    a.save("u1", full_values(incivility="1"), codebook)
    b.save("u1", full_values(), codebook)
    assert a.latest()["u1"]["values"]["incivility"] == "1"
    assert len(a.records()) == 2  # append-only audit trail
    assert b.latest()["u1"]["values"]["incivility"] == "0"
    assert list_coders(tmp_path) == ["A", "B"]
    rec = a.latest()["u1"]
    assert rec["codebook_sha256"] == codebook.sha256 and rec["kind"] == "human"


def test_store_rejects_bad_coder_ids():
    for bad in ("", "../x", "a/b", ".hidden", "x" * 65):
        with pytest.raises(ValueError):
            check_coder_id(bad)


def test_import_export_roundtrip(tmp_path, codebook):
    src = tmp_path / "coded.csv"
    with open(src, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["uid"] + codebook.names)
        w.writeheader()
        w.writerow({"uid": "u1", **full_values(slur="1")})
    assert import_csv(src, tmp_path / "s", "A", codebook) == 1
    out = tmp_path / "out.csv"
    CoderStore(tmp_path / "s", "A").export_csv(out, codebook)
    rows = list(csv.DictReader(open(out)))
    assert rows[0]["slur"] == "1" and rows[0]["uid"] == "u1"


def test_import_is_all_or_nothing(tmp_path, codebook):
    src = tmp_path / "coded.csv"
    with open(src, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["uid"] + codebook.names)
        w.writeheader()
        w.writerow({"uid": "u1", **full_values()})
        w.writerow({"uid": "u2", **full_values(threat="")})
    with pytest.raises(ValueError, match="line 3.*Nothing was imported"):
        import_csv(src, tmp_path / "s", "A", codebook)
    assert not (tmp_path / "s" / "A.jsonl").exists()
    assert import_csv(src, tmp_path / "s", "ai", codebook, kind="ai") == 2  # AI codes may be partial
