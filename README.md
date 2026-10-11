# scryfall-local

A lightweight, offline command-line tool for searching [Scryfall](https://scryfall.com) Oracle cards from a local cache. No API key, no rate limits, no internet required.

Built for Magic: The Gathering players who want fast card lookups during deckbuilding, theorycrafting, or kitchen-table sessions — especially useful alongside local LLM tools for private brainstorming.

## Features

- 🔍 **Search by name, text, type, colour, mana cost, or keyword**
- 🔮 **Fuzzy name search** — handles typos, misspellings, and partial names
- 💰 **Price lookup** — USD, EUR, and TIX with foil variants
- 🖼️ **Card image download** — grab high-res PNGs straight to your Desktop
- 🤖 **LLM-ready output** — auto-detects agents vs humans; JSONL/JSON/CSV when piped, plus [AGENT.md](AGENT.md) instructions for models
- 🎲 **Random card** generation
- ⚡ **Fast** — ~50 ms per lookup from a SQLite index (was ~1.6 s per call)
- 🔒 **Offline** — works without internet once the cache is downloaded
- 🎨 **Colour-coded output** with emoji symbols (⚪🔵⚫🔴🟢)
- 🏛️ **Format filtering** — Commander, Modern, Legacy, Pauper, Vintage
- 🧩 **Commander colour identity** filtering
- 📊 **Sorting** — by name, mana value, or price
- 🔄 **Built-in cache updater** — `scryfall update` fetches the latest data from Scryfall
- 🛡️ **Input validation** — clear errors for empty queries and unknown commands

## Quick Start

### 1. Download the Scryfall Oracle cache

```shell
curl -o ~/.hermes/scryfall/oracle-cards.jsonl \
  "https://data.scryfall.io/oracle-cards/oracle-cards.jsonl"
```

Or use the built-in updater after installation (see [Updating the cache](#updating-the-cache)).

### 2. Install the script

```shell
# Clone this repo
git clone https://github.com/pigarmahdar/scryfall-local.git
cd scryfall-local

# Make executable
chmod +x scryfall

# Optional: add to your PATH (shim + package both go in the same directory,
# or keep the package in a directory already on PYTHONPATH)
mkdir -p /usr/local/lib/scryfall-local
cp -r scryfall scryfall_cli /usr/local/lib/scryfall-local/
ln -sf /usr/local/lib/scryfall-local/scryfall /usr/local/bin/scryfall
```

`scryfall` is a small executable shim; the implementation lives in the
`scryfall_cli/` package beside it. Copy both (as above) — the shim finds the
package relative to its own location, so no `PYTHONPATH` is needed.

### 3. Search!

```shell
scryfall name "Sol Ring"
scryfall text "create a treasure token"
scryfall color WG --legal commander
scryfall random
```

## Commands

| Command | Description | Example |
|---------|-------------|---------|
| `name` | Search by card name (partial match) | `scryfall name "Gilded Drake"` |
| `text` | Search by oracle text | `scryfall text "destroy all creatures"` |
| `type` | Search by type line | `scryfall type "enchantment"` |
| `color` | Search by colour identity (WUBRG letters) | `scryfall color WG` |
| `cmc` | Search by mana value (`=`, `<=`, `>=`) | `scryfall cmc <=3` |
| `keyword` | Search by keyword ability | `scryfall keyword flash` |
| `oracle` | Canonical card text only, deduplicated across printings | `scryfall oracle "Sol Ring"` |
| `fuzzy` | Fuzzy name search (handles typos, partial names) | `scryfall fuzzy "sol rng"` |
| `price` | Search by name with market prices | `scryfall price "Rhystic Study"` |
| `image` | Download a card's image (PNG to Desktop) | `scryfall image "Sol Ring"` |
| `random` | Get a random card | `scryfall random` |
| `search` | General search across name + text + type | `scryfall search "2 mana green creature"` |
| `update` | Update the Oracle cache from Scryfall | `scryfall update` |
| `reindex` | Rebuild the local search index | `scryfall reindex` |
| `doctor` | Report index health and staleness | `scryfall doctor` |

## Options

| Flag | Description | Example |
|------|-------------|---------|
| `--limit N` | Max results (default: 10) | `--limit 20` |
| `--commander WUBRG` | Cards whose colour identity fits within these colours | `--commander WU` |
| `--legal <format>` | Only cards legal in a format | `--legal commander` |
| `--exact` | Exact name match only (for `name` command) | `--exact` |
| `--sort <field>` | Sort by `name`, `cmc`, or `price` (descending) | `--sort price` |
| `--size <s\|n\|l\|png>` | Image size for `image`: small, normal, large, png (default: png) | `--size large` |
| `--out <dir>` | Output directory for `image` (default: `~/Desktop`) | `--out ~/Pictures` |
| `--border <color>` | Prefer a specific border colour for `image` (black, silver) | `--border silver` |
| `--format <fmt>` | Output format: `pretty`, `json`, `jsonl`, `csv`, `tsv` (see [Machine-Readable Output](#machine-readable-output-for-llms--scripts)) | `--format json` |
| `--json` / `--jsonl` / `--csv` / `--tsv` | Shorthands for the corresponding `--format` value | `--json` |
| `--pretty` | Force human-styled output even when piped | `--pretty` |
| `--no-db` | Bypass the search index and scan the cache (debugging) | `--no-db` |

## How searching works now: the SQLite index

Queries are answered from a **SQLite index** built from the Oracle cache, using
FTS5 full-text search. This replaced parsing all 38,700 cards on every
invocation:

| | Before | Now |
|---|---|---|
| Typical lookup (`name`, `text`, `search`, `price`, `random`) | ~1.6 s | **43–58 ms** |
| Broad query (`type creature`, `cmc <=3`) | ~1.6 s | ~220 ms |
| Peak memory per call | ~920 MB | **22–39 MB** typical |
| Startup cost | parse whole file | open index |

Things worth knowing:

- **The index is derived data.** It lives at `~/.hermes/scryfall/oracle-cards.db`
  (~102 MB — *smaller* than the 194 MB JSONL it comes from), alongside transient
  `-wal`/`-shm` files while open and a `.lock` during builds. Delete any of it and
  it rebuilds automatically; none of it is ever committed to git.
- **It builds itself.** The first query after installing or after `scryfall update`
  pays a one-time ~2 s build. `scryfall update` also rebuilds it for you.
  `scryfall reindex` forces a rebuild; `scryfall doctor` reports freshness,
  schema version, FTS5 availability, and row-count parity with the JSONL.
- **Behaviour is unchanged.** Same commands, same flags, same output, same order.
  `tests/parity.py` compares the index against the JSONL scan (221 checks);
  `tests/cli_golden.py` compares CLI stdout/stderr/exit codes byte-for-byte
  against a recorded pre-refactor baseline (22 cases).
- **Fallback is automatic and total.** If `sqlite3`, FTS5, or the trigram tokenizer
  is missing, or the index is stale or corrupt, the tool silently uses the original
  full-file scan. Worst case you get yesterday's speed, never a wrong answer.
  `--no-db` forces that path for debugging.
- **Searching stays offline; `update` and `image`/`fuzzy` resolution need internet.**

## Machine-Readable Output (for LLMs & scripts)

`scryfall` is built to be a tool-calling companion for LLM harnesses, agents, and shell scripts — while staying pleasant for humans. The output format is chosen automatically:

| Signal | Result |
|--------|--------|
| Run in a terminal (TTY) | Styled, colourful `pretty` output — unchanged from before |
| stdout piped or redirected (agent, script, `\| jq`) | Compact **JSONL**, one card per line, automatically |
| `SCRYFALL_FORMAT=json` (env var) | Format override for whole sessions/harness configs |
| `--json` / `--jsonl` / `--csv` / `--tsv` / `--format <f>` | Explicit per-call override |
| `--pretty` | Force styled output even when piping |

Priority: **flag > `$SCRYFALL_FORMAT` > TTY auto-detect**. Colours additionally honour `NO_COLOR=1` and `TERM=dumb`.

**Why it matters for LLMs:** JSONL is roughly half the tokens of styled text, has zero parsing ambiguity, streams line-by-line into prompts, and composes with `jq`. Warnings and meta-information go to **stderr**, so stdout is always pure data you can pipe anywhere.

Each record uses stable, minimal fields:

```json
{"name": "Sol Ring", "lang": "en", "mana_cost": "{1}", "cmc": 1.0,
 "type_line": "Artifact", "colors": [], "color_identity": [],
 "power": null, "toughness": null,
 "oracle_text": "{T}: Add {C}{C}.", "keywords": [],
 "legalities": {"commander": "legal", "modern": "not_legal"},
 "prices": {"usd": 1.19, "eur": 1.08},
 "image_uris": {"small": "...", "normal": "...", "large": "...", "png": "..."},
 "scryfall_uri": "https://scryfall.com/card/..."}
```

`colors` is the card's printed colours; `color_identity` is what counts for deck
legality (they differ on cards like Savai Triome, which has no colours but a
three-colour identity).

Examples for agent pipelines:

```shell
# Names of every counter spell legal in Modern (no flag needed — piping triggers JSONL)
scryfall search "counter target spell" --limit 500 | jq -r 'select(.legalities.modern=="legal") | .name'

# Full array for programmatic use
scryfall name "Force of Will" --json | jq '.[0].prices.usd'

# Spreadsheet-bound: CSV of budget commander staples
scryfall type "creature" --commander G --legal pauper --csv > underdogs.csv

# fuzzy is non-interactive in machine mode: returns {query, match, candidates}
scryfall fuzzy "sol rng" | jq '.match.name'          # → matched card or null + candidates

# image returns the saved path instead of prose — chain it into vision models
scryfall image "Sol Ring" --out /tmp/cards | jq -r '.saved'
```

The `update` command remains human-oriented (progress messages on stderr).

## Examples

```shell
# Find Lightning Greaves
scryfall name "Lightning Greaves"

# All green-white creatures legal in Commander
scryfall type "creature" --commander WG --legal commander

# Cards that create Treasure tokens
scryfall text "create a treasure token"

# Cheap counterspells (CMC 2 or less)
scryfall text "counter target spell" --legal commander --limit 5

# Random card for EDH night
scryfall random

# Fuzzy search — handles typos and partial names
scryfall fuzzy "sol rng"           # → Sol Ring
scryfall fuzzy "thragtuskk"        # → Thragtusk
scryfall fuzzy "jac bele"          # → Jace Beleren etc.

# Download a card image to your Desktop
scryfall image "Sol Ring"          # → ~/Desktop/Sol Ring.png

# All flash creatures in blue
scryfall keyword flash --commander U

# Just the rules text, no price/legality noise
scryfall oracle "Sol Ring"
```

## Canonical Text Lookup (`oracle`)

`oracle` answers one question — *what does this card actually do?* — and nothing else.
It returns the rules text plus the fields needed to read it (name, mana cost, type
line, P/T, colours, keywords), omitting legalities, prices, image URIs, and the
Scryfall web link. That projection is roughly **85% smaller** than a `name` lookup:
177 bytes versus 1,146 for Sol Ring, which matters when every card costs context
tokens in an LLM session.

```shell
scryfall oracle "Sol Ring"
#   Sol Ring  {1}  ·  CMC 1
#     Artifact
#     {T}: Add {C}{C}.
```

Identical printings collapse into a single record, tagged with a `printings` count:

```shell
scryfall oracle "Sheep"          # 3 cached printings -> 1 record, "3 printings"
scryfall oracle "Elemental"       # 31 printings -> 13 records
```

The collapse groups on canonical text, not on printing identity, so it is lossless:
same-name cards that genuinely differ (the 13 distinct Elementals) stay separate.
Because this cache holds one row per oracle card rather than one row per printing,
`oracle` is a *text* deduplicator, not a reprint browser — use `name` when you want
every printing.

Two behaviours worth knowing:

- **Exact name first, substring second.** `oracle "ring"` finds no card literally
  named "ring", so it falls back to listing names containing it. For typos use
  `fuzzy`, which consults Scryfall; `oracle` never touches the network.
- **Single-card flags do not apply.** `--commander`, `--legal`, and `--sort` are
  browse-time filters, so `oracle` warns on stderr and ignores them. Output is
  `pretty` / `json` / `jsonl`; `--csv` and `--tsv` return a structured
  `unsupported_format` error rather than inventing a column set.

## Price Lookup

The `price` command searches by card name and displays market prices prominently — USD, EUR, and TIX (Magic Online tickets), with foil prices shown when available.

```shell
# Look up prices for a specific card
scryfall price "Force of Will"

# Price-sorted results for a partial name
scryfall price "bolt" --limit 5

# Prices for cards in your colour identity
scryfall price "draw" --commander WU --limit 10
```

Example output:

```
  [1] Force of Will  {3}{U}{U}  (CMC 5)
       Instant  •  🔵
       USD $60.09 (foil $71.56)  •  EUR €51.00 (foil €55.44)  •  TIX 16.99
       https://scryfall.com/card/dmr/50/force-of-will
```

The `price` command sorts by USD value (most expensive first) by default. You can also add `--sort price` to any other command to order results by price.

**Note:** Prices come from the Oracle cache and reflect the last `scryfall update`. Run `scryfall update` to refresh if prices seem stale.

## Card Images

The `image` command downloads a card's picture — PNG by default — straight to your **Desktop**:

```shell
# Highest-quality PNG → ~/Desktop/Sol Ring.png
scryfall image "Sol Ring"

# Typo? No problem — resolves via fuzzy match + local fallbacks
scryfall image "sol rng"              # → Sol Ring.png
scryfall image "jace bele"            # → Jace Beleren.png

# Smaller JPEG instead of PNG
scryfall image "Lightning Bolt" --size large

# Save somewhere else
scryfall image "Force of Will" --out ~/Pictures
```

Example output:

```
  Card: Sol Ring
  Source: https://cards.scryfall.io/png/front/8/e/8ee443cc-e17a-493b-9c93-1f9e141a30e4.png
  ✓ Saved: /Users/you/Desktop/Sol Ring.png  (753 KB)
```

How it works:

1. **Name resolution** in three tiers — exact match in your local cache first (instant, offline), then Scryfall's fuzzy API for typos, then a local word-similarity fallback that catches cases where the API returns an unrelated printed-name coincidence
2. **Size selection** — `--size small|normal|large|png` (default `png`, the high-res version). The file extension always matches the real format (`.png` vs `.jpg`)
3. **Collision-safe** — never overwrites existing files; adds ` (1)`, ` (2)`, … as needed
4. **Double-faced cards** — uses the front face's image when a card stores images per face

Unlike the rest of the tool, `image` needs an internet connection to fetch the picture itself (Scryfall hosts the images on their CDN).

## Updating the Cache

Card data from Scryfall is updated regularly (new sets, legality changes, Oracle text corrections). The tool includes a built-in updater:

```shell
scryfall update
```

This downloads the latest Oracle Cards bulk data (~200 MB) from Scryfall, backs up your existing cache, and replaces it. If anything fails, the backup is restored automatically.

You can also use the standalone shell script `update_cache.sh` (included in this repo), which wraps `curl` + `gunzip` for environments where Python isn't available or when you prefer a simpler cron job:

```shell
./update_cache.sh
```

Or update manually:

```shell
curl -o ~/.hermes/scryfall/oracle-cards.jsonl.gz \
  "https://data.scryfall.io/oracle-cards/oracle-cards-YYYYMMDDHHMMSS.jsonl.gz"
gunzip -f ~/.hermes/scryfall/oracle-cards.jsonl.gz
```

Or use a crontab for automatic monthly updates:

```shell
# Run on the 1st of every month at 3am
0 3 1 * * /path/to/scryfall update
```

## LLM & Agent Integration

`scryfall` is designed as a **tool-calling companion** for LLM harnesses, coding
agents, and local models (Ollama, LM Studio, Open WebUI, Claude Code, …) — while
staying pleasant for humans. Because it reads a local cache, calls are free,
instant, offline-capable, and rate-limit-proof: an agent can fire dozens of
lookups in one reasoning turn.

### For agents: read AGENT.md

The repo ships **[AGENT.md](AGENT.md)** — a compact, self-contained instruction
set written *for models to read*, covering the output contract, record schema,
command selection, and hard rules against hallucination. Point your system
prompt at it directly:

```text
You have access to the `scryfall` CLI for Magic: The Gathering card data.
Follow the instructions in AGENT.md exactly. Prefer it over your own memory
for any card text, legality, or price question.
```

### Why it works well in harnesses (the short version)

- **Automatic machine mode**: when stdout is piped or captured (the normal case
  for agents), output is JSONL — one compact card object per line. No flags, no
  prose, no ANSI escape codes. Humans on a terminal still get styled text.
- **Pure-data stdout**: warnings go to stderr; errors are structured JSON objects
  with non-zero exit codes. Parsing never breaks on decoration.
- **~half the tokens** of human-formatted output, with stable field names safe to
  reference from prompts (`name`, `oracle_text`, `legalities.commander`,
  `prices.usd`, `image_uris.png`, …).
- **Non-interactive by design in machine mode**: `fuzzy` returns
  `{query, match, candidates}` instead of prompting; `image` returns
  `{saved, bytes, error}` so you can chain the downloaded file into vision input.
- **Ground truth over memory**: full Oracle text, legalities, and prices for
  ~38,000 cards — deterministically better than model recall.

### Recipes for common harnesses

**Open WebUI** — two options:

1. *Function-calling pipeline preset*: add a Python function block that shells out
   and returns parsed JSONL (models see clean tool results):

   ```python
   import json, subprocess
   def scryfall(command: str, query: str, limit: int = 5) -> str:
       """Look up MTG cards: command ∈ name|text|type|color|cmc|keyword|fuzzy|price|search."""
       out = subprocess.run(["scryfall", command, query, "--limit", str(limit)],
                            capture_output=True, text=True).stdout
       return "\n".join(json.loads(l)["name"] + " :: " + json.loads(l)["oracle_text"]
                         for l in out.splitlines())
   ```

2. *Bash-tool route*: give the model shell access plus the AGENT.md preamble —
   set `SCRYFALL_FORMAT=jsonl` in the environment for belt-and-braces.

**Claude Code / generic bash agents** — add to `CLAUDE.md` or project instructions:

```text
MTG card questions: run `scryfall <cmd> "<query>" --limit N`. Piped output is
JSONL — parse with jq. See AGENT.md for the full contract. Never answer card
text, legality, or price from memory.
```

**MCP clients** — plain bash tool access is sufficient today; an MCP server
wrapper exposing these commands as typed tools is on the roadmap.

## Fuzzy Search

The `fuzzy` command uses Scryfall's API to handle typos, misspellings, and partial card names. It works in two stages:

1. **Fuzzy match** — queries Scryfall's `/cards/named?fuzzy=` endpoint
2. **Autocomplete** — if fuzzy fails, tries Scryfall's autocomplete API and presents suggestions

You pick a number and it looks up the full card.

```shell
$ scryfall fuzzy "craterhoof behemuth"
  Searching for: "craterhoof behemuth"
  ✓ Found: Craterhoof Behemoth
```

## Input Validation

The tool validates your input and gives clear feedback:

- **Empty queries** — tells you what's missing instead of dumping all 38,000 cards
- **Unknown commands** — shows the list of valid commands and suggests `scryfall search` as a fallback
- **Unknown sort fields** — warns and suggests valid options (`name`, `cmc`, `price`)

## Data Source

Card data is sourced from [Scryfall](https://scryfall.com), the best open MTG card database. The Oracle cards file contains one entry per unique card (~38,000+ cards).

Bulk data is refreshed every 12–24 hours by Scryfall. Prices become stale after 24 hours, but gameplay data (Oracle text, types, legalities) is stable for weeks.

## Project layout

The tool is a small Python package behind an executable shim:

```
scryfall              # 18-line executable shim (keeps `chmod +x` + PATH installs working)
scryfall_cli/
  __init__.py         # side-effect-free; re-exports the API the tests use
  state.py            # shared state: paths, MODE/USE_COLOR, DB/DB_MODE/CARDS/FORCE_NO_DB
  project.py          # slim_card/text_card projections + json/jsonl/csv/tsv emitters
  store.py            # SQLite sidecar: build, status, open, legacy JSONL loader, query helpers
  search.py           # search_name/text/type/color/cmc/keyword/general/random/oracle + filters/sort
  api.py              # Scryfall HTTP API + offline name resolution + fuzzy handler
  display.py          # pretty-mode rendering + image handler
  cli.py              # parse_args, command routing, update/reindex/doctor/oracle, main()
tests/
  parity.py           # 221 checks: index results == JSONL scan results, ordered
  cli_golden.py       # 22 cases: CLI stdout/stderr/exit code byte-identical to baseline
  golden.json         # recorded baseline (pre-refactor single-file behaviour)
```

**Why a package, not one file.** The script stayed single-file through the
first feature stage (adding the SQLite index, ~580 lines, without restructuring
— evidence the file *could* hold it), but two practical costs tipped the
decision: the parity harness had to load the script by path with
`SourceFileLoader` because it wasn't importable, and shared mutable globals
(`MODE`, `DB`, `CARDS`, …) were reachable from anywhere with no single source
of truth. The package split removes both while keeping the install story almost
as simple — copy the shim *and* the package directory, or run from the repo.
Behaviour is protected by the two test gates above; `tests/cli_golden.py`
exists specifically so a refactor like this can be verified byte-for-byte.

**Module layering** (imports only point downward):
`state → project → store → search → api/display → cli`. `state` is the only
module allowed to hold mutable state; everything else reads and writes
`state.<NAME>` attribute access so every module sees one object (never a
`from state import MODE` rebound copy).

## Testing

Two gates, both run from the repo root:

```shell
python3 tests/parity.py        # 221 checks: index results == JSONL scan, ordered
python3 tests/cli_golden.py     # 22 cases: CLI stdout/stderr/exit byte-identical
```

`parity.py` proves the SQLite path and the legacy full-scan path return the same
cards in the same order. `cli_golden.py` replays a recorded baseline of real
CLI invocations (usage, every search command, validation errors, pretty/json/
csv modes, `--no-db`, env-var format override, `doctor`) and diffs stdout,
stderr, and exit code byte-for-byte — the gate that lets a refactor of this size
be verified instead of trusted. Re-record with `python3 tests/cli_golden.py
--record` **only** when a behaviour change is intentional.

## Requirements

- Python 3.6+ (pre-installed on macOS and most Linux distributions)
- ~200 MB disk space for the Oracle cards cache

## License

MIT License. See [LICENSE](LICENSE) for details.

Card data is copyright Wizards of the Coast. Scryfall bulk data is provided under [Scryfall's Terms of Service](https://scryfall.com/docs/api/bulk-data).

---

*Built as part of [Kwain.gg](https://kwain.gg/) — a project about generosity, attention, and play.*
