from __future__ import annotations

import json
from datetime import datetime

from fastapi import Request
from fastapi.templating import Jinja2Templates

from ..core import paths

templates = Jinja2Templates(directory=str(paths.REPO_ROOT / "admin/app/templates"))


def human_bytes(n: int | None) -> str:
    if not n:
        return "—"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def issue_list(raw: str | None) -> list[str]:
    try:
        return json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []


def short_time(iso: str | None) -> str:
    if not iso:
        return "never"
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%H:%M:%S")
    except ValueError:
        return iso


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


templates.env.filters["human_bytes"] = human_bytes
templates.env.filters["issue_list"] = issue_list
templates.env.filters["short_time"] = short_time
