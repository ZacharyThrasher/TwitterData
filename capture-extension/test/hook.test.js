const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SRC = fs.readFileSync(path.join(__dirname, "..", "hook.js"), "utf8");
const TD = "https://x.com/i/api/graphql/abc/TweetDetail?variables=%7B%7D";

function sandbox() {
  const posted = [];
  const fetched = [];
  class FakeXHR {
    constructor() { this.listeners = {}; this.responseType = ""; }
    open() {}
    send() {}
    addEventListener(name, fn) { this.listeners[name] = fn; }
    finish(status, text) { this.status = status; this.responseText = text; (this.listeners.load || (() => {}))(); }
  }
  const win = {
    location: { href: "https://x.com/home", origin: "https://x.com" },
    postMessage: (msg, origin) => posted.push({ msg, origin }),
    fetch: (input) => { fetched.push(input); return Promise.resolve({ status: 200, clone: () => ({ text: () => Promise.resolve("{\"data\":1}") }) }); },
  };
  win.window = win;
  const ctx = vm.createContext({ window: win, location: win.location, XMLHttpRequest: FakeXHR, URL, Date, JSON, String });
  vm.runInContext(SRC, ctx);
  return { win, ctx, posted, fetched, FakeXHR };
}

test("passes TweetDetail XHR responses to the relay, same origin only", () => {
  const s = sandbox();
  const xhr = new s.ctx.XMLHttpRequest();
  xhr.open("GET", TD);
  xhr.send();
  xhr.finish(200, "{\"data\":{}}");
  assert.strictEqual(s.posted.length, 1);
  assert.strictEqual(s.posted[0].origin, "https://x.com");
  assert.deepStrictEqual(Object.keys(s.posted[0].msg).sort(), ["__tdcapture", "started", "status", "text", "url"]);
});

test("ignores other API calls", () => {
  const s = sandbox();
  const xhr = new s.ctx.XMLHttpRequest();
  xhr.open("GET", "https://x.com/i/api/graphql/abc/HomeTimeline?variables=%7B%7D");
  xhr.send();
  xhr.finish(200, "{}");
  assert.strictEqual(s.posted.length, 0);
});

test("fetch is passed through unchanged and TweetDetail bodies are copied", async () => {
  const s = sandbox();
  await s.win.fetch(TD);
  await s.win.fetch("https://x.com/i/api/1.1/other.json");
  await new Promise(r => setImmediate(r));
  assert.deepStrictEqual(s.fetched, [TD, "https://x.com/i/api/1.1/other.json"]);
  assert.strictEqual(s.posted.length, 1);
  assert.strictEqual(s.posted[0].msg.text, "{\"data\":1}");
});
