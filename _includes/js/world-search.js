const tableBody = document.querySelector("#world-table tbody");
const searchInput = document.getElementById("search");
const tagSelect = document.getElementById("tag-filter");
const dateFrom = document.getElementById("date-from");
const dateTo = document.getElementById("date-to");

let allWorlds = [];

fetch("{{ site.baseurl }}/assets/data/worlds.json")
  .then(res => res.json())
  .then(worlds => {
    allWorlds = worlds;

    populateTags(worlds);
    computeStats(worlds);
    render(worlds);
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
    <td>${(w.tags || []).join(", ")}</td>
    `;

    tableBody.appendChild(row);
  });
}

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

  const filtered = allWorlds.filter(w => {
    const text =
      `${w.worldname} ${w.author} ${(w.tags || []).join(" ")}`.toLowerCase();

    if (q && !text.includes(q)) return false;
    if (tag && !(w.tags || []).includes(tag)) return false;
    if (from && w.publishdate < from) return false;
    if (to && w.publishdate > to) return false;

    return true;
  });

  render(filtered);
}

[searchInput, tagSelect, dateFrom, dateTo].forEach(el =>
  el.addEventListener("input", applyFilters)
);
