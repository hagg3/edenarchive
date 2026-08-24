# EdenFind

An archivist's search interface over the Eden World Builder shared-worlds upload
log (`file_list2.txt`, 896k lines) and the `featured/` popularlist snapshots. See
`CLAUDE.md` in this directory for the full data model, parsing rules, and design
notes — this file is just setup.

## Requirements

- Python **3.14**, stdlib only. No `pip install`, no `npm`, no build step.
- The two data inputs, already present in this directory:
  - `file_list2.txt` — the raw upload log
  - `featured/*.txt` — popularlist snapshots

## Setup

```bash
cd admin-filelist

# 1. Build the SQLite index (~85s, produces worlds.db, ~590MB — gitignored,
#    not checked in; you must build it locally)
python3 build.py

# 2. Serve the app
python3 serve.py
```

Then open **http://127.0.0.1:8777**. The server binds to localhost only.

Optionally verify the build is correct:

```bash
python3 -m edenfind.selftest
```

This asserts a set of exact known counts (rows parsed, distinct names, flag
counts, etc.) against the shipped `file_list2.txt` — see the "Measured baseline"
table in `CLAUDE.md` if anything fails.

## Rebuilding

Re-run `python3 build.py` any time `file_list2.txt` or `featured/` changes. It's
fully deterministic and safe to re-run — any existing `triage` state (starred /
rejected / noted worlds) in `worlds.db` is preserved across the rebuild, since
world ids are assigned deterministically.

## Browsing

The web UI (`edenfind/web/`) is a single page with four search modes — lexical,
fuzzy, concept, and regex — plus date-range and flag filters (chat, flood, burst,
repost, default-name). Click a result to open its drawer: full name, origin,
timestamp, quality score breakdown, series membership, session neighbours (other
uploads from the same origin within ±1h), and — where available — a proxied
preview image (fetched live from `files.edengame.net`, cached to `.preview_cache/`
on first view; also gitignored).

A persistent banner appears whenever the active date filter reaches into the
pre-2015-02 coverage gap — the log effectively begins February 2015, so results
(or the lack of them) before that date reflect log coverage, not upload history.

## Not checked in

- `worlds.db` — rebuild with `build.py` (~590MB, fully derived from
  `file_list2.txt` + `featured/`)
- `.preview_cache/` — proxied preview images, populated lazily as you browse
