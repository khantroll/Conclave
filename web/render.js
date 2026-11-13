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
    const parts = [stage.status];
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
  function delegateCardsHtml(delegates, canRetry) {
    return delegates
      .map((d) => {
        const failed = d.status !== "succeeded";
        const body = d.raw_response || d.error || d.status;
        const meta = formatStageMeta(d);
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
        <div class="meta">${escapeHtml(meta)}</div>
        <pre>${escapeHtml(body)}</pre>
        ${prompt}
        ${retry}
      </article>`;
      })
      .join("");
  }

  // The history list. `formatDate` is passed in so this stays free of locale and clock state.
  function historyHtml(runs, formatDate) {
    if (!runs.length) return "<p>No runs yet.</p>";
    return runs
      .map((run) => {
        const title = summarizeQuestion(run.question, 78);
        const preview = summarizeQuestion(run.question, 150);
        const panel = run.result?.panel;
        const delegateCount = panel?.delegates?.length ?? 0;
        const succeeded = panel?.successful_count ?? 0;
        const critic =
          run.result?.critic?.status === "succeeded"
            ? "Critic ✓"
            : run.result?.critic
              ? "Critic ✕"
              : "No Critic";
        const arbiter =
          run.result?.arbiter?.status === "succeeded"
            ? "Arbiter ✓"
            : run.result?.arbiter
              ? "Arbiter ✕"
              : "No Arbiter";
        const cost = formatCost(run.result?.estimated_cost_usd);
        return `
        <div class="history-item" data-run-id="${escapeHtml(run.id)}">
          <strong>${escapeHtml(title)}</strong>
          <div class="history-preview">${escapeHtml(preview)}</div>
          <small>${escapeHtml(formatDate(run.created_at))} · ${succeeded}/${delegateCount} delegates · ${critic} · ${arbiter}${run.workspace_id ? "" : " · detached"}${cost ? " · " + escapeHtml(cost) : ""}</small>
        </div>`;
      })
      .join("");
  }

  return {
    escapeHtml,
    summarizeQuestion,
    formatCost,
    formatStageMeta,
    describeRefresh,
    delegateCardsHtml,
    historyHtml,
  };
});
