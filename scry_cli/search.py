"""Search functions: every query path, DB-served or legacy full scan.

Each returns a list of card dicts in cache order (DB_MODE) or cache order via
CARDS (legacy). ORDER BY rid mirrors JSONL line order so --limit tie-breaking
inside sort_results (a stable sort) picks the same survivors as before.
"""
import json
import random as rng

from . import state
from .project import text_card  # noqa: F401  (oracle display projection)
from .state import fmt, warn
from .store import (
    SearchResult,
    _any_substr_cards,
    _commander_clause,
    _hydrate,
    _legal_clause,
    _like_pattern,
    _query_cards,
    _substr_cards,
)

# ── Canonical card-text lookup (`oracle`) ────────────────────────────────
# Grouping key for "same canonical card". The roadmap assumed an `oracle_id`
# column would do this; measured against the real cache it cannot: oracle_id is
# 1:1 with rid (38,708 distinct values over 38,708 rows, max group size 1), so
# GROUP BY oracle_id is a no-op. This cache is oracle-scoped, not prints-scoped.
# What actually identifies a canonical card here is its rules text, so group on
# (name, oracle_text, type_line, mana_cost) — derived at query time from the
# stored JSON rather than promoted to a column, because ALTER+populate would
# cost a full 102 MB rebuild to store something computable in ~0.2 ms.
_ORACLE_SIG = ("lower(coalesce(json_extract(data, '$.name'), '')) || char(31)"
               "|| lower(coalesce(json_extract(data, '$.oracle_text'), '')) || char(31)"
               "|| lower(coalesce(json_extract(data, '$.type_line'), '')) || char(31)"
               "|| coalesce(json_extract(data, '$.mana_cost'), '')")

def _oracle_signature(card):
    """Python twin of _ORACLE_SIG, so --no-db groups identically to SQL."""
    return (str(card.get("name") or "").lower(),
            str(card.get("oracle_text") or "").lower(),
            str(card.get("type_line") or "").lower(),
            card.get("mana_cost") or "")

def search_oracle(query, limit=None):
    """Canonical cards for a name, deduplicated across identical printings.

    Exact-name match is the primary path and is grouped by rules-text
    signature; if nothing matches exactly it falls back to a substring scan
    (ungrouped — measured collapse gain there is 0, e.g. 'ring' 678 rows ->
    678 groups, so grouping would only add cost). Returns
    (records, total, mode) where records are (card, printing_count) pairs in
    cache order, `total` is the untruncated group/row count, and mode is
    "exact" | "substr".

    Grouping is lossless: audited across every name in the cache, no distinct
    oracle_text is ever hidden by it. Same-name cards that differ in text stay
    separate records (e.g. 'Elemental' -> 13 records over 31 printings).
    """
    q = query.lower().strip('"')
    if state.DB_MODE:
        rows = state.DB.execute(
            "SELECT min(rid) AS rid, count(*) AS n FROM cards"
            " WHERE name_lc = ? GROUP BY %s ORDER BY min(rid)" % _ORACLE_SIG,
            (q,)).fetchall()
        if not rows:
            from . import aliases
            canon = aliases.resolve_alias(q)
            if canon:
                rows = state.DB.execute(
                    "SELECT min(rid) AS rid, count(*) AS n FROM cards"
                    " WHERE name_lc = ? GROUP BY %s ORDER BY min(rid)" % _ORACLE_SIG,
                    (canon.lower(),)).fetchall()
        if rows:
            ids = [r[0] for r in (rows[:limit] if limit else rows)]
            hydrated = {h[0]: json.loads(h[1]) for h in state.DB.execute(
                "SELECT rid, data FROM cards WHERE rid IN (%s)"
                % ",".join("?" * len(ids)), ids)}
            return ([(hydrated[r[0]], r[1]) for r in rows[:limit] if r[0] in hydrated],
                    len(rows), "exact")
        # Substr fallback: ungrouped, and --limit pushed into SQL so a query like
        # `oracle a` (29,707 matches) does not hydrate thousands of discarded rows.
        # total still counts every match so the "N of M shown" notice stays honest.
        total = state.DB.execute(
            "SELECT count(*) FROM cards WHERE name_lc LIKE ? ESCAPE '\\'",
            (_like_pattern(q),)).fetchone()[0]
        sql = "SELECT data FROM cards WHERE name_lc LIKE ? ESCAPE '\\' ORDER BY rid"
        params = (_like_pattern(q),)
        if limit:
            sql += " LIMIT ?"
            params = params + (limit,)
        cards = [json.loads(r[0]) for r in state.DB.execute(sql, params).fetchall()]
        return ([(c, 1) for c in cards], total, "substr")

    # Legacy path: one pass over CARDS. Exact hits bucket by the same signature
    # the SQL uses; substring hits are kept flat (ungrouped), matching DB_MODE.
    exact = {}
    subs = []
    for i, card in enumerate(state.CARDS):
        name = str(card.get("name") or "").lower()
        if name == q:
            key = _oracle_signature(card)
            if key not in exact:
                exact[key] = [i, card, 0]
            exact[key][2] += 1
        elif q in name:
            subs.append((i, card))
    if not exact:
        from . import aliases
        canon = aliases.resolve_alias(q)
        if canon:
            canon_lc = canon.lower()
            for i, card in enumerate(state.CARDS):
                if str(card.get("name") or "").lower() == canon_lc:
                    key = _oracle_signature(card)
                    if key not in exact:
                        exact[key] = [i, card, 0]
                    exact[key][2] += 1
    if exact:
        ordered = sorted(exact.values(), key=lambda v: v[0])
        taken = ordered[:limit] if limit else ordered
        return ([(v[1], v[2]) for v in taken], len(ordered), "exact")
    ordered_subs = sorted(subs, key=lambda t: t[0])
    taken = ordered_subs[:limit] if limit else ordered_subs
    return ([(c, 1) for _, c in taken], len(ordered_subs), "substr")

