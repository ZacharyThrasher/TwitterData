import csv
import json
import re
import shutil
import subprocess

import pytest

from blindcode.cli import main
from blindcode.hatecheck import load_cases
from blindcode.items import Item, load_items
from blindcode.sample import draw_sample
from blindcode.store import CoderStore, import_csv
from blindcode.webpage import build_page

from .conftest import full_values

ITEMS = [Item(f"u{i}", f"text {i}", "parent") for i in range(200)]


def test_sample_oversamples_flagged_items():
    pre = {f"u{i}": {"hate_speech": "1"} for i in range(0, 200, 20)}  # 10 flagged
    out, rep = draw_sample(ITEMS, 30, seed=1, prelabels=pre, fields=["hate_speech"], min_per_field=8)
    uids = {it.uid for it in out}
    assert len(out) == 30 and len(uids) == 30
    assert rep["hate_speech"] == {"flagged": 10, "taken": 8}
    assert sum(u in pre for u in uids) >= 8
    assert draw_sample(ITEMS, 30, seed=1)[0] == draw_sample(ITEMS, 30, seed=1)[0]


def test_sample_excludes_and_checks_size():
    out, _ = draw_sample(ITEMS, 150, exclude={f"u{i}" for i in range(50)})
    assert not any(int(it.uid[1:]) < 50 for it in out)
    with pytest.raises(ValueError):
        draw_sample(ITEMS, 151, exclude={f"u{i}" for i in range(50)})


def _page_data(html):
    m = re.search(r"const DATA = (.*?);\nconst CB", html, re.S)
    return json.loads(m.group(1).replace("<\\/", "</").replace("<\\!--", "<!--"))


def test_page_is_blind_and_script_safe(codebook):
    items = [Item("u1", "hello </script><script>alert(1)</script> <!-- x", "child"), Item("u2", "two", "parent")]
    html = build_page(items, codebook, "vol1")
    assert html.count("</script>") == 1  # only the real closing tag
    data = _page_data(html)
    assert data["items"][0].keys() == {"uid", "text", "context"}
    assert {i["text"] for i in data["items"]} == {it.text for it in items}
    assert data["codebook"]["sha256"] == codebook.sha256
    with pytest.raises(ValueError):
        build_page(items, codebook, "../x")


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_page_script_parses(codebook, tmp_path):
    html = build_page(ITEMS[:3], codebook, "vol1")
    script = html.split("<script>")[1].split("</script>")[0]
    js = tmp_path / "page.js"
    js.write_text(script)
    assert subprocess.run(["node", "--check", str(js)], capture_output=True).returncode == 0


def test_page_csv_roundtrip_and_version_check(tmp_path, codebook):
    # The page's CSV: uid, codebook fields, codebook_sha256
    p = tmp_path / "codes_vol1.csv"
    with open(p, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["uid"] + codebook.names + ["codebook_sha256"])
        w.writeheader()
        w.writerow({"uid": "u1", **full_values(threat="1"), "codebook_sha256": codebook.sha256})
    assert import_csv(p, tmp_path / "s", "vol1", codebook) == 1
    assert CoderStore(tmp_path / "s", "vol1").latest()["u1"]["values"]["threat"] == "1"
    bad = tmp_path / "bad.csv"
    bad.write_text(p.read_text().replace(codebook.sha256, "f" * 64))
    with pytest.raises(ValueError, match="different codebook"):
        import_csv(bad, tmp_path / "s", "vol2", codebook)


def test_hatecheck_flow(tmp_path, capsys):
    cases = tmp_path / "hc.csv"
    with open(cases, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["", "functionality", "case_id", "test_case", "label_gold"])
        w.writerow([0, "derog_neg_emote_h", 1, "I hate women.", "hateful"])
        w.writerow([1, "derog_neg_emote_h", 2, "I hate trans people.", "hateful"])
        w.writerow([2, "counter_quote_nh", 3, "Saying 'I hate women' is wrong, idiot.", "non-hateful"])
        w.writerow([3, "counter_quote_nh", 4, "You should not say that.", "non-hateful"])
    items, gold, func = load_cases(cases, limit_per_functionality=1)
    assert len(items) == 2 and gold == {"hc_1": "1", "hc_3": "0"}
    out = tmp_path / "hc.md"
    assert main(["hatecheck", str(cases), "--backend", "keyword", "--store", str(tmp_path / "s"), "--out", str(out)]) == 0
    text = out.read_text()
    assert "Cases scored: 4 of 4" in text and "| derog_neg_emote_h | hateful | 2 | 0.00 |" in text


def test_cli_page_and_sample(tmp_path, source_csv, capsys):
    items = tmp_path / "items.csv"
    main(["build-items", str(source_csv), str(items)])
    assert main(["sample", str(items), str(tmp_path / "s.csv"), "--n", "2", "--enrich-fields", ""]) == 0
    assert len(load_items(tmp_path / "s.csv")) == 2
    assert main(["page", str(items), "--coder", "vol1", "--out", str(tmp_path / "vol1.html")]) == 0
    assert "Reply coding: vol1" in (tmp_path / "vol1.html").read_text()


def test_cli_default_backend_is_free_local(tmp_path, source_csv, capsys):
    items = tmp_path / "items.csv"
    main(["build-items", str(source_csv), str(items)])
    rc = main(["ai-code", str(items), "--store", str(tmp_path / "s"), "--ollama-url", "http://127.0.0.1:9"])
    assert rc == 2 and "ollama serve" in capsys.readouterr().err


def test_paid_backend_without_env_is_a_clean_error(tmp_path, source_csv, capsys, monkeypatch):
    monkeypatch.delenv("BLINDCODE_ALLOW_PAID", raising=False)
    items = tmp_path / "items.csv"
    main(["build-items", str(source_csv), str(items)])
    rc = main(["ai-code", str(items), "--backend", "anthropic", "--allow-paid", "--store", str(tmp_path / "s")])
    assert rc == 2 and "BLINDCODE_ALLOW_PAID" in capsys.readouterr().err


def test_hatecheck_default_store_is_separate(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cases = tmp_path / "hc.csv"
    cases.write_text("functionality,case_id,test_case,label_gold\nx_h,1,I hate them.,hateful\n")
    main(["hatecheck", str(cases), "--backend", "keyword"])
    assert (tmp_path / "work" / "hatecheck").is_dir() and not (tmp_path / "work" / "coders").exists()
