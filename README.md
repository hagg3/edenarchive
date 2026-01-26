# Eden Worlds Archive

The core purpose of the project is to maintain a **curated catalogue of high-quality Eden world files**, rather than a raw or complete bulk archive. Over the lifetime of the game, tens of thousands of worlds were uploaded. Thousands of these worlds are spam uploads, or minor revisions of existing. Attempting to archive everything would significantly reduce the usefulness of the collection.

Instead, this site focuses on:

- Worlds that appeared on **official or in-game featured lists** throughout Eden’s history  
- **Notable community creations** and “hidden gems” discovered through the later shared-worlds upload and search systems  
- Select **historically or technically significant versions** of worlds, where older iterations meaningfully demonstrate how a world evolved over time  

Older versions are only archived where they add value; this is not intended to be a version-complete mirror of the Eden servers.

There already exists a fan-maintained project at (https://eden.anmon.org/) that aims to mass archive and preserve worlds. It even includes a feature that allows you to quickly archive a world from the game servers, provided that you know the world ID.

## Community and Discussion

If you are interested in Eden preservation, world building, or archival work, you may also want to join the following Discord servers:

- **Community Project Discord:** https://discord.gg/SgEQfurMmj  
- **Official Eden Discord:** http://discord.gg/rjYXwBC  

## Project Status Notes

- This site is **actively under development**  
- Some metadata (such as file size for worlds uploaded using the newer parser) may be inaccurate and will be corrected or removed in future updates  

Expect gradual improvements rather than rapid iteration.


## Improved Discoverability

One of the main motivations for this project is the **poor usability of Eden’s in-game world search**, particularly in later years when spam uploads overwhelmed meaningful content.

To address this, all archived worlds are organized using a **manual tagging system**. Tags allow worlds to be browsed and filtered by type and theme. For example:

- City builds  
- Parkour / challenge maps  
- Castles and historical builds  
- Experimental or technical worlds  

This makes it significantly easier to discover worlds by interest rather than by filename, author, or upload date alone.

## Temporary Documentation

TO-DO: I will eventually write up a comprehensive and properly written README outlining the site's purpose and how it works technically. For now, below is generated overview.

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