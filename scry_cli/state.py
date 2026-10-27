"""Shared runtime state and small output helpers.

One module = one source of truth: paths, the output mode (MODE/USE_COLOR), and
the shared query state (DB / DB_MODE / FORCE_NO_DB / CARDS) live here so every
other module reads and writes the SAME names — never a rebound copy. Modules
must mutate attributes of this module (state.MODE = ...) or declare
`global MODE` (same module), never `from state import MODE` for a mutable.
"""
import os
import sys

# ── Path to the Oracle cards cache ──────────────────────────────────────
ORACLE_PATH = (
    os.environ.get("SCRY_ORACLE_PATH")
    or os.environ.get("SCRYFALL_ORACLE_PATH")
    or os.path.expanduser("~/.hermes/scryfall/oracle-cards.jsonl")
)
DB_PATH = (
    os.environ.get("SCRY_DB_PATH")
    or os.environ.get("SCRYFALL_DB_PATH")
    or os.path.expanduser("~/.hermes/scryfall/oracle-cards.db")
)
SCHEMA_VERSION = "1"

# ── Output mode (resolved once at startup in main()) ────────────────────
MODE = "pretty"          # pretty | json | jsonl | csv | tsv
VALID_FORMATS = {"pretty", "json", "jsonl", "csv", "tsv"}

def machine_mode():
    return MODE != "pretty"

def resolve_format(explicit):
    """Decide output format. Priority: --format/--json/--pretty flag >
    $SCRY_FORMAT / $SCRYFALL_FORMAT env var > terminal auto-detection.

    Auto-detection is the human-vs-agent signal: a human typing in a terminal
    has a TTY on stdout and gets styled text; an LLM harness or script that
    captures output runs with stdout as a pipe and gets JSONL automatically.
    """
    if explicit:
        explicit = explicit.lower()
        if explicit not in VALID_FORMATS:
            # Unknown format value: emit structured error (stdout is still pure data)
            from .project import emit_single  # local: project imports state
            emit_single({"error": "invalid_format", "value": explicit,
                         "valid_formats": sorted(VALID_FORMATS)})
            sys.exit(1)
        return explicit
    env = (os.environ.get("SCRY_FORMAT") or os.environ.get("SCRYFALL_FORMAT", "")).strip().lower()
    if env in VALID_FORMATS:
        return env
    try:
        if not sys.stdout.isatty():
            return "jsonl"
    except Exception:
        return "jsonl"
    return "pretty"

def _colors_enabled(fmt):
    """ANSI styling only for interactive pretty output."""
    if fmt != "pretty":
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM", "").lower() == "dumb":
        return False
    # Piping --pretty to a file or another program must never emit escapes.
    # CI and `| cat` have no tty, where raw ANSI would corrupt the output.
    try:
        if not sys.stdout.isatty():
            return False
    except Exception:
        return False
    return True

USE_COLOR = True  # recomputed in main() after format resolution

def c(text, code):
    """Wrap text in ANSI codes unless colours are disabled. Coerces non-str."""
    text = str(text)
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text

def fmt(template, *args, **kw):
    """Format a template string with positional args (quote-safe inside c())."""
    return template.format(*args, **kw)

def warn(msg):
    """Status/warning line → stderr so stdout stays pure data in machine modes."""
    print(f"scry: {msg}", file=sys.stderr)

# ── Shared query/data state (moved verbatim; one module = one source of truth)
# DB is an open sqlite3.Connection once load_cards() has run; DB_MODE flips when
# queries are served from the sidecar; FORCE_NO_DB is set by --no-db.
DB = None
DB_MODE = False
FORCE_NO_DB = False

# ── Colour symbols for display ──────────────────────────────────────────
COLOUR_SYMBOLS = {
    "W": "⚪", "U": "🔵", "B": "⚫", "R": "🔴", "G": "🟢"
}

# ── Load all cards into memory ──────────────────────────────────────────
CARDS = []

