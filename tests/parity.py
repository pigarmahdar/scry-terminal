#!/usr/bin/env python3
"""DB-vs-JSONL parity harness (design doc §5, Stage 1 acceptance gate).

For each query it runs the search twice in one process — once with the SQLite
sidecar serving results, once with the legacy full-scan path — and compares the
results as ORDERED LISTS of slim dicts, not sets. Ordered comparison is the
point: --limit is applied after sort_results (a stable sort), so any divergence
in cache order silently changes which cards survive a limit.

Also probes the cases the design doc flagged as regression risks:
  - 1- and 2-character substring queries (trigram returns ZERO rows below 3)
  - duplicate names (223 are genuinely duplicated; multi-row must be preserved)
  - punctuation/accent substrings (trigram tokenizer behaviour)
  - LIKE metacharacters in queries
  - --commander / --legal filters, which read color_identity

Usage: python3 tests/parity.py [-v] [pattern]
Exit code 0 = full parity, 1 = mismatches.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# Import the package normally — no path loading, no exec_module tricks.
# (Stage 1's parity harness had to load the single-file script by path because
#  it wasn't importable; the package split removed that friction.)
sys.path.insert(0, REPO)
import scryfall_cli as cli            # noqa: E402
from scryfall_cli import state        # noqa: E402  (shared mutable state)


def load_both():
    """Populate CARDS (legacy) and DB (index) in one process."""
    state.FORCE_NO_DB = True
    state.DB_MODE = False
    state.DB = None
    state.CARDS = []
    cli.load_cards()
    assert state.CARDS, "legacy path loaded no cards"
    legacy_counts = len(state.CARDS)

    conn = cli.open_db()
    assert conn is not None, "could not open sidecar for parity run"
    state.DB = conn
    return legacy_counts
def run_pair(fn_name, *args, **kwargs):
    """Call cli.<fn> on both paths, returning (legacy_result, db_result)."""
    fn = getattr(cli, fn_name)

    # Legacy first
    state.DB_MODE = False
    legacy = list(fn(*args, **kwargs))

    # DB second
    state.DB_MODE = True
    db = list(fn(*args, **kwargs))
    return legacy, db


def project(cards):
    """Normalise to the fields any output layer consumes, in order.

    Both paths ultimately feed slim_card(), so comparing slim projections is
    comparing what the user/agent actually sees. Legacy cards carry extra raw
    Scryfall fields that never reach output; projecting hides those.
    """
    return [cli.slim_card(c) for c in cards]


class Result:
    def __init__(self, name, ok, detail=""):
        self.name, self.ok, self.detail = name, ok, detail


def compare(case, fn_name, args, kwargs=None, expect_nonempty=True):
    kwargs = kwargs or {}
    legacy, db = run_pair(fn_name, *args, **kwargs)
    lp, dp = project(legacy), project(db)
    if lp != dp:
        # Describe the first divergence for the failure message
        detail = describe_diff(lp, dp, legacy, db)
        return Result(case, False, detail)
    if expect_nonempty and not lp:
        return Result(case, True, "both empty (suspicious: query matched nothing)")
    return Result(case, True, "%d rows" % len(lp))


def describe_diff(lp, dp, legacy, db):
    if len(lp) != len(dp):
        return "count %d (jsonl) vs %d (db)" % (len(lp), len(dp))
    for i, (a, b) in enumerate(zip(lp, dp)):
        if a != b:
            keys = [k for k in set(list(a) + list(b)) if a.get(k) != b.get(k)]
            return ("order/content differ at index %d: %r vs %r (fields %s)"
                    % (i, a.get("name"), b.get("name"), sorted(keys)))
    return "unknown difference"


# ── Case table ──────────────────────────────────────────────────────────
NAME_QUERIES = [
    "sol ring", "Sol Ring", "ring", "lotus", "black lotus", "fetch",
    "land", "dragon", "jace", "karn", "urza", "misty", "moat",
    # 1-2 char: the trigram silent-zero trap (§3.3)
    "a", "b", "e", "i", "o", "u", "so", "ri", "ng", "th", "xx", "z",
    # punctuation / accents (trigram tokeniser)
    "sisters'", "kamahl,", "ömnoms", "grist,", "d'vir", "tomik",
    # LIKE metacharacters
    "100%", "underworld_", "%", "_", "a%b",
    # quotes and whitespace
    '"sol ring"', "sol  ring", " sol ring ", "",
    # duplicates by name (223 exist)
    "elemental", "spirit", "soldier", "bird", "insect",
    # non-english rows
    "murgish",
]

TEXT_QUERIES = [
    "devious", "counter target spell", "create a treasure token",
    "flying", "when this dies", "whenever", "protection",
    "a", "is", "the", "ing", "'s", "%", "_", "regenerate",
    "extort", "kick", "manifest", "delve", "conjure",
]

TYPE_QUERIES = [
    "creature", "instant", "enchantment", "artifact creature",
    "legendary", "planeswalker", "sorcery", "land", "token",
    "a", "e", "ous", "ic", "walk", "saproling", "equipment",
]

KEYWORD_QUERIES = [
    "flying", "trample", "flash", "haste", "deathtouch", "vigilance",
    "hexproof", "menace", "skulk", "intimidate", "first strike",
    "hop", "ha", "y", "ing", "fight",
]

CMC_EXPRS = ["3", "=3", "<=3", ">=3", "0", "<=1", ">=7", "2.5", "-1", "abc", ""]

COLOR_ARGS = ["W", "U", "B", "R", "G", "WU", "WG", "BGR", "WUBRG", "wu",
              "WUB", "RB", "BG", "GU", "BW", "Z", "WBZ", ""]

GENERAL_QUERIES = [
    "fetch land", "counter", "devious", "a", "is", "treasure",
    "creature flying", "sol ring", "'", "%", "discard", "draw a card",
]

FUZZY_RESOLVE = [  # exercises _resolve_card's exact/partial/typo steps (offline part)
    "sol rng", "jac bele", "black lotus", "ancestor s chosen",
    "molten rn", "karn scion urza", "grist the hunger tide",
]

ORACLE_QUERIES = [  # `oracle` groups by canonical text; exact path grouped, substr flat
    "sol ring", "Sol Ring", "elemental", "sheep", "golem", "spirit", "bird",
    "bolt", "ring", "land", "dragon", "lightening bolt", "murgish",
    # 1-2 char: substr blow-up + the trigram silent-zero trap (§3.3)
    "a", "so", "xx",
    # punctuation / accents / LIKE metacharacters
    "sisters'", "kamahl,", "ömnoms", "d'vir", "100%", "underworld_", "%", "_",
    # quotes and whitespace
    '"sol ring"', "sol  ring", " sol ring ", "",
]


def compare_oracle(case, query):
    """`search_oracle` returns (records, total, mode); compare all three in order."""
    fn = cli.search_oracle

    state.DB_MODE = False
    l_recs, l_tot, l_mode = fn(query)
    state.DB_MODE = True
    d_recs, d_tot, d_mode = fn(query)

    lp = [(cli.text_card(c), n) for c, n in l_recs]
    dp = [(cli.text_card(c), n) for c, n in d_recs]
    if lp != dp:
        return Result(case, False, describe_diff([p[0] for p in lp], [p[0] for p in dp],
                                                  l_recs, d_recs))
    if [n for _, n in lp] != [n for _, n in dp]:
        return Result(case, False, "printing counts differ")
    if l_tot != d_tot or l_mode != d_mode:
        return Result(case, False, "total/mode differ: %s/%s vs %s/%s"
                      % (l_tot, l_mode, d_tot, d_mode))
    if not lp:
        return Result(case, True, "both empty (suspicious: query matched nothing)")
    return Result(case, True, "%d groups / %d printings (%s)"
                  % (len(lp), sum(n for _, n in lp), l_mode))


def main():
    verbose = "-v" in sys.argv
    pattern = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
    total_lines = load_both()
    print("legacy rows: %s   index: ready\n" % format(total_lines, ","))

    results = []

    for q in NAME_QUERIES:
        results.append(compare("name %r (substr)" % q, "search_name", (q,)))
        results.append(compare("name %r (exact)" % q, "search_name", (q,), {"exact": True}))
    for q in TEXT_QUERIES:
        results.append(compare("text %r" % q, "search_text", (q,)))
    for q in TYPE_QUERIES:
        results.append(compare("type %r" % q, "search_type", (q,)))
    for q in KEYWORD_QUERIES:
        results.append(compare("keyword %r" % q, "search_keyword", (q,)))
    for e in CMC_EXPRS:
        try:
            a = cli.search_cmc(e)
            err_a = None
        except ValueError as ex:
            a, err_a = None, str(ex)
        state.DB_MODE = True
        try:
            b = cli.search_cmc(e)
            err_b = None
        except ValueError as ex:
            b, err_b = None, str(ex)
        ok = (err_a is None) == (err_b is None)
        if ok and err_a is None:
            ok = project(a) == project(b)
        elif ok:
            ok = err_a == err_b
        results.append(Result("cmc %r" % e, ok,
                              "" if ok else "jsonl err=%r db err=%r counts %s/%s"
                              % (err_a, err_b, len(a or []), len(b or []))))
    for col in COLOR_ARGS:
        try:
            a = cli.search_color(col)
            ea = None
        except ValueError as ex:
            a, ea = None, str(ex)
        state.DB_MODE = True
        try:
            b = cli.search_color(col)
            eb = None
        except ValueError as ex:
            b, eb = None, str(ex)
        ok = (ea is None) == (eb is None) and (project(a) == project(b) if ea is None else ea == eb)
        results.append(Result("color %r" % col, ok,
                              "" if ok else "jsonl err=%r db err=%r" % (ea, eb)))
    for q in GENERAL_QUERIES:
        results.append(compare("search %r" % q, "search_general", (q,)))
    for q in ORACLE_QUERIES:
        results.append(compare_oracle("oracle %r" % q, q))

    # random: same shape + membership, not identity (it is random)
    state.DB_MODE = False
    r_leg = cli.search_random()
    state.DB_MODE = True
    r_db = cli.search_random()
    leg_names = {c.get("name") for c in state.CARDS}
    ok = (len(r_db) == 1 and isinstance(r_db[0], dict)
          and r_db[0].get("name") in leg_names
          and set(r_db[0]) == set(cli.slim_card(r_leg[0])))
    results.append(Result("random shape/membership", ok,
                          "" if ok else "got %r" % (r_db[:1],)))

    # _resolve_card offline behaviour (exact/partial/typo candidate pools).
    # Network step is neutralised so this stays hermetic and fast.
    from scryfall_cli import api as _api
    orig_api = _api.scryfall_fuzzy
    _api.scryfall_fuzzy = lambda name: None
    try:
        for q in FUZZY_RESOLVE:
            state.DB_MODE = False
            ca, sa = cli._resolve_card(q)
            state.DB_MODE = True
            cb, sb = cli._resolve_card(q)
            na = (ca or {}).get("name")
            nb = (cb or {}).get("name")
            ok = na == nb and abs(sa - sb) < 1e-9
            results.append(Result("resolve %r" % q, ok,
                                  "" if ok else "jsonl %r(%.3f) vs db %r(%.3f)"
                                  % (na, sa, nb, sb)))
    finally:
        _api.scryfall_fuzzy = orig_api

    fails = [r for r in results if not r.ok]
    warns = [r for r in results if r.ok and "suspicious" in r.detail]
    for r in results:
        if verbose or not r.ok or ("suspicious" in r.detail):
            mark = "ok  " if r.ok else "FAIL"
            print("%s %-34s %s" % (mark, r.name[:34], r.detail))
    print("\n%d checks: %d passed, %d failed, %d empty-on-both"
          % (len(results), len(results) - len(fails), len(fails), len(warns)))
    if fails:
        print("\nMISMATCHES:")
        for r in fails:
            print("  %-36s %s" % (r.name[:36], r.detail))
        return 1
    print("\nFull parity between SQLite index and JSONL scan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
