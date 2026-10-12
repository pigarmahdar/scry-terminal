"""Pretty-mode rendering: one function per output shape.

All of these print() to stdout with ANSI styling gated by USE_COLOR (state.USE_COLOR)
(never in machine modes — machine output goes through project.emit_*).
"""
import os
import re

from . import state
from .state import COLOUR_SYMBOLS, c, fmt, warn, machine_mode
from .project import emit_single
from .api import _resolve_card, _api_get, USER_AGENT

# ── Display a single card ───────────────────────────────────────────────
def display_card(card, index=None):
    name = card.get("name", "Unknown")
    mana = card.get("mana_cost", "—")
    cmc = card.get("cmc", "?")
    cmc_display = int(cmc) if isinstance(cmc, (int, float)) and cmc == int(cmc) else cmc
    type_line = card.get("type_line", "—")
    oracle = card.get("oracle_text", "—")
    power = card.get("power")
    toughness = card.get("toughness")
    colors = card.get("color_identity", [])
    keywords = card.get("keywords", [])
    legalities = card.get("legalities", {})

    # Colour display
    colour_str = " ".join(COLOUR_SYMBOLS.get(c, c) for c in colors) if colors else "—"

    # P/T display
    pt = f" ({power}/{toughness})" if power and toughness else ""

    # Format legality badges
    legal_formats = [f for f, v in legalities.items() if v == "legal" and f in ("commander", "modern", "legacy", "pauper", "vintage")]
    legal_str = ", ".join(legal_formats) if legal_formats else "none"

    # Build output
    prefix = f"  [{index}] " if index is not None else "  "
    print('\n' + prefix + c(name, '1;33') + '  ' + mana + '  (CMC ' + str(cmc_display) + ')')
    print(f"       {type_line}{pt}")
    print(f"       {colour_str}")
    if keywords:
        print(f"       Keywords: {', '.join(keywords)}")
    print(f"       {oracle}")
    print(f"       Legal: {legal_str}")
    print(f"       {card.get('scryfall_uri', '')}")

# ── Display a canonical card-text record (`oracle`) ─────────────────────
def display_oracle_card(card, printings=1, index=None):
    """Text-first rendering: no legality badges, no prices, no URI.

    Colours come from `colors` (printed colours) rather than color_identity as
    display_card does, because text_card() — the projection this renders — does
    not carry color_identity, and inventing a lookup here would reintroduce the
    field oracle deliberately drops.
    """
    name = card.get("name", "Unknown")
    mana = card.get("mana_cost", "")
    cmc = card.get("cmc", "?")
    cmc_display = int(cmc) if isinstance(cmc, (int, float)) and cmc == int(cmc) else cmc
    type_line = card.get("type_line", "—")
    oracle = card.get("oracle_text") or "(no rules text)"
    power = card.get("power")
    toughness = card.get("toughness")
    colors = card.get("colors", [])
    keywords = card.get("keywords", [])

    pt = f" ({power}/{toughness})" if power and toughness else ""
    colour_str = " ".join(COLOUR_SYMBOLS.get(x, x) for x in colors) if colors else ""
    cost_bits = []
    if mana:
        cost_bits.append(mana)
    cost_bits.append("CMC " + str(cmc_display))
    if printings > 1:
        cost_bits.append("%d printings" % printings)

    prefix = f"  [{index}] " if index is not None else "  "
    print('\n' + prefix + c(name, '1;33') + '  ' + '  ·  '.join(cost_bits))
    print(f"       {type_line}{pt}")
    if colour_str:
        print(f"       {colour_str}")
    if keywords:
        print(f"       Keywords: {', '.join(keywords)}")
    for line in str(oracle).split("\n"):
        print(f"       {line}")

def display_api_card(card):
    """Display a card from API JSON (same format as Oracle cache but may have extra fields)."""
    name = card.get("name", "Unknown")
    mana = card.get("mana_cost", "—")
    cmc = card.get("cmc", "?")
    cmc_display = int(cmc) if isinstance(cmc, (int, float)) and cmc == int(cmc) else cmc
    type_line = card.get("type_line", "—")
    oracle = card.get("oracle_text", "—")
    power = card.get("power")
    toughness = card.get("toughness")
    colors = card.get("color_identity", [])
    keywords = card.get("keywords", [])
    legalities = card.get("legalities", {})

    colour_str = " ".join(COLOUR_SYMBOLS.get(c, c) for c in colors) if colors else "—"
    pt = f" ({power}/{toughness})" if power and toughness else ""
    legal_formats = [f for f, v in legalities.items() if v == "legal" and f in ("commander", "modern", "legacy", "pauper", "vintage")]
    legal_str = ", ".join(legal_formats) if legal_formats else "none"

    print('\n  ' + c(name, '1;33') + '  ' + mana + '  (CMC ' + str(cmc_display) + ')')
    print(f"       {type_line}{pt}")
    print(f"       {colour_str}")
    if keywords:
        print(f"       Keywords: {', '.join(keywords)}")
    print(f"       {oracle}")
    print(f"       Legal: {legal_str}")
    print(f"       {card.get('scryfall_uri', '')}")

