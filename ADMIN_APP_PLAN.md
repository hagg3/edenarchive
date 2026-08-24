# Eden Archive Admin — Handoff / Implementation Plan

> **Status: M0–M6 all shipped (2026-07-11).** Every planned milestone through the upload flow
> is done and live-verified against the real repo. Only M7 (optional CLI cleanup) remains. See
> "M6 outcome" below for what shipped last.

---

## M6 outcome (2026-07-11)

**Shipped:** `admin/core/importer.py` — a de-interactivized port of
`z_add_world.py:import_one_file()` (every `input()` prompt removed; the archivist fills in the
same fields through a review form instead, pre-filled by `parse_naming_convention()` from the
same `<world name> <10+ digit id> <tags>.eden(.zip)` convention the original script already
understood). Two-phase, matching the plan exactly:

- `stage()` — read-only. Extracts the `.eden` payload into `admin/.runtime/uploads/`, computes
  both hash tiers via M4's `core/hashing.py`. Writes nothing into the archive.
- `check_against_archive()` — the plan's "Upload-time check" table verbatim: world ID already
  archived is a **hard block** (returns immediately, nothing else computed); payload-hash match,
  zip-hash match, and near-name/version-chain match (reusing `world.normalize_name`/
  `strip_version` from M0) are **soft warnings** requiring an explicit "import anyway" checkbox.
- `commit()` — writes the asset dir, a freshly-recompressed `{id}.eden.zip` (matches
  `z_add_world.py`'s behavior exactly — new imports are always the "standard" raw-in-zip
  packaging, not the gzip-packaged form most existing downloads use, since that's what the
  original script already did), an optional bundled preview image as `map.png`, a best-effort
  live preview download, the 0-byte worldname marker file (kept for corpus parity per Open
  item 4), and `_worlds/{slug}.md` in the exact hand-written shape `z_add_world.py` emits —
  intentionally *not* routed through `frontmatter.render()`, since this is a new file, not an
  edit. **Never overwrites an existing `.md` for the same slug**, matching the original script.

New routes: `GET /upload`, `POST /upload/stage`, `POST /upload/commit`, `POST /upload/discard`.
On a successful commit, reindexes and auto-enqueues a `mapgen` job for the new world through
M2's job queue (only if it doesn't already have a map — relevant when a bundled preview image
was already used).

**Deliberate scope reduction:** the "hard block" path (world ID already archived) doesn't offer
the plan's "replace assets instead" alternative — overwriting an existing world's files is a
materially riskier operation than importing a new one and deserves its own careful design rather
than being bolted onto M6 at the end of a long session. It's a clear block with a link to the
existing world instead.

**17 new tests** (`admin/tests/test_importer.py`) — naming-convention parsing, staging (zip-wrapped,
raw, missing ID), all four warning kinds, and commit (front-matter byte shape, never overwriting
an existing `.md`, bundled-preview-as-map.png, required-field validation). **887/887 green.**

**Live-verified against the real repo, the full round trip:** staged and committed a real upload
(`Admin Upload Smoke Test 9999999999 test smoketest.eden.zip`) — naming convention parsed
correctly (worldname, world ID, tags), front matter and asset zip matched `z_add_world.py`'s
exact output shape, and a `mapgen` job was auto-enqueued and failed cleanly (`node_error`, since
the payload was synthetic, not a real Eden world — confirming the M2 job queue and M2-era error
classification both still work correctly end to end). Re-uploading the *same* world ID correctly
hard-blocked with a link to the existing entry. A second upload with a similar name correctly
produced a `similar_name` soft warning, was correctly refused without the confirm checkbox, and
succeeded once confirmed. Discard correctly removed staged files from `admin/.runtime/uploads/`.
All test worlds and assets were removed before committing — `git status` was clean before and
after.

---

## M5 outcome (2026-07-11)

**Shipped:** `admin/core/content.py` (`ContentItem`, `load`/`load_all`/`create`/`save`/
`rename`/`delete` for both `_posts` and `_articles`), `GET /content` (combined list),
`GET`/`POST /content/{kind}/create`, `GET`/`POST /content/{kind}/{filename}`, `POST
/content/{kind}/{filename}/rename`, `POST /content/{kind}/{filename}/delete`, `GET
/content/{kind}/{filename}/diff`, `POST /content/preview` (markdown → HTML via the `markdown`
package already in requirements.txt).

**Key design decision — reused `frontmatter.py`, didn't build a parallel format-preserving
parser.** `CANONICAL_ORDER`/`ALWAYS_QUOTED` only affect world-specific keys (`worldname`,
`filesize`, `tags`) that posts/articles never use, and the quoting-preservation logic (keep
whatever the original line did) is generic. Confirmed this holds against the real corpus:
`_posts/*.md` quote `title:` (e.g. `title: "Moof Hacks: Tips and Tricks"`), `_articles/*.md`
don't (`title: Santa Ines`) — both round-trip correctly with the same `render()`.

**Rename is a separate, explicit action — never automatic on save**, addressing the plan's
"rename warnings" requirement literally rather than silently renaming on any title/date edit.
Found live while testing M1's precedent doesn't quite carry over: Jekyll uses a post's
*filename* date (not its front-matter `date:` field) for permalink/sort order — confirmed in
the real corpus, `_posts/2026-02-09-a-b-c.md`'s front matter says `date: 2013-05-31`, a
genuine, intentional mismatch. So editing the date field alone is a legitimate, meaningful
action distinct from renaming the file, and the UI must not conflate them. `content_edit.html`
shows a warning banner with an explicit "Rename to …" button whenever the title/date would
imply a different filename; nothing renames until that button is clicked.

**14 new tests** (`admin/tests/test_content.py`) — no-op save, targeted single-line diff, create
(including the `filename_date` vs. front-matter-`date` distinction), rename collision refusal,
malformed front matter (`_articles/creatures.md`) still loads and flags rather than crashing,
delete. **870/870 green.**

