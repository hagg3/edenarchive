import yaml
from pathlib import Path
from collections import defaultdict
from difflib import get_close_matches

WORLD_DIR = Path("_worlds")

def load_front_matter(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None

    try:
        _, fm, _ = text.split("---", 2)
        return yaml.safe_load(fm)
    except Exception as e:
        print(f"⚠️  Failed to parse front matter: {path.name} ({e})")
        return None

def normalize(tag):
    return tag.lower().strip()

all_tags = defaultdict(set)

for md in WORLD_DIR.glob("*.md"):
    fm = load_front_matter(md)
    if not fm:
        continue

    tags = fm.get("tags")

    # Skip missing or empty tags
    if not tags:
        continue

    # If tags is a single string, coerce to list
    if isinstance(tags, str):
        tags = [tags]

    # Skip invalid tag formats
    if not isinstance(tags, list):
        print(f"⚠️  Invalid tags format in {md.name}: {tags}")
        continue

    for tag in tags:
        if not isinstance(tag, str):
            continue
        all_tags[normalize(tag)].add(tag)

# Fuzzy matching
normalized = sorted(all_tags.keys())
suggestions = set()

for tag in normalized:
    matches = get_close_matches(tag, normalized, cutoff=0.85)
    group = tuple(sorted({tag, *matches}))
    if len(group) > 1:
        suggestions.add(group)

print("\nPOTENTIAL TAG MERGE GROUPS:\n")

for group in sorted(suggestions):
    originals = {orig for key in group for orig in all_tags[key]}
    print(f"{group}  → originals: {sorted(originals)}")
