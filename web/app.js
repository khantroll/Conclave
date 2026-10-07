const $ = (id) => document.getElementById(id);

let workspaces = [];
let activeWorkspaceId = null;
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
        </span>`).join("")
    : body.providers.map(p => `<span>${escapeHtml(p)}</span>`).join("");
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

async function createWorkspace(event) {
  event.preventDefault();
  const delegates = $("workspaceDelegates").value.split(",").map(s => s.trim()).filter(Boolean);
  const body = {
    name: $("workspaceName").value.trim(),
    description: $("workspaceDescription").value.trim() || null,
    context: $("workspaceContext").value.trim() || null,
    delegates,
    critic: $("workspaceCritic").value.trim() || null,
    arbiter: $("workspaceArbiter").value.trim(),
    minimum_successes: Number($("workspaceQuorum").value || 1),
    auto_select_delegates: $("workspaceAutoSelect").checked,
  };
  const created = await (await api("/api/workspaces", {
    method: "POST",
    body: JSON.stringify(body),
  })).json();
  activeWorkspaceId = created.id;
  event.target.reset();
  $("workspaceQuorum").value = "1";
  await loadWorkspaces();
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
  if (activeWorkspaceId) {
    try {
      const selection = await (await api(`/api/workspaces/${activeWorkspaceId}/select`, {
        method: "POST",
        body: JSON.stringify({question}),
      })).json();
      detail += ` Suggested delegates: ${selection.selected.join(", ")}.`;
    } catch {
      // The generic analysis is still useful if workspace selection preview fails.
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
    $("status").textContent = result.panel.synthesizeable
      ? `${result.panel.successful_count} delegate(s) completed.`
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
    const content = d.raw_response || d.error || d.status;
    const timing = d.latency_ms == null ? "" : ` · ${d.latency_ms} ms`;
    const retry = failed && currentRunId
      ? `<button class="secondary retry-delegate" data-name="${escapeHtml(d.name)}">Retry this delegate</button>`
      : "";
    return `
      <article class="delegate ${failed ? "failed" : ""}">
        <strong>${escapeHtml(d.name)}</strong>
        <div class="meta">${escapeHtml(d.status)}${d.model ? " · " + escapeHtml(d.model) : ""}${timing}</div>
        <pre>${escapeHtml(content)}</pre>
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
    $("status").textContent = `${name} retried; Critic and Arbiter refreshed.`;
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
          <small>${new Date(run.created_at).toLocaleString()} · ${run.id.slice(0, 8)}</small>
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
  await loadHistory();
});
$("workspaceForm").addEventListener("submit", createWorkspace);
$("refreshWorkspaces").addEventListener("click", loadWorkspaces);
$("refreshHistory").addEventListener("click", loadHistory);
$("analyzeButton").addEventListener("click", analyze);
$("runButton").addEventListener("click", deliberate);

Promise.all([loadHealth(), loadProviders(), loadWorkspaces()]).catch(error => {
  $("status").textContent = error.message;
});
