"""Read-only Eden game-server client: search, browse, thumbnail fetch, and a
streaming gzip-safe world download.

Port of `~/eden-world-editor` (VuencEdit)'s `src-tauri/src/network.rs`,
reimplemented in Python rather than shelled out to — the wire protocol is
just two GET endpoints and a line-pair parser. HTTP only: TLS reportedly
fails against these hosts.

**Server-load discipline (explicit requirement): exactly one HTTP request
per user action.** No crawl, no prefetch, no background listing sync, no
polling. Never call `browse`/`search` in a loop without a user action behind
each call.
"""
from __future__ import annotations

import datetime
import gzip
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote_plus

TIMEOUT = 15
DOWNLOAD_CONNECT_TIMEOUT = 15
DOWNLOAD_READ_TIMEOUT = 60

# Anything past this can't be map-rendered anyway (mapgen.TOO_LARGE_BYTES is
# 1.9 GiB) — reuse upload_api.MAX_UPLOAD_BYTES rather than the editor's own
# 12 GiB ceiling, which was sized for a Rust app that doesn't render maps.
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024


class EdenServerError(RuntimeError):
    pass


class DownloadTooLarge(EdenServerError):
    pass


@dataclass(frozen=True)
class Server:
    name: str
    list_url: str
    files_base: str


SERVERS: dict[str, Server] = {
    "current": Server("current", "http://app2.edengame.net/list2.php", "http://files2.edengame.net"),
    "legacy": Server("legacy", "http://app.edengame.net/list2.php", "http://files.edengame.net"),
}


def get_server(name: str) -> Server:
    try:
        return SERVERS[name]
    except KeyError:
        raise EdenServerError(f"unknown server: {name!r}") from None


@dataclass
class ServerWorld:
    id: str
    name: str
    timestamp: int


def parse_listing(text: str) -> list[ServerWorld]:
    """Plain-text alternating `<id>.eden` / `<name>.name` lines — no JSON.
    Scans for a `.eden` line immediately followed by its `.name` line rather
    than trusting a fixed stride-2 layout: one stray blank line in the
    response would otherwise desync every subsequent pair."""
    lines = [ln.strip() for ln in text.splitlines()]
    results: list[ServerWorld] = []
    i = 0
    while i + 1 < len(lines):
        id_line, name_line = lines[i], lines[i + 1]
        if id_line.endswith(".eden") and name_line.endswith(".name"):
            world_id = id_line[: -len(".eden")]
            name = name_line[: -len(".name")]
            try:
                timestamp = int(world_id)
            except ValueError:
                timestamp = 0
            results.append(ServerWorld(id=world_id, name=name, timestamp=timestamp))
            i += 2
        else:
            i += 1
    return results


def search(query: str, server: Server) -> list[ServerWorld]:
    """`GET {list_url}?search=...`. Not paginated by the server."""
    import requests

    url = f"{server.list_url}?search={quote_plus(query)}"
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    return parse_listing(resp.text)


def browse(start: int, server: Server, sort: int = 2) -> list[ServerWorld]:
    """`GET {list_url}?start=&sort=`. No cursor — the caller passes
    `start = rows so far`; an empty page means done. `sort=2` is what the
    real desktop client sends."""
    import requests

    url = f"{server.list_url}?start={start}&sort={sort}"
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    return parse_listing(resp.text)


def preview_url(world_id: str, server: Server) -> str:
    return f"{server.files_base}/{world_id}.eden.png"


