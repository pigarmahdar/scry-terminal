"""scryfall_cli — package form of the `scryfall` CLI.

Deliberately side-effect-free: importing this package must never open the
index, touch argv, or print. Entry point is `scryfall_cli.cli.main()`.

The names re-exported here are exactly the surface the parity harness and any
other in-process consumer needs — they used to be trivially reachable because
the whole tool was one module. Mutable state (DB / DB_MODE / CARDS / MODE /
USE_COLOR / FORCE_NO_DB) is NOT re-exported: import `scryfall_cli.state` and
mutate its attributes so every module sees one object.
"""
from .project import slim_card, text_card, emit_records, emit_single  # noqa: F401
from .state import machine_mode, resolve_format, warn, c, fmt  # noqa: F401
from .store import load_cards, open_db, db_status, build_db, check_cache_age  # noqa: F401
from .search import (  # noqa: F401
    search_name, search_text, search_type, search_color, search_cmc,
    search_keyword, search_general, search_random, search_oracle,
    apply_filters, sort_results,
)
from .api import scryfall_fuzzy, scryfall_autocomplete, _resolve_card  # noqa: F401
from .display import (  # noqa: F401
    display_card, display_oracle_card, display_api_card, display_price_card,
)
from .cli import main, parse_args, VALID_COMMANDS  # noqa: F401
