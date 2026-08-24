"use strict";

// Live server browsing (Recent / Search / Featured / Saved) against the
// real Eden game servers, via the /api/live/* endpoints in server.py.
//
// Rate discipline, enforced here on the client too (server already caps and
// never loops, but the UI shouldn't make it easy to hammer it either):
//   - Recent only fetches on "Load next 30" click, never auto-loads.
//   - Search only fetches on submit (button/Enter), never as-you-type.
//   - Search results page client-side from the one fetched batch — paging
//     never re-hits the server.
//   - Featured is fetched once per server per session and cached client-
//     side too; "Refresh" forces exactly one more fetch.
//   - Preview images load only when a row's "Preview" button is clicked.

const liveState = {
  server: "current",
  tab: "recent",
  recent: { rows: [], nextStart: 0, hasMore: true },
  search: { rows: [], page: 0, capped: false },
  featured: { rows: null }, // per server, filled lazily
  saved: { rows: [] },
};

const $$ = (sel) => document.querySelector(sel);

function liveEscapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function liveRowHtml(row, extraButtons) {
  return `
    <div class="live-row" data-ts="${liveEscapeHtml(row.ts)}">
      <span class="live-row-ts">${liveEscapeHtml(row.ts)}</span>
      <span class="live-row-name">${liveEscapeHtml(row.name)}</span>
      <span class="live-row-actions">
        <button class="live-preview-btn" data-ts="${liveEscapeHtml(row.ts)}">Preview</button>
        ${extraButtons || ""}
      </span>
      <span class="live-preview-slot"></span>
    </div>`;
}

function wireRowActions(container, server) {
  container.querySelectorAll(".live-preview-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".live-row");
      const slot = row.querySelector(".live-preview-slot");
      if (slot.querySelector("img")) { slot.innerHTML = ""; return; }
      slot.textContent = "Loading…";
      try {
        const res = await fetch(`/api/live/preview/${btn.dataset.ts}?server=${server}`);
        if (!res.ok) { slot.textContent = "No preview."; return; }
        const blob = await res.blob();
        const img = document.createElement("img");
        img.className = "live-preview-img";
        img.src = URL.createObjectURL(blob);
        slot.innerHTML = "";
        slot.appendChild(img);
      } catch (e) {
        slot.textContent = "No preview.";
      }
    });
  });
  container.querySelectorAll(".live-save-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".live-row");
      await fetch("/api/live/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ts: row.dataset.ts, server, name: btn.dataset.name }),
      });
      btn.textContent = "Saved ✓";
      btn.disabled = true;
    });
  });
}

// ---- Recent -------------------------------------------------------------

async function liveLoadRecentPage(reset) {
  if (reset) { liveState.recent = { rows: [], nextStart: 0, hasMore: true }; }
  const st = liveState.recent;
  if (!st.hasMore) return;
  $$("#live-recent-status").textContent = "Loading…";
  const res = await fetch(`/api/live/recent?server=${liveState.server}&start=${st.nextStart}`);
  const data = await res.json();
  if (data.error) { $$("#live-recent-status").textContent = "Error: " + data.error; return; }
  st.rows = st.rows.concat(data.rows);
  st.nextStart = data.next_start;
  st.hasMore = data.has_more;
  renderLiveRecent();
  $$("#live-recent-status").textContent = `${st.rows.length} rows loaded`;
  $$("#live-recent-more").disabled = !st.hasMore;
}

function renderLiveRecent() {
  const container = $$("#live-recent-table");
  container.innerHTML = liveState.recent.rows
    .map((r) => liveRowHtml(r, `<button class="live-save-btn" data-name="${liveEscapeHtml(r.name)}">Save</button>`))
    .join("");
  wireRowActions(container, liveState.server);
}

// ---- Search ---------------------------------------------------------------

const LIVE_SEARCH_PAGE_SIZE = 50;

async function liveRunSearch() {
  const q = $$("#live-search-q").value.trim();
  if (!q) return;
  $$("#live-search-status").textContent = "Searching…";
  const res = await fetch(`/api/live/search?server=${liveState.server}&q=${encodeURIComponent(q)}`);
  const data = await res.json();
  if (data.error) { $$("#live-search-status").textContent = "Error: " + data.error; return; }
  liveState.search = { rows: data.rows, page: 0, capped: data.capped };
  renderLiveSearchPage();
}

function renderLiveSearchPage() {
  const st = liveState.search;
  const start = st.page * LIVE_SEARCH_PAGE_SIZE;
  const pageRows = st.rows.slice(start, start + LIVE_SEARCH_PAGE_SIZE);
  const container = $$("#live-search-table");
  container.innerHTML = pageRows
    .map((r) => liveRowHtml(r, `<button class="live-save-btn" data-name="${liveEscapeHtml(r.name)}">Save</button>`))
    .join("");
  wireRowActions(container, liveState.server);
  const totalPages = Math.max(1, Math.ceil(st.rows.length / LIVE_SEARCH_PAGE_SIZE));
  $$("#live-search-page").textContent = `page ${st.page + 1}/${totalPages} — ${st.rows.length} result(s)${st.capped ? " (capped)" : ""}`;
  $$("#live-search-status").textContent = "";
  $$("#live-search-prev").disabled = st.page === 0;
  $$("#live-search-next").disabled = start + LIVE_SEARCH_PAGE_SIZE >= st.rows.length;
}

// ---- Featured ---------------------------------------------------------------

