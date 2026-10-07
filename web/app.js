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
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  return response;
}

async function loadHealth() {
  try {
    const body = await (await api("/health")).json();
    $("health").textContent = `online · ${body.provider_count} providers`;
  } catch {
    $("health").textContent = "offline";
  }
}

async function loadProviders() {
  const body = await (await api("/api/providers")).json();
  const descriptors = body.descriptors || [];
  $("providers").innerHTML = descriptors.length
    ? descriptors.map(p => `
        <span class="provider-detail">
          <strong>${escapeHtml(p.name)}</strong>
          <small>${escapeHtml((p.capabilities || []).join(", ") || "general")}</small>
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
    $("status").textContent = result.error
      ? `${name}: ${result.error}`
      : `${name} connected successfully.`;
  } catch (error) {
    button.textContent = "Failed";
    $("status").textContent = `${name}: ${error.message}`;
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
  await loadHistory();
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
    critic: $("workspaceCritic").value.trim() || null,
    arbiter: $("workspaceArbiter").value.trim(),
    minimum_successes: Number($("workspaceQuorum").value || 1),
    auto_select_delegates: $("workspaceAutoSelect").checked,
  };
}

async function saveWorkspace(event) {
  event.preventDefault();
  const body = workspaceFormBody();
  try {
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
    $("status").textContent = editingWorkspaceId
      ? "Workspace updated."
      : "Workspace created.";
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
  $("workspaceCritic").value = workspace.critic || "";
  $("workspaceArbiter").value = workspace.arbiter;
  $("workspaceQuorum").value = String(workspace.minimum_successes);
  $("workspaceAutoSelect").checked = Boolean(workspace.auto_select_delegates);
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
    $("status").textContent = result.panel.synthesizeable
      ? `${result.panel.successful_count} delegate(s) completed.${cost ? " Estimated run cost " + cost + "." : ""}`
      : "Not enough delegates succeeded to synthesize.";
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

  const arbiter = result.arbiter;
  $("answerSection").classList.toggle("hidden", !arbiter);
  $("arbiterAnswer").textContent = arbiter
    ? (arbiter.raw_response || arbiter.error || arbiter.status)
    : "";

  const critic = result.critic;
  $("criticSection").classList.toggle("hidden", !critic);
  $("criticAnswer").textContent = critic
    ? (critic.raw_response || critic.error || critic.status)
    : "";

  $("delegatesSection").classList.remove("hidden");
  $("delegateCards").innerHTML = result.panel.delegates.map(d => {
    const failed = d.status !== "succeeded";
    const body = d.raw_response || d.error || d.status;
    const timing = d.latency_ms == null ? "" : ` · ${d.latency_ms} ms`;
    const cost = formatCost(d.estimated_cost_usd);
    const costText = cost ? ` · ${cost}` : "";
    const retry = failed && currentRunId
      ? `<button class="secondary retry-delegate" data-name="${escapeHtml(d.name)}">Retry this delegate</button>`
      : "";
    return `
      <article class="delegate ${failed ? "failed" : ""}">
        <strong>${escapeHtml(d.name)}</strong>
        <div class="meta">${escapeHtml(d.status)}${d.model ? " · " + escapeHtml(d.model) : ""}${timing}${costText}</div>
        <pre>${escapeHtml(body)}</pre>
        ${retry}
      </article>`;
  }).join("");

  document.querySelectorAll(".retry-delegate").forEach(button => {
    button.addEventListener("click", () => retryDelegate(button.dataset.name, button));
  });
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
    $("status").textContent = `${name} retried; Critic and Arbiter refreshed.${cost ? " Estimated run cost " + cost + "." : ""}`;
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
    return;
  }
  const runs = await (await api(`/api/workspaces/${activeWorkspaceId}/runs`)).json();
  $("history").innerHTML = runs.length
    ? runs.map(run => `
        <div class="history-item" data-run-id="${run.id}">
          <strong>${escapeHtml(run.question)}</strong>
          <small>${new Date(run.created_at).toLocaleString()} · ${run.id.slice(0, 8)}${formatCost(run.result?.estimated_cost_usd) ? " · " + formatCost(run.result.estimated_cost_usd) : ""}</small>
        </div>`).join("")
    : "<p>No runs yet.</p>";

  document.querySelectorAll(".history-item").forEach(item => {
    item.addEventListener("click", async () => {
      const run = await (await api(`/api/runs/${item.dataset.runId}`)).json();
      $("question").value = run.question;
      renderResult(run.result, run.id);
    });
  });
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
  await loadHistory();
});
$("workspaceForm").addEventListener("submit", saveWorkspace);
$("workspaceCancel").addEventListener("click", resetWorkspaceForm);
$("editWorkspace").addEventListener("click", beginWorkspaceEdit);
$("deleteWorkspace").addEventListener("click", deleteWorkspace);
$("refreshWorkspaces").addEventListener("click", loadWorkspaces);
$("refreshHistory").addEventListener("click", loadHistory);
$("analyzeButton").addEventListener("click", analyze);
$("runButton").addEventListener("click", deliberate);

Promise.all([loadHealth(), loadProviders(), loadWorkspaces()]).catch(error => {
  $("status").textContent = error.message;
});
