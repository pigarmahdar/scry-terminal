# Contributing to Scry Terminal

Thank you for your interest in contributing to Scry Terminal! Whether you're fixing a bug, improving query performance, adding deck diagnostics, or expanding the MCP server, we welcome your contributions.

This document outlines our engineering principles, local development setup, testing gates, and pull request workflow.

---

## Table of Contents

- [Core Principles & Architectural Invariants](#core-principles--architectural-invariants)
- [Local Development Setup](#local-development-setup)
- [Project Architecture](#project-architecture)
- [Testing & Quality Gates](#testing--quality-gates)
- [Pull Request Workflow](#pull-request-workflow)
- [Reporting Issues](#reporting-issues)

---

## Core Principles & Architectural Invariants

Scry Terminal is designed to be an ultra-fast, zero-friction tool for both human terminal users and autonomous AI agents. To preserve this, all contributions must respect the following invariants:

1. **Zero External Runtime Dependencies**  
   The core CLI, search indexer, and MCP server rely strictly on the **Python standard library** (`sqlite3`, `json`, `urllib.request`, `argparse`, etc.). Third-party dependencies (like `requests`, `pydantic`, or `rich`) must **not** be introduced into the runtime path.

2. **Sub-50ms Latency Budget**  
   Searches, card lookups, and deck diagnostics execute against local SQLite indexes and memory caches in under 50 ms. Any changes to hot query paths, regex evaluators, or card projectors must be benchmarked to prevent regressions.

3. **Strict Downward-Only Module Imports**  
   Dependencies between modules must flow strictly downward:
   ```text
   state → project → store → search → api / display → cli
   ```
   Circular dependencies and horizontal cross-imports are prohibited.

4. **Single Source of Mutable State (`state.py`)**  
   `scry_cli/state.py` is the only module allowed to hold mutable runtime state (such as `DB`, `DB_MODE`, `CARDS`, `USE_COLOR`, and `FORCE_NO_DB`). All other modules access these attributes via `state.<NAME>`. Importing any module in `scry_cli` must remain strictly side-effect free (no database opens, no disk reads, no printing).

5. **Stdout vs. Stderr Contract**  
   `stdout` is strictly reserved for pure data output (color-formatted text when attached to a TTY, or compact newline-delimited JSONL when piped). All diagnostics, warnings, and progress logs must go to `stderr` (using `state.warn(...)`). This ensures unix pipelines (`| jq`, `| grep`) and AI tool calls never fail due to mixed output.

---

## Local Development Setup

### 1. Prerequisites

- Python 3.9+
- Git

### 2. Clone and Setup Environment

```bash
# Clone your fork
git clone https://github.com/<your-username>/Scry-Terminal.git
cd Scry-Terminal

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install development & linting tools
pip install pytest ruff
```

### 3. Fetch Local Card Cache

Run `./scry update` to download the Oracle bulk card data (~200 MB) and automatically build the initial SQLite search index:

```bash
chmod +x scry
./scry update
```

Verify that the local index is healthy:

```bash
./scry doctor
```

---

## Project Architecture

```text
scry                  # Primary executable shim (prepends root to sys.path)
scryfall              # Symlink for backwards-compatibility
scry_cli/             # Core application package
├── __init__.py       # Re-exports clean API for testing harnesses
├── state.py          # Shared state & configuration (mutable state root)
├── project.py        # Card projection helpers & record serializers
├── store.py          # SQLite full-text search indexer & cache loading
├── search.py         # Query execution, filtering, and sorting
├── aliases.py        # Nickname & slang resolution (e.g. "Bob" -> Dark Confidant)
├── api.py            # Scryfall HTTP API client & fuzzy fallback resolver
├── display.py        # Terminal rendering, ANSI colorizer, image downloads
├── deck.py           # 4-pillar deck architecture & health linter
├── mcp.py            # Model Context Protocol stdio server
└── cli.py            # Argument parsing, command dispatch, and main()
tests/
├── parity.py         # Full-scan vs SQLite index parity gate (200+ checks)
├── cli_golden.py     # Byte-for-byte CLI golden regression gate
├── golden.json       # Baseline expectations for cli_golden.py
├── test_deck.py      # Unit tests for decklist parsing & diagnostics
├── test_mcp.py       # JSON-RPC unit tests for MCP tools
└── test_aliases.py   # Card nickname resolution tests
```

---

## Testing & Quality Gates

Before opening a pull request, all test suites and style checks must pass:

### 1. Code Style & Linting
We use [Ruff](https://github.com/astral-sh/ruff) for fast, consistent linting and formatting:

```bash
ruff check .
ruff format --check .
```

To auto-format files:
```bash
ruff format .
```

### 2. Regression & Parity Gates

Run the regression gates:

```bash
# 1. Parity Gate: verifies SQLite index and memory full-scan return identical results
python3 tests/parity.py

# 2. Golden Gate: ensures CLI stdout/stderr/exit codes match baseline byte-for-byte
python3 tests/cli_golden.py

# 3. Pytest suite: covers Deck Linter, MCP server, and Aliases
python3 -m pytest
```

> **Note on Golden Files:** If you intentionally alter CLI output formatting, you may update `tests/golden.json` by running:
> ```bash
> python3 tests/cli_golden.py --record
> ```
> Please clearly explain in your pull request why the output changes were necessary.

---

## Pull Request Workflow

1. **Fork & Branch**: Create a descriptive feature branch from `main`:
   ```bash
   git checkout -b feat/karsten-mana-weights
   # or
   git checkout -b fix/cli-eof-handling
   ```
2. **Make Focused Changes**: Keep commits atomic and adhere to [Conventional Commits](https://www.conventionalcommits.org/):
   - `feat(deck): ...`
   - `fix(search): ...`
   - `perf(store): ...`
   - `docs(readme): ...`
3. **Run All Gates**: Ensure `ruff`, `parity.py`, `cli_golden.py`, and `pytest` all pass cleanly.
4. **Submit PR**: Open a pull request against `main`. Include:
   - A concise description of the problem solved.
   - Any benchmark results or proof that the sub-50ms budget is maintained.
   - Confirmation that all testing gates passed.

---

## Reporting Issues

- **Card Data Discrepancies**: If a card's Oracle text, rulings, or legalities appear outdated, run `./scry update` first to refresh the local cache. If Scryfall's upstream data itself is incorrect, report it directly to [Scryfall](https://scryfall.com/contact).
- **Bug Reports**: Please include your Python version, operating system, the exact command run, and any error tracebacks output to `stderr`. For deck diagnostics bugs, attach a minimal reproducible sample decklist.
