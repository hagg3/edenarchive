# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

A curated Jekyll static site that archives high-quality world files from the mobile game *Eden World Builder*. The site is hosted on GitHub Pages at `hagg3.github.io/edenarchive`. It is not a mass archive — it focuses on featured, community-notable, or historically significant worlds only.

There is no backend. All querying and filtering happens at build time (Jekyll/Liquid) or in the browser (client-side JS consuming a generated JSON feed).

## Local Development

```bash
bundle install           # install Jekyll and dependencies
bundle exec jekyll serve # serve locally at http://localhost:4000/edenarchive
The site is GitHub Pages compatible (gem "github-pages") — do not use plugins that are incompatible with GitHub Pages.

World Entry Data Model
Each world is a Markdown file in _worlds/ with YAML front matter as the authoritative metadata. The Markdown body is secondary (description text only).

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
Key conventions:

filename must be <world_id>.eden — this is what all asset paths are derived from
publishdate is the Unix timestamp of the world ID converted to a date (datetime.date.fromtimestamp(int(world_id))) — don't invent it
tags must be a YAML list of lowercase strings, never a plain string
The _worlds/ slug (filename) is derived by slugify(worldname) — lowercase, non-alphanumeric → -, deduped
archivedate and filesize fields exist in some entries but are currently suppressed in the rendered template; treat them as optional
Asset Layout
Every world's assets live under assets/worldfiles/<world_id>/:

assets/worldfiles/1330091988/
  1330091988.eden.zip   # required — compressed world file for download
  1330091988.eden.png   # optional — in-game preview screenshot
  map.png               # optional — generated top-down map
  <worldname>           # zero-byte sentinel file (world name as filename, no extension)
The download link in _includes/world-download.html constructs its URL from page.filename, so filename in front matter must exactly match the actual zip basename (<id>.eden.zip).

Zip packaging variations in the wild:

Standard: outer zip → raw .eden
Common: outer zip → gzip-compressed .eden named *.eden.zip (gzip magic 1f 8b, not a real zip)
Rare: outer zip contains the entire .eden.zip bundle from the Eden server download
Rare: zip has a non-standard name (e.g. 18 04 14 Interior Design 2.1.zip instead of <id>.eden.zip)
generate_missing_maps.py and node-mapgen handle all three packaging patterns. World.ts auto-detects gzip vs raw. The batch script falls back to any *.zip in the asset dir when the standard-named zip is absent.

Map Generation (node-mapgen/)
Renders a 2D top-down PNG of an Eden world: finds the highest non-air block per column and colors it using a flat palette (MapColors.ts).

cd node-mapgen && npm install        # first time only
node dist/generate-map.js <eden_file> <output.png>
# or without pre-compiling:
npx ts-node src/generate-map.ts <eden_file> <output.png>
Key files:

src/World.ts — parses .eden binary; handles gzip (via pako) and raw; reads chunk pointer table; signed i16 chunk coordinates
src/renderNormalMap.ts — iterates all 16 bands top-down, bounds-checks every access, finds highest non-air block per column
src/MapColors.ts — flat RGB palette (54 paint colors + 127 block-type colors)
src/generate-map.ts — CLI entry point; uses pngjs to write PNG; slices buffer.buffer to byteOffset..+byteLength to handle Node.js buffer pool correctly
dist/ — compiled JS (run npx tsc to rebuild after editing TypeScript)
node-mapgen-broken/ is the old non-working version kept for history — do not use it.

Known limitation: cannot render worlds that decompress to >~2 GB (Node.js ArrayBuffer limit). 12 worlds in the archive fall into this category (e.g. Starling City at 8.8 GB). The Rust rendering pipeline in eden-world-editor handles these via memory-mapped files; a standalone Rust CLI could be added later.

Batch Map Generation
generate_missing_maps.py (repo root) generates map.png for every world that is missing one.

python3 generate_missing_maps.py              # generate all missing maps
python3 generate_missing_maps.py --dry-run    # list which are missing without generating
python3 generate_missing_maps.py --limit 10   # process first 10
python3 generate_missing_maps.py --world-id 1315348100  # one specific world
Extracts each .eden.zip into .mapgen-tmp/ (gitignored, repo root), generates map.png, then immediately deletes the extracted file before moving to the next world — never holds more than one unzipped world on disk at a time. Uses compiled JS (dist/) if present, otherwise falls back to npx ts-node.

JSON Feed
worlds.json at the repo root is not static JSON — it is a Jekyll Liquid page with permalink /assets/data/worlds.json. It renders from _includes/worlds.json (a Liquid template iterating site.worlds). The client-side search at /worlds/ fetches this generated URL. Never edit worlds.json directly as static data.

Content Pipeline — Adding Worlds
The primary ingestion script is z_add_world.py (interactive, run from repo root):

# Single file
python3 z_add_world.py --eden "My World 1644212230 city.eden.zip"

# Batch directory
python3 z_add_world.py --folder /path/to/folder
The script:

Parses the filename convention <World Name> <10-digit-id> <tags>.eden.zip to pre-fill prompts
Prompts for world name, author, tags (interactive — skips if already set from filename)
Extracts .eden from zip, compresses to <id>.eden.zip in assets/worldfiles/<id>/
Attempts to download the preview image from http://files.edengame.net/<id>.eden.png
Generates map.png via node-mapgen and writes it to assets/worldfiles/<id>/map.png
Writes _worlds/<slug>.md if it does not already exist
script.py in the root is a duplicate of z_add_world.py — use z_add_world.py as the canonical version.

Admin CLI
admin/edenadmin.py is a unified CLI wrapping all maintenance operations:

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
Validation checks: valid front matter, filename format, existence of asset dir, .eden.zip, preview PNG, map PNG, valid publishdate/archivedate format, tags as list.

Downloading Worlds from Eden Servers
z_AutoDownloader/fetch_worlds.py fetches .eden files directly from Eden's servers:

# By name search (one name per line in worlds.txt)
cd z_AutoDownloader && python3 fetch_worlds.py

# By explicit ID/name pairs (alternating lines: ID, then name)
cd z_AutoDownloader && python3 fetch_worlds.py --ids
Downloaded files are saved as <World Name> <id>.eden.zip into z_AutoDownloader/downloads/, ready for import via z_add_world.py.

Shortlisting Candidate Worlds
admin/shortlist_worlds.py scores worlds from an Eden server file list (file_list2 260202.txt) to identify candidates worth archiving:

python3 admin/shortlist_worlds.py --list "file_list2 260202.txt"
# Outputs admin/reports/shortlist.txt and shortlist.json
Already-archived world IDs (present in _worlds/) are automatically excluded from results.

Tag Maintenance
Tags are lowercase strings in a YAML list. To clean up inconsistencies:

python3 admin/edenadmin.py tags analyze — prints fuzzy-matched groups of similar tags
Create/edit z_scripts/tag manage/tag_map.yaml with rename mappings (old_tag: new_tag)
python3 admin/edenadmin.py tags merge — rewrites all _worlds/*.md front matter using the map
z_scripts/remove_frontmatter_fields.py bulk-removes named fields from all world entries (edit FIELDS_TO_REMOVE in the script before running).

What Not to Do
Never commit or edit _site/ — it is the Jekyll build output and is gitignored
Never edit front matter fields outside the YAML block (metadata lives only in front matter)
Do not create a _worlds/ entry without a corresponding assets/worldfiles/<id>/ directory containing at least the .eden.zip
Do not use Jekyll plugins incompatible with GitHub Pages
Do not pass a directory path to node-mapgen — it expects the full map.png output path, not a directory
---
Changes from the original:
- Added the **zip packaging variations** paragraph under Asset Layout (the three patterns + non-standard naming)
- Added the **Map Generation** section covering `node-mapgen/`, CLI usage, key files, the buffer pool fix note, and the >2 GB limitation
- Added the **Batch Map Generation** section for `generate_missing_maps.py`
- Added step 5 to the `z_add_world.py` pipeline (map generation)
- Added one bullet to "What Not to Do" about the directory-vs-file path issue
