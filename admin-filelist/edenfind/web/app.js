"use strict";

const ROW_H = 30;
const PAGE_SIZE = 150;
const OVERSCAN = 8;

const FLAG_NAMES = [
  "f_empty", "f_default", "f_chat_channel", "f_chat_words", "f_chat_escape",
  "f_repost", "f_burst", "f_flood", "f_gibberish", "f_short", "f_featured",
];
const DEFAULT_EXCLUDE = new Set(["f_chat_channel", "f_chat_words", "f_default", "f_repost", "f_flood"]);

const ERA_RANGES = {
  fragment: ["", "2015-01-31"],
  peak: ["2015-01-01", "2017-12-31"],
  modern: ["2020-01-01", ""],
  all: ["", ""],
};

const state = {
  q: "",
  mode: "lexical",
  sort: "relevance",
  dateFrom: "",
  dateTo: "",
  flags: {},
  quality: 0,
  seriesSize: null,
  featuredOnly: false,
  origin: "",
  originClass: "",
  author: "",
  collapse: "none",
  total: 0,
  pages: new Map(),
  pending: new Set(),
  reqId: 0,
  selectedIndex: -1,
  visibleRows: new Map(),
  starred: new Set(),
  rejected: new Set(),
};

for (const f of FLAG_NAMES) state.flags[f] = DEFAULT_EXCLUDE.has(f) ? "exclude" : "ignore";

const $ = (sel) => document.querySelector(sel);

function buildSearchQS(extra) {
  const p = new URLSearchParams();
  p.set("q", state.q);
  p.set("mode", state.mode);
  p.set("sort", state.sort);
  if (state.dateFrom) p.set("from", state.dateFrom);
  if (state.dateTo) p.set("to", state.dateTo);
  if (state.origin) p.set("origin", state.origin);
  if (state.originClass) p.set("origin_class", state.originClass);
  if (state.author) p.set("author", state.author);
  if (state.quality > 0) p.set("min_quality", String(state.quality));
  if (state.seriesSize) p.set("min_series_size", String(state.seriesSize));
  if (state.featuredOnly) p.set("featured_only", "1");
  p.set("collapse", state.collapse);
  for (const [name, st] of Object.entries(state.flags)) {
    if (st === "require") p.append("flag_require", name);
    if (st === "exclude") p.append("flag_exclude", name);
  }
  if (!Object.values(state.flags).some((v) => v !== "ignore")) {
    // explicit signal to the server: user cleared every flag on purpose
    p.set("flag_exclude", "");
  }
  if (extra) for (const [k, v] of Object.entries(extra)) p.set(k, v);
  return p;
}

function resetResults() {
  state.pages.clear();
  state.pending.clear();
  for (const el of state.visibleRows.values()) el.remove();
  state.visibleRows.clear();
  state.reqId++;
  state.selectedIndex = -1;
  closeDrawer();
}

async function runSearch() {
  resetResults();
  $("#table-viewport").scrollTop = 0;
  const myReq = state.reqId;
  const qs = buildSearchQS({ limit: String(PAGE_SIZE), offset: "0" });
  setStatus("Searching…");
  try {
    const res = await fetch("/api/search?" + qs.toString());
    const data = await res.json();
    if (myReq !== state.reqId) return;
    if (data.error) { setStatus("Error: " + data.error); return; }
    state.total = data.total;
    state.pages.set(0, data.rows);
    $("#resultcount").textContent = data.total.toLocaleString() + " results";
    layoutSpacer();
    renderVisible();
    setStatus(`${data.total.toLocaleString()} results`);
  } catch (e) {
    setStatus("Error: " + e);
  }
}

async function fetchPage(page) {
  if (state.pages.has(page) || state.pending.has(page)) return;
  state.pending.add(page);
  const myReq = state.reqId;
  const qs = buildSearchQS({ limit: String(PAGE_SIZE), offset: String(page * PAGE_SIZE) });
  try {
    const res = await fetch("/api/search?" + qs.toString());
    const data = await res.json();
    if (myReq !== state.reqId) return;
    state.pages.set(page, data.rows);
    state.pending.delete(page);
    renderVisible();
  } catch (e) {
    state.pending.delete(page);
  }
}

function layoutSpacer() {
  $("#table-spacer").style.height = Math.max(state.total * ROW_H, 0) + "px";
}

