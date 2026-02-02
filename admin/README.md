# Eden Admin CLI

This directory contains a lightweight, single-entry CLI for project administration. It **wraps existing scripts** without modifying them and provides a consistent workflow for download, import, tag management, and validation.

## Quick Start

```bash
python3 admin/edenadmin.py --help
```

## Commands

```bash
# Download worlds listed in z_AutoDownloader/worlds.txt
python3 admin/edenadmin.py download

# Download using a custom list file (copied into z_AutoDownloader/worlds.txt)
python3 admin/edenadmin.py download --list /path/to/worlds.txt

# Import one or more files (delegates to z_add_world.py)
python3 admin/edenadmin.py import --eden /path/to/file1.eden.zip /path/to/file2.eden.zip

# Import all files in a folder (delegates to z_add_world.py)
python3 admin/edenadmin.py import --folder /path/to/folder

# Analyze tag similarity (delegates to z_scripts/tag manage/analyze_tags.py)
python3 admin/edenadmin.py tags analyze

# Merge tags using tag_map.yaml (delegates to z_scripts/tag manage/merge_tags.py)
python3 admin/edenadmin.py tags merge

# Validate repository consistency and emit a basic report
python3 admin/edenadmin.py validate

# Validate and write a JSON report to a file
python3 admin/edenadmin.py validate --out admin/reports/validate.json
```

## Notes

- The CLI **does not edit or remove** any existing admin scripts.
- It calls those scripts in-place to preserve their behavior.
- Validation is read-only and reports missing assets, invalid front matter, and common consistency issues.
