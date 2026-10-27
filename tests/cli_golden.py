#!/usr/bin/env python3
"""CLI golden-output gate (three lanes: structural / volatile / stable).

`tests/parity.py` proves the two SEARCH paths agree with each other; this gate
proves the CLI as a whole still behaves exactly like the pre-split single-file
script. It runs a fixed table of invocations against ./scry and compares stdout,
stderr, and exit code against a recorded baseline.

Usage:
  python3 tests/cli_golden.py            # run all lanes
  python3 tests/cli_golden.py --record   # (re)record the baseline
  python3 tests/cli_golden.py --lane structural|volatile|stable
  python3 tests/cli_golden.py -v         # always show per-case detail

WHY THREE LANES
---------------
Scryfall ships new cards continuously, so any figure derived from the card set
(match counts, row counts, cache size, prices) changes on an ordinary `scry
update` with no code change at all. A single byte-identical gate cannot tell
"the data moved" from "the code broke", so every refresh looked catastrophic.

  structural : help/usage, error objects, exit codes, flag routing, machines
               vs pretty routing. MUST be byte-identical. No tolerance. This
               is the lane that catches a real regression.
  volatile   : the same text with data-derived tokens scrubbed. Catches
               STRUCTURAL damage to data-bearing commands (field reordering,
               dropped keys, wrong exit code) while tolerating a refresh.
  stable     : quotes the data-derived tokens themselves (match counts, row
               parity, cache size) so schema or invariant breakage still
               shows up, without pinning exact figures.

The baseline was captured from the single-file `scryfall` (1,783 lines) before
the package split; recording again is only correct if an intentional behaviour
change was made. Record AFTER a release refresh, not after a mid-cycle update,
so the structural lane stays the source of truth.

Network-backed commands (update/image/fuzzy) are excluded — they are covered by
the offline parts of parity.py.
"""

import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
# SCRY_BIN lets the same suite run against a PyInstaller build (see scry.spec).
CLI = os.environ.get("SCRY_BIN") or os.path.join(REPO, "scry")
BASELINE = os.path.join(HERE, "golden.json")

LANES = ("structural", "volatile", "stable")

# (label, argv, env overrides) — env is merged over the caller's environment.
CASES = [
    ("help",            [],                                   {}),
    ("name",            ["name", "sol ring"],                 {}),
    ("name-limit-json", ["name", "lotus", "--limit", "3", "--json"], {}),
    ("text",            ["text", "counter target spell"],     {}),
    ("type",            ["type", "enchantment", "--limit", "5"], {}),
    ("cmc",             ["cmc", "<=2", "--limit", "5"],       {}),
    ("cmc-bad",         ["cmc", "abc"],                       {}),
    ("color",           ["color", "WG", "--limit", "5"],      {}),
    ("color-bad",       ["color", "XYZ"],                     {}),
    ("keyword",         ["keyword", "flying", "--limit", "5"], {}),
    ("oracle",          ["oracle", "Sol Ring"],               {}),
    ("search",          ["search", "treasure token", "--limit", "5"], {}),
    ("price",           ["price", "Sol Ring", "--limit", "3"], {}),
    ("price-sort",      ["price", "lotus", "--sort", "name", "--limit", "3"], {}),
    ("name-pretty",     ["name", "sol ring", "--pretty", "--limit", "2"], {}),
    ("name-nodb",       ["name", "sol ring", "--limit", "2", "--no-db"], {}),
    ("unknown-cmd",     ["frobnicate", "x"],                  {}),
    ("empty-query",     ["name"],                             {}),
    ("unknown-flag",    ["name", "x", "--bogus"],             {}),
    ("csv",             ["name", "lotus", "--limit", "2", "--csv"], {}),
    ("doctor",          ["doctor"],                           {}),
    ("env-format",      ["price", "Sol Ring", "--limit", "2"],
                        {"SCRYFALL_FORMAT": "json"}),
]

# Cases whose ENTIRE output is structural: no card data, no prices, no counts.
# These are compared byte-for-byte in every lane. Everything else carries data.
STRUCTURAL_CASES = frozenset({
    "help", "cmc-bad", "color-bad", "unknown-cmd", "empty-query",
    "unknown-flag", "name-pretty",
})

# --- Lane B: tokens scrubbed before comparing data-bearing output -------------
# Deliberately narrow. Anything NOT listed here that differs is a real change:
# field names, field order, error keys, column order, exit codes, URL paths.
def _pad(width_token):
    """Replace a number with a same-width placeholder.

    Doctor aligns its columns with spaces, so substituting a short token would
    change the gap width and flag pure formatting as a regression. Matching the
    original character count keeps the layout comparable.
    """
    return lambda m: "<" + "N" * max(0, len(m.group(0)) - 2) + ">"


