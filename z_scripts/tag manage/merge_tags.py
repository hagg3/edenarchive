import yaml
from pathlib import Path

WORLD_DIR = Path("_worlds")
TAG_MAP = yaml.safe_load(Path("tag_map.yaml").read_text())

def load_file(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None, None
    try:
        _, fm_text, body = text.split("---", 2)
        fm = yaml.safe_load(fm_text)
        return fm, body
    except Exception as e:
        print(f"⚠️  Failed to parse front matter in {path.name}: {e}")
        return None, None

def save_file(path, fm, body):
    text = "---\n"
    text += yaml.safe_dump(fm, sort_keys=False)
    text += "---\n"
    text += body.lstrip("\n")
    path.write_text(text, encoding="utf-8")

for md in WORLD_DIR.glob("*.md"):
    fm, body = load_file(md)
    if not fm or "tags" not in fm:
        continue  # skip files without tags

    original = fm.get("tags")

    # Skip if tags is None or empty
    if not original:
        continue

    # Coerce string → list
    if isinstance(original, str):
        original = [original]

    # Skip invalid formats
    if not isinstance(original, list):
        print(f"⚠️  Invalid tags in {md.name}: {original}")
        continue

    updated = []
    for tag in original:
        if not isinstance(tag, str):
            continue
        key = tag.lower()
        updated.append(TAG_MAP.get(key, tag))

    # Remove duplicates while preserving order
    fm["tags"] = list(dict.fromkeys(updated))

    if fm["tags"] != original:
        save_file(md, fm, body)
        print(f"Updated: {md.name}")
