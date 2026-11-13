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

test("a delegate card says which blind label the judges saw it as", () => {
  const card = (labelMap) =>
    render.delegateCardsHtml([{ name: "alpha", status: "succeeded", raw_response: "hi" }], false, labelMap);
  assert.match(card({ B: "alpha", A: "beta" }), /judges saw this as Response B/);
  assert.doesNotMatch(card({}), /judges saw/);
  assert.doesNotMatch(card(undefined), /judges saw/);
});

test("a label map cannot inject markup through a label or a delegate name", () => {
  const html = render.delegateCardsHtml(
    [{ name: `<b onclick="x">`, status: "succeeded", raw_response: "hi" }],
    false,
    { '<img src=x onerror=1>': `<b onclick="x">` }
  );
  assert.doesNotMatch(html, /<img|<b /);
});

test("the judge-overlap notice names the labels, and is empty without an overlap", () => {
  assert.equal(render.judgeOverlapNotice({ judge_overlaps: [] }), "");
  assert.equal(render.judgeOverlapNotice({}), "");
  assert.equal(render.judgeOverlapNotice(null), "");
  assert.match(render.judgeOverlapNotice({ judge_overlaps: ["A", "C"] }), /Response A, Response C/);
});

test("the source summary reports sources, families and why answers merged", () => {
  const panel = {
    independent_source_count: 2,
    distinct_families: 1,
    sources: [
      { delegates: ["a", "b"], reason: "near_duplicate_text", similarity: 0.934 },
      { delegates: ["c"], reason: null, similarity: null },
    ],
  };
  assert.equal(
    render.sourceSummary(panel),
    "2 independent sources from 1 model family.\na, b count as one source (near-identical text, 93% similar)."
  );
  assert.equal(render.sourceSummary({ independent_source_count: 1, distinct_families: null, sources: [] }), "1 independent source.");
  assert.equal(render.sourceSummary({ independent_source_count: 3, distinct_families: 2, sources: [] }), "3 independent sources from 2 model families.");
  assert.equal(render.sourceSummary({ independent_source_count: null }), "");
  assert.equal(render.sourceSummary(null), "");
});

test("a merged group with an unknown reason still says it counts as one", () => {
  const out = render.sourceSummary({ independent_source_count: 1, sources: [{ delegates: ["a", "b"], reason: "future_reason" }] });
  assert.match(out, /a, b count as one source \(shared identity\)/);
});

test("the agreement sentence is fixed", () => {
  assert.equal(render.AGREEMENT_NOTE, "Agreement between responses is not evidence of correctness.");
});

for (const fixture of fixtures) {
  test(`positions table is inert and faithful: ${fixture.id}`, () => {
    const text = fixture.text;
    const make = (v) => [
      { delegate: v, label: "A", source: 1, status: "succeeded", conclusion: v, confidence: null, confidence_text: v },
      { delegate: "b", label: "B", source: 2, status: "succeeded", conclusion: v, confidence: "high", confidence_text: null },
      { delegate: v, label: null, source: null, status: "failed", conclusion: null, confidence: null, confidence_text: null },
    ];
    const hostile = render.positionsHtml(make(text));
    const control = render.positionsHtml(make("x"));
    assertInert(hostile, control, fixture.id);
    assert.ok(decode(hostile).includes(text), `${fixture.id}: text was altered`);
  });
}

test("the positions table shows every row, 'not stated' and failed delegates", () => {
  const html = render.positionsHtml([
    { delegate: "a", label: "B", source: 1, status: "succeeded", conclusion: "Yes", confidence: "high" },
    { delegate: "b", label: "A", source: 2, status: "succeeded", conclusion: null, confidence: null },
    { delegate: "c", label: "C", source: 3, status: "succeeded", conclusion: "Maybe", confidence: null, confidence_text: "90%" },
    { delegate: "d", label: null, source: null, status: "failed" },
  ]);
  assert.equal((html.match(/<tr/g) || []).length, 5); // header + 4
  assert.match(html, /not stated/);
  assert.match(html, /90% \(not a recognized level\)/);
  assert.match(html, /did not answer \(failed\)/);
  assert.match(html, /<td>S2<\/td>/);
  assert.equal(render.positionsHtml([]), "");
  assert.equal(render.positionsHtml(undefined), "");
});

test("the insufficient-evidence notice is fixed text", () => {
  assert.match(render.INSUFFICIENT_NOTICE, /^Insufficient evidence/);
});

for (const fixture of fixtures) {
  test(`arbiter sections are inert and faithful: ${fixture.id}`, () => {
    const text = fixture.text;
    const make = (v) => ({
      format_ok: true,
      sections: { common_ground: v, disagreements: v, uncertainty: v, synthesis: v },
      points: {
        common_ground: [{ text: v, citations: [] }],
        disagreements: [],
        uncertainty: [{ text: v, citations: ["A"] }],
        synthesis: [{ text: v, citations: [] }],
      },
      unknown_citations: [],
      uncited_points: 0,
    });
    const hostile = render.structureHtml(make(text));
    const control = render.structureHtml(make("x"));
    assertInert(hostile, control, fixture.id);
    assert.ok(decode(hostile).includes(text), `${fixture.id}: text was altered`);
  });
}

