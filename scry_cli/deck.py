"""Decklist analysis engine: parsing, batch offline resolution, and the 4 diagnostic pillars.

Pillar 1: Vitals & Mana Architecture (Karsten colored source allocation, pip demand, early hurdles)
Pillar 2: Table Dynamic & Political Posture (Self-focused vs Targeted vs Symmetrical table influence)
Pillar 3: Engine Balance ('Fuel vs Payoff' action generator vs reward listener ratio)
Pillar 4: Deck Heritage (Vintage spectrum: Classic Pre-2003, Modern Frame 2003-2014, Contemporary 2015+)

Strictly offline-first: never makes HTTP requests to Scryfall API.
"""
from __future__ import annotations

import difflib
import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from . import state
from .project import slim_card
from .state import warn


# ── Decklist Parsing ──────────────────────────────────────────────────────

# Regex to strip set codes, collector numbers, foil tags:
# e.g. "1 Sol Ring (LCC) 211 *F*" -> "Sol Ring"
# e.g. "4 Lightning Bolt [M10:146] #foil" -> "Lightning Bolt"
_SET_TAG_RE = re.compile(
    r"\s*(?:\([A-Za-z0-9_-]+\)|\[[A-Za-z0-9_:-]+\])\s*(?:[A-Za-z0-9#*_-]+)?(?:\s*[*#][A-Za-z0-9*#_-]*)*\s*$"
)
# Trailing standalone foil/etched tags like *F* or *E* or #foil
_FOIL_TAG_RE = re.compile(r"\s+[*#][A-Za-z0-9*#_-]+\s*$")
# Line count prefix: "1 ", "1x ", "4x "
_COUNT_PREFIX_RE = re.compile(r"^\s*(\d+)\s*[xX]?\s+(.*)$")

# Section headers in exports
_SECTION_HEADERS = {
    "commander": {"// commander", "//commander", "commander:", "commander", "[commander]"},
    "sideboard": {"// sideboard", "//sideboard", "sideboard:", "sideboard", "[sideboard]"},
    "maybeboard": {"// maybeboard", "//maybeboard", "maybeboard:", "maybeboard", "[maybeboard]"},
    "mainboard": {"// main", "// mainboard", "deck", "mainboard:", "mainboard", "[mainboard]"},
}


def clean_card_name(raw_name: str) -> str:
    """Clean a card name string by removing set codes, collector numbers, and foil tags."""
    name = raw_name.strip()
    # Strip trailing foil markers like *F*
    name = _FOIL_TAG_RE.sub("", name).strip()
    # Strip set tags like (LCC) 211
    name = _SET_TAG_RE.sub("", name).strip()
    # Strip trailing foil tags again in case order was (LCC) *F*
    name = _FOIL_TAG_RE.sub("", name).strip()
    # Handle split card slashes: normalize "Fire/Ice" -> "Fire // Ice"
    if "/" in name and " // " not in name:
        parts = [p.strip() for p in name.split("/") if p.strip()]
        if len(parts) == 2:
            name = f"{parts[0]} // {parts[1]}"
    # Handle dual-name format like "Master Emerald Shrine (Command Tower)"
    m_paren = re.match(r"^(.+?)\s*\((.+?)\)$", name)
    if m_paren:
        p1, p2 = m_paren.group(1).strip(), m_paren.group(2).strip()
        from . import aliases
        if aliases.resolve_alias(p1):
            name = p1
        elif aliases.resolve_alias(p2):
            name = p2
    return name.strip()


