import re
from pathlib import Path

WORLD_ID_RE = re.compile(r"(1\d{9,10})")

OLD_PREFIX_RE = re.compile(
    r"""
    ^
    (\d{2}\s+\d{2}\s+\d{2}\s+)?   # date
    (\(ND\)\s*)?
    (\(\*\)\s*|\*\s*)?
    """,
    re.VERBOSE,
)

MID_MARKER_RE = re.compile(r"\s*(\(ND\)|\(\*\))\s*")

def clean_name(filename: str) -> str:
    name = filename

    # strip extension
    name = re.sub(r"\.eden\.zip$|\.zip$", "", name, flags=re.IGNORECASE)

    # remove leading junk
    name = OLD_PREFIX_RE.sub("", name)

    # remove mid-string markers
    name = MID_MARKER_RE.sub(" ", name)

    # normalize spaces
    name = re.sub(r"\s+", " ", name).strip()

    return name

def main(directory: str, dry_run: bool = True):
    base = Path(directory)

    renamed = []
    skipped = []

    for file in base.iterdir():
        if not file.name.lower().endswith((".zip", ".eden.zip")):
            continue

        name = file.name
        match = WORLD_ID_RE.search(name)

        if not match:
            skipped.append((name, "NO WORLD ID IN NAME"))
            continue

        cleaned = clean_name(name)
        new_name = f"{cleaned}.eden.zip"

        if new_name == name:
            continue

        target = file.with_name(new_name)
        if target.exists():
            skipped.append((name, "TARGET EXISTS"))
            continue

        renamed.append((name, new_name))

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
    main("./", dry_run=False)
