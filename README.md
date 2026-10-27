# Scry Terminal

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-8A2BE2.svg)](https://modelcontextprotocol.io)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

**Instant Magic: The Gathering card lookups from your terminal. No API key, no rate limits, no internet.**

`scry` searches the full Scryfall Oracle database (~38,000 cards) from a local copy on your disk. Results come back in **~50 ms** — fast enough to fire a dozen lookups while you're mid-deckbuild — and the tool works completely offline once installed.

It's built for two audiences at once:

- **Players** — clean, colour-coded answers for deckbuilding, theorycrafting, and kitchen-table rules questions.
- **AI agents & scripts** — pipe it and it becomes a JSONL data source: stable fields, warnings on stderr, pure data on stdout. See [AGENT.md](AGENT.md).

For MTG brewers, script writers, and AI assistants who want instant, distraction-free answers, Scry Terminal is an offline diagnostic engine and CLI toolkit that validates card rules, deck architecture, and mana math in sub-50ms—without web bloat, rate limits, or context switching.

---

[Features](#what-it-can-do) • 
[Install](#install) • 
[Try It](#try-it) • 
[Command Reference](#command-reference) • 
[Deck Diagnostics](#deck-diagnostics--architecture-the-deck-linter) • 
[AI Agents & MCP](#for-developers-agents-and-scripts) • 
[How It Works](#how-it-works) • 
[Contributing](#contributing) • 
[License](#license)

---

## Install

Requires Python 3.9+ and ~200 MB for the card cache (downloaded separately — installing the package itself fetches ~0 bytes of card data).

### Recommended: pipx (isolated CLI)

```shell
pipx install scry-terminal
scry update   # one-time: downloads the Oracle cache & builds the search index
```

### Alternative: pip

```shell
pip install scry-terminal
scry update
```

Both `scry` and `scryfall` (backwards-compatible alias) are placed on your PATH automatically.

### Alternative: standalone binary (no Python required)

Prebuilt bundles for **macOS (Apple Silicon)** and **Linux (x86_64)** are attached to each
[GitHub Release](https://github.com/pigarmahdar/Scry-Terminal/releases) as `scry-macos-arm64.tar.gz`
and `scry-linux-x86_64.tar.gz`.

```shell
# macOS (Apple Silicon)
curl -L -o scry.tar.gz https://github.com/pigarmahdar/Scry-Terminal/releases/latest/download/scry-macos-arm64.tar.gz
tar xzf scry.tar.gz && sudo mv scry /usr/local/
sudo xattr -d com.apple.quarantine /usr/local/scry/scry   # see note below
sudo ln -sf /usr/local/scry/scry /usr/local/bin/scry
scry update
```

```shell
# Linux (x86_64)
curl -L -o scry.tar.gz https://github.com/pigarmahdar/Scry-Terminal/releases/latest/download/scry-linux-x86_64.tar.gz
tar xzf scry.tar.gz && sudo mv scry /usr/local/
sudo ln -sf /usr/local/scry/scry /usr/local/bin/scry
scry update
```

> **macOS Gatekeeper note:** these binaries are **not code-signed or notarised** (that requires a
> paid Apple Developer account). macOS attaches a quarantine flag to downloaded files and will refuse
> to run them. The `xattr -d com.apple.quarantine` line above removes it — only do this for binaries
> you got from this repository's official Releases page. If you'd rather not, use `pipx` instead.

Windows, macOS Intel, and Linux ARM are not yet built. The bundle never contains the card cache;
`scry update` downloads that separately to `~/.hermes/scryfall/`.

### Developer: git clone

```shell
git clone https://github.com/pigarmahdar/Scry-Terminal.git
cd Scry-Terminal
pip install -e .
scry update
```

### Packaging & Distribution Roadmap

- **pip / pipx**: `pip install scry-terminal` ✅ (this release)
- **Pre-compiled standalone binaries**: `scry-macos-arm64` / `scry-linux-x86_64` on GitHub Releases ✅ (no Python required)
- **Homebrew tap** *(Planned)*: `brew tap pigarmahdar/tap && brew install scry`

> **Offline / Manual Cache Setup**: If you prefer not to use `scry update`, you can fetch the dataset directly:
> ```shell
> mkdir -p ~/.hermes/scryfall
> curl -o ~/.hermes/scryfall/oracle-cards.jsonl \
>   "https://data.scryfall.io/oracle-cards/oracle-cards.jsonl"
> ```

## Try it

```shell
scry name "Sol Ring"                       # every printing of a card
scry fuzzy "sol rng"                       # typos and partial names just work
scry oracle "Sol Ring"                     # just the rules text
scry text "create a treasure token"        # find cards that do a thing
scry type "enchantment" --commander WG     # browse by type, colour identity
scry cmc <=2 --legal commander --limit 5   # cheap commander staples
scry image "Sol Ring"                      # high-res art to your Desktop
scry random                                # a random card
scry deck "my_deck.txt"                    # instant mana, engine, posture & vintage audit
```

Piped output flips to JSONL automatically:

```shell
scry search "counter target spell" --limit 500 \
  | jq -r 'select(.legalities.modern=="legal") | .name'
```

## What it can do

| | |
|---|---|
| **Search** | name, oracle text, type line, colour identity, mana value, keyword, or all of the above at once |
| **Fuzzy** | `fuzzy "thragtuskk"` → Thragtusk; misspellings, partials, and near-misses resolve to the right card |
| **Deck** | `deck <file>` or `pbpaste \| scry deck`: Karsten mana balance, table posture, engine fuel/payoff ratios, vintage heritage, legality |
| **Prices** | USD, EUR, and MTGO tickets with foil variants, sorted most-expensive-first |
| **Images** | Download PNG/JPG art straight to disk (`--size`, `--out`, `--border`) |
| **Filters** | `--commander WUBRG` colour identity, `--legal <format>` for 15+ formats, `--sort name/cmc/price` |
| **Offline** | Every search runs against your local cache — no network, no API key, no rate limit |
| **Agent-ready** | Auto-detects pipes and emits compact JSONL; human-readable colour output in a terminal |

## For developers, agents, and scripts

The output format is chosen for you:

| Situation | Output |
|---|---|
| Typed in a terminal | Styled, colour-coded text |
| Piped or redirected (`\| jq`, scripts, LLM tools) | Compact **JSONL**, one card per line |
| `--json` / `--csv` / `--tsv` / `SCRY_FORMAT=json` | Explicit override |

Stdout is **always pure data** — warnings and progress go to stderr, so parsing never breaks. Every record uses the same stable fields (`name`, `oracle_text`, `color_identity`, `legalities`, `prices`, `image_uris`, …), roughly half the tokens of the styled output. Commands that normally prompt (`fuzzy`, `image`) return structured objects instead, so they never hang a pipeline.

**Agents:** the repo ships [AGENT.md](AGENT.md) — a compact instruction set written for models, covering the output contract, record schema, and rules against hallucinating card text. Point your system prompt at it and tell the model to prefer it over its own memory.

```text
You have access to the `scry` CLI (Scry Terminal) for Magic: The Gathering card data.
Follow AGENT.md exactly. Prefer it over your memory for card text,
legality, or prices.
```

Works out of the box with Open WebUI, Claude Code, Ollama, LM Studio, Antigravity, or any tool that can run a shell command.

### Model Context Protocol (MCP) Server

`scry` includes a built-in MCP server running over stdio with **zero external dependencies**:

```shell
scry mcp
```

Add it to your MCP client configuration (Claude Desktop, Cursor, Windsurf, Claude Code):

**`claude_desktop_config.json`**:
```json
{
  "mcpServers": {
    "scry": {
      "command": "/path/to/scry",
      "args": ["mcp"]
    }
  }
}
```

Exposed native tools:
- `scryfall_oracle`: Canonical card text, mana cost, and types (token-efficient).
- `scryfall_search`: Search cards with format legality (`legal`), commander color identity (`commander`), and sorting.
- `scryfall_fuzzy`: Typo-tolerant card name resolution.
- `scryfall_deck`: Full 4-pillar decklist audit and format legality verification.
- `scryfall_price`: Market pricing in USD, EUR, and TIX.
- `scryfall_doctor`: Local SQLite index and cache health check.

## Command reference

| Command | Description | Example |
|---|---|---|
| `name` | Search by card name (partial match) | `scry name "Gilded Drake"` |
| `text` | Search by oracle text | `scry text "destroy all creatures"` |
| `type` | Search by type line | `scry type "enchantment"` |
| `color` | Search by colour identity (WUBRG letters) | `scry color WG` |
| `cmc` | Search by mana value (`=`, `<=`, `>=`) | `scry cmc <=3` |
| `keyword` | Search by keyword ability | `scry keyword flash` |
| `search` | General search across name + text + type | `scry search "2 mana green creature"` |
| `oracle` | Canonical card text only, deduplicated across printings | `scry oracle "Sol Ring"` |
| `fuzzy` | Fuzzy name search (handles typos, partial names) | `scry fuzzy "sol rng"` |
| `price` | Search by name with market prices | `scry price "Rhystic Study"` |
| `image` | Download a card's image (PNG to Desktop) | `scry image "Sol Ring"` |
| `deck` | Static analysis & diagnostic audit across 4 pillars | `scry deck deck.txt` |
| `random` | Get a random card | `scry random` |
| `mcp` | Start Model Context Protocol server on stdio | `scry mcp` |
| `update` | Update the Oracle cache from Scryfall | `scry update` |
| `reindex` | Rebuild the local search index | `scry reindex` |
| `doctor` | Report index health and staleness | `scry doctor` |
| `completion` | Generate shell completions (bash, zsh, fish) | `source <(scry completion zsh)` |
| `version` | Show installed version | `scry version` |

### Flags

| Flag | Description |
|---|---|
| `--limit N` | Max results (default: 10) |
| `--commander WUBRG` | Cards whose colour identity fits within these colours |
| `--commander-card <name>` | Explicit commander card name override (for `deck`) |
| `--legal <format>` | Only cards legal in a format (default `commander` for `deck`) |
| `--exact` | Exact name match (for `name`) |
| `--sort <field>` | Sort by `name`, `cmc`, or `price` |
| `--size <s\|n\|l\|png>` | Image size for `image` (default: png) |
| `--out <dir>` | Output directory for `image` (default: `~/Desktop`) |
| `--border <color>` | Prefer a specific border colour for `image` |
| `--format <fmt>` | `pretty`, `json`, `jsonl`, `csv`, `tsv` |
| `--json` / `--jsonl` / `--csv` / `--tsv` | Shorthands for `--format` |
| `--pretty` | Force human-styled output even when piped |
| `--no-db` | Bypass the search index (debugging) |
| `--version` / `-v` | Display version and exit |
| `--help` / `-h` | Display usage and options text |

## Deck Diagnostics & Architecture (The Deck Linter)

```shell
scry deck deck.txt                             # audit decklist file
cat deck.txt | scry deck                       # audit from pipe
pbpaste | scry deck                            # audit macOS clipboard directly
scry deck deck.txt --json                      # machine-readable diagnostic schema
```

### Why We Made It
Web deckbuilders (Moxfield, Archidekt) already excel at visual drag-and-drop card grids and image galleries. We did not build `scry deck` to be an inferior ASCII clone of a web browser.

Instead, it is designed as a **Deck Architecture & Health Linter** (`cargo check` / `eslint` for Magic: The Gathering):
- **Instant Terminal Speed (<20 ms):** Run instant sanity checks while editing `.txt` decklists in VS Code or Vim without context switching.
- **100% Offline & Private:** Validates and audits full 100-card decks using local SQLite batch queries with zero external network calls.
- **Respect for Diverse Wincons:** Rather than grading every deck against a rigid, hyper-efficient cEDH aggro template, it analyzes a deck against **its own internal engine and playstyle** (Group Hug, alternate wincons, mill, or 90s retro themes).

### The 4 Diagnostic Pillars
1. **Vitals & Mana Architecture:** Compares Frank Karsten colored mana production (lands and rocks) against colored pip demands. Detects early-turn multi-pip hurdles (e.g. `{U}{U}` at CMC 2 Counterspell with insufficient blue sources) and measures Turn 1–3 playables density.
2. **Table Dynamic & Political Posture:** Quantifies table influence by parsing card targeting into **Self-Focused** (advancing own board), **Targeted** (adversarial removal/interaction), and **Symmetrical** (table-wide effects, group hug, sweepers).
3. **Engine Balance ("Fuel vs. Payoff"):** Models universal action generators (draw, sacrifice, tokens, counters, color alteration) against reward listeners (`"Whenever you..."`). Flags fuel chokes or payoff deficits.
4. **Deck Heritage & Vintage Spectrum:** Partitions cards into **Classic (Pre-2003)**, **Modern Frame (2003–2014)**, and **Contemporary (2015+)**, identifying the deck's Heritage Anchor Card and celebrating retro brews.

### Superpower for LLMs & AI Agents
When AI assistants (Claude Code, Cursor, ChatGPT) are asked to tune a deck or suggest cuts/adds, models routinely hallucinate card legality, mana values, and curve math, or exhaust web rate limits across 100 API calls.

With `scry deck deck.txt --json` (or the native `scryfall_deck` MCP tool), the agent receives an authoritative, ground-truth architectural diagnostic in **one single tool call (<20 ms)**. The agent can then reason with 100% mathematical accuracy without guessing.

## How it works

A local **SQLite index** built from the Oracle cache answers queries with full-text search, replacing the old approach of parsing all 38,700 cards on every call:

| | Before | Now |
|---|---|---|
| Typical lookup | ~1.6 s | **43–58 ms** |
| Peak memory per call | ~920 MB | **22–39 MB** |

The index (~102 MB) lives beside the cache and is **derived data** — delete it and it rebuilds on the next query. It builds itself the first time you search after installing or running `scry update`; `scry doctor` reports its health, and `scry reindex` forces a rebuild. If SQLite or its full-text extension is unavailable, or the index is stale or corrupt, the tool silently falls back to a full-file scan — you get yesterday's speed, never a wrong answer. Searching is offline; only `update`, `image`, and `fuzzy` resolution need internet.

## Updating the cache

Scryfall refreshes its bulk data every 12–24 hours; prices are freshest after an update. Any of these work:

```shell
scry update                                    # built-in updater (~200 MB)
./update_cache.sh                              # curl + gunzip wrapper for cron
0 3 1 * * /path/to/scry update                 # crontab example: 1st of the month
```

The updater backs up your existing cache and restores it automatically if anything fails. Note that prices reflect the last update — treat them as approximate.

## Development

Two test gates run from the repo root:

```shell
python3 tests/parity.py        # 221 checks: index results == full-scan results, ordered
python3 tests/cli_golden.py     # 22 cases: CLI stdout/stderr/exit byte-identical to baseline
```

`parity.py` proves the SQLite path and the legacy full-scan path return the same cards in the same order. `cli_golden.py` replays a recorded baseline of real invocations and diffs stdout, stderr, and exit codes byte-for-byte.

### Project layout

```
scry                  # primary executable shim
scryfall              # backwards-compatibility symlink -> scry
scry_cli/             # implementation package
  state.py            # shared state: paths, output mode, query state
  project.py          # slim_card/text_card projections + output emitters
  store.py            # SQLite sidecar: build/status/open, query helpers
  search.py           # search_* functions + filters/sort
  api.py              # Scryfall HTTP API + offline name resolution
  display.py          # pretty-mode rendering + image download
  cli.py              # argument parsing, command routing, main()
tests/
  test_deck.py        # unit tests for decklist parsing & diagnostics
  test_mcp.py         # MCP protocol & tool execution tests
  parity.py           # index-vs-full-scan parity gate
  cli_golden.py       # byte-identical CLI baseline gate
```

Imports only point downward: `state → project → store → search → api/display → cli`. `state.py` is the only module allowed to hold mutable state; everything else reads and writes `state.<NAME>` attribute access so every module sees one object.

## Contributing

Contributions, bug reports, and pull requests are welcome!

Please read our [Contributing Guidelines](CONTRIBUTING.md) for details on code style (Ruff), architectural constraints (downward imports), and running the test gates.

## Data source and Disclaimers

Card data comes from [Scryfall](https://scryfall.com), the open MTG card database (~38,000 unique cards).

**Scry Terminal is an unofficial, community-made tool.** It is not produced, endorsed, supported, or affiliated with Scryfall LLC or Wizards of the Coast.
- Magic: The Gathering is a trademark and copyright of Wizards of the Coast LLC, a subsidiary of Hasbro, Inc.
- Card data and imagery are subject to Wizards of the Coast's Fan Content Policy.
- Scryfall bulk data is provided under [Scryfall's API Guidelines and Terms](https://scryfall.com/docs/api).

## License

MIT License. See [LICENSE](LICENSE) for details.

---

*Built as part of grouphug.gg — a project about generosity, attention, and play.*