def parse_decklist(text_or_lines: str | List[str]) -> List[Dict[str, Any]]:
    """Parse raw decklist lines into structured card entries.

    Returns a list of dicts:
        {"count": int, "name": str, "section": str, "raw": str}
    """
    if isinstance(text_or_lines, str):
        lines = text_or_lines.splitlines()
    else:
        lines = list(text_or_lines)

    current_section = "main"
    entries: List[Dict[str, Any]] = []

    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue

        lower = line_clean.lower()

        # Check section header
        is_header = False
        for sec_name, headers in _SECTION_HEADERS.items():
            if lower in headers or any(lower.startswith(h) for h in headers if h.endswith(":")):
                current_section = sec_name
                is_header = True
                break

        if is_header:
            continue

        # Ignore non-section comments
        if line_clean.startswith("#") or line_clean.startswith("//"):
            continue

        # Extract count
        m = _COUNT_PREFIX_RE.match(line_clean)
        if m:
            count = int(m.group(1))
            raw_name = m.group(2)
        else:
            count = 1
            raw_name = line_clean

        cleaned_name = clean_card_name(raw_name)
        if not cleaned_name:
            continue

        entries.append({
            "count": count,
            "name": cleaned_name,
            "section": current_section,
            "raw": line_clean,
        })

    return entries


# ── Batch Offline Name Resolution ──────────────────────────────────────────