SCRUB = [
    # prices: "usd": 1.96 -> "usd": <P>
    (re.compile(r'"(usd|usd_foil|usd_etched|eur|eur_foil|tix)":\s*(?:"[^"]*"|[0-9.]+|null)'),
     r'"\1": <P>'),
    # cache / index sizes: "199.2 MB" -> "<SIZE>"
    (re.compile(r"\b\d+(?:\.\d+)? MB\b"), "<SIZE>"),
    # row counts: "38,940 vs 38,940 jsonl lines" -> "<N> vs <N> jsonl lines"
    (re.compile(r"\b\d{1,3}(?:,\d{3})+\b"), None),  # filled in below (needs width)
    # timestamps / ages from staleness warnings
    (re.compile(r"\b\d+ days old\b"), "<AGE> days old"),
    # sqlite runtime version: differs per interpreter (3.9 -> 3.54.0,
    # 3.12 -> 3.50.4) and again inside a PyInstaller bundle. Capability, not
    # version, is what doctor's `fts5 + trigram` line already proves.
    (re.compile(r"available \(\d+\.\d+[\.\d]*\)"), "available (<SQLITE>)"),
]

# The shown-count ("5 of 3926") keeps its limit but loses its total: the limit
# is ours and structural, the total comes from the card set.
MATCH_RE = re.compile(r"\b(\d+) of (\d+) matches shown")
LIMIT_HINT_RE = re.compile(r"--limit\s+\d+")

# Card-image URLs carry a cache-busting epoch (?1783911030) that changes on
# every Scryfall refresh even when the artwork does not. The PATH must stay
# intact so a broken image URL is still caught; only the stamp is scrubbed.
IMG_STAMP_RE = re.compile(r'(cards\.scryfall\.io/[^\s"?]+)\?\d+')


def scrub_csv(text):
    """Blank price cells in CSV output by column position.

    CSV emits bare numbers (,,45.46,,26.22,) with no key to anchor on, so we
    read the header row and replace only the price columns. Blindly scrubbing
    every decimal would also erase cmc/mana values, which must stay exact.
    """
    if not text.startswith("name,lang,"):
        return text
    lines = text.split("\n")
    header = lines[0].split(",")
    price_cols = [i for i, h in enumerate(header)
                  if h in ("usd", "usd_foil", "usd_etched", "eur", "eur_foil", "tix")]
    if not price_cols:
        return text
    out = [lines[0]]
    for line in lines[1:]:
        if not line or line.count(",") < len(header) - 1:
            out.append(line)
            continue
        cells, rest = parse_csv_row(line)
        for i in price_cols:
            if i < len(cells) and cells[i] != "":
                cells[i] = "<P>"
        out.append(rest.join(cells))
    return "\n".join(out)


def parse_csv_row(line):
    """Split a CSV row on unquoted commas; return (cells, sep) for round-trip."""
    cells, buf, in_q, sep = [], [], False, ","
    for ch in line:
        if ch == '"':
            in_q = not in_q
            buf.append(ch)
        elif ch == "," and not in_q:
            cells.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    cells.append("".join(buf))
    return cells, sep


def scrub(text):
    """Replace data-derived tokens. Structural text is preserved verbatim."""
    text = scrub_csv(text)
    text = MATCH_RE.sub(r"\1 of <N> matches shown", text)
    text = LIMIT_HINT_RE.sub("--limit <N>", text)
    text = IMG_STAMP_RE.sub(r"\1?<STAMP>", text)
    for pat, repl in SCRUB:
        if repl is None:
            # width-preserving: doctor aligns columns with spaces
            text = pat.sub(_pad(None), text)
        else:
            text = pat.sub(repl, text)
    # Doctor re-pads its label column as values change width, so equal content
    # can still differ by indentation. Lane B compares CONTENT; lane A owns
    # exact layout (structural cases still compare byte-for-byte).
    text = re.sub(r"[ \t]+", " ", text)
    return text


# --- Lane C: the data-derived facts themselves --------------------------------
# Extracted as a dict of invariants rather than compared as raw text, so 'the
# card count went up' is fine but 'the two counts disagree' or 'the figure
# vanished' is a failure.
def stable_facts(out, err):
    facts = {}
    # NOTE: counts are comma-grouped ("38,940"); \d+ alone silently matches
    # nothing here, which is precisely the failure this lane must not have.
    NUM = r"([\d,]+)"
    m = re.search(r"rows indexed\s+" + NUM + r" vs " + NUM + r" jsonl lines", out)
    if m:
        a, b = int(m.group(1).replace(",", "")), int(m.group(2).replace(",", ""))
        facts["row_parity_equal"] = (a == b)
        facts["rows_positive"] = (a > 0)
    m = re.search(r"status\s+(\w+)", out)
    if m:
        facts["index_status"] = m.group(1)
    m = re.search(r"schema_version\s+(\d+) \(expected (\d+)\)", out)
    if m:
        facts["schema_matches"] = (m.group(1) == m.group(2))
    m = re.search(r"fts5 \+ trigram\s+(\w+)", out)
    if m:
        facts["fts5"] = m.group(1)
    for shown, total in MATCH_RE.findall(out + err):
        if int(shown) < 1 or int(total) < 1:
            facts["totals_positive"] = False
        if int(shown) > int(total):
            facts["limit_honoured"] = False
    # CSV/JSON price columns must remain numeric, never stringly-typed.
    if re.search(r'"(usd|usd_foil|usd_etched|eur|eur_foil|tix)":\s*"', out):
        facts["prices_numeric"] = False
    return facts


