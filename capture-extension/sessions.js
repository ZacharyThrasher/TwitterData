// Groups TweetDetail pages into thread views. A view is one focal tweet under
// one sort, from the first page (no cursor) through every page loaded while
// scrolling. Loading the thread from the top again starts a new view.
(function (root) {
  function variables(url) {
    try {
      const raw = new URL(url).searchParams.get("variables");
      const v = raw ? JSON.parse(raw) : {};
      return v && typeof v === "object" ? v : {};
    } catch (e) {
      return {};
    }
  }

  class SessionStore {
    constructor() {
      this.views = new Map();
    }

    // Returns the view the page was added to, or null if it is not usable.
    add(page) {
      if (page.status !== 200 || typeof page.text !== "string") return null;
      const v = variables(page.url);
      if (!v.focalTweetId) return null;
      const sort = typeof v.rankingMode === "string" ? v.rankingMode : "Relevance";
      const key = `${v.focalTweetId}|${sort}`;
      let view = this.views.get(key);
      if (!v.cursor || !view) {
        view = { key, focal: String(v.focalTweetId), sort, fromTop: !v.cursor,
                 started: page.started, pages: [] };
        this.views.set(key, view);
      }
      view.pages.push({ url: page.url, status: page.status, text: page.text, started: page.started });
      return view;
    }

    payload(view) {
      return { session_started: view.started, from_top: view.fromTop, pages: view.pages };
    }
  }

  const api = { SessionStore, variables };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.TDSessions = api;
})(typeof self !== "undefined" ? self : this);
