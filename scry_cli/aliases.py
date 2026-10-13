"""Offline card name alias resolution (flavor names, promo reskins, and reprints).

Maps promotional flavor names (e.g. 'Master Emerald Shrine' -> 'Command Tower',
'Godzilla, King of the Monsters' -> 'Zilortha, Strength Incarnate') and
interchangeable pairs to canonical Oracle card names.

Features:
- Bundled precompiled data in scry_cli/data/aliases.json
- User override support via ~/.hermes/scryfall/aliases.json
- Strictly offline, O(1) in-memory resolution (< 0.05 ms)
"""
from __future__ import annotations

import json
import os
from typing import Dict, Optional

# Bundled data path
_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_BUNDLED_ALIASES_PATH = os.path.join(_DATA_DIR, "aliases.json")

# User override path in ~/.hermes/scryfall/aliases.json
_USER_ALIASES_PATH = os.path.expanduser("~/.hermes/scryfall/aliases.json")

_ALIAS_CACHE: Optional[Dict[str, str]] = None


def normalize_alias_key(key: str) -> str:
    """Normalize apostrophes, quotes, and whitespace for robust matching."""
    if not key or not isinstance(key, str):
        return ""
    return (
        key.replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .strip()
        .lower()
    )


def get_alias_map() -> Dict[str, str]:
    """Return the merged alias dictionary (lowercase alias -> canonical card name)."""
    global _ALIAS_CACHE
    if _ALIAS_CACHE is not None:
        return _ALIAS_CACHE

    aliases: Dict[str, str] = {}

    # 1. Load bundled aliases
    if os.path.exists(_BUNDLED_ALIASES_PATH):
        try:
            with open(_BUNDLED_ALIASES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    for k, v in data.items():
                        if isinstance(k, str) and isinstance(v, str):
                            aliases[normalize_alias_key(k)] = v.strip()
        except Exception:
            pass

    # 2. Merge user overrides if present
    if os.path.exists(_USER_ALIASES_PATH):
        try:
            with open(_USER_ALIASES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    for k, v in data.items():
                        if isinstance(k, str) and isinstance(v, str):
                            aliases[normalize_alias_key(k)] = v.strip()
        except Exception:
            pass

    _ALIAS_CACHE = aliases
    return _ALIAS_CACHE


def resolve_alias(name: str) -> Optional[str]:
    """Resolve an alias or flavor name to its canonical Oracle card name.

    Returns the canonical name string if an alias is found, or None.
    """
    if not name or not isinstance(name, str):
        return None
    normalized = normalize_alias_key(name)
    m = get_alias_map()
    if normalized in m:
        return m[normalized]

    # Fallback: check if stripped of leading owner (e.g. "tidus's brotherhood sword" -> "brotherhood sword")
    if "'s " in normalized:
        suffix = normalized.split("'s ", 1)[1].strip()
        if suffix in m:
            return m[suffix]

    return None


def reload_aliases() -> None:
    """Clear in-memory cache to force reloading from disk."""
    global _ALIAS_CACHE
    _ALIAS_CACHE = None


def save_user_alias(alias: str, canonical: str) -> bool:
    """Save a newly discovered alias to user's override file (~/.hermes/scryfall/aliases.json)."""
    if not alias or not canonical:
        return False
    norm_alias = normalize_alias_key(alias)
    canonical = canonical.strip()

    # Update in-memory cache
    m = get_alias_map()
    m[norm_alias] = canonical

    # Persist to ~/.hermes/scryfall/aliases.json
    try:
        user_dir = os.path.dirname(_USER_ALIASES_PATH)
        os.makedirs(user_dir, exist_ok=True)
        user_data = {}
        if os.path.exists(_USER_ALIASES_PATH):
            try:
                with open(_USER_ALIASES_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        user_data = data
            except Exception:
                user_data = {}
        user_data[norm_alias] = canonical
        with open(_USER_ALIASES_PATH, "w", encoding="utf-8") as f:
            json.dump(user_data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        return True
    except Exception:
        return False