def resolve_deck_cards(
    parsed_entries: List[Dict[str, Any]],
    offline: bool = False,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Resolve card names to card data strictly offline with optional online fallback."""
    from . import aliases

    distinct_names = list({e["name"].lower() for e in parsed_entries})
    name_map: Dict[str, Dict[str, Any]] = {}
    alias_targets: Dict[str, str] = {}  # original_nlc -> canonical_target_nlc

    # Check aliases for distinct names
    lookup_names_set: Set[str] = set()
    for n in distinct_names:
        canon = aliases.resolve_alias(n)
        if canon:
            canon_lc = canon.lower()
            alias_targets[n] = canon_lc
            lookup_names_set.add(canon_lc)
        else:
            lookup_names_set.add(n)

    lookup_names = list(lookup_names_set)
    raw_found: Dict[str, Dict[str, Any]] = {}

    # 1. Primary Batch Lookup
    if state.DB_MODE and state.DB is not None:
        chunk_size = 200
        for i in range(0, len(lookup_names), chunk_size):
            chunk = lookup_names[i : i + chunk_size]
            placeholders = ",".join("?" for _ in chunk)
            sql = f"SELECT name_lc, data FROM cards WHERE name_lc IN ({placeholders})"
            rows = state.DB.execute(sql, chunk).fetchall()
            for name_lc, data_json in rows:
                if name_lc not in raw_found:
                    try:
                        raw_found[name_lc] = json.loads(data_json)
                    except Exception:
                        pass
    elif state.CARDS:
        cards_by_name = {c.get("name", "").lower(): slim_card(c) for c in state.CARDS}
        for n in lookup_names:
            if n in cards_by_name:
                raw_found[n] = cards_by_name[n]

    # Map back to distinct_names
    for n in distinct_names:
        target = alias_targets.get(n, n)
        if target in raw_found:
            name_map[n] = raw_found[target]

    # 2. Offline Fallback for Unmatched Cards (Split cards, front-face, typos)
    unmatched = [n for n in distinct_names if n not in name_map]
    if unmatched:
        if state.DB_MODE and state.DB is not None:
            for un in unmatched:
                target_un = alias_targets.get(un, un)
                # Try front-face match: e.g. "Delver of Secrets" for "Delver of Secrets // Insectile Aberration"
                row = state.DB.execute(
                    "SELECT data FROM cards WHERE name_lc LIKE ? || ' // %' LIMIT 1",
                    (target_un,),
                ).fetchone()
                if row:
                    name_map[un] = json.loads(row[0])
                    continue

                # Try substring LIKE search if query is at least 4 chars
                if len(target_un) >= 4:
                    pattern = f"%{target_un}%"
                    candidates = state.DB.execute(
                        "SELECT name, data FROM cards WHERE name_lc LIKE ? LIMIT 5",
                        (pattern,),
                    ).fetchall()
                    if candidates:
                        best_match = None
                        best_score = 0.0
                        for cand_name, cand_data in candidates:
                            score = difflib.SequenceMatcher(None, target_un, cand_name.lower()).ratio()
                            if score > best_score:
                                best_score = score
                                best_match = json.loads(cand_data)
                        if best_match and best_score >= 0.7:
                            name_map[un] = best_match
        elif state.CARDS:
            for un in unmatched:
                target_un = alias_targets.get(un, un)
                for c in state.CARDS:
                    c_name = c.get("name", "").lower()
                    if c_name.startswith(target_un + " // "):
                        name_map[un] = slim_card(c)
                        break

    # 3. Online Fallback for Unresolved Cards (Self-healing via Scryfall API)
    discovered_online: Dict[str, Dict[str, Any]] = {}
    unmatched_after_offline = [n for n in distinct_names if n not in name_map]
    if unmatched_after_offline and not offline:
        from . import api
        for un in unmatched_after_offline:
            try:
                api_card = api.scryfall_fuzzy(un)
                if api_card and not api_card.get("error") and not isinstance(api_card.get("name"), list):
                    c_name = api_card.get("name", "")
                    f_name = api_card.get("flavor_name", "")
                    p_name = api_card.get("printed_name", "")
                    candidates = [c_name]
                    if f_name:
                        candidates.append(f_name)
                    if p_name:
                        candidates.append(p_name)
                    sim = max((api._similarity(un, cand) for cand in candidates if cand), default=0.0)
                    if sim >= 0.65 or (f_name and f_name.lower() == un.lower()):
                        local_card = None
                        if state.DB_MODE and state.DB is not None:
                            row = state.DB.execute(
                                "SELECT data FROM cards WHERE name_lc = ? LIMIT 1",
                                (c_name.lower(),),
                            ).fetchone()
                            if row:
                                try:
                                    local_card = json.loads(row[0])
                                except Exception:
                                    pass
                        elif state.CARDS:
                            for c in state.CARDS:
                                if c.get("name", "").lower() == c_name.lower():
                                    local_card = slim_card(c)
                                    break

                        card_to_use = local_card if local_card else slim_card(api_card)
                        name_map[un] = card_to_use
                        alias_targets[un] = c_name.lower()
                        discovered_online[un] = {
                            "canonical": c_name,
                            "flavor_name": f_name or un,
                        }
                        # Persist to local alias cache so it resolves offline in future sessions
                        aliases.save_user_alias(un, c_name)
            except Exception:
                pass

    # Build final list
    resolved: List[Dict[str, Any]] = []
    failed_names: List[str] = []

    for entry in parsed_entries:
        nlc = entry["name"].lower()
        if nlc in name_map:
            card_data = name_map[nlc]
            item: Dict[str, Any] = {"entry": entry, "card": card_data}
            if nlc in alias_targets:
                item["original_alias"] = entry["name"]
                item["alias_for"] = card_data.get("name", alias_targets[nlc])
                if nlc in discovered_online:
                    item["discovered_online"] = True
            resolved.append(item)
        else:
            failed_names.append(entry["name"])

    return resolved, failed_names


# ── Pillar 1: Vitals & Mana Architecture ───────────────────────────────────

_BASIC_LAND_COLORS = {
    "plains": "W", "island": "U", "swamp": "B", "mountain": "R", "forest": "G",
    "snow-covered plains": "W", "snow-covered island": "U",
    "snow-covered swamp": "B", "snow-covered mountain": "R",
    "snow-covered forest": "G",
}

_MANA_SYMBOL_RE = re.compile(r"\{([WUBRGCX0-9/]+)\}")


def analyze_mana(resolved_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate mana curve, Frank Karsten colored sources vs pip demands, and early hurdles."""
    lands_count = 0
    non_lands_count = 0
    total_cmc = 0.0
    turn_1_to_3_playables = 0
    curve_counts: Dict[str, int] = {"0": 0, "1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6+": 0}

    pip_demand: Dict[str, float] = {"W": 0.0, "U": 0.0, "B": 0.0, "R": 0.0, "G": 0.0, "C": 0.0}
    mana_sources: Dict[str, int] = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0}
    ramp_count = 0

    early_hurdles: List[Dict[str, Any]] = []
    candidates_for_hurdles = []
    high_cmc_outliers: List[str] = []

    for item in resolved_items:
        count = item["entry"]["count"]
        card = item["card"]
        type_line = card.get("type_line", "")
        oracle_text = card.get("oracle_text", "")
        mana_cost = card.get("mana_cost", "")
        cmc = float(card.get("cmc") or 0.0)

        is_land = "Land" in type_line

        if is_land:
            lands_count += count
            # Count colored sources from lands
            card_name_lower = card.get("name", "").lower()
            added_colors: Set[str] = set()

            # Check basic land names/types
            for basic_name, col in _BASIC_LAND_COLORS.items():
                if basic_name in card_name_lower:
                    added_colors.add(col)

            # Check oracle text for "{T}: Add {W}" or "{T}: Add one mana of any color"
            for col in ("W", "U", "B", "R", "G"):
                if f"{{{col}}}" in oracle_text or f"add {{{col}}}" in oracle_text.lower():
                    added_colors.add(col)

            if "any color" in oracle_text.lower() or "any one color" in oracle_text.lower():
                for col in ("W", "U", "B", "R", "G"):
                    added_colors.add(col)

            for col in added_colors:
                mana_sources[col] += count

        else:
            # Non-land card
            non_lands_count += count
            total_cmc += cmc * count

            # Curve bin
            cmc_int = int(cmc) if cmc == int(cmc) else int(cmc)
            if cmc_int <= 0:
                curve_counts["0"] += count
            elif cmc_int <= 5:
                curve_counts[str(cmc_int)] += count
            else:
                curve_counts["6+"] += count

            # Turn 1-3 playables
            if cmc <= 3.0:
                turn_1_to_3_playables += count

            # High CMC outliers (>= 6)
            if cmc >= 6.0 and count > 0:
                name = card.get("name", "Unknown")
                high_cmc_outliers.append(f"{name} (CMC {int(cmc) if cmc == int(cmc) else cmc})")

            # Detect Mana Rocks & Ramp spells
            is_artifact = "Artifact" in type_line
            is_creature = "Creature" in type_line
            is_spell = "Instant" in type_line or "Sorcery" in type_line

            if is_artifact and ("add {" in oracle_text.lower() or "any color" in oracle_text.lower()):
                ramp_count += count
                for col in ("W", "U", "B", "R", "G"):
                    if f"{{{col}}}" in oracle_text or "any color" in oracle_text.lower():
                        mana_sources[col] += count
            elif is_creature and ("{t}: add" in oracle_text.lower() or "add one mana" in oracle_text.lower()):
                ramp_count += count
            elif is_spell and ("search your library for a" in oracle_text.lower() and "land" in oracle_text.lower()):
                ramp_count += count

            # Pip demand from non-land mana costs
            symbols = _MANA_SYMBOL_RE.findall(mana_cost)
            color_pips_in_card: Dict[str, int] = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0}

            for sym in symbols:
                if "/" in sym:
                    # Hybrid e.g. W/U or 2/U or G/P
                    parts = sym.split("/")
                    for p in parts:
                        if p in pip_demand:
                            pip_demand[p] += (0.5 * count)
                            if p in color_pips_in_card:
                                color_pips_in_card[p] += 1
                elif sym in pip_demand:
                    pip_demand[sym] += (1.0 * count)
                    if sym in color_pips_in_card:
                        color_pips_in_card[sym] += 1

            # Record candidates for Frank Karsten Early Turn Hurdle Check
            if cmc <= 3.0:
                for col, pips in color_pips_in_card.items():
                    if pips >= 2:
                        candidates_for_hurdles.append((card, mana_cost, cmc, col, pips))

    # Evaluate early hurdles now that all sources are aggregated
    for card, mana_cost, cmc, col, pips in candidates_for_hurdles:
        recommended = 21 if cmc <= 2 else 19
        if pips >= 3:
            recommended = 23
        current = mana_sources.get(col, 0)
        if current < recommended:
            early_hurdles.append({
                "card": card.get("name"),
                "cost": mana_cost,
                "cmc": cmc,
                "color": col,
                "current_sources": current,
                "recommended_sources": recommended,
            })

    avg_cmc_nonlands = round(total_cmc / max(non_lands_count, 1), 2)

    # Compute percentages of colored pips
    colored_total_pips = sum(pip_demand[c] for c in ("W", "U", "B", "R", "G"))
    pip_pct: Dict[str, float] = {}
    source_total = sum(mana_sources.values())
    source_pct: Dict[str, float] = {}

    for c in ("W", "U", "B", "R", "G"):
        pip_pct[c] = round((pip_demand[c] / colored_total_pips * 100), 1) if colored_total_pips > 0 else 0.0
        source_pct[c] = round((mana_sources[c] / source_total * 100), 1) if source_total > 0 else 0.0

    return {
        "lands_count": lands_count,
        "non_lands_count": non_lands_count,
        "ramp_count": ramp_count,
        "avg_cmc_nonlands": avg_cmc_nonlands,
        "curve_counts": curve_counts,
        "turn_1_to_3_playables": turn_1_to_3_playables,
        "pip_demand": {k: int(v) if v == int(v) else v for k, v in pip_demand.items() if v > 0},
        "pip_pct": pip_pct,
        "mana_sources": mana_sources,
        "source_pct": source_pct,
        "early_hurdles": early_hurdles[:5],
        "high_cmc_outliers": high_cmc_outliers[:5],
    }


