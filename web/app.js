const $ = (id) => document.getElementById(id);

let workspaces = [];
let activeWorkspaceId = null;
let editingWorkspaceId = null;
let currentRunId = null;

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {"Content-Type": "application/json", ...(options.headers || {})},
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    throw new Error(
      (detail && typeof detail === "object" ? detail.message : detail) || `HTTP ${response.status}`
    );
  }
  return response;
}

async function loadHealth() {
  try {
    const body = await (await api("/health")).json();
    $("health").textContent = `online · ${body.provider_count} providers`;
    $("providerMode").textContent = body.demo_only
      ? "demo only"
      : `${body.configured_provider_count} configured`;
    $("providerNotice").classList.toggle("warning", body.demo_only);
    $("providerNotice").textContent = body.demo_only
      ? "No real API providers are configured yet. Demo runs prove orchestration only; they do not evaluate answer quality."
      : `${body.configured_provider_count} real provider(s) configured plus ${body.demo_provider_count} demo provider(s). Restart Conclave after changing conclave.json or .env.`;
  } catch {
    $("health").textContent = "offline";
    $("providerMode").textContent = "";
    $("providerNotice").textContent = "";
  }
}

async function loadProviders() {
  const body = await (await api("/api/providers")).json();
  const descriptors = body.descriptors || [];
  $("providers").innerHTML = descriptors.length
    ? descriptors.map(p => `
        <span class="provider-detail" data-provider="${escapeHtml(p.name)}">
          <strong>${escapeHtml(p.name)}</strong>
          <small>${escapeHtml(p.model || "model not reported")}</small>
          <small>${escapeHtml((p.capabilities || []).join(", ") || "general")}</small>
          <span class="provider-source">${escapeHtml(p.source || "configured")}</span>
          <span class="provider-status" data-status-for="${escapeHtml(p.name)}"></span>
          <button class="secondary provider-test" data-name="${escapeHtml(p.name)}">Test</button>
        </span>`).join("")
    : body.providers.map(p => `
        <span class="provider-detail">
          <strong>${escapeHtml(p)}</strong>
          <button class="secondary provider-test" data-name="${escapeHtml(p)}">Test</button>
        </span>`).join("");

  document.querySelectorAll(".provider-test").forEach(button => {
    button.addEventListener("click", () => testProvider(button.dataset.name, button));
  });
}

function renderProviderTestStatus(result) {
  const target = document.querySelector(`[data-status-for="${CSS.escape(result.name)}"]`);
  if (!target) return;
  const attempts = result.attempts > 1 ? ` · ${result.attempts} attempts` : "";
  const latency = result.latency_ms != null ? ` · ${result.latency_ms} ms` : "";
  target.textContent = result.status === "succeeded"
    ? `OK${latency}${attempts}`
    : `${result.status}${latency}${attempts}`;
  target.classList.toggle("error", result.status !== "succeeded");
}

async function testAllProviders() {
  const button = $("testAllProviders");
  button.disabled = true;
  const original = button.textContent;
  button.textContent = "Testing…";
  $("providerTestDetail").classList.remove("error");
  $("providerTestDetail").textContent = "Testing configured providers concurrently…";

  try {
    const results = await (await api("/api/providers/test-all", {method: "POST"})).json();
    results.forEach(renderProviderTestStatus);
    const succeeded = results.filter(result => result.status === "succeeded").length;
    const failed = results.length - succeeded;
    const failures = results
      .filter(result => result.status !== "succeeded")
      .map(result => `${result.name}: ${result.error || result.status}`);

    $("providerTestDetail").textContent = results.length
      ? `${succeeded}/${results.length} configured providers passed.${failures.length ? " " + failures.join(" | ") : ""}`
      : "No configured providers to test.";
    $("providerTestDetail").classList.toggle("error", failed > 0);
  } catch (error) {
    $("providerTestDetail").textContent = error.message || "Provider test failed.";
    $("providerTestDetail").classList.add("error");
  } finally {
    button.textContent = original;
    button.disabled = false;
  }
}