# ── Price display ─────────────────────────────────────────────────────
def format_price(value, symbol="$"):
    """Format a price string with currency symbol, or return '—' for None/null."""
    if value is None:
        return "—"
    try:
        amount = float(value)
        return f"{symbol}{amount:,.2f}"
    except (ValueError, TypeError):
        return "—"

def display_price_card(card, index=None):
    """Display a card with prices prominent."""
    name = card.get("name", "Unknown")
    mana = card.get("mana_cost", "—")
    type_line = card.get("type_line", "—")
    cmc = card.get("cmc", "?")
    cmc_display = int(cmc) if isinstance(cmc, (int, float)) and cmc == int(cmc) else cmc
    colors = card.get("color_identity", [])
    prices = card.get("prices", {})

    colour_str = " ".join(COLOUR_SYMBOLS.get(c, c) for c in colors) if colors else "—"

    usd = format_price(prices.get("usd"), "$")
    usd_foil = format_price(prices.get("usd_foil"), "$")
    eur = format_price(prices.get("eur"), "€")
    eur_foil = format_price(prices.get("eur_foil"), "€")
    tix = format_price(prices.get("tix"), "")

    prefix = f"  [{index}] " if index is not None else "  "
    print('\n' + prefix + c(name, '1;33') + '  ' + mana + '  (CMC ' + str(cmc_display) + ')')
    print(f"       {type_line}  •  {colour_str}")

    # Price line — only show foil if it has a value
    usd_part = f"USD {usd}"
    if usd_foil != "—":
        usd_part += f" (foil {usd_foil})"
    eur_part = f"EUR {eur}"
    if eur_foil != "—":
        eur_part += f" (foil {eur_foil})"
    tix_part = f"TIX {tix}"

    print('       ' + c(usd_part, '1;32') + '  •  ' + eur_part + '  •  ' + tix_part)
    print(f"       {card.get('scryfall_uri', '')}")