async function liveLoadFeatured(refresh) {
  $$("#live-featured-status").textContent = "Loading…";
  const res = await fetch(`/api/live/featured?server=${liveState.server}${refresh ? "&refresh=1" : ""}`);
  const data = await res.json();
  if (data.error) { $$("#live-featured-status").textContent = "Error: " + data.error; return; }
  liveState.featured.rows = data.rows;
  renderLiveFeatured();
}

function renderLiveFeatured() {
  const rows = liveState.featured.rows || [];
  const container = $$("#live-featured-table");
  container.innerHTML = rows
    .map((r) => liveRowHtml(r, `<span class="live-rank">#${r.rank}</span> <button class="live-save-btn" data-name="${liveEscapeHtml(r.name)}">Save</button>`))
    .join("");
  wireRowActions(container, liveState.server);
  $$("#live-featured-status").textContent = `${rows.length} featured worlds`;
}

// ---- Saved ---------------------------------------------------------------

async function liveLoadSaved() {
  const res = await fetch("/api/live/saved");
  const data = await res.json();
  liveState.saved.rows = data.rows || [];
  renderLiveSaved();
}

function renderLiveSaved() {
  const container = $$("#live-saved-table");
  container.innerHTML = liveState.saved.rows
    .map((r) => `
      <div class="live-row" data-ts="${liveEscapeHtml(r.ts)}" data-server="${liveEscapeHtml(r.server)}">
        <span class="live-row-ts">${liveEscapeHtml(r.ts)}</span>
        <span class="live-row-name">${liveEscapeHtml(r.name)}</span>
        <span class="live-row-server">${liveEscapeHtml(r.server)}</span>
        <span class="live-row-actions">
          <button class="live-preview-btn" data-ts="${liveEscapeHtml(r.ts)}">Preview</button>
          <button class="live-unsave-btn">Remove</button>
        </span>
        <span class="live-preview-slot"></span>
      </div>`)
    .join("") || "<p class='no-preview'>Nothing saved yet.</p>";
  container.querySelectorAll(".live-preview-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".live-row");
      const slot = row.querySelector(".live-preview-slot");
      if (slot.querySelector("img")) { slot.innerHTML = ""; return; }
      slot.textContent = "Loading…";
      const res = await fetch(`/api/live/preview/${row.dataset.ts}?server=${row.dataset.server}`);
      if (!res.ok) { slot.textContent = "No preview."; return; }
      const blob = await res.blob();
      const img = document.createElement("img");
      img.className = "live-preview-img";
      img.src = URL.createObjectURL(blob);
      slot.innerHTML = "";
      slot.appendChild(img);
    });
  });
  container.querySelectorAll(".live-unsave-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".live-row");
      await fetch("/api/live/unsave", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ts: row.dataset.ts, server: row.dataset.server }),
      });
      liveLoadSaved();
    });
  });
}

// ---- Tab / server switching ------------------------------------------------

function liveSwitchTab(tab) {
  liveState.tab = tab;
  document.querySelectorAll("#live-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".live-panel").forEach((p) => p.classList.add("hidden"));
  $$(`#live-${tab}-panel`).classList.remove("hidden");
  if (tab === "recent" && liveState.recent.rows.length === 0) liveLoadRecentPage(true);
  if (tab === "featured" && !liveState.featured.rows) liveLoadFeatured(false);
  if (tab === "saved") liveLoadSaved();
}

function liveSwitchServer(server) {
  liveState.server = server;
  document.querySelectorAll("#live-server-switch button").forEach((b) => b.classList.toggle("active", b.dataset.server === server));
  liveState.featured.rows = null;
  liveLoadRecentPage(true);
  if (liveState.tab === "featured") liveLoadFeatured(false);
  $$("#live-search-table").innerHTML = "";
  $$("#live-search-page").textContent = "";
}

function liveInit() {
  $$("#view-archive-btn").addEventListener("click", () => {
    $$("#view-archive-btn").classList.add("active");
    $$("#view-live-btn").classList.remove("active");
    $$("#live-view").classList.add("hidden");
    $$("#body").classList.remove("hidden");
    $$("#searchbar").classList.remove("hidden");
  });
  $$("#view-live-btn").addEventListener("click", () => {
    $$("#view-live-btn").classList.add("active");
    $$("#view-archive-btn").classList.remove("active");
    $$("#live-view").classList.remove("hidden");
    $$("#body").classList.add("hidden");
    $$("#searchbar").classList.add("hidden");
    closeDrawer();
    if (liveState.recent.rows.length === 0) liveLoadRecentPage(true);
  });

  document.querySelectorAll("#live-server-switch button").forEach((b) => {
    b.addEventListener("click", () => liveSwitchServer(b.dataset.server));
  });
  document.querySelectorAll("#live-tabs button").forEach((b) => {
    b.addEventListener("click", () => liveSwitchTab(b.dataset.tab));
  });

  $$("#live-recent-first").addEventListener("click", () => liveLoadRecentPage(true));
  $$("#live-recent-more").addEventListener("click", () => liveLoadRecentPage(false));

  $$("#live-search-btn").addEventListener("click", liveRunSearch);
  $$("#live-search-q").addEventListener("keydown", (e) => { if (e.key === "Enter") liveRunSearch(); });
  $$("#live-search-prev").addEventListener("click", () => { if (liveState.search.page > 0) { liveState.search.page--; renderLiveSearchPage(); } });
  $$("#live-search-next").addEventListener("click", () => { liveState.search.page++; renderLiveSearchPage(); });

  $$("#live-featured-refresh").addEventListener("click", () => liveLoadFeatured(true));
}

document.addEventListener("DOMContentLoaded", liveInit);