async function testProvider(name, button) {
  button.disabled = true;
  const original = button.textContent;
  button.textContent = "Testing…";
  try {
    const result = await (await api(
      `/api/providers/${encodeURIComponent(name)}/test`,
      {method: "POST"}
    )).json();
    button.textContent = result.status === "succeeded"
      ? `OK ${result.latency_ms ?? ""}ms`
      : result.status;
    const attempts = result.attempts > 1 ? ` after ${result.attempts} attempts` : "";
    const detail = result.error
      ? `${name}: ${result.error}`
      : `${name} connected successfully${attempts}.`;
    $("status").textContent = detail;
    $("providerTestDetail").textContent = detail;
    renderProviderTestStatus(result);
    $("providerTestDetail").classList.toggle("error", Boolean(result.error));
  } catch (error) {
    button.textContent = "Failed";
    const detail = `${name}: ${error.message || error.name || "provider test failed"}`;
    $("status").textContent = detail;
    $("providerTestDetail").textContent = detail;
    $("providerTestDetail").classList.add("error");
  } finally {
    setTimeout(() => {
      button.textContent = original;
      button.disabled = false;
    }, 2500);
  }
}

async function loadWorkspaces() {
  workspaces = await (await api("/api/workspaces")).json();
  const select = $("workspaceSelect");
  select.innerHTML = workspaces.length
    ? workspaces.map(w => `<option value="${w.id}">${escapeHtml(w.name)}</option>`).join("")
    : '<option value="">No workspaces yet</option>';

  if (activeWorkspaceId && workspaces.some(w => w.id === activeWorkspaceId)) {
    select.value = activeWorkspaceId;
  } else {
    activeWorkspaceId = workspaces[0]?.id || null;
  }
  select.value = activeWorkspaceId || "";
  renderWorkspaceSummary();
  await loadHistory();
}

function renderWorkspaceSummary() {
  const target = $("workspaceSummary");
  const workspace = workspaces.find(w => w.id === activeWorkspaceId);
  if (!workspace) {
    target.innerHTML = "<em>No active workspace.</em>";
    return;
  }

  const roles = workspace.roles || {};
  const delegates = workspace.delegates.map(name => {
    const role = roles[name] ? ` — ${roles[name]}` : "";
    return `<div><strong>${escapeHtml(name)}</strong>${escapeHtml(role)}</div>`;
  }).join("");

  const overlaps = [];
  if (workspace.delegates.includes(workspace.arbiter)) {
    overlaps.push(`Arbiter ${workspace.arbiter} is also a Delegate`);
  }
  if (workspace.critic && workspace.delegates.includes(workspace.critic)) {
    overlaps.push(`Critic ${workspace.critic} is also a Delegate`);
  }

  target.innerHTML = `
    <dl>
      <dt>Delegates</dt><dd>${delegates || "None"}</dd>
      <dt>Critic</dt><dd>${escapeHtml(workspace.critic || "None")}</dd>
      <dt>Critic fallback</dt><dd>${escapeHtml((workspace.critic_fallbacks || []).join(" → ") || "None")}</dd>
      <dt>Arbiter</dt><dd>${escapeHtml(workspace.arbiter)}</dd>
      <dt>Arbiter fallback</dt><dd>${escapeHtml((workspace.arbiter_fallbacks || []).join(" → ") || "None")}</dd>
      <dt>Routing</dt><dd>${workspace.auto_select_delegates ? "Automatic subset" : "Fixed panel"}</dd>
      <dt>Quorum</dt><dd>${workspace.minimum_successes} independent source(s)${workspace.allow_single_source ? " — single-source runs allowed (labelled, quorum not met)" : " — single-source runs not allowed below the quorum"}</dd>
      <dt>One source answers</dt><dd>${workspace.single_source_mode === "arbiter_single_source" ? "Arbiter assesses the answer" : "Answer returned, no Arbiter"}</dd>
      <dt>Context</dt><dd>${workspace.context ? "Configured" : "None"}</dd>
    </dl>
    ${overlaps.length ? `<div class="warning">⚠ ${escapeHtml(overlaps.join("; "))}</div>` : ""}
    ${workspace.context ? "" : '<div class="warning">⚠ No persistent workspace context is configured. You will need to repeat project constraints in each question.</div>'}
  `;
}

function parseRoles(text) {
  const roles = {};
  const normalized = String(text || "").replaceAll("\\n", "\n");
  for (const line of normalized.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const separator = trimmed.indexOf("=");
    if (separator === -1) continue;
    const name = trimmed.slice(0, separator).trim();
    const role = trimmed.slice(separator + 1).trim();
    if (name && role) roles[name] = role;
  }
  return roles;
}

