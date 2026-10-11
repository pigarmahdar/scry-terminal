# Argument parsing, command routing, maintenance handlers, main().
# This is the only module that may call sys.exit() for user-facing errors (the
# library modules above it raise/return instead), and the only one that reads
# sys.argv. The usage docstring below is printed verbatim by `scryfall` with no
# args, exactly as the single-file script did.
"""
scryfall — Local MTG card search from your Oracle cache.
Usage:
  scryfall <command> <query> [options]

Commands:
  name <query>        Search by card name (partial match)
  text <query>        Search by oracle text (what the card does)
  type <query>        Search by type line (creature, enchantment, etc.)
  color <W|U|B|R|G>  Search by colour identity (combine letters, e.g. WG)
  cmc <number>        Search by mana value (exact or <=  / >=)
  keyword <query>     Search by keyword (Flying, Trample, etc.)
  oracle <name>       Canonical card text only, deduplicated across printings
  fuzzy <query>        Fuzzy name search (handles typos, partial names)
  random              Get a random card
  search <query>      General search across name + text + type
  price <query>       Search by name, showing market prices
  image <name>        Download PNG image of a card (to Desktop by default)
  update              Update the Oracle cache from Scryfall

Options:
  --limit N           Max results (default: 10)
  --commander <WUBRG> Cards whose colour identity fits within these colours
  --legal <format>    Only cards legal in a format (commander, modern, etc.)
  --exact             Exact name match only (for 'name' command)
  --sort <field>      Sort results by: name, cmc, price (default: database order; price desc for price command)
  --size <small|normal|large|png>  Image size for 'image' command (default: png)
  --out <dir>         Output directory for 'image' command (default: ~/Desktop)
  --border <black|silver>  Request a specific border colour for 'image'
  --format <fmt>      Output format: pretty | json | jsonl | csv | tsv
                      Default is auto-detected: pretty on a terminal, jsonl when
                      piped or redirected. Env override: SCRYFALL_FORMAT=<fmt>.
                      NO_COLOR=1 strips ANSI styling from pretty output.

Machine-readable output (json/jsonl/csv/tsv):
  When stdout is not a terminal — e.g. an LLM harness, script, or pipe — the
  tool emits compact JSONL automatically, one card per line, with stable fields:
  name, lang, mana_cost, cmc, type_line, colors, power, toughness, oracle_text,
  keywords, legalities, prices, image_uris, scryfall_uri. Warnings and status
  messages go to stderr so stdout stays pure data. 'fuzzy' becomes
  non-interactive: it returns the best match plus candidate suggestions instead
  of prompting. Pass --pretty to force human output even when piped.

Examples:
  scryfall name "Gilded Drake"
  scryfall text "create a treasure token"
  scryfall type "enchantment"
  scryfall color WG
  scryfall cmc <=3
  scryfall keyword flying
  scryfall random
  scryfall search "2 mana green creature"
  scryfall name "Sol Ring" --legal commander --limit 5
  scryfall oracle "Sol Ring"
  scryfall oracle "Elemental" --limit 999
  scryfall fuzzy "sol rng"
  scryfall fuzzy "jac bele"
  scryfall price "Sol Ring"
  scryfall price "treasure" --sort price
  scryfall image "Sol Ring"
  scryfall image "sol rng" --size large
  scryfall search "counter target spell" --json | jq '.[].name'
  SCRYFALL_FORMAT=json scryfall price "Force of Will"   # for agents/harnesses
"""

import json
import os
import sys

from . import state
from .state import (
    VALID_FORMATS, ORACLE_PATH, DB_PATH, SCHEMA_VERSION,
    machine_mode, resolve_format, _colors_enabled, c, fmt, warn,
)
from .project import emit_single, emit_records, text_card, slim_card  # noqa: F401
from .store import (
    _sqlite_module, _sqlite_supports_fts5, db_status, build_db, load_cards,
)
from .search import (
    search_name, search_text, search_type, search_color, search_cmc,
    search_keyword, search_general, search_random, search_oracle,
    apply_filters, sort_results,
)
from .api import handle_fuzzy, SCRYFALL_API  # noqa: F401
from .display import (
    display_card, display_oracle_card, display_price_card, handle_image,
)


