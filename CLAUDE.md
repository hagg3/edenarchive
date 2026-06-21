# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

A curated Jekyll static site that archives high-quality world files from the mobile game *Eden World Builder*. The site is hosted on GitHub Pages at `hagg3.github.io/edenarchive`. It is not a mass archive — it focuses on featured, community-notable, or historically significant worlds only.

There is no backend. All querying and filtering happens at build time (Jekyll/Liquid) or in the browser (client-side JS consuming a generated JSON feed).

## Local Development

```bash
bundle install           # install Jekyll and dependencies
bundle exec jekyll serve # serve locally at http://localhost:4000/edenarchive
```

The site is GitHub Pages compatible (`gem "github-pages"`) — do not use plugins that are incompatible with GitHub Pages.

## World Entry Data Model

Each world is a Markdown file in `_worlds/` with YAML front matter as the authoritative metadata. The Markdown body is secondary (description text only).

```yaml
---
layout: page
filename: 1330091988.eden        # links to assets/worldfiles/<id>/
worldname: A Fine City To Explore
publishdate: 2012-02-24          # derived from unix timestamp of world ID
author: Some Author
tags:
  - city
  - old
---
```

Key conventions:
- **`filename`** must be `<world_id>.eden` — this is what all asset paths are derived from
- **`publishdate`** is the Unix timestamp of the world ID converted to a date (`datetime.date.fromtimestamp(int(world_id))`) — don't invent it
- **`tags`** must be a YAML list of lowercase strings, never a plain string
- The `_worlds/` slug (filename) is derived by `slugify(worldname)` — lowercase, non-alphanumeric → `-`, deduped
- `archivedate` and `filesize` fields exist in some entries but are currently suppressed in the rendered template; treat them as optional

## Asset Layout

Every world's assets live under `assets/worldfiles/<world_id>/`:

```
assets/worldfiles/1330091988/
  1330091988.eden.zip   # required — compressed world file for download
  1330091988.eden.png   # optional — in-game preview screenshot
  map.png               # optional — generated top-down map
  <worldname>           # zero-byte sentinel file (world name as filename, no extension)
```

The download link in `_includes/world-download.html` constructs its URL from `page.filename`, so `filename` in front matter must exactly match the actual zip basename (`<id>.eden.zip`).

## JSON Feed

`worlds.json` at the repo root is **not static JSON** — it is a Jekyll Liquid page with permalink `/assets/data/worlds.json`. It renders from `_includes/worlds.json` (a Liquid template iterating `site.worlds`). The client-side search at `/worlds/` fetches this generated URL. Never edit `worlds.json` directly as static data.

## Content Pipeline — Adding Worlds

The primary ingestion script is `z_add_world.py` (interactive, run from repo root):

```bash
# Single file
python3 z_add_world.py --eden "My World 1644212230 city.eden.zip"

# Batch directory
python3 z_add_world.py --folder /path/to/folder
```

The script:
1. Parses the filename convention `<World Name> <10-digit-id> <tags>.eden.zip` to pre-fill prompts
2. Prompts for world name, author, tags (interactive — skips if already set from filename)
3. Extracts `.eden` from zip, compresses to `<id>.eden.zip` in `assets/worldfiles/<id>/`
4. Attempts to download the preview image from `http://files.edengame.net/<id>.eden.png`
5. Writes `_worlds/<slug>.md` if it does not already exist

`script.py` in the root is a duplicate of `z_add_world.py` — use `z_add_world.py` as the canonical version.

## Admin CLI

`admin/edenadmin.py` is a unified CLI wrapping all maintenance operations:

```bash
# Import worlds (delegates to z_add_world.py)
python3 admin/edenadmin.py import --eden file1.zip file2.zip
python3 admin/edenadmin.py import --folder /path/to/folder

# Download worlds from Eden servers (uses z_AutoDownloader/fetch_worlds.py)
python3 admin/edenadmin.py download
python3 admin/edenadmin.py download --list my_worlds.txt

# Validate all _worlds entries against assets
python3 admin/edenadmin.py validate
python3 admin/edenadmin.py validate --out admin/reports/validation.json

# Tag maintenance
python3 admin/edenadmin.py tags analyze   # find similar/mergeable tags
python3 admin/edenadmin.py tags merge     # apply tag_map.yaml renames
```

Validation checks: valid front matter, `filename` format, existence of asset dir, `.eden.zip`, preview PNG, map PNG, valid `publishdate`/`archivedate` format, tags as list.

## Downloading Worlds from Eden Servers

`z_AutoDownloader/fetch_worlds.py` fetches `.eden` files directly from Eden's servers:

```bash
# By name search (one name per line in worlds.txt)
cd z_AutoDownloader && python3 fetch_worlds.py

# By explicit ID/name pairs (alternating lines: ID, then name)
cd z_AutoDownloader && python3 fetch_worlds.py --ids
```

Downloaded files are saved as `<World Name> <id>.eden.zip` into `z_AutoDownloader/downloads/`, ready for import via `z_add_world.py`.

## Shortlisting Candidate Worlds

`admin/shortlist_worlds.py` scores worlds from an Eden server file list (`file_list2 260202.txt`) to identify candidates worth archiving:

```bash
python3 admin/shortlist_worlds.py --list "file_list2 260202.txt"
# Outputs admin/reports/shortlist.txt and shortlist.json
```

Already-archived world IDs (present in `_worlds/`) are automatically excluded from results.

## Tag Maintenance

Tags are lowercase strings in a YAML list. To clean up inconsistencies:

1. `python3 admin/edenadmin.py tags analyze` — prints fuzzy-matched groups of similar tags
2. Create/edit `z_scripts/tag manage/tag_map.yaml` with rename mappings (`old_tag: new_tag`)
3. `python3 admin/edenadmin.py tags merge` — rewrites all `_worlds/*.md` front matter using the map

`z_scripts/remove_frontmatter_fields.py` bulk-removes named fields from all world entries (edit `FIELDS_TO_REMOVE` in the script before running).

## What Not to Do

- Never commit or edit `_site/` — it is the Jekyll build output and is gitignored
- Never edit front matter fields outside the YAML block (metadata lives only in front matter)
- Do not create a `_worlds/` entry without a corresponding `assets/worldfiles/<id>/` directory containing at least the `.eden.zip`
- Do not use Jekyll plugins incompatible with GitHub Pages