function serializeRoles(roles) {
  return Object.entries(roles || {})
    .map(([name, role]) => `${name} = ${role}`)
    .join("\n");
}

function insertContextTemplate() {
  const existing = $("workspaceContext").value.trim();
  if (existing && !confirm("Replace the existing workspace context with a starter template?")) {
    return;
  }
  $("workspaceContext").value = [
    "Project purpose:",
    "- ",
    "",
    "Core principles / constraints:",
    "- ",
    "",
    "Current state:",
    "- ",
    "",
    "Do not do:",
    "- ",
    "",
    "Decision preferences:",
    "- ",
  ].join("\n");
  $("workspaceContext").focus();
}

function workspaceFormBody() {
  return {
    name: $("workspaceName").value.trim(),
    description: $("workspaceDescription").value.trim() || null,
    context: $("workspaceContext").value.trim() || null,
    delegates: $("workspaceDelegates").value
      .split(",")
      .map(s => s.trim())
      .filter(Boolean),
    roles: parseRoles($("workspaceRoles").value),
    critic: $("workspaceCritic").value.trim() || null,
    critic_fallbacks: $("workspaceCriticFallbacks").value
      .split(",").map(s => s.trim()).filter(Boolean),
    arbiter: $("workspaceArbiter").value.trim(),
    arbiter_fallbacks: $("workspaceArbiterFallbacks").value
      .split(",").map(s => s.trim()).filter(Boolean),
    minimum_successes: Number($("workspaceQuorum").value || 1),
    auto_select_delegates: $("workspaceAutoSelect").checked,
    allow_single_source: $("workspaceAllowSingleSource").checked,
    single_source_mode: $("workspaceSingleSourceMode").value || null,
  };
}

async function saveWorkspace(event) {
  event.preventDefault();
  const body = workspaceFormBody();

  const overlaps = [];
  if (body.delegates.includes(body.arbiter)) {
    overlaps.push(`Arbiter "${body.arbiter}" is also listed as a Delegate`);
  }
  if (body.critic && body.delegates.includes(body.critic)) {
    overlaps.push(`Critic "${body.critic}" is also listed as a Delegate`);
  }
  if (overlaps.length && !confirm(
    `${overlaps.join(". ")}. This is allowed, but that provider will run in both roles. Continue?`
  )) {
    return;
  }

  try {
    const wasEditing = Boolean(editingWorkspaceId);
    let workspace;
    if (editingWorkspaceId) {
      workspace = await (await api(`/api/workspaces/${editingWorkspaceId}`, {
        method: "PUT",
        body: JSON.stringify(body),
      })).json();
    } else {
      workspace = await (await api("/api/workspaces", {
        method: "POST",
        body: JSON.stringify(body),
      })).json();
    }
    activeWorkspaceId = workspace.id;
    resetWorkspaceForm();
    await loadWorkspaces();
    const saved = wasEditing ? "Workspace updated." : "Workspace created.";
    const warnings = workspace.warnings || [];
    $("status").textContent = warnings.length
      ? `${saved} Warning: ${warnings.join(" ")}`
      : saved;
  } catch (error) {
    $("status").textContent = error.message;
  }
}

function beginWorkspaceEdit() {
  const workspace = workspaces.find(w => w.id === activeWorkspaceId);
  if (!workspace) {
    $("status").textContent = "Select a workspace first.";
    return;
  }
  editingWorkspaceId = workspace.id;
  $("workspaceName").value = workspace.name;
  $("workspaceDescription").value = workspace.description || "";
  $("workspaceContext").value = workspace.context || "";
  $("workspaceDelegates").value = workspace.delegates.join(", ");
  $("workspaceRoles").value = serializeRoles(workspace.roles);
  $("workspaceCritic").value = workspace.critic || "";
  $("workspaceCriticFallbacks").value = (workspace.critic_fallbacks || []).join(", ");
  $("workspaceArbiter").value = workspace.arbiter;
  $("workspaceArbiterFallbacks").value = (workspace.arbiter_fallbacks || []).join(", ");
  $("workspaceQuorum").value = String(workspace.minimum_successes);
  $("workspaceAutoSelect").checked = Boolean(workspace.auto_select_delegates);
  $("workspaceAllowSingleSource").checked = Boolean(workspace.allow_single_source);
  $("workspaceSingleSourceMode").value = workspace.single_source_mode || "";
  $("workspaceFormSummary").textContent = "Edit workspace";
  $("workspaceSubmit").textContent = "Save changes";
  $("workspaceCancel").classList.remove("hidden");
  $("workspaceForm").closest("details").open = true;
}

