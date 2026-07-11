# Eden Archive Admin

Two ways to administer the archive:

- **Admin UI** (`./admin/run.sh`) — a local web app for browsing, searching, and curating the
  768 worlds. This is the main surface.
- **Admin CLI** (`admin/edenadmin.py`) — the original script wrapper. Still works.

Both operate on a cloned copy of the repo. They write plain files into the working tree; you
review with `git diff` and push to publish. **Neither ever talks to GitHub.**

---

## Admin UI

```bash
./admin/run.sh          # → http://127.0.0.1:8765
```

First run creates `admin/.venv` and installs dependencies (~15s). Afterwards it starts in about
a second. `PORT=9000 ./admin/run.sh` to use a different port.

The app binds to `127.0.0.1` only. There is no auth, because nothing outside your machine can
reach it.

### What it does today (M0)

| Page | |
|---|---|
| **Dashboard** | Archive counts, defect tallies (missing zip/map/preview, untagged), top tags, and a live panel of your uncommitted changes. |
| **Worlds** | Full-text search across name, author, tags and body, plus filters by tag, author, asset state and defect. Map thumbnails inline. |
| **World detail** | Front matter, assets, map and preview images, and the `git diff` for that one file. |

M0 is **read-only** — it will not modify anything in `_worlds/`, `_articles/`, `_posts/`, or
`assets/`. Editing arrives in M1. See `ADMIN_APP_PLAN.md` at the repo root for the roadmap.

### Rescanning

The index is a SQLite cache at `admin/.runtime/index.db` (gitignored). Markdown is always the
source of truth, so the cache is disposable — delete it and it rebuilds.

It rescans automatically at startup, and incrementally: a world whose `.md` file has the same
mtime and size is skipped. A cold scan of all 768 worlds takes ~1.4s; a warm one is instant.
Click **Rescan archive** on the dashboard if you have edited files by hand while the app is
running.

### Git

The app shows your pending changes and gives you a copy-paste-ready `git add … && git commit`
line. **You run it.** The app never runs `add`, `commit`, `push`, `checkout`, `reset`, or
`clean`. The one command that touches the network is the explicit **fetch** button.

---

## Architecture

```
admin/
├── run.sh              # launch: venv + deps + uvicorn
├── requirements.txt
├── edenadmin.py        # the original CLI
├── core/               # pure library — no FastAPI imports, usable from scripts
│   ├── paths.py        # every path in the repo; validates all writes stay inside it
│   ├── frontmatter.py  # ★ format-preserving parse/render — read this before editing world files
│   ├── world.py        # World record: front matter + assets on disk; validate()
│   ├── index.py        # SQLite schema, incremental scanner, search
│   └── git.py          # read-only git
├── app/                # FastAPI + Jinja2 + HTMX (no JS build step)
│   ├── main.py
│   ├── routers/        # dashboard, worlds, git_api
│   ├── templates/
│   └── static/         # vendored htmx.min.js — no CDN, works offline
├── tests/
└── .runtime/           # gitignored: index.db, backups/, uploads/
```

Stack is FastAPI + Jinja2 + HTMX. No JavaScript build step, no CDN, no Node dependency for the
app itself (Node is only used by `node-mapgen` to render maps).

---

## ⚠️ Never `yaml.dump` a world file

The world files were hand-emitted by `z_add_world.py`, not by a YAML library, and the corpus
depends on those exact bytes:

- empty scalars are written `key: ` **with a trailing space** (598 files have `author: `)
- `filesize` is **always** double-quoted; nothing else ever is
- tags are 2-space block sequences

`yaml.safe_dump` rewrites all of that — it unquotes `filesize`, turns an empty `archivedate:`
into `archivedate: null`, and re-wraps the file. **`z_scripts/tag manage/merge_tags.py` does
exactly this today and corrupts every file it touches.**

So `core/frontmatter.py` uses YAML only to *read*. Writing edits the original lines in place and
leaves every untouched line byte-identical. Anything that modifies a world file must go through
it.

The invariant is enforced by a test:

```bash
admin/.venv/bin/python -m pytest admin/tests -q
```

`render(parse(f)) == f` for all 775 markdown files in the archive. **If this does not pass, no
write feature is safe to ship.**

---

## Admin CLI

```bash
python3 admin/edenadmin.py --help

# Validate metadata against assets on disk
python3 admin/edenadmin.py validate
python3 admin/edenadmin.py validate --out admin/reports/validate.json

# Import worlds (delegates to z_add_world.py)
python3 admin/edenadmin.py import --eden /path/to/world.eden.zip
python3 admin/edenadmin.py import --folder /path/to/folder

# Download worlds listed in z_AutoDownloader/worlds.txt
python3 admin/edenadmin.py download --list /path/to/worlds.txt

# Build a shortlist from a server file list (dedupes series to latest)
python3 admin/shortlist_worlds.py --list "file_list2 260202.txt"
```

### Known issues in the CLI

These are fixed in the UI and will be fixed in the CLI when it is rewired onto `core/` (M7):

- **`validate` requires PyYAML, which is not installed by default** — it exits with an error.
  Run it with the admin venv instead: `admin/.venv/bin/python admin/edenadmin.py validate`.
- **`validate` reports `invalid_publishdate` for all 768 worlds.** PyYAML loads a bare
  `2011-09-07` as a `datetime.date`, not a `str`, so its `isinstance(pd, str)` check always
  fails. Ignore that one line; every other count is correct.
- **`tags analyze` and `tags merge` read zero worlds.** They run with `cwd` set to
  `z_scripts/tag manage/`, but the scripts hardcode a relative `Path("_worlds")`. And
  `merge_tags.py` would corrupt front-matter formatting if it did run (see above).
