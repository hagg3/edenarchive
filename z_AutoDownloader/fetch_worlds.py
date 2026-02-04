import requests
import re
import time
import sys
from pathlib import Path
import urllib3

# --- Setup ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = Path(__file__).resolve().parent
WORLDS_FILE = BASE_DIR / "worlds.txt"
OUT_DIR = BASE_DIR / "downloads"

OUT_DIR.mkdir(exist_ok=True)

# --- Eden endpoints ---
SEARCH_URL = "http://app2.edengame.net/list2.php"
DOWNLOAD_BASE = "https://files2.edengame.net"

# --- Helpers ---
def download_eden_file(file_id: str, world_name: str | None = None):
    eden_name = f"{file_id}.eden"
    url = f"{DOWNLOAD_BASE}/{eden_name}"

    try:
        data = requests.get(url, timeout=60).content
    except Exception as e:
        print(f"[ERROR] Download failed for {eden_name}: {e}")
        return

    if world_name:
        # CORRECT ORDER: NAME first, ID last
        out_name = f"{world_name} {file_id}.eden.zip"
    else:
        out_name = f"{file_id}.eden.zip"

    out_file = OUT_DIR / out_name
    out_file.write_bytes(data)
    print(f"[OK] downloaded {out_name}")

# --- Mode 1: name-based search ---
def fetch_latest_world_by_name(world_name: str):
    r = requests.get(
        SEARCH_URL,
        params={"search": world_name},
        timeout=15,
        verify=False
    )
    r.raise_for_status()

    matches = re.findall(r"(\d+\.eden)", r.text)
    if not matches:
        print(f"[MISS] {world_name} — no results found")
        return

    latest_id = matches[0].replace(".eden", "")
    print(f"[OK] {world_name} -> {latest_id}")
    download_eden_file(latest_id, world_name)

# --- Mode 2: ID + name pairs ---
def fetch_worlds_by_id_pairs(lines: list[str]):
    if len(lines) % 2 != 0:
        print("[ERROR] worlds.txt must contain ID / name pairs when using --ids")
        sys.exit(1)

    it = iter(lines)
    for file_id, raw_name in zip(it, it):
        if not file_id.isdigit():
            print(f"[SKIP] invalid ID: {file_id}")
            continue

        world_name = raw_name.removesuffix(".name")
        print(f"[OK] ID-only {file_id} -> {world_name}")
        download_eden_file(file_id, world_name)
        time.sleep(1)

# --- Main ---
if __name__ == "__main__":
    if not WORLDS_FILE.exists():
        print(f"[ERROR] worlds.txt not found at {WORLDS_FILE}")
        sys.exit(1)

    use_id_mode = "--ids" in sys.argv

    with open(WORLDS_FILE) as f:
        lines = [line.strip() for line in f if line.strip()]

    if use_id_mode:
        fetch_worlds_by_id_pairs(lines)
    else:
        for name in lines:
            fetch_latest_world_by_name(name)
            time.sleep(1)
