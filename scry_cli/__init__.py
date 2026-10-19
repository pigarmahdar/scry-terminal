"""scry_cli — package form of Scry Terminal (`scry`).

Deliberately side-effect-free: importing this package must never open the
index, touch argv, or print. Entry point is `scry_cli.cli.main()`.

The names re-exported here are exactly the surface the parity harness and any
other in-process consumer needs. Mutable state (DB / DB_MODE / CARDS / MODE /
USE_COLOR / FORCE_NO_DB) is NOT re-exported: import `scry_cli.state` and
mutate its attributes so every module sees one object.
"""
from .api import _resolve_card, scryfall_autocomplete, scryfall_fuzzy  # noqa: F401
from .cli import VALID_COMMANDS, main, parse_args  # noqa: F401
from .display import (  # noqa: F401
    display_api_card,
    display_card,
    display_oracle_card,
    display_price_card,
)
from .mcp import run_mcp_server  # noqa: F401
from .project import emit_records, emit_single, slim_card, text_card  # noqa: F401
from .search import (  # noqa: F401
    apply_filters,
    search_cmc,
    search_color,
    search_general,
    search_keyword,
    search_name,
    search_oracle,
    search_random,
    search_text,
    search_type,
    sort_results,
)
from .state import c, fmt, machine_mode, resolve_format, warn  # noqa: F401
from .store import build_db, check_cache_age, db_status, load_cards, open_db  # noqa: F401
