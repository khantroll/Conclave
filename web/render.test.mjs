// Run with: node --test web/
//
// The adversarial corpus (tests/adversarial/corpus.json, shared with the Python suite) is fed
// through every console helper that can show model text. The property under test is that
// hostile text is *inert*: it is rendered as text, never as markup, and it is shown faithfully.
//
// "Inert" is checked structurally. For each hostile value we render the same card with a
// harmless control value and require that the hostile output adds no `<`, `>`, `"` or `'`
// characters of its own, and that every `&` in it begins an entity. Markup and attribute
// breakouts all need at least one of those characters, so none can survive.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const render = require("./render.js");

const here = path.dirname(fileURLToPath(import.meta.url));
const corpus = JSON.parse(
  readFileSync(path.join(here, "..", "tests", "adversarial", "corpus.json"), "utf8"),
);

function expand(text) {
  if (typeof text === "string") return text.replaceAll("{{TOKEN}}", "0123456789ab");
  if ("repeat" in text) return expand(text.repeat).repeat(text.times);
  return text.parts.map(expand).join("");
}
const fixtures = corpus.fixtures.map((item) => ({ ...item, text: expand(item.text) }));

const ENTITY = /&(?:amp|lt|gt|quot|#039);/g;
const count = (string, char) => string.split(char).length - 1;
const decode = (html) =>
  html
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&#039;", "'")
    .replaceAll("&amp;", "&");

// The hostile output must contain exactly the markup characters the control output has.
function assertInert(hostileHtml, controlHtml, label) {
  for (const char of ["<", ">", '"', "'"]) {
    assert.equal(count(hostileHtml, char), count(controlHtml, char), `${label}: extra ${char}`);
  }
  assert.ok(!hostileHtml.replace(ENTITY, "").includes("&"), `${label}: a raw & survived`);
}

test("the corpus is loaded and covers every class", () => {
  assert.ok(fixtures.length >= 40);
  assert.deepEqual(
    [...new Set(fixtures.map((f) => f.class))].sort((a, b) => a - b),
    [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
  );
});

for (const fixture of fixtures) {
  test(`delegate card is inert: ${fixture.id}`, () => {
    const text = fixture.text;
    const shapes = {
      // an answer, with every model-derived field hostile
      answered: (v) => ({
        name: v, status: "succeeded", raw_response: v, error: v, model: v, prompt: v,
        latency_ms: 5, attempts: 2, usage: { total_tokens: 7 }, estimated_cost_usd: 0.001,
      }),
      // a failure: the error text is what is shown, and a retry button carries the name
      failed: (v) => ({
        name: v, status: "failed", raw_response: null, error: v, model: v, prompt: v,
        latency_ms: 5, attempts: 1, usage: {},
      }),
    };
    for (const [shape, make] of Object.entries(shapes)) {
      for (const canRetry of [false, true]) {
        const label = `${fixture.id}/${shape}/retry=${canRetry}`;
        const hostile = render.delegateCardsHtml([make(text)], canRetry);
        const control = render.delegateCardsHtml([make("x")], canRetry);
        assertInert(hostile, control, label);
        // faithful: the exact text is recoverable, so nothing was dropped or rewritten
        assert.ok(decode(hostile).includes(text), `${label}: text was altered`);
      }
    }
  });

  test(`history list is inert: ${fixture.id}`, () => {
    const make = (v) => ({
      id: v,
      question: v,
      created_at: v,
      workspace_id: v,
      result: {
        panel: { delegates: [{}, {}], successful_count: 1 },
        critic: { status: v },
        arbiter: { status: v },
        estimated_cost_usd: 0.25,
      },
    });
    const hostile = render.historyHtml([make(fixture.text)], (value) => String(value));
    const control = render.historyHtml([make("x")], (value) => String(value));
    assertInert(hostile, control, fixture.id);
  });
}

test("escapeHtml escapes every character that can open markup or break an attribute", () => {
  assert.equal(render.escapeHtml(`<a href="x" onclick='y'>&</a>`),
    "&lt;a href=&quot;x&quot; onclick=&#039;y&#039;&gt;&amp;&lt;/a&gt;");
  assert.equal(render.escapeHtml(null), "");
  assert.equal(render.escapeHtml(undefined), "");
  assert.equal(render.escapeHtml(42), "42");
});

test("an empty history says so and contains no model text", () => {
  assert.equal(render.historyHtml([], String), "<p>No runs yet.</p>");
});

test("describeRefresh reads the returned result, never assumes success", () => {
  const result = (extra) => ({ single_source: false, panel: { synthesizeable: true }, critic: {}, ...extra });
  assert.match(render.describeRefresh(result({ single_source: true, single_source_answer: {} }), "delegate"), /answer returned/);
  assert.match(render.describeRefresh(result({ single_source: true, critic: null }), "delegate"), /Arbiter assessed/);
  assert.match(render.describeRefresh(result({ panel: { synthesizeable: false } }), "delegate"), /quorum is still not met/);
  assert.equal(render.describeRefresh(result(), "arbiter"), "Arbiter refreshed; the panel and Critic were kept");
  assert.equal(render.describeRefresh(result(), "critic"), "Critic and Arbiter refreshed");
});