function resetWorkspaceForm() {
  editingWorkspaceId = null;
  $("workspaceForm").reset();
  $("workspaceQuorum").value = "1";
  $("workspaceFormSummary").textContent = "Create workspace";
  $("workspaceSubmit").textContent = "Create";
  $("workspaceCancel").classList.add("hidden");
  $("workspaceFormDetails").open = false;
}

async function deleteWorkspace() {
  const workspace = workspaces.find(w => w.id === activeWorkspaceId);
  if (!workspace) {
    $("status").textContent = "Select a workspace first.";
    return;
  }
  if (!confirm(`Delete workspace "${workspace.name}"? Saved run history will be retained but detached from the workspace.`)) {
    return;
  }
  try {
    await api(`/api/workspaces/${workspace.id}`, {method: "DELETE"});
    if (editingWorkspaceId === workspace.id) resetWorkspaceForm();
    activeWorkspaceId = null;
    currentRunId = null;
    await loadWorkspaces();
    $("status").textContent = "Workspace deleted; run history was preserved.";
  } catch (error) {
    $("status").textContent = error.message;
  }
}

async function analyze() {
  const question = $("question").value.trim();
  if (!question) return;

  const body = await (await api("/api/analyze", {
    method: "POST",
    body: JSON.stringify({question}),
  })).json();

  $("complexity").textContent =
    `${body.complexity} · suggests ${body.recommended_delegate_count} delegate${body.recommended_delegate_count === 1 ? "" : "s"}`;

  let detail = body.rationale;
  if (body.desired_capabilities?.length) {
    detail += ` Desired capabilities: ${body.desired_capabilities.join(", ")}.`;
  }
  if (activeWorkspaceId) {
    try {
      const selection = await (await api(`/api/workspaces/${activeWorkspaceId}/select`, {
        method: "POST",
        body: JSON.stringify({question}),
      })).json();
      detail += ` Suggested delegates: ${selection.selected.join(", ")}.`;
    } catch {
      // Generic analysis remains useful if workspace preview is unavailable.
    }
  }
  $("status").textContent = detail;
}

async function deliberate() {
  const question = $("question").value.trim();
  if (!question) {
    $("status").textContent = "Enter a question first.";
    return;
  }
  if (!activeWorkspaceId) {
    $("status").textContent = "Create or select a workspace first.";
    return;
  }

  $("runButton").disabled = true;
  $("status").textContent = "The delegates are deliberating…";
  try {
    const response = await api(`/api/workspaces/${activeWorkspaceId}/deliberate`, {
      method: "POST",
      body: JSON.stringify({question}),
    });
    const result = await response.json();
    renderResult(result, response.headers.get("X-Conclave-Run-ID"));
    const cost = formatCost(result.estimated_cost_usd);
    const sourceCount = result.panel.independent_source_count;
    const sameSource = sourceCount != null && result.panel.successful_count > sourceCount;
    const sources = sourceCount != null
      ? ` ${sourceCount} independent source(s)${sameSource ? ", so some answers count as one" : ""}.`
      : "";
    const quorum = result.panel.quorum;
    if (result.single_source_label) {
      $("status").textContent = result.single_source_label;
    } else if (quorum && quorum.status !== "met") {
      // Never present an unmet or overridden quorum as a normal result.
      const label = quorum.status === "single_source_override" ? "SINGLE-SOURCE RUN" : "QUORUM UNMET";
      $("status").textContent = `${label}: ${quorum.summary}`;
    } else {
      $("status").textContent = result.panel.synthesizeable
        ? `${result.panel.successful_count} delegate(s) completed.${sources}${cost ? " Estimated run cost " + cost + "." : ""}`
        : sameSource
          ? `${result.panel.successful_count} delegate(s) answered, but only ${sourceCount} independent source(s): not enough to synthesize.`
          : "Not enough delegates succeeded to synthesize.";
    }
    await loadHistory();
  } catch (error) {
    $("status").textContent = error.message;
  } finally {
    $("runButton").disabled = false;
  }
}

