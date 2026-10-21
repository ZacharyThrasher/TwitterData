"""Single-file offline coding page for volunteer coders.

`blindcode page` writes one HTML file holding the blind items (in that
coder's own shuffled order) and the codebook. The coder opens it in any
browser, offline, codes one reply at a time, and clicks Download to get a CSV.
`blindcode import <csv> --coder <id>` loads it into the store.

Progress autosaves in the browser (localStorage) as a convenience only; the
downloaded CSV is the record.
"""
from __future__ import annotations

import json
from pathlib import Path

from .codebook import Codebook
from .items import Item, coder_order
from .store import check_coder_id


def _embed(obj) -> str:
    # Safe inside <script>: no "</" sequences, no HTML comment openers.
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")


def build_page(items: list[Item], codebook: Codebook, coder: str) -> str:
    check_coder_id(coder)
    data = {
        "coder": coder,
        "codebook": {
            "id": codebook.id, "sha256": codebook.sha256, "title": codebook.title,
            "instructions": codebook.instructions, "contexts": codebook.contexts,
            "fields": [{"name": f.name, "type": f.type, "definition": f.definition,
                        "options": list(f.allowed), "max_words": f.max_words} for f in codebook.fields],
        },
        "items": [{"uid": it.uid, "text": it.text, "context": it.context} for it in coder_order(items, coder)],
    }
    return _TEMPLATE.replace("__DATA__", _embed(data)).replace("__CODER__", coder)


