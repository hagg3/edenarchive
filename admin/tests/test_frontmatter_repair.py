"""frontmatter.repair_corruption / save_repair: the one-off fix for the 24
world files a historical run of z_scripts/tag manage/merge_tags.py left with
a literal `author: null` and an unindented tags block (see ADMIN_APP_PLAN.md,
"Open items" #2). Narrower than the normal render()/save() update path on
purpose — see the module docstring in frontmatter.py for why _unchanged()
can't be reused here.
"""
from __future__ import annotations

from admin.core import frontmatter as fm

CORRUPTED = (
    "---\nlayout: page\nfilename: 1765395041.eden\nworldname: Barnim v28\n"
    "publishdate: 2025-12-10\nauthor: null\ntags:\n- impressive\n- large\n"
    "- city\n---\n## Barnim v28\n\nBody text.\n"
)


def _doc(tmp_path, text: str, name: str = "w.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return fm.parse(p), p


def test_repairs_null_author_and_tag_indent(tmp_path):
    doc, _ = _doc(tmp_path, CORRUPTED)
    repaired = fm.repair_corruption(doc)
    assert repaired is not None
    assert "author: \n" in repaired
    assert "author: null" not in repaired
    assert "\n  - impressive\n  - large\n  - city\n" in repaired
    assert "\n- impressive" not in repaired
    # nothing else in the file should move
    assert repaired.startswith("---\nlayout: page\nfilename: 1765395041.eden\n"
                                "worldname: Barnim v28\npublishdate: 2025-12-10\n")
    assert repaired.endswith("---\n## Barnim v28\n\nBody text.\n")


def test_repair_is_none_for_a_clean_file(tmp_path):
    clean = (
        "---\nlayout: page\nfilename: 123.eden\nworldname: Clean\n"
        "publishdate: 2025-01-01\narchivedate: \nfilesize: \"1.0 MB\"\nauthor: \n"
        "tags:\n  - city\n---\n## Clean\n\nBody.\n"
    )
    doc, _ = _doc(tmp_path, clean)
    assert fm.repair_corruption(doc) is None


def test_repair_leaves_a_real_empty_author_alone(tmp_path):
    """`author: ` (the corpus convention) is not `author: null` and must not
    be touched — only the literal YAML null token is corruption."""
    text = (
        "---\nlayout: page\nfilename: 123.eden\nworldname: X\n"
        "publishdate: 2025-01-01\nauthor: \ntags:\n  - city\n---\n## X\n\nBody.\n"
    )
    doc, _ = _doc(tmp_path, text)
    assert fm.repair_corruption(doc) is None


def test_repair_only_touches_unindented_lines_directly_under_tags(tmp_path):
    """A `- ` line doesn't get misfired on just because it's null-adjacent —
    only unindented entries in the tags block itself are re-indented."""
    text = (
        "---\nlayout: page\nfilename: 123.eden\nworldname: X\n"
        "publishdate: 2025-01-01\nauthor: null\ntags:\n  - already-indented\n"
        "- needs-indent\n---\n## X\n\nsome body text\n- not a tag, just a bullet\n"
    )
    doc, _ = _doc(tmp_path, text)
    repaired = fm.repair_corruption(doc)
    assert "  - already-indented\n  - needs-indent\n" in repaired
    # body content is passed through byte-for-byte, never touched
    assert "\nsome body text\n- not a tag, just a bullet\n" in repaired


def test_save_repair_writes_and_backs_up(tmp_path, monkeypatch):
    monkeypatch.setattr(fm.paths, "WRITABLE_ROOTS", (tmp_path,))
    monkeypatch.setattr(fm.paths, "RUNTIME_DIR", tmp_path / ".runtime")
    monkeypatch.setattr(fm.paths, "BACKUP_DIR", tmp_path / ".runtime" / "backups")
    doc, path = _doc(tmp_path, CORRUPTED)

    changed = fm.save_repair(path, doc)
    assert changed is True
    assert "author: null" not in path.read_text()
    backups = list((tmp_path / ".runtime" / "backups").glob("*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text() == CORRUPTED


def test_save_repair_is_noop_on_a_clean_file(tmp_path, monkeypatch):
    monkeypatch.setattr(fm.paths, "WRITABLE_ROOTS", (tmp_path,))
    monkeypatch.setattr(fm.paths, "RUNTIME_DIR", tmp_path / ".runtime")
    monkeypatch.setattr(fm.paths, "BACKUP_DIR", tmp_path / ".runtime" / "backups")
    clean = (
        "---\nlayout: page\nfilename: 123.eden\nworldname: Clean\n"
        "publishdate: 2025-01-01\narchivedate: \nfilesize: \"1.0 MB\"\nauthor: \n"
        "tags:\n  - city\n---\n## Clean\n\nBody.\n"
    )
    doc, path = _doc(tmp_path, clean)
    before = path.read_bytes()
    assert fm.save_repair(path, doc) is False
    assert path.read_bytes() == before
