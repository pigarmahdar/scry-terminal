"""Scryfall HTTP API + offline name resolution (typos, partials, ambiguity).

`_resolve_card` is the shared brain behind `fuzzy` and `image`; it prefers the
API but falls back to local cache matching (exact -> partial -> typo), so it
stays useful offline. Network failures degrade to local results, never errors.
"""
import difflib
import json
import re

from . import state
from .state import c, warn, fmt, machine_mode
from .project import emit_single, slim_card
from .search import search_name
from .store import _hydrate, _fts_phrase
# display imports are local (inside handle_fuzzy) to avoid a module-level cycle:

# ── Scryfall API calls for fuzzy matching ─────────────────────────────
SCRYFALL_API = "https://api.scryfall.com"
USER_AGENT = "scryfall-cli/1.0"

def _api_get(endpoint, params=None):
    """Make a GET request to the Scryfall API. Returns parsed JSON or None."""
    import urllib.error
    import urllib.parse
    import urllib.request
    url = f"{SCRYFALL_API}{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Return the error body so callers can inspect it
        body = None
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            pass
        return {"error": True, "status": e.code, "body": body}
    except Exception as e:
        return {"error": True, "status": 0, "body": {"details": str(e)}}

def scryfall_fuzzy(name):
    """Fuzzy card lookup via /cards/named?fuzzy=. Returns card dict or error dict."""
    return _api_get("/cards/named", {"fuzzy": name})

def scryfall_autocomplete(query):
    """Autocomplete card names via /cards/autocomplete. Returns list of names or empty list."""
    result = _api_get("/cards/autocomplete", {"q": query})
    if result and not result.get("error") and "data" in result:
        return result["data"]
    return []

def _similarity(query, name):
    """Similarity score of query vs card name (0..1), with word-start bonus."""
    q, n = query.lower(), name.lower()
    ratio = difflib.SequenceMatcher(None, q, n).ratio()
    # Bonus if every query word lines up with a word in the name
    q_words = [w for w in re.split(r'\s+', q) if w]
    n_words = re.split(r'\s+', n)
    if q_words and all(any(nw.startswith(qw) or qw.startswith(nw) for nw in n_words) for qw in q_words):
        return max(ratio, 0.95)
    # Typo-tolerant: most query words found inside the name (e.g. "sol rng" → Sol Ring)
    contained = sum(1 for qw in q_words if len(qw) >= 2 and qw in n)
    if q_words and contained / len(q_words) >= 0.75:
        return max(ratio, 0.85)
    return ratio

def _normalize_name(name):
    """Lowercase, drop punctuation — used for closest-match comparison."""
    return re.sub(r"[\u2019'\".,!?|()/\\:-]", "", name.lower()).strip()

def _api_closest_match(card, query):
    """If the API returned an ambiguous result, pick the closest 'name' from its list."""
    candidates = card.get("name")
    if not isinstance(candidates, list) or not candidates:
        return None
    q_norm = _normalize_name(query)
    best = max(candidates, key=lambda c: _similarity(q_norm, _normalize_name(c)))
    return best if _similarity(q_norm, _normalize_name(best)) >= 0.6 else None

def _all_db_cards():
    """Every cached card as dicts, cache order. Used only by rare fallbacks."""
    return _hydrate(state.DB.execute("SELECT data FROM cards ORDER BY rid").fetchall())

def _typo_candidates(words):
    """Cards whose name shares a >=3-char substring with any of `words`.

    Union of per-word trigram matches — a superset of the difflib-ratio>=0.6
    set for words of that length, so it can over-select but never miss a
    candidate the old full scan would have found.
    """
    seen, out = set(), []
    for w in words:
        for row in state.DB.execute(
                "SELECT c.rid, c.data FROM cards c JOIN cards_ft f ON f.rowid = c.rid"
                " WHERE f.name MATCH ? ORDER BY c.rid", (_fts_phrase(w),)):
            if row[0] not in seen:
                seen.add(row[0])
                out.append(json.loads(row[1]))
    return out

