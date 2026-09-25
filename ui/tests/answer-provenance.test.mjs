/**
 * The model pills' source: what answered, read off the console's own API responses.
 *
 * These import `lib/answer-provenance.mjs` itself, so a rule that changes in the component
 * changes here too. What is checked is that a pill can never name a model no response named,
 * that a response from outside the console's API base cannot set it, and that the one `fetch`
 * wrapper is installed once and put back.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { answerOf, isConsoleApi, watchAnswers } from "../lib/answer-provenance.mjs";

const HERE = "http://console.test/";
const API = "http://api.test:8088";

function reply(headers) {
  return { headers: new Headers(headers) };
}

function host(headers) {
  const calls = [];
  const original = async (input) => {
    calls.push(input);
    return reply(headers);
  };
  return { fetch: original, original, calls, location: { href: HERE } };
}

test("a response that names no model is no answer, never a guess", () => {
  assert.equal(answerOf(new Headers()), null);
  assert.equal(answerOf(new Headers({ "x-search-used": "true" })), null);
  assert.equal(answerOf(new Headers({ "x-answered-by": "  " })), null);
});

test("the answering model and the search flag are read as sent", () => {
  assert.deepEqual(answerOf(new Headers({ "x-answered-by": "gemini-3.5-flash" })), {
    model: "gemini-3.5-flash",
    search: false,
  });
  assert.deepEqual(
    answerOf(new Headers({ "x-answered-by": "a, b", "x-search-used": "true" })),
    { model: "a, b", search: true },
  );
});

test("only URLs under the console's API base count", () => {
  assert.equal(isConsoleApi(API + "/validate", API, HERE), true);
  assert.equal(isConsoleApi(new URL(API + "/healthz"), API, HERE), true);
  assert.equal(isConsoleApi({ url: API + "/principles" }, API, HERE), true);
  assert.equal(isConsoleApi("http://elsewhere.test/validate", API, HERE), false);
  assert.equal(isConsoleApi("/validate", API, HERE), false, "the page's own origin is not the API");
  assert.equal(isConsoleApi(42, API, HERE), false);
  // A base with a path (a deployment behind a reverse proxy) bounds the prefix at a segment.
  assert.equal(isConsoleApi("/svc/api/validate", "/svc/api", HERE), true);
  assert.equal(isConsoleApi("/svc/apix/validate", "/svc/api", HERE), false);
});

test("the wrapper reports an answer from the console's API and ignores other origins", async () => {
  const window = host({ "x-answered-by": "model-a", "x-search-used": "true" });
  const seen = [];
  const stop = watchAnswers(window, API, (answer) => seen.push(answer));
  await window.fetch(API + "/validate", { method: "POST" });
  await window.fetch("http://elsewhere.test/validate");
  stop();
  assert.deepEqual(seen, [{ model: "model-a", search: true }]);
  assert.equal(window.calls.length, 2, "the wrapper must still perform every call");
});

test("the wrapper is installed once however many listeners, and restored by the last", async () => {
  const window = host({ "x-answered-by": "model-b" });
  const first = [];
  const second = [];
  const stopFirst = watchAnswers(window, API, (answer) => first.push(answer.model));
  const wrapped = window.fetch;
  const stopSecond = watchAnswers(window, API, (answer) => second.push(answer.model));
  assert.equal(window.fetch, wrapped, "a second listener wrapped fetch again");
  await window.fetch(API + "/validate");
  stopFirst();
  assert.equal(window.fetch, wrapped, "the wrapper left while a listener remained");
  stopSecond();
  assert.equal(window.fetch, window.original, "the original fetch was not put back");
  assert.deepEqual(first, ["model-b"]);
  assert.deepEqual(second, ["model-b"]);
});
