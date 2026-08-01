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
into `archivedate: null`, and re-wraps the file, producing a huge spurious diff. `z_scripts/tag
manage/merge_tags.py` does exactly this; it already corrupted 41 files this way before the admin
app existed (repaired 2026-07-11 — see `frontmatter.repair_corruption()`/`save_repair()`, a
one-off fix for literal `key: null` scalars and de-indented tag blocks). Do not use
`merge_tags.py` or copy its `save_file()`.

**Anything that modifies a world (or post/article) file must go through
`admin/core/frontmatter.py`**, which uses YAML only to *read* and edits the original lines in
place, leaving every untouched line byte-identical (`core/content.py` reuses the same module for
`_posts`/`_articles` — it isn't world-specific). Its invariant — `render(parse(f)) == f` for
every markdown file in the corpus — is enforced by `admin/tests/`. Run it after touching that
module:

```bash
admin/.venv/bin/python -m pytest admin/tests -q     # must be 887/887 (grows as admin/ grows)
```

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
  frontmatter.py  # ★ format-preserving parse/render (see warning above) + repair_corruption()
  world.py        # World record: front matter + assets on disk; validate(), normalize_name/strip_version
  content.py      # _posts/_articles CRUD, reusing frontmatter.py directly
  index.py        # SQLite cache + incremental scanner + FTS search + dupe_pairs/jobs tables
  mapgen.py       # zip→.eden extraction ladder (4 packaging variants), pre-flight size check, lock
  hashing.py      # streaming zip + payload sha256 (never extracts to disk, even for 8+ GB worlds)
  tags.py         # near-dupe grouping, tag_map.yaml bulk retag
  dupes.py        # candidate-pair scoring (hash/name/author), dismissal persistence
  importer.py     # de-interactivized z_add_world.py: staged upload -> similarity check -> commit
  git.py          # read-only git
admin/app/        # FastAPI + Jinja2 + HTMX; jobs.py (asyncio queue), routers/, templates/, static/
admin/tests/      # ~890 tests; the front-matter round-trip test gates all write features
admin/.runtime/   # gitignored: index.db, backups/, uploads/. Disposable — markdown is the truth.
```

**Status: M0–M6 all shipped** — read-only dashboard, world editing, assets + map-generation job
queue, tag health, duplicate/version detection, blog/article CRUD, upload flow. Only M7 (optional
CLI cleanup) remains. The roadmap, design rationale, and findings behind them are in
`ADMIN_APP_PLAN.md` — each milestone has an "outcome" section with what was actually built and
verified live against the real repo, which is more current than anything summarized here.

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
worldformat: 64z          # or 256z — see node-mapgen's numBands detection
chunkwidth: 40            # world bounding box, in 16-block chunks
chunkheight: 37
skycolor: 0               # raw sky byte from the header, no known RGB mapping
seed: 263133
spawnx: 344.0             # home/respawn point, in the same local coords map.png uses
spawny: 312.0
---
```

The last seven fields are machine-extracted from the `.eden` binary by node-mapgen (see
`node-mapgen/src/worldMeta.ts`) rather than hand-curated, and are optional — many worlds won't
have them until their map is (re)generated at least once since this landed. `spawnx`/`spawny` are
absent for worlds with no home point set (all-zero header field). Written via
`admin/core/frontmatter.py` like every other field — never hand-edited, never through
`yaml.dump`. `admin/app/jobs.py`'s mapgen job folds them in automatically after every map
render; `backfill_world_meta.py` (repo root) does the same in bulk without re-rendering
`map.png` for worlds that already have one.

Page body typically: description, preview image `{id}.eden.png`, `{% include world-details.html %}`, `{% include world-download.html %}`, and a `## Map` section with `map.png`.

## Asset Layout

```
assets/worldfiles/{world_id}/
├── {world_id}.eden.zip       # compressed world file (served for download)
├── {world_id}.eden.png       # 3D preview screenshot (from Eden servers, often missing)
├── map.png                   # 2D top-down render (generated by node-mapgen)
└── meta.json                 # technical fields node-mapgen computed while rendering map.png —
                               # disposable (regenerated by every mapgen run); the front-matter
                               # fields it gets folded into are the source of truth
```

**Zip packaging variations in the wild:**
- Standard: outer zip → raw `.eden`
- Common: outer zip → gzip-compressed `.eden` named `*.eden.zip` (gzip magic `1f 8b`, not a real zip)
- Rare: outer zip contains the entire `.eden.zip` bundle from the Eden server download
- Rare: **no outer zip at all** — a bare gzip stream saved directly as `{id}.eden.zip`
  (`zipfile.is_zipfile()` is `False` for it; the game server always delivers worlds
  gzip-compressed over HTTP, and this is what you get if that response is saved straight to disk
  under the `.eden.zip` naming convention, skipping the usual outer wrap). Confirmed on world
  `1584568651`. This is what usually gets reported as "doubly zipped" — the `.zip` in the name is
  misleading; there's no zip layer at all, just gzip. There is no genuine double-compression
  (gzip-of-gzip or zip-of-zip) anywhere in the current archive — verified by walking every stored
  zip's payload layers by magic bytes.

`generate_missing_maps.py`, `admin/core/mapgen.py`, and `node-mapgen` handle all four
(`mapgen._bare_gzip_fallback`/`_eden_name_for`). `World.ts` auto-detects gzip vs raw regardless of
which packaging got it there.

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
- `src/World.ts` — parses `.eden` binary; handles gzip and raw; reads chunk pointer table; detects 64z vs 256z via min-gap between chunk offsets
- `src/renderNormalMap.ts` — iterates bands top-down (4 for 64z, 16 for 256z), finds highest block per column
- `src/MapColors.ts` — flat RGB palette (54 paint colors + 127 block-type colors)
- `src/generate-map.ts` — CLI entry point; uses `pngjs` to write PNG; slices the read buffer to its exact byte range (Node pools small `Buffer`s in a shared `ArrayBuffer`) before parsing
- `dist/` — compiled JS (`npx tsc` to rebuild; excludes `*.test.ts`)
- `src/*.test.ts` — `node --test` suite (`npm test`), synthetic `.eden` buffers, no real-file fixtures

**Known limitation:** cannot render worlds that decompress to >~2 GB (Node.js ArrayBuffer limit). ~14 worlds fall into this category (e.g. Starling City, 8.8 GB) — pre-flight in `admin/core/mapgen.py` catches most of these before spawning node. The Rust pipeline in `eden-world-editor` handles these via memory-mapped files; a standalone Rust CLI could be added later.

**The chunk pointer table has no length field or end marker** (confirmed against `eden-world-editor/MROB.txt`) — read by scanning 16-byte records to EOF, which can produce an implausible chunk count or bounding box for a corrupt or genuinely oversized world. `World.ts`'s `MAX_CHUNK_COUNT`/`MAX_CHUNK_AREA` guard against this (clean `WorldParseError`, cluster-based trimming when a world has several separate builds, never a multi-GB canvas allocation or a stack overflow) — see `ADMIN_APP_PLAN.md`'s "doubly zipped" entry for the full investigation and the three real worlds that found each failure mode. Surfaced through `admin/core/mapgen.py`'s `classify_error()`.

## Batch Map Generation

```bash
python3 generate_missing_maps.py              # generate all missing maps
python3 generate_missing_maps.py --dry-run    # list which are missing
python3 generate_missing_maps.py --limit 10   # process first 10
python3 generate_missing_maps.py --world-id 1315348100  # one specific world
```

Extracts each `.eden.zip` into `.mapgen-tmp/` (gitignored, repo-root), generates `map.png`, then immediately deletes the extracted file before moving to the next world — never accumulates more than one unzipped world on disk at a time. Uses compiled JS (`dist/`) if present, otherwise falls back to `npx ts-node`.

## Adding New Worlds

**Preferred: the admin app's `/upload`** (`./admin/run.sh`) — staged upload with a similarity
check against the archive (world ID already archived is a hard block; near-name/version-chain
and hash matches are soft warnings requiring explicit confirmation) before anything is written,
then auto-enqueues a map-generation job. Same underlying logic as `z_add_world.py`
(`admin/core/importer.py` is a de-interactivized port of it — same naming-convention parsing,
same front-matter shape, same never-overwrite-an-existing-`.md` behavior), minus the terminal
prompts and plus the duplicate check.

**CLI, still works, no similarity check:**
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

**Known bugs in the CLI** (all fixed in the admin app — use `/tags` there instead of `tags
analyze`/`tags merge`; the CLI itself gets rewired onto `admin/core/` in the optional M7):

- `validate` needs **PyYAML, which is not installed system-wide** — it exits with an error under
  bare `python3`. Use the admin venv: `admin/.venv/bin/python admin/edenadmin.py validate`.
- `validate` reports **`invalid_publishdate` for all 768 worlds**. PyYAML loads a bare
  `2011-09-07` as a `datetime.date`, not a `str`, so its `isinstance(pd, str)` check
  (`edenadmin.py:136`) always fails. Ignore that line; every other count is correct.
- `tags analyze` / `tags merge` **read zero worlds** — they run with `cwd` set to
  `z_scripts/tag manage/`, but those scripts hardcode a relative `Path("_worlds")`. The admin
  app's `/tags` page does the same job correctly (`admin/core/tags.py`).
- `_articles/creatures.md` has **genuinely malformed front matter** (a bare
  `Eden World Builder Wiki` line with no key). The admin app tolerates and flags it; still worth
  repairing by hand.

Current real defect counts (as of 2026-07-11): 1 `missing_asset_dir`, 5 `missing_zip`, 227
`missing_preview`, 10 `missing_map`, 392 `missing_tags`.

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
