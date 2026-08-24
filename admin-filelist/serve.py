#!/usr/bin/env python3
"""python3 serve.py [port]  ->  http://127.0.0.1:8777 (default port)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from edenfind.server import main  # noqa: E402

if __name__ == "__main__":
    main()