def run_all():
    out = {}
    for label, args, env_over in CASES:
        env = dict(os.environ)
        env["SCRYFALL_NO_CACHE_WARN"] = "1"
        env.update(env_over)
        p = subprocess.run([CLI] + args, capture_output=True, text=True, env=env, cwd=REPO)
        out[label] = {"rc": p.returncode, "out": p.stdout, "err": p.stderr}
    return out


def compare(lane, want, got):
    """Return (passed, failed) lists of (case/channel, message)."""
    passed, failed = [], []
    for label, base in want.items():
        cur = got.get(label)
        if cur is None:
            failed.append((label, "not in case table"))
            continue
        is_structural = label in STRUCTURAL_CASES

        # A. exit codes are always structural
        if cur["rc"] != base["rc"]:
            failed.append((label + ".rc", "baseline rc=%s got rc=%s" % (base["rc"], cur["rc"])))
            continue

        if lane == "structural":
            if not is_structural:
                passed.append((label, "skipped: data-bearing (covered by volatile)"))
                continue
            bad = [k for k in ("out", "err") if cur[k] != base[k]]
            if bad:
                for k in bad:
                    failed.append((label + "." + k, first_diff(base[k], cur[k])))
            else:
                passed.append((label, "byte-identical"))

        elif lane == "volatile":
            if is_structural:
                bad = [k for k in ("out", "err") if cur[k] != base[k]]
                if bad:
                    for k in bad:
                        failed.append((label + "." + k, first_diff(base[k], cur[k])))
                else:
                    passed.append((label, "byte-identical (structural case)"))
                continue
            bad = [k for k in ("out", "err") if scrub(cur[k]) != scrub(base[k])]
            if bad:
                for k in bad:
                    failed.append((label + "." + k, first_diff(scrub(base[k]), scrub(cur[k]))))
            else:
                passed.append((label, "matches after scrubbing data tokens"))

        elif lane == "stable":
            # Assert INVARIANTS on the live output. We deliberately do not diff
            # against the baseline's facts: exact counts legitimately grow with
            # every Scryfall refresh, so only breakage of the invariant matters.
            c = stable_facts(cur["out"], cur["err"])
            b = stable_facts(base["out"], base["err"])
            if not b and not c:
                passed.append((label, "no data facts to check"))
                continue
            broken = [k for k, v in c.items() if v is False]
            if broken:
                failed.append((label + ".facts", "invariant broken: %s" % broken))
            elif b and set(b) != set(c):
                # A fact we used to be able to read has vanished. This also
                # catches a regex that silently stopped matching — the gate
                # must never pass by failing to parse.
                failed.append((label + ".facts",
                               "fact keys differ: baseline=%s got=%s"
                               % (sorted(b), sorted(c))))
            else:
                passed.append((label, "%d invariant(s) hold" % len(c)))
    return passed, failed


def first_diff(base, got):
    for i, (x, y) in enumerate(zip(base, got)):
        if x != y:
            return "at %d: baseline=%r got=%r" % (
                i, base[max(0, i - 40):i + 40], got[max(0, i - 40):i + 40])
    if len(base) == len(got):
        return "identical"
    return "prefix identical; baseline tail=%r got tail=%r" % (
        base[len(got):][:80], got[len(base):][:80])


def main(argv):
    record = "--record" in argv
    verbose = "-v" in argv or "--verbose" in argv
    lane = None
    if "--lane" in argv:
        lane = argv[argv.index("--lane") + 1]
        if lane not in LANES:
            print("unknown lane %r (choose: %s)" % (lane, ", ".join(LANES)))
            return 2

    got = run_all()

    if record:
        with open(BASELINE, "w") as f:
            json.dump(got, f, indent=1)
        print("recorded %d cases -> %s" % (len(got), BASELINE))
        print("NOTE: structural lane changes are now FROZEN. Review the diff you")
        print("      recorded over, or an unintended regression is now the spec.")
        return 0

    if not os.path.exists(BASELINE):
        print("no baseline at %s — run with --record first" % BASELINE)
        return 1

    with open(BASELINE) as f:
        want = json.load(f)

    lanes = [lane] if lane else list(LANES)
    total_failed = 0
    for this in lanes:
        passed, failed = compare(this, want, got)
        total_failed += len(failed)
        checked = len({lbl for lbl, _ in passed} | {lbl.split(".")[0] for lbl, _ in failed})
        status = "PASS" if not failed else "FAIL"
        print("\n[%s] %s  %d/%d checked cases passed, %d diff(s)"
              % (this, status, checked - len({lbl.split(".")[0] for lbl, _ in failed}),
                 checked, len(failed)))
        for label, msg in failed:
            print("  DIFF  %-22s %s" % (label, msg))
        if verbose or failed:
            for label, msg in passed:
                if verbose:
                    print("  ok    %-22s %s" % (label, msg))

    print("\n%d lane(s) checked, %d total diff(s)" % (len(lanes), total_failed))
    return 1 if total_failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
