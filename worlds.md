---
layout: page
title: Worlds Archive
permalink: /worlds/
---
## Introduction
This page contains a list of every world contained in the curated archive. All archived worlds are organized using a **manual tagging system**. Tags allow worlds to be browsed and filtered by type and theme.

An unresolved bug in the latest version of Eden has meant that the vast majority of newly uploaded worlds in the last 1-2 years do not contain a preview image. We are trying to remedy this by providing custom preview images for each world. For now however, many pages and entries in the table below will show missing image errors.

## Downloads and File Handling

World files hosted on this site are **compressed for download**.

- After downloading, you must **extract the archive** before importing the world into Eden. 
- In some cases, files may be **double-compressed** .
- Extraction is successful once you are left with a `.eden` file that is **larger than the originally downloaded archive**.

If you end up with a usable `.eden` file, the extraction has worked correctly.

## Archive Statistics

<div id="world-stats" class="world-stats">
  <ul>
    <li><strong>Total worlds archived:</strong> <span id="stat-total">–</span></li>
    <li><strong>Top tags:</strong> <span id="stat-top-tags">–</span></li>
    <li><strong>Most recently added:</strong>
      <ul id="stat-recent"></ul>
    </li>
    <li><strong>Unique authors:</strong> <span id="stat-authors">–</span></li>
  </ul>
</div>


## Browse Worlds

<input id="search" type="text" placeholder="Search name, author, tags…" />

<label>
  From:
  <input id="date-from" type="date">
</label>

<label>
  To:
  <input id="date-to" type="date">
</label>

<label>
  Tag:
  <select id="tag-filter">
    <option value="">All</option>
  </select>
</label>

<table id="world-table">
  <thead>
    <tr>
      <th>Preview</th>
      <th>World</th>
      <th>Author</th>
      <th>Published</th>
      <th>Tags</th>
    </tr>
  </thead>
  <tbody></tbody>
</table>

<script>
{% include js/world-search.js %}
</script>

