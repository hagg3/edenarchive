import requests
import re
import time
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

# --- Functions ---
def fetch_latest_world(world_name):
    # Send search request
    r = requests.get(
        SEARCH_URL,
        params={"search": world_name},
        timeout=15,
        verify=False
    )
    r.raise_for_status()

    # Parse alternating FILENAMEID.eden / WorldName.name format
    matches = re.findall(r"(\d+\.eden)", r.text)
    if not matches:
        print(f"[MISS] {world_name} — no results found")
        return

    latest = matches[0]  # Topmost = newest
    url = f"{DOWNLOAD_BASE}/{latest}"

    print(f"[OK] {world_name} -> {latest}")

    # Download world file
    try:
        data = requests.get(url, timeout=60).content
    except Exception as e:
        print(f"[ERROR] Download failed for {latest}: {e}")
        return

    # Save to downloads directory
    # Example: "Manchon 1769365605.eden.zip"
    out_file = OUT_DIR / f"{world_name} {latest}.zip"
    out_file.write_bytes(data)

# --- Main ---
if __name__ == "__main__":
    if not WORLDS_FILE.exists():
        print(f"[ERROR] worlds.txt not found at {WORLDS_FILE}")
        exit(1)

    with open(WORLDS_FILE) as f:
        worlds = [line.strip() for line in f if line.strip()]

    for w in worlds:
        fetch_latest_world(w)
        time.sleep(1)  # polite rate limit
