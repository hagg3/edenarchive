# Eden Worlds Archive — Project Context

Static archive site for Eden world files, hosted on GitHub Pages.
URL: `https://hagg3.github.io/edenarchive`

## Stack

| Layer | Choice |
|---|---|
| Site | Jekyll (GitHub Pages), Minima theme |
| Collections | `_worlds/` (768 entries), `_articles/` |
| Scripting | Python 3 (admin/import/batch tools) |
| Map rendering | TypeScript + Node.js (`node-mapgen/`) |
| Admin app | FastAPI + Jinja2 + HTMX, local-only (`admin/`) |

## Repository Structure

```
_worlds/            # One .md per world (YAML front matter + content)
_articles/          # Long-form articles (separate collection)
assets/worldfiles/  # Per-world assets: {id}/{id}.eden.zip, map.png, {id}.eden.png
node-mapgen/        # TypeScript CLI: renders .eden files to top-down PNG maps
node-mapgen-broken/ # Old broken version (kept for history, not used)
z_add_world.py      # Interactive importer: one or many worlds at once
generate_missing_maps.py  # Batch-generate map.png for worlds that lack one
admin/              # Admin app (web UI) + core library + edenadmin.py CLI
z_AutoDownloader/   # Bulk download helper (fetch_worlds.py)
z_scripts/          # Tag analysis/merge utilities (see warnings below)
ADMIN_APP_PLAN.md   # Admin app design + roadmap; read before extending admin/
```

## ⚠️ Never `yaml.dump` a world file

**This is the single biggest correctness risk in the repo.** The `_worlds/*.md` front matter was
hand-emitted by `z_add_world.py:190-201`, not written by a YAML library, and the corpus depends
on those exact bytes:

- Empty values are written `key: ` **with a trailing space**. 598 files have `author: `; zero
  have a bare `author:`.
- `filesize` is **always** double-quoted (`filesize: "3.5 MB"`). Nothing else ever is.
- Tags are block sequences: `tags:` then `  - tag` at 2-space indent.
- Files are LF and ASCII. All 208 `archivedate:` lines are currently empty.

`yaml.safe_dump` destroys all of this — it unquotes `filesize`, turns an empty `archivedate:`
into `archivedate: null`, and re-wraps the file, producing a huge spurious diff.

**Anything that modifies a world file must go through `admin/core/frontmatter.py`**, which uses
YAML only to *read* and edits the original lines in place, leaving every untouched line
byte-identical. Its invariant — `render(parse(f)) == f` for all 775 markdown files — is enforced
by `admin/tests/`. Run it after touching that module:

```bash
admin/.venv/bin/python -m pytest admin/tests -q     # must be 782/782
```

`z_scripts/tag manage/merge_tags.py` violates this today and corrupts the formatting of every
file it touches. Do not use it; do not copy its `save_file()`.

## Admin App (`admin/`)

Local-only web app for browsing and curating the archive. Writes plain files into the working
tree; the archivist reviews with `git diff` and pushes. It never talks to GitHub, and never runs
`add`/`commit`/`push`/`checkout`/`reset`.

```bash
./admin/run.sh          # → http://127.0.0.1:8765 (creates admin/.venv on first run)
```

```
admin/core/       # pure library, no FastAPI imports, usable from CLI scripts
  paths.py        # all repo paths; validates every write stays inside the archive
  frontmatter.py  # ★ format-preserving parse/render (see warning above)
  world.py        # World record: front matter + assets on disk; validate()
  index.py        # SQLite cache + incremental scanner + FTS search
  git.py          # read-only git
admin/app/        # FastAPI + Jinja2 + HTMX; templates/, static/ (htmx vendored, no CDN)
admin/tests/      # the front-matter round-trip test — gates all write features
admin/.runtime/   # gitignored: index.db, backups/. Disposable — markdown is the truth.
```

**Status: M0 (read-only) is shipped** — dashboard, world search/filter, world detail, git panel.
Editing, map generation, tag health, dupe detection and the upload flow are M1–M6. The roadmap,
the design rationale, and the findings behind them are in `ADMIN_APP_PLAN.md`.

The SQLite index at `admin/.runtime/index.db` is a disposable cache — delete it and it rebuilds
on next start. Markdown is always the source of truth. Cold scan of 768 worlds: ~1.4s.

## World Page Format

Each `_worlds/{slug}.md` has YAML front matter:

