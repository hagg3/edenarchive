import requests
import urllib3

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

UPLOAD_URL = "https://eden.anmon.org/uploadworld"
IDS_FILE = "idlist.txt"

with open(IDS_FILE, "r") as f:
    world_ids = [line.strip() for line in f if line.strip()]

for wid in world_ids:
    data = {
        "worldName": wid
    }

    files = {
        "file": ("", b"")
    }

    try:
        r = requests.post(
            UPLOAD_URL,
            data=data,
            files=files,
            verify=False,     # ← THIS IS REQUIRED
            timeout=20
        )

        print(wid, "→", r.status_code, r.text)

    except Exception as e:
        print(wid, "→ ERROR:", e)
