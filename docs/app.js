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

function renderLive(snapshot) {
  const el = document.getElementById("live-panel");
  const pct = (x) => `${(x * 100).toFixed(1)}%`;
  el.innerHTML = `
    <div class="stat-row">
      <div class="stat"><span class="stat-value">${snapshot.total}</span><span class="stat-label">customers</span></div>
      <div class="stat"><span class="stat-value">${snapshot.active}</span><span class="stat-label">active</span></div>
      <div class="stat"><span class="stat-value">${snapshot.churned}</span><span class="stat-label">churned</span></div>
      <div class="stat"><span class="stat-value">${pct(snapshot.churnRate)}</span><span class="stat-label">churn rate</span></div>
      <div class="stat"><span class="stat-value">${snapshot.nEvents}</span><span class="stat-label">events logged</span></div>
    </div>
    <table class="segment-table">
      <thead><tr><th>segment</th><th>n</th><th>churn rate</th></tr></thead>
      <tbody>
        ${snapshot.segmentRows
          .map((r) => `<tr><td>${r.seg}</td><td>${r.n}</td><td>${pct(r.rate)}</td></tr>`)
          .join("")}
      </tbody>
    </table>
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
  return v === undefined || v === null || v === "" ? "—" : v;
}

function renderPipeline(run) {
  const el = document.getElementById("pipeline-panel");
  const a = run.artefacts;
  const chainRows = run.chain_audit
    .map(
      (c) =>
        `<tr><td>${c.handoff}</td><td>${c.carried ? "✓" : "✗"}</td><td><code>${c.via}</code></td></tr>`
    )
    .join("");

  el.innerHTML = `
    <p class="muted">
      run <code>${run.run_id}</code> · model ${run.model} · data fetched at
      ${run.data_fetched_at} from <code>${run.data_source}</code>
    </p>

    <div class="agent-card">
      <h3>1. Researcher — Mara Vance</h3>
      <p><strong>${fieldOrDash(a.opportunity_brief.headline_finding)}</strong></p>
      <p class="muted">target cohort: <code>${fieldOrDash(a.opportunity_brief.target_cohort?.cohort_id)}</code>
      (n=${fieldOrDash(a.opportunity_brief.target_cohort?.size)}) · confidence: ${fieldOrDash(a.opportunity_brief.confidence)}</p>
    </div>

    <div class="agent-card">
      <h3>2. Designer — Theo Lindqvist</h3>
      <p><strong>${fieldOrDash(a.solution_concept.concept_name)}</strong></p>
      <p class="muted">${fieldOrDash(a.solution_concept.customer_problem)}</p>
    </div>

    <div class="agent-card">
      <h3>3. Maker — Devika Rao</h3>
      <p><strong>${fieldOrDash(a.build_spec.what_it_is)}</strong></p>
      <p class="muted">implements: <code>${fieldOrDash(a.build_spec.implements_concept)}</code></p>
    </div>

    <div class="agent-card">
      <h3>4. Communicator — Jonah Okafor</h3>
      <p><strong>${fieldOrDash(a.messaging_pack.primary_message?.subject)}</strong></p>
      <p class="muted">${fieldOrDash(a.messaging_pack.primary_message?.body)}</p>
    </div>

    <div class="agent-card">
      <h3>5. Manager — Isabel Ferreira</h3>
      <p><strong>verdict: ${fieldOrDash(a.executive_review.verdict)}</strong></p>
      <p class="muted">${fieldOrDash(a.executive_review.executive_summary)}</p>
    </div>

    <h3>Chain audit</h3>
    <table class="segment-table">
      <thead><tr><th>handoff</th><th>carried?</th><th>via</th></tr></thead>
      <tbody>${chainRows}</tbody>
    </table>
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
