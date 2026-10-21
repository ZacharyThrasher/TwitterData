// Runs beside the page (isolated world). Collects pages from hook.js, asks the
// background worker to save each thread view a moment after the last page
// arrives, and shows a small status box. It never touches X's page content.
(() => {
  const store = new TDSessions.SessionStore();
  const timers = new Map();
  const status = new Map(); // view key -> last result
  const SORT_LABEL = { relevance: "Relevant", likes: "Likes", recent: "Recent" };
  let box = null;

  function ensureBox() {
    if (box || !document.documentElement) return box;
    const host = document.createElement("div");
    host.style.cssText = "position:fixed;left:12px;bottom:12px;z-index:2147483647;";
    const shadow = host.attachShadow({ mode: "closed" });
    shadow.innerHTML = `<style>
      div{font:13px/1.4 system-ui,sans-serif;background:#1d1d1b;color:#ececea;border-radius:8px;
          padding:8px 10px;max-width:340px;box-shadow:0 2px 10px rgba(0,0,0,.35)}
      b{font-weight:600} .ok{color:#6fd3a0} .warn{color:#e9c46a} .bad{color:#f08a7a} .dim{color:#a2a29b}
    </style><div id="b"><span class="dim">Capture recorder ready</span></div>`;
    document.documentElement.append(host);
    box = shadow.getElementById("b");
    return box;
  }

  function line(res) {
    if (res.error === "helper_unreachable")
      return `<span class="bad">Helper not running. Start: python -m twitterdata assist</span>`;
    if (res.paused) return `<span class="warn">Recorder paused, nothing saved (toolbar button resumes)</span>`;
    if (res.error) return `<span class="bad">Not saved: ${escape(res.error)}</span>`;
    const sort = SORT_LABEL[res.sort] || res.sort;
    if (res.reason === "not_due") return `<span class="dim">${sort}: not a due capture, nothing saved</span>`;
    if (res.organic) return `<span class="dim">${sort}: ${res.n_replies} replies kept in organic set (not a scheduled capture)</span>`;
    if (res.reason === "kept_earlier")
      return `<span class="warn">${sort}: already captured (${res.n_replies}), kept the earlier one</span>`;
    const target = res.target_replies || 200;
    const cls = res.n_replies >= target ? "ok" : "warn";
    const late = res.status === "late" ? " (late)" : "";
    const top = res.rank_is_absolute ? "" : ` <span class="bad">reload from top</span>`;
    return `<span class="${cls}">${sort} ${res.age_hours}h${late}: <b>${res.n_replies}/${target}</b> saved</span>${top}`;
  }

  function escape(s) {
    return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  }

  function render(focal) {
    const b = ensureBox();
    if (!b) return;
    const rows = [...status.entries()].filter(([k]) => k.startsWith(focal + "|")).map(([, r]) => line(r));
    b.innerHTML = rows.length ? rows.join("<br>") : `<span class="dim">Capture recorder ready</span>`;
  }

  function save(view) {
    chrome.runtime.sendMessage({ type: "save", payload: store.payload(view) }, res => {
      status.set(view.key, res || { error: "helper_unreachable" });
      render(view.focal);
    });
  }

  window.addEventListener("message", e => {
    if (e.source !== window || !e.data || e.data.__tdcapture !== 1) return;
    const view = store.add(e.data);
    if (!view) return;
    clearTimeout(timers.get(view.key));
    timers.set(view.key, setTimeout(() => save(view), 1200));
  });
})();
