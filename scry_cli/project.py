"""Machine-readable projections of a card + emitters.

slim_card() is the single canonical projection: the SQLite index stores its
output verbatim, so every output layer (pretty/json/jsonl/csv/tsv) sees what
the JSONL path gives it. text_card() reuses it for the `oracle` shape.
"""
import json
import sys

from . import state
from .state import VALID_FORMATS  # noqa: F401  (read by resolve_format callers)

# ── Machine-readable projection of a card ───────────────────────────────
IMAGE_FIELDS = ("small", "normal", "large", "png")

def slim_card(card):
    """Project a card dict down to stable, LLM-useful fields (token-efficient)."""
    legalities = card.get("legalities", {})
    prices = card.get("prices", {})
    uris = card.get("image_uris") or {}
    if not uris and card.get("card_faces"):
        for face in card["card_faces"]:
            if face.get("image_uris"):
                uris = face["image_uris"]
                break
    image_uris = {k: uris[k] for k in IMAGE_FIELDS if uris.get(k)}

    def num(v):
        try:
            f = float(v)
            return int(f) if f == int(f) else f
        except (TypeError, ValueError):
            return None

    return {
        "name": card.get("name"),
        "lang": card.get("lang", "en"),
        "mana_cost": card.get("mana_cost", ""),
        "cmc": card.get("cmc"),
        "type_line": card.get("type_line", ""),
        "colors": card.get("colors", []),
        # color_identity is kept because display_card renders it and search_color
        # / --commander filter on it; dropping it blanks the colour line on
        # 32,199 of 38,708 cards once results come from the DB.
        "color_identity": card.get("color_identity", []),
        "power": card.get("power"),
        "toughness": card.get("toughness"),
        "oracle_text": card.get("oracle_text", ""),
        "keywords": card.get("keywords", []),
        "legalities": {f: legalities.get(f) for f in
                       ("standard", "future", "historic", "gladiator", "pioneer",
                        "modern", "legacy", "pauper", "vintage", "commander", "oathbreaker",
                        "standard_brawl", "future_brawl", "classic_brawl", "brawl",
                        "timeless", "bullet", "predh", "premodern") if f in legalities},
        "prices": {k: num(prices.get(k)) for k in ("usd", "usd_foil", "usd_etched", "eur", "eur_foil", "tix")
                   if prices.get(k) is not None},
        "image_uris": image_uris,
        "scryfall_uri": card.get("scryfall_uri", ""),
    }

# Canonical rules-text projection: what the card DOES, and nothing else. Drops
# lang/color_identity/legalities/prices/image_uris/scryfall_uri from slim_card()
# because the 'oracle' command answers "what does this card actually do?", where
# a 352-byte legalities blob and a price map are pure noise. Measured on Sol Ring:
# 1,145 bytes (slim) -> 176 bytes here, ~85% smaller. Built by reusing slim_card()
# so DFC face handling and numeric coercion stay single-sourced.
TEXT_FIELDS = ("name", "mana_cost", "cmc", "type_line", "colors",
               "power", "toughness", "oracle_text", "keywords")

def text_card(card):
    """Project a card down to its canonical rules text (see TEXT_FIELDS)."""
    s = slim_card(card)
    return {k: s[k] for k in TEXT_FIELDS}

CSV_COLUMNS = ["name", "lang", "mana_cost", "cmc", "type_line", "colors", "color_identity",
               "power", "toughness", "oracle_text", "keywords",
               "usd", "usd_foil", "eur", "tix", "scryfall_uri"]

def _csv_row(card):
    s = slim_card(card)
    p = s["prices"]
    return [s["name"], s["lang"], s["mana_cost"], s["cmc"], s["type_line"],
            "|".join(s["colors"]) or "", "|".join(s["color_identity"]) or "",
            s["power"] or "", s["toughness"] or "",
            (s["oracle_text"] or "").replace("\n", " "),
            "|".join(s["keywords"]),
            p.get("usd", ""), p.get("usd_foil", ""), p.get("eur", ""), p.get("tix", ""),
            s["scryfall_uri"]]

def emit_records(cards):
    """Write result cards to stdout in the active MODE (pretty handled elsewhere)."""
    import csv as _csv
    if state.MODE == "json":
        json.dump([slim_card(c_) for c_ in cards], sys.stdout, ensure_ascii=False, default=str)
        sys.stdout.write("\n")
    elif state.MODE == "jsonl":
        for c_ in cards:
            sys.stdout.write(json.dumps(slim_card(c_), ensure_ascii=False, default=str) + "\n")
    elif state.MODE in ("csv", "tsv"):
        writer = _csv.writer(sys.stdout, delimiter="," if state.MODE == "csv" else "\t",
                             lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        for c_ in cards:
            writer.writerow(_csv_row(c_))

def emit_single(payload):
    """Emit one structured object (used by fuzzy/image machine-mode paths)."""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
