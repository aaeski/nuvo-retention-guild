const SHEET_ID = "1ufEfEqSBBr_sU1_IeTwHy82bC4qUxbwxjYNaaS6MxG4";

/**
 * Pulls one tab of the public Google Sheet into the browser without a
 * backend and without hitting CORS: Google's gviz endpoint returns its
 * JSON wrapped in a JS callback (google.visualization.Query.setResponse),
 * so it is loaded as a <script> tag rather than fetched with fetch().
 * A fresh network request is made every time this runs — nothing here
 * is cached or hardcoded.
 */
function loadSheetTab(sheetName) {
  return new Promise((resolve, reject) => {
    let script;
    const cleanup = () => script && script.remove();
    const settle = (fn, arg) => {
      cleanup();
      fn(arg);
    };

    window.google = window.google || {};
    window.google.visualization = {
      Query: {
        setResponse(resp) {
          if (!resp || !resp.table) return settle(reject, new Error(`bad response for ${sheetName}`));
          const cols = resp.table.cols.map((c) => c.label);
          const rows = resp.table.rows.map((r) =>
            Object.fromEntries(cols.map((c, i) => [c, r.c[i] ? r.c[i].v : null]))
          );
          settle(resolve, rows);
        },
      },
    };
    script = document.createElement("script");
    script.src =
      `https://docs.google.com/spreadsheets/d/${SHEET_ID}/gviz/tq` +
      `?tqx=out:json&sheet=${encodeURIComponent(sheetName)}&_=${Date.now()}`;
    script.onerror = () => settle(reject, new Error(`could not load sheet tab: ${sheetName}`));
    document.head.appendChild(script);
    setTimeout(() => settle(reject, new Error(`timed out loading: ${sheetName}`)), 15000);
  });
}