# ── Parse arguments ─────────────────────────────────────────────────────
def parse_args(args):
    """Parse command line arguments into (command, query, options)."""
    command = None
    query_parts = []
    options = {"limit": 10, "commander": None, "legal": None, "exact": False, "sort": None,
               "size": None, "out": None, "border": None, "format": None}

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--limit" and i + 1 < len(args):
            try:
                options["limit"] = max(0, int(args[i + 1]))
            except ValueError:
                pass
            i += 2
        elif arg == "--commander" and i + 1 < len(args):
            options["commander"] = args[i + 1]
            i += 2
        elif arg == "--legal" and i + 1 < len(args):
            options["legal"] = args[i + 1]
            i += 2
        elif arg == "--exact":
            options["exact"] = True
            i += 1
        elif arg == "--sort" and i + 1 < len(args):
            options["sort"] = args[i + 1].lower()
            i += 2
        elif arg == "--size" and i + 1 < len(args):
            options["size"] = args[i + 1].lower()
            i += 2
        elif arg == "--out" and i + 1 < len(args):
            options["out"] = args[i + 1]
            i += 2
        elif arg == "--border" and i + 1 < len(args):
            options["border"] = args[i + 1].lower()
            i += 2
        elif arg == "--format" and i + 1 < len(args):
            options["format"] = args[i + 1].lower()
            i += 2
        elif arg in ("--json", "-j"):
            options["format"] = "json"
            i += 1
        elif arg == "--jsonl":
            options["format"] = "jsonl"
            i += 1
        elif arg == "--csv":
            options["format"] = "csv"
            i += 1
        elif arg == "--tsv":
            options["format"] = "tsv"
            i += 1
        elif arg == "--pretty":
            options["format"] = "pretty"
            i += 1
        elif arg == "--no-db":
            # Escape hatch: force the legacy JSONL scan path (debugging/parity).
            state.FORCE_NO_DB = True  # module attr: parse_args can't `global` across modules
            i += 1
        elif arg.startswith("--"):
            # Unknown flag: emit structured error (stdout is still pure data)
            emit_single({"error": "unknown_flag", "flag": arg})
            sys.exit(1)
        elif command is None:
            command = arg.lower()
            i += 1
        else:
            query_parts.append(arg)
            i += 1

    query = " ".join(query_parts) if query_parts else ""
    return command, query, options

