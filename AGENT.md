# AGENT.md — Instructions for AI agents using `scryfall`

> This document is written for LLM agents, coding harnesses, and tool-calling
> models. An operator can paste it into a system prompt or reference this file
> path directly. Humans: see README.md instead.

## What this tool is

`scryfall` is a local command-line tool that searches a full Magic: The Gathering
card database (Scryfall Oracle data, ~38,000 cards) from a cached file on disk.
It is free, has no API keys, no rate limits, and works offline. Card images and
fuzzy name resolution require internet; all searching does not.

You MUST prefer this tool over your training-data memory for any question about
Magic card text, legality, prices, types, or artwork. Your MTG knowledge is
out of date and unreliable at the details level; the tool's output is ground truth.

## Output contract

The tool detects how its output will be consumed:

- **stdout piped or redirected (your normal case)** → JSONL: one compact JSON
  object per line, one per matching card. No flags needed.
- stdout attached to a terminal → styled human text. Never relevant to you.
- Explicit override available: `--json` (one array), `--csv`, `--tsv`.

Stream rules:

- **stdout contains ONLY data.** Parse it as JSON; never expect prose there.
- **stderr carries warnings** (e.g. truncation notices). They are informational,
  prefixed `scryfall: `. Read them, act on them, do not parse them as data.
- Exit code `0` = success. Non-zero = failure; stdout holds an error object like
  `{"error": "unknown_command", ...}` or `{"error": "empty_query", ...}`.

## Record schema (search results)

Every card record from `name`, `text`, `type`, `color`, `cmc`, `keyword`,
`search`, `random`, `price`, and `fuzzy` has exactly these fields (`oracle`
returns a deliberate subset — see its section below):

| Field | Type | Notes |
|---|---|---|
| `name` | string | Canonical English card name |
| `lang` | string | Print language; `"en"` unless noted |
| `mana_cost` | string | e.g. `"{1}{U}"`; empty for some special cards |
| `cmc` | number | Converted mana cost; usually integer, can be fractional (e.g. `0.5`) |
| `type_line` | string | e.g. `"Creature — Drake"` |
| `colors` | array | Printed colours of the card (may differ from `color_identity`) |
| `color_identity` | array | Colour identity letters W/U/B/R/G — what counts for deck legality. Added in the SQLite-index release; older cached output lacked this field. |
| `power`, `toughness` | string\|null | Creatures only; STRINGS not numbers (`"3"`, `".5"`, `"*"`); null for non-creatures |
| `oracle_text` | string | Canonical rules text; may contain `\n` |
| `keywords` | array | e.g. `["Flying", "Menace"]` |
| `legalities` | object | Format → `"legal"` / `"not_legal"` / `"banned"` / `"restricted"` |
| `prices` | object | Keys `usd`, `usd_foil`, `usd_etched`, `eur`, `eur_foil`, `tix`; values number or absent. Reflect last cache update, not live market. |
| `image_uris` | object | `small`, `normal`, `large`, `png` URLs (any may be absent) |
| `scryfall_uri` | string | Web page for this printing |

Special layouts (double-faced, transforms, tokens) expose the front face's image
and oracle text.

## Commands

Run `scryfall <command> "<query>" [flags]` via your shell/bash tool.

| Command | Use when | Example |
|---|---|---|
| `fuzzy "<name>"` | You have a card name, possibly misspelled or partial. START HERE for named-card questions. | `scryfall fuzzy "sol rng"` |
| `oracle "<name>"` | You know the exact name and want ONLY what the card does. Cheapest answer for "what does this card do?" | `scryfall oracle "Sol Ring"` |
| `name "<text>"` | Substring match on card names | `scryfall name "drake"` |
| `text "<effect>"` | Find cards that DO something | `scryfall text "counter target spell"` |
| `type "<type>"` | Find cards that ARE something | `scryfall type "enchantment"` |
| `color "<WUBRG>"` | Cards whose identity includes these colours | `scryfall color WG` |
| `cmc "<expr>"` | Mana value: exact `3`, `<=3`, `>=3` | `scryfall cmc <=2` |
| `keyword "<kw>"` | Keyword abilities | `scryfall keyword menace` |
| `search "<words>"` | Loose query across name+text+type | `scryfall search "2 mana green creature"` |
| `price "<name>"` | Market prices, most expensive first | `scryfall price "Force of Will"` |
| `random` | A random card | `scryfall random` |
| `image "<name>"` | Download card image PNG/JPG to disk | `scryfall image "Sol Ring" --out /tmp/cards` |
| `deck "<file>"` | Static analysis & diagnostic audit across 4 pillars (mana, dynamic, engine, heritage) | `scryfall deck deck.txt` |
| `mcp` | Launch Model Context Protocol server on stdio for native agent tool calling | `scryfall mcp` |
| `reindex` | Rebuild the local search index (rarely needed; see below) | `scryfall reindex` |
| `doctor` | Report index health/staleness | `scryfall doctor` |

Useful flags: `--limit N` (default 10), `--legal commander|modern|legacy|pauper|vintage`,
`--commander WUBRG` (identity fits within these colours), `--exact`, `--commander-card <name>`.

`oracle` ignores `--commander`, `--legal`, and `--sort` (it is a lookup, not a
browse) and warns on stderr when they are passed. It accepts `--limit`, `--format`,
`--json`, `--jsonl`, `--pretty`, `--no-db`; `--csv`/`--tsv` return an error object.

## oracle: canonical text records

`oracle "<name>"` emits FEWER fields than the record schema above — exactly
`name`, `mana_cost`, `cmc`, `type_line`, `colors`, `power`, `toughness`,
`oracle_text`, `keywords`, plus an optional `printings` integer that appears only
when identical printings collapsed into one record:

