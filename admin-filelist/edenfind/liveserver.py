"""Read-only Eden game-server client: recent/browse, search, featured list,
and preview thumbnails. Stdlib-only (`urllib`), matching this project's
no-pip constraint (see CLAUDE.md) — a port of the wire-protocol logic in
`edenarchive/admin/core/edenserver.py` (itself a port of
`~/eden-world-editor`'s `src-tauri/src/network.rs`), not a code reuse of it,
since that module depends on `requests` and lives in a different project.

**Server-load discipline (explicit requirement, carried over from the admin
port): exactly one HTTP request per exported call here.** No crawl, no
prefetch, no polling, no looping over these functions without a user action
behind each call. Paging/capping is the caller's job (`edenfind/server.py`),
kept out of this module so the protocol layer stays a single, auditable place
to check "does this hit the network more than once."
"""
from __future__ import annotations

import re
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import quote_plus

TIMEOUT = 15

_ID_RE = re.compile(r"^(\d{9,12})\.eden$")
_NAME_RE = re.compile(r"^(.*)\.name$")


class LiveServerError(RuntimeError):
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
        raise LiveServerError(f"unknown server: {name!r}") from None


@dataclass
class ServerWorld:
    ts: str
    name: str


def _get_text(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as e:
        raise LiveServerError(str(e)) from e


def parse_listing(text: str) -> list[ServerWorld]:
    """Plain-text alternating `<ts>.eden` / `<name>.name` lines. Scans for an
    `.eden` line immediately followed by its `.name` line rather than
    trusting a fixed stride-2 layout: one stray blank line in the response
    would otherwise desync every subsequent pair. Same approach as
    `edenarchive/admin/core/edenserver.py:parse_listing`."""
    lines = [ln.strip() for ln in text.splitlines()]
    results: list[ServerWorld] = []
    i = 0
    while i + 1 < len(lines):
        id_line, name_line = lines[i], lines[i + 1]
        if id_line.endswith(".eden") and name_line.endswith(".name"):
            results.append(ServerWorld(ts=id_line[: -len(".eden")], name=name_line[: -len(".name")]))
            i += 2
        else:
            i += 1
    return results


def browse(start: int, server: Server, sort: int = 2) -> list[ServerWorld]:
    """`GET {list_url}?start=&sort=`. No cursor — the caller passes
    `start = rows so far`; an empty page means done. `sort=2` is what the
    real desktop client sends. One request."""
    return parse_listing(_get_text(f"{server.list_url}?start={start}&sort={sort}"))


def search(query: str, server: Server) -> list[ServerWorld]:
    """`GET {list_url}?search=...`. Not paginated by the server — one
    request returns every match."""
    return parse_listing(_get_text(f"{server.list_url}?search={quote_plus(query)}"))


@dataclass
class FeaturedEntry:
    ts: str
    name: str
    rank: int


def fetch_featured(server: Server) -> list[FeaturedEntry]:
    """`GET {files_base}/popularlist.txt` — one request for the full,
    already-ranked featured list. Same alternating-line format and pairing
    logic as `edenfind/parse.py:iter_featured`, which parses this exact file
    offline from the `featured/*.txt` snapshots already in this repo."""
    text = _get_text(f"{server.files_base}/popularlist.txt")
    pending_ts: str | None = None
    rank = 0
    out: list[FeaturedEntry] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if pending_ts is None:
            m = _ID_RE.match(line)
            if m:
                pending_ts = m.group(1)
            continue
        m = _NAME_RE.match(line)
        if m:
            rank += 1
            name = unicodedata.normalize("NFC", m.group(1)).rstrip()
            out.append(FeaturedEntry(ts=pending_ts, name=name, rank=rank))
            pending_ts = None
        else:
            pending_ts = None
    return out


def preview_url(ts: str, server: Server) -> str:
    return f"{server.files_base}/{ts}.eden.png"


def fetch_preview_bytes(ts: str, server: Server) -> bytes | None:
    """One GET. Returns None on any request failure or non-PNG body — never
    raises, since a missing preview is an expected, common outcome (many
    worlds have none regardless of server)."""
    try:
        with urllib.request.urlopen(preview_url(ts, server), timeout=TIMEOUT) as resp:
            data = resp.read()
    except (urllib.error.URLError, TimeoutError):
        return None
    if not data.startswith(b"\x89PNG"):
        return None
    return data