# ── Search functions ────────────────────────────────────────────────────
# Each returns a list of card dicts in cache order, whether served from the
# sidecar (DB_MODE) or the legacy full-scan path. ORDER BY rid mirrors the
# JSONL line order so --limit tie-breaking inside sort_results (a stable sort)
# picks the same survivors as before.

def _legacy_finish(results, limit=None, commander=None, legal=None, sort=None):
    if commander or legal:
        results = apply_filters(results, commander=commander, legal=legal)
    if sort:
        results = sort_results(results, sort)
    total = len(results)
    shown = results[:limit] if limit is not None else results
    return SearchResult(shown, total=total)

def search_name(query, exact=False, limit=None, commander=None, legal=None, sort=None):
    query_lower = query.lower().strip('"')
    if state.DB_MODE:
        allowed = _resolve_commander_identity(commander) if commander else None
        if exact:
            res = _query_cards("cards c", ["c.name_lc = ?"], (query_lower,),
                               limit=limit, allowed_colors=allowed, legal=legal, sort=sort)
            if not res:
                from . import aliases
                canon = aliases.resolve_alias(query_lower)
                if canon:
                    res = _query_cards("cards c", ["c.name_lc = ?"], (canon.lower(),),
                                       limit=limit, allowed_colors=allowed, legal=legal, sort=sort)
            return res
        return _substr_cards("name", query_lower,
                             limit=limit, allowed_colors=allowed, legal=legal, sort=sort)
    results = []
    for card in state.CARDS:
        name = card.get("name", "").lower()
        if exact:
            if name == query_lower:
                results.append(card)
        else:
            if query_lower in name:
                results.append(card)
    if exact and not results:
        from . import aliases
        canon = aliases.resolve_alias(query_lower)
        if canon:
            for card in state.CARDS:
                if card.get("name", "").lower() == canon.lower():
                    results.append(card)
    return _legacy_finish(results, limit=limit, commander=commander, legal=legal, sort=sort)

def search_text(query, limit=None, commander=None, legal=None, sort=None):
    query_lower = query.lower()
    if state.DB_MODE:
        allowed = _resolve_commander_identity(commander) if commander else None
        return _substr_cards("oracle_text", query_lower,
                             limit=limit, allowed_colors=allowed, legal=legal, sort=sort)
    results = []
    for card in state.CARDS:
        oracle = card.get("oracle_text", "").lower()
        if query_lower in oracle:
            results.append(card)
    return _legacy_finish(results, limit=limit, commander=commander, legal=legal, sort=sort)

def search_type(query, limit=None, commander=None, legal=None, sort=None):
    query_lower = query.lower()
    if state.DB_MODE:
        allowed = _resolve_commander_identity(commander) if commander else None
        return _substr_cards("type_line", query_lower,
                             limit=limit, allowed_colors=allowed, legal=legal, sort=sort)
    results = []
    for card in state.CARDS:
        type_line = card.get("type_line", "").lower()
        if query_lower in type_line:
            results.append(card)
    return _legacy_finish(results, limit=limit, commander=commander, legal=legal, sort=sort)

