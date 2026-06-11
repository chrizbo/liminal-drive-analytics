const state = {
  workspace: localStorage.getItem("liminal-workspace") || "demo",
  route: location.hash.slice(1) || "overview",
  cache: new Map(),
  token: localStorage.getItem("liminal-admin-token") || "",
  workspaces: [],
  indexingTimer: null,
  writeTokenRequired: true,
  viewerId: localStorage.getItem("liminal-viewer-id") || "",
  configuration: {},
};

const app = document.querySelector("#app");
const drawer = document.querySelector("#drawer");
const drawerContent = document.querySelector("#drawer-content");
const titles = {
  overview: ["Knowledge operations", "Overview"],
  review: ["Persistent signals", "Ops review"],
  graph: ["Connected knowledge", "Document graph"],
  documents: ["Indexed corpus", "Documents"],
  external: ["Knowledge beyond Drive", "External links"],
  settings: ["Workspace administration", "Settings"],
};

function esc(value = "") {
  return String(value).replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}
function query(path) {
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}workspace=${encodeURIComponent(state.workspace)}`;
}
async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers["X-Admin-Token"] = state.token;
  const response = await fetch(query(path), { ...options, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json();
}
async function cached(path) {
  const key = `${state.workspace}:${path}`;
  if (!state.cache.has(key)) state.cache.set(key, api(path));
  return state.cache.get(key);
}
function toast(message) {
  const node = document.querySelector("#toast");
  node.textContent = message;
  node.classList.add("show");
  setTimeout(() => node.classList.remove("show"), 2600);
}
function badge(value) {
  const kind = String(value).toLowerCase().replaceAll(" ", "_").replace(/[^\w]/g, "");
  return `<span class="badge ${kind}">${esc(value)}</span>`;
}
function reviewCount(findings) {
  return findings.filter(f => f.active && ["new", "in_review"].includes(f.status)).length;
}
function urgency(score) {
  if (score >= 8) return { label: "Urgent", kind: "urgent" };
  if (score >= 5) return { label: "Attention", kind: "attention" };
  return { label: "Monitor", kind: "monitor" };
}
function docButton(doc) {
  return `<button data-doc="${esc(doc.id || doc.document_id)}">${esc(doc.title || doc.document_title || "Untitled")}</button>`;
}
function empty(message) { return `<div class="empty">${esc(message)}</div>`; }

async function loadWorkspaces() {
  const [workspaces, configuration] = await Promise.all([
    fetch("/workspaces").then(r => r.json()),
    fetch("/configuration").then(r => r.json()),
  ]);
  state.workspaces = workspaces;
  state.writeTokenRequired = configuration.write_token_required;
  state.configuration = configuration;
  if (!workspaces.some(w => w.id === state.workspace)) state.workspace = workspaces[0].id;
  const select = document.querySelector("#workspace");
  select.innerHTML = workspaces.map(w => `<option value="${esc(w.id)}">${w.kind === "shared" ? "Shared · " : ""}${esc(w.name)}</option>`).join("");
  select.value = state.workspace;
  select.onchange = () => {
    state.workspace = select.value;
    localStorage.setItem("liminal-workspace", state.workspace);
    state.cache.clear();
    render();
  };
}
function selectedWorkspace() {
  return state.workspaces.find(workspace => workspace.id === state.workspace);
}
function ensureWriteToken(message) {
  if (!state.writeTokenRequired || state.token) return true;
  state.token = prompt(message) || "";
  if (!state.token) return false;
  localStorage.setItem("liminal-admin-token", state.token);
  return true;
}
function metric(label, value, note, href) {
  return `<a class="summary-metric" href="${href}"><strong>${Number(value || 0).toLocaleString()}</strong><span>${esc(label)}</span><small>${esc(note)} →</small></a>`;
}
function listCard(title, subtitle, rows) {
  return `<article class="card"><div class="card-header"><div><h2>${esc(title)}</h2><p>${esc(subtitle)}</p></div></div><div class="data-list">${rows || empty("Nothing to show yet.")}</div></article>`;
}
function dataRow(doc, meta, right) {
  return `<div class="data-row"><div>${docButton(doc)}<small>${esc(meta)}</small></div><div>${right}</div></div>`;
}
function renderBrief(brief, findings, recommendations, people) {
  if (!brief) return `<article class="card brief"><div class="card-header"><div><h2>Leader brief</h2><p>No brief has been generated yet.</p></div><button class="button primary small" data-generate-brief>Generate brief</button></div></article>`;
  const content = brief.polished || brief.deterministic;
  const findingsById = new Map(findings.map(finding => [finding.id, finding]));
  const labels = { what_changed: "What changed", follow_ups: "Decisions and follow-ups", knowledge_risks: "Knowledge risks", terminology_drift: "Terminology drift", duplicate_candidates: "Possible duplicates", orphaned_meetings: "Unreachable meeting docs", recently_reviewed: "Recently reviewed" };
  const sections = Object.entries(content.sections || {}).filter(([, claims]) => claims.length).map(([key, claims]) =>
    `<section class="brief-section"><strong>${labels[key] || key}</strong>${claims.map(c => {
      if (c.drift) {
        return `<p>${esc(c.text)}</p><div class="brief-links">
          <button class="brief-doc-btn" data-doc="${esc(c.drift.src_id)}">${esc(c.drift.src_title)}</button>${c.drift.src_url ? `<a class="brief-doc-ext" href="${esc(c.drift.src_url)}" target="_blank" rel="noreferrer" title="Open source document">↗</a>` : ""}
          <button class="brief-doc-btn" data-doc="${esc(c.drift.dst_id)}">${esc(c.drift.dst_title)}</button>${c.drift.dst_url ? `<a class="brief-doc-ext" href="${esc(c.drift.dst_url)}" target="_blank" rel="noreferrer" title="Open source document">↗</a>` : ""}
        </div>`;
      }
      if (c.duplicate) {
        return `<p>${esc(c.text)}</p><div class="brief-links">
          <button class="brief-doc-btn" data-doc="${esc(c.duplicate.doc_a_id)}">${esc(c.duplicate.doc_a_title)}</button>
          <button class="brief-doc-btn" data-doc="${esc(c.duplicate.doc_b_id)}">${esc(c.duplicate.doc_b_title)}</button>
        </div>`;
      }
      if (c.docs) {
        return `<p>${esc(c.text)}</p><div class="brief-links">${c.docs.slice(0, 4).map(d =>
          `<button class="brief-doc-btn" data-doc="${esc(d.id)}">${esc(d.title)}</button>`
        ).join("")}</div>`;
      }
      const evidence = c.evidence_ids.map(id => findingsById.get(id)).filter(Boolean);
      return `<p>${esc(c.text)}</p>${evidence.length ? `<div class="brief-links">${evidence.slice(0, 6).map(f => `<button class="brief-doc-btn" data-doc="${esc(f.document_id)}">${esc(f.evidence.document_title)}</button>${f.evidence.document_url ? `<a class="brief-doc-ext" href="${esc(f.evidence.document_url)}" target="_blank" rel="noreferrer" title="Open source document">↗</a>` : ""}`).join("")}</div>` : ""}`;
    }).join("")}</section>`
  ).join("");
  const viewerOptions = people.map(person => `<option value="${esc(person.id)}" ${person.id === state.viewerId ? "selected" : ""}>${esc(person.display_name || person.email || person.id)}</option>`).join("");
  const recommendationRows = recommendations.recommendations.map(doc =>
    `<div class="brief-recommendation"><button class="brief-doc-btn" data-doc="${esc(doc.id)}">${esc(doc.title)}</button><small>+${doc.gain} recent activity</small>${doc.url ? `<a class="brief-doc-ext" href="${esc(doc.url)}" target="_blank" rel="noreferrer" title="Read document">↗</a>` : ""}</div>`
  ).join("");
  const personalizationNote = recommendations.personalized
    ? "Showing rising documents this person has not viewed."
    : recommendations.attributed_view_events_available
      ? "Choose a person to exclude documents they have already viewed."
      : "Viewer identity is not available in the indexed activity, so these are the strongest rising documents.";
  return `<article class="card brief"><div class="card-header"><div><h2>Leader brief</h2><p>${esc(brief.window_start)} to ${esc(brief.window_end)} · ${brief.polished ? "Polished" : "Deterministic"}</p></div><button class="button primary small" data-generate-brief>Regenerate</button></div>
    <section class="brief-reading"><div class="brief-reading-header"><div><strong>Worth reading</strong><p>${esc(personalizationNote)}</p></div><label>Viewing as<select id="brief-viewer"><option value="">Unspecified</option>${viewerOptions}</select></label></div>${recommendationRows || `<p>No rising documents to recommend right now.</p>`}</section>
    ${sections}</article>`;
}

async function overview() {
  const [summary, rising, stale, hubs, findings, brief, people, recommendations, briefFindings] = await Promise.all([
    cached("/overview"), cached("/analytics/rising?limit=6"), cached("/analytics/stale?limit=6"),
    cached("/analytics/hubs?limit=6"), cached("/findings?active=true&limit=100"),
    api("/briefs/latest").catch(() => null),
    cached("/people"),
    api(`/briefs/recommendations?limit=8${state.viewerId ? `&person_id=${encodeURIComponent(state.viewerId)}` : ""}`),
    cached("/findings?limit=500"),
  ]);
  document.querySelector("#review-count").textContent = reviewCount(findings) || "";
  const risingRows = rising.map(d => dataRow(d, `${d.prior_activity} → ${d.recent_activity} activity`, `<span class="delta">+${d.gain}</span>`)).join("");
  const riskRows = findings.slice(0, 6).map(f => dataRow({ id: f.document_id, title: f.evidence.document_title }, f.evidence.signal, badge(f.signal_type))).join("");
  const hubRows = hubs.map(d => dataRow(d, "Referenced across the workspace", `<strong>${d.inbound_links}</strong>`)).join("");
  app.innerHTML = `
    <div class="summary-strip">
      ${metric("documents indexed", summary.documents_indexed, "Browse documents", "#documents")}
      ${metric("document links", summary.doc_links, "Explore graph", "#graph")}
      ${metric("external links", summary.external_links, "Explore destinations", "#external")}
      ${metric("active findings", findings.length, "Open ops review", "#review")}
    </div>
    <div class="grid two-col">
      ${renderBrief(brief, briefFindings, recommendations, people)}
      ${listCard("Priority signals", "Highest scoring active findings", riskRows)}
    </div>
    <div class="grid three-col" style="margin-top:18px">
      ${listCard("Rising now", "Recent activity versus prior period", risingRows)}
      ${listCard("Knowledge hubs", "Most referenced documents", hubRows)}
      ${listCard("Went quiet", "Previously active documents", stale.map(d => dataRow(d, `${d.history_daily_avg}/day historically`, badge("stale"))).join(""))}
    </div>`;
}

async function review() {
  const findings = await cached("/findings?limit=500");
  document.querySelector("#review-count").textContent = reviewCount(findings) || "";
  app.innerHTML = `
    <div class="filters">
      <input id="review-search" placeholder="Search findings">
      <select id="review-status"><option value="">All statuses</option>${["new","in_review","resolved","dismissed"].map(x => `<option>${x}</option>`).join("")}</select>
      <select id="review-signal"><option value="">All signals</option>${["stale_hub","rising","went_quiet"].map(x => `<option>${x}</option>`).join("")}</select>
    </div>
    <article class="card" id="findings-list">${findingsMarkup(findings)}</article>`;
  const filter = () => {
    const search = document.querySelector("#review-search").value.toLowerCase();
    const status = document.querySelector("#review-status").value;
    const signal = document.querySelector("#review-signal").value;
    document.querySelector("#findings-list").innerHTML = findingsMarkup(findings.filter(f =>
      (!search || f.evidence.document_title.toLowerCase().includes(search) || f.evidence.signal.toLowerCase().includes(search)) &&
      (!status || f.status === status) && (!signal || f.signal_type === signal)
    ));
  };
  document.querySelector("#review-search").oninput = filter;
  document.querySelector("#review-status").onchange = filter;
  document.querySelector("#review-signal").onchange = filter;
}
function findingsMarkup(findings) {
  if (!findings.length) return empty("No findings match these filters.");
  return findings.map(f => {
    const level = urgency(f.score);
    return `<div class="finding">
    <div class="urgency ${level.kind}">${level.label}</div>
    <div><h3><button class="finding-title-btn" data-finding="${esc(f.id)}">${esc(f.evidence.document_title)}</button></h3><p>${esc(f.evidence.signal)}</p><div class="finding-meta">${badge(f.signal_type)} ${badge(f.status)} ${f.active ? "" : badge("inactive")}</div></div>
    <div class="finding-actions">
      ${f.evidence.document_url ? `<a class="button small" href="${esc(f.evidence.document_url)}" target="_blank" rel="noreferrer">Open doc ↗</a>` : ""}
      <button class="button small" data-finding="${esc(f.id)}">Review</button>
    </div>
  </div>`;
  }).join("");
}

async function documents() {
  const docs = await cached("/documents?limit=1000");
  const rows = docs.map(doc => `<tr><td>${docButton(doc)}</td><td>${esc(doc.owner_email || "—")}</td><td>${esc((doc.modified_at || "").slice(0, 10) || "—")}</td><td>${esc((doc.mime_type || "").split(".").pop())}</td></tr>`).join("");
  app.innerHTML = `<div class="filters"><input id="doc-search" placeholder="Search ${docs.length} documents"></div><article class="card table-wrap"><table><thead><tr><th>Document</th><th>Owner</th><th>Modified</th><th>Type</th></tr></thead><tbody id="doc-rows">${rows}</tbody></table></article>`;
  document.querySelector("#doc-search").oninput = event => {
    const term = event.target.value.toLowerCase();
    document.querySelector("#doc-rows").innerHTML = docs.filter(d => `${d.title} ${d.owner_email}`.toLowerCase().includes(term)).map(doc => `<tr><td>${docButton(doc)}</td><td>${esc(doc.owner_email || "—")}</td><td>${esc((doc.modified_at || "").slice(0, 10) || "—")}</td><td>${esc((doc.mime_type || "").split(".").pop())}</td></tr>`).join("");
  };
}

async function external() {
  const [apex, domains] = await Promise.all([cached("/external-links?group_by=apex&limit=50"), cached("/external-links?group_by=domain&limit=100")]);
  const max = Math.max(...apex.map(x => x.links), 1);
  const bars = apex.map(x => `<div class="bar-row"><span class="bar-label">${esc(x.domain)}</span><span class="bar-track"><span class="bar-fill" style="width:${x.links / max * 100}%"></span></span><strong>${x.links}</strong></div>`).join("");
  const rows = domains.map(x => `<tr><td>${esc(x.domain)}</td><td>${x.links}</td></tr>`).join("");
  app.innerHTML = `<div class="grid two-col"><article class="card"><div class="card-header"><div><h2>External system footprint</h2><p>Links grouped by apex domain</p></div></div><div class="bar-chart">${bars || empty("No external links found.")}</div></article><article class="card table-wrap"><div class="card-header"><div><h2>All domains</h2><p>Detailed destination inventory</p></div></div><table><thead><tr><th>Domain</th><th>Links</th></tr></thead><tbody>${rows}</tbody></table></article></div>`;
}

async function settings() {
  const workspace = selectedWorkspace();
  const job = workspace?.kind === "demo"
    ? { status: "idle" }
    : await api("/indexing/jobs/current").catch(() => ({ status: "idle" }));
  const running = ["queued", "running"].includes(job.status);
  app.innerHTML = `<div class="grid two-col settings-grid">
    <article class="card settings-card">
      <div class="card-header"><div><h2>Drive indexing</h2><p>Refresh documents, links, activity, and contributors for the selected workspace.</p></div></div>
      <div class="settings-workspace"><span>Selected workspace</span><strong>${esc(workspace?.name || "")}</strong></div>
      ${workspace?.kind === "demo"
        ? `<p class="muted">Demo data is isolated and cannot be indexed from Google Drive.</p>`
        : `<p class="muted">${running ? esc(job.message || "Indexing is running.") : "No indexing job is currently running."}</p><button class="button primary" data-open-index>${running ? "View indexing progress" : "Index Drive"}</button>`}
    </article>
    <article class="card settings-card">
      <div class="card-header"><div><h2>Analysis settings</h2><p>Parameters used when classifying external resources and polishing briefs.</p></div></div>
      <form class="review-form" id="settings-form">
        <label>OpenAI model<input name="openai_model" value="${esc(state.configuration.openai_model || "gpt-5.4-mini")}"></label>
        <label>Path-significant domains<textarea name="path_significant_domains" placeholder="One domain per line">${esc((state.configuration.path_significant_domains || []).join("\n"))}</textarea></label>
        <p class="muted">Paths are preserved for these domains during the next index. Re-index to apply changes.</p>
        <button class="button primary" type="submit">Save settings</button>
      </form>
    </article>
  </div>`;
  document.querySelector("#settings-form").onsubmit = async event => {
    event.preventDefault();
    if (!ensureWriteToken("Enter DRIVE_ANALYTICS_WRITE_TOKEN to save settings")) return;
    const form = new FormData(event.target);
    const domains = String(form.get("path_significant_domains") || "").split("\n").map(x => x.trim()).filter(Boolean);
    try {
      state.configuration = await api("/configuration", {
        method: "PATCH",
        body: JSON.stringify({ openai_model: form.get("openai_model"), path_significant_domains: domains }),
      });
      toast("Settings saved");
      settings();
    } catch (error) { toast(error.message); }
  };
}

async function graph() {
  const isDemo = state.workspace === "demo";
  const [data, alignmentData] = await Promise.all([
    cached("/graph"),
    isDemo ? api("/ontology/drift?threshold=1").catch(() => []) : Promise.resolve([]),
  ]);
  const alignmentToggle = isDemo ? `<label class="alignment-toggle"><input type="checkbox" id="graph-alignment"> Show alignment</label>` : "";
  app.innerHTML = `<div class="filters"><input id="graph-search" placeholder="Focus on a document"><select id="graph-min"><option value="0">All nodes</option><option value="1">1+ inbound</option><option value="2">2+ inbound</option><option value="4">4+ inbound</option></select>${alignmentToggle}</div><div class="graph-wrap"><canvas id="graph-canvas"></canvas></div><div class="graph-legend">${["rising","stale_hub","hub","stale","normal"].map(s => `<span><i class="legend-dot" style="background:${graphColors[s]}"></i>${s.replace("_"," ")}</span>`).join("")}${isDemo ? `<span><i class="legend-dot" style="background:#34a853"></i>aligned</span><span><i class="legend-dot" style="background:#fbbc04"></i>partial</span><span><i class="legend-dot" style="background:#ea4335"></i>divergent</span>` : ""}</div>`;
  const alignMap = buildAlignMap(alignmentData);
  drawGraph(data, 0, "", false, alignMap);
  document.querySelector("#graph-min").onchange = e => drawGraph(data, Number(e.target.value), document.querySelector("#graph-search").value, isDemo && document.querySelector("#graph-alignment")?.checked, alignMap);
  document.querySelector("#graph-search").oninput = e => drawGraph(data, Number(document.querySelector("#graph-min").value), e.target.value, isDemo && document.querySelector("#graph-alignment")?.checked, alignMap);
  if (isDemo) document.querySelector("#graph-alignment").onchange = e => drawGraph(data, Number(document.querySelector("#graph-min").value), document.querySelector("#graph-search").value, e.target.checked, alignMap);
}

function buildAlignMap(alignmentData) {
  const map = new Map();
  if (!alignmentData || !alignmentData.length) return map;
  const maxScore = Math.max(...alignmentData.map(a => a.alignment_score || 0), 0.01);
  alignmentData.forEach(a => {
    const pct = (a.alignment_score || 0) / maxScore;
    const color = pct >= 0.7 ? "#34a853" : pct >= 0.4 ? "#fbbc04" : "#ea4335";
    const key = `${a.src_id}|${a.dst_id}`;
    map.set(key, color);
  });
  return map;
}

const graphColors = { rising: "#34a853", stale_hub: "#ea4335", hub: "#fbbc04", stale: "#8ab4f8", normal: "#4285f4" };
function drawGraph(data, minInbound = 0, search = "", showAlignment = false, alignMap = new Map()) {
  const canvas = document.querySelector("#graph-canvas");
  const width = canvas.clientWidth; const height = 620; const scale = devicePixelRatio || 1;
  canvas.width = width * scale; canvas.height = height * scale;
  const ctx = canvas.getContext("2d"); ctx.scale(scale, scale);
  const matches = search.toLowerCase();
  let nodes = data.nodes.filter(n => n.inbound_links >= minInbound && (!matches || n.title.toLowerCase().includes(matches)));
  if (matches && nodes.length) {
    const ids = new Set(nodes.map(n => n.id));
    data.edges.forEach(e => { if (ids.has(e.source) || ids.has(e.target)) { ids.add(e.source); ids.add(e.target); } });
    nodes = data.nodes.filter(n => ids.has(n.id));
  }
  const ids = new Set(nodes.map(n => n.id)); const edges = data.edges.filter(e => ids.has(e.source) && ids.has(e.target));
  const byId = new Map();
  nodes.forEach((node, i) => {
    const angle = i / Math.max(nodes.length, 1) * Math.PI * 2;
    const ring = 120 + (i % 3) * 75;
    byId.set(node.id, { ...node, x: width / 2 + Math.cos(angle) * Math.min(ring, width * .38), y: height / 2 + Math.sin(angle) * ring, r: 6 + Math.min(node.inbound_links, 8) });
  });
  ctx.globalAlpha = .72;
  edges.forEach(e => {
    const a = byId.get(e.source), b = byId.get(e.target);
    if (!a || !b) return;
    const alignColor = showAlignment ? (alignMap.get(`${e.source}|${e.target}`) || alignMap.get(`${e.target}|${e.source}`) || "#c4c7c5") : "#c4c7c5";
    ctx.strokeStyle = alignColor;
    ctx.lineWidth = showAlignment && alignColor !== "#c4c7c5" ? 2 : 1;
    ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke();
  });
  ctx.globalAlpha = 1; ctx.lineWidth = 1;
  byId.forEach(n => { ctx.beginPath(); ctx.fillStyle = graphColors[n.status] || graphColors.normal; ctx.arc(n.x,n.y,n.r,0,Math.PI*2); ctx.fill(); if (n.inbound_links > 1 || matches) { ctx.fillStyle="#3c4043"; ctx.font="11px Arial, sans-serif"; ctx.fillText(n.title.slice(0,28),n.x+n.r+5,n.y+4); } });
  canvas.onclick = event => {
    const box = canvas.getBoundingClientRect(); const x = event.clientX - box.left, y = event.clientY - box.top;
    const hit = [...byId.values()].find(n => Math.hypot(n.x-x,n.y-y) < n.r+5);
    if (hit) openDocument(hit.id);
  };
}

function lineChart(history) {
  const values = history.map(x => x.views + x.edits + x.comments);
  const max = Math.max(...values, 1);
  const points = values.map((v, i) => `${i / Math.max(values.length - 1, 1) * 560 + 10},${125 - v / max * 105}`).join(" ");
  return values.length ? `<svg class="line-chart" viewBox="0 0 580 140" preserveAspectRatio="none"><polyline class="area" points="10,130 ${points} 570,130"></polyline><polyline points="${points}"></polyline></svg>` : empty("No activity history.");
}
async function openDocument(id) {
  const isDemo = state.workspace === "demo";
  const [doc, alignment] = await Promise.all([
    api(`/documents/${encodeURIComponent(id)}`),
    isDemo ? api(`/ontology/alignment/${encodeURIComponent(id)}`).catch(() => []) : Promise.resolve([]),
  ]);
  drawerContent.innerHTML = `<p class="eyebrow">Document detail</p><h2 class="drawer-title">${esc(doc.title)}</h2><p class="muted">${esc(doc.owner_email || "No owner")} · modified ${esc((doc.modified_at || "").slice(0,10) || "unknown")}</p>
    <p><a class="button dark small" href="${esc(doc.url)}" target="_blank" rel="noreferrer">Open source document</a></p>
    <div class="grid detail-metrics"><div class="detail-metric"><strong>${doc.inbound_links.length}</strong><small>Inbound links</small></div><div class="detail-metric"><strong>${doc.outbound_links.length}</strong><small>Outbound links</small></div><div class="detail-metric"><strong>${doc.contributors.length}</strong><small>Contributors</small></div></div>
    <section class="detail-section"><h3>Activity</h3>${lineChart(doc.activity_history)}</section>
    <section class="detail-section"><h3>Linked from</h3>${doc.inbound_links.length ? `<ul>${doc.inbound_links.map(x => `<li><button data-doc="${esc(x.src_id)}">${esc(x.title || x.src_id)}</button></li>`).join("")}</ul>` : `<p class="muted">Nothing links here.</p>`}</section>
    <section class="detail-section"><h3>Links to</h3>${doc.outbound_links.length ? `<ul>${doc.outbound_links.map(x => `<li><button data-doc="${esc(x.dst_id)}">${esc(x.title || x.dst_id)}</button></li>`).join("")}</ul>` : `<p class="muted">No outbound links.</p>`}</section>
    <section class="detail-section"><h3>Contributors</h3>${doc.contributors.length ? doc.contributors.map(x => `<p>${esc(x.display_name || x.email || x.person_id)} · ${esc(x.action)} × ${x.count}</p>`).join("") : `<p class="muted">No contributor activity.</p>`}</section>
    <section class="detail-section"><h3>External links</h3>${doc.external_links.length ? doc.external_links.map(x => `<p><a href="${esc(x.url)}" target="_blank" rel="noreferrer">${esc(x.anchor_text || x.domain)}</a> · ${esc(x.domain)}</p>`).join("") : `<p class="muted">No external links.</p>`}</section>
    ${isDemo && alignment.length ? alignmentSection(alignment) : ""}`;
  drawer.showModal();
}

function alignmentSection(alignment) {
  const maxScore = Math.max(...alignment.map(a => a.alignment_score || 0), 0.01);
  const rows = alignment.map(a => {
    const pct = Math.round(((a.alignment_score || 0) / maxScore) * 100);
    const color = pct >= 70 ? "#34a853" : pct >= 40 ? "#fbbc04" : "#ea4335";
    const label = pct >= 70 ? "aligned" : pct >= 40 ? "partial" : "divergent";
    const divergent = (a.divergent_terms || []).slice(0, 6).join(", ");
    const dir = a.direction === "outbound" ? "→" : "←";
    return `<div class="alignment-row">
      <div class="alignment-meta"><span class="alignment-dir">${dir}</span><button class="alignment-title" data-doc="${esc(a.linked_doc_id)}">${esc(a.linked_doc_title)}</button></div>
      <div class="alignment-bar-wrap" title="${pct}% alignment"><div class="alignment-bar" style="width:${pct}%;background:${color}"></div></div>
      <span class="alignment-label" style="color:${color}">${label}</span>
      ${divergent ? `<p class="alignment-divergent">Terms not in linked doc: <em>${esc(divergent)}</em></p>` : ""}
    </div>`;
  }).join("");
  return `<section class="detail-section"><h3>Concept alignment <span class="demo-badge">demo</span></h3>
    <p class="muted small">How closely this document's key terms align with linked documents. Lower alignment may indicate terminology drift.</p>
    <div class="alignment-list">${rows}</div></section>`;
}
async function openFinding(id) {
  const isDemo = state.workspace === "demo";
  const f = await api(`/findings/${encodeURIComponent(id)}`);
  const docId = f.document_id;
  const [doc, alignment] = await Promise.all([
    api(`/documents/${encodeURIComponent(docId)}`),
    isDemo ? api(`/ontology/alignment/${encodeURIComponent(docId)}`).catch(() => []) : Promise.resolve([]),
  ]);
  const level = urgency(f.score);
  drawerContent.innerHTML = `<p class="eyebrow">Operational finding</p><h2 class="drawer-title">${esc(f.evidence.document_title)}</h2>
    <div class="finding-header-meta">${badge(level.label)} ${badge(f.signal_type)} ${badge(f.status)} <span class="muted finding-signal">${esc(f.evidence.signal)}</span>${f.evidence.document_url ? `<a class="finding-ext-link" href="${esc(f.evidence.document_url)}" target="_blank" rel="noreferrer">Open doc ↗</a>` : ""}</div>
    <section class="detail-section"><h3>Suggested action</h3><p>${esc(f.suggested_action)}</p></section>
    <section class="detail-section"><h3>Review</h3><form class="review-form" id="review-form">
      <div class="form-row"><select name="status">${["new","in_review","resolved","dismissed"].map(x => `<option ${x === f.status ? "selected" : ""}>${x}</option>`)}</select><select name="disposition"><option value="">No disposition</option>${["current_no_action","update_needed","deprecate","superseded","false_positive","monitor"].map(x => `<option ${x === f.disposition ? "selected" : ""}>${x}</option>`)}</select></div>
      <div class="form-row"><input name="reviewer" placeholder="Reviewer" value="${esc(f.reviewer || "")}"><input name="assignee" placeholder="Assignee" value="${esc(f.assignee || "")}"></div>
      <input name="follow_up_date" placeholder="Follow-up date (YYYY-MM-DD)" value="${esc(f.follow_up_date || "")}">
      <textarea name="note" placeholder="Review note">${esc(f.note || "")}</textarea><button class="button primary" type="submit">Save review</button>
    </form></section>
    <div class="grid detail-metrics"><div class="detail-metric"><strong>${doc.inbound_links.length}</strong><small>Inbound links</small></div><div class="detail-metric"><strong>${doc.outbound_links.length}</strong><small>Outbound links</small></div><div class="detail-metric"><strong>${doc.contributors.length}</strong><small>Contributors</small></div></div>
    <section class="detail-section"><h3>Activity</h3>${lineChart(doc.activity_history)}</section>
    <section class="detail-section"><h3>Linked from</h3>${doc.inbound_links.length ? `<ul>${doc.inbound_links.map(x => `<li><button data-doc="${esc(x.src_id)}">${esc(x.title || x.src_id)}</button></li>`).join("")}</ul>` : `<p class="muted">Nothing links here.</p>`}</section>
    <section class="detail-section"><h3>Links to</h3>${doc.outbound_links.length ? `<ul>${doc.outbound_links.map(x => `<li><button data-doc="${esc(x.dst_id)}">${esc(x.title || x.dst_id)}</button></li>`).join("")}</ul>` : `<p class="muted">No outbound links.</p>`}</section>
    ${isDemo && alignment.length ? alignmentSection(alignment) : ""}`;
  drawer.showModal();
  document.querySelector("#review-form").onsubmit = async event => {
    event.preventDefault();
    if (!ensureWriteToken("Enter DRIVE_ANALYTICS_WRITE_TOKEN to save reviews")) return;
    const values = Object.fromEntries(new FormData(event.target));
    try {
      await api(`/findings/${encodeURIComponent(id)}/review`, { method: "PATCH", body: JSON.stringify(values) });
      state.cache.clear(); drawer.close(); toast("Review saved"); render();
    } catch (error) { toast(error.message); }
  };
}

async function generateBrief() {
  if (!ensureWriteToken("Enter DRIVE_ANALYTICS_WRITE_TOKEN to generate a brief")) return;
  try {
    await api("/briefs/generate", { method: "POST", body: JSON.stringify({ days: 7, polish: false }) });
    state.cache.clear(); toast("Leader brief generated"); render();
  } catch (error) { toast(error.message); }
}

function progressPercent(job) {
  if (job.status === "completed") return 100;
  if (!job.total) return null;
  return Math.max(0, Math.min(100, Math.round((job.current || 0) / job.total * 100)));
}
function indexingMarkup(job) {
  const percent = progressPercent(job);
  const running = ["queued", "running"].includes(job.status);
  const statusLabel = job.status === "failed" ? "Indexing failed" :
    job.status === "completed" ? "Index complete" : "Indexing workspace";
  return `<p class="eyebrow">Google Drive index</p><h2 class="drawer-title">${statusLabel}</h2>
    <p class="muted">${esc(job.workspace_name || selectedWorkspace()?.name || "")}</p>
    <section class="index-progress ${job.status}">
      <div class="index-orbit"><span></span></div>
      <h3>${esc(job.message || "Preparing index")}</h3>
      ${job.document_title ? `<p class="muted">${esc(job.document_title)}</p>` : ""}
      <div class="progress-track ${percent === null && running ? "indeterminate" : ""}">
        <span style="width:${percent === null ? 35 : percent}%"></span>
      </div>
      <div class="progress-meta"><span>${esc((job.phase || job.status).replaceAll("_", " "))}</span><strong>${percent === null ? "" : `${percent}%`}</strong></div>
    </section>
    ${job.status === "completed" ? `<section class="detail-section"><h3>Index summary</h3><p>${Number(job.result?.files_found || 0).toLocaleString()} files found.</p><button class="button primary" data-finish-index>Return to workspace</button></section>` : ""}
    ${job.status === "failed" ? `<section class="detail-section"><h3>What happened</h3><p>${esc(job.error || job.message)}</p><button class="button dark" data-open-index>Try again</button></section>` : ""}
    ${running ? `<p class="index-note">You can close this screen and continue using the app. Indexing will keep running locally.</p>` : ""}`;
}
function showIndexingJob(job, shouldOpen = true) {
  drawerContent.innerHTML = indexingMarkup(job);
  if (shouldOpen && !drawer.open) drawer.showModal();
  clearTimeout(state.indexingTimer);
  if (["queued", "running"].includes(job.status)) {
    state.indexingTimer = setTimeout(async () => {
      const updated = await api(`/indexing/jobs/${job.id}`).catch(error => ({ ...job, status: "failed", error: error.message }));
      showIndexingJob(updated, drawer.open);
    }, 800);
  } else {
    state.cache.clear();
  }
}
async function openIndexing() {
  const workspace = selectedWorkspace();
  if (!workspace || workspace.kind === "demo") {
    toast("Switch to Live Drive or a Shared Drive to run indexing");
    return;
  }
  const current = await api("/indexing/jobs/current");
  if (["queued", "running"].includes(current.status)) {
    showIndexingJob(current);
    return;
  }
  drawerContent.innerHTML = `<p class="eyebrow">Google Drive index</p><h2 class="drawer-title">Refresh ${esc(workspace.name)}</h2>
    <p class="muted">Pull recent Docs, Slides, links, activity, and contributors into this local workspace.</p>
    <form class="review-form" id="index-form">
      <label>Look back <select name="days"><option value="30">30 days</option><option value="90" selected>90 days</option><option value="365">365 days</option><option value="730">2 years</option></select></label>
      <label class="check-row"><input type="checkbox" name="expand" checked> Follow links to referenced documents outside the date window</label>
      <button class="button primary" type="submit">Start indexing</button>
    </form>`;
  drawer.showModal();
  document.querySelector("#index-form").onsubmit = async event => {
    event.preventDefault();
    if (!ensureWriteToken("Enter DRIVE_ANALYTICS_WRITE_TOKEN to start indexing")) return;
    const form = new FormData(event.target);
    try {
      const job = await api("/indexing/jobs", {
        method: "POST",
        body: JSON.stringify({ days: Number(form.get("days")), expand: form.get("expand") === "on" }),
      });
      showIndexingJob(job);
    } catch (error) { toast(error.message); }
  };
}

async function render() {
  state.route = location.hash.slice(1) || "overview";
  if (!titles[state.route]) state.route = "overview";
  document.querySelector("#route-eyebrow").textContent = titles[state.route][0];
  document.querySelector("#route-title").textContent = titles[state.route][1];
  document.querySelectorAll("#nav a").forEach(a => a.classList.toggle("active", a.dataset.route === state.route));
  app.innerHTML = `<div class="loading">Reading the workspace…</div>`;
  try { await ({ overview, review, graph, documents, external, settings })[state.route](); }
  catch (error) { app.innerHTML = `<article class="card empty"><h2>Could not load this view</h2><p>${esc(error.message)}</p></article>`; }
}

window.addEventListener("hashchange", render);
document.querySelector("#refresh-button").onclick = () => { state.cache.clear(); render(); };
document.querySelector("[data-close-drawer]").onclick = () => drawer.close();
drawer.addEventListener("click", event => {
  if (event.target !== drawer) return;
  const bounds = drawer.getBoundingClientRect();
  const inside = event.clientX >= bounds.left && event.clientX <= bounds.right &&
    event.clientY >= bounds.top && event.clientY <= bounds.bottom;
  if (!inside) drawer.close();
});
document.addEventListener("click", event => {
  const doc = event.target.closest("[data-doc]"); const finding = event.target.closest("[data-finding]");
  if (doc) openDocument(doc.dataset.doc);
  if (finding) openFinding(finding.dataset.finding);
  if (event.target.closest("[data-generate-brief]")) generateBrief();
  if (event.target.closest("[data-open-index]")) openIndexing();
  if (event.target.closest("[data-finish-index]")) { drawer.close(); render(); }
});
document.addEventListener("change", event => {
  if (event.target.id !== "brief-viewer") return;
  state.viewerId = event.target.value;
  localStorage.setItem("liminal-viewer-id", state.viewerId);
  render();
});
document.querySelector("#global-search").addEventListener("keydown", event => {
  if (event.key === "Enter") { location.hash = "documents"; setTimeout(() => { const input = document.querySelector("#doc-search"); if (input) { input.value = event.target.value; input.dispatchEvent(new Event("input")); } }, 100); }
});

loadWorkspaces().then(render);