**Live-verified against the real repo:** the list page correctly showed all 3 posts + 4 articles
(with `creatures.md` flagged `invalid front matter`, exactly as the M0 finding described).
Created a real post, edited it, previewed markdown (headings/bold/links rendered correctly),
triggered the rename-suggestion banner by changing the title, confirmed the explicit rename
endpoint actually moved the file, checked the diff panel, then deleted it — `git status` was
clean before and after, confirming no test residue was left in `_posts`/`_articles`. Also
confirmed a real quirk during testing: the corpus's `_posts`/`_articles` files (unlike
`_worlds/*.md`) currently don't end in a trailing newline; `content.save()`'s body
normalization adds one on first edit (matching M1's `normalize_body` convention) — a real,
one-time, intentional diff, not a bug, exactly like M0 finding 3's `worldname:` trailing-space
case.

---

## M4 outcome (2026-07-11)

**Shipped:** `admin/core/hashing.py` (streaming sha256 of zip bytes and of the decompressed
payload — reuses `mapgen.py`'s packaging ladder but never extracts to disk or holds a full
payload in memory, so even the ~14 worlds too large for node-mapgen get a payload identity
hash), `admin/core/dupes.py` (name normalization/version-stripping reused from M0's
`world.normalize_name`/`strip_version`, candidate scoring per the plan's table, dismissal
persistence to the committed `admin/dupe_dismissals.yaml`), a new `payload_hash` job kind wired
into the M2 job queue, and `GET /dupes` / `POST /dupes/scan` / `POST /dupes/{a}/{b}/{reason}` /
`POST /dupes/hash/bulk` / `POST /dupes/hash/{slug}`.

**Scope note:** dupe *scoring* (`POST /dupes/scan`) is a synchronous route, not a queued job —
name-similarity scoring across all 768 worlds runs in well under a second (matches the plan's own
estimate), so queueing it would add latency and complexity for no benefit. Only payload *hashing*
(genuinely slow — streaming gigabytes for the largest worlds) goes through the job queue, exactly
as the plan intended.

**29 new tests** (`test_hashing.py`, `test_dupes.py`, plus 2 in `test_jobs.py` for the
`payload_hash` job kind) — including a same-bytes-different-packaging test proving the payload
hash is identity-stable across raw/gzip/nested-zip/bare-gzip packaging, which is the entire point
of hashing the decompressed payload instead of the zip bytes. **856/856 green.**

**Live-verified against the real repo, all the way through:**
- `POST /dupes/scan` against all 768 worlds (before any payload hashing) found 458 candidate
  pairs — 422 `version_chain`, 20 `near_name`, 8 `same_author_similar`, 8 `identical_zip` — and
  eyeballing the top-scored ones (verification item 8) found them **genuinely useful**: e.g.
  `town-city-by-finto-opera-theatre` / `...theatreg` at 0.98 near-name (almost certainly a
  typo'd duplicate slug) and a chain of `the-creature-quest-part-*` entries from the same author
  (a real version series). The 8 `identical_zip` pairs (byte-identical re-uploads under
  different names, e.g. `mars-colony-5000` / `mars-colony-5000-2-1`) look like real duplicate
  archive entries worth the archivist's attention.
- `POST /dupes/hash/bulk` was run against the **entire real archive**: all 762 worlds missing a
  payload hash at the time, including every one of the ~14 known oversized worlds. **763/763
  succeeded, 0 failures** (one had already been hashed via the single-world endpoint moments
  earlier in the same test). Starling City (8.8 GB) got a payload hash with no error.
  `.mapgen-tmp/` stayed completely empty throughout, confirming the streaming design never
  touches disk — this is verification item 7 from the M0 plan, now fully confirmed rather than
  just designed for.
- Re-ran `POST /dupes/scan` after hashing: all 8 `identical_zip` pairs were correctly promoted
  to (also) `identical_payload` — the strongest possible signal, byte-identical decompressed
  world data — with the original `identical_zip` rows left in place rather than deleted (the
  schema's `PRIMARY KEY (a_slug, b_slug, reason)` deliberately allows both to coexist; `status`
  is tracked per reason, never overwritten by a rescan per the plan).
- Exercised `POST /dupes/{a}/{b}/{reason}` end-to-end with a `dismissed` status: confirmed the
  dupe_pairs row updated and the decision was appended to `admin/dupe_dismissals.yaml` — then
  reverted that specific test dismissal (the note was fabricated for the test, not a real
  archivist judgment call) before committing, same discipline as M2/M3's live-test-then-revert
  pattern.

**Not done in this pass** (deliberate M4 scope, matching what M6 needs later): the upload-time
similarity check (plan section "Upload-time check") is part of M6's staged-upload flow, not M4.

---

## M3 outcome (2026-07-11)

**Shipped:** `admin/core/tags.py` (tag inventory, difflib near-dupe grouping ported from
`analyze_tags.py`, `tag_map.yaml` loader, format-preserving bulk retag), `GET /tags` (near-dupe
groups, thin tags, untagged count, bulk-retag dry-run diff), `POST /tags/bulk` (applies
`z_scripts/tag manage/tag_map.yaml`, writes through `world.save`/`frontmatter.render` — never
`yaml.dump`). Tags nav link enabled in `base.html`.

**Deliberate scope reduction from the original plan:** bulk retag is two plain synchronous routes
(`GET /tags` for the dry-run preview, `POST /tags/bulk` to apply), not a queued `bulk_retag` job.
Rewriting ~25 small text files takes milliseconds — routing it through the async job queue would
have added SSE/job-table plumbing for no benefit in a single-user local app. The "mandatory
dry-run diff" requirement is still met: the preview table is always rendered before the apply
button, and the two are separate requests. `/tags/suggest` (autocomplete) from the original route
list was also dropped — the world-edit tag `<datalist>` already gets its options from
`index.all_tags()` at page load (built in M1), so a dedicated endpoint would have duplicated that
for no user-visible gain.

**11 new tests** (`admin/tests/test_tags.py`), covering tag inventory counting/ordering,
near-dupe grouping, `tag_map.yaml` case normalization, `rewrite_tags` dedup behavior, and —
critically — that `apply_bulk_retag` writes through `frontmatter.render` (quoted `filesize`
untouched, `archivedate: ` stays empty-with-trailing-space, no `archivedate: null`) rather than
`yaml.dump`. **821/821 green.**

**Live-verified against the real repo:** `GET /tags` renders correctly against all 768 worlds
(near-dupe groups, thin-tag cloud, untagged count all populated). `POST /tags/bulk` was actually
applied against the real corpus — 25 worlds changed, diff was clean and format-preserving
(quoted fields, empty-field trailing spaces, and tag-block indentation all correct; the *only*
change per file was the tags block) — **then reverted** (`git checkout -- _worlds/`) before
committing, since applying it for real is the archivist's call, not something to land silently as
a side effect of shipping the feature. The dry-run/apply flow is proven correct; running it for
real is a one-click action away whenever the archivist wants it.

**What the live test found:** confirmed the corpus really does contain a batch of
`merge_tags.py`-corrupted files (24 of them, `author: null` + unindented tag blocks) — see "Open
items" item 2 for the correction to the wrong M0 finding, and why it's flagged rather than
auto-repaired here.

---

## M2 outcome (2026-07-11)

**The fix designed in "M2 handoff" below was applied to `admin/app/jobs.py` exactly as
specified**, all three pieces:

1. Each job body now runs as its own `asyncio.create_task` (`_run_job`), distinct from the
   worker-loop task, so `cancel(job_id)` targets only that job.
2. A `self._shutting_down` flag, set by `stop()` before cancelling, decides whether `_run()`
   re-raises `CancelledError` (real shutdown → loop exits) or swallows it and continues to the
   next queued job (per-job cancel).
3. `_run_mapgen`'s `finally` now does `if proc is not None and proc.returncode is None:
   proc.kill(); await proc.wait()` before releasing the lock/clearing the temp dir — `proc` is
   hoisted above the `try` so it's always in scope, even if cancellation struck during
   extraction (before a subprocess ever spawned).
4. (Minor hygiene, also applied) `JobQueue.start()` now sweeps any `jobs` rows still `queued` or
   `running` from a previous crashed/force-killed process and marks them `cancelled`, so the
   `/jobs` UI never shows a stuck-forever "running" row after a `pkill -9` or crash.

**New regression tests** (`admin/tests/test_jobs.py`, 3 tests, no new dependency — no
`pytest-asyncio`, each test wraps its body in `asyncio.run`): patches
`asyncio.create_subprocess_exec` to spawn a real `sleep 5` in place of the `node` invocation, so
the tests exercise the actual kill/wait code in milliseconds.
- `cancel()` on a running job kills its subprocess and the worker continues to the next queued job.
- `stop()` kills the in-flight subprocess and `await stop()` returns promptly (doesn't hang).
- `start()` sweeps a `running` row left over from a prior process into `cancelled`.

**809 → 812/812 green** (`admin/.venv/bin/python -m pytest admin/tests -q`).

**Live verification, all against the real repo (server started with `./admin/run.sh`, killed
afterward, `admin/.runtime/` deleted after each run):**

- Reproduced the exact original bug scenario — enqueued a real mapgen job (world `1458329249`,
  ~1 GB uncompressed, so it actually spawns `node dist/generate-map.js` rather than hitting the
  `too_large` preflight skip), waited until the `node` subprocess was confirmed running via `ps`,
  then sent SIGTERM (`kill -TERM`, no `-9`) to the server. **Shutdown completed within ~2
  seconds, no `pkill -9` needed, no orphaned `node` process, `.mapgen-tmp/` ended empty, the
  job's DB row ended `cancelled` (not stuck `running`).** This is the precise failure mode
  described in "M2 handoff" below, now fixed.
- Exercised the same kill through the real `POST /jobs/{id}/cancel` HTTP endpoint (not just
  SIGTERM) against a genuinely slow-rendering world (`1592031274`, ~498 MB, took over 2 minutes
  of node CPU time — legitimately slow, not a hang): the endpoint killed the subprocess,
  released the mapgen lock, cleared the temp dir, marked the job `cancelled`, and **the server
  kept serving requests afterward** (`GET /` still returned 200) — confirming `cancel()` no
  longer takes down the worker loop.
- **Verification item 9 (concurrency guard):** started an admin mapgen job holding the lock,
  then ran `python3 generate_missing_maps.py --world-id 1592031274` concurrently → correctly
  refused with `map generation is already running (pid …)`.
- **Verification item 6 (mapgen parity):** regenerated `map.png` through the job queue for 3
  small worlds with existing committed maps (`11725550371`, `1315348100`, `1315572509`) — all
  three came back **byte-identical** to the committed versions (`git status` empty). Also
  confirmed Starling City (`1705432759`, the world named in item 6, 8.2 GB uncompressed) lands in
  `too_large` **without spawning node**, consistent with the pre-flight design.

**Everything else in M2** (asset grid, SSE job log stream, preview upload/re-fetch,
`generate_missing_maps.py` lockfile) was already spot-verified in the prior session per the
"What's already solid in M2" section below and untouched by this fix.

---

## M2 handoff (2026-07-11, session paused mid-fix) — historical record, bug now fixed above

**Where this session stopped:** mid-edit on `admin/app/jobs.py`, about to apply a fix for a
real concurrency bug found via live testing. The fix is fully designed below but **not yet
written to disk**. `admin/app/jobs.py` on disk right now is the pre-fix version — functional
for the happy path, but unsafe on cancellation/shutdown. Nothing else in M2 is blocked on this;
it's isolated to `jobs.py`.

**Repo state:** working tree matches what's described here (`git status` shows the same M0+M1
untracked/modified files as before, plus `generate_missing_maps.py` modified for the lockfile
addition — see below). No stray `uvicorn` or `node` processes were left running; all killed
before pausing. `admin/.runtime/` was left deleted (gitignored, rebuilds on next `run.sh`).
782+27 tests green (`admin/.venv/bin/python -m pytest admin/tests -q` → **809/809**).

### The bug

Found by actually running the job queue against real worlds (not just unit tests). Sequence:
enqueued a bulk map-generation batch, then sent SIGTERM to the server (`pkill`, no `-9`) to
restart it after a routing fix. Observed **two `node dist/generate-map.js` processes running
concurrently** for two different worlds, and the graceful shutdown *hung* (had to `pkill -9` to
actually kill it).

**Root cause**, confirmed against `jobs` table timestamps: `JobQueue.stop()` calls
`self._worker_task.cancel()`. But `self._current_task = asyncio.current_task()` in the old
`_run()` sets "the job's task" to **the same task object as the worker loop itself** (`_run_mapgen`
runs inline in `_run()`, not as a separate task). So cancelling "the current job" and cancelling
"the whole worker" are indistinguishable — and worse, `_run()`'s per-job `except
asyncio.CancelledError` **catches and swallows** the cancellation, then the `while True` loop
just continues to the *next* queued job. Two consequences:
1. `stop()`'s `await self._worker_task` never actually completes (the task never exits — it
   keeps consuming the queue), so graceful shutdown hangs until force-killed.
2. The **cancelled job's subprocess is never killed** — nothing in the old code calls
   `proc.kill()` on cancellation — so it keeps running in the OS as an orphan, *while the loop
   immediately starts the next job*. That's the two-concurrent-`node`-processes bug, and it
   breaks the hard "concurrency 1 / one unzipped world at a time" invariant the whole
   `.mapgen-tmp/` design depends on.

This is a real bug, not a test artifact — it would happen to any archivist who closes the app
(or hits Ctrl-C) while a map job is running.

### The fix (designed, not yet applied)

Two changes to `admin/app/jobs.py`:

1. **Run each job's body as its own child task**, separate from the worker loop task:
   `self._current_task = asyncio.create_task(self._run_job(job_id, job))` inside `_run()`, then
   `await self._current_task`. This makes `cancel(job_id)` (which cancels `self._current_task`)
   target *only* that job, never the worker loop.
2. **Add a `self._shutting_down` flag**, set by `stop()` before cancelling. In `_run_mapgen`,
   wrap the whole body in one `except asyncio.CancelledError:` that logs, marks the job
   `cancelled` in the DB, publishes the SSE done event, then **always re-raises**. In `_run()`'s
   `await self._current_task`, catch `CancelledError` and **re-raise only if
   `self._shutting_down`** — otherwise swallow it and loop to the next queued job. This is what
   makes `stop()` (cancel + actually exit) and `cancel(job_id)` (cancel + keep serving the
   queue) behave differently despite both going through the same `.cancel()` mechanism.
3. **Kill the subprocess unconditionally on any exit path.** Change the existing
   `finally: mapgen.clear_temp_dir(); mapgen.release_lock()` in `_run_mapgen` to first do
   `if proc is not None and proc.returncode is None: proc.kill()` — this guarantees no orphaned
   `node` process regardless of *where* cancellation/exception struck (extraction phase, subprocess
   spawn, pump loop, wait). Requires hoisting `proc = None` above the try block so it's in scope
   for `finally` even if `create_subprocess_exec` is what got cancelled.
4. (Minor, optional hygiene) On `JobQueue.start()`, sweep any `jobs` rows still `queued` or
   `running` from a previous crashed/killed process and mark them `cancelled` — otherwise a
   force-killed server (`pkill -9`, or a crash) leaves rows stuck `running` forever, which the
   `/jobs` UI would show as perpetually in-progress.

The full rewritten `_run`/`_run_job`/`_run_mapgen`/`cancel`/`stop` was drafted in-session (see
this conversation's tool history around the "I found a genuine concurrency bug" message) — the
shape is: `_run()` owns the loop + shutdown-vs-cancel decision, a new `_run_job()` wraps
kind-dispatch + generic exception handling, `_run_mapgen()` owns the subprocess lifecycle and is
the only place that touches `proc`.

### What to do next, in order

1. **Apply the fix above to `admin/app/jobs.py`.** Re-read the file first (it may have shifted
   slightly) rather than assuming the line numbers above are current.
2. **Add regression tests** for the two behaviors that broke: (a) `cancel()` on a running job
   kills its subprocess and lets the worker continue to the next queued job; (b) `stop()` kills
   the in-flight subprocess and the worker task actually completes (i.e. `await stop()` returns
   promptly, not hangs). These need a fake/slow subprocess (e.g. `sleep 5` via
   `asyncio.create_subprocess_exec` in a test, or monkeypatch `asyncio.create_subprocess_exec`)
   rather than real node-mapgen, so they run in milliseconds.
3. **Re-run the live smoke test**: start the server, enqueue a job, `pkill` (SIGTERM, no `-9`)
   mid-job, confirm (a) shutdown completes within a couple seconds, (b) `ps aux | grep node` shows
   nothing left running, (c) the job's DB row ends up `cancelled` not stuck `running`.
4. Continue M2 with the rest of the verification checklist (item 6: mapgen parity on 3 known-good
   worlds + Starling City goes to `too_large` without spawning node; item 9: concurrency guard
   against a terminal-run `generate_missing_maps.py`) — see "Verification" section below.
5. Once M2's own verification passes, write the "M2 outcome" section (following the M0/M1
   pattern already in this file) and flip the M2 milestone line to ✅ DONE.

### What's already solid in M2 (built and spot-verified this session, not touched by the bug)

- **`core/mapgen.py`** — extraction ladder (raw/gzip/nested-zip), lockfile, pre-flight size
  check, post-hoc error classification. **27 unit tests, all green**
  (`admin/tests/test_mapgen.py`), covering extraction variants, `find_zip`, preflight verdicts,
  error classification, and lock acquire/stale-reclaim/refuse-when-held.
- **Pre-flight correctly caught a real too-large world** live: world `1753809393` has a genuine
  5.6 GB `.eden` (confirmed via `zipfile` inspection) and was skipped as `too_large` **without
  ever spawning node** — exactly per the plan's ~2 GB Node ArrayBuffer-limit design.
  `map_status='too_large'` persisted to the DB via `index.refresh_assets()`.
  - **Caveat, documented in `mapgen.preflight()`'s docstring:** this exact pre-flight is only
    possible for the "raw `.eden` inside the zip" packaging, where the zip's own central
    directory records the true uncompressed size for free. gzip-packaged and nested-zip worlds
    return `"unknown"` from preflight (can't cheaply know the real size without the M4 streaming
    payload hasher) and fall back to post-hoc classification if node actually chokes on them.
    This is a deliberate, plan-consistent scope reduction, not an oversight.
- **A real mapgen job ran end-to-end successfully** live: world `1768873101` — job completed
  `ok`, `map.png` regenerated, and **the regenerated PNG was byte-identical to the previously
  committed one** (`git status` showed no diff) — good empirical evidence the renderer is
  deterministic, which is what verification item 6 (mapgen parity) will formally check.
- **Post-hoc error classification confirmed live**: manually `kill -9`'d a node subprocess mid-run
  (simulating a crash) → correctly classified as `node_error` and the job marked `failed`. (This
  test predates the cancellation-path work; it exercises a *different* code path — an externally
  killed process the job wasn't trying to cancel itself — and is unaffected by the bug above.)
- **One of the ~14 known-oversized worlds was discovered concretely**: `1753809393` ("Big Ben
  Test17"), 5.6 GB uncompressed. Worth keeping a running list as more are found during M2/M4
  verification.
- **Routing bug found and fixed during this session**: `app.mount("/assets", StaticFiles(...))`
  was registered *before* `app.include_router(assets_api.router)` in `admin/app/main.py`, so the
  static mount's prefix match swallowed every request under `/assets/*` — including the new
  `POST /assets/{world_id}/map` — before the router ever saw them (405 Method Not Allowed). Fixed
  by moving all `app.include_router(...)` calls before the `app.mount(...)` calls, with a comment
  explaining why the order matters. **This fix is live and correct**, unrelated to the
  cancellation bug above.
- **`core/index.py`** additions: `refresh_assets()` (targeted re-stat of one slug's assets,
  needed because the incremental `scan()` skips a slug whose *markdown* file didn't change, even
  if its map.png just appeared — asset changes don't touch the .md mtime), plus job CRUD
  (`create_job`, `update_job`, `get_job`, `list_jobs`, `append_log`, `job_logs`) and
  `get_by_world_id()`. All exercised live, no known issues.
- **Templates/routes for `/assets` (grid), `/jobs` (list + detail + SSE log stream), and the
  world-detail page's new asset action buttons** (generate map, upload preview, retry preview
  fetch) — built and smoke-tested for the happy path (see above). The SSE log stream
  (`GET /jobs/{id}/stream`, htmx `sse-swap`) has **not** been visually verified in a browser this
  session (only exercised via curl/DB checks) — worth an eyeball check once the queue fix lands.
- **`generate_missing_maps.py`** gained a matching lockfile check (`check_not_locked` /
  `acquire_lock` / `release_lock`, sharing `.mapgen-tmp/.lock` with `core/mapgen.py`) so the
  standalone script and the admin app's job queue refuse to run concurrently in either direction.
  **Not yet tested live** (verification item 9) — do that after the jobs.py fix, since a hung
  job queue could give a false pass/fail right now.

### Files touched this session (M1 + M2), for orientation on next pickup

- `admin/core/frontmatter.py`, `admin/core/world.py` — M1, done, tested, stable.
- `admin/app/routers/worlds.py`, `admin/app/templates/world_detail.html`,
  `admin/app/static/app.css` — M1 (editing) + M2 (asset action buttons) additions, stable.
- `admin/core/mapgen.py` — M2, new, stable, well-tested.
- `admin/core/index.py` — M2 additions (`refresh_assets`, job CRUD, `get_by_world_id`, `now()`),
  stable.
- `admin/app/jobs.py` — M2, new, **has the live bug described above, fix designed but not
  applied**.
- `admin/app/routers/assets_api.py`, `admin/app/routers/jobs_api.py` — M2, new, stable (routes
  themselves are fine; they just call into the buggy `JobQueue`).
- `admin/app/templates/assets.html`, `partials/asset_grid.html`, `partials/bulk_enqueued.html`,
  `partials/preview_fetch_result.html`, `jobs.html`, `job_detail.html` — M2, new, stable.
- `admin/app/main.py` — M2: `JobQueue` wired into lifespan, routers reordered before static
  mounts (see routing-bug fix above).
- `admin/app/templates/base.html` — M2: nav links for Assets/Jobs enabled.
- `generate_missing_maps.py` — M2: lockfile addition, not yet live-tested.
- `admin/tests/test_mapgen.py` — new, 27 tests, green.
- `admin/tests/test_world_edit.py`, `admin/tests/test_frontmatter_roundtrip.py` — M1, stable.

---

## M1 outcome (2026-07-11)

**Shipped:** editable front-matter form (worldname, author, publishdate, archivedate, filesize,
tags) + body textarea on `/worlds/{slug}`, `POST /worlds/{slug}` save handler, format-preserving
writes through `frontmatter.save`/`world.save`, date validation (rejects malformed
publishdate/archivedate without touching the file), and an incremental reindex after every save.

**`frontmatter.render`/`save` gained an optional `body=` override** — previously the body always
passed through `doc.body` untouched with no way to edit it; now `None` keeps the old byte-exact
behavior (all 788 tests still green) and a string replaces it. `core/world.py` gained
`normalize_body()` (editor text → the corpus convention: leading `\n`, exactly one trailing `\n`,
whitespace-only body collapses to `\n`) and `save()`, the single entry point the router uses.

**Verified live against the real repo, then reverted** (world `070032-980002`):
1. Submitting the edit form unchanged → `git status --porcelain` on the file is empty.
2. Adding one tag → `git diff` shows exactly `+  - newtag` and nothing else.
3. Submitting an invalid `publishdate` → 400, form re-rendered with an error, file untouched.

These are also covered by `admin/tests/test_world_edit.py` against throwaway fixtures (the corpus
itself is never touched by the test suite — `WRITABLE_ROOTS`/`RUNTIME_DIR`/`BACKUP_DIR` are
monkeypatched to `tmp_path`). **788/788 green.**

**Not done in M1** (deliberately out of scope, per the plan's phasing): tag autocomplete is a
plain `<datalist>`, not the fancier picker; no HTMX partial-save (full form POST + full page
re-render, which is enough for a local single-user tool); no per-field diff preview before saving
— the git diff panel below the form is the review step.

---

## M0 outcome (2026-07-11)

**Shipped:** `core/{paths,frontmatter,world,index,git}.py`, SQLite index + incremental scanner,
FastAPI app (dashboard, `/worlds` search + filters, read-only detail, git panel), `run.sh`,
vendored htmx, `_config.yml` + `.gitignore` updates. **Zero writes to the corpus.**

**Gating test: 782/782 green** — all 775 corpus files round-trip byte-for-byte.
Cold scan 1.4 s, warm 0.01 s.

**Python 3.14 question — RESOLVED.** FastAPI 0.139 + pydantic 2.13.4 install from wheels on
3.14.3. No Starlette fallback needed; the escape hatch can be forgotten.

**Four things the plan didn't know, found by building it:**

1. **`edenadmin.py validate` has a latent bug: it flags all 768 worlds `invalid_publishdate`.**
   PyYAML loads a bare `2011-09-07` as a `datetime.date`, not a `str`, so its
   `isinstance(pd, str)` check (line 136) always fails. Never noticed because PyYAML was never
   installed, so the command crashed before reaching it. `core/world.validate()` compares on the
   rendered form instead. Every other count matches the CLI exactly — **that is the parity check
   (item 4) passing.**
2. **`_articles/creatures.md` has malformed front matter** — a bare `Eden World Builder Wiki`
   line with no key, which is invalid YAML. `frontmatter.parse()` tolerates it (bytes preserved,
   `doc.malformed=True`, flagged in the UI) rather than crashing. Worth repairing by hand.
3. **One `worldname:` line carries a trailing space** that YAML strips on load, so re-emitting an
   unchanged value would silently rewrite those bytes. `render()` now leaves any semantically
   unchanged line byte-identical — which is what makes verification item 2 (a no-op save through
   the UI produces an empty `git status`) hold by construction.
4. **The FTS5 table must not be contentless.** `content=''` cannot service the per-slug `DELETE`
   the incremental scan does on every rewrite, and silently indexes nothing.

**Not verified locally:** `bundle exec jekyll build` — the system Ruby (2.6) has a bundler
version mismatch, unrelated to this work. The exclusions only stop `admin/`, `z_scripts/`,
`node-mapgen/` and `*.py` from being *copied* into `_site`; nothing under `_worlds`, `_articles`,
`assets` or `_includes` is touched, so `worlds.json` is unaffected by inspection. **Confirm on the
next Pages deploy.**

---

## Context

The archive has 768 worlds managed by a scattering of one-off Python scripts that only work from a terminal, are duplicated three times over, and in two cases are outright broken. Adding or curating a world means running an interactive CLI, answering prompts, and hoping the map renders. There is no way to see the archive as a whole — no search, no way to spot a world that's missing its map, no way to notice you've just re-uploaded a world that's already archived under a slightly different name.

The goal is a **local-only web app** that an archivist runs against a cloned copy of this repo. It gives them a real interface for viewing, editing, and curating worlds and blog posts, plus the "smart" checks that are impractical from a CLI: duplicate detection, version-chain detection, tag health, and a similar-name warning at upload time. It writes plain files into the working tree; the archivist reviews with `git diff` and pushes to publish. It never talks to GitHub itself.

---

## Decisions locked in (confirmed with the user)

| Decision | Choice |
|---|---|
| Stack | **Python FastAPI + Jinja2 + HTMX.** No JS build step, `htmx.min.js` vendored. |
| Git | **Working-tree only.** The app writes files and shows a read-only pending-changes panel. It never commits, pushes, or checks out. |
| Index | **SQLite cache**, gitignored, rebuilt on demand. Markdown stays the source of truth. |
| Scope | All four feature areas (dupes, tag health, assets/maps, blog CRUD) + upload flow, phased M0–M6. |
| Existing scripts | **Refactor into a shared `admin/core/` package.** Delete the duplicate copies, fix the broken tag commands, rewire the CLI to import from core. |
| Repo size (1.1 GB assets, no LFS) | **Out of scope — warn only.** App surfaces size, doesn't change storage. |
| Worlds >2 GB (~14 of them) | **Detect, flag, allow manual `map.png` upload.** No failed jobs. |

---

## What we learned about the repo (this is the part worth not re-deriving)

These findings drove the design and are easy to get wrong:

**Front matter is not uniform.** Two shapes exist across `_worlds/*.md`:
- **560 files:** `layout, filename, worldname, publishdate, author, tags`
- **208 files:** the same plus `archivedate, filesize`

**The exact byte conventions matter**, because the files were hand-written by `z_add_world.py:190-201`, not emitted by a YAML library:
- Empty values are written as `key: ` **with a trailing space**. 598 files have `author: ` (trailing space); zero have a bare `author:`.
- All 208 `archivedate:` lines are empty. The field is currently unused across the entire archive.
- `filesize` is **always** double-quoted (`filesize: "3.5 MB"`). `worldname`, `author`, `publishdate` are never quoted.
- Tags are block sequences: `tags:` then `  - tag` at 2-space indent.
- Files are LF, ASCII, and end with exactly one newline.

**`z_scripts/tag manage/merge_tags.py` corrupts formatting today.** Its `save_file()` calls `yaml.safe_dump(fm, sort_keys=False)`, which unquotes `filesize`, turns empty `archivedate:` into `archivedate: null`, and re-wraps everything. Any file it has already touched has drifted. **The new app must never call `yaml.dump` on a world file.** This is the single biggest correctness risk in the project.

**Other facts:**
- `z_add_world.py` exists in **three** places: repo root, `script.py` (byte-identical), and `z_scripts/z_add_world.py`.
- `edenadmin.py`'s `tags analyze` / `tags merge` subcommands are **broken** — it runs them with `cwd=TAG_DIR`, but they hardcode `Path("_worlds")`, so they read zero worlds.
- **PyYAML and requests are not installed.** `python3` is **3.14.3** (Homebrew). Only `pillow` is present. So `edenadmin.py validate` currently fails outright.
- `z_add_world.py:186` does `(asset_dir / worldname).touch()` — every asset dir has a stray 0-byte file named after the world. The indexer must ignore it.
- `generate_missing_maps.py` is the **best-engineered file in the repo**. Its `_extract_eden()` handles all three zip packagings in the wild. Reuse it wholesale.
- `worlds.json` is **Jekyll-generated at build time** from `_includes/worlds.json`. You cannot read it for an index — scan `_worlds/*.md` directly.
- Asset reality: 768 md files, **764 zips, 746 maps, 539 previews**. So ~4 missing zips, ~22 missing maps, ~229 missing previews.
- `node-mapgen/node_modules` is installed and `dist/` **is built**, so the fast `node dist/generate-map.js` path is live.
- No Git LFS. `assets/worldfiles/` (1.1 GB) is committed directly; `.git` is already 2.1 GB.

---

## Architecture

Everything lives under the existing `admin/` directory, which becomes the single admin surface.

```
admin/
├── requirements.txt
├── run.sh                     # single launch command (venv + install + uvicorn)
├── edenadmin.py               # EXISTING CLI — refactored to import admin.core.*
├── core/                      # pure library, no FastAPI imports, CLI-usable
│   ├── paths.py               # REPO_ROOT, WORLDS_DIR, ASSETS_DIR, MAPGEN_DIST, TEMP_DIR, WORLD_ID_RE
│   ├── frontmatter.py         # ★ format-preserving parse/render — see below
│   ├── world.py               # World dataclass, load/save, slugify, validate()
│   ├── content.py             # _posts / _articles parse, list, save
│   ├── hashing.py             # streaming sha256 of zip + decompressed .eden payload
│   ├── mapgen.py              # zip→.eden extraction, node subprocess, error classification
│   ├── tags.py                # tag inventory, difflib near-dupe grouping, tag_map.yaml
│   ├── dupes.py               # normalization, version-token stripping, pair scoring
│   ├── index.py               # SQLite open/migrate/scan/query
│   ├── importer.py            # non-interactive port of z_add_world.py:import_one_file()
│   └── git.py                 # read-only git status/diff/ahead-behind
├── app/
│   ├── main.py                # app factory, lifespan (db, scan, job worker, git check)
│   ├── jobs.py                # in-process asyncio job queue + SSE broadcast
│   ├── routers/               # dashboard, worlds, assets, jobs_api, tags_api,
│   │                          # dupes_api, content_api, upload, git_api
│   ├── templates/             # base + page templates + partials/ for HTMX fragments
│   └── static/                # vendored htmx.min.js, app.css
├── tests/
│   └── test_frontmatter_roundtrip.py   # ★ the gating test
└── .runtime/                  # GITIGNORED — index.db, backups/, uploads/, jobs/
```

### Reuse map (what comes from where)

| New module | Extracted from |
|---|---|
| `core/paths.py` | `admin/edenadmin.py:11-27`, `generate_missing_maps.py:22-29` |
| `core/world.py` | `edenadmin.py:validate_world()` (104-152), `z_add_world.py:slugify()` (20-24), `bytes_to_mb()` (26-27) |
| `core/mapgen.py` | `generate_missing_maps.py:_is_junk/_real_entries/_extract_eden/find_zip/generate_map` (44-170) — lift the extraction ladder verbatim |
| `core/tags.py` | `z_scripts/tag manage/analyze_tags.py` (difflib grouping, cutoff 0.85). **Discard its `save_file()`.** |
| `core/importer.py` | `z_add_world.py:import_one_file()` (110-215), with all `input()` prompts removed |
| `core/frontmatter.py` | New — but must reproduce the emitter at `z_add_world.py:190-201` byte-for-byte |

`generate_missing_maps.py`, `z_add_world.py`, and the tag scripts stay at their paths as **thin shims** over `core/`, so existing habits and CLAUDE.md keep working (M7).

---

## The critical piece: format-preserving front matter

**Do not use `yaml.dump`.** Reproduce the hand-written emitter exactly.

```python
CANONICAL_ORDER = ["layout", "filename", "worldname", "publishdate",
                   "archivedate", "filesize", "author", "tags"]
ALWAYS_QUOTED = {"filesize"}    # the only key ever quoted in the corpus

def parse(path) -> Document     # keeps fm_lines verbatim + yaml.safe_load for reading
def render(doc, updates) -> str # returns full file text
def save(path, doc, updates)    # backup → atomic write via os.replace()
```

`render()` rules, derived from the corpus:
1. Iterate the original front-matter lines. For a key in `updates`, **replace only that line**; every other line stays byte-identical.
2. Scalar emission: `key: value`, or **`key: ` with a trailing space when empty** (matches all 598 `author: ` lines). Quote if the key is in `ALWAYS_QUOTED` or the original line was quoted.
3. `tags` replaces the `tags:` line plus its contiguous `  - ` lines. Preserve existing tag order; append new tags at the end, so a bulk retag is a one-line diff.
4. A key in `updates` not present in the file (e.g. setting `archivedate` on one of the 560 short-form files) is inserted at its `CANONICAL_ORDER` position.
5. A key set to **empty** on a file where it doesn't exist is a **no-op** — never add `archivedate: ` to 560 files and blow up the diff.
6. Body passes through byte-for-byte. File ends with exactly one `\n`.

**Gating invariant:** for all 768 worlds + 4 articles + 3 posts, `render(parse(f), {}) == f.read_bytes()`. 775/775 or the write features don't ship.

---

## SQLite schema (`admin/.runtime/index.db`)

Disposable cache, **except** dismissed-dupe decisions — those also append to `admin/dupe_dismissals.yaml`, which **is committed**, so the DB stays safely throwaway.

```sql
PRAGMA journal_mode=WAL;

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE worlds (
  slug TEXT PRIMARY KEY, md_path TEXT NOT NULL, world_id TEXT,
  layout TEXT, filename TEXT, worldname TEXT, publishdate TEXT,
  archivedate TEXT, filesize TEXT, author TEXT,
  fm_key_order TEXT,          -- JSON list: remembers which of the 2 shapes this file uses
  body_sha256 TEXT,
  md_mtime_ns INTEGER, md_size INTEGER, md_sha256 TEXT,   -- incremental scan
  asset_dir TEXT,
  has_zip INTEGER, zip_path TEXT, zip_bytes INTEGER, zip_sha256 TEXT, zip_mtime_ns INTEGER,
  has_preview INTEGER, preview_bytes INTEGER,
  has_map INTEGER, map_bytes INTEGER, map_mtime_ns INTEGER,
  payload_sha256 TEXT, payload_bytes INTEGER, payload_head_sha256 TEXT,
  payload_hashed_at TEXT, payload_error TEXT,
  map_status TEXT,            -- ok | missing | too_large | failed | pending
  map_error TEXT,
  norm_name TEXT, base_name TEXT, version_token TEXT, name_tokens TEXT,
  issues TEXT, indexed_at TEXT
);
CREATE INDEX idx_worlds_base    ON worlds(base_name);
CREATE INDEX idx_worlds_payload ON worlds(payload_sha256);
CREATE INDEX idx_worlds_zipsha  ON worlds(zip_sha256);

CREATE TABLE world_tags (
  slug TEXT REFERENCES worlds(slug) ON DELETE CASCADE,
  tag TEXT NOT NULL, pos INTEGER NOT NULL,   -- pos preserves original order on rewrite
  PRIMARY KEY (slug, tag)
);

CREATE VIRTUAL TABLE worlds_fts USING fts5(
  slug UNINDEXED, worldname, author, tags, body, content=''
);

CREATE TABLE dupe_pairs (
  a_slug TEXT, b_slug TEXT,     -- always stored a_slug < b_slug
  reason TEXT,                  -- identical_payload | identical_zip | near_name
                                -- | version_chain | same_author_similar
  score REAL, detail TEXT,
  status TEXT DEFAULT 'new',    -- new | confirmed_dupe | confirmed_version | dismissed
  status_note TEXT, status_at TEXT,
  PRIMARY KEY (a_slug, b_slug, reason)
);

CREATE TABLE jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT,     -- mapgen | payload_hash | dupe_scan | bulk_retag | reindex | import
  target TEXT, params TEXT,
  status TEXT,   -- queued | running | ok | failed | cancelled | skipped
  result TEXT, error_class TEXT,
  queued_at TEXT, started_at TEXT, ended_at TEXT
);

CREATE TABLE job_logs (
  job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
  seq INTEGER, ts TEXT, stream TEXT, line TEXT,
  PRIMARY KEY (job_id, seq)
);
```

**Scan strategy:** compare `(mtime_ns, size)` per md file; unchanged → skip. `zip_sha256` recomputed only on zip mtime change. `payload_sha256` is **never** computed during a scan — only by the background `payload_hash` job. Cold scan of 768 files should be well under 5 s.

---

## Duplicate & version detection

**Two-tier hashing.**

*Tier 1 — zip bytes* (cheap, during scan): `sha256` of `.eden.zip`, streamed. Catches byte-identical re-uploads. Insufficient alone — the same world packaged two of the three ways gives different zip hashes.

*Tier 2 — decompressed `.eden` payload* (the canonical identity, background job): reuse the `_extract_eden` decision tree from `generate_missing_maps.py`, but **stream instead of extract** — `zf.open(entry)`, sniff for gzip magic `1f 8b`, wrap in `gzip.GzipFile(fileobj=...)`, read 1 MiB chunks into `hashlib.sha256()`.

This **sidesteps the 2 GB Node limit entirely** — Python streams the 8.8 GB Starling City payload without materializing it, so even the ~14 giant worlds get a payload hash. They just can't get a *map*. Peak memory ~1 MiB, zero disk. Budget 3–10 minutes for a one-time full pass, cached forever after.

**Name similarity: stdlib `difflib` only, no new dependency.** 768 worlds → 294k pairs, but a cheap prefilter (length ratio < 0.5, no shared token or 3-gram) cuts the real `SequenceMatcher` calls to tens of thousands. Sub-second. `rapidfuzz` isn't worth a compiled dep at n=768; revisit past ~10k worlds.

Normalize: lowercase → strip diacritics → non-alphanumerics to spaces → collapse. Then strip version tokens off the tail, repeatedly (`"city v2 final"` → base `"city"`, tokens `["v2","final"]`):

```
v2 | v 2 | v1.1 | version 2 | final | fixed | updated | new | old | revised
| remake | remaster | redux | complete | wip | beta | copy | rc1
| part 2 | pt2 | ep3 | trailing bare number | (1) | ii | iii | iv
```
Guard: never strip if the result is empty or under 3 chars, so a world literally named "2" survives.

**Candidate scoring:**

| reason | condition | score |
|---|---|---|
| `identical_payload` | same `payload_sha256`, different slug | 1.00 |
| `identical_zip` | same `zip_sha256`, payload not yet hashed | 0.98 |
| `version_chain` | same `base_name`, ≥1 has a version token | 0.90 |
| `near_name` | `SequenceMatcher.ratio() >= 0.87` or token Jaccard ≥ 0.8 | ratio |
| `same_author_similar` | equal non-empty author, ratio ≥ 0.70, within 90 days | 0.70 + 0.3·ratio |

Upsert with `ON CONFLICT DO UPDATE SET score, detail` — **`status` is never overwritten**, so dismissals survive rescans.

**Upload-time check** (`POST /upload/stage`), against the staged file only:
1. World ID already archived → **hard block**, offer "replace assets" instead.
2. Payload hash match → "byte-identical to X".
3. Zip hash match → "identical download to X".
4. Name similarity ≥ 0.75 or version-chain base match → soft warn, side-by-side with name/author/date/map thumbnail.

The archivist must explicitly click "Import anyway" to pass 2–4.

---

## Background job queue

**Single in-process `asyncio` worker, concurrency 1.** No Celery, no Redis. This is a single-user local app.

- Started/stopped in the FastAPI `lifespan`.
- **Concurrency 1 is a hard invariant** — it's what satisfies the existing "never more than one unzipped world on disk" constraint. `.mapgen-tmp/` is cleared before and after every job in a `finally:`.
- **Lockfile** `.mapgen-tmp/.lock` (PID + timestamp): if the archivist also runs `generate_missing_maps.py` in a terminal, the app refuses the job rather than stomping the shared temp dir. The standalone script gets the same check when refactored onto `core/mapgen.py`.
- Execution: `asyncio.create_subprocess_exec("node", MAPGEN_DIST, eden, out, cwd=node-mapgen)`, read line-by-line → `job_logs` + pushed to SSE subscribers. 300 s timeout.
- **SSE:** `GET /jobs/{id}/stream` replays existing log rows then streams new ones. Uses HTMX's SSE extension (`sse-connect` / `sse-swap`) — no bespoke JS. Hand-rolled `StreamingResponse`, ~20 lines, no `sse-starlette` dep.

**The >2 GB failure, handled gracefully — two mechanisms:**

1. **Pre-flight (preferred, avoids wasting minutes):** sum `zipinfo.file_size` over the zip's central directory — free, no decompression. If uncompressed size > **1.9 GB**, mark the job `skipped`, `error_class='too_large'`, `map_status='too_large'`, and **never invoke node**. For nested/gzip cases where `file_size` is the inner compressed size, fall back to the exact `payload_bytes` from the hashing job.
2. **Post-hoc classification:** if node dies, match stderr — `RangeError: Invalid typed array length` / `Array buffer allocation failed` / `Cannot create a string longer than` / heap OOM → `too_large`. Other non-zero exit → `node_error`. `ENOENT` on `node` → `env_error` with an `npm install && npm run build` hint.

`too_large` renders as a grey pill ("Too large for node-mapgen — payload N GB, Node 2 GB ArrayBuffer limit"), is **excluded from bulk generate-all-missing** by default, is **not counted as a defect** on the dashboard, and offers a manual `map.png` upload.

---

## Routes (HTMX surface)

Full page or fragment depending on the `HX-Request` header.

| Route | Purpose |
|---|---|
| `GET /` | Dashboard: counts, issue tallies, open dupes, job state, git panel |
| `GET /git` · `POST /git/fetch` | Pending-changes panel (polled every 10s); explicit fetch is the only network git op |
| `GET /worlds` | FTS search + tag/author/asset/issue filters + sort → swaps `#world-table` |
| `GET`/`POST /worlds/{slug}` | Detail; front-matter form + body; save via `frontmatter.render()` |
| `GET /worlds/{slug}/diff` | `git diff` for just this file |
| `GET /assets` | Asset grid, status pills, paginated |
| `POST /assets/{id}/map` · `/assets/mapgen/bulk` | Enqueue map generation (single / filtered set) |
| `POST /assets/{id}/preview` · `/preview/fetch` | Upload a preview, or re-try `files.edengame.net` |
| `GET /jobs` · `GET /jobs/{id}/stream` · `POST /jobs/{id}/cancel` | Queue UI + SSE log |
| `GET /tags` · `/tags/suggest` · `POST /tags/bulk` | Tag health, autocomplete, bulk retag (dry-run diff first) |
| `GET /dupes` · `POST /dupes/{a}/{b}/{reason}` · `POST /dupes/scan` | Review UI, confirm/dismiss |
| `GET`/`POST /content[/{kind}/{name}]` | `_posts` + `_articles` CRUD, markdown live preview |
| `GET /upload` · `POST /upload/stage` · `POST /upload/commit` | Upload → similarity review → import → enqueue map |

---

## Dependencies & launch

`admin/requirements.txt`:
```
fastapi>=0.115
uvicorn[standard]>=0.32
jinja2>=3.1
python-multipart>=0.0.12   # file uploads
PyYAML>=6.0                # already used by existing scripts (NOT INSTALLED YET)
requests>=2.32             # already used; preview download (NOT INSTALLED YET)
markdown>=3.7              # live preview for posts/articles
```
Deliberately excluded: rapidfuzz, sse-starlette, SQLAlchemy. `htmx.min.js` vendored (~48 KB, committed) — no CDN, works offline.

**⚠️ Python 3.14 risk — resolve first, in M0.** System `python3` is **3.14.3**. FastAPI pulls in `pydantic-core` (Rust); if no 3.14 wheel is published, `pip install` attempts a source build and likely fails. `run.sh` probes `python3.12 → python3.13 → python3`. **Escape hatch:** this app uses zero pydantic features (all handlers take `Form(...)`/`Request`), so it can drop to plain **Starlette + Jinja2 + uvicorn** at almost no cost. Settle it with a 2-minute `pip install fastapi` spike.

`./admin/run.sh` — picks interpreter → creates `admin/.venv` → installs if the requirements hash changed → checks `node-mapgen/dist/generate-map.js` exists → `exec uvicorn admin.app.main:app --host 127.0.0.1 --port 8765 --reload`.

**Security boundary:** bound to `127.0.0.1` only; refuses to start on a non-loopback bind. No auth (same-origin local). The real boundary is that **every write path is validated to be inside** `_worlds/`, `_posts/`, `_articles/`, or `assets/worldfiles/`, with slug/world_id regex-validated and no `..`.

### Repo config changes

`_config.yml` — **required, or the admin app gets published to GitHub Pages:**
```yaml
exclude:
  - z_Uploading
  - node-mapgen-broken
  - admin          # NEW
  - z_scripts      # NEW
  - node-mapgen
  - "*.py"
  - Gemfile
  - Gemfile.lock
```

`.gitignore` additions (`.mapgen-tmp/` is already ignored and gets reused):
```
admin/.runtime/
admin/.venv/
__pycache__/
*.pyc
```

---

## Git integration (read-only)

`core/git.py` — `status()` (`--porcelain=v1 -z`, grouped by directory), `diffstat()`, `file_diff(path)`, `ahead_behind()` (`rev-list --left-right --count HEAD...origin/main` against the **cached** ref, no implicit network).

- Startup: if the working tree is already dirty, banner — "Working tree was already dirty when the admin started (N files) — changes below may not all be yours."
- If `origin/main` is ahead: red banner, "pull before editing."
- The app **never** runs `add`, `commit`, `push`, `checkout`, `reset`, or `clean`. The panel ends with a copy-paste-ready `git add … && git commit -m "…"` string the archivist runs themselves.

---

## Milestones

**M0 — Foundation + read-only. ✅ DONE (2026-07-11).** `core/paths|frontmatter|world|index|git`, SQLite schema, incremental scanner, `run.sh`/venv/requirements, `_config.yml` + `.gitignore`, FastAPI shell + base template + HTMX. Ships: dashboard, `/worlds` with FTS search and filters, read-only world detail, git panel. **Zero writes to the repo.** Round-trip test green at 782/782 — the license to build M1. Python 3.14 / pydantic question resolved. See the M0 outcome section above.

**M1 — World editing. ✅ DONE (2026-07-11).** `frontmatter.render/save` + backups + atomic writes. Editable front-matter form + body. Tag input with `<datalist>` autocomplete. Per-world `git diff` panel (already existed from M0, now reflects live edits). See the M1 outcome section above.

**M2 — Assets + job queue. ✅ DONE (2026-07-11).** `core/mapgen`, `app/jobs.py` + SSE, asset grid, single + bulk map generation, `too_large` pre-flight, preview upload + re-fetch. See the M2 outcome section above.

**M3 — Tag health. ✅ DONE (2026-07-11).** `core/tags`, difflib near-dupe grouping, thin/missing-tag reports, `tag_map.yaml` apply **routed through `frontmatter.render`** (replacing the format-destroying `merge_tags.py:save_file`), bulk retag with mandatory dry-run diff. Shipped as synchronous routes rather than a queued job — see the M3 outcome section above for why. See the M3 outcome section above.

**M4 — Dupes & versions. ✅ DONE (2026-07-11).** `core/hashing` streaming payload hash over the archive, `core/dupes` scoring, `/dupes` review UI, persisted dismissals. See the M4 outcome section above.

**M5 — Blog/article CRUD. ✅ DONE (2026-07-11).** `core/content`, list/create/edit/delete, markdown live preview, filename/date/slug rules with rename warnings. See the M5 outcome section above.

**M6 — Upload flow. ✅ DONE (2026-07-11).** `core/importer` (de-interactivized `z_add_world.py`), staged upload → hash + similarity check → review panel → commit → auto-enqueue map. See the M6 outcome section above.

**M7 — Cleanup (optional).** Rewrite `generate_missing_maps.py`, `z_add_world.py`, `z_scripts/tag manage/*` as thin shims over `core/`. Delete `script.py` and `z_scripts/z_add_world.py`. Update `CLAUDE.md`.

**M8 — Eden Server integration + ribbon design. ✅ DONE.** `core/edenserver.py` (Python port of `~/eden-world-editor`'s `network.rs`: listing parse, search/browse, gzip-safe capped download, preview fetch, `score_world` heuristic). `/server` browse/search page with archive-status badges (`archived` / `possibly archived`, reusing `importer.check_against_archive`'s cutoff) and an infinite-scroll "load more" via htmx OOB swap on the pager. `server_fetch` job downloads a world into a fresh staged upload and links to `GET /upload/review/{token}` (split out of `POST /upload/stage` so a finished job can reach the same review screen). `preview_backfill` job (button on `/assets`) bulk-fetches missing previews, logging misses as skips, not failures. `importer._try_download_preview` and the `/assets/{id}/preview/fetch` button now go through `edenserver.fetch_preview_any` (current, then legacy) instead of legacy-only. Top bar restyled as an Office-style ribbon tab strip using VuencEdit's ported palette/geometry tokens (`--rbn-*` in `app.css`) with a violet accent instead of the editor's cyan, and a "VuencLibrary" brand badge in place of the old "Eden Archive admin" wordmark — scoped to the top bar only, no changes to any page body. See `admin/tests/test_edenserver.py`.

---

## Verification

The formatting test gates everything else. Status as of M0:

1. ✅ **Front-matter round-trip (blocking):** for all 768 worlds + 4 articles + 3 posts, `render(parse(p), {}) == p.read_bytes()`. **782/782 green** (775 corpus files + 7 unit tests). Run: `admin/.venv/bin/python -m pytest admin/tests -q`.
2. ✅ **No-op save through HTTP** (M1): open a world, submit the form unchanged → `git status --porcelain` must be **empty**. Verified live against `070032-980002` (both front-matter shapes covered by `test_world_edit.py`'s fixtures). *`render()` guarantees this by leaving semantically-unchanged lines byte-identical — see M0 finding 3.*
3. ✅ **Targeted diff** (M1): add one tag via the UI → `git diff` shows exactly `+  - newtag` and nothing else. Verified live and in `test_world_edit.py::test_adding_one_tag_is_a_single_line_diff`.
4. ✅ **Validate parity:** the app's counts match `edenadmin.py validate` exactly — 1 `missing_asset_dir`, 5 `missing_zip`, 227 `missing_preview`, 14 `missing_map`, 392 `missing_tags`. The **only** divergence is `invalid_publishdate`, where the CLI reports 768 (all worlds) and the app reports 0 — the CLI is wrong; see M0 finding 1.
5. ⚠️ **Jekyll unchanged:** **could not run** — the local Ruby toolchain is broken (system Ruby 2.6 vs. bundler mismatch), unrelated to this work. Verified by inspection instead: the new exclusions only stop `admin/`, `z_scripts/`, `node-mapgen/` and `*.py` from being copied into `_site`; nothing under `_worlds`, `_articles`, `assets` or `_includes` is touched, so `worlds.json` is unaffected. **Confirm on the next Pages deploy.**
6. ✅ **Mapgen parity:** regenerated 3 known-good maps through the queue (`11725550371`,
   `1315348100`, `1315572509`) → all byte-identical to the committed ones (`git status` empty).
   Starling City (`1705432759`) lands in `too_large` without spawning node. *(Did not confirm the
   64z/256z/gzip-packaging split specifically — the 3 worlds chosen were small ones with existing
   maps, picked for speed; worth a follow-up if a format-specific regression is ever suspected.)*
7. ✅ **Payload hashing:** ran the full bulk-hash job against all 762 unhashed real worlds —
   `.mapgen-tmp/` stayed empty throughout (confirmed, streaming not extracting), 763/763
   succeeded including Starling City (8.8 GB). *(Peak RSS wasn't independently profiled, but the
   design streams in 1 MiB chunks and never buffers a full payload — see core/hashing.py — so
   this is expected by construction, not just by observation.)*
8. ✅ **Dupe sanity:** ran the scan against the real archive (458 pairs from 768 worlds),
   eyeballed the top-scored results — genuinely useful (a likely typo'd duplicate slug at 0.98
   near-name, a real version series from one author, 8 byte-identical re-uploads under different
   names). The 0.87 near-name cutoff wasn't retuned — real output looked reasonable at the
   plan's original value, so there was no signal to tune against.
9. ✅ **Concurrency:** ran `generate_missing_maps.py --world-id 1592031274` in a terminal while an
   admin mapgen job for the same world held the lock → refused with the lock message, exactly as
   designed.

---

## Open items / things to watch

1. ~~**Python 3.14 + pydantic wheels**~~ — **RESOLVED in M0.** FastAPI 0.139 + pydantic 2.13.4
   install from wheels on 3.14.3. No fallback needed.

2. ~~**CORRECTION (M3, 2026-07-11): the M0 finding below was wrong.**~~ **FIXED (2026-07-11,
   immediately after M3).** `merge_tags.py` *had* mangled files — the original M0 claim
   ("RESOLVED: it hasn't") checked `filesize`/`archivedate`, which happen to be absent from the
   affected files, and missed the two fields that actually showed the damage:
   - **24 files had a literal `author: null`** instead of the corpus convention's `author: ` with
     a trailing space. Confirmed via `git log -p` on one of them (`barnim-v28.md`, commit `571d584
     "cleaned tags using script"`) that this predates the admin app entirely — `yaml.safe_dump`
     rendering `None` as `null`, from a run of `merge_tags.py` before this project existed.
   - **41 files** (the 24 above plus 17 more whose `author` happened to already be set, so they
     had no `null` symptom) **had the tags block's 2-space indent stripped** — `- tag` at column 0
     instead of `  - tag`, `yaml.safe_dump`'s default list indentation.
   - **Fixed via `frontmatter.repair_corruption()`/`save_repair()`** (new, `admin/core/
     frontmatter.py`) — a narrow one-off pass, deliberately *not* going through the normal
     `render()`/`_unchanged()` update path, since `_unchanged()` treats `None` and `""` as equal by
     design (see M0 finding 3) and would silently no-op a `null`→`""` edit forever. 6 new tests
     (`admin/tests/test_frontmatter_repair.py`). Applied to the real corpus: **41 files changed**,
     diff touches nothing but the `author:` line and tag-block indentation on those files, and the
     front-matter round-trip gate stayed **827/827**. Verified zero `: null`/`: ~` scalars and zero
     unindented tag lines remain anywhere in `_worlds/`, `_articles/`, `_posts/` after the fix.
   - The original (now-corrected) M0 finding is preserved below for the historical record of what
     was actually checked and why it gave a false all-clear.

   ~~**`merge_tags.py` may have already mangled some files.**~~ — ~~RESOLVED: it hasn't. No file
   in the corpus is mangled.~~ *(Superseded by the correction above.)*
   *The plan's proposed detector was wrong and would have given a false all-clear.* Round-tripping
   preserves whatever bytes are on disk, so a file `merge_tags.py` had already rewritten would
   still round-trip perfectly — a failure to round-trip proves nothing about it either way. The
   actual test is whether a file *deviates from the corpus convention*, which was measured
   directly: all 208 files that have `filesize` still have it double-quoted, all 208
   `archivedate:` lines are still empty-with-trailing-space, and not one `archivedate: null`
   exists anywhere. **This check just didn't cover `author` or tag-block indentation, which is
   where the actual damage is.**

3. **`_articles/creatures.md` has malformed front matter** (found in M0) — a bare
   `Eden World Builder Wiki` line with no key, which is not valid YAML. The app tolerates it and
   flags it. Worth repairing by hand; it is the only file in the corpus like this.

4. **The 0-byte worldname marker file** in every asset dir looks accidental. Keep producing it
   for parity; propose removing it in a separate deliberate commit.

5. **`archivedate` is empty in all 208 files that have it.** The admin form will be the first
   thing to actually populate it, which means the first save on a short-form (560) file *inserts*
   the key. That's a legitimate one-line diff, not drift — but don't be surprised by it.

6. **Dismissed-dupe durability** — the committed `admin/dupe_dismissals.yaml` is what makes the
   gitignored SQLite cache safely disposable. Don't skip it.

7. **Repo size** (deferred by decision): no LFS, 1.1 GB of assets committed, `.git` at 2.1 GB,
   growing with every world. The app warns; it doesn't fix. Worth revisiting separately.

8. **The Ruby toolchain is broken locally** (system Ruby 2.6 vs. bundler version mismatch), so
   `bundle exec jekyll build` cannot run on this machine and verification item 5 could not be
   executed. Unrelated to this work — Pages builds remotely. Confirm on the next deploy.

9. ~~**"Doubly zipped" / "doubly compressed" worlds.**~~ **FIXED (2026-07-11).** Investigated
   using `~/eden-world-editor`'s Rust source as reference (`network.rs::download_world` — the
   Eden game server always delivers worlds gzip-compressed over HTTP, magic `1f 8b`, unrelated to
   its separate local "compressed save" format which is a real PK zip; `lib.rs::load_world`
   detects that by magic bytes on load). Empirically surveyed every stored zip in the archive by
   walking payload layers via magic bytes (not filename) — **there is no genuine double
   compression anywhere in the corpus**: zero gzip-of-gzip, zero zip-of-zip. What actually breaks
   is a 4th, previously undocumented packaging variant — see `CLAUDE.md`'s "Zip packaging
   variations" — where the stored `{id}.eden.zip` is a **bare gzip stream with no outer zip
   wrapper at all**. `extract_eden()`'s `if not zipfile.is_zipfile(...): return None` gate
   rejected this outright. Confirmed live: world `1584568651` (`assets/worldfiles/1584568651/`,
   "\*Video Game Museum") is the one case of this in the current 768-world archive (verified by
   running the *actual* `find_zip`/`extract_eden` production code, not just a heuristic scan,
   against every world).
   - **Fixed in both `admin/core/mapgen.py` and `generate_missing_maps.py`** (kept in sync, per
     this doc's reuse-map note) — a new `_bare_gzip_fallback()` catches the case: no Python-side
     decompression needed, since `World.ts` already detects gzip by magic bytes regardless of
     filename, so the fix just gets the bytes to the temp dir under a `.eden` name.
   - Also fixed a related cosmetic bug hit along the way while investigating: the "last resort,
     take the sole zip entry" fallback branch never renamed its output to `.eden`, and the
     existing rename logic (`.with_suffix("").with_suffix(".eden")`) broke on filenames with an
     embedded `.eden` substring that isn't the real extension (e.g. world `1770253120`'s zip entry
     is literally named `"...1770253120.eden retro oldterrain city ikea.zip"` — tags baked into
     the filename). Both now go through one `_eden_name_for()` helper.
   - **11 new tests** (`admin/tests/test_mapgen.py`), covering the bare-gzip case (both `.zip`-
     and `.eden`-named), the embedded-`.eden`-substring filename case, and the helper directly.
     **832/832 green.**
   - **Live-verified**: regenerated world `1584568651`'s map through the real job queue — it now
     extracts and renders (previously always returned `None`/failed). The regenerated `map.png`
     is *not* byte-identical to the one already committed, and that's the interesting part: the
     old file **visibly lacks a building** that the new render shows clearly — a museum structure,
     consistent with the world's actual name. Since `extract_eden` could never have succeeded for
     this world before this fix, the old `map.png` must have been produced some other way (by
     hand, or against different/incomplete bytes); the new one is the first map ever generated
     through this pipeline for this world, and it looks more complete, not less. The new
     `map.png` is committed alongside the code fix.
