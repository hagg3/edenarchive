const tableBody = document.querySelector("#world-table tbody");
const searchInput = document.getElementById("search");
const tagSelect = document.getElementById("tag-filter");
const dateFrom = document.getElementById("date-from");
const dateTo = document.getElementById("date-to");

let allWorlds = [];

fetch("/assets/data/worlds.json")
  .then(res => res.json())
  .then(worlds => {
    allWorlds = worlds;
    populateTags(worlds);
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
      <td><a href="${w.url}">${w.worldname}</a></td>
      <td>${w.author || ""}</td>
      <td>${w.publishdate || ""}</td>
      <td>${w.archivedate || ""}</td>
      <td>${w.filesize || ""}</td>
      <td>${(w.tags || []).join(", ")}</td>
    `;
    tableBody.appendChild(row);
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
