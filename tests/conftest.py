"""Shared pytest configuration.

Pins the card cache to a small committed fixture before ANY test module
imports scry_cli. state.py reads SCRY_ORACLE_PATH at import time and store.py
binds it by value, so setting it inside a test module is too late: whichever
test file happens to import scry_cli first freezes the path for the session.

Why this exists: the tool-call tests need real card data. CI has no
~/.hermes cache, so they failed there while passing on any developer machine
that happened to have one — the classic "works on my machine" test.

A developer's real cache is used when SCRY_ORACLE_PATH is already set, so
`SCRY_ORACLE_PATH=~/.hermes/... pytest` still tests against real data.
"""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE = os.path.join(_HERE, "fixtures", "oracle_min.jsonl")

# setdefault: an explicitly provided path always wins.
os.environ.setdefault("SCRY_ORACLE_PATH", _FIXTURE)
# A fixture cache has no SQLite sidecar; keep tests on the JSONL path.
os.environ.setdefault("SCRY_DB_PATH", os.path.join(_HERE, "fixtures", "oracle_min.db"))