def _resolve_card(query):
    """Resolve a card name to (card, similarity). Shared by image + machine paths."""
    # Step 1: Scryfall fuzzy lookup (handles typos + gives us image URLs)
    api_card = scryfall_fuzzy(query)
    if api_card and api_card.get("error"):
        api_card = None
    if api_card and isinstance(api_card.get("name"), list):
        # Ambiguous match — API returned several candidate names; pick the best one
        chosen = _api_closest_match(api_card, query)
        api_card = scryfall_fuzzy(chosen) if chosen else None
        if api_card and api_card.get("error"):
            api_card = None
    # Guard against unrelated printed-name coincidences (e.g. fuzzy "sol rng"
    # returning a Portuguese card whose printed name starts with "Sol R")
    if api_card and not isinstance(api_card.get("name"), list):
        if _similarity(query, api_card.get("name", "")) < 0.55:
            api_card = None

    # Step 2: Local cache candidates (exact match wins outright)
    local_exact = search_name(query, exact=True)
    local_partial = [] if local_exact else search_name(query)

    # Step 3: Typo tolerance — match each query word against cached card names
    local_typo = []
    if not local_exact and not local_partial and len(query.split()) >= 2:
        q_words = [w.lower() for w in re.split(r'\s+', query) if len(w) >= 2]
        # Candidate pool. Scoring all 38,708 names with difflib measured 778 ms,
        # which alone would swamp a ~40 ms call, so under DB_MODE we first take
        # the union of per-word trigram matches (each word shares >= 3 chars with
        # a name word => it is in that word's trigram set => substring match on
        # the FTS index finds it). Words shorter than 3 chars can't be routed
        # through trigram, so any such word falls back to the full scan rather
        # than risking a missed candidate — correctness over speed here.
        if state.DB_MODE and q_words and all(len(w) >= 3 for w in q_words):
            pool = _typo_candidates(q_words)
        else:
            pool = state.CARDS if not state.DB_MODE else _all_db_cards()
        for card in pool:
            n_words = re.split(r'\s+', card.get("name", "").lower())
            hits = sum(1 for qw in q_words
                       if any(difflib.SequenceMatcher(None, qw, nw).ratio() >= 0.6 for nw in n_words))
            if hits == len(q_words):
                local_typo.append(card)

    card = None
    sim = 0.0
    if local_exact:
        card = local_exact[0]
        sim = 1.0
    elif api_card and not isinstance(api_card.get("name"), list):
        sim = _similarity(query, api_card.get("name", ""))
        card = api_card
    elif local_typo:
        best = max(local_typo, key=lambda c: _similarity(query, c.get("name", "")))
        card = best
        sim = _similarity(query, best.get("name", ""))

    # Step 4: Fall back to the best partial match from the local cache
    if card is None and local_partial:
        best = max(local_partial, key=lambda c: _similarity(query, c.get("name", "")))
        card = best
        sim = _similarity(query, best.get("name", ""))

    return card, sim


