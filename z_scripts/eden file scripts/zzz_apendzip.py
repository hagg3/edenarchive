#!/usr/bin/env python3
from pathlib import Path

# Use the folder where this script is located
ROOT = Path(__file__).resolve().parent

def main():
    renamed = 0
    skipped = 0

    for subdir in sorted(p for p in ROOT.iterdir() if p.is_dir()):
        for f in subdir.iterdir():
            # Target .eden files that do not already end with .zip
            if f.is_file() and f.name.endswith(".eden") and not f.name.endswith(".eden.zip"):
                new_path = f.with_name(f.name + ".zip")
                if new_path.exists():
                    print(f"⚠ SKIP (target exists): {new_path}")
                    skipped += 1
                    continue
                f.rename(new_path)
                print(f"✔ RENAMED: {f.name} → {new_path.name}")
                renamed += 1
            else:
                skipped += 1

    print("\nDone.")
    print(f"Renamed: {renamed}")
    print(f"Skipped: {skipped}")

if __name__ == "__main__":
    main()