test("the structure view is empty unless the format was ok", () => {
  assert.equal(render.structureHtml(null), "");
  assert.equal(render.structureHtml({ format_ok: false, problems: ["x"] }), "");
  const html = render.structureHtml({
    format_ok: true,
    sections: { synthesis: "Do it." },
    points: { common_ground: [{ text: "Shared [A]", citations: ["A"] }] },
  });
  for (const title of ["Common ground", "Disagreements", "Uncertainty", "Synthesis"]) {
    assert.match(html, new RegExp(`<h3>${title}</h3>`));
  }
  assert.match(html, /<li>Shared \[A\]<\/li>/);
  assert.match(html, /<p>Do it\.<\/p>/);
});

test("structure notices cover format failure, unknown citations and uncited points", () => {
  assert.deepEqual(render.structureNotices(null), []);
  assert.deepEqual(render.structureNotices({ format_ok: true, unknown_citations: [], uncited_points: 0 }), []);
  assert.match(render.structureNotices({ format_ok: false, problems: ["missing heading ## Uncertainty"] })[0], /did not follow the required four-section format \(missing heading ## Uncertainty\)/);
  const notes = render.structureNotices({ format_ok: true, unknown_citations: ["Q", "Z"], uncited_points: 2 });
  assert.match(notes[0], /\[Q\] \[Z\]/);
  assert.match(notes[1], /2 points/);
  assert.match(render.structureNotices({ format_ok: true, unknown_citations: [], uncited_points: 1 })[0], /1 point in/);
});

test("the label legend maps labels to delegates in order", () => {
  assert.equal(render.labelLegend({ B: "beta", A: "alpha" }), "[A] = alpha, [B] = beta");
  assert.equal(render.labelLegend({}), "");
  assert.equal(render.labelLegend(undefined), "");
});

test("stage meta shows the error kind and the fallback trail", () => {
  assert.equal(render.formatStageMeta({ status: "failed", error_kind: "auth", attempts: 1 }), "failed (auth)");
  assert.equal(render.formatStageMeta({ status: "succeeded" }), "succeeded");
  const meta = render.formatStageMeta({
    status: "succeeded",
    prior_attempts: [
      { name: "arbiter", status: "failed", error_kind: "quota" },
      { name: "arbiter-2", status: "timed_out", error_kind: "timeout" },
      { name: "plain", status: "failed", error_kind: null },
    ],
  });
  assert.match(meta, /after: arbiter failed \(quota\), arbiter-2 timed_out \(timeout\), plain failed$/);
});

test("cost descriptions keep estimated and provider-reported apart and never show unknown as $0", () => {
  const base = { total_calls: 7, estimated_total_usd: 0.0123, priced_calls: 5, unpriced_calls: 2, possibly_billed_unpriced_calls: 0, reported_total_usd: null, reported_calls: 0 };
  assert.equal(render.describeCost(base), "Estimated $0.0123 (2 calls unpriced).");
  assert.equal(
    render.describeCost({ ...base, possibly_billed_unpriced_calls: 1, reported_total_usd: 0.0119, reported_calls: 5 }),
    "Estimated $0.0123 (2 calls unpriced, 1 possibly billed). Provider-reported $0.0119 for 5 of 7 calls.",
  );
  assert.equal(render.describeCost({ ...base, unpriced_calls: 0 }), "Estimated $0.0123.");
  assert.equal(
    render.describeCost({ total_calls: 1, estimated_total_usd: null, priced_calls: 0, unpriced_calls: 1, possibly_billed_unpriced_calls: 1, reported_total_usd: null, reported_calls: 0 }),
    "Cost unknown: 1 call unpriced, 1 possibly billed.",
  );
  assert.equal(render.describeCost(null), "");
  assert.equal(render.describeCost({ total_calls: 0 }), "");
});

test("the chain total is shown only when it holds more calls than the run", () => {
  const run = { total_calls: 2, estimated_total_usd: 0.01, unpriced_calls: 0 };
  const chain = { total_calls: 5, estimated_total_usd: 0.04, unpriced_calls: 1, possibly_billed_unpriced_calls: 0 };
  assert.deepEqual(render.costLines(run, run), ["This run: Estimated $0.0100."]);
  assert.deepEqual(render.costLines(run, chain), [
    "This run: Estimated $0.0100.",
    "Whole retry chain: Estimated $0.0400 (1 call unpriced).",
  ]);
  assert.deepEqual(render.costLines(run, null), ["This run: Estimated $0.0100."]);
  assert.deepEqual(render.costLines(null, null), []);
});
