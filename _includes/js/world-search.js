const PAGE_SIZE = 40;

const tableBody = document.querySelector("#world-table tbody");
const searchInput = document.getElementById("search");
const tagSelect = document.getElementById("tag-filter");
const dateFrom = document.getElementById("date-from");
const dateTo = document.getElementById("date-to");
const pagePrev = document.getElementById("page-prev");
const pageNext = document.getElementById("page-next");
const pageStatus = document.getElementById("page-status");

let allWorlds = [];
let filteredWorlds = [];
let currentPage = 1;

fetch("{{ site.baseurl }}/assets/data/worlds.json")
  .then(res => res.json())
  .then(worlds => {
    allWorlds = worlds;

    populateTags(worlds);
    computeStats(worlds);

    // A tag link (e.g. from a world page) arrives as ?tag=City — honor it on
    // load so those links are shareable/bookmarkable, not just a client-side
    // filter state that resets on navigation.
    const params = new URLSearchParams(window.location.search);
    const tagParam = params.get("tag");
    if (tagParam && [...tagSelect.options].some(o => o.value === tagParam)) {
      tagSelect.value = tagParam;
    }

    applyFilters();
  });

function populateTags(worlds) {
  const tags = new Set();
  worlds.forEach(w => (w.tags || []).forEach(t => tags.add(t)));

  [...tags].sort().forEach(tag => {
    const opt = document.createElement("option");
    opt.value = tag;
    opt.textContent = tag;
    tagSelect.appendChild(opt);
  });
}

function render(worlds) {
  tableBody.innerHTML = "";

  worlds.forEach(w => {
    const row = document.createElement("tr");
    const tagLinks = (w.tags || [])
      .map(t => `<a href="?tag=${encodeURIComponent(t)}" class="tag-link">${t}</a>`)
      .join(", ");
    row.innerHTML = `
    <td class="preview-cell">
        ${w.filename ? `
        <img
         src="{{ site.baseurl }}/assets/worldfiles/${w.filename.replace('.eden','')}/${w.filename}.png"
         alt="Preview of ${w.worldname}"
            loading="lazy"
        >
        ` : ``}
    </td>
    <td><a href="{{ site.baseurl }}${w.url}">${w.worldname}</a></td>
    <td>${w.author || ""}</td>
    <td>${w.publishdate || ""}</td>
    <td>${tagLinks}</td>
    <td>${w.filename ? `<a href="https://hagg3.github.io/Emod/public/eden-st.html?build=rel&playworld=${encodeURIComponent(w.filename.replace('.eden',''))}">Play</a>` : ""}</td>
    `;

    tableBody.appendChild(row);
  });

  // Tag links reuse the same client-side filter instead of a full page
  // navigation to themselves.
  tableBody.querySelectorAll(".tag-link").forEach(a => {
    a.addEventListener("click", evt => {
      evt.preventDefault();
      const tag = new URLSearchParams(a.search).get("tag");
      tagSelect.value = tag;
      applyFilters();
      window.scrollTo({ top: document.getElementById("world-table").offsetTop - 20, behavior: "smooth" });
    });
  });
}

function renderPage() {
  const pages = Math.max(1, Math.ceil(filteredWorlds.length / PAGE_SIZE));
  currentPage = Math.min(Math.max(1, currentPage), pages);

  const start = (currentPage - 1) * PAGE_SIZE;
  render(filteredWorlds.slice(start, start + PAGE_SIZE));

  pageStatus.textContent = filteredWorlds.length
    ? `Page ${currentPage} of ${pages} (${filteredWorlds.length} worlds)`
    : "No worlds match these filters";
  pagePrev.disabled = currentPage <= 1;
  pageNext.disabled = currentPage >= pages;
}

pagePrev.addEventListener("click", () => { currentPage--; renderPage(); });
pageNext.addEventListener("click", () => { currentPage++; renderPage(); });

function computeStats(worlds) {
  // --- Total worlds ---
  document.getElementById("stat-total").textContent = worlds.length;

  // --- Unique authors ---
  const authors = new Set(
    worlds.map(w => w.author).filter(Boolean)
  );
  document.getElementById("stat-authors").textContent = authors.size;

  // --- Top 3 tags ---
  const tagCounts = {};
  worlds.forEach(w => {
    (w.tags || []).forEach(tag => {
      tagCounts[tag] = (tagCounts[tag] || 0) + 1;
    });
  });

  const topTags = Object.entries(tagCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([tag, count]) => `${tag} (${count})`);

  document.getElementById("stat-top-tags").textContent =
    topTags.length ? topTags.join(", ") : "—";

  // --- 3 most recent worlds ---
  const recentList = document.getElementById("stat-recent");
  recentList.innerHTML = "";

  const recentWorlds = worlds
    .filter(w => w.publishdate)
    .sort((a, b) => b.publishdate.localeCompare(a.publishdate))
    .slice(0, 3);

  recentWorlds.forEach(w => {
    const li = document.createElement("li");
    li.innerHTML = `<a href="{{ site.baseurl }}${w.url}">${w.worldname}</a> (${w.publishdate})`;
    recentList.appendChild(li);
  });
}


function applyFilters() {
  const q = searchInput.value.toLowerCase();
  const tag = tagSelect.value;
  const from = dateFrom.value;
  const to = dateTo.value;

  filteredWorlds = allWorlds.filter(w => {
    const text =
      `${w.worldname} ${w.author} ${(w.tags || []).join(" ")}`.toLowerCase();

    if (q && !text.includes(q)) return false;
    if (tag && !(w.tags || []).includes(tag)) return false;
    if (from && w.publishdate < from) return false;
    if (to && w.publishdate > to) return false;

    return true;
  });

  currentPage = 1;

  // Keep the tag filter shareable in the URL without a full navigation.
  const params = new URLSearchParams(window.location.search);
  if (tag) params.set("tag", tag); else params.delete("tag");
  const query = params.toString();
  history.replaceState(null, "", query ? `?${query}` : window.location.pathname);

  renderPage();
}

[searchInput, tagSelect, dateFrom, dateTo].forEach(el =>
  el.addEventListener("input", applyFilters)
);
