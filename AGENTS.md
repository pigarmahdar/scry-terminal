# AGENTS.md — Development Guide for Autonomous AI Agents

> This document guides autonomous AI agents working on issues, bug fixes, features, and pull requests in the Scry Terminal codebase. For agent tool-calling usage instructions when querying MTG data, see [AGENT_PROMPT.md](AGENT_PROMPT.md).

## Project Overview

Scry Terminal (`scry`) is an ultra-fast, local command-line Magic: The Gathering card lookup tool, 4-pillar deck architecture linter, and zero-dependency Model Context Protocol (MCP) server. It queries Scryfall Oracle bulk data (~38,000 cards) stored locally in a SQLite FTS5 database (~102 MB) with sub-50ms latency and full offline capability. The project is implemented in Python (>=3.9) with zero external runtime dependencies, automatically adapting output between human-styled ANSI text on interactive terminals and compact JSONL for piped tools and AI harnesses.

## Verification Commands

Before opening a pull request, an agent MUST run and pass all of the following verification commands from the repository root:

### 1. Environment Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e . pytest ruff build twine
```

### 2. Linting & Formatting
```bash
# Check code style, import sorting, and linting rules
ruff check .

# Verify formatting without altering files
ruff format --check .

# To auto-format and fix trivial lint issues:
ruff format .
ruff check --fix .
```

### 3. Unit Test Suite
```bash
# Run all unit tests (uses minimal fixture cache in tests/fixtures/)
pytest tests/

# If pytest is unavailable, run via standard library unittest:
python3 -m unittest discover -s tests
```

### 4. Regression & Quality Gates
```bash
# Parity Gate: verifies SQLite FTS5 queries match legacy JSONL full-scan results
python3 tests/parity.py