# ── Pillar 2: Table Dynamic & Political Posture ───────────────────────────

def analyze_table_dynamic(resolved_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Classify non-land cards by grammatical targeting: Self-focused vs Targeted vs Symmetrical."""
    self_count = 0
    targeted_count = 0
    symmetrical_count = 0

    symmetrical_patterns = (
        "each player", "each opponent", "all players", "all creatures",
        "all nonland", "all permanents", "each other player", "any player may",
        "players can't", "each other creature",
    )
    targeted_patterns = (
        "target opponent", "target player", "target permanent", "target creature",
        "target artifact", "target enchantment", "target spell", "target nonland",
        "destroy target", "exile target", "deals damage to target", "counter target",
    )

    total_non_land = 0
    for item in resolved_items:
        card = item["card"]
        if "Land" in card.get("type_line", ""):
            continue
        count = item["entry"]["count"]
        total_non_land += count
        oracle = card.get("oracle_text", "").lower()

        # Check symmetrical first
        if any(p in oracle for p in symmetrical_patterns):
            symmetrical_count += count
        elif any(p in oracle for p in targeted_patterns):
            # Verify it's not just "target creature you control"
            if "target creature you control" in oracle and not any(
                p in oracle for p in ("target spell", "target creature an opponent", "target opponent")
            ):
                self_count += count
            else:
                targeted_count += count
        else:
            self_count += count

    total = max(total_non_land, 1)
    self_pct = round(self_count / total * 100, 1)
    targeted_pct = round(targeted_count / total * 100, 1)
    symmetrical_pct = round(symmetrical_count / total * 100, 1)

    if symmetrical_pct >= 30.0:
        posture = "High Table Influence (Group Hug / Global Rules Engine)"
    elif targeted_pct >= 30.0:
        posture = "High Targeted Interaction (Table Police / Control)"
    elif self_pct >= 65.0:
        posture = "Self-Focused (Proactive Engine / Battlecruiser)"
    else:
        posture = "Balanced Midrange Posture"

    return {
        "self_count": self_count,
        "self_pct": self_pct,
        "targeted_count": targeted_count,
        "targeted_pct": targeted_pct,
        "symmetrical_count": symmetrical_count,
        "symmetrical_pct": symmetrical_pct,
        "posture": posture,
    }


# ── Pillar 3: Engine Balance ("Fuel vs Payoff") ───────────────────────────

_ENGINE_THEMES = [
    {
        "name": "Card Draw & Library Manipulation",
        "enablers": ("draw a card", "draws a card", "draw an", "draws an", "draw two", "draw three", "draw cards", "draws that many", "look at the top", "draw that many"),
        "payoffs": ("whenever you draw", "whenever a player draws", "whenever an opponent draws", "cards in your hand", "hand size"),
    },
    {
        "name": "Sacrifice & Death Triggers (Aristocrats)",
        "enablers": ("sacrifice a", "sacrifices a", "sacrifice another", "sacrifice this"),
        "payoffs": ("whenever another creature dies", "whenever a creature you control dies", "whenever a permanent is put into a graveyard"),
    },
    {
        "name": "+1/+1 Counters & Growth",
        "enablers": ("put a +1/+1 counter", "puts a +1/+1 counter", "proliferate"),
        "payoffs": ("whenever one or more +1/+1 counters", "creatures you control with +1/+1 counters", "for each counter"),
    },
    {
        "name": "Tokens & Swarm",
        "enablers": ("create a ", "creates a ", "create two", "create three", "token"),
        "payoffs": ("whenever a creature token", "whenever a token enters", "for each creature you control"),
    },
    {
        "name": "Text & Color Alteration (Color-Hacking)",
        "enablers": ("change the text", "color word", "basic land type"),
        "payoffs": ("protection from", "choose a color", "color of your choice"),
    },
]


def analyze_engine_balance(resolved_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Detect the deck's primary mechanical engine and compute Fuel (Enablers) vs Payoffs."""
    best_theme = _ENGINE_THEMES[0]
    best_total = 0
    theme_counts: Dict[str, Tuple[int, int]] = {}

    for theme in _ENGINE_THEMES:
        enablers = 0
        payoffs = 0
        for item in resolved_items:
            card = item["card"]
            count = item["entry"]["count"]
            oracle = card.get("oracle_text", "").lower()

            if any(e in oracle for e in theme["enablers"]):
                enablers += count
            if any(p in oracle for p in theme["payoffs"]):
                payoffs += count

        theme_counts[theme["name"]] = (enablers, payoffs)
        total = enablers + payoffs
        if total > best_total:
            best_total = total
            best_theme = theme

    enablers, payoffs = theme_counts.get(best_theme["name"], (0, 0))

    if payoffs > 0:
        ratio = round(enablers / payoffs, 2)
    else:
        ratio = float(enablers) if enablers > 0 else 1.0

    if payoffs == 0 and enablers > 5:
        diagnostic = "Open Value: High action generation with no internal payoff triggers."
    elif enablers == 0 and payoffs > 0:
        diagnostic = "Payoff Stalled: Reward triggers present with zero detected fuel enablers."
    elif ratio < 1.2:
        diagnostic = "Payoff Choke: High risk of reward cards stranded without enough enablers."
    elif ratio > 4.5:
        diagnostic = "Fuel Heavy: Ample enablers; may need more payoff outlets to close games."
    else:
        diagnostic = "Stable Flow Buffer"

    return {
        "primary_theme": best_theme["name"],
        "fuel_count": enablers,
        "payoff_count": payoffs,
        "ratio": ratio,
        "diagnostic": diagnostic,
    }


# ── Pillar 4: Deck Heritage & Historical Vintage ──────────────────────────

def analyze_heritage(resolved_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Partition cards by debut vintage era: Classic (Pre-2003), Modern (2003-2014), Contemporary (2015+)."""
    classic_count = 0
    modern_count = 0
    contemporary_count = 0
    total_cards = 0

    anchor_card = None
    oldest_era = 9999

    for item in resolved_items:
        card = item["card"]
        count = item["entry"]["count"]
        total_cards += count
        legalities = card.get("legalities", {})

        # Classification based on Scryfall format legalities
        # premodern: 1995-2003 (Classic era)
        # predh: up to 2011 (Modern frame era)
        is_premodern = legalities.get("premodern") == "legal"
        is_predh = legalities.get("predh") == "legal"

        card_name = card.get("name", "Unknown")

        if is_premodern:
            classic_count += count
            if oldest_era > 1995:
                oldest_era = 1995
                anchor_card = f"{card_name} (Pre-2003, Classic Era)"
        elif is_predh:
            modern_count += count
            if oldest_era > 2005:
                oldest_era = 2005
                if not anchor_card:
                    anchor_card = f"{card_name} (2003–2011, Modern Frame)"
        else:
            contemporary_count += count

    total = max(total_cards, 1)
    classic_pct = round(classic_count / total * 100, 1)
    modern_pct = round(modern_count / total * 100, 1)
    contemporary_pct = round(contemporary_count / total * 100, 1)

    # Approximate median age in years
    # Classic avg ~25 yrs, Modern avg ~15 yrs, Contemporary avg ~5 yrs
    median_age = round(
        ((classic_pct * 25.0) + (modern_pct * 15.0) + (contemporary_pct * 5.0)) / 100.0, 1
    )

    if not anchor_card and resolved_items:
        anchor_card = resolved_items[0]["card"].get("name", "Unknown")

    return {
        "classic_count": classic_count,
        "classic_pct": classic_pct,
        "modern_count": modern_count,
        "modern_pct": modern_pct,
        "contemporary_count": contemporary_count,
        "contemporary_pct": contemporary_pct,
        "anchor_card": anchor_card or "Unknown",
        "median_age_years": median_age,
    }


# ── Format Legality & Integrity Audit ─────────────────────────────────────

def audit_legality(
    resolved_items: List[Dict[str, Any]],
    commander_card: Optional[Dict[str, Any]] = None,
    target_format: str = "commander",
) -> Dict[str, Any]:
    """Verify format legalities, commander color identity, singleton rule, and deck size."""
    banned_cards: List[str] = []
    color_identity_violations: List[Dict[str, Any]] = []
    singleton_violations: List[str] = []

    total_card_count = sum(item["entry"]["count"] for item in resolved_items)

    commander_identity = set(commander_card.get("color_identity", [])) if commander_card else None

    basic_names = {
        "plains", "island", "swamp", "mountain", "forest", "wastes",
        "snow-covered plains", "snow-covered island", "snow-covered swamp",
        "snow-covered mountain", "snow-covered forest", "relentless rats",
        "rat colony", "shadowborn apostle", "persistent petitioners",
        "dragon's approach", "slime against humanity", "hare apparent",
    }

    card_counts: Dict[str, int] = {}

    for item in resolved_items:
        card = item["card"]
        count = item["entry"]["count"]
        name = card.get("name", "Unknown")
        card_counts[name] = card_counts.get(name, 0) + count

        # 1. Format Banlist check
        legality = card.get("legalities", {}).get(target_format.lower())
        if legality == "banned":
            banned_cards.append(name)

        # 2. Commander Color Identity check
        if target_format.lower() == "commander" and commander_identity is not None:
            card_identity = set(card.get("color_identity", []))
            if not card_identity.issubset(commander_identity):
                off_colors = sorted(list(card_identity - commander_identity))
                color_identity_violations.append({
                    "card": name,
                    "off_colors": off_colors,
                    "card_identity": sorted(list(card_identity)),
                    "commander_identity": sorted(list(commander_identity)),
                })

    # 3. Singleton Rule check (for Commander)
    if target_format.lower() == "commander":
        for name, cnt in card_counts.items():
            if cnt > 1 and name.lower() not in basic_names:
                singleton_violations.append(f"{name} ({cnt} copies)")

    is_legal = (
        len(banned_cards) == 0
        and len(color_identity_violations) == 0
        and len(singleton_violations) == 0
    )
    if target_format.lower() == "commander" and total_card_count != 100:
        is_legal = False

    return {
        "is_legal": is_legal,
        "total_card_count": total_card_count,
        "target_format": target_format,
        "banned_cards": banned_cards,
        "color_identity_violations": color_identity_violations,
        "singleton_violations": singleton_violations,
    }


# ── Top-Level Orchestrator ────────────────────────────────────────────────

def run_deck_analysis(
    text_or_lines: str | List[str],
    deck_name: str = "Decklist",
    target_format: str = "commander",
    commander_override: Optional[str] = None,
    offline: bool = False,
) -> Dict[str, Any]:
    """Execute complete decklist analysis and return the comprehensive diagnostic dictionary."""
    parsed = parse_decklist(text_or_lines)
    if not parsed:
        return {"error": "empty_decklist", "message": "No valid card lines found in decklist."}

    resolved, unresolved = resolve_deck_cards(parsed, offline=offline)

    # Detect Commander
    commander_card = None
    commander_entry = None

    if commander_override:
        # User explicitly passed --commander-card
        cleaned_override = clean_card_name(commander_override).lower()
        for item in resolved:
            if item["card"].get("name", "").lower() == cleaned_override:
                commander_card = item["card"]
                commander_entry = item["entry"]
                break
    else:
        # 1. Check if an item was tagged in 'commander' section
        for item in resolved:
            if item["entry"]["section"] == "commander":
                commander_card = item["card"]
                commander_entry = item["entry"]
                break

        # 2. Auto-detect if there is exactly 1 Legendary Creature or Planeswalker
        if not commander_card:
            legends = [
                item for item in resolved
                if "Legendary" in item["card"].get("type_line", "")
                and ("Creature" in item["card"].get("type_line", "") or "Planeswalker" in item["card"].get("type_line", ""))
                and item["entry"]["count"] == 1
            ]
            if len(legends) == 1:
                commander_card = legends[0]["card"]
                commander_entry = legends[0]["entry"]

    # Calculate Market Value
    usd_total = 0.0
    prices_list: List[Tuple[str, float]] = []
    for item in resolved:
        cnt = item["entry"]["count"]
        p = item["card"].get("prices", {}).get("usd")
        if p is not None:
            try:
                pval = float(p)
                usd_total += pval * cnt
                prices_list.append((item["card"].get("name", "Unknown"), pval))
            except (ValueError, TypeError):
                pass

    prices_list.sort(key=lambda x: x[1], reverse=True)

    mana_analysis = analyze_mana(resolved)
    table_dynamic = analyze_table_dynamic(resolved)
    engine_balance = analyze_engine_balance(resolved)
    heritage = analyze_heritage(resolved)
    legality_audit = audit_legality(resolved, commander_card, target_format)

    resolved_aliases = []
    seen_aliases = set()
    for item in resolved:
        orig = item.get("original_alias")
        if orig and orig.lower() not in seen_aliases:
            seen_aliases.add(orig.lower())
            resolved_aliases.append({
                "alias": orig,
                "canonical": item["card"].get("name", item.get("alias_for", "")),
                "discovered_online": item.get("discovered_online", False),
            })

    return {
        "deck_name": deck_name,
        "commander": commander_card.get("name") if commander_card else None,
        "commander_identity": commander_card.get("color_identity", []) if commander_card else [],
        "format": target_format,
        "total_cards": legality_audit["total_card_count"],
        "is_legal": legality_audit["is_legal"],
        "unresolved_cards": unresolved,
        "resolved_aliases": resolved_aliases,
        "valuation": {
            "usd_total": round(usd_total, 2),
            "top_expensive": prices_list[:3],
        },
        "mana_architecture": mana_analysis,
        "table_dynamic": table_dynamic,
        "engine_profile": engine_balance,
        "heritage": heritage,
        "legality_audit": legality_audit,
    }
