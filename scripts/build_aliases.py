#!/usr/bin/env python3
"""Build/update scry_cli/data/aliases.json from Scryfall API or local card dump.

Queries Scryfall API for promotional cards with `flavor_name` or Universes Within pairs,
merges with curated aliases, and writes a compact sorted JSON file.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
DATA_FILE = os.path.join(REPO_ROOT, "scry_cli", "data", "aliases.json")

SCRYFALL_API = "https://api.scryfall.com"
USER_AGENT = "scry-terminal/1.0"


def fetch_scryfall_paged(query: str) -> list[dict]:
    """Fetch all cards matching a query via Scryfall Search API with pagination."""
    cards = []
    url = f"{SCRYFALL_API}/cards/search?q={urllib.parse.quote(query)}"
    page = 1

    while url:
        print(f"Fetching page {page} for query '{query}'...")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                cards.extend(data.get("data", []))
                if data.get("has_more") and data.get("next_page"):
                    url = data["next_page"]
                    page += 1
                    time.sleep(0.1)  # Scryfall rate limit etiquette (100ms)
                else:
                    url = None
        except Exception as e:
            print(f"Error fetching {url}: {e}", file=sys.stderr)
            break

    return cards


def main():
    existing = {}
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            try:
                existing = json.load(f)
            except Exception:
                existing = {}

    print(f"Loaded {len(existing)} existing aliases.")

    # 1. Fetch cards with flavor_name from Scryfall
    try:
        flavor_cards = fetch_scryfall_paged("has:flavor_name")
        print(f"Found {len(flavor_cards)} cards with flavor_name.")
        for c in flavor_cards:
            fname = c.get("flavor_name")
            cname = c.get("name")
            if fname and cname:
                existing[fname.strip().lower()] = cname.strip()
    except Exception as e:
        print(f"Skipping online flavor_name fetch: {e}")

    # Write sorted JSON
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(existing.items())), f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"✓ Saved {len(existing)} aliases to {DATA_FILE}")


if __name__ == "__main__":
    main()
