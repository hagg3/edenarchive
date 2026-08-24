"""Line grammars for the two source formats this tool reads.

file_list2.txt is written one line at a time by the legacy upload servlet
(UploadMap2.java:205-213) and spans three eras in one format:

    1327810665.eden DANIELAND                                     # pre-logging fragment, no origin
    !D61AC753-72C8-45CD-8A87-26E25BF0C922 1423718682.eden test     # UUID era, Feb 2015
    !69.113.102.74 1786425051.eden Chainsaw Hotel' s1ep6 BzX       # IPv4 era, everything since
    !(null) 1424179318.eden HHoffun2 V001                          # pre-iOS6 placeholder, 1 row

featured/*.txt is Eden's own popularlist.txt wire format: alternating lines,
id then name+".name" suffix that clients strip on receipt (SharedList.mm:275-276,
network.rs:53). We scan for the pairing rather than stride-by-2 to survive stray
blank lines, matching what the real clients do.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterator, Optional

LINE_RE = re.compile(
    r"^\s*(?:!(?P<origin>\S+)\s+)?(?P<id>\d{9,12})\.eden(?: (?P<name>.*))?$"
)

IPV4_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
UUID_RE = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)


def classify_origin_kind(origin: Optional[str]) -> str:
    """ipv4 / uuid / null / none — none means no '!'-prefix at all (the 423
    pre-logging fragment rows at the top of the file)."""
    if origin is None:
        return "none"
    if origin == "(null)":
        return "null"
    if IPV4_RE.match(origin):
        return "ipv4"
    if UUID_RE.match(origin):
        return "uuid"
    return "unknown"


@dataclass
class ParsedRow:
    line_no: int
    ts: int
    name: str
    origin: Optional[str]
    origin_kind: str


def _clean_name(raw: Optional[str]) -> str:
    if raw is None:
        return ""
    name = unicodedata.normalize("NFC", raw)
    # Leading/trailing whitespace on names is very common in the source file.
    return name.strip()


def iter_filelist(path: str) -> Iterator[ParsedRow | tuple[int, str]]:
    """Yields ParsedRow for every parseable line, or (line_no, raw) for the
    handful that don't match the grammar — callers route those to `rejects`."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.rstrip("\n").rstrip("\r")
            m = LINE_RE.match(line)
            if not m:
                if line.strip() == "":
                    continue
                yield (line_no, raw_line)
                continue
            origin = m.group("origin")
            ts = int(m.group("id"))
            name = _clean_name(m.group("name"))
            yield ParsedRow(
                line_no=line_no,
                ts=ts,
                name=name,
                origin=origin,
                origin_kind=classify_origin_kind(origin),
            )


@dataclass
class FeaturedRow:
    ts: int
    name: str
    snapshot_date: str
    rank: int


_ID_RE = re.compile(r"^(\d{9,12})\.eden$")
_NAME_RE = re.compile(r"^(.*)\.name$")


def iter_featured(path: str, snapshot_date: str) -> Iterator[FeaturedRow]:
    """Scans for a '<id>.eden' line followed (not necessarily immediately) by
    the next non-blank line, which must be '<name>.name'. Matches the pairing
    logic in network.rs:53 and SharedList.mm:275, which survive stray blanks
    rather than assuming strict alternation."""
    pending_ts: Optional[int] = None
    rank = 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            if pending_ts is None:
                m = _ID_RE.match(line)
                if m:
                    pending_ts = int(m.group(1))
                continue
            m = _NAME_RE.match(line)
            if m:
                rank += 1
                name = unicodedata.normalize("NFC", m.group(1)).rstrip()
                yield FeaturedRow(
                    ts=pending_ts, name=name, snapshot_date=snapshot_date, rank=rank
                )
                pending_ts = None
            else:
                # Not the expected pairing; try to resync on this line as a
                # fresh id, otherwise drop the orphaned id and keep scanning.
                m2 = _ID_RE.match(line)
                pending_ts = int(m2.group(1)) if m2 else None