function renderResult(result, runId = null) {
  currentRunId = runId || currentRunId;
  $("runId").textContent = currentRunId ? `run ${currentRunId.slice(0, 8)}` : "";
  $("downloadRun").classList.toggle("hidden", !currentRunId);

  const arbiter = result.arbiter;
  // A single-source run may return the lone delegate's answer instead of an Arbiter synthesis.
  const lone = result.single_source_answer;
  $("answerSection").classList.toggle("hidden", !arbiter && !lone);
  $("singleSourceBanner").classList.toggle("hidden", !result.single_source_label);
  // The label is the server's own sentence, so the console, the saved result and the
  // Arbiter prompt all describe the run identically.
  $("singleSourceBanner").textContent = result.single_source_label || "";
  $("arbiterAnswer").textContent = arbiter
    ? (arbiter.raw_response || arbiter.error || arbiter.status)
    : (lone ? lone.text : "");
  $("arbiterMeta").textContent = arbiter
    ? formatStageMeta(arbiter)
    : (lone ? `Single answer from ${lone.delegate}${lone.model ? " · " + lone.model : ""}. No Arbiter was used.` : "");
  $("arbiterPromptDetails").classList.toggle("hidden", !arbiter?.prompt);
  $("arbiterPrompt").textContent = arbiter?.prompt || "";
  $("retryArbiter").classList.toggle(
    "hidden",
    !currentRunId || !arbiter || arbiter.status === "succeeded"
  );

  const critic = result.critic;
  $("criticSection").classList.toggle("hidden", !critic);
  $("criticAnswer").textContent = critic
    ? (critic.raw_response || critic.error || critic.status)
    : "";
  $("criticMeta").textContent = critic ? formatStageMeta(critic) : "";
  $("criticPromptDetails").classList.toggle("hidden", !critic?.prompt);
  $("criticPrompt").textContent = critic?.prompt || "";
  $("retryCritic").classList.toggle(
    "hidden",
    !currentRunId || !critic || critic.status === "succeeded"
  );

  $("delegatesSection").classList.remove("hidden");
  $("delegateCards").innerHTML = result.panel.delegates.map(d => {
    const failed = d.status !== "succeeded";
    const body = d.raw_response || d.error || d.status;
    const meta = formatStageMeta(d);
    const retry = failed && currentRunId
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
  }).join("");

  document.querySelectorAll(".retry-delegate").forEach(button => {
    button.addEventListener("click", () => retryDelegate(button.dataset.name, button));
  });
}

// What a retry actually refreshed, read from the returned result rather than assumed.
function describeRefresh(result, stage) {
  if (result.single_source_answer) return "single-source answer returned; no Critic or Arbiter ran";
  if (result.single_source) return "the Arbiter assessed the single source; no Critic ran";
  if (!result.panel.synthesizeable) return "quorum is still not met, so no Critic or Arbiter ran";
  if (stage === "arbiter") return "Arbiter refreshed; the panel and Critic were kept";
  return result.critic ? "Critic and Arbiter refreshed" : "Arbiter refreshed";
}

