"""Markdown report: verdict table first, then details. Effect sizes and intervals, not bare p-values."""

from __future__ import annotations


def _f(x, digits=2):
    if x is None:
        return "n/a"
    return f"{x:.{digits}f}"


def _est(e: dict | None) -> str:
    if not e:
        return "n/a"
    return f"{_f(e['estimate'])} [{_f(e['ci_low'])}, {_f(e['ci_high'])}]"


def _interval(pair) -> str:
    if not pair or pair[0] is None:
        return "n/a"
    return f"[{_f(pair[0])}, {_f(pair[1])}]"


def render_markdown(r: dict) -> str:
    meta = r["meta"]
    lines = [
        "# Reply analysis report",
        "",
        f"Pipeline {meta['pipeline_version']}, run {meta['run_at_utc']}. Main frame: {meta['main_frame']}.",
        f"Viewer: {meta['sessions'].get('viewer')}. Sessions used {meta['sessions'].get('sessions_used')} of "
        f"{meta['sessions'].get('sessions_total')} ({meta['sessions'].get('sessions_not_absolute')} did not start at the top of the thread).",
        "",
    ]
    if meta.get("below_confirmatory_minimum"):
        lines += [
            f"> **Exploratory only.** {meta['threads_in_main_frame']} threads have a usable main capture, below the "
            f"pre-registered minimum of {meta['min_confirmatory_threads']}. Per the stopping rules, the tests below are "
            "reported as exploratory, and the shortfall must be stated up front.",
            "",
        ]
    lines += [
        "## Confirmatory tests (pre-registered, Holm-corrected as one family)",
        "",
        "| Test | Result | Effect [95% CI] | Scale | Holm p | Big enough to matter |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for t in r["confirmatory"]:
        p = t["primary"]
        sesoi = {True: "yes", False: "no", None: "n/a"}[t["meets_sesoi"]]
        lines.append(f"| {t['id']} | **{t['status']}** | {_est(p)} | {p['scale'] if p else ''} | "
                     f"{_f(t['p_holm'], 3)} | {sesoi} |")
    lines += ["", "### Details", ""]
    for t in r["confirmatory"]:
        lines.append(f"**{t['id']}.** {t['prediction']}")
        lines.append("")
        if t["primary"]:
            p = t["primary"]
            lines.append(f"- Main estimate ({p['term']}): {_est(p)} {p['scale']}; n = {p['n_obs']}"
                         + (f" replies in {p['n_groups']} threads" if p.get("n_groups") else "") + f"; {p['method']}.")
        for name, s in t["supporting"].items():
            if name == "amplification":
                lines.append(f"- Premium amplification ratio (view share / reply share): median {_f(s['median_ratio'])} "
                             f"{_interval(s['median_ratio_ci'])} over {s['threads_with_ratio']} threads; pooled "
                             f"{_f(s['pooled_ratio'])} {_interval(s['pooled_ratio_ci'])}.")
            elif isinstance(s, dict) and "estimate" in s:
                lines.append(f"- {name.replace('_', ' ')}: {_est(s)} {s['scale']} ({s['method']}).")
        for n in t["notes"]:
            lines.append(f"- {n}")
        lines.append("")

    ex = r["exploratory"]
    d = ex["descriptives"]
    lines += [
        "## Exploratory (labelled exploratory; cannot confirm or refute H1 to H3)",
        "",
        "### Descriptives",
        "",
        f"- {d['threads']} threads, {d['captures']} captures; main frame {d['top_level_replies_main']} replies in {d['threads_main']} threads.",
        f"- Premium share of replies in the main frame: {_f(d.get('premium_share_main'), 3)}.",
    ]
    if "incivility_rate" in d:
        lines.append(f"- Incivility rate {_f(d['incivility_rate'], 3)}; by Premium (0 = free, 1 = Premium): "
                     + ", ".join(f"{k}: {_f(v, 3)}" for k, v in d["incivility_rate_by_premium"].items()) + ".")
        e = d["incivility_exposure"]
        lines.append(f"- Uncivil replies' view share / reply share: median {_f(e['median_ratio'])} {_interval(e['median_ratio_ci'])}.")
    if "uncivil_view_multiplier" in d:
        m = d["uncivil_view_multiplier"]
        lines.append(f"- Views of an uncivil reply relative to a comparable civil one: x{_f(m['multiplier'])} {_interval(m['ci'])}.")
    lines.append("")
    lines += ["| Id | Question | Status | Headline |", "| --- | --- | --- | --- |"]
    for key in ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9"]:
        a = ex[key]
        lines.append(f"| {key} | {a['title']} | {a['status']} | {_headline(a)} |")
    lines.append("")
    nd = ex.get("near_duplicates", {})
    if nd.get("status") == "ran":
        total = sum(p["near_duplicate_pairs"] for p in nd["per_thread"])
        lines.append(f"Near-duplicate reply pairs (5-gram Jaccard >= {nd['threshold']}): {total} across {len(nd['per_thread'])} threads.")
    else:
        lines.append(f"Near-duplicate text check: {nd.get('reason', 'not run')}.")
    if meta.get("notes"):
        lines += ["", "## Notes", ""] + [f"- {n}" for n in meta["notes"]]
    lines.append("")
    return "\n".join(lines)


def _headline(a: dict) -> str:
    if a["status"] not in ("ran",):
        return a.get("reason", "")
    if "estimate" in a:
        e = a["estimate"]
        return f"{_est(e)} {e['scale']}"
    if a["id"] == "A1":
        return "; ".join(f"{s['stance']}: {_f(s['mean_gap_pp'], 1)} pp {_interval(s['ci'])}" for s in a["by_stance"])
    if a["id"] == "A6":
        return f"mismatch rate {_f(a['mismatch_rate'], 3)} over {a['authors']} authors"
    if a["id"] == "A7":
        return f"{len(a['flagged_pairs'])} flagged pairs, {len(a['pods'])} candidate pods"
    if a["id"] == "A8":
        return "; ".join(f"{k}: {_f(v['level_change_pp'], 1)} pp {_interval(v['ci_pp'])}" for k, v in a["series"].items())
    if a["id"] == "A9":
        reps = a.get("repliers", [])
        return "; ".join(f"{x['motive']}: {_f(100 * x['reply_share'], 0)}% of replies, "
                         f"{_f(100 * x['view_share'], 0) if x['view_share'] is not None else 'n/a'}% of views" for x in reps)
    return ""
