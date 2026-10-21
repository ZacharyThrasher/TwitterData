// Runs in the page. Watches the page's own TweetDetail requests and, when a
// response arrives, passes its URL, status and body to relay.js. It sends no
// requests, reads no headers or cookies, and changes nothing on the page.
(() => {
  const TWEETDETAIL = /\/i\/api\/graphql\/[A-Za-z0-9_-]+\/TweetDetail(\?|$)/;
  const hand = (url, status, text, started) => {
    try {
      window.postMessage({ __tdcapture: 1, url: new URL(url, location.href).href, status, text, started },
        location.origin);
    } catch (e) { /* never break the page */ }
  };

  const open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__tdUrl = String(url);
    this.__tdStarted = new Date().toISOString();
    return open.apply(this, arguments);
  };
  const send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function () {
    if (this.__tdUrl && TWEETDETAIL.test(this.__tdUrl)) {
      this.addEventListener("load", () => {
        let text = null;
        if (this.responseType === "" || this.responseType === "text") text = this.responseText;
        else if (this.responseType === "json") text = JSON.stringify(this.response);
        if (text) hand(this.__tdUrl, this.status, text, this.__tdStarted);
      });
    }
    return send.apply(this, arguments);
  };

  const pageFetch = window.fetch;
  window.fetch = function (input) {
    const url = typeof input === "string" ? input : (input && input.url) || String(input);
    const started = new Date().toISOString();
    const result = pageFetch.apply(this, arguments);
    if (TWEETDETAIL.test(url)) {
      result.then(r => r.clone().text().then(t => hand(url, r.status, t, started))).catch(() => {});
    }
    return result;
  };
})();
