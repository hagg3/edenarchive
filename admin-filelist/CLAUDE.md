# EdenFind

An archivist's search interface over `file_list2.txt` (46 MB, 896,157 lines) — the
upload log of the legacy Eden World Builder shared-worlds server. It's not a report
*about* the server; it **is** the server's database, written one line at a time by
the upload servlet (`~/emod/tools/eden2/src/UploadMap2.java:205-213`) and read back
at startup to rebuild the search index (`List2.java:199-206`).

Stdlib-only Python (3.14, no pip/npm/build step) builds a SQLite index and serves a
JSON API; a vanilla-JS page consumes it.

```
python3 build.py     # file_list2.txt + featured/*.txt -> worlds.db  (~85s, ~590MB)
python3 serve.py      # -> http://127.0.0.1:8777
python3 -m edenfind.selftest    # asserts the measured baseline below
```

`build.py` preserves existing `triage` (star/reject/note) state across a rebuild —
world ids are assigned deterministically (file_list2.txt in line order, then the
featured-only synthetic worlds sorted by ts), so they're stable run to run.

## Line grammar — three eras, one format

```
1327810665.eden DANIELAND                                         # 423 rows, pre-logging fragment, no origin
!D61AC753-72C8-45CD-8A87-26E25BF0C922 1423718682.eden test upload3 # 8,749 rows, UUID era (Feb 2015)
!69.113.102.74 1786425051.eden Chainsaw Hotel' s1ep6 BzX           # 886,983 rows, IPv4 era (everything since)
!(null) 1424179318.eden HHoffun2 V001                              # 1 row, pre-iOS6 placeholder
```

One regex handles all of it (`edenfind/parse.py`):
`^\s*(?:!(?P<origin>\S+)\s+)?(?P<id>\d{9,12})\.eden(?: (?P<name>.*))?$`
The leading `\s*` matters — line 184,264 carries 51 leading spaces before a run of
NUL bytes, which is why it's the corpus's one unparseable line (routed to the
`rejects` table, not silently dropped).

World ids are unix timestamps (`System.currentTimeMillis()/1000` with collision
bumping server-side) — **the id is the publish date**, no separate date field
exists. `worlds.id` in the database is a surrogate autoincrement key, not the raw
timestamp; `worlds.ts` holds the actual world id used in URLs (previews, and to
correlate with `featured/`).

## The `[A-Za-z0-9 ']` restriction — read the apostrophe

World names can only contain letters, digits, spaces and apostrophes, enforced at
three independent layers (game keyboard `ShareMenu.mm:80`/`VKeyboard.mm`, server
re-filter `UploadMap2.java:146-152`, desktop editor `src-tauri/src/lib.rs:6026-6030`).
There is no path to type `?`, `,`, `!`, `.` or `-`. So the apostrophe became a
universal escape, present in 26% of names:

| Usage | Example |
| --- | --- |
| `?` | `Jon'red' cray 'qm'` — `'qm'` = question mark |
| decimal point | `Ocean Shores V4'5`, `Atlantis v15'1` |
| version separator | `DIRECT CITY 2'9'4` (→ version ordinal `2.94` — segments after the first concatenate, not sum) |
| quotes | `Octagon Islands 'Concert Hall'` |
| dash | `Ar10 by BrixXx ' Hack by Vuenc` |
| chat channel | `Jon'red' ok' im just glad edens back` |

The game's own server does the right thing (`List2.java:137-145`): uppercase, then
replace every non-`[A-Z0-9]` with a space, so `DIRECT CITY 2'9'4` indexes as
`DIRECT CITY 2 9 4`. `worlds_fts` (FTS5, `tokenize='unicode61'`) matches this
automatically — unicode61's default tokenchars exclude apostrophe, so it's already
treated as a separator; no custom tokenizer config was needed.

`edenfind/series.py` uses the apostrophe-as-decimal convention for
`version_ordinal()`: `V3'1` → `3.1`, `2'9'4` → `2.94`.

Name length: the game caps typing at 36 chars, the header allows 49, longest
observed is 38 — don't assume 36 is a hard limit.

## The pre-2015 coverage gap

**The record effectively begins 2015-02.** Only 326 raw log rows predate
2015-01-01, for a game that was at its most popular in 2012–2014.

| Month | Rows |
| --- | --- |
| 2012-03 … 2014-12 | 1–33/month |
| 2015-01 | 64 |
| **2015-02** | **42,899** |
| 2015-03 | 98,336 |

`file_list2.txt` was evidently rebuilt/restarted around February 2015; the 423
unprefixed rows at the top are a hand-preserved fragment carried over (and look
unusually good — DANIELAND, Olympic Village, Party Park — because that's
survivorship, not quality).