# ── Fuzzy command handler (API-first; lives here because it drives the API) ──
def handle_fuzzy(query, options=None):
    """Fuzzy search: try fuzzy → if ambiguous/no match, autocomplete → pick → lookup.

    In machine mode (json/jsonl/csv/tsv) it is fully non-interactive: emits a
    single JSON object {query, match, candidates} instead of prompting with
    input(), which would hang an LLM harness forever.
    """
    from .display import display_card, display_api_card  # local: display imports api
    if not query:
        print("\n  Usage: scryfall fuzzy <card name>")
        return

    # Step 1: Try Scryfall fuzzy match
    if not machine_mode():
        print('\n  ' + c('Searching for:', '1') + ' \"' + query + '\"')
    result = scryfall_fuzzy(query)

    matched_name = None
    if result and not result.get("error"):
        name = result.get("name", "Unknown")
        if isinstance(name, str):
            # Sanity check: is the returned name actually similar to the query?
            ratio = difflib.SequenceMatcher(None, query.lower(), name.lower()).ratio()
            query_words = set(w.lower() for w in query.split() if len(w) >= 3)
            name_lower = name.lower()
            has_word_overlap = any(w in name_lower or name_lower.startswith(w[:4]) for w in query_words)

            if ratio >= 0.55 or has_word_overlap:
                matched_name = name
            else:
                # Fuzzy returned something unrelated — treat as no match
                if not machine_mode():
                    print("  " + c(fmt("~ Scryfall suggested '{}' but it doesn't match your query.", name), '1;33') + "\n")
        elif isinstance(name, list):
            # Ambiguous response — resolve to the closest candidate name
            chosen = _api_closest_match(result, query)
            if chosen:
                resolved = scryfall_fuzzy(chosen)
                if resolved and not resolved.get("error") and isinstance(resolved.get("name"), str):
                    result = resolved
                    matched_name = resolved["name"]

    # Step 2: Gather autocomplete suggestions (candidates)
    suggestions = []
    if matched_name is None and query.strip():
        # Scryfall's q= param treats leading "-" as negation; quote the query
        suggestions = scryfall_autocomplete('"' + query.strip('"') + '"')
    if matched_name is None and not suggestions:
        suggestions = scryfall_autocomplete(query)
        if not suggestions:
            words = [w for w in query.split() if len(w) >= 3]
            for word in words:
                suggestions = scryfall_autocomplete(word)
                if suggestions:
                    break

    # Step 2b: Local fallback — word-level typo matching against the cache
    # (rescues queries like "sol rng" / "jac bele" where Scryfall's own fuzzy
    # endpoint returns nothing useful)
    local_fallback_card = None
    if matched_name is None:
        candidate, sim = _resolve_card(query)
        if candidate is not None and sim >= 0.85:
            local_fallback_card = candidate

    # ── Machine mode: emit structured result, never prompt ──
    if machine_mode():
        card = None
        if local_fallback_card is not None:
            card = local_fallback_card
        elif matched_name:
            local = search_name(matched_name, exact=True)
            card = local[0] if local else (result if result and not result.get("error") else None)
        payload = {"query": query,
                   "match": slim_card(card) if card else None,
                   "candidates": suggestions[:10]}
        emit_single(payload)
        return

    if matched_name:
        print('  ' + c('✓ Found:', '1;32') + ' ' + matched_name + '\n')
        local = search_name(matched_name, exact=True)
        if local:
            display_card(local[0])
        else:
            display_api_card(result)
        return

    error_body = (result or {}).get("body", {}) or {}
    details = error_body.get("details", "")
    print('  ' + c('✗ No exact fuzzy match.', '1;31') + ' ' + details + '\n')

    if not suggestions:
        print("  No close matches found. Try a different spelling or use 'scryfall name' for partial search.")
        return

    # Step 3: Show suggestions and let user pick
    print("  " + c('Did you mean…', '1;36'))
    for i, name in enumerate(suggestions, 1):
        print(f"    [{i}] {name}")
    print(f"    [0] Cancel\n")

    try:
        choice = input("  Pick a number: ").strip()
        choice = int(choice)
    except (ValueError, EOFError):
        print("  Cancelled.")
        return

    if choice < 1 or choice > len(suggestions):
        print("  Cancelled.")
        return

    picked = suggestions[choice - 1]
    print('\n  ' + c('→ Looking up:', '1;32') + ' ' + picked + '\n')

    # Step 4: Lookup the picked card from local cache (exact)
    local = search_name(picked, exact=True)
    if local:
        display_card(local[0])
    else:
        # Fall back to API
        api_card = scryfall_fuzzy(picked)
        if api_card and not api_card.get("error"):
            display_api_card(api_card)
        else:
            print(f"  Could not find '{picked}' in cache or on Scryfall.")