def write_page(items: list[Item], codebook: Codebook, coder: str, out: str | Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_page(items, codebook, coder), encoding="utf-8")
    return out


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reply coding: __CODER__</title>
<style>
:root { --bg:#fafaf8; --card:#ffffff; --ink:#1c1c1c; --muted:#5d5d5d; --line:#d9d9d4; --accent:#2457c5; --accent-ink:#ffffff; --sel:#e3ebfb; --warn:#9a3412; }
@media (prefers-color-scheme: dark) { :root { --bg:#151515; --card:#1f1f1f; --ink:#ececec; --muted:#a6a6a6; --line:#3a3a3a; --accent:#7aa2ff; --accent-ink:#0d0d0d; --sel:#25324d; --warn:#fdba74; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 760px; margin: 0 auto; padding: 16px; }
header { display:flex; flex-wrap:wrap; gap:8px 16px; align-items:center; justify-content:space-between; margin-bottom:12px; }
h1 { font-size:18px; margin:0; }
.bar { height:8px; background:var(--line); border-radius:4px; overflow:hidden; margin:4px 0 16px; }
.bar > div { height:100%; background:var(--accent); width:0; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; margin-bottom:16px; }
.ctx { color:var(--muted); font-size:14px; }
.reply { font-size:20px; line-height:1.45; white-space:pre-wrap; overflow-wrap:anywhere; margin:8px 0 0; }
fieldset { border:0; border-top:1px solid var(--line); margin:0; padding:12px 0; }
legend { font-weight:600; padding:0; }
fieldset.current legend { color:var(--accent); }
fieldset.current legend::before { content:"> "; }
.def { color:var(--muted); font-size:14px; margin:2px 0 8px; }
.opts { display:flex; flex-wrap:wrap; gap:8px; }
.opts label { border:1px solid var(--line); border-radius:8px; padding:6px 10px; cursor:pointer; user-select:none; }
.opts input { position:absolute; opacity:0; pointer-events:none; }
.opts input:checked + span { font-weight:600; }
.opts label:has(input:checked) { background:var(--sel); border-color:var(--accent); }
.opts label:has(input:focus-visible) { outline:2px solid var(--accent); outline-offset:2px; }
input[type=text] { width:100%; padding:8px; border:1px solid var(--line); border-radius:8px; background:var(--card); color:var(--ink); font:inherit; }
.nav { display:flex; flex-wrap:wrap; gap:8px; }
button { font:inherit; padding:8px 14px; border-radius:8px; border:1px solid var(--line); background:var(--card); color:var(--ink); cursor:pointer; }
button.primary { background:var(--accent); color:var(--accent-ink); border-color:var(--accent); font-weight:600; }
.msg { color:var(--warn); min-height:1.5em; }
details { margin-bottom:16px; }
kbd { border:1px solid var(--line); border-radius:4px; padding:0 4px; font-size:13px; }
</style>
</head>
<body>
<main>
  <header>
    <h1>Reply coding, coder <span id="coder"></span></h1>
    <div><span id="count"></span> <button id="download" class="primary">Download CSV</button></div>
  </header>
  <div class="bar"><div id="fill"></div></div>
  <details>
    <summary>How this works</summary>
    <p>Score each reply from its words only. Do not look the reply up on X. When unsure, pick the milder code and say why in the note.</p>
    <p>Keys: for yes/no questions <kbd>1</kbd> = yes and <kbd>0</kbd> = no; otherwise <kbd>1</kbd>-<kbd>9</kbd> pick the numbered option. Answers move down the questions in order. <kbd>Enter</kbd> saves and goes to the next reply, <kbd>Left</kbd>/<kbd>Right</kbd> move between replies.</p>
    <p>Your work is kept in this browser while you go, but the <b>Download CSV</b> file is what counts. Download when you finish or stop, and send that file back.</p>
    <p id="instructions"></p>
  </details>
  <div class="card">
    <div class="ctx" id="ctx"></div>
    <p class="reply" id="reply"></p>
  </div>
  <form id="form" class="card" autocomplete="off"></form>
  <div class="msg" id="msg" role="status"></div>
  <div class="nav">
    <button id="prev" type="button">Previous</button>
    <button id="save" type="button" class="primary">Save and next</button>
    <button id="nextOpen" type="button">Next not done</button>
  </div>
</main>
<script>
const DATA = __DATA__;
const CB = DATA.codebook, ITEMS = DATA.items;
const KEY = "blindcode:" + CB.sha256.slice(0, 12) + ":" + DATA.coder;
let codes = {};
try { codes = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { codes = {}; }
const persist = () => { try { localStorage.setItem(KEY, JSON.stringify(codes)); } catch (e) {} };
let idx = ITEMS.findIndex(it => !codes[it.uid]); if (idx < 0) idx = 0;
let focusField = 0;
const $ = id => document.getElementById(id);
$("coder").textContent = DATA.coder;
$("instructions").textContent = CB.instructions;

function render() {
  const it = ITEMS[idx], saved = codes[it.uid] || {};
  $("ctx").textContent = "Reply " + (idx + 1) + " of " + ITEMS.length + (it.context ? ". " + (CB.contexts[it.context] || it.context) : "");
  $("reply").textContent = it.text;
  const form = $("form"); form.innerHTML = "";
  CB.fields.forEach((f, fi) => {
    const fs = document.createElement("fieldset"); fs.dataset.fi = fi;
    const lg = document.createElement("legend"); lg.textContent = f.name.replace(/_/g, " "); fs.appendChild(lg);
    const d = document.createElement("div"); d.className = "def"; d.textContent = f.definition; fs.appendChild(d);
    if (f.type === "text") {
      const inp = document.createElement("input"); inp.type = "text"; inp.name = f.name; inp.value = saved[f.name] || "";
      inp.placeholder = "Optional" + (f.max_words ? ", up to " + f.max_words + " words" : "");
      fs.appendChild(inp);
    } else {
      const wrap = document.createElement("div"); wrap.className = "opts";
      f.options.forEach((o, oi) => {
        const lab = document.createElement("label");
        const r = document.createElement("input"); r.type = "radio"; r.name = f.name; r.value = o; r.checked = saved[f.name] === o;
        r.addEventListener("change", () => { focusField = fi; markFocus(); });
        const sp = document.createElement("span");
        sp.textContent = f.type === "binary" ? (o === "1" ? "1. yes" : "0. no") : (oi < 9 ? (oi + 1) + ". " : "") + o.replace(/_/g, " ");
        lab.appendChild(r); lab.appendChild(sp); wrap.appendChild(lab);
      });
      fs.appendChild(wrap);
    }
    fs.addEventListener("focusin", () => { focusField = fi; markFocus(); });
    form.appendChild(fs);
  });
  const done = ITEMS.filter(i => codes[i.uid]).length;
  $("count").textContent = done + " of " + ITEMS.length + " done";
  $("fill").style.width = (100 * done / ITEMS.length) + "%";
  $("msg").textContent = codes[it.uid] ? "Already saved. Changes overwrite it." : "";
  focusField = 0;
  markFocus();
}

function markFocus() {
  document.querySelectorAll("fieldset").forEach(fs => fs.classList.toggle("current", Number(fs.dataset.fi) === focusField));
}

function collect() {
  const out = {}, missing = [];
  CB.fields.forEach(f => {
    if (f.type === "text") {
      let v = (document.querySelector('input[name="' + f.name + '"]').value || "").trim();
      if (f.max_words) v = v.split(/\s+/).filter(Boolean).slice(0, f.max_words).join(" ");
      out[f.name] = v;
    } else {
      const c = document.querySelector('input[name="' + f.name + '"]:checked');
      if (c) out[f.name] = c.value; else missing.push(f.name.replace(/_/g, " "));
    }
  });
  return { out, missing };
}

function save() {
  const { out, missing } = collect();
  if (missing.length) { $("msg").textContent = "Still to answer: " + missing.join(", "); return; }
  codes[ITEMS[idx].uid] = out; persist();
  const next = ITEMS.findIndex((it, i) => i > idx && !codes[it.uid]);
  idx = next >= 0 ? next : Math.min(idx + 1, ITEMS.length - 1);
  render(); window.scrollTo(0, 0);
}

function csvCell(v) { v = String(v ?? ""); return /[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }
function download() {
  const names = CB.fields.map(f => f.name);
  const rows = [["uid", ...names, "codebook_sha256"].join(",")];
  ITEMS.forEach(it => { const c = codes[it.uid]; if (c) rows.push([it.uid, ...names.map(n => c[n]), CB.sha256].map(csvCell).join(",")); });
  const blob = new Blob([rows.join("\n") + "\n"], { type: "text/csv" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
  a.download = "codes_" + DATA.coder + ".csv"; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

$("save").onclick = save;
$("prev").onclick = () => { idx = Math.max(0, idx - 1); render(); };
$("nextOpen").onclick = () => { const n = ITEMS.findIndex(it => !codes[it.uid]); if (n >= 0) { idx = n; render(); } else { $("msg").textContent = "Everything is coded. Download the CSV."; } };
$("download").onclick = download;
document.addEventListener("keydown", e => {
  if (e.target.type === "text") { if (e.key === "Enter") { e.preventDefault(); save(); } return; }
  if (e.key === "Enter") { e.preventDefault(); save(); return; }
  if (e.target.type === "radio" && e.key.startsWith("Arrow")) return;  // native radio-group keys
  if (e.key === "ArrowLeft") { idx = Math.max(0, idx - 1); render(); return; }
  if (e.key === "ArrowRight") { idx = Math.min(ITEMS.length - 1, idx + 1); render(); return; }
  const n = parseInt(e.key, 10);
  if (n >= 0 && n <= 9) {
    const fs = document.querySelector('fieldset[data-fi="' + focusField + '"]');
    const radios = fs ? fs.querySelectorAll('input[type=radio]') : [];
    const f = CB.fields[focusField];
    // binary: 0 = no, 1 = yes; categorical: 1-9 pick the numbered option
    const r = f && f.type === "binary" ? Array.from(radios).find(x => x.value === String(n)) : (n >= 1 ? radios[n - 1] : null);
    if (r) {
      r.checked = true;
      for (let j = focusField + 1; j < CB.fields.length; j++) { if (CB.fields[j].type !== "text") { focusField = j; break; } if (j === CB.fields.length - 1) focusField = j; }
      markFocus();
      const nf = document.querySelector('fieldset[data-fi="' + focusField + '"]');
      if (nf) nf.scrollIntoView({ block: "nearest" });
    }
  }
});
render();
</script>
</body>
</html>
"""