# ── Image download ──────────────────────────────────────────────────────
def _safe_filename(name):
    """Turn a card name into a safe filename (keep spaces, strip path chars)."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    return cleaned.strip() or "card"

def _pick_image(card, size="png", border=None):
    """Pick an image URI from a card dict. Returns (uri, ext) or (None, None)."""
    import urllib.parse
    uris = card.get("image_uris") or {}
    # Some special cards (tokens, double-faced backs) store per-face URIs in
    # `card_faces`. Fall back to the first face that has images.
    if not uris and card.get("card_faces"):
        for face in card["card_faces"]:
            if face.get("image_uris"):
                uris = face["image_uris"]
                break

    if not uris:
        return None, None

    # Order of preference by requested size
    order = {
        "small": ["small", "normal", "large", "png"],
        "normal": ["normal", "large", "png", "small"],
        "large": ["large", "png", "normal", "small"],
        "png": ["png", "large", "normal", "small"],
    }.get(size, ["png", "large", "normal", "small"])

    uri = next((uris[k] for k in order if uris.get(k)), None)
    if not uri:
        return None, None

    # Determine extension from the URL itself (e.g. .png vs .jpg)
    path = urllib.parse.urlparse(uri).path.lower()
    ext = ".png" if path.endswith(".png") else (".jpg" if path.endswith(".jpg") else ".bin")
    return uri, ext


# ── Image command handler ────────────────────────────────────────────────
def handle_image(query, options):
    """Resolve a card name and download its image."""
    import shutil
    import urllib.request
    query = query.strip().strip('"')
    if not query:
        print("\n  Usage: scryfall image <card name> [--size small|normal|large|png] [--out <dir>] [--border black|silver]\n")
        return

    size = options.get("size", "png")
    out_dir = os.path.expanduser(options.get("out") or "~/Desktop")
    border = options.get("border")

    card, sim = _resolve_card(query)

    if card is None:
        if machine_mode():
            emit_single({"query": query, "saved": None, "error": "not_found"})
        else:
            print("\n  " + c(fmt("✗ Could not find a card matching '{}'.", query), '1;31') + "\n")
        return

    name = card.get("name", "Unknown")
    if not machine_mode():
        note = "" if sim >= 0.9 else "  " + c(fmt("(from '{}')", query), '2')
        print('\n  ' + c('Card:', '1') + ' ' + name + note)

    # If a border is requested, ask the API for that specific version
    if border:
        set_code = (card.get("set") or "").upper()
        api_card = _api_get("/cards/named", {"exact": name, "set": set_code}) if set_code else None
        if api_card and not api_card.get("error") and api_card.get("border") == border:
            card = api_card
        else:
            warn(f"no {border}-border version found; using default")

    uri, ext = _pick_image(card, size=size)
    if not uri:
        if machine_mode():
            emit_single({"query": query, "name": name, "saved": None, "error": "no_image"})
        else:
            print('  ' + c('✗ No image available for this card.', '1;31') + '\n')
        return

    # Build output path — avoid clobbering existing files
    os.makedirs(out_dir, exist_ok=True)
    base = _safe_filename(name)
    out_path = os.path.join(out_dir, f"{base}{ext}")
    counter = 1
    while os.path.exists(out_path):
        out_path = os.path.join(out_dir, f"{base} ({counter}){ext}")
        counter += 1

    if not machine_mode():
        print('  ' + c('Source:', '2') + ' ' + uri)
    try:
        req = urllib.request.Request(uri, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as resp, open(out_path, "wb") as f:
            shutil.copyfileobj(resp, f)
    except Exception as e:
        if machine_mode():
            emit_single({"query": query, "name": name, "source_uri": uri,
                         "saved": None, "error": f"download_failed: {e}"})
        else:
            print('  ' + c('✗ Download failed: ' + str(e), '1;31') + '\n')
        return

    if machine_mode():
        emit_single({"query": query, "name": name, "source_uri": uri,
                     "saved": out_path, "bytes": os.path.getsize(out_path), "error": None})
    else:
        size_kb = os.path.getsize(out_path) / 1024
        print('  ' + c('✓ Saved:', '1;32') + ' ' + out_path + '  (' + c(str(round(size_kb)) + ' KB', '2') + ')\n')


# ── Deck Analysis Display ───────────────────────────────────────────────

def _bar(pct: float, width: int = 15) -> str:
    """Generate a simple block bar for percentages."""
    filled = max(0, min(width, int(round((pct / 100.0) * width))))
    return "■" * filled


def display_deck_analysis(res: dict):
    """Render the 4 diagnostic pillars and legality vitals to stdout in pretty mode."""
    if res.get("error"):
        print('\n  ' + c('✗ Error: ' + res.get("message", "Unknown error"), '1;31') + '\n')
        return

    name = res.get("deck_name", "Decklist")
    fmt_name = res.get("format", "commander").title()
    total_cards = res.get("total_cards", 0)
    is_legal = res.get("is_legal", False)

    status_str = c('✓ Tournament Legal', '1;32') if is_legal else c('✗ Issues Found', '1;31')

    print(f"\n  {c('Deck Analysis:', '1;37')} {name}")
    print(f"  Format: {fmt_name} ({total_cards} cards)  ·  Status: {status_str}")

    cmd_name = res.get("commander")
    if cmd_name:
        cmd_id = res.get("commander_identity", [])
        id_str = " ".join(COLOUR_SYMBOLS.get(col, col) for col in cmd_id) if cmd_id else "Colorless"
        print(f"  Commander: {c(cmd_name, '1;33')} (Identity: {id_str})")

    # Display Errors / Warnings if any
    audit = res.get("legality_audit", {})
    banned = audit.get("banned_cards", [])
    violations = audit.get("color_identity_violations", [])
    singletons = audit.get("singleton_violations", [])
    unresolved = res.get("unresolved_cards", [])

    if banned or violations or singletons or unresolved:
        print(f"\n  {c('ERRORS & WARNINGS:', '1;31')}")
        for b in banned:
            print(f"    {c('[BANNED]', '1;31')} {b} is banned in {fmt_name}")
        for v in violations:
            off = ", ".join(v.get("off_colors", []))
            print(f"    {c('[OFF-COLOR]', '1;31')} {v['card']} has off-color identity {{{off}}}")
        for s in singletons:
            print(f"    {c('[SINGLETON]', '1;31')} {s}")
        for u in unresolved:
            print(f"    {c('[UNRESOLVED]', '1;33')} Could not resolve card: '{u}'")

    # Pillar 1: Vitals & Mana Health
    mana = res.get("mana_architecture", {})
    lands = mana.get("lands_count", 0)
    ramp = mana.get("ramp_count", 0)
    avg_cmc = mana.get("avg_cmc_nonlands", 0.0)
    t1_3 = mana.get("turn_1_to_3_playables", 0)

    print(f"\n  {c('[1] Vitals & Mana Health', '1;36')}")
    print(f"    Lands: {lands}  ·  Rocks/Ramp: {ramp}  ·  Avg Non-Land CMC: {avg_cmc}  ·  Turn 1–3 Density: {t1_3} cards")

    pip_pct = mana.get("pip_pct", {})
    source_pct = mana.get("source_pct", {})
    pip_dem = mana.get("pip_demand", {})

    active_colors = [col for col in ("W", "U", "B", "R", "G") if pip_dem.get(col, 0) > 0 or source_pct.get(col, 0) > 0]
    if active_colors:
        print(f"    Mana Balance:")
        for col in active_colors:
            sym = COLOUR_SYMBOLS.get(col, col)
            p_p = pip_pct.get(col, 0.0)
            s_p = source_pct.get(col, 0.0)
            diff = s_p - p_p
            note = c("Balanced", "2")
            if diff < -12.0:
                note = c("⚠ Deficit", "1;33")
            elif diff > 15.0:
                note = c("Surplus", "2")
            print(f"    {sym} {col}: {_bar(p_p, 10)} {p_p}% pips  vs  {_bar(s_p, 10)} {s_p}% sources ({note})")

    hurdles = mana.get("early_hurdles", [])
    if hurdles:
        for h in hurdles:
            print(f"    {c('⚠ Early Hurdle:', '1;33')} {h['card']} ({h['cost']}) has {h['current_sources']} {h['color']} sources (recommend {h['recommended_sources']}+)")

    # Pillar 2: Table Dynamic (Posture)
    dyn = res.get("table_dynamic", {})
    print(f"\n  {c('[2] Table Dynamic & Posture', '1;36')}")
    print(f"    Self-Focused: {dyn.get('self_pct')}% ({dyn.get('self_count')} cards)  ·  "
          f"Targeted: {dyn.get('targeted_pct')}% ({dyn.get('targeted_count')} cards)  ·  "
          f"Symmetrical: {dyn.get('symmetrical_pct')}% ({dyn.get('symmetrical_count')} cards)")
    print(f"    Posture: {c(dyn.get('posture', ''), '1;35')}")

    # Pillar 3: Engine Balance
    eng = res.get("engine_profile", {})
    print(f"\n  {c('[3] Engine Balance (' + eng.get('primary_theme', '') + ')', '1;36')}")
    fuel = eng.get("fuel_count", 0)
    payoffs = eng.get("payoff_count", 0)
    print(f"    Fuel (Enablers):  {_bar(min(100, fuel * 5), 10)} {fuel} cards")
    print(f"    Payoffs (Spouts): {_bar(min(100, payoffs * 5), 10)} {payoffs} cards")
    print(f"    Ratio: {eng.get('ratio')} : 1 ({c(eng.get('diagnostic', ''), '2')})")

    # Pillar 4: Deck Heritage & Era Distribution
    her = res.get("heritage", {})
    print(f"\n  {c('[4] Deck Heritage & Era Distribution', '1;36')}")
    print(f"    Classic (Pre-2003): {her.get('classic_pct')}% ({her.get('classic_count')} cards)  ·  "
          f"Modern Frame: {her.get('modern_pct')}% ({her.get('modern_count')} cards)  ·  "
          f"Contemporary: {her.get('contemporary_pct')}%")
    print(f"    Heritage Anchor: {c(her.get('anchor_card', ''), '1;33')}  ·  Est. Median Age: {her.get('median_age_years')} yrs")

    val = res.get("valuation", {})
    usd = val.get("usd_total", 0.0)
    top_cards = val.get("top_expensive", [])
    top_str = ", ".join(f"{name} ${price:.2f}" for name, price in top_cards) if top_cards else "None"
    print(f"\n  Est. Market USD: {c('$' + f'{usd:.2f}', '1;32')} (Top: {top_str})\n")