# ── Update cache ─────────────────────────────────────────────────────
def handle_update():
    """Download the latest Oracle Cards bulk data from Scryfall."""
    import gzip
    import shutil
    import time
    import urllib.request
    cache_dir = os.path.dirname(ORACLE_PATH)
    os.makedirs(cache_dir, exist_ok=True)

    gz_path = ORACLE_PATH + ".gz"
    backup_path = ORACLE_PATH + ".backup"

    # 1. Get the download URL
    warn("Fetching Scryfall bulk-data catalogue...")
    try:
        req = urllib.request.Request(
            "https://api.scryfall.com/bulk-data",
            headers={"User-Agent": "scryfall-cli/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            bulk_data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        warn('✗ Failed to fetch catalogue: ' + str(e))
        sys.exit(1)

    download_url = None
    for item in bulk_data.get("data", []):
        if item.get("type") == "oracle_cards":
            download_url = item.get("jsonl_download_uri")
            break

    if not download_url:
        warn('✗ Could not find oracle_cards download URL.')
        sys.exit(1)

    # 2. Download the gzipped file
    warn(f"Downloading from:\n  {download_url}")
    try:
        req = urllib.request.Request(
            download_url,
            headers={"User-Agent": "scryfall-cli/1.0"},
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            with open(gz_path, "wb") as f:
                shutil.copyfileobj(resp, f)
    except Exception as e:
        warn('✗ Download failed: ' + str(e))
        sys.exit(1)

    if os.path.getsize(gz_path) == 0:
        os.remove(gz_path)
        warn('✗ Downloaded file is empty.')
        sys.exit(1)

    # 3. Decompress and replace
    warn("Decompressing...")
    try:
        # Back up existing cache
        if os.path.exists(ORACLE_PATH):
            shutil.copy2(ORACLE_PATH, backup_path)

        with gzip.open(gz_path, "rb") as f_in:
            with open(ORACLE_PATH, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        os.remove(gz_path)
    except Exception as e:
        # Restore backup on failure
        if os.path.exists(backup_path):
            shutil.move(backup_path, ORACLE_PATH)
        if os.path.exists(gz_path):
            os.remove(gz_path)
        warn('✗ Decompression failed: ' + str(e))
        sys.exit(1)

    # 4. Count and report
    line_count = 0
    with open(ORACLE_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                line_count += 1

    file_size = os.path.getsize(ORACLE_PATH)
    size_mb = file_size / (1024 * 1024)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    # Clean up backup
    if os.path.exists(backup_path):
        os.remove(backup_path)

    print('\n  ' + c('✓ Oracle cache updated: ' + timestamp, '1;32'), file=sys.stderr)
    print(f"    File:  {ORACLE_PATH}", file=sys.stderr)
    print(f"    Size:  {size_mb:.1f} MB", file=sys.stderr)
    print(f"    Cards: {line_count:,}\n", file=sys.stderr)

    # Refresh the derived search index so queries stay fast after an update.
    if _sqlite_supports_fts5(_sqlite_module()):
        warn("Rebuilding search index...")
        build_db(verbose=True)
    else:
        warn("sqlite3/FTS5 unavailable in this Python build;"
             " queries will use the JSONL scan path.")

VALID_COMMANDS = {"name", "text", "type", "color", "cmc", "keyword", "fuzzy", "random",
                  "search", "price", "image", "update", "reindex", "doctor", "oracle"}

# ── Index maintenance commands (Option C) ───────────────────────────────
def handle_reindex():
    """Rebuild the SQLite sidecar from the JSONL cache."""
    import time
    if not os.path.exists(ORACLE_PATH):
        warn("Oracle cache not found at %s — run 'scryfall update' first." % ORACLE_PATH)
        sys.exit(1)
    sq = _sqlite_module()
    if sq is None or not _sqlite_supports_fts5(sq):
        warn("this Python build has no sqlite3/FTS5+trigram support; nothing to index.")
        warn("Queries will keep using the JSONL scan path.")
        sys.exit(1)
    t0 = time.time()
    if not build_db(verbose=True):
        sys.exit(1)
    warn("reindex took %.2fs" % (time.time() - t0))

def handle_doctor():
    """Report index health: staleness, schema version, FTS5, row-count parity."""
    sq = _sqlite_module()
    fts_ok = _sqlite_supports_fts5(sq)
    stale, reason = db_status()
    lines = []
    lines.append(("jsonl", "%s" % ORACLE_PATH))
    lines.append(("jsonl size", "%.1f MB" % (os.path.getsize(ORACLE_PATH) / (1024*1024))
                  if os.path.exists(ORACLE_PATH) else "MISSING"))
    lines.append(("sqlite3", "available (%s)" % sq.sqlite_version if sq else "UNAVAILABLE"))
    lines.append(("fts5 + trigram", "ok" if fts_ok else "unavailable -> JSONL path"))
    if os.path.exists(DB_PATH):
        lines.append(("index", DB_PATH))
        lines.append(("index size", "%.1f MB (+ WAL siblings while open)" %
                      (os.path.getsize(DB_PATH) / (1024*1024))))
        lines.append(("status", "fresh" if not stale else "STALE: %s" % reason))
        try:
            conn = sq.connect(DB_PATH)
            meta = dict(conn.execute("SELECT k, v FROM meta").fetchall())
            db_rows = conn.execute("SELECT count(*) FROM cards").fetchone()[0]
            ft_rows = conn.execute("SELECT count(*) FROM cards_ft").fetchone()[0]
            color_rows = conn.execute("SELECT count(*) FROM colors").fetchone()[0]
            conn.close()
            jsonl_rows = 0
            if os.path.exists(ORACLE_PATH):
                with open(ORACLE_PATH, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        jsonl_rows += chunk.count(b"\n")
            lines.append(("schema_version", "%s (expected %s)" %
                          (meta.get("schema_version"), SCHEMA_VERSION)))
            lines.append(("rows indexed", "%s vs %s jsonl lines%s" %
                          (format(db_rows, ","), format(jsonl_rows, ","),
                           "" if db_rows == jsonl_rows else "   <-- MISMATCH (truncated build?)")))
            if ft_rows != db_rows:
                lines.append(("fts rows", "%s != cards %s  <-- MISMATCH" %
                              (format(ft_rows, ","), format(db_rows, ","))))
            lines.append(("colour rows", format(color_rows, ",")))
        except Exception as e:
            lines.append(("index read", "FAILED: %s" % e))
    else:
        lines.append(("index", "not built yet (runs automatically on next query,"
                               " or 'scryfall reindex')"))

    use_db = bool(sq and fts_ok and not stale and os.path.exists(DB_PATH))
    lines.append(("queries would use", "SQLite index" if use_db else "JSONL full scan"))
    width = max(len(k) for k, _ in lines)
    print()
    for k, v in lines:
        print("  " + c(k.ljust(width), '1') + "  " + str(v))
    print()

def _handle_oracle(query, options):
    """`oracle <name>`: canonical rules text, deduplicated across identical printings.

    Deliberately offline-only (no Scryfall API step) so it stays a guaranteed-fast
    lookup; typos are `fuzzy`'s job. --commander/--legal/--sort do not apply to a
    single-card lookup, and csv/tsv have no column set for this shape, so those
    are warned about rather than silently ignored.
    """
    limit = options["limit"]
    records, total, mode = search_oracle(query, limit=None if not limit or limit <= 0 else limit)

    if options.get("commander") or options.get("legal"):
        warn("oracle ignores --commander/--legal (a lookup, not a browse;"
             " use 'name'/'search' with those filters)")
    if options.get("sort"):
        warn("oracle ignores --sort (results are in cache order)")

    shown = len(records)
    if machine_mode():
        if state.MODE in ("csv", "tsv"):
            emit_single({"error": "unsupported_format", "format": state.MODE,
                         "command": "oracle", "valid_formats": ["pretty", "json", "jsonl"]})
            sys.exit(1)
        if total > shown:
            warn(f"{shown} of {total} matches shown (use --limit {total} for all)")
        # Same array-vs-lines contract emit_records() upholds for other commands.
        payloads = []
        for card, n in records:
            out = text_card(card)
            if n > 1:
                out["printings"] = n
            payloads.append(out)
        if state.MODE == "json":
            json.dump(payloads, sys.stdout, ensure_ascii=False, default=str)
            sys.stdout.write("\n")
        else:
            for out in payloads:
                sys.stdout.write(json.dumps(out, ensure_ascii=False, default=str) + "\n")
        return

    if not records:
        print("\n  No cards found matching your search.")
        return
    if total > shown:
        print(f"\n  Showing {shown} of {total} results (use --limit {total} to see all):")
    else:
        print(f"\n  Found {total} canonical result{'s' if total != 1 else ''}:")
    for i, (card, n) in enumerate(records, 1):
        display_oracle_card(card, printings=n, index=i)
    print()

# ── Main ────────────────────────────────────────────────────────────────
def main():

    if len(sys.argv) < 2:
        print(__doc__)
        return

    command, query, options = parse_args(sys.argv[1:])

    # Resolve output format: flag > $SCRYFALL_FORMAT > TTY auto-detect
    state.MODE = resolve_format(options.get("format"))
    state.USE_COLOR = _colors_enabled(state.MODE)

    # Handle update command (doesn't need card data)
    if command == "update":
        handle_update()
        return

    # Index maintenance (doesn't need card data loaded)
    if command == "reindex":
        handle_reindex()
        return
    if command == "doctor":
        handle_doctor()
        return

    # Handle image command (uses API first, local cache as fallback)
    if command == "image":
        load_cards()
        handle_image(query, options)
        return

    # Validate command (#4)
    if command and command not in VALID_COMMANDS:
        if machine_mode():
            emit_single({"error": "unknown_command", "command": command,
                         "valid_commands": sorted(VALID_COMMANDS - {"update"})})
        else:
            print("\n  " + c(fmt("✗ Unknown command '{}'.", command), '1;31'))
            print(f"  Valid commands: {', '.join(sorted(VALID_COMMANDS - {'update'}))}")
            print(f"  Use 'scryfall search \"{command} {query}\"' for a general search.\n")
        sys.exit(1)

    # Guard empty queries (#1) — except random which needs no query
    if command != "random" and not query.strip():
        if machine_mode():
            emit_single({"error": "empty_query", "command": command})
        else:
            print('\n  ' + c('✗ No search query provided.', '1;31'))
            print(f"  Usage: scryfall {command} <query>\n")
        sys.exit(1)

    # Load cards
    load_cards()

    # Run search
    results = []
    if command == "name":
        results = search_name(query, exact=options["exact"])
    elif command == "fuzzy":
        handle_fuzzy(query, options)
        return
    elif command == "text":
        results = search_text(query)
    elif command == "type":
        results = search_type(query)
    elif command == "color":
        try:
            results = search_color(query)
        except ValueError as e:
            if machine_mode():
                emit_single({"error": "invalid_color", "query": query, "details": str(e)})
            else:
                print("\n  " + c(fmt("✗ Invalid colour: {}", e), '1;31'))
                print("  Usage: scryfall color W | scryfall color WG | scryfall color BGR\n")
            sys.exit(1)
    elif command == "cmc":
        try:
            results = search_cmc(query)
        except ValueError as e:
            if machine_mode():
                emit_single({"error": "invalid_cmc", "query": query, "details": str(e)})
            else:
                print("\n  " + c(fmt("✗ Invalid mana value: {}", e), '1;31'))
                print("  Usage: scryfall cmc 3 | scryfall cmc <=3 | scryfall cmc >=3\n")
            sys.exit(1)
    elif command == "keyword":
        results = search_keyword(query)
    elif command == "oracle":
        # Own shape (records + printing counts, text-only projection), so it
        # bypasses the shared filter/sort/emit block below.
        _handle_oracle(query, options)
        return
    elif command == "random":
        results = search_random()
    elif command == "search":
        results = search_general(query)
    elif command == "price":
        results = search_name(query, exact=options["exact"])
        # Default to price-sorted (most expensive first) when no sort specified
        if not options["sort"]:
            options["sort"] = "price"
        if machine_mode():
            # Numeric prices for clean comparisons; keep every field from the projector
            for r in results:
                p = r.get("prices", {})
                for k in ("usd", "usd_foil", "usd_etched", "eur", "eur_foil", "tix"):
                    try:
                        p[k] = float(p[k]) if p.get(k) is not None else None
                    except (TypeError, ValueError):
                        p[k] = None

    # Apply filters
    results = apply_filters(results, commander=options["commander"], legal=options["legal"])

    # Apply sort (#5)
    if options["sort"]:
        results = sort_results(results, options["sort"])

    limit = options["limit"]
    total = len(results)
    shown = min(limit, total)

    # ── Machine-readable output: stdout is pure data, meta goes to stderr ──
    if machine_mode():
        if total > shown:
            warn(f"{shown} of {total} matches shown (use --limit {total} for all)")
        emit_records(results[:shown])
        return

    # Display
    if not results:
        print(f"\n  No cards found matching your search.")
        return

    if total > shown:
        print(f"\n  Showing {shown} of {total} results (use --limit {total} to see all):")
    else:
        print(f"\n  Found {total} result{'s' if total != 1 else ''}:")

    display_fn = display_price_card if command == "price" else display_card
    for i, card in enumerate(results[:shown], 1):
        display_fn(card, index=i)

    print()  # trailing newline

if __name__ == "__main__":
    main()