def fetch_preview(world_id: str, server: Server) -> bytes | None:
    """One GET. Returns None on any request failure or non-PNG body — never
    raises, since a missing preview is an expected, common outcome."""
    import requests

    try:
        resp = requests.get(preview_url(world_id, server), timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException:
        return None
    if not resp.content.startswith(b"\x89PNG"):
        return None
    return resp.content


def fetch_preview_any(world_id: str) -> tuple[bytes | None, str | None]:
    """Tries current, then legacy. Returns (bytes, server_name) or (None, None)."""
    for name in ("current", "legacy"):
        data = fetch_preview(world_id, SERVERS[name])
        if data:
            return data, name
    return None, None


def _copy_capped(src, dst, max_bytes: int) -> None:
    """Streams src->dst, raising DownloadTooLarge the moment more than
    max_bytes would be written — the gzip-bomb guard. Port of network.rs's
    `copy_capped`."""
    written = 0
    while True:
        chunk = src.read(65536)
        if not chunk:
            return
        written += len(chunk)
        if written > max_bytes:
            raise DownloadTooLarge(
                f"decompressed world exceeds the {max_bytes} byte safety limit"
            )
        dst.write(chunk)


def download(
    world_id: str,
    server: Server,
    dest: Path,
    *,
    progress: Callable[[int, int | None], None] | None = None,
) -> None:
    """Streams the world file to `dest`, decompressing if the server sent it
    gzip-compressed (it always does — the game server delivers worlds
    gzip-over-HTTP). Atomic: writes to `{dest}.download.tmp` (and, if
    decompressing, `{dest}.tmp`), then renames onto `dest`. Cleans up its
    temp files on any failure, including cancellation.

    `progress`, if given, is called as `progress(downloaded_bytes, total_or_None)`.
    """
    import requests

    url = f"{server.files_base}/{world_id}.eden"
    raw_tmp = dest.with_name(dest.name + ".download.tmp")
    decompressed_tmp = dest.with_name(dest.name + ".tmp")
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        with requests.get(
            url, stream=True,
            timeout=(DOWNLOAD_CONNECT_TIMEOUT, DOWNLOAD_READ_TIMEOUT),
        ) as resp:
            resp.raise_for_status()
            total_header = resp.headers.get("content-length")
            total = int(total_header) if total_header is not None else None
            if total is not None and total > MAX_DOWNLOAD_BYTES:
                raise DownloadTooLarge(
                    f"server-reported size exceeds the {MAX_DOWNLOAD_BYTES} byte limit"
                )

            downloaded = 0
            head = b""
            with open(raw_tmp, "wb") as f:
                for chunk in resp.iter_content(65536):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > MAX_DOWNLOAD_BYTES:
                        raise DownloadTooLarge(
                            f"downloaded response exceeds the {MAX_DOWNLOAD_BYTES} byte limit"
                        )
                    if len(head) < 2:
                        head += chunk[: 2 - len(head)]
                    f.write(chunk)
                    if progress:
                        progress(downloaded, total)

            if head[:2] == b"\x1f\x8b":
                try:
                    with gzip.open(raw_tmp, "rb") as gz, open(decompressed_tmp, "wb") as out:
                        _copy_capped(gz, out, MAX_DOWNLOAD_BYTES)
                finally:
                    raw_tmp.unlink(missing_ok=True)
                decompressed_tmp.replace(dest)
            else:
                raw_tmp.replace(dest)
    except BaseException:
        raw_tmp.unlink(missing_ok=True)
        decompressed_tmp.unlink(missing_ok=True)
        raise


# ── junk/quality heuristic ───────────────────────────────────────────────────

_NEG_TERMS = ("test", "asdf", "qwer", "xxxx", "lol")
_STRUCTURE_TERMS = (
    "city", "station", "base", "facility", "complex", "zone", "sector", "district",
    "hub", "port", "terminal", "outpost", "bunker", "vault", "lab", "laboratory", "factory",
    "plant", "tower", "bridge", "arena", "stadium", "castle", "fortress", "palace", "temple",
    "dungeon", "citadel", "stronghold", "colony", "ruins", "museum", "stadt", "basis",
    "komplex", "hafen", "fabrik", "turm", "ville", "secteur", "ciudad", "complejo",
    "laboratorio",
)
_GAMEPLAY_TERMS = (
    "adventure", "quest", "puzzle", "parkour", "story", "campaign", "mission", "maze",
    "challenge", "rpg", "survival", "course", "race", "trial", "gauntlet", "battle", "boss",
    "raid",
)
_VERSIONISH_TERMS = ("alpha", "beta", "wip", "redux", "remake", "final", "rev")


def score_world(name: str, timestamp: int) -> int:
    """Junk/quality heuristic — line-by-line port of `scoreWorld`
    (WorldBrowserModal.tsx:37-61). Kept labelled experimental in the UI, same
    as the editor: it's a nudge for sorting, not a filter to trust blindly."""
    lname = name.lower()
    if "'red'" in lname:
        return -10

    score = 0
    if any(w in lname for w in _NEG_TERMS):
        score -= 3
    score += min(sum(1 for w in _STRUCTURE_TERMS if w in lname), 3)
    score += min(sum(1 for w in _GAMEPLAY_TERMS if w in lname), 3)
    if re.search(r"\bv\d+\b", lname) or any(w in lname for w in _VERSIONISH_TERMS):
        score += 1
    words = [w for w in re.split(r"\s+", lname) if w]
    if len(words) >= 3:
        score += 1
    if re.search(r"[A-Z]", name):
        score += 1
    if re.match(r"^[a-z0-9_]{6,}$", lname.replace(" ", "")):
        score -= 2

    try:
        year = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc).year
    except (ValueError, OSError, OverflowError):
        year = None
    if year is not None:
        if year <= 2014:
            score += 1
        if year <= 2012:
            score += 1

    if re.search(r"\bby\s+[a-z0-9]+$", name, re.IGNORECASE):
        score += 1
    return score
