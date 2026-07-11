from __future__ import annotations

from fastapi import APIRouter, Request

from ...core import index, paths
from ...core import tags as tags_mod
from ...core import world as world_mod
from ..templating import is_htmx, templates

router = APIRouter()

TAG_MAP_PATH = paths.REPO_ROOT / "z_scripts" / "tag manage" / "tag_map.yaml"


def _tag_map() -> dict[str, str]:
    if not TAG_MAP_PATH.exists():
        return {}
    return tags_mod.load_tag_map(TAG_MAP_PATH)


def _ctx(request: Request, *, applied: list[str] | None = None) -> dict:
    conn = request.app.state.db
    worlds = world_mod.load_all()
    stats = tags_mod.tag_inventory(worlds)
    tag_map = _tag_map()
    untagged, _ = index.search(conn, issue="missing_tags", sort="name", limit=1000)
    return {
        "stats": stats,
        "thin": [s for s in stats if s.count <= 2],
        "groups": tags_mod.near_dupe_groups([s.tag for s in stats]),
        "tag_map": tag_map,
        "tag_map_path": str(TAG_MAP_PATH.relative_to(paths.REPO_ROOT)) if TAG_MAP_PATH.exists() else None,
        "preview": tags_mod.preview_bulk_retag(worlds, tag_map) if tag_map else [],
        "untagged": untagged,
        "applied": applied,
        "nav": "tags",
    }


@router.get("/tags")
async def tag_health(request: Request):
    return templates.TemplateResponse(request, "tags.html", _ctx(request))


@router.post("/tags/bulk")
async def bulk_retag(request: Request):
    """Apply z_scripts/tag manage/tag_map.yaml to every world whose tags it
    would change, writing through world.save (frontmatter.render) rather than
    yaml.dump — see core/tags.py. The dry-run diff is the GET /tags page
    itself (the "preview" section below); this route is the second step the
    archivist takes after reviewing it."""
    tag_map = _tag_map()
    changed: list[str] = []
    if tag_map:
        worlds = world_mod.load_all()
        changed = tags_mod.apply_bulk_retag(worlds, tag_map)
        if changed:
            index.scan(request.app.state.db, force=True)
    if is_htmx(request):
        return templates.TemplateResponse(
            request, "partials/retag_applied.html", {"changed": changed}
        )
    return templates.TemplateResponse(request, "tags.html", _ctx(request, applied=changed))
