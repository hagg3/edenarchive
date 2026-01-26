import zipfile
import re
from pathlib import Path

WORLD_ID_RE = re.compile(r"(1\d{9,10})")  # Eden-style IDs

OLD_PREFIX_RE = re.compile(
    r"""
    ^
    (\d{2}\s+\d{2}\s+\d{2}\s+)?   # date
    (\(ND\)\s*)?
    (\(\*\)\s*|\*\s*)?
    """,
    re.VERBOSE,
)

def extract_world_id(zip_path: Path) -> str | None:
    try:
        with zipfile.ZipFile(zip_path) as z:
            for name in z.namelist():
                if name.lower().endswith(".eden"):
                    match = WORLD_ID_RE.search(name)
                    if match:
                        return match.group(1)
    except zipfile.BadZipFile:
        return None
    return None

def clean_name(filename: str) -> str:
    name = filename
    name = OLD_PREFIX_RE.sub("", name)
    name = re.sub(r"\.eden\.zip$|\.zip$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+", " ", name).strip()
    return name

def already_new_style(name: str) -> bool:
    return WORLD_ID_RE.search(name) is not None

def main(directory: str, dry_run: bool = True):
    base = Path(directory)

    renamed = []
    skipped = []

    for file in base.iterdir():
        if not file.name.lower().endswith((".zip", ".eden.zip")):
            continue

        if already_new_style(file.name):
            continue

        world_id = extract_world_id(file)
        if not world_id:
            skipped.append((file.name, "NO INTERNAL .eden ID"))
            continue

        clean = clean_name(file.name)

        if world_id not in clean:
            clean = f"{clean} {world_id}"

        new_name = f"{clean}.eden.zip"
        target = file.with_name(new_name)

        if target.exists():
            skipped.append((file.name, "TARGET EXISTS"))
            continue

        renamed.append((file.name, new_name))

        if not dry_run:
            file.rename(target)

    print("\n--- RENAME PREVIEW ---")
    for old, new in renamed:
        print(f"{old}  ->  {new}")

    print("\n--- SKIPPED ---")
    for name, reason in skipped:
        print(f"{name} ({reason})")

    print(f"\nTotal renamed: {len(renamed)}")
    print(f"Total skipped: {len(skipped)}")

if __name__ == "__main__":
    WORLD_DIR = "./"
    main(WORLD_DIR, dry_run=False)
