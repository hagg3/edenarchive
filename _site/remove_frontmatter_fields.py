import os
import re

WORLDS_DIR = "_worlds"
FIELDS_TO_REMOVE = {"archivedate", "filesize"}

frontmatter_pattern = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n",
    re.DOTALL
)

def clean_frontmatter(frontmatter: str) -> str:
    cleaned_lines = []
    for line in frontmatter.splitlines():
        key = line.split(":", 1)[0].strip()
        if key not in FIELDS_TO_REMOVE:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)

for filename in os.listdir(WORLDS_DIR):
    if not filename.endswith(".md"):
        continue

    path = os.path.join(WORLDS_DIR, filename)

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    match = frontmatter_pattern.match(content)
    if not match:
        continue  # no valid frontmatter

    original_frontmatter = match.group(1)
    cleaned_frontmatter = clean_frontmatter(original_frontmatter)

    if cleaned_frontmatter == original_frontmatter:
        continue  # nothing to change

    new_content = (
        "---\n"
        + cleaned_frontmatter
        + "\n---\n"
        + content[match.end():]
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"Updated: {filename}")