function rowAt(index) {
  const page = Math.floor(index / PAGE_SIZE);
  const rows = state.pages.get(page);
  if (!rows) { fetchPage(page); return null; }
  return rows[index % PAGE_SIZE] || null;
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function highlightName(name) {
  const q = state.q.trim();
  if (!q || state.mode === "regex") return escapeHtml(name);
  const terms = q.replace(/[":*]/g, " ").split(/\s+/).filter((t) => t && !/^(AND|OR|NOT)$/i.test(t));
  let html = escapeHtml(name);
  for (const t of terms) {
    const esc = t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    html = html.replace(new RegExp("(" + esc + ")", "ig"), "<mark>$1</mark>");
  }
  return html;
}

function fmtDate(iso) { return iso; }

function renderRow(index, row) {
  let el = state.visibleRows.get(index);
  if (!el) {
    el = document.createElement("div");
    el.className = "row data-row";
    el.style.top = index * ROW_H + "px";
    el.style.height = ROW_H + "px";
    el.addEventListener("click", () => selectIndex(index, true));
    $("#table-spacer").appendChild(el);
    state.visibleRows.set(index, el);
  }
  el.dataset.worldId = row.id;
  el.classList.toggle("selected", index === state.selectedIndex);
  el.classList.toggle("status-star", state.starred.has(row.id));
  el.classList.toggle("status-reject", state.rejected.has(row.id));
  const flagChips = (row.flag_names || [])
    .filter((f) => f !== "f_featured")
    .slice(0, 4)
    .map((f) => `<span class="mini-flag">${f.replace("f_", "")}</span>`)
    .join("");
  const seriesChip = row.series_size && row.series_size > 1 ? `▸${row.series_size}` : "";
  el.innerHTML = `
    <div class="col-date">${fmtDate(row.iso_date)}</div>
    <div class="col-name" title="${escapeHtml(row.name)}">${highlightName(row.name)}</div>
    <div class="col-flags">${flagChips}</div>
    <div class="col-quality"><div class="qbar"><i style="width:${Math.max(row.quality_score, 0)}%"></i></div></div>
    <div class="col-series">${seriesChip}</div>
    <div class="col-origin">${row.origin || ""}</div>
  `;
}

function renderVisible() {
  const vp = $("#table-viewport");
  const scrollTop = vp.scrollTop;
  const viewH = vp.clientHeight;
  const start = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN);
  const end = Math.min(state.total, Math.ceil((scrollTop + viewH) / ROW_H) + OVERSCAN);

  for (const [idx, el] of [...state.visibleRows]) {
    if (idx < start || idx >= end) {
      el.remove();
      state.visibleRows.delete(idx);
    }
  }
  for (let i = start; i < end; i++) {
    if (state.visibleRows.has(i)) continue;
    const row = rowAt(i);
    if (row) renderRow(i, row);
  }
}

function selectIndex(index, openDrawer) {
  const prev = state.selectedIndex;
  state.selectedIndex = index;
  if (state.visibleRows.has(prev)) state.visibleRows.get(prev).classList.remove("selected");
  if (state.visibleRows.has(index)) state.visibleRows.get(index).classList.add("selected");
  const row = rowAt(index);
  if (row && openDrawer) openDrawerFor(row.id);
}

function ensureIndexVisible(index) {
  const vp = $("#table-viewport");
  const top = index * ROW_H;
  if (top < vp.scrollTop) vp.scrollTop = top;
  else if (top + ROW_H > vp.scrollTop + vp.clientHeight) vp.scrollTop = top + ROW_H - vp.clientHeight;
}

function setStatus(text) { $("#status-text").textContent = text; }

// ---- Drawer -----------------------------------------------------------

async function openDrawerFor(worldId) {
  const drawer = $("#drawer");
  drawer.classList.remove("hidden");
  $("#drawer-content").innerHTML = "<p>Loading…</p>";
  const res = await fetch(`/api/world/${worldId}`);
  const w = await res.json();
  if (w.error) { $("#drawer-content").innerHTML = `<p>${w.error}</p>`; return; }

  if (w.triage && w.triage.status === "star") state.starred.add(w.id); else state.starred.delete(w.id);
  if (w.triage && w.triage.status === "reject") state.rejected.add(w.id); else state.rejected.delete(w.id);
  // Update whichever rendered row(s) actually match this world — not
  // state.selectedIndex, which is stale when the drawer was opened via a
  // sibling/neighbour link rather than a table click.
  for (const [, el] of state.visibleRows) {
    if (Number(el.dataset.worldId) === Number(w.id)) {
      el.classList.toggle("status-star", state.starred.has(w.id));
      el.classList.toggle("status-reject", state.rejected.has(w.id));
    }
  }

  const scoreParts = (w.score_parts || [])
    .map(([label, val]) => `<div class="score-part"><span>${escapeHtml(label)}</span><span class="${val < 0 ? "neg" : "pos"}">${val > 0 ? "+" : ""}${val}</span></div>`)
    .join("");

  const siblings = (w.series_siblings || [])
    .filter((s) => s.id !== w.id)
    .map((s) => `<div class="sibling" data-id="${s.id}"><span>${escapeHtml(s.name)}</span><span>${s.version_ordinal ?? ""}</span></div>`)
    .join("") || "<p class='no-preview'>No other members.</p>";

  const similar = (w.similar_names || [])
    .map((s) => `<div class="sibling" data-name="${escapeHtml(s.name_lc)}"><span>${escapeHtml(s.name_lc)}</span><span>${s.ratio}</span></div>`)
    .join("") || "<p class='no-preview'>None found.</p>";

  const neighbours = (w.session_neighbours || [])
    .map((n) => `<div class="neighbour" data-id="${n.id}"><span>${escapeHtml(n.name)}</span><span>${n.iso_date}</span></div>`)
    .join("") || "<p class='no-preview'>No other uploads from this origin nearby.</p>";

  const featuredList = (w.featured_appearances || [])
    .map((f) => `<div class="sibling"><span>${f.snapshot_date}</span><span>#${f.rank}</span></div>`)
    .join("");

  $("#drawer-content").innerHTML = `
    <h2>${escapeHtml(w.name)}</h2>
    <div id="preview-slot"><button id="load-preview">Load preview image</button></div>
    <div class="triage-buttons">
      <button id="btn-star" class="${w.triage.status === "star" ? "active-star" : ""}">★ Star (s)</button>
      <button id="btn-reject" class="${w.triage.status === "reject" ? "active-reject" : ""}">✕ Reject (x)</button>
    </div>
    <textarea id="note-field" placeholder="Note…">${w.triage.note || ""}</textarea>
    <h4>Quality score: ${w.quality_score}</h4>
    ${scoreParts}
    <h4>ID / date</h4>
    <div class="score-part"><span>world id</span><span>${w.ts}</span></div>
    <div class="score-part"><span>uploaded</span><span>${w.iso_date}</span></div>
    <div class="score-part"><span>origin</span><span>${w.origin || "(none)"}</span></div>
    <div class="score-part"><span>source</span><span>${w.source}</span></div>
    ${featuredList ? `<h4>Featured snapshots</h4>${featuredList}` : ""}
    <h4>Same series (${(w.series_siblings || []).length})</h4>
    ${siblings}
    <h4>Similar names</h4>
    ${similar}
    <h4>Same session (±1h from this origin)</h4>
    ${neighbours}
  `;

  $("#load-preview").addEventListener("click", async () => {
    const slot = $("#preview-slot");
    slot.innerHTML = "Loading…";
    const img = new Image();
    img.className = "preview";
    img.onload = () => { slot.innerHTML = ""; slot.appendChild(img); };
    img.onerror = () => { slot.innerHTML = "<p class='no-preview'>No preview available for this world.</p>"; };
    img.src = `/api/preview/${w.ts}`;
  });
  $("#btn-star").addEventListener("click", () => triage(w.id, "star"));
  $("#btn-reject").addEventListener("click", () => triage(w.id, "reject"));
  $("#note-field").addEventListener("change", (e) => {
    // Read current status live, not the drawer-open-time snapshot in `w` —
    // the user may have starred/rejected since opening the drawer.
    const current = state.starred.has(w.id) ? "star" : state.rejected.has(w.id) ? "reject" : "none";
    saveNote(w.id, current, e.target.value);
  });
  drawer.querySelectorAll(".sibling[data-id], .neighbour[data-id]").forEach((el) => {
    el.addEventListener("click", () => openDrawerFor(el.dataset.id));
  });
  drawer.querySelectorAll(".sibling[data-name]").forEach((el) => {
    el.addEventListener("click", () => { state.q = el.dataset.name; state.mode = "lexical"; syncControls(); runSearch(); });
  });
}

async function postTriage(worldId, newStatus, note) {
  // Only include "note" in the payload when the caller explicitly passed
  // one (the drawer's note field) — omitting the key tells the server to
  // leave any existing note alone, so a star/reject toggle from the table
  // (no note in hand) can't silently wipe it.
  const body = { id: worldId, status: newStatus };
  if (note !== undefined) body.note = note;
  await fetch("/api/triage", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (newStatus === "star") { state.starred.add(worldId); state.rejected.delete(worldId); }
  else if (newStatus === "reject") { state.rejected.add(worldId); state.starred.delete(worldId); }
  else { state.starred.delete(worldId); state.rejected.delete(worldId); }
  for (const [idx, el] of state.visibleRows) {
    if (Number(el.dataset.worldId) === Number(worldId)) {
      el.classList.toggle("status-star", state.starred.has(worldId));
      el.classList.toggle("status-reject", state.rejected.has(worldId));
    }
  }
  const btnStar = $("#btn-star"), btnReject = $("#btn-reject");
  if (btnStar) btnStar.classList.toggle("active-star", newStatus === "star");
  if (btnReject) btnReject.classList.toggle("active-reject", newStatus === "reject");
}

// Toggle from a star/reject button click: "star" again on an already-starred
// world clears it back to "none".
async function triage(worldId, kind) {
  const isStarActive = state.starred.has(worldId);
  const isRejectActive = state.rejected.has(worldId);
  let newStatus = kind;
  if (kind === "star") newStatus = isStarActive ? "none" : "star";
  if (kind === "reject") newStatus = isRejectActive ? "none" : "reject";
  await postTriage(worldId, newStatus);
}

// Note field save: keep whatever status is already set, just update the note.
async function saveNote(worldId, currentStatus, note) {
  await postTriage(worldId, currentStatus, note);
}

function closeDrawer() { $("#drawer").classList.add("hidden"); }

// ---- Sidebar / filters --------------------------------------------------

function renderFlagList(counts) {
  const container = $("#flag-list");
  container.innerHTML = "";
  for (const name of FLAG_NAMES) {
    const chip = document.createElement("div");
    chip.className = "flag-chip";
    chip.dataset.state = state.flags[name];
    chip.dataset.flag = name;
    const c = counts && counts[name] !== undefined ? counts[name].toLocaleString() : "";
    chip.innerHTML = `<span>${name.replace("f_", "")}</span><span class="count">${c}</span>`;
    chip.addEventListener("click", () => {
      const order = ["ignore", "exclude", "require"];
      const next = order[(order.indexOf(state.flags[name]) + 1) % order.length];
      state.flags[name] = next;
      chip.dataset.state = next;
      runSearch();
    });
    container.appendChild(chip);
  }
}

function syncControls() {
  $("#q").value = state.q;
  $("#mode").value = state.mode;
  $("#sort").value = state.sort;
  $("#date-from").value = state.dateFrom;
  $("#date-to").value = state.dateTo;
  $("#quality").value = state.quality;
  $("#quality-val").textContent = state.quality;
  $("#series-size").value = state.seriesSize || "";
  $("#featured-only").checked = state.featuredOnly;
  $("#origin").value = state.origin;
  $("#origin-class").value = state.originClass;
  $("#author").value = state.author;
  $("#collapse").value = state.collapse;
  for (const el of document.querySelectorAll(".flag-chip")) {
    el.dataset.state = state.flags[el.dataset.flag];
  }
}

function resetFilters() {
  state.dateFrom = ""; state.dateTo = "";
  state.quality = 0; state.seriesSize = null; state.featuredOnly = false;
  state.origin = ""; state.originClass = ""; state.author = "";
  state.collapse = "none";
  for (const f of FLAG_NAMES) state.flags[f] = DEFAULT_EXCLUDE.has(f) ? "exclude" : "ignore";
  syncControls();
  runSearch();
}

// ---- Coverage banner ------------------------------------------------

async function loadStats() {
  const res = await fetch("/api/stats");
  const stats = await res.json();
  renderFlagList(stats.flag_counts);
  window.__coverageGapEnd = stats.coverage_gap_end;
  window.__coverageWarning = stats.coverage_warning;
  updateCoverageBanner();
}

function updateCoverageBanner() {
  const banner = $("#coverage-banner");
  const gapEnd = window.__coverageGapEnd || "2015-02-01";
  const reachesGap = !state.dateFrom || state.dateFrom < gapEnd;
  if (reachesGap && (state.dateFrom || state.dateTo === "" || state.dateTo < "2020-01-01")) {
    banner.textContent = "⚠ " + (window.__coverageWarning || "");
    banner.classList.remove("hidden");
  } else {
    banner.classList.add("hidden");
  }
}

// ---- Export ----------------------------------------------------------

function exportResults() {
  const qs = buildSearchQS({ format: "csv" });
  window.location = "/api/export?" + qs.toString();
}

// ---- Wiring ------------------------------------------------------------

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

function init() {
  const debouncedSearch = debounce(runSearch, 250);

  $("#q").addEventListener("input", (e) => { state.q = e.target.value; debouncedSearch(); });
  $("#mode").addEventListener("change", (e) => { state.mode = e.target.value; runSearch(); });
  $("#sort").addEventListener("change", (e) => { state.sort = e.target.value; runSearch(); });
  $("#date-from").addEventListener("change", (e) => { state.dateFrom = e.target.value; updateCoverageBanner(); runSearch(); });
  $("#date-to").addEventListener("change", (e) => { state.dateTo = e.target.value; updateCoverageBanner(); runSearch(); });
  $("#quality").addEventListener("input", (e) => { state.quality = Number(e.target.value); $("#quality-val").textContent = state.quality; });
  $("#quality").addEventListener("change", runSearch);
  $("#series-size").addEventListener("change", (e) => { state.seriesSize = e.target.value ? Number(e.target.value) : null; runSearch(); });
  $("#featured-only").addEventListener("change", (e) => { state.featuredOnly = e.target.checked; runSearch(); });
  $("#origin").addEventListener("change", (e) => { state.origin = e.target.value; runSearch(); });
  $("#origin-class").addEventListener("change", (e) => { state.originClass = e.target.value; runSearch(); });
  $("#author").addEventListener("change", (e) => { state.author = e.target.value; runSearch(); });
  $("#collapse").addEventListener("change", (e) => { state.collapse = e.target.value; runSearch(); });
  $("#reset-filters").addEventListener("click", resetFilters);
  $("#export-btn").addEventListener("click", exportResults);
  $("#drawer-close").addEventListener("click", closeDrawer);

  document.querySelectorAll(".era-presets button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const [from, to] = ERA_RANGES[btn.dataset.era];
      state.dateFrom = from; state.dateTo = to;
      syncControls();
      updateCoverageBanner();
      runSearch();
    });
  });

  $("#table-viewport").addEventListener("scroll", () => renderVisible());
  window.addEventListener("resize", () => renderVisible());

  document.addEventListener("keydown", (e) => {
    const tag = (e.target.tagName || "").toLowerCase();
    const typing = tag === "input" || tag === "textarea" || tag === "select";
    if (e.key === "/" && !typing) { e.preventDefault(); $("#q").focus(); return; }
    if (typing) return;
    if (e.key === "j") { selectIndex(Math.min(state.selectedIndex + 1, state.total - 1), false); ensureIndexVisible(state.selectedIndex); renderVisible(); }
    else if (e.key === "k") { selectIndex(Math.max(state.selectedIndex - 1, 0), false); ensureIndexVisible(state.selectedIndex); renderVisible(); }
    else if (e.key === "Enter") { const row = rowAt(state.selectedIndex); if (row) openDrawerFor(row.id); }
    else if (e.key === "s") { const row = rowAt(state.selectedIndex); if (row) triage(row.id, "star"); }
    else if (e.key === "x") { const row = rowAt(state.selectedIndex); if (row) triage(row.id, "reject"); }
    else if (e.key === "e") { exportResults(); }
    else if (e.key === "Escape") { closeDrawer(); }
  });

  loadStats();
  runSearch();
}

document.addEventListener("DOMContentLoaded", init);