The `featured/` snapshots (Eden's own `popularlist.txt`, 21 captures 2012-10-28 →
2024-02-10) partially cover the gap: 423 distinct featured worlds, only 164 present
in the dump. The other 259 are ingested as first-class `worlds` rows with
`source='featured'` — the only coverage of that era this tool has.
`/api/stats` returns `coverage_gap_end` (`2015-02-01`) and a `coverage_warning`
string; the frontend shows a persistent banner whenever the active date filter
reaches before that date. **This is surfaced in the UI, not just here** — an
archivist searching for a 2013 world and getting nothing needs to know the log
doesn't cover 2013, not that the world didn't exist.

## Chat vs. flood: two different failure modes, one discriminator

People used the shared-worlds list as a chat room: one world uploaded per message,
message as the name, format `Handle'CHANNEL'message`:

```
50.198.35.41     2015-02-28 01:23:12  Scc'red'I wish something good would
101.177.156.187  2015-02-28 01:23:21  Jon'red' ok' im just glad edens back
```

`'red'` is the largest channel (131k+ rows, spans 2015-02-18 → 2026-04-26 — eleven
years). `terms.CHAT_CHANNEL_TAGS` also tracks `lava`, `war`, `ktpn`, `abce`, `dotd`,
`rb`, `mam`, `pscp`. Separately, **flooding**: `45.36.48.248` uploaded `HACKED Gold`
902 times on 2015-03-27 (the plan's illustrative sub-window: 601 in an 11-minute
span, roughly once a second) — a stricter, distinct failure mode from a chat burst
of varied messages.

One ratio separates them cleanly — **distinct names ÷ uploads, per origin**
(`classify.origin_class`, `ORIGIN_CHAT_RATIO=0.55`, `ORIGIN_FLOOD_RATIO=0.12`):

| Origin | Uploads | Distinct | Ratio | Class |
| --- | --- | --- | --- | --- |
| `75.131.34.15` | 9,614 | 8,812 | 0.92 | chat |
| `24.45.52.119` | 12,313 | 9,873 | 0.80 | chat |
| `24.217.126.77` | 27,691 | 6,441 | 0.23 | builder (heavy re-uploader) |
| `24.207.130.162` | 14,534 | 764 | 0.05 | flooder |

Row-level flags are separate and finer-grained than origin class:
- `f_burst` — origin has ≥5 uploads within any 120s window (origin-less rows are
  grouped into one pseudo-origin; 143,171 rows, matches the plan exactly)
- `f_flood` — ≥15 uploads of the **exact same name** from one origin within any 120s
  window (identical-content spam, not just rapid-fire — 20,504 rows across 351
  incidents)

## IPs are sessions, not identities

`by julien baillod` appears from 142 different IPs; `by joeygrim` from 344. IP is a
session key — good for burst/flood detection and "what else went up alongside
this" (`/api/world/<id>` → `session_neighbours`, ±1h same origin) — useless as an
author key. The real author signal is the `by <name>` suffix
(`classify.extract_author`, regex `\bby\s+([A-Za-z0-9][A-Za-z0-9 ']{0,30})$`):
~49k rows, ~9.5k distinct authors.

## Series recovery (`edenfind/series.py`)

`series_key()` **truncates** the name at the first version marker (explicit
`v12`/`part 4`/`s1ep6`-style words, an apostrophe-decimal chain, a numeric range, or
a trailing bare number) rather than stripping it in place — per-version subtitles
("DANIELAND v30 ULTIMATE BEACH HOUSE" vs "DANIELAND v26 THE BIG HOUSE") are
changelog text for that release, not part of the series' identity, so keeping them
would fragment v1..v30 into 30 different series instead of one. Trailing bare
numbers over 999 are excluded from `version_ordinal()` — a date-shaped suffix like
`Airport V25032021` is not a real version and would otherwise make an unrelated
collision of generic names look like decades of iterative history.

The quality scorer's "series depth" signal (`classify.score_world`) is **not** raw
series member count — it's the count of *distinct version numbers actually
reached*. A generic reposted name like "Airport" collapses ~30 unrelated uploads
into one series_key with zero real version progression, which raw count would
reward as if it were a deliberate 30-build iterative effort; distinct-version-count
correctly gives it ~0.

## Measured baseline (what `selftest.py` checks, and why some numbers differ from the plan)

The build was implemented against a plan that included exploratory measurements
taken before the final parsing rules were locked down. Where they differ from what
this pipeline actually produces, this tool's numbers are the ones asserted by
`edenfind/selftest.py` (a rebuild is 100% deterministic, so these are stable):

