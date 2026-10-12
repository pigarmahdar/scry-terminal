#!/usr/bin/env python3
"""CLI golden-output gate (byte-identity for every output channel).

`tests/parity.py` proves the two SEARCH paths agree with each other; this gate
proves the CLI as a whole still behaves exactly like the pre-split single-file
script. It runs a fixed table of invocations against ./scryfall and compares
stdout, stderr, and exit code byte-for-byte against a recorded baseline.

Usage:
  python3 tests/cli_golden.py            # compare against tests/golden.json
  python3 tests/cli_golden.py --record   # (re)record the baseline

The baseline was captured from the single-file `scryfall` (1,783 lines) before
the package split; recording again is only correct if an intentional behaviour
change was made.

Cases are chosen to cover every exit path and output mode the split could
plausibly break: usage docstring, all search commands, both validation errors,
machine/pretty modes, --no-db, env-var format override, and the maintenance
commands. Network-backed commands (update/image/fuzzy) are excluded — they are
covered by the offline parts of parity.py.
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CLI = os.path.join(REPO, "scry")
BASELINE = os.path.join(HERE, "golden.json")

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


def run_all():
    out = {}
    for label, args, env_over in CASES:
        env = dict(os.environ)
        env["SCRYFALL_NO_CACHE_WARN"] = "1"
        env.update(env_over)
        p = subprocess.run([CLI] + args, capture_output=True, text=True, env=env, cwd=REPO)
        out[label] = {"rc": p.returncode, "out": p.stdout, "err": p.stderr}
    return out


def main():
    record = "--record" in sys.argv
    got = run_all()

    if record:
        with open(BASELINE, "w") as f:
            json.dump(got, f, indent=1)
        print("recorded %d cases -> %s" % (len(got), BASELINE))
        return 0

    if not os.path.exists(BASELINE):
        print("no baseline at %s — run with --record first" % BASELINE)
        return 1

    with open(BASELINE) as f:
        want = json.load(f)

    fails = 0
    for label, base in want.items():
        cur = got.get(label)
        if cur is None:
            print("MISSING  %s (not in case table)" % label)
            fails += 1
            continue
        for k in ("rc", "out", "err"):
            if cur[k] == base[k]:
                continue
            fails += 1
            print("DIFF     %s.%s" % (label, k))
            if k == "rc":
                print("         baseline rc=%s got rc=%s" % (base[k], cur[k]))
                continue
            b, g = base[k], cur[k]
            print("         baseline %dB / got %dB" % (len(b), len(g)))
            for i, (x, y) in enumerate(zip(b, g)):
                if x != y:
                    print("         at %d: baseline=%r" % (i, b[max(0, i - 40):i + 40]))
                    print("              got     =%r" % (g[max(0, i - 40):i + 40],))
                    break
            else:
                print("         prefix identical; baseline tail=%r got tail=%r"
                      % (b[len(g):][:80], g[len(b):][:80]))
        if not fails or all(cur[k] == base[k] for k in ("rc", "out", "err")):
            if all(cur[k] == base[k] for k in ("rc", "out", "err")):
                print("ok       %s" % label)

    total = len(want)
    print("\n%d/%d cases byte-identical" % (total - fails, total))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