def search_color(colors, limit=None, commander=None, legal=None, sort=None):
    """Search by colour identity. Accepts any combination of WUBRG letters.

    Raises ValueError on characters outside WUBRG so the caller can report
    a proper input-validation error instead of silently returning nothing.
    """
    colors_upper = set(colors.upper())
    invalid = colors_upper - set("WUBRG")
    if invalid:
        raise ValueError(
            f"invalid colour letter(s): {', '.join(sorted(invalid))}. "
            "Use only W, U, B, R, G (e.g. WG, BGR)."
        )
    if state.DB_MODE:
        allowed = _resolve_commander_identity(commander) if commander else None
        if not colors_upper:
            # Empty set is a subset of every colour identity (legacy semantics).
            return _query_cards("cards c", [], (),
                                limit=limit, allowed_colors=allowed, legal=legal, sort=sort)
        subs = ["c.rid IN (SELECT rid FROM colors WHERE color = ?)"] * len(colors_upper)
        return _query_cards("cards c", subs, tuple(sorted(colors_upper)),
                            limit=limit, allowed_colors=allowed, legal=legal, sort=sort)
    results = []
    for card in state.CARDS:
        card_colors = set(card.get("color_identity", []))
        if colors_upper.issubset(card_colors):
            results.append(card)
    return _legacy_finish(results, limit=limit, commander=commander, legal=legal, sort=sort)

def search_cmc(expr, limit=None, commander=None, legal=None, sort=None):
    """Search by CMC. Supports: =3, <=3, >=3, or just a number.

    Raises ValueError on an unparseable expression so the caller can report
    a proper input-validation error instead of silently returning nothing.
    """
    expr = expr.strip()

    if expr.startswith("<="):
        op, val_str = "<=", expr[2:]
    elif expr.startswith(">="):
        op, val_str = ">=", expr[2:]
    elif expr.startswith("="):
        op, val_str = "=", expr[1:]
    else:
        op, val_str = "=", expr

    try:
        val = float(val_str)
    except ValueError:
        raise ValueError(
            f"not a number: '{val_str.strip() or expr}'. "
            "Use an exact value (3), a comparison (<=3, >=3), or '=3'."
        )

    if val < 0:
        raise ValueError(f"mana value cannot be negative: {val}")

    if state.DB_MODE:
        allowed = _resolve_commander_identity(commander) if commander else None
        col_op = {"<=": "<=", ">=": ">=", "=": "="}[op]
        return _query_cards("cards c", [f"c.cmc {col_op} ?"], (val,),
                            limit=limit, allowed_colors=allowed, legal=legal, sort=sort)

    if op == "<=":
        results = [c for c in state.CARDS if c.get("cmc", 99) <= val]
    elif op == ">=":
        results = [c for c in state.CARDS if c.get("cmc", 0) >= val]
    else:
        results = [c for c in state.CARDS if c.get("cmc", -1) == val]
    return _legacy_finish(results, limit=limit, commander=commander, legal=legal, sort=sort)

def search_keyword(query, limit=None, commander=None, legal=None, sort=None):
    query_lower = query.lower()
    if state.DB_MODE:
        allowed = _resolve_commander_identity(commander) if commander else None
        clause = ("EXISTS (SELECT 1 FROM json_each(c.data, '$.keywords') j"
                  " WHERE lower(j.value) LIKE ? ESCAPE '\\')")
        return _query_cards("cards c", [clause], (_like_pattern(query_lower),),
                            limit=limit, allowed_colors=allowed, legal=legal, sort=sort)
    results = []
    for card in state.CARDS:
        keywords = [k.lower() for k in card.get("keywords", [])]
        if any(query_lower in k for k in keywords):
            results.append(card)
    return _legacy_finish(results, limit=limit, commander=commander, legal=legal, sort=sort)

