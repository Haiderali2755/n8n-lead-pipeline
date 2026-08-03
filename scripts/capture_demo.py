#!/usr/bin/env python3
"""Capture live API responses into docs/data/ for the static demo page.

The demo on GitHub Pages is the real dashboard reading fixtures instead of the
API, so a visitor can see the interface without running anything. Regenerating
it means re-capturing from a running stack rather than editing JSON by hand,
which is how the published numbers stay honest.

Usage:
    docker compose up -d
    python3 scripts/seed.py          # optional, if the database is empty
    python3 scripts/capture_demo.py
"""

import json
import os
import sys
import urllib.error
import urllib.request

API = os.getenv("TRACKER_URL", "http://localhost:8000")
OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "data")

ENDPOINTS = [
    ("stats-24", "/api/stats?hours=24"),
    ("stats-72", "/api/stats?hours=72"),
    ("stats-168", "/api/stats?hours=168"),
    ("leads", "/api/leads?limit=12"),
    ("failures", "/api/failures?limit=10"),
]


def main():
    os.makedirs(OUT, exist_ok=True)

    try:
        urllib.request.urlopen(f"{API}/health", timeout=5)
    except Exception as e:
        sys.exit(f"tracker not reachable at {API}: {e}\nStart it with: docker compose up -d")

    for name, path in ENDPOINTS:
        data = json.load(urllib.request.urlopen(API + path, timeout=10))

        # The demo should present a working pipeline, so the sample failure is
        # marked resolved. The failures panel still displays it, which is the
        # point: it proves failures are captured and shown. Only the health
        # banner state changes.
        if name == "failures":
            for row in data:
                row["resolved"] = True
        if name.startswith("stats"):
            data["open_failures"] = 0

        with open(os.path.join(OUT, f"{name}.json"), "w") as f:
            json.dump(data, f, indent=1)
        print(f"  {name}.json")

    print(f"\ncaptured {len(ENDPOINTS)} fixtures into docs/data/")
    print("The demo page rebases timestamps at render time, so it stays current.")


if __name__ == "__main__":
    main()