# Golden Gate: verifies CLI stdout, stderr, and exit codes match baseline byte-for-byte
NO_COLOR=1 TERM=dumb python3 tests/cli_golden.py
```
> **Note on Golden Files:** Only run `python3 tests/cli_golden.py --record` if your pull request intentionally alters CLI output formatting, and explain why in your PR description.

### 5. Packaging & Distribution Build
```bash
# Build source distribution and wheel, then validate package metadata
python -m build
twine check dist/*
```

## Architecture & Code Layout

```text
scry                  # Main executable shim (prepends root to sys.path)
scryfall              # Symlink alias for backwards compatibility
pyproject.toml        # Package metadata, tool configuration (ruff, pytest), entry points
scry.spec             # PyInstaller onedir distribution spec (macOS & Linux)
scry_cli/             # Core application package (deliberately side-effect-free on import)
├── __init__.py       # Re-exports clean API for in-process harnesses; package versioning
├── state.py          # Single source of mutable runtime state (DB, CARDS, MODE, USE_COLOR)
├── store.py          # SQLite FTS5 schema, indexing, card caching, and price history
├── search.py         # Search algorithms, color/type/CMC/legalities filters, stable sorting
├── project.py        # Record projections (project_card) and output emission (emit_records)
├── deck.py           # 4-pillar deck architecture & health linter (Karsten mana, dynamic, engine, heritage)
├── mcp.py            # Zero-dependency Model Context Protocol (MCP) JSON-RPC stdio server
├── api.py            # Upstream Scryfall REST API client (urllib.request) for online fallback
├── display.py        # Terminal rendering, ANSI colorizer, table output, image downloads
├── aliases.py        # Card nickname and flavor/promo alias resolution (uses data/aliases.json)
├── chart.py          # Unicode sparklines and terminal price trend chart renderers
├── completion.py     # Shell completion generator (bash, zsh, fish)
├── onboarding.py     # Interactive first-run assistant and setup
└── cli.py            # Argument parsing (argparse), command dispatch, and main() entry point
tests/                # Test suite and quality gates
├── conftest.py       # Pytest setup pointing SCRY_ORACLE_PATH to tests/fixtures/oracle_min.jsonl
├── fixtures/         # Minimal card dataset fixture for offline/CI test execution
├── test_cli.py       # Argument parsing, help flags, and CLI error handling tests
├── test_deck.py      # Deck parser and 4-pillar architectural diagnostic tests
├── test_mcp.py       # MCP protocol JSON-RPC request/response unit tests
├── test_aliases.py   # Nickname and flavor name resolution tests
├── test_chart.py     # Sparkline and ASCII/Unicode chart rendering tests
├── parity.py         # 200+ case verification comparing SQLite FTS5 vs JSONL full-scan paths
├── cli_golden.py     # Byte-for-byte CLI output regression gate (structural/volatile/stable lanes)
└── golden.json       # Recorded golden baseline for cli_golden.py
scripts/              # Maintenance scripts (e.g. build_aliases.py)
```

## Development Guidelines

- **Minimal Diffs & YAGNI**: The best code is the code never written. Solve the immediate task with the smallest complete diff. Do not introduce speculative abstractions, wrappers, configurability, or unrequested features.
- **Strict Downward-Only Import Flow**: Dependencies between modules must flow strictly downward:
  ```text
  state → project → store → search → api / display → cli
  ```
  Circular imports and horizontal cross-imports are strictly forbidden. Importing any module must remain side-effect-free (no database opens, file reads, or output emission at import time).
- **Single State Object**: Always access and mutate shared runtime state via `scry_cli.state` attributes (e.g., `state.DB = conn`, `state.MODE = "jsonl"`). Never re-bind local copies like `from .state import DB`.
- **Output Channel Separation (Stdout vs. Stderr)**:
  - `stdout`: Strictly reserved for pure data output (ANSI formatted text for TTYs, compact JSONL for pipes or tools).
  - `stderr`: Diagnostics, progress, and warnings must exclusively use `state.warn(...)` to write to `stderr`. Never use bare `print()` for diagnostics.
- **Structured Error Handling**: In machine modes (`jsonl`, `json`, `csv`, `tsv`), exit non-zero by emitting a structured JSON error object (e.g. `{"error": "invalid_format", ...}`) to `stdout`. Do not allow raw Python tracebacks to leak to users in normal operation.
- **Typing & Formatting**: Target Python >=3.9 conventions using built-in generics (`list[dict]`, `dict[str, Any]`, `tuple[int, ...]`). Comply with Ruff rules (`line-length = 100`, import sorting `I`, errors `E`, `F`, `W`).
- **Test Coverage**: Any non-trivial logic branch, bug fix, or new command option must include unit tests in `tests/`. Always run the full verification loop (Ruff, pytest, parity, and cli_golden) before submitting a PR.

## Hard Invariants & Anti-Patterns

- **Zero Runtime Dependencies**: `pyproject.toml` `dependencies = []` must NEVER be modified. The CLI, MCP server, and deck engine must run exclusively on the Python Standard Library (`sqlite3`, `json`, `urllib.request`, `argparse`, etc.). Third-party runtime packages (e.g., `requests`, `pydantic`, `click`, `rich`) are strictly prohibited.
- **Sub-50ms Latency Budget**: The primary query path must execute in under 50 ms. Never introduce unindexed full-table scans, repetitive file deserialization, or synchronous network requests into local search commands.
- **No Side Effects on Import**: Importing `scry_cli` or any submodule must never open a SQLite connection, read the card cache from disk, or write to stdout/stderr.
- **No Schema Regressions**: Downstream LLMs, MCP consumers, and UNIX pipelines rely on the exact card record schema (`version`, `name`, `mana_cost`, `cmc`, `type_line`, `colors`, `color_identity`, `power`, `toughness`, `oracle_text`, `keywords`, `legalities`, `prices`, `image_uris`, `scryfall_uri`). Never delete, rename, or alter field types in `project_card()`. The `version` field bumps only on a breaking change; additive changes are allowed.
- **Never Commit Cache Databases**: SQLite databases (`*.db`) and Scryfall bulk downloads (`*.jsonl`) are derived data. Never commit them to Git.
- **Offline By Default**: Only `scry update`, `scry image`, and remote fuzzy fallbacks in `scry fuzzy` may access the network. All search, oracle, type, cmc, and deck commands must function 100% offline.
- **No Blind Golden Baseline Updates**: Do not re-record `tests/golden.json` to mask unexpected output diffs. Every change to the golden file must represent a deliberate, justified CLI output change.
