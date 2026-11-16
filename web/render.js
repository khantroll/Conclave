// Pure helpers that turn data into text or HTML for the console.
//
// Everything that can contain model output goes through here and is HTML-escaped, so that
// hostile model text is shown as text and never becomes markup. These functions touch no DOM,
// which is what lets `node --test web/` run the adversarial corpus through them.
//
// Loaded as a classic browser script (exposes `ConclaveRender`) and as a CommonJS module.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.ConclaveRender = api;
  }
})(typeof self !== "undefined" ? self : globalThis, function () {
  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function summarizeQuestion(question, maxLength) {
    const normalized = String(question || "").replace(/\s+/g, " ").trim();
    if (normalized.length <= maxLength) return normalized;
    return normalized.slice(0, Math.max(0, maxLength - 1)).trimEnd() + "…";
  }

  function formatCost(value) {
    if (value == null || Number.isNaN(Number(value))) return "";
    const amount = Number(value);
    if (amount < 0.01) return `$${amount.toFixed(5)}`;
    return `$${amount.toFixed(3)}`;
  }

  function formatStageMeta(stage) {
    const parts = [stage.error_kind ? `${stage.status} (${stage.error_kind})` : stage.status];
    if (stage.model) parts.push(stage.model);
    if (stage.latency_ms != null) parts.push(`${stage.latency_ms} ms`);
    if (stage.attempts > 1) parts.push(`${stage.attempts} attempts`);
    const promptTokens = stage.usage?.prompt_tokens;
    const completionTokens = stage.usage?.completion_tokens;
    const totalTokens = stage.usage?.total_tokens;
    if (totalTokens != null) {
      parts.push(`${totalTokens} tokens`);
    } else if (promptTokens != null || completionTokens != null) {
      parts.push(`${promptTokens || 0} in / ${completionTokens || 0} out`);
    }
    const cost = formatCost(stage.estimated_cost_usd);
    if (cost) parts.push(cost);
    // A fallback that answered after earlier providers failed: say which, and why.
    const prior = (stage.prior_attempts || [])
      .map((p) => `${p.name} ${p.status}${p.error_kind ? " (" + p.error_kind + ")" : ""}`)
      .join(", ");
    if (prior) parts.push(`after: ${prior}`);
    return parts.join(" · ");
  }

  // What a retry actually refreshed, read from the returned result rather than assumed.
  function describeRefresh(result, stage) {
    if (result.single_source_answer) return "single-source answer returned; no Critic or Arbiter ran";
    if (result.single_source) return "the Arbiter assessed the single source; no Critic ran";
    if (!result.panel.synthesizeable) return "quorum is still not met, so no Critic or Arbiter ran";
    if (stage === "arbiter") return "Arbiter refreshed; the panel and Critic were kept";
    return result.critic ? "Critic and Arbiter refreshed" : "Arbiter refreshed";
  }

  // One card per delegate. Every model-derived field (answer, error, model name, prompt) is
  // escaped. `canRetry` is true when the run is saved, so a failed delegate can be retried.
  function delegateCardsHtml(delegates, canRetry, labelMap) {
    // Judges see answers only as "Response A", "Response B"...; show which delegate each was.
    const labelOf = {};
    Object.entries(labelMap || {}).forEach(([label, name]) => {
      labelOf[name] = label;
    });
    return delegates
      .map((d) => {
        const failed = d.status !== "succeeded";
        const body = d.raw_response || d.error || d.status;
        const meta = formatStageMeta(d);
        const label = labelOf[d.name]
          ? `<span class="judge-label">judges saw this as Response ${escapeHtml(labelOf[d.name])}</span>`
          : "";
        const retry =
          failed && canRetry
            ? `<button class="secondary retry-delegate" data-name="${escapeHtml(d.name)}">Retry this delegate</button>`
            : "";
        const prompt = d.prompt
          ? `<details class="prompt-details"><summary>Show exact Delegate prompt</summary><pre>${escapeHtml(d.prompt)}</pre></details>`
          : "";
        return `
      <article class="delegate ${failed ? "failed" : ""}">
        <strong>${escapeHtml(d.name)}</strong>
        ${label}
        <div class="meta">${escapeHtml(meta)}</div>
        <pre>${escapeHtml(body)}</pre>
        ${prompt}
        ${retry}
      </article>`;
      })
      .join("");
  }

  // Shown when the Critic or Arbiter is the same source as a delegate it judged. The judge itself
  // is never told, since that would undo the blinding. Plain text; empty when there is no overlap.
  function judgeOverlapNotice(result) {
    const labels = (result && result.judge_overlaps) || [];
    if (!labels.length) return "";
    const list = labels.map((l) => `Response ${l}`).join(", ");
    return `The Critic or Arbiter uses the same underlying source as ${list}, so it may have judged its own source's answer.`;
  }

  // "Estimated $0.0123 (2 calls unpriced). Provider-reported $0.0119 for 5 of 7 calls." Estimated
  // (tokens x configured price) and provider-reported are separate, and unknown is never $0.
  // Ledger totals keep four significant decimals ($0.0123), five below a cent.
  function formatLedgerAmount(value) {
    const amount = Number(value);
    return `$${amount.toFixed(amount < 0.01 ? 5 : 4)}`;
  }

  function describeCost(summary) {
    if (!summary || !summary.total_calls) return "";
    const n = summary.total_calls;
    const plural = (count) => `${count} call${count === 1 ? "" : "s"}`;
    const parts = [];
    if (summary.estimated_total_usd != null) {
      const unpriced = summary.unpriced_calls
        ? ` (${plural(summary.unpriced_calls)} unpriced${summary.possibly_billed_unpriced_calls ? `, ${summary.possibly_billed_unpriced_calls} possibly billed` : ""})`
        : "";
      parts.push(`Estimated ${formatLedgerAmount(summary.estimated_total_usd)}${unpriced}.`);
    } else {
      parts.push(`Cost unknown: ${plural(n)} unpriced${summary.possibly_billed_unpriced_calls ? `, ${summary.possibly_billed_unpriced_calls} possibly billed` : ""}.`);
    }
    if (summary.reported_calls) {
      parts.push(`Provider-reported ${formatLedgerAmount(summary.reported_total_usd)} for ${summary.reported_calls} of ${n} calls.`);
    }
    return parts.join(" ");
  }

  // The run's own calls, and the whole retry chain when it holds more calls than this run.
  function costLines(runCost, chainCost) {
    const lines = [];
    const run = describeCost(runCost);
    if (run) lines.push(`This run: ${run}`);
    if (chainCost && (!runCost || chainCost.total_calls > runCost.total_calls)) {
      const chain = describeCost(chainCost);
      if (chain) lines.push(`Whole retry chain: ${chain}`);
    }
    return lines;
  }

  // The Critic has no default: the form must say "none" or name a provider. Returns the value to
  // send (a provider name, or null for no Critic) or an error to show instead.
  function criticChoice(mode, name) {
    if (mode === "none") return { ok: true, critic: null };
    if (mode === "provider") {
      const provider = (name || "").trim();
      if (!provider) return { ok: false, error: "Name the Critic provider, or choose No Critic." };
      return { ok: true, critic: provider };
    }
    return {
      ok: false,
      error: "Choose whether to use a Critic. There is no default: its value has not been measured yet.",
    };
  }

  const AGREEMENT_NOTE = "Agreement between responses is not evidence of correctness.";

  const MERGE_REASONS = {
    same_config: "same configured model",
    same_reported_model: "same reported model",
    unresolved_router_alias: "unresolved router alias",
    near_duplicate_text: "near-identical text",
  };

  // "3 independent sources from 2 model families", plus one line per merged group saying why.
  // Plain text from the server's own fields (provider names, counts, reasons), never model text.
  function sourceSummary(panel) {
    if (!panel || panel.independent_source_count == null) return "";
    const n = panel.independent_source_count;
    let line = `${n} independent source${n === 1 ? "" : "s"}`;
    const f = panel.distinct_families;
    if (f != null) line += ` from ${f} model famil${f === 1 ? "y" : "ies"}`;
    const lines = [line + "."];
    (panel.sources || []).forEach((group) => {
      if ((group.delegates || []).length < 2) return;
      const why = MERGE_REASONS[group.reason] || "shared identity";
      const score = group.similarity != null ? `, ${Math.round(group.similarity * 100)}% similar` : "";
      lines.push(`${group.delegates.join(", ")} count as one source (${why}${score}).`);
    });
    return lines.join("\n");
  }

  const INSUFFICIENT_NOTICE =
    "Insufficient evidence: every independent source, or the Arbiter, says the responses do not support an answer.";

  // One row per delegate, verbatim and escaped, so dissent is visible whatever the Arbiter wrote.
  // Every field except the label, the source number and the fixed words is model text.
  function positionsHtml(rows) {
    if (!rows || !rows.length) return "";
    const body = rows
      .map((r) => {
        const answered = r.status === "succeeded";
        const conclusion = !answered
          ? `did not answer (${r.status})`
          : r.conclusion || "not stated";
        // Shown as the delegate wrote it; the recognized level is only for logic.
        let confidence = "not stated";
        if (!answered) confidence = "-";
        else if (r.confidence_text) {
          confidence = r.confidence ? r.confidence_text : `${r.confidence_text} (not a recognized level)`;
        } else if (r.confidence) confidence = r.confidence;
        const cls = answered ? "" : ' class="failed"';
        return `<tr${cls}>
          <td>${r.label ? escapeHtml(r.label) : "-"}</td>
          <td>${escapeHtml(r.delegate)}</td>
          <td>${r.source ? "S" + escapeHtml(r.source) : "-"}</td>
          <td>${escapeHtml(conclusion)}</td>
          <td>${escapeHtml(confidence)}</td>
        </tr>`;
      })
      .join("");
    return `<table class="positions"><thead><tr><th>Response</th><th>Delegate</th><th>Source</th><th>Conclusion</th><th>Confidence</th></tr></thead><tbody>${body}</tbody></table>`;
  }

  const SECTION_TITLES = [
    ["common_ground", "Common ground"],
    ["disagreements", "Disagreements"],
    ["uncertainty", "Uncertainty"],
    ["synthesis", "Synthesis"],
  ];

  // The Arbiter's four sections, shown separately (every point verbatim and escaped). Empty when
  // the answer was not in the required format: the raw answer is shown instead.
  function structureHtml(structure) {
    if (!structure || !structure.format_ok) return "";
    return SECTION_TITLES.map(([key, title]) => {
      const points = (structure.points && structure.points[key]) || [];
      const body = points.length
        ? `<ul>${points.map((p) => `<li>${escapeHtml(p.text)}</li>`).join("")}</ul>`
        : `<p>${escapeHtml((structure.sections && structure.sections[key]) || "")}</p>`;
      return `<div class="arbiter-section"><h3>${title}</h3>${body}</div>`;
    }).join("");
  }

  // Plain-text notices about the Arbiter's structure: format failure, citations to responses that
  // do not exist, and points that cite nothing. Empty for a single-source or failed Arbiter.
  function structureNotices(structure) {
    if (!structure) return [];
    if (!structure.format_ok) {
      const why = (structure.problems || []).join("; ");
      return [`The Arbiter did not follow the required four-section format (${why}). Its raw answer is shown as written.`];
    }
    const notices = [];
    const unknown = structure.unknown_citations || [];
    if (unknown.length) {
      notices.push(`The Arbiter cites responses that do not exist in this run: ${unknown.map((l) => "[" + l + "]").join(" ")}.`);
    }
    if (structure.uncited_points) {
      const n = structure.uncited_points;
      notices.push(`${n} point${n === 1 ? "" : "s"} in Common ground, Disagreements or Uncertainty cite no response.`);
    }
    return notices;
  }

  // "A = alpha, B = beta": which delegate each label stood for, so [A] in the Arbiter's answer
  // can be read. Judges never saw these names.
  function labelLegend(labelMap) {
    const entries = Object.entries(labelMap || {}).sort(([a], [b]) => a.localeCompare(b));
    return entries.length ? entries.map(([label, name]) => `[${label}] = ${name}`).join(", ") : "";
  }

  // The history list. `formatDate` is passed in so this stays free of locale and clock state.
  function historyHtml(runs, formatDate) {
    if (!runs.length) return "<p>No runs yet.</p>";
    return runs
      .map((run) => {
        // `run` is a summary (see RunSummary): counts and statuses, never prompts or answers.
        const title = summarizeQuestion(run.question, 78);
        const preview = summarizeQuestion(run.question, 150);
        const delegateCount = run.delegate_count ?? 0;
        const succeeded = run.successful_count ?? 0;
        const critic =
          run.critic_status === "succeeded"
            ? "Critic ✓"
            : run.critic_status
              ? "Critic ✕"
              : "No Critic";
        const arbiter =
          run.arbiter_status === "succeeded"
            ? "Arbiter ✓"
            : run.arbiter_status
              ? "Arbiter ✕"
              : "No Arbiter";
        const cost = formatCost(run.estimated_cost_usd);
        const state = run.status && run.status !== "complete" ? ` · ${run.status}` : "";
        return `
        <div class="history-item" data-run-id="${escapeHtml(run.id)}">
          <strong>${escapeHtml(title)}</strong>
          <div class="history-preview">${escapeHtml(preview)}</div>
          <small>${escapeHtml(formatDate(run.created_at))} · ${succeeded}/${delegateCount} delegates · ${critic} · ${arbiter}${run.workspace_id ? "" : " · detached"}${run.parent_run_id ? " · retry" : ""}${escapeHtml(state)}${cost ? " · " + escapeHtml(cost) : ""}</small>
        </div>`;
      })
      .join("");
  }

  // A cost that is not known is shown as "unknown", never as zero.
  function costOrUnknown(value) {
    const text = formatCost(value);
    return text || "unknown";
  }

  function providerStatusHtml(rows) {
    if (!rows || !rows.length) return "";
    const unknown = (v) => (v == null || v === "" ? "unknown" : escapeHtml(v));
    const price = (p) =>
      p.input_cost_per_million == null || p.output_cost_per_million == null
        ? "unknown"
        : `${escapeHtml(p.input_cost_per_million)} / ${escapeHtml(p.output_cost_per_million)} per M`;
    const failure = (p) =>
      p.last_failure_at
        ? `${escapeHtml(p.last_failure_at)} (${escapeHtml(p.last_failure_outcome)}${
            p.last_failure_http_status ? " " + escapeHtml(p.last_failure_http_status) : ""
          })`
        : "none recorded";
    const body = rows
      .map(
        (p) => `<tr>
          <td><strong>${escapeHtml(p.name)}</strong><br><small>${unknown(p.source)}</small></td>
          <td>${unknown(p.model)}</td>
          <td>${unknown(p.credentials)}${p.unavailable_reason ? "<br><small>" + escapeHtml(p.unavailable_reason) + "</small>" : ""}</td>
          <td>${escapeHtml((p.capabilities || []).join(", ") || "general")}</td>
          <td>${price(p)}</td>
          <td>max output ${unknown(p.max_output_tokens)}<br>context ${unknown(p.context_window_tokens)}</td>
          <td>quota ${unknown(p.quota_remaining)}</td>
          <td>${p.last_success_at ? escapeHtml(p.last_success_at) : "none recorded"}</td>
          <td>${failure(p)}</td>
        </tr>`,
      )
      .join("");
    return `<table class="data"><thead><tr><th>Provider</th><th>Model</th><th>Credentials</th><th>Capabilities</th><th>Price in / out</th><th>Limits</th><th>Quota</th><th>Last success</th><th>Last failure</th></tr></thead><tbody>${body}</tbody></table>`;
  }

  function dashboardSummary(dash) {
    const cost = dash && dash.cost_last_7_days;
    const lines = [];
    if (!cost) {
      lines.push("No provider calls recorded in the last 7 days.");
    } else {
      const total = cost.estimated_total_usd == null ? "unknown" : formatCost(cost.estimated_total_usd);
      lines.push(
        `Last 7 days: ${cost.total_calls} call(s), estimated cost ${total} (${cost.unpriced_calls} call(s) unpriced, ${cost.possibly_billed_unpriced_calls} of them possibly billed). Estimates are not invoices.`,
      );
    }
    const running = (dash && dash.running_in_background) || [];
    lines.push(running.length ? `${running.length} run(s) running in the background.` : "No background runs active.");
    return lines.join(" ");
  }

  function ledgerHtml(rows) {
    if (!rows || !rows.length) return "<p>No provider calls were recorded for this run.</p>";
    const body = rows
      .map(
        (r) => `<tr>
          <td>${escapeHtml(r.stage)}</td>
          <td>${escapeHtml(r.provider)}</td>
          <td>${escapeHtml(r.outcome)}${r.http_status ? " " + escapeHtml(r.http_status) : ""}</td>
          <td>${escapeHtml(r.attempt_no)}</td>
          <td>${r.latency_ms == null ? "unknown" : escapeHtml(r.latency_ms) + " ms"}</td>
          <td>${r.prompt_tokens == null ? "unknown" : escapeHtml(r.prompt_tokens)} / ${r.completion_tokens == null ? "unknown" : escapeHtml(r.completion_tokens)}</td>
          <td>${r.estimated_cost_usd == null ? "unpriced" : escapeHtml(formatCost(r.estimated_cost_usd))}${r.possibly_billed && r.estimated_cost_usd == null ? " (possibly billed)" : ""}</td>
          <td>${r.reported_cost_usd == null ? "not reported" : escapeHtml(formatCost(r.reported_cost_usd))}</td>
        </tr>`,
      )
      .join("");
    return `<table class="data"><thead><tr><th>Stage</th><th>Provider</th><th>Outcome</th><th>Attempt</th><th>Latency</th><th>Tokens in / out</th><th>Estimated</th><th>Provider-reported</th></tr></thead><tbody>${body}</tbody></table>`;
  }

  function stoppedNotice(result) {
    if (!result || result.stopped_reason !== "cost_ceiling") return "";
    const refused = ((result.panel && result.panel.delegates) || [])
      .concat([result.critic, result.arbiter])
      .filter((x) => x && x.error_kind === "cost_ceiling")
      .map((x) => x.name);
    return `STOPPED BY THE COST CEILING: ${refused.length} call(s) were not made (${refused.map(escapeHtml).join(", ")}) because they could exceed the estimated ceiling. Answers already received are kept.`;
  }

  function progressText(run) {
    const result = run && run.result;
    if (!result) return "Starting…";
    const delegates = (result.panel && result.panel.delegates) || [];
    const done = delegates.filter((d) => d.status === "succeeded").length;
    const failed = delegates.filter((d) => d.status !== "succeeded").length;
    const parts = [`Panel: ${done} answered, ${failed} failed or skipped`];
    parts.push(result.critic ? `Critic ${result.critic.status}` : "Critic pending or not used");
    parts.push(result.arbiter ? `Arbiter ${result.arbiter.status}` : "Arbiter pending");
    return parts.join(" · ");
  }

  return {
    costOrUnknown,
    providerStatusHtml,
    dashboardSummary,
    ledgerHtml,
    progressText,
    stoppedNotice,
    escapeHtml,
    summarizeQuestion,
    formatCost,
    formatStageMeta,
    describeRefresh,
    delegateCardsHtml,
    judgeOverlapNotice,
    criticChoice,
    describeCost,
    costLines,
    structureHtml,
    structureNotices,
    labelLegend,
    positionsHtml,
    INSUFFICIENT_NOTICE,
    sourceSummary,
    AGREEMENT_NOTE,
    historyHtml,
  };
});
