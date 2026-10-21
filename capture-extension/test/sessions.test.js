const test = require("node:test");
const assert = require("node:assert");
const { SessionStore } = require("../sessions.js");

const url = vars => "https://x.com/i/api/graphql/abc123/TweetDetail?variables=" +
  encodeURIComponent(JSON.stringify(vars)) + "&features=%7B%7D";
const page = (vars, extra = {}) => ({ url: url(vars), status: 200, text: "{}", started: "2026-11-02T18:00:00.000Z", ...extra });

test("groups scroll pages into one view per focal tweet and sort", () => {
  const s = new SessionStore();
  const a = s.add(page({ focalTweetId: "1", rankingMode: "Relevance" }));
  const b = s.add(page({ focalTweetId: "1", rankingMode: "Relevance", cursor: "c1" }));
  const c = s.add(page({ focalTweetId: "1", rankingMode: "Likes" }));
  assert.strictEqual(a, b);
  assert.notStrictEqual(a, c);
  assert.strictEqual(a.pages.length, 2);
  assert.strictEqual(a.fromTop, true);
});

test("loading from the top again starts a fresh view", () => {
  const s = new SessionStore();
  const first = s.add(page({ focalTweetId: "1" }));
  s.add(page({ focalTweetId: "1", cursor: "c1" }));
  const again = s.add(page({ focalTweetId: "1" }, { started: "2026-11-02T18:05:00.000Z" }));
  assert.notStrictEqual(first, again);
  assert.strictEqual(again.pages.length, 1);
  assert.strictEqual(s.payload(again).session_started, "2026-11-02T18:05:00.000Z");
});

test("a view that starts mid-scroll is marked as not from the top", () => {
  const s = new SessionStore();
  const v = s.add(page({ focalTweetId: "1", cursor: "c9" }));
  assert.strictEqual(v.fromTop, false);
});

test("ignores failed responses and pages without a focal tweet", () => {
  const s = new SessionStore();
  assert.strictEqual(s.add(page({ focalTweetId: "1" }, { status: 429 })), null);
  assert.strictEqual(s.add(page({})), null);
});

test("payload carries only url, status, body and time per page", () => {
  const s = new SessionStore();
  const v = s.add(page({ focalTweetId: "1" }, { headers: { cookie: "auth_token=x" } }));
  const keys = Object.keys(s.payload(v).pages[0]).sort();
  assert.deepStrictEqual(keys, ["started", "status", "text", "url"]);
});
