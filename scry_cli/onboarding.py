"""First-run onboarding experience for Scry Terminal."""
import sys


def handle_missing_cache() -> None:
    """Handle missing cache: conversational prompt if interactive, error if machine/agent."""
    from .project import emit_single
    from .state import ORACLE_PATH, c, machine_mode

    # Machine / Script / LLM mode: do not prompt, emit structured error
    if machine_mode() or not (sys.stdin.isatty() and sys.stdout.isatty()):
        if machine_mode():
            emit_single(
                {
                    "error": "missing_cache",
                    "message": f"Oracle card cache not found at {ORACLE_PATH}.",
                    "action": "Run 'scry update' to initialize the local card database (~200 MB).",
                }
            )
        else:
            print(
                f"\n  Error: Oracle card cache not found at {ORACLE_PATH}",
                file=sys.stderr,
            )
            print(
                "  Run 'scry update' to initialize the local card database (~200 MB).\n",
                file=sys.stderr,
            )
        sys.exit(1)

    # Interactive TTY: Conversational Welcome & Onboarding
    print("\n  " + c("✨ Welcome to Scry Terminal! Thanks for installing.", "1;33"))
    print("\n  To search all 38,000+ Magic cards completely offline in ~50 ms,")
    print("  Scry needs to download Scryfall's bulk Oracle dataset (~200 MB).")

    try:
        choice = (
            input(
                "\n  Would you like to download and index the card database now? [Y/n]: "
            )
            .strip()
            .lower()
        )
    except (KeyboardInterrupt, EOFError):
        print("\n\n  Setup cancelled. Run 'scry update' whenever you're ready.\n")
        sys.exit(0)

    if choice in ("", "y", "yes"):
        print()
        from .cli import handle_update

        handle_update()
        print(
            "  "
            + c(
                "✨ Database ready! May your draws be smooth and your brews unstoppable.",
                "1;32",
            )
        )
        print("\n  Quick lookups to try:")
        print(
            "    "
            + c('scry oracle "Sol Ring"', "1;36")
            + "                  # canonical rules text"
        )
        print(
            "    "
            + c('scry text "create a treasure token"', "1;36")
            + "     # search card text"
        )
        print(
            "    "
            + c("scry deck my_deck.txt", "1;36")
            + "                   # instant 4-pillar deck audit\n"
        )
    else:
        print(
            "\n  No problem! When you're ready to set up your local cache, just run:"
        )
        print("    " + c("scry update", "1;36"))
        print("\n  Happy brewing!\n")
        sys.exit(0)
