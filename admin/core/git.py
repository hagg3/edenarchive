"""Read-only git. The app never runs add, commit, push, checkout, reset or clean.

The only command here that touches the network is fetch(), and it runs solely
when the archivist clicks the button.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .paths import REPO_ROOT

_TIMEOUT = 20


def _git(*args: str, timeout: int = _TIMEOUT) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)


@dataclass
class Change:
    status: str
    path: str
    group: str

    @property
    def label(self) -> str:
        return {
            "??": "new",
            " M": "modified",
            "M ": "modified (staged)",
            "MM": "modified",
            " D": "deleted",
            "D ": "deleted (staged)",
            "A ": "added (staged)",
            "R ": "renamed",
        }.get(self.status, self.status.strip() or "changed")


def _group_for(path: str) -> str:
    for prefix, name in (
        ("_worlds/", "worlds"),
        ("_articles/", "articles"),
        ("_posts/", "posts"),
        ("assets/worldfiles/", "assets"),
        ("admin/", "admin"),
    ):
        if path.startswith(prefix):
            return name
    return "other"


def status() -> list[Change]:
    code, out, _ = _git("status", "--porcelain=v1", "-z")
    if code != 0:
        return []
    changes: list[Change] = []
    fields = out.split("\0")
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        st, path = entry[:2], entry[3:]
        if st[0] == "R":
            i += 1  # rename entries carry a second NUL-separated path
        changes.append(Change(status=st, path=path, group=_group_for(path)))
    return changes


def grouped_status() -> dict[str, list[Change]]:
    groups: dict[str, list[Change]] = {}
    for c in status():
        groups.setdefault(c.group, []).append(c)
    return groups


def is_dirty() -> bool:
    return bool(status())


def file_diff(path: str) -> str:
    code, out, err = _git("diff", "--no-color", "--", path)
    if code != 0:
        return err
    if not out.strip():
        # Untracked files have no diff; show them as added.
        code, out, _ = _git(
            "diff", "--no-color", "--no-index", "/dev/null", path
        )
    return out


def diffstat() -> str:
    _, out, _ = _git("diff", "--stat", "--no-color")
    return out


def ahead_behind(upstream: str = "origin/main") -> tuple[int, int] | None:
    """(ahead, behind) against the *cached* remote ref — no implicit network."""
    code, _, _ = _git("rev-parse", "--verify", "--quiet", upstream)
    if code != 0:
        return None
    code, out, _ = _git("rev-list", "--left-right", "--count", f"HEAD...{upstream}")
    if code != 0:
        return None
    try:
        ahead, behind = out.split()
        return int(ahead), int(behind)
    except ValueError:
        return None


def fetch() -> tuple[bool, str]:
    """The one network operation, and only on an explicit click."""
    code, out, err = _git("fetch", "--quiet", "origin", timeout=60)
    return code == 0, (err or out).strip() or "Fetched origin."


def current_branch() -> str:
    _, out, _ = _git("rev-parse", "--abbrev-ref", "HEAD")
    return out.strip() or "?"


def commit_hint(changes: list[Change]) -> str:
    """A copy-paste-ready command. The archivist runs it; the app never does."""
    if not changes:
        return ""
    groups = sorted({c.group for c in changes})
    dirs = sorted({c.path.split("/")[0] for c in changes})
    msg = f"Update {', '.join(groups)}"
    return f"git add {' '.join(dirs)} && git commit -m {msg!r}"