```yaml
---
layout: page
filename: 1315348100.eden       # numeric Unix-timestamp ID + .eden suffix
worldname: Olympics by Dante
publishdate: 2011-09-07         # derived from timestamp
archivedate: 2024-01-15         # when it was added to the archive (optional)
filesize: "2.3 MB"
author: Dante
tags:
  - sport
  - stadium
---
```

Page body typically: description, preview image `{id}.eden.png`, `{% include world-details.html %}`, `{% include world-download.html %}`, and a `## Map` section with `map.png`.

## Asset Layout

```
assets/worldfiles/{world_id}/
├── {world_id}.eden.zip       # compressed world file (served for download)
├── {world_id}.eden.png       # 3D preview screenshot (from Eden servers, often missing)
└── map.png                   # 2D top-down render (generated by node-mapgen)
```

**Zip packaging variations in the wild:**
- Standard: outer zip → raw `.eden`
- Common: outer zip → gzip-compressed `.eden` named `*.eden.zip` (gzip magic `1f 8b`, not a real zip)
- Rare: outer zip contains the entire `.eden.zip` bundle from the Eden server download
- Rare: **no outer zip at all** — a bare gzip stream saved directly as `{id}.eden.zip` (`zipfile.is_zipfile()` is False for it; the game server always delivers worlds gzip-compressed over HTTP, and this is what you get if that response gets saved straight to disk under the archive's `.eden.zip` naming convention without the usual outer real-zip wrap). Confirmed live on world `1584568651`. This is what usually gets reported as "doubly zipped" — the `.zip` in the name is misleading, since there's no zip layer there at all, just gzip.

`generate_missing_maps.py` and `node-mapgen` handle all four. `World.ts` auto-detects gzip vs raw regardless of which packaging got it there.

## Map Generation (`node-mapgen/`)

Renders a 2D top-down PNG of an Eden world: finds the highest non-air block per column and colors it using a flat palette (`MapColors.ts`).

**CLI usage:**
```bash
cd node-mapgen && npm install       # first time only
node dist/generate-map.js <eden_file> <output.png>
# or without pre-compiling:
npx ts-node src/generate-map.ts <eden_file> <output.png>
```

**Key files:**
- `src/World.ts` — parses `.eden` binary; handles gzip and raw; reads chunk pointer table; detects 64z vs 256z via min-gap between chunk offsets; `MAX_CHUNK_COUNT`/`MAX_CHUNK_AREA` guard against the chunk table's lack of an end marker producing an implausible chunk count or bounding box (see below)
- `src/renderNormalMap.ts` — iterates bands top-down (4 for 64z, 16 for 256z), finds highest block per column
- `src/MapColors.ts` — flat RGB palette (54 paint colors + 127 block-type colors)
- `src/generate-map.ts` — CLI entry point; uses `pngjs` to write PNG. Slices the read buffer to its exact byte range before handing it to `loadWorldFromArrayBuffer` — Node pools small `Buffer`s in a shared `ArrayBuffer`, so `buffer.buffer` alone can include unrelated neighboring data for small files.
- `dist/` — compiled JS (run `npx tsc` to rebuild after editing TypeScript; the build excludes `*.test.ts`)
- `src/*.test.ts` — `node --test` suite, run with `npm test`; builds synthetic `.eden` buffers rather than depending on real archive files

**Known limitation:** cannot render worlds that decompress to >~2 GB (Node.js ArrayBuffer limit). ~14 worlds in the archive fall into this category (e.g. Starling City at 8.8 GB). The Rust rendering pipeline in `eden-world-editor` handles these via memory-mapped files; a standalone Rust CLI could be added later.

**The chunk pointer table has no length field or end marker** (confirmed against `eden-world-editor/MROB.txt`'s reverse-engineering notes) — it's read by scanning 16-byte records from the header's directory offset to end of file. This can produce implausible results the naive `Math.min`/`Math.max`-based bounding box used to choke on:
- A world whose chunk table scan finds >2,000,000 plausible-looking records (`MAX_CHUNK_COUNT`) is either genuinely too large for node-mapgen or its table is corrupt; fails cleanly with a `WorldParseError` instead of `Math.min(...millions_of_args)` throwing "Maximum call stack size exceeded" (found live on world `1770253120`, a genuine ~6.3 GB world compressing to a deceptively small ~18 MB gzip stream).
- A world whose naive bounding box exceeds `MAX_CHUNK_AREA` (400M px / 256 px-per-chunk) gets cluster-trimmed: chunks are grouped by proximity, and only the largest cluster (plus any others that fit within 4x its own area) survives — a world can genuinely have several separate builds far apart, so simple distance-from-median trimming isn't reliable (found live on world `1315736126`: a 572-chunk build, a much smaller one, and a handful of outliers spread out to 5,911 chunks away, all *within* the real chunk-table region, not from over-scanning past it). If even the largest single cluster is still implausibly large, throws `WorldParseError` rather than allocating a multi-GB canvas.
- An empty chunk table throws `WorldParseError` ("no valid chunks found") instead of silently producing a broken 0×0 PNG — found live on world `1623093424`, whose stored `.eden.zip` decompresses to a 263-byte XML error page (a failed download), not real Eden data.

All three are surfaced through `admin/core/mapgen.py`'s `classify_error()` as `too_large` (the first two) or a generic `node_error` (the last one — it's corrupt source data, not a size problem).

## Batch Map Generation

```bash
python3 generate_missing_maps.py              # generate all missing maps
python3 generate_missing_maps.py --dry-run    # list which are missing
python3 generate_missing_maps.py --limit 10   # process first 10
python3 generate_missing_maps.py --world-id 1315348100  # one specific world
```

Extracts each `.eden.zip` into `.mapgen-tmp/` (gitignored, repo-root), generates `map.png`, then immediately deletes the extracted file before moving to the next world — never accumulates more than one unzipped world on disk at a time. Uses compiled JS (`dist/`) if present, otherwise falls back to `npx ts-node`.

## Adding New Worlds

```bash
python3 z_add_world.py --eden path/to/world.eden
python3 z_add_world.py --folder path/to/folder/   # batch import
```

Prompts for world name, author, tags, archive date. Auto-detects the numeric world ID from the filename timestamp. Downloads the 3D preview image from Eden servers (often fails — servers are HTTP-only and frequently down). Generates `map.png` via `node-mapgen`. Creates `_worlds/{slug}.md`.

## Admin CLI

```bash
python3 admin/edenadmin.py validate           # check all worlds for missing assets/metadata
python3 admin/edenadmin.py validate --out report.json
python3 admin/edenadmin.py import --eden ...  # delegates to z_add_world.py
python3 admin/edenadmin.py tags analyze       # find similar/duplicate tags
python3 admin/edenadmin.py tags merge         # apply tag_map.yaml merges
```

`validate` checks for: `missing_zip`, `missing_preview`, `missing_map`, `missing_tags`, `invalid_publishdate`, `missing_asset_dir`, `invalid_front_matter`.

**Known bugs in the CLI** (all fixed in the admin app; the CLI gets rewired onto `admin/core/`
in M7):

- `validate` needs **PyYAML, which is not installed system-wide** — it exits with an error under
  bare `python3`. Use the admin venv: `admin/.venv/bin/python admin/edenadmin.py validate`.
- `validate` reports **`invalid_publishdate` for all 768 worlds**. PyYAML loads a bare
  `2011-09-07` as a `datetime.date`, not a `str`, so its `isinstance(pd, str)` check
  (`edenadmin.py:136`) always fails. Ignore that line; every other count is correct.
- `tags analyze` / `tags merge` **read zero worlds** — they run with `cwd` set to
  `z_scripts/tag manage/`, but those scripts hardcode a relative `Path("_worlds")`.
- `_articles/creatures.md` has **genuinely malformed front matter** (a bare
  `Eden World Builder Wiki` line with no key). Worth repairing by hand.

Current real defect counts: 1 `missing_asset_dir`, 5 `missing_zip`, 227 `missing_preview`,
14 `missing_map`, 392 `missing_tags`.

## Dev / Build

```bash
bundle exec jekyll serve    # local preview at http://localhost:4000/edenarchive
bundle exec jekyll build    # production build to _site/
```

The site is deployed automatically by GitHub Pages on push to `main`.

`_config.yml` excludes the tooling from the Jekyll build so it is never published to GitHub
Pages: `z_Uploading/`, `node-mapgen-broken/`, `admin/`, `z_scripts/`, `node-mapgen/`,
`z_AutoDownloader/`, `*.py`, and the Gemfiles. Adding a new tooling directory means adding it
here too.

Gitignored: `node-mapgen/node_modules/`, `.mapgen-tmp/`, `admin/.venv/`, `admin/.runtime/`,
`__pycache__/`.

Note: the local Ruby toolchain is currently broken (system Ruby 2.6 vs. a bundler version
mismatch), so `bundle exec jekyll build` does not run on this machine. Pages builds remotely and
is unaffected.
