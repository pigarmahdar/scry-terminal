# Argument parsing, command routing, maintenance handlers, main().
# This is the only module that may call sys.exit() for user-facing errors (the
# library modules above it raise/return instead), and the only one that reads
# sys.argv. The usage docstring below is printed verbatim by `scry` with no
# args, exactly as the single-file script did.
"""
scry (Scry Terminal) — Local MTG card search from your Oracle cache.
Usage:
  scry <command> <query> [options]

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
  deck <file>         Analyze a decklist (mana curve, colors, engines, format audit)
  update              Update the Oracle cache from Scryfall
  completion <shell>  Generate shell completion script (bash, zsh, fish)
  version             Show version
  help                Show this help message and exit

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
                      piped or redirected. Env override: SCRY_FORMAT=<fmt>.
                      NO_COLOR=1 strips ANSI styling from pretty output.
  --version, -v       Show version and exit
  --help, -h          Show this help message and exit

Machine-readable output (json/jsonl/csv/tsv):
  When stdout is not a terminal — e.g. an LLM harness, script, or pipe — the
  tool emits compact JSONL automatically, one card per line, with stable fields:
  name, lang, mana_cost, cmc, type_line, colors, power, toughness, oracle_text,
  keywords, legalities, prices, image_uris, scryfall_uri. Warnings and status
  messages go to stderr so stdout stays pure data. 'fuzzy' becomes
  non-interactive: it returns the best match plus candidate suggestions instead
  of prompting. Pass --pretty to force human output even when piped.

Examples:
  scry name "Gilded Drake"
  scry text "create a treasure token"
  scry type "enchantment"
  scry color WG
  scry cmc <=3
  scry keyword flying
  scry random
  scry search "2 mana green creature"
  scry name "Sol Ring" --legal commander --limit 5
  scry oracle "Sol Ring"
  scry oracle "Elemental" --limit 999
  scry fuzzy "sol rng"
  scry fuzzy "jac bele"
  scry price "Sol Ring"
  scry price "treasure" --sort price
  scry image "Sol Ring"
  scry image "sol rng" --size large
  scry deck my_deck.txt
  scry search "counter target spell" --json | jq '.[].name'
  SCRY_FORMAT=json scry price "Force of Will"   # for agents/harnesses
"""

import json
import os
import sys

from . import __version__, state
from .api import SCRYFALL_API, handle_fuzzy  # noqa: F401
from .display import (
    display_card,
    display_deck_analysis,
    display_oracle_card,
    display_price_card,
    handle_image,
)
from .project import emit_records, emit_single, slim_card, text_card  # noqa: F401
from .search import (
    search_cmc,
    search_color,
    search_general,
    search_keyword,
    search_name,
    search_oracle,
    search_random,
    search_text,
    search_type,
)
from .state import (
    DB_PATH,
    ORACLE_PATH,
    SCHEMA_VERSION,
    _colors_enabled,
    c,
    fmt,
    machine_mode,
    resolve_format,
    warn,
)
from .store import (
    _sqlite_module,
    _sqlite_supports_fts5,
    build_db,
    db_status,
    load_cards,
)


