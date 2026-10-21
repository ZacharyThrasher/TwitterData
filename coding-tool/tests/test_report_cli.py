import csv

from blindcode.cli import main
from blindcode.store import CoderStore

from .conftest import full_values


def seed(store, codebook, coder, flips=(), kind="human", n=40):
    s = CoderStore(store, coder)
    for i in range(n):
        uncivil = i % 3 == 0
        if i in flips:
            uncivil = not uncivil
        s.save(f"u{i}", full_values(incivility=int(uncivil), stance="pro_stunt" if i % 2 else "anti_stunt",
                                    slur=int(i % 5 == 0)), codebook, kind=kind)


def test_report_end_to_end(tmp_path, codebook, capsys):
    store = tmp_path / "s"
    seed(store, codebook, "A")
    seed(store, codebook, "B", flips={1})
    seed(store, codebook, "ai-good", kind="ai")
    seed(store, codebook, "ai-bad", flips=set(range(0, 40, 2)), kind="ai")
    groups = tmp_path / "g.csv"
    with open(groups, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["uid", "premium"])
        w.writerows([[f"u{i}", "yes" if i < 20 else "no"] for i in range(40)])
    out = tmp_path / "r.md"
    assert main(["report", "--store", str(store), "--n-boot", "50", "--groups", str(groups),
                 "--group-col", "premium", "--out", str(out)]) == 0
    text = out.read_text()
    assert "Human coders: A, B" in text and "AI coders: ai-bad, ai-good" in text
    assert "**AI `ai-good`: PASS**" in text
    assert "**AI `ai-bad`: FAIL**" in text
    assert "## 6. Bias check by premium" in text
    # threat never varies, so alpha is undefined and flagged
    assert "`threat`: every coder gave the same value" in text


def test_report_needs_two_humans(tmp_path, codebook, capsys):
    seed(tmp_path, codebook, "A")
    main(["report", "--store", str(tmp_path), "--n-boot", "0"])
    assert "at least two are needed" in capsys.readouterr().out


def test_cli_build_code_flow(source_csv, tmp_path, capsys):
    items = tmp_path / "items.csv"
    store = tmp_path / "store"
    assert main(["build-items", str(source_csv), str(items)]) == 0
    assert main(["ai-code", str(items), "--store", str(store)]) == 0
    assert main(["export", str(tmp_path / "x.csv"), "--coder", "ai-keyword-baseline", "--store", str(store)]) == 0
    assert len(list(csv.DictReader(open(tmp_path / "x.csv")))) == 3


def test_cli_paid_backend_is_dry_run_by_default(source_csv, tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("BLINDCODE_ALLOW_PAID", raising=False)
    items = tmp_path / "items.csv"
    main(["build-items", str(source_csv), str(items)])
    assert main(["ai-code", str(items), "--backend", "anthropic", "--store", str(tmp_path / "s")]) == 2
    out = capsys.readouterr().out
    assert "Estimated cost" in out and "Dry run only" in out
    assert not (tmp_path / "s").exists()
