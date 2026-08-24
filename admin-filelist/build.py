#!/usr/bin/env python3
"""python3 build.py [file_list2.txt] [worlds.db]

Builds worlds.db from the upload log + featured/ snapshots. Preserves any
existing triage (star/reject/note) state and any live-saved (worlds saved
from live server browsing) rows across the rebuild.
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from edenfind import index  # noqa: E402


def main() -> None:
    root = Path(__file__).resolve().parent
    filelist = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "file_list2.txt"
    db_path = Path(sys.argv[2]) if len(sys.argv) > 2 else root / "worlds.db"
    featured_dir = root / "featured"

    if not filelist.exists():
        sys.exit(f"error: {filelist} not found")
    if not featured_dir.exists():
        sys.exit(f"error: {featured_dir} not found")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_db = Path(tmp) / "worlds.db"
        index.build(str(filelist), str(featured_dir), str(tmp_db))
        restored = index.restore_triage(str(db_path), str(tmp_db))
        if restored:
            print(f"Restored {restored} triage record(s) from previous build.")
        restored_live = index.restore_live_saved(str(db_path), str(tmp_db))
        if restored_live:
            print(f"Restored {restored_live} live-saved record(s) from previous build.")
        shutil.move(str(tmp_db), str(db_path))

    print(f"Wrote {db_path}")


if __name__ == "__main__":
    main()