# ── Parse arguments ─────────────────────────────────────────────────────
def parse_args(args):
    """Parse command line arguments into (command, query, options)."""
    command = None
    query_parts = []
    options = {"limit": 10, "commander": None, "legal": None, "exact": False, "sort": None,
               "size": None, "out": None, "border": None, "format": None, "commander_card": None,
               "help": False, "version": False}

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
        elif arg == "--commander-card" and i + 1 < len(args):
            options["commander_card"] = args[i + 1]
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
        elif arg == "--offline":
            options["offline"] = True
            i += 1
        elif arg in ("--version", "-v", "-V"):
            options["version"] = True
            i += 1
        elif arg in ("--help", "-h"):
            options["help"] = True
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

    try:
        _, _, free = shutil.disk_usage(cache_dir)
        free_mb = free / (1024 * 1024)
        if free_mb < 350:
            warn(f"Warning: Low disk space ({free_mb:.0f} MB available). Cache setup requires ~350 MB.")
    except Exception:
        pass

    gz_path = ORACLE_PATH + ".gz"
    gz_part = gz_path + ".part"
    backup_path = ORACLE_PATH + ".backup"

    # 1. Get the download URL
    warn("Fetching Scryfall bulk-data catalogue...")
    try:
        req = urllib.request.Request(
            "https://api.scryfall.com/bulk-data",
            headers={"User-Agent": "scry-terminal/1.0", "Accept": "application/json"},
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
            headers={"User-Agent": "scry-terminal/1.0"},
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            with open(gz_part, "wb") as f:
                shutil.copyfileobj(resp, f)
        os.replace(gz_part, gz_path)
    except KeyboardInterrupt:
        if os.path.exists(gz_part):
            try:
                os.remove(gz_part)
            except OSError:
                pass
        print("\n\n  Download cancelled.", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        if os.path.exists(gz_part):
            try:
                os.remove(gz_part)
            except OSError:
                pass
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

def handle_deck(query, options):
    load_cards()
    deck_content = ""
    deck_name = "Decklist"

    if query == "-" or (not query.strip() and not sys.stdin.isatty()):
        deck_content = sys.stdin.read()
        deck_name = "Standard Input (stdin)"
    elif query.strip():
        expanded = os.path.expanduser(query)
        if os.path.exists(expanded):
            deck_name = query
            with open(expanded, "r", encoding="utf-8") as f:
                deck_content = f.read()
        else:
            deck_content = query
            deck_name = "Inline Decklist"
    else:
        if machine_mode():
            emit_single({"error": "empty_decklist", "message": "No decklist file or input provided."})
        else:
            print('\n  ' + c('✗ No decklist file or input provided.', '1;31'))
            print("  Usage: scry deck <file> | cat deck.txt | scry deck\n")
        sys.exit(1)

    target_format = options.get("legal") or "commander"
    commander_override = options.get("commander_card")
    offline = options.get("offline", False)
    from .deck import run_deck_analysis
    res = run_deck_analysis(deck_content, deck_name=deck_name, target_format=target_format,
                            commander_override=commander_override, offline=offline)

    if machine_mode():
        json.dump(res, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        display_deck_analysis(res)

VALID_COMMANDS = {"name", "text", "type", "color", "cmc", "keyword", "fuzzy", "random",
                  "search", "price", "image", "update", "reindex", "doctor", "oracle", "mcp", "deck",
                  "completion", "version"}

# ── Index maintenance commands (Option C) ───────────────────────────────
def handle_reindex():
    """Rebuild the SQLite sidecar from the JSONL cache."""
    import time
    if not os.path.exists(ORACLE_PATH):
        warn("Oracle cache not found at %s — run 'scry update' first." % ORACLE_PATH)
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
                               " or 'scry reindex')"))

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
        print(f"  Try 'scry fuzzy \"{query}\"' for typo tolerance.\n")
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

    if options.get("help") or command == "help":
        print(__doc__)
        return

    # Resolve output format: flag > $SCRYFALL_FORMAT > TTY auto-detect
    state.MODE = resolve_format(options.get("format"))
    state.USE_COLOR = _colors_enabled(state.MODE)

    # Version
    if options.get("version") or command == "version":
        if machine_mode():
            emit_single({"version": __version__})
        else:
            print(f"scry {__version__}")
        return

    # Shell completion
    if command == "completion":
        from .completion import handle_completion
        handle_completion(query)
        return

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

    # MCP server (stdio JSON-RPC 2.0 loop)
    if command == "mcp":
        from .mcp import run_mcp_server
        run_mcp_server()
        return

    # Handle image command (uses API first, local cache as fallback)
    if command == "image":
        load_cards()
        handle_image(query, options)
        return

    # Handle deck command
    if command == "deck":
        handle_deck(query, options)
        return

    # Validate command (#4)
    if command and command not in VALID_COMMANDS:
        import difflib
        matches = difflib.get_close_matches(command, list(VALID_COMMANDS), n=1, cutoff=0.55)
        suggestion = matches[0] if matches else None
        full_query = (f"{command} {query}").strip()
        visible_commands = sorted(VALID_COMMANDS - {"update", "mcp", "completion", "version"})

        search_hint = f'scry search "{full_query}"'
        name_hint = f'scry name "{full_query}"'

        if machine_mode():
            payload = {
                "error": "unknown_command",
                "command": command,
                "valid_commands": visible_commands,
            }
            if suggestion:
                payload["suggestion"] = suggestion
            else:
                payload["suggestions"] = [search_hint, name_hint]
            emit_single(payload)
        else:
            print("\n  " + c(fmt("✗ Unknown command '{}'.", command), '1;31'))
            if suggestion:
                suggested_cmd = f"scry {suggestion}" + (f" \"{query}\"" if query else "")
                print(f"  Did you mean: {c(suggested_cmd, '1;32')}?")
            else:
                print("  Did you mean:")
                print(f"    {c(search_hint, '1;32')}  (search card text, name & types)")
                print(f"    {c(name_hint, '1;32')}    (search card name)")
            print(f"  Valid commands: {', '.join(visible_commands)}\n")
        sys.exit(1)

    # Guard empty queries (#1) — except random which needs no query
    if command != "random" and not query.strip():
        if machine_mode():
            emit_single({"error": "empty_query", "command": command})
        else:
            print('\n  ' + c('✗ No search query provided.', '1;31'))
            print(f"  Usage: scry {command} <query>\n")
        sys.exit(1)

    # Load cards
    load_cards()

    # Validate commander if specified
    if options["commander"]:
        try:
            from .search import _resolve_commander_identity
            _resolve_commander_identity(options["commander"])
        except ValueError as e:
            if machine_mode():
                emit_single({"error": "invalid_commander", "details": str(e)})
            else:
                print("\n  " + c(fmt("✗ Invalid commander: {}", e), '1;31'))
                print("  Usage: --commander WG | --commander 'Kwain, Itinerant Meddler'\n")
            sys.exit(1)

    limit = options["limit"]
    commander = options["commander"]
    legal = options["legal"]
    sort = options["sort"]
    if command == "price" and not sort:
        sort = "price"
        options["sort"] = "price"

    # Run search
    results = []
    if command == "name":
        results = search_name(query, exact=options["exact"], limit=limit,
                              commander=commander, legal=legal, sort=sort)
    elif command == "fuzzy":
        handle_fuzzy(query, options)
        return
    elif command == "text":
        results = search_text(query, limit=limit, commander=commander, legal=legal, sort=sort)
    elif command == "type":
        results = search_type(query, limit=limit, commander=commander, legal=legal, sort=sort)
    elif command == "color":
        try:
            results = search_color(query, limit=limit, commander=commander, legal=legal, sort=sort)
        except ValueError as e:
            if machine_mode():
                emit_single({"error": "invalid_color", "query": query, "details": str(e)})
            else:
                print("\n  " + c(fmt("✗ Invalid colour: {}", e), '1;31'))
                print("  Usage: scry color W | scry color WG | scry color BGR\n")
            sys.exit(1)
    elif command == "cmc":
        try:
            results = search_cmc(query, limit=limit, commander=commander, legal=legal, sort=sort)
        except ValueError as e:
            if machine_mode():
                emit_single({"error": "invalid_cmc", "query": query, "details": str(e)})
            else:
                print("\n  " + c(fmt("✗ Invalid mana value: {}", e), '1;31'))
                print("  Usage: scry cmc 3 | scry cmc <=3 | scry cmc >=3\n")
            sys.exit(1)
    elif command == "keyword":
        results = search_keyword(query, limit=limit, commander=commander, legal=legal, sort=sort)
    elif command == "oracle":
        # Own shape (records + printing counts, text-only projection), so it
        # bypasses the shared filter/sort/emit block below.
        _handle_oracle(query, options)
        return
    elif command == "random":
        results = search_random(commander=commander, legal=legal)
    elif command == "search":
        results = search_general(query, limit=limit, commander=commander, legal=legal, sort=sort)
    elif command == "price":
        results = search_name(query, exact=options["exact"], limit=limit,
                              commander=commander, legal=legal, sort=sort)
        if machine_mode():
            # Numeric prices for clean comparisons; keep every field from the projector
            for r in results:
                p = r.get("prices", {})
                for k in ("usd", "usd_foil", "usd_etched", "eur", "eur_foil", "tix"):
                    try:
                        p[k] = float(p[k]) if p.get(k) is not None else None
                    except (TypeError, ValueError):
                        p[k] = None

    total = getattr(results, "total", len(results))
    shown = len(results)

    # ── Machine-readable output: stdout is pure data, meta goes to stderr ──
    if machine_mode():
        if total > shown:
            warn(f"{shown} of {total} matches shown (use --limit {total} for all)")
        emit_records(results)
        return

    # Display
    if not results:
        print("\n  No cards found matching your search.")
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