function computeSnapshot(customers, events) {
  const total = customers.length;
  const churned = customers.filter((c) => c.status === "churned").length;
  const active = total - churned;
  const bySegment = {};
  for (const c of customers) {
    const seg = c.segment || "unknown";
    bySegment[seg] = bySegment[seg] || { n: 0, churned: 0 };
    bySegment[seg].n += 1;
    if (c.status === "churned") bySegment[seg].churned += 1;
  }
  const segmentRows = Object.entries(bySegment)
    .map(([seg, v]) => ({ seg, n: v.n, rate: v.n ? v.churned / v.n : 0 }))
    .sort((a, b) => b.rate - a.rate);
  return { total, active, churned, churnRate: total ? churned / total : 0, segmentRows, nEvents: events.length };
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function renderLive(snapshot) {
  const el = document.getElementById("live-panel");
  const pct = (x) => `${(x * 100).toFixed(1)}%`;
  const maxRate = Math.max(...snapshot.segmentRows.map((r) => r.rate), 0.0001);

  const bars = snapshot.segmentRows
    .map(
      (r) => `
      <div class="bar-row">
        <span class="bar-label">${escapeHtml(r.seg)}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${Math.max((r.rate / maxRate) * 100, 2)}%"></div></div>
        <span class="bar-value">${pct(r.rate)} (n=${r.n})</span>
      </div>`
    )
    .join("");

  el.innerHTML = `
    <div class="stat-row">
      <div class="stat"><span class="stat-value">${snapshot.total}</span><span class="stat-label">customers</span></div>
      <div class="stat"><span class="stat-value">${snapshot.active}</span><span class="stat-label">active</span></div>
      <div class="stat"><span class="stat-value">${snapshot.churned}</span><span class="stat-label">churned</span></div>
      <div class="stat"><span class="stat-value accent">${pct(snapshot.churnRate)}</span><span class="stat-label">churn rate</span></div>
      <div class="stat"><span class="stat-value">${snapshot.nEvents}</span><span class="stat-label">events logged</span></div>
    </div>
    <p class="muted" style="margin-bottom:0.4rem">churn rate by segment</p>
    <div class="bar-chart">${bars}</div>
  `;
}

async function refreshLiveData() {
  const el = document.getElementById("live-panel");
  const stamp = document.getElementById("live-timestamp");
  el.innerHTML = `<p class="muted">fetching live data from Google Sheets…</p>`;
  try {
    // Sequential, not Promise.all: Google's gviz JSONP callback name is fixed
    // (google.visualization.Query.setResponse), so two concurrent requests
    // race to overwrite the same global callback and one of them loses its
    // response. Awaiting one at a time keeps each request's callback intact.
    const customers = await loadSheetTab("customers");
    const events = await loadSheetTab("events");
    renderLive(computeSnapshot(customers, events));
    stamp.textContent = `last fetched: ${new Date().toLocaleString()} · this request just hit the live sheet, nothing here is cached`;
  } catch (err) {
    el.innerHTML = `<p class="error">Could not reach the live sheet right now: ${err.message}</p>`;
    stamp.textContent = "";
  }
}

function fieldOrDash(v) {
  return v === undefined || v === null || v === "" ? "—" : escapeHtml(v);
}

// Fixed categorical order, one slot per agent, same order as the pipeline.
const AGENT_META = [
  { role: "Researcher", name: "Mara Vance", initials: "MV", color: "var(--brand)" },
  { role: "Designer", name: "Theo Lindqvist", initials: "TL", color: "var(--slot-2)" },
  { role: "Maker", name: "Devika Rao", initials: "DR", color: "var(--slot-3)" },
  { role: "Communicator", name: "Jonah Okafor", initials: "JO", color: "var(--slot-4)" },
  { role: "Manager", name: "Isabel Ferreira", initials: "IF", color: "var(--slot-5)" },
];

function agentStep(i, headline, detail, sub) {
  const m = AGENT_META[i];
  return `
    <div class="agent-step">
      <div class="agent-avatar" style="background:${m.color}">${m.initials}</div>
      <div class="agent-card">
        <div class="agent-role">${i + 1}. ${m.role}</div>
        <div class="agent-name">${m.name}</div>
        <p class="agent-headline">${headline}</p>
        ${detail ? `<p class="agent-detail">${detail}</p>` : ""}
        ${sub ? `<p class="agent-sub">${sub}</p>` : ""}
      </div>
    </div>`;
}

function renderPipeline(run) {
  const el = document.getElementById("pipeline-panel");
  const a = run.artefacts;
  const verdict = a.executive_review.verdict;
  const verdictBadge =
    verdict === "APPROVE"
      ? `<span class="badge badge-good">✓ APPROVE</span>`
      : `<span class="badge badge-warning">↻ ${escapeHtml(verdict || "—")}</span>`;

  const auditRows = run.chain_audit
    .map(
      (c) => `
      <div class="audit-row ${c.carried ? "" : "fail"}">
        <span class="check">${c.carried ? "✓" : "✗"}</span>
        <span>${escapeHtml(c.handoff)}</span>
        <span class="via"><code>${escapeHtml(c.via)}</code></span>
      </div>`
    )
    .join("");

  el.innerHTML = `
    <p class="pipeline-meta">
      run <code>${escapeHtml(run.run_id)}</code> · model ${escapeHtml(run.model)} · data fetched at
      ${escapeHtml(run.data_fetched_at)} from <code>${escapeHtml(run.data_source)}</code>
      ${run.revision ? " · one revision loop occurred" : ""}
    </p>

    <div class="pipeline-rail">
      ${agentStep(
        0,
        fieldOrDash(a.opportunity_brief.headline_finding),
        null,
        `target cohort: <code>${fieldOrDash(a.opportunity_brief.target_cohort?.cohort_id)}</code> (n=${fieldOrDash(a.opportunity_brief.target_cohort?.size)}) · confidence: ${fieldOrDash(a.opportunity_brief.confidence)}`
      )}
      ${agentStep(1, fieldOrDash(a.solution_concept.concept_name), fieldOrDash(a.solution_concept.customer_problem))}
      ${agentStep(
        2,
        fieldOrDash(a.build_spec.what_it_is),
        null,
        `implements: <code>${fieldOrDash(a.build_spec.implements_concept)}</code>`
      )}
      ${agentStep(
        3,
        fieldOrDash(a.messaging_pack.primary_message?.subject),
        fieldOrDash(a.messaging_pack.primary_message?.body)
      )}
      ${agentStep(4, verdictBadge, fieldOrDash(a.executive_review.executive_summary))}
    </div>

    <h3 style="margin-top:1.8rem">Chain audit</h3>
    <p class="muted" style="margin-top:-0.4rem">Does each agent's output genuinely cite the one before it?</p>
    <div class="audit-trail">${auditRows}</div>
  `;
}

async function loadLatestRun() {
  const el = document.getElementById("pipeline-panel");
  const { githubUser, githubRepo, branch } = REPO_CONFIG;
  const url = `https://raw.githubusercontent.com/${githubUser}/${githubRepo}/${branch}/runs/latest_run.json?_=${Date.now()}`;
  try {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const run = await resp.json();
    renderPipeline(run);
  } catch (err) {
    el.innerHTML = `<p class="muted">No pipeline run published yet at <code>runs/latest_run.json</code>.
      Run <code>python orchestrator.py</code> locally and push the result to see it here. (${err.message})</p>`;
  }
}

document.getElementById("refresh-btn").addEventListener("click", refreshLiveData);
refreshLiveData();
loadLatestRun();