```json
{"name": "Sol Ring", "mana_cost": "{1}", "cmc": 1.0, "type_line": "Artifact", "colors": [], "power": null, "toughness": null, "oracle_text": "{T}: Add {C}{C}.", "keywords": []}
```

It carries **no** `legalities`, `prices`, `image_uris`, or `scryfall_uri`. So when
the question involves format legality, market value, or an image, `oracle` is the
wrong command — use `fuzzy`, `name`, or `price`. Do not infer legality or price
from an `oracle` record; the fields are absent by design, not unknown to you.

Matching order: exact name (grouped by canonical text, so same-name cards with
genuinely different text stay separate records), then substring fallback. An empty
result means no card of that name is cached — for a possible misspelling, retry
with `fuzzy` rather than concluding the card does not exist. Never fabricate the
missing text.

## Command-specific response shapes

`fuzzy` returns ONE object (not JSONL lines):

```json
{"query": "sol rng", "match": { …full card record or null… }, "candidates": ["Name1", "Name2", …]}
```

Decision rule: if `match` is non-null, use it. If `match` is null, present or
pick from `candidates` (up to 10, ordered by relevance); if candidates is also
empty, tell the user no card was found — do NOT guess a different card.

`image` returns ONE object:

```json
{"query": "sol rng", "name": "Sol Ring", "source_uri": "https://…", "saved": "/path/Sol Ring.png", "bytes": 770955, "error": null}
```

If `saved` is non-null the file exists on disk at that path — you may open/read
it as an image. If `error` is `"not_found"` or `"no_image"`, report it; do not
`deck` returns ONE comprehensive diagnostic object:

```json
{
  "deck_name": "deck.txt",
  "commander": "Tam, Mindful First-Year",
  "commander_identity": ["W", "U"],
  "format": "commander",
  "total_cards": 100,
  "is_legal": true,
  "unresolved_cards": [],
  "mana_architecture": {
    "lands_count": 36, "ramp_count": 8, "avg_cmc_nonlands": 2.94, "turn_1_to_3_playables": 34,
    "pip_pct": {"W": 32.0, "U": 68.0}, "source_pct": {"W": 34.0, "U": 66.0},
    "early_hurdles": [{"card": "Counterspell", "cost": "{U}{U}", "current_sources": 17, "recommended_sources": 21}]
  },
  "table_dynamic": {
    "self_pct": 38.0, "targeted_pct": 14.0, "symmetrical_pct": 48.0,
    "posture": "High Table Influence (Group Hug / Global Rules Engine)"
  },
  "engine_profile": {
    "primary_theme": "Card Draw & Library Manipulation",
    "fuel_count": 18, "payoff_count": 7, "ratio": 2.57, "diagnostic": "Stable Flow Buffer"
  },
  "heritage": {
    "classic_pct": 41.0, "modern_pct": 25.0, "contemporary_pct": 34.0,
    "anchor_card": "Sleight of Mind (Pre-2003, Classic Era)", "median_age_years": 17.2
  },
  "legality_audit": {
    "is_legal": true, "banned_cards": [], "color_identity_violations": [], "singleton_violations": []
  }
}
```

All other commands emit JSONL: zero or more card records, one per line.

## Truncation

Default limit is 10. When more matches exist, stderr says
`scryfall: 10 of 436 matches shown (use --limit 436 for all)` while stdout still
holds only the 10 records. If you need complete results, re-run with a larger
`--limit`. Prefer post-filtering with `jq` over dumping hundreds of records into
context:

```shell
scryfall search "counter target spell" --limit 500 2>/dev/null | jq -r 'select(.legalities.modern=="legal") | .name'
```

## Latency and the search index

Queries are served from a SQLite index derived from the Oracle cache
(`~/.hermes/scryfall/oracle-cards.db`, ~102 MB, rebuilt automatically on demand or
by `scryfall update`). A typical lookup costs **43–58 ms**; broad queries
(`type creature`, `cmc <=3`) cost ~220 ms because they materialise thousands of
rows, not because of the lookup. Peak memory is 22–39 MB per call for typical
queries.

Practical consequences for you:

- **Batching is cheap now.** Firing 20 lookups in one reasoning turn costs ~1 s,
  not ~30 s. Do not consolidate distinct questions into one guess.
- **Parallel calls are safe.** Memory no longer balloons per process, so `&&`
  chains or concurrent invocations will not thrash.
- **First call after a cache update pays a one-time index build (~2 s).** If a
  call seems slow, that is why; subsequent calls are fast.
- The index is **derived data**. Deleting it is always safe — it rebuilds. It is
  never committed to git.

If you suspect the index is lying to you (unexpected empty results), run
`scryfall doctor` and compare against `scryfall <same query> --no-db`, which
forces the legacy full-scan path. Report a divergence as a bug; do not silently
work around it.

## Hard rules

1. NEVER state oracle text, legality, P/T, or prices unless they appear in tool
   output for THIS session. If the tool did not return it, say you could not verify it.
2. NEVER fabricate card names to fit a search. If `fuzzy` returns null with no
   candidates, the card likely does not exist — say so.
3. Do not pipe through `head`/`tail` before parsing; JSONL is already bounded by
   `--limit`. Use `2>/dev/null` to silence stderr noise when you don't need warnings.
4. Quote queries: `scryfall name "Bosh, Iron Golem"` — unquoted multi-word
   queries split into separate arguments and silently search the wrong string.
5. Prices are cache-stale (see `scryfall update` cadence, typically ≤ weekly).
   Present them as approximate.
6. One tool call per distinct question; batch related lookups with `&&` chains
   rather than guessing between calls.