async function retryDelegate(name, button) {
  if (!currentRunId) return;
  button.disabled = true;
  $("status").textContent = `Retrying ${name} without rerunning successful delegates…`;
  try {
    const run = await (await api(
      `/api/runs/${currentRunId}/delegates/${encodeURIComponent(name)}/retry`,
      {method: "POST"}
    )).json();
    renderResult(run.result, run.id);
    const cost = formatCost(run.result.estimated_cost_usd);
    $("status").textContent = `${name} retried; ${describeRefresh(run.result, "delegate")}.${cost ? " Estimated run cost " + cost + "." : ""}`;
    await loadHistory();
  } catch (error) {
    $("status").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function retryStage(stage, button) {
  if (!currentRunId) return;
  button.disabled = true;
  $("status").textContent = stage === "critic"
    ? "Retrying Critic, then refreshing Arbiter…"
    : "Retrying Arbiter without rerunning the panel…";
  try {
    const run = await (await api(
      `/api/runs/${currentRunId}/${stage}/retry`,
      {method: "POST"}
    )).json();
    renderResult(run.result, run.id);
    $("status").textContent =
      `${stage === "critic" ? "Critic" : "Arbiter"} retried; ${describeRefresh(run.result, stage)}.`;
    await loadHistory();
  } catch (error) {
    $("status").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function loadHistory() {
  if (!activeWorkspaceId) {
    $("history").textContent = "No workspace selected.";
    await loadAllHistory();
    return;
  }
  const runs = await (await api(`/api/workspaces/${activeWorkspaceId}/runs`)).json();
  renderHistory("history", runs);
  await loadAllHistory();
}

async function loadAllHistory() {
  const runs = await (await api("/api/runs")).json();
  renderHistory("allHistory", runs);
}

function renderHistory(targetId, runs) {
  const target = $(targetId);
  target.innerHTML = runs.length
    ? runs.map(run => {
        const title = summarizeQuestion(run.question, 78);
        const preview = summarizeQuestion(run.question, 150);
        const panel = run.result?.panel;
        const delegateCount = panel?.delegates?.length ?? 0;
        const succeeded = panel?.successful_count ?? 0;
        const critic = run.result?.critic?.status === "succeeded" ? "Critic ✓" : (run.result?.critic ? "Critic ✕" : "No Critic");
        const arbiter = run.result?.arbiter?.status === "succeeded" ? "Arbiter ✓" : (run.result?.arbiter ? "Arbiter ✕" : "No Arbiter");
        const cost = formatCost(run.result?.estimated_cost_usd);
        return `
        <div class="history-item" data-run-id="${run.id}">
          <strong>${escapeHtml(title)}</strong>
          <div class="history-preview">${escapeHtml(preview)}</div>
          <small>${new Date(run.created_at).toLocaleString()} · ${succeeded}/${delegateCount} delegates · ${critic} · ${arbiter}${run.workspace_id ? "" : " · detached"}${cost ? " · " + cost : ""}</small>
        </div>`;
      }).join("")
    : "<p>No runs yet.</p>";

  target.querySelectorAll(".history-item").forEach(item => {
    item.addEventListener("click", async () => {
      const run = await (await api(`/api/runs/${item.dataset.runId}`)).json();
      $("question").value = run.question;
      renderResult(run.result, run.id);
    });
  });
}

async function downloadCurrentRun() {
  if (!currentRunId) return;
  try {
    const run = await (await api(`/api/runs/${currentRunId}`)).json();
    const blob = new Blob([JSON.stringify(run, null, 2)], {type: "application/json"});
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `conclave-run-${currentRunId}.json`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    $("status").textContent = error.message;
  }
}

function summarizeQuestion(question, maxLength) {
  const normalized = String(question || "").replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) return normalized;
  return normalized.slice(0, Math.max(0, maxLength - 1)).trimEnd() + "…";
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

function formatCost(value) {
  if (value == null || Number.isNaN(Number(value))) return "";
  const amount = Number(value);
  if (amount < 0.01) return `$${amount.toFixed(5)}`;
  return `$${amount.toFixed(3)}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

$("workspaceSelect").addEventListener("change", async (event) => {
  activeWorkspaceId = event.target.value || null;
  currentRunId = null;
  renderWorkspaceSummary();
  await loadHistory();
});
$("workspaceForm").addEventListener("submit", saveWorkspace);
$("testAllProviders").addEventListener("click", testAllProviders);
$("insertContextTemplate").addEventListener("click", insertContextTemplate);
$("workspaceCancel").addEventListener("click", resetWorkspaceForm);
$("editWorkspace").addEventListener("click", beginWorkspaceEdit);
$("deleteWorkspace").addEventListener("click", deleteWorkspace);
$("refreshWorkspaces").addEventListener("click", loadWorkspaces);
$("refreshHistory").addEventListener("click", loadHistory);
$("analyzeButton").addEventListener("click", analyze);
$("runButton").addEventListener("click", deliberate);
$("downloadRun").addEventListener("click", downloadCurrentRun);
$("retryCritic").addEventListener("click", event => retryStage("critic", event.currentTarget));
$("retryArbiter").addEventListener("click", event => retryStage("arbiter", event.currentTarget));

Promise.all([loadHealth(), loadProviders(), loadWorkspaces()]).catch(error => {
  $("status").textContent = error.message;
});
