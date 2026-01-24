# Documentation

## Purpose

This document describes the structure, data model, and content pipeline of the EdenWorlds Jekyll site. It is intended for maintainers and contributors who need to understand how worlds are stored, indexed, rendered, and uploaded.

The site is deliberately designed to behave like a lightweight database on top of a static site generator.

---

## High‑Level Architecture

- **Static site generator:** Jekyll (GitHub Pages compatible)
    
- **Content model:** One Markdown file per world (front‑matter driven)
    
- **Assets:** World files, preview images, and maps stored separately from content entries
    
- **Indexing:** Jekyll collections + Liquid filters
    
- **Automation:** Python script for bulk world ingestion
    

There is no runtime backend. All querying and filtering is done at build time.

---

## Repository Structure (Simplified)

```
/
├── _config.yml
├── _layouts/
├── _includes/
├── _worlds/               # World metadata entries (collection)
│   ├── 1584568651.md
│   ├── 1584569002.md
│   └── ...
├── assets/
│   ├── worldfiles/         # Raw .eden world files
│   │   ├── 1584568651.eden
│   │   └── ...
│   ├── previews/           # Preview images
│   └── maps/               # Optional map images
├── scripts/
│   └── upload_worlds.py    # Automation script
├── index.md
└── _site/                  # Generated output (ignored by Git)
```

---

## World Files (`assets/worldfiles`)

- Stores the **raw, downloadable world files** (e.g. `.eden`).
    
- Files are not processed by Jekyll.
    
- Naming convention typically matches the world entry filename or ID.
    

Example:

```
assets/worldfiles/1584568651.eden
```

These files are linked from the rendered world pages but never duplicated into `_site` manually.

---

## World Entries (`_worlds` Collection)

`_worlds` is a custom Jekyll collection that acts as the site’s primary data store.

Each file represents **one world** and contains:

- Structured metadata (YAML front matter)
    
- Optional descriptive content (Markdown)
    

### Example World Entry

```yaml
---
layout: page
filename: 1584568651.eden
worldname: Video Game Museum
publishdate: 2011-07-12
archivedate: 2025-10-31
filesize: "13.1 MB"
author: Davey Todd
tags:
  - old
  - veryoldterrain
  - oldc
---

Optional description text.
```

### Key Fields

|Field|Purpose|
|---|---|
|`filename`|Links entry to file in `assets/worldfiles`|
|`worldname`|Human‑readable title|
|`publishdate`|Original creation or release date|
|`archivedate`|Date added to EdenWorlds|
|`author`|World creator|
|`tags`|Used for filtering and search|

The front matter is authoritative. Templates never infer metadata from filenames.

---

## Database‑Like Behaviour

Although Jekyll is static, the site functions as a database via:

- **Collections:** `_worlds` exposes `site.worlds`
    
- **Liquid filters:** sort, where, group_by
    
- **Derived indexes:** pages for tags, authors, dates
    

### Supported Queries

Worlds can be filtered or sorted by:

- Name
    
- Author
    
- Tags
    
- Publish date
    
- Archive date
    

All queries are resolved at build time.

---

## Pages and Indexes

Typical generated pages include:

- **World listing pages** (all worlds, paginated)
    
- **Tag pages** (all worlds with a given tag)
    
- **Author pages** (all worlds by one author)
    
- **Individual world pages**
    

These pages iterate over `site.worlds` and apply Liquid filters.

---

## Automation Script (`upload_worlds.py`)

A Python script is used to automate ingestion of new worlds.

### Responsibilities

- Scan a directory of raw world files
    
- Generate matching `_worlds` Markdown entries
    
- Normalize filenames and slugs
    
- Copy assets into `assets/worldfiles`
    
- Optionally handle preview images
    

### Why Automation Exists

Manual entry does not scale. The script enforces:

- Consistent naming
    
- Required metadata presence
    
- Deterministic IDs
    

This prevents silent data drift and broken links.

### Script Location

```
z_add_world.py
```

The script is run **before committing** changes to Git.

### Script Usage

```
python3 z_add_world.py --eden *path-to-file*
```

The script is run **before committing** changes to Git.

---

## Build Output (`_site`)

- `_site` is **generated**, not authored
    
- Contains the fully rendered static site
    
- Must be excluded via `.gitignore`
    

Never edit `_site` directly.

---

## Design Constraints

- GitHub Pages compatibility (no custom plugins)
    
- Static‑only hosting
    
- Deterministic builds
    
- Human‑readable content files
    

The system trades runtime flexibility for long‑term archival stability.

---

## Common Mistakes

- Committing `_site`
    
- Editing generated files instead of source
    
- Mismatched `filename` vs actual world file
    
- Adding metadata outside front matter
    

---

## Summary

- `_worlds` = metadata database
    
- `assets/worldfiles` = raw downloadable content
    
- Liquid templates = query layer
    
- Python script = ingestion pipeline
    

This architecture is intentionally simple, explicit, and archival‑friendly.