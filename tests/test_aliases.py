#!/usr/bin/env python3
"""Unit tests for offline card name alias resolution."""
import os
import tempfile
import unittest
from unittest import mock

from scry_cli import aliases


class TestAliases(unittest.TestCase):

    def setUp(self):
        aliases.reload_aliases()

    def tearDown(self):
        aliases.reload_aliases()

    def test_bundled_aliases_loaded(self):
        alias_map = aliases.get_alias_map()
        self.assertIn("master emerald shrine", alias_map)
        self.assertEqual(alias_map["master emerald shrine"], "Command Tower")

    def test_resolve_alias_canonical_match(self):
        self.assertEqual(aliases.resolve_alias("Master Emerald Shrine"), "Command Tower")
        self.assertEqual(aliases.resolve_alias("master emerald shrine"), "Command Tower")
        self.assertEqual(aliases.resolve_alias("Godzilla, King of the Monsters"), "Zilortha, Strength Incarnate")
        self.assertEqual(aliases.resolve_alias("Eleven, the Mage"), "Cecily, Haunted Mage")
        self.assertEqual(aliases.resolve_alias("Tidus's Brotherhood Sword"), "Sword of Truth and Justice")
        # Unicode curly apostrophe
        self.assertEqual(aliases.resolve_alias("Tidus’s Brotherhood Sword"), "Sword of Truth and Justice")
        # Subphrase / weapon name without owner
        self.assertEqual(aliases.resolve_alias("Brotherhood Sword"), "Sword of Truth and Justice")

    def test_resolve_non_alias_returns_none(self):
        self.assertIsNone(aliases.resolve_alias("Sol Ring"))
        self.assertIsNone(aliases.resolve_alias("TotallyMadeUpCardName123"))
        self.assertIsNone(aliases.resolve_alias(""))
        self.assertIsNone(aliases.resolve_alias(None))

    def test_user_override_precedence(self):
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
            f.write('{"custom proxy": "Black Lotus", "master emerald shrine": "Custom Tower"}')
            temp_path = f.name

        try:
            with mock.patch("scry_cli.aliases._USER_ALIASES_PATH", temp_path):
                aliases.reload_aliases()
                self.assertEqual(aliases.resolve_alias("custom proxy"), "Black Lotus")
                self.assertEqual(aliases.resolve_alias("master emerald shrine"), "Custom Tower")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
