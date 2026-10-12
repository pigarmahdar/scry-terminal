"""Model Context Protocol (MCP) server for scryfall-local.

Provides a stdio JSON-RPC 2.0 interface for AI assistants (Claude Desktop,
Claude Code, Cursor, Windsurf, Open WebUI, Antigravity, etc.).
Pure standard library implementation with zero external dependencies.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

from . import state
from .api import resolve_fuzzy
from .project import slim_card, text_card
from .search import (
    apply_filters,
    search_cmc,
    search_color,
    search_general,
    search_keyword,
    search_name,
    search_oracle,
    search_text,
    sort_results,
)
from .store import DB_PATH, ORACLE_PATH, SCHEMA_VERSION, db_status, load_cards

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "scryfall-mcp"
SERVER_VERSION = "1.0.0"

# ── Tool Definitions ───────────────────────────────────────────────────

TOOLS = [
    {
        "name": "scryfall_oracle",
        "description": (
            "Look up canonical rules text, mana cost, card types, power/toughness, "
            "and keywords for a Magic: The Gathering card. Deduplicated across printings. "
            "This is the most token-efficient tool for 'what does this card do?'"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Card name, e.g. 'Sol Ring' or 'Lightning Bolt'",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of distinct cards to return if multiple match (default: 5)",
                    "default": 5,
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "scryfall_search",
        "description": (
            "Search Magic: The Gathering cards from the local offline database across "
            "name, oracle text, and type line. Note: Matches literal keywords/substrings "
            "(e.g. 'create a treasure token', 'destroy all creatures', 'flying'). Does not "
            "support natural language queries like 'creatures with flash' — use 'flash' "
            "with type='Creature' instead. Supports format legality, commander color identity "
            "(WUBRG letters or commander card name), and sorting."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search phrase (e.g. 'create a treasure token', 'destroy all creatures', 'flying')",
                },
                "search_type": {
                    "type": "string",
                    "enum": ["general", "name", "text", "type", "color", "cmc", "keyword"],
                    "description": "Which search mode to run (default: 'general')",
                    "default": "general",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of cards to return (default: 10)",
                    "default": 10,
                },
                "commander": {
                    "type": "string",
                    "description": (
                        "Optional commander constraint: either WUBRG color identity letters "
                        "(e.g. 'WG', 'UBR', 'C') or a commander card name (e.g. 'Kwain, Itinerant Meddler')"
                    ),
                },
                "legal": {
                    "type": "string",
                    "description": "Filter by format legality (e.g. 'commander', 'modern', 'standard', 'pauper', 'legacy')",
                },
                "sort": {
                    "type": "string",
                    "enum": ["name", "cmc", "price"],
                    "description": "Sort results by 'name', 'cmc', or 'price'",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "scryfall_fuzzy",
        "description": (
            "Look up a card by name with typo tolerance and candidate suggestions. "
            "Resolves misspellings and near-misses (e.g. 'sol rng' -> Sol Ring)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Card name, possibly misspelled or partial",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "scryfall_price",
        "description": (
            "Look up market prices (USD, EUR, TIX, and foil/etched variants) for printings "
            "of a card name, sorted most-expensive first."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Card name to check prices for",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of printings to return (default: 5)",
                    "default": 5,
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "scryfall_doctor",
        "description": (
            "Check local SQLite index health, staleness, schema version, and row parity."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "scryfall_deck",
        "description": (
            "Analyze and audit a Magic: The Gathering decklist (.txt or text lines). "
            "Returns authoritative ground-truth diagnostics across 4 dimensions: "
            "1) Vitals & Mana Health (Frank Karsten colored sources vs pip demands, early hurdles), "
            "2) Table Dynamic (Self-focused vs Targeted vs Symmetrical table influence), "
            "3) Engine Balance (Fuel enablers vs Payoff reward listeners ratio), "
            "4) Deck Heritage (Classic Pre-2003, Modern 2003-2014, Contemporary 2015+), "
            "along with format legality and commander color identity verification."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "deck": {
                    "type": "string",
                    "description": "Decklist as multi-line string or file path",
                },
                "format": {
                    "type": "string",
                    "description": "Target format, e.g. 'commander', 'modern', 'standard' (default: 'commander')",
                    "default": "commander",
                },
                "commander": {
                    "type": "string",
                    "description": "Optional commander card name override",
                },
            },
            "required": ["deck"],
        },
    },
]


# ── Tool Implementations ───────────────────────────────────────────────

def _tool_oracle(args: dict[str, Any]) -> str:
    name = str(args.get("name", "")).strip()
    if not name:
        raise ValueError("Parameter 'name' cannot be empty.")
    limit = int(args.get("limit", 5))

    load_cards()
    records, total, mode = search_oracle(name, limit=limit)
    out = []
    for card, printings in records:
        c_proj = text_card(card)
        if printings > 1:
            c_proj["printings"] = printings
        out.append(c_proj)

    payload = {
        "query": name,
        "match_mode": mode,
        "total_matches": total,
        "cards": out,
    }
    return json.dumps(payload, indent=2)


def _tool_search(args: dict[str, Any]) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        raise ValueError("Parameter 'query' cannot be empty.")

    search_type = str(args.get("search_type", "general")).lower()
    limit = int(args.get("limit", 10))
    commander = args.get("commander")
    legal = args.get("legal")
    sort_field = args.get("sort")

    load_cards()

    if search_type == "name":
        results = search_name(query)
    elif search_type == "text":
        results = search_text(query)
    elif search_type == "type":
        results = search_type(query)
    elif search_type == "color":
        results = search_color(query)
    elif search_type == "cmc":
        results = search_cmc(query)
    elif search_type == "keyword":
        results = search_keyword(query)
    else:
        results = search_general(query)

    filtered = apply_filters(results, commander=commander, legal=legal)
    if sort_field:
        filtered = sort_results(filtered, sort_field)

    total = len(filtered)
    shown = filtered[:limit] if limit else filtered
    cards = [slim_card(c) for c in shown]

    payload = {
        "query": query,
        "search_type": search_type,
        "total_matches": total,
        "shown_matches": len(cards),
        "cards": cards,
    }
    return json.dumps(payload, indent=2)


def _tool_fuzzy(args: dict[str, Any]) -> str:
    name = str(args.get("name", "")).strip()
    if not name:
        raise ValueError("Parameter 'name' cannot be empty.")

    load_cards()
    resolved = resolve_fuzzy(name)

    payload = {
        "query": name,
        "match": resolved.get("match"),
        "candidates": resolved.get("candidates", []),
    }
    return json.dumps(payload, indent=2)


def _tool_price(args: dict[str, Any]) -> str:
    name = str(args.get("name", "")).strip()
    if not name:
        raise ValueError("Parameter 'name' cannot be empty.")
    limit = int(args.get("limit", 5))

    load_cards()
    results = search_name(name)
    sorted_cards = sort_results(results, "price")
    cards = [slim_card(c) for c in sorted_cards[:limit]]

    payload = {
        "query": name,
        "total_matches": len(results),
        "cards": cards,
    }
    return json.dumps(payload, indent=2)


def _tool_doctor(args: dict[str, Any]) -> str:
    is_stale, reason = db_status()
    payload = {
        "db_path": DB_PATH,
        "oracle_path": ORACLE_PATH,
        "schema_version": SCHEMA_VERSION,
        "db_exists": os.path.exists(DB_PATH),
        "source_exists": os.path.exists(ORACLE_PATH),
        "is_stale": is_stale,
        "status_reason": reason,
        "db_mode_active": bool(state.DB_MODE),
    }
    if os.path.exists(DB_PATH) and state.DB is not None:
        try:
            row = state.DB.execute("SELECT count(*) FROM cards").fetchone()
            payload["indexed_cards"] = row[0] if row else 0
        except Exception:  # noqa: BLE001
            payload["indexed_cards"] = None
    return json.dumps(payload, indent=2)


def _tool_deck(args: dict[str, Any]) -> str:
    raw_deck = str(args.get("deck", "")).strip()
    if not raw_deck:
        raise ValueError("Parameter 'deck' cannot be empty.")
    target_format = str(args.get("format", "commander"))
    commander_override = args.get("commander")

    deck_content = raw_deck
    deck_name = "Decklist"
    expanded = os.path.expanduser(raw_deck)
    if "\n" not in raw_deck and os.path.exists(expanded):
        deck_name = raw_deck
        with open(expanded, "r", encoding="utf-8") as f:
            deck_content = f.read()

    load_cards()
    from .deck import run_deck_analysis
    res = run_deck_analysis(deck_content, deck_name=deck_name, target_format=target_format,
                            commander_override=commander_override)
    return json.dumps(res, indent=2, ensure_ascii=False)


TOOL_DISPATCH = {
    "scryfall_oracle": _tool_oracle,
    "scryfall_search": _tool_search,
    "scryfall_fuzzy": _tool_fuzzy,
    "scryfall_price": _tool_price,
    "scryfall_doctor": _tool_doctor,
    "scryfall_deck": _tool_deck,
}


# ── JSON-RPC 2.0 Dispatcher ───────────────────────────────────────────

def _format_response(req_id: Any, result: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": result,
    }


def _format_error(req_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": err,
    }


def handle_request(req: dict[str, Any]) -> dict[str, Any] | None:
    """Process a single JSON-RPC message. Returns response dict or None for notifications."""
    if not isinstance(req, dict):
        return _format_error(None, -32600, "Invalid Request: expected JSON object")

    req_id = req.get("id")
    method = req.get("method")
    params = req.get("params", {})

    if not isinstance(method, str):
        return _format_error(req_id, -32600, "Invalid Request: 'method' must be a string")

    # Notifications (no id)
    is_notification = "id" not in req

    if method == "initialize":
        return _format_response(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "tools": {
                    "listChanged": False,
                },
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
            },
        })

    if method in ("notifications/initialized", "initialized"):
        # Client notifying that initialization is complete
        return None

    if method == "ping":
        return _format_response(req_id, {})

    if method == "tools/list":
        return _format_response(req_id, {
            "tools": TOOLS,
        })

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        handler = TOOL_DISPATCH.get(tool_name)
        if not handler:
            return _format_response(req_id, {
                "content": [
                    {
                        "type": "text",
                        "text": f"Unknown tool: '{tool_name}'",
                    }
                ],
                "isError": True,
            })

        try:
            result_text = handler(arguments)
            return _format_response(req_id, {
                "content": [
                    {
                        "type": "text",
                        "text": result_text,
                    }
                ],
                "isError": False,
            })
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"scryfall-mcp error in {tool_name}: {e}\n")
            return _format_response(req_id, {
                "content": [
                    {
                        "type": "text",
                        "text": f"Error executing tool '{tool_name}': {e!s}",
                    }
                ],
                "isError": True,
            })

    if is_notification:
        return None

    return _format_error(req_id, -32601, f"Method not found: '{method}'")


def run_mcp_server():
    """Main stdio loop reading JSON-RPC 2.0 lines from stdin."""
    # Ensure stdout only carries pure JSON-RPC output; machine mode suppresses formatting
    state.MODE = "json"

    # Pre-open cards database so initial tools/call is warm
    try:
        load_cards()
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"scryfall-mcp: initial load_cards failed ({e}), will retry per query\n")

    sys.stderr.write(f"scryfall-mcp server v{SERVER_VERSION} listening on stdio\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            resp = _format_error(None, -32700, f"Parse error: {e!s}")
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
            continue

        resp = handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    run_mcp_server()