def search_general(query, limit=None, commander=None, legal=None, sort=None):
    """Search across name, oracle text, and type line."""
    query_lower = query.lower()
    if state.DB_MODE:
        allowed = _resolve_commander_identity(commander) if commander else None
        res = _any_substr_cards(query_lower, limit=limit, allowed_colors=allowed, legal=legal, sort=sort)
        if not res:
            from . import aliases
            canon = aliases.resolve_alias(query)
            if canon:
                return _any_substr_cards(canon.lower(), limit=limit, allowed_colors=allowed, legal=legal, sort=sort)
        return res
    results = []
    seen = set()
    for card in state.CARDS:
        card_id = card.get("id", "")
        if card_id in seen:
            continue
        name = card.get("name", "").lower()
        oracle = card.get("oracle_text", "").lower()
        type_line = card.get("type_line", "").lower()
        if query_lower in name or query_lower in oracle or query_lower in type_line:
            results.append(card)
            seen.add(card_id)
    if not results:
        from . import aliases
        canon = aliases.resolve_alias(query)
        if canon:
            canon_lower = canon.lower()
            for card in state.CARDS:
                card_id = card.get("id", "")
                if card_id in seen:
                    continue
                name = card.get("name", "").lower()
                oracle = card.get("oracle_text", "").lower()
                type_line = card.get("type_line", "").lower()
                if canon_lower in name or canon_lower in oracle or canon_lower in type_line:
                    results.append(card)
                    seen.add(card_id)
    return _legacy_finish(results, limit=limit, commander=commander, legal=legal, sort=sort)

def search_random(commander=None, legal=None):
    if state.DB_MODE:
        allowed = _resolve_commander_identity(commander) if commander else None
        where_parts = []
        params = []
        l_clause, l_params = _legal_clause(legal)
        if l_clause:
            where_parts.append(l_clause)
            params.extend(l_params)
        c_clause, c_params = _commander_clause(allowed)
        if c_clause:
            where_parts.append(c_clause)
            params.extend(c_params)
        where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
        sql = f"SELECT c.data FROM cards c{where_sql} ORDER BY RANDOM() LIMIT 1"
        row = state.DB.execute(sql, params).fetchone()
        return SearchResult(_hydrate([row]) if row else [], total=1 if row else 0)
    cards = state.CARDS
    if commander or legal:
        cards = apply_filters(cards, commander=commander, legal=legal)
    return SearchResult([rng.choice(cards)] if cards else [], total=1 if cards else 0)

# ── Apply filters ───────────────────────────────────────────────────────
def _resolve_commander_identity(commander):
    """Resolve a commander constraint to a set of allowed color identity letters (WUBRG).

    Accepts:
      - WUBRG color identity code (e.g., 'WG', 'UBR', 'WUBRG', 'C' for colorless)
      - Commander card name (e.g., 'Kwain, Itinerant Meddler', 'Atraxa, Praetors\' Voice')

    Raises ValueError if input cannot be resolved to a valid color identity or card.
    """
    if not commander or not str(commander).strip():
        return set()

    c_str = str(commander).strip()
    c_upper = c_str.upper()

    # Check for direct WUBRGC color identity string (e.g. 'WG', 'UBR', 'C')
    if len(c_upper) <= 5 and set(c_upper).issubset({"W", "U", "B", "R", "G", "C"}):
        return set(c_upper) - {"C"}

    # Attempt to resolve as card name from local cache
    exact = search_name(c_str, exact=True)
    if exact:
        return set(exact[0].get("color_identity", []))

    partial = search_name(c_str, exact=False)
    if partial:
        return set(partial[0].get("color_identity", []))

    # Try typo/fuzzy resolution via api._resolve_card if available
    try:
        from .api import _resolve_card
        card, sim = _resolve_card(c_str)
        if card and sim >= 0.7:
            return set(card.get("color_identity", []))
    except Exception:
        pass

    raise ValueError(
        f"Invalid commander '{commander}': must be WUBRG color letters (e.g. 'WG', 'UBR') or a known card name."
    )


def apply_filters(results, commander=None, legal=None):
    if commander:
        allowed = _resolve_commander_identity(commander)
        results = [c for c in results if set(c.get("color_identity", [])).issubset(allowed)]
    if legal:
        legal = legal.lower()
        results = [c for c in results if c.get("legalities", {}).get(legal) == "legal"]
    return results

def sort_results(results, sort_key):
    """Sort results by the given key."""
    if sort_key == "name":
        return sorted(results, key=lambda c: c.get("name", "").lower())
    elif sort_key == "cmc":
        return sorted(results, key=lambda c: c.get("cmc", 0))
    elif sort_key == "price":
        def usd_val(c):
            p = c.get("prices", {}).get("usd")
            return float(p) if p else 0
        return sorted(results, key=usd_val, reverse=True)
    else:
        warn(fmt("⚠ Unknown sort field '{}'. Use 'name', 'cmc', or 'price'.", sort_key))
        return results