| Metric | Plan draft | This tool | Note |
| --- | --- | --- | --- |
| Rows parsed / rejects | 896,156 / 1 | 896,156 / 1 | exact |
| Distinct names (raw log, ci) | 339,103 | 339,103 | exact (requires full `.strip()`, not just trailing) |
| `f_repost` | 288,831 | 288,831 | exact |
| `f_burst` | 143,171 | 143,171 | exact |
| Rows predating 2015-01-01 | 326 | 326 | exact |
| `f_default` (`^world\s*\d+$`) | 139,528 | 139,163 | 0.3% low; some default-name variants use punctuation the plan's estimate didn't enumerate |
| Distinct featured worlds | 420 | 423 | featured/*.txt parsing handles leading/trailing whitespace on id lines that naive line-stride missed |
| Featured worlds present in dump | 163 | 164 | follows from the above |
| `by <author>` rows / distinct | 47,975 / 9,278 | 49,076 / 9,558 | regex-boundary difference, ~2-3% |

All of these are cross-checked in `selftest.py`; run it after any change to
`parse.py`, `classify.py`, or `series.py`.

## Scoring validation

`quality_score` is stored as a list of named contributions (`score_parts`, JSON),
not just a total — the drawer shows *why* a world scored what it did. Deliberately
**no "old = good" bonus**: the 326 pre-2015 rows score on their own merits, since
rewarding them for their date would double-count a survivorship artifact (see
coverage gap above). The held-out check: featured worlds should score materially
higher than a random non-featured sample — if a scoring change breaks this, the
weights are wrong.

## Server endpoint map (for `/api/preview` and future upload/search integrations)

Per `~/emod/docs/networking.md` (`ShareUtil.mm:48-53`), **current**:
- `UPLOAD_URL`: `http://app.edengame.net/upload2.php?uuid=<identifierForVendor>`
- `LIST_URL`: `http://app2.edengame.net/list2.php?start=N&sort=N` (also `?search=`)
- `REPORT_URL`: `http://app2.edengame.net/report.php?map=<file>&uuid=<...>`
- `MAPS_URL`: `http://files2.edengame.net/<file>` (worlds + `<file>.png` previews)
- `POPULAR_URL`: `http://files2.edengame.net/popularlist.txt`

**Legacy** (superseded, kept as comments in `ShareUtil.mm`): `app.edengame.net` for
listing, `files.edengame.net` for maps/previews. All plain HTTP — TLS reportedly
fails against these hosts, and modern iOS needs an ATS exception.

`edenfind/server.py`'s `/api/preview/<id>` proxies `http://files.edengame.net/<ts>.eden.png`
(the **legacy** host) per the project plan's explicit spec — if previews come back
empty, the service may have fully cut over to `files2.edengame.net`; that's the
first thing to try. Many recent worlds have no preview at all regardless of host (a
documented late-era upload bug), so a 404 there is expected and shown as such, not
treated as an error.

Preview fetches are cached to `.preview_cache/` on disk and are otherwise exactly
one HTTP request per drawer-open — no crawl, no prefetch, no polling (matching the
rate discipline in `edenarchive/admin/core/edenserver.py:8`).

## Where to edit the taxonomy

`edenfind/terms.py` is a plain-dict module, no code changes needed elsewhere:
- `KEYWORDS` — category taxonomy (iteration/architecture/worldbuilding/realworld/
  gameplay/older/other), used by `classify.score_world` for the "key terms" score
  contribution.
- `CONCEPT_MAP` — powers concept search (`theme park` → coaster/rides/fairground/…).
- `CHAT_CHANNEL_TAGS` / `CHAT_ESCAPE_TOKENS` / `CHAT_WORDS` — the chat-culture
  lexicon; grow these as new channels or conversational patterns turn up.
- `MULTILINGUAL` — German/French/Spanish structure & gameplay terms (the corpus is
  genuinely international: `FLUGHAFEN cmg`, `Le Bluflaym Royaume`, `ciudad satelite`).

Scoring weights and thresholds (`ORIGIN_CHAT_RATIO`, `BURST_MIN_COUNT`,
`_JUNK_PENALTY`, etc.) live in one constants block at the top of each function's
section in `edenfind/classify.py`.

## Search modes seam

`edenfind/query.py`'s four modes (lexical, fuzzy, concept, regex) share one filter
pipeline (`_build_where` / `_run`); a mode only needs to produce a candidate id set
(or an FTS/name_lc expression for the two SQL-native modes). Adding embedding-based
semantic search later means adding one more candidate generator — no embedding
dependency exists today (`numpy`/`torch`/`sentence-transformers` are absent from
this Python install; fuzzy trigram + `difflib.SequenceMatcher` covers the
misspelling-dense, not synonym-dense, character of this corpus, per the user's
explicit choice).

## Why not to trust the three prior triage scripts in this directory

- **`shortlist_worlds.py:115-119`** splits on the first space and requires token 0
  to end in `.eden` — every `!`-prefixed (i.e. IP/UUID-origin) line fails to parse.
  `reports/shortlist.txt` was built from only the 423 unprefixed fragment rows —
  **0.05% of the corpus**.
- **`search.py:17-18`** does `if line.startswith("!"): continue` — discards 99.95%
  of the data before searching the rest.
- **`eden_triage_v2_1.py:202-203`** parses every line correctly but hard-`continue`s
  on `'red'`, silently deleting the single largest coherent subculture in the
  archive (131k+ rows) instead of flagging it.

None of their output CSVs (`ranked_worlds_v2.csv`, `ranked_worlds_v2_1.csv`,
`reports/shortlist.txt`) should be treated as ground truth for anything — they're
kept in this directory as the source the taxonomy in `terms.py` was lifted from,
not as data.
