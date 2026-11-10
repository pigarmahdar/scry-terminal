# Scry Terminal

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-8A2BE2.svg)](https://modelcontextprotocol.io)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

**Instant Magic: The Gathering card lookups and deck auditing from your terminal. No API keys, no rate limits, completely offline.**

`scry` searches the entire Scryfall Oracle database (~38,000 cards) from a local SQLite index in **~50 ms**. Built for MTG brewers, script writers, and AI assistants: human-friendly colored terminal output when interactive, compact JSONL when piped, and a zero-dependency Model Context Protocol (MCP) server for LLMs.

---

[Install](#install) • 
[Quick Start](#quick-start) • 
[Deck Linter](#deck-architecture--health-linter) • 
[AI Agents & MCP](#ai-agents--mcp) • 
[Command Reference](#command-reference) • 
[Contributing](#contributing--development)

---

## Install

Requires Python 3.9+ (or use standalone prebuilt binaries) and ~200 MB disk space for the card cache.

```shell
pipx install scry-terminal
scry update   # one-time: downloads the Oracle cache & builds the search index
```

<details>
<summary><b>Alternative: Standalone Prebuilt Binaries (no Python required)</b></summary>

Prebuilt bundles for **macOS (Apple Silicon)** and **Linux (x86_64)** are attached to each [GitHub Release](https://github.com/pigarmahdar/Scry-Terminal/releases) as `scry-macos-arm64.tar.gz` and `scry-linux-x86_64.tar.gz`.

**macOS (Apple Silicon)**:
```shell
curl -L -o scry.tar.gz https://github.com/pigarmahdar/Scry-Terminal/releases/latest/download/scry-macos-arm64.tar.gz
tar xzf scry.tar.gz && sudo mv scry /usr/local/
sudo xattr -d com.apple.quarantine /usr/local/scry/scry   # clears macOS Gatekeeper block
sudo ln -sf /usr/local/scry/scry /usr/local/bin/scry
scry update
```

**Linux (x86_64)**:
```shell
curl -L -o scry.tar.gz https://github.com/pigarmahdar/Scry-Terminal/releases/latest/download/scry-linux-x86_64.tar.gz
tar xzf scry.tar.gz && sudo mv scry /usr/local/
sudo ln -sf /usr/local/scry/scry /usr/local/bin/scry
scry update
```

> **macOS Gatekeeper note:** Because these binaries are not signed with a paid Apple Developer certificate, macOS sets a quarantine attribute. The `xattr -d com.apple.quarantine` command removes it safely.
</details>

<details>
<summary><b>Alternative: pip / Git Clone</b></summary>

```shell
# Standard pip
pip install scry-terminal
scry update

# Clone for local development
git clone https://github.com/pigarmahdar/Scry-Terminal.git
cd Scry-Terminal && pip install -e .
scry update
```
</details>

Both `scry` and `scryfall` (backwards-compatible alias) are placed on your PATH automatically.

## Quick Start

```shell
scry name "Sol Ring"                       # all printings of a card
scry fuzzy "sol rng"                       # typo-tolerant and partial-name search
scry oracle "Sol Ring"                     # canonical rules text only
scry text "create a treasure token"        # search rules text
scry type "enchantment" --commander WG     # browse by type and color identity
scry cmc <=2 --legal commander --limit 5   # filter by mana value & format legality
scry image "Sol Ring"                      # download high-res art to Desktop
scry deck "my_deck.txt"                    # instant deck architecture & mana audit
```

### Auto-Switching Output (Human vs Agent)

Output formats adapt to how they are called:
- **Terminal (Interactive)**: Formatted, color-coded text.
- **Piped (`| jq`, scripts, tools)**: Automatically emits compact **JSONL** (one JSON card per line).
- **Overrides**: Use `--json`, `--jsonl`, `--csv`, or `--tsv`. Stdout is strictly reserved for data; warnings and progress go to stderr.

```shell
scry search "counter target spell" --limit 500 \
  | jq -r 'select(.legalities.modern=="legal") | .name'
```

## Deck Architecture & Health Linter

Run instant (`<20 ms`), offline architectural audits on 100-card decklists:

```shell
scry deck deck.txt                             # audit decklist file
cat deck.txt | scry deck                       # audit from pipe
pbpaste | scry deck                            # audit macOS clipboard directly
scry deck deck.txt --json                      # machine-readable diagnostic schema
```

### The 4 Diagnostic Pillars
1. **Mana Architecture & Vitals**: Compares Frank Karsten colored mana sources against colored pip demands to detect early-turn multi-pip hurdles (e.g. `{U}{U}` at CMC 2 with insufficient blue sources) and measures early playables density.
2. **Table Dynamic & Political Posture**: Categorizes card targets into **Self-Focused** (advancing board), **Targeted** (single-target removal/interaction), and **Symmetrical** (sweepers, group hug, table-wide effects).
3. **Engine Balance (Fuel vs. Payoff)**: Balances resource engines (draw, tokens, sacrifice, counters) against payoff listeners (`"Whenever you..."`) to flag engine chokes or payoff deficits.
4. **Vintage Spectrum & Heritage**: Tracks chronological distribution (**Classic Pre-2003**, **Modern Frame 2003–2014**, **Contemporary 2015+**) and surfaces your deck's Heritage Anchor card.

## AI Agents & MCP

`scry` includes a built-in Model Context Protocol (MCP) server running over stdio with **zero external dependencies**:

```shell
scry mcp
```

Add it to your MCP client configuration (`claude_desktop_config.json`, Cursor, Windsurf, Claude Code):

```json
{
  "mcpServers": {
    "scry": {
      "command": "scry",
      "args": ["mcp"]
    }
  }
}
```

- **Native MCP Tools**: `scryfall_oracle` (token-efficient rules text), `scryfall_search` (filtered card search), `scryfall_fuzzy` (typo resolution), `scryfall_deck` (4-pillar deck audit), `scryfall_price` (market prices), and `scryfall_doctor` (cache health).
- **Agent Prompts**: Point your AI assistant at [AGENT_PROMPT.md](AGENT_PROMPT.md) for output contracts, schemas, and prompting rules to prevent LLM card hallucinations.

## Command Reference

| Command | Purpose | Example |
|---|---|---|
| `name` | Search by card name (partial match) | `scry name "Gilded Drake"` |
| `oracle` | Canonical rules text only (deduplicated) | `scry oracle "Sol Ring"` |
| `fuzzy` | Typo-tolerant name lookup | `scry fuzzy "thragtuskk"` |
| `text` | Search rules/oracle text | `scry text "destroy all creatures"` |
| `type` | Search type line | `scry type "enchantment"` |
| `color` | Search by colour identity (WUBRG) | `scry color WG` |
| `cmc` | Search by mana value (`=`, `<=`, `>=`) | `scry cmc <=3` |
| `keyword` | Search keyword abilities | `scry keyword flash` |
| `price` | Search with USD, EUR, and TIX pricing | `scry price "Rhystic Study"` |
| `deck` | 4-pillar static analysis of a decklist | `scry deck deck.txt` |
| `image` | Download high-res card art to disk | `scry image "Sol Ring"` |
| `search` | General search across name, text, and type | `scry search "green creature"` |
| `random` | Fetch a random card | `scry random` |
| `mcp` | Start Model Context Protocol server on stdio | `scry mcp` |
| `update` | Download latest Oracle cache & rebuild index | `scry update` |
| `doctor` | Report cache & search index health | `scry doctor` |
| `reindex` | Force rebuild of SQLite search index | `scry reindex` |
| `completion` | Generate shell completions (`bash`, `zsh`, `fish`) | `source <(scry completion zsh)` |
| `version` | Print installed version | `scry version` |

### Common Flags

| Flag | Description |
|---|---|
| `--commander WUBRG` | Filter cards within a commander's colour identity |
| `--legal <format>` | Restrict to legal cards in a format (`commander`, `modern`, `standard`, etc.) |
| `--limit N` | Maximum results returned (default: 10) |
| `--sort <field>` | Sort by `name`, `cmc`, or `price` |
| `--exact` | Require exact name match for `name` |
| `--json` / `--jsonl` / `--csv` / `--tsv` | Explicit output format overrides |
| `--pretty` | Force color terminal output even when piped |
| `--out <dir>` / `--size <s\|n\|l\|png>` | Output directory and size for `image` |

## Cache & Maintenance

Searches run entirely offline against a local SQLite FTS5 index (~102 MB) derived from Scryfall bulk data. The index automatically creates and updates itself on demand.

- **Refresh Cache**: `scry update` downloads the latest Oracle dataset (~200 MB) from Scryfall.
- **Check Health**: `scry doctor` reports index status, card counts, and staleness.
- **Rebuild Index**: `scry reindex` forces a clean rebuild of the SQLite database.

## Contributing & Development

Contributions and pull requests are welcome!

See [CONTRIBUTING.md](CONTRIBUTING.md) for local development setup, architectural invariants (downward-only imports, zero runtime dependencies), and test quality gates (`parity.py`, `cli_golden.py`).

## Disclaimers & License

Card data and imagery courtesy of [Scryfall](https://scryfall.com). **Scry Terminal is an unofficial, community-made tool** and is not affiliated with Scryfall LLC or Wizards of the Coast LLC. Magic: The Gathering is TM & © Wizards of the Coast LLC.

Released under the [MIT License](LICENSE).

---

*Built as part of [Kwain.gg](https://pigar.me/kwaingg) — a project about generosity, attention, and play.*
