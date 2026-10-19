#!/usr/bin/env python3
"""Comprehensive unit tests for scry_cli/deck.py."""
import unittest
from unittest import mock

from scry_cli import deck, state


class TestDeckParser(unittest.TestCase):

    def test_clean_card_name(self):
        self.assertEqual(deck.clean_card_name("Sol Ring (LCC) 211 *F*"), "Sol Ring")
        self.assertEqual(deck.clean_card_name("Lightning Bolt [M10:146] #foil"), "Lightning Bolt")
        self.assertEqual(deck.clean_card_name("Counterspell *F*"), "Counterspell")
        self.assertEqual(deck.clean_card_name("Fire/Ice"), "Fire // Ice")
        self.assertEqual(deck.clean_card_name("Fire // Ice"), "Fire // Ice")
        self.assertEqual(deck.clean_card_name("  Birds of Paradise  "), "Birds of Paradise")

    def test_parse_decklist_formats(self):
        sample = """
// Commander
1 Atraxa, Praetors' Voice (2XM) 198 *F*

// Mainboard
1 Sol Ring
4x Brainstorm
Swamp
1 Fire/Ice (UMA) 225
# Comment line
// Non-section comment
        """
        entries = deck.parse_decklist(sample)
        self.assertEqual(len(entries), 5)

        self.assertEqual(entries[0]["name"], "Atraxa, Praetors' Voice")
        self.assertEqual(entries[0]["count"], 1)
        self.assertEqual(entries[0]["section"], "commander")

        self.assertEqual(entries[1]["name"], "Sol Ring")
        self.assertEqual(entries[1]["count"], 1)
        self.assertEqual(entries[1]["section"], "mainboard")

        self.assertEqual(entries[2]["name"], "Brainstorm")
        self.assertEqual(entries[2]["count"], 4)

        self.assertEqual(entries[3]["name"], "Swamp")
        self.assertEqual(entries[3]["count"], 1)

        self.assertEqual(entries[4]["name"], "Fire // Ice")
        self.assertEqual(entries[4]["count"], 1)


class TestDeckDiagnostics(unittest.TestCase):

    def setUp(self):
        # Create mock cards for testing diagnostic calculations
        self.card_commander = {
            "name": "Tam, Mindful First-Year",
            "mana_cost": "{1}{W}{U}",
            "cmc": 3.0,
            "type_line": "Legendary Creature — Human Wizard",
            "colors": ["W", "U"],
            "color_identity": ["W", "U"],
            "oracle_text": "Whenever you draw your second card each turn, create a 1/1 white Bird token.",
            "legalities": {"commander": "legal", "premodern": "not_legal", "predh": "not_legal"},
            "prices": {"usd": 5.0},
        }
        self.card_sol_ring = {
            "name": "Sol Ring",
            "mana_cost": "{1}",
            "cmc": 1.0,
            "type_line": "Artifact",
            "colors": [],
            "color_identity": [],
            "oracle_text": "{T}: Add {C}{C}.",
            "legalities": {"commander": "legal", "premodern": "not_legal", "predh": "legal"},
            "prices": {"usd": 1.5},
        }
        self.card_howling_mine = {
            "name": "Howling Mine",
            "mana_cost": "{2}",
            "cmc": 2.0,
            "type_line": "Artifact",
            "colors": [],
            "color_identity": [],
            "oracle_text": "At the beginning of each player's draw step, if Howling Mine is untapped, that player draws an additional card.",
            "legalities": {"commander": "legal", "premodern": "legal", "predh": "legal"},
            "prices": {"usd": 4.0},
        }
        self.card_sleight = {
            "name": "Sleight of Mind",
            "mana_cost": "{U}",
            "cmc": 1.0,
            "type_line": "Instant",
            "colors": ["U"],
            "color_identity": ["U"],
            "oracle_text": "Change the text of target spell or permanent by replacing all instances of one color word with another.",
            "legalities": {"commander": "legal", "premodern": "legal", "predh": "legal"},
            "prices": {"usd": 2.0},
        }
        self.card_counterspell = {
            "name": "Counterspell",
            "mana_cost": "{U}{U}",
            "cmc": 2.0,
            "type_line": "Instant",
            "colors": ["U"],
            "color_identity": ["U"],
            "oracle_text": "Counter target spell.",
            "legalities": {"commander": "legal", "premodern": "legal", "predh": "legal"},
            "prices": {"usd": 1.0},
        }
        self.card_island = {
            "name": "Island",
            "mana_cost": "",
            "cmc": 0.0,
            "type_line": "Basic Land — Island",
            "colors": [],
            "color_identity": ["U"],
            "oracle_text": "{T}: Add {U}.",
            "legalities": {"commander": "legal", "premodern": "legal", "predh": "legal"},
            "prices": {"usd": 0.1},
        }
        self.card_plains = {
            "name": "Plains",
            "mana_cost": "",
            "cmc": 0.0,
            "type_line": "Basic Land — Plains",
            "colors": [],
            "color_identity": ["W"],
            "oracle_text": "{T}: Add {W}.",
            "legalities": {"commander": "legal", "premodern": "legal", "predh": "legal"},
            "prices": {"usd": 0.1},
        }
        self.card_banned = {
            "name": "Mana Crypt",
            "mana_cost": "{0}",
            "cmc": 0.0,
            "type_line": "Artifact",
            "colors": [],
            "color_identity": [],
            "oracle_text": "{T}: Add {C}{C}.",
            "legalities": {"commander": "banned", "premodern": "not_legal", "predh": "legal"},
            "prices": {"usd": 180.0},
        }
        self.card_off_color = {
            "name": "Lightning Bolt",
            "mana_cost": "{R}",
            "cmc": 1.0,
            "type_line": "Instant",
            "colors": ["R"],
            "color_identity": ["R"],
            "oracle_text": "Lightning Bolt deals 3 damage to any target.",
            "legalities": {"commander": "legal", "premodern": "legal", "predh": "legal"},
            "prices": {"usd": 1.0},
        }

    def test_analyze_mana_and_karsten_hurdles(self):
        items = [
            {"entry": {"count": 1, "name": "Counterspell", "section": "main"}, "card": self.card_counterspell},
            {"entry": {"count": 10, "name": "Island", "section": "main"}, "card": self.card_island},
            {"entry": {"count": 10, "name": "Plains", "section": "main"}, "card": self.card_plains},
            {"entry": {"count": 1, "name": "Sol Ring", "section": "main"}, "card": self.card_sol_ring},
        ]
        mana = deck.analyze_mana(items)
        self.assertEqual(mana["lands_count"], 20)
        self.assertEqual(mana["ramp_count"], 1)
        self.assertEqual(mana["non_lands_count"], 2)
        # Counterspell requires {U}{U} with 10 islands -> flags hurdle (recommends 21+)
        self.assertEqual(len(mana["early_hurdles"]), 1)
        self.assertEqual(mana["early_hurdles"][0]["card"], "Counterspell")
        self.assertEqual(mana["early_hurdles"][0]["current_sources"], 10)
        self.assertEqual(mana["early_hurdles"][0]["recommended_sources"], 21)

    def test_table_dynamic(self):
        items = [
            # Howling Mine has "each player" -> Symmetrical
            {"entry": {"count": 1, "name": "Howling Mine", "section": "main"}, "card": self.card_howling_mine},
            # Counterspell has "counter target spell" -> Targeted
            {"entry": {"count": 1, "name": "Counterspell", "section": "main"}, "card": self.card_counterspell},
            # Sleight of Mind has "target spell" -> Targeted
            {"entry": {"count": 1, "name": "Sleight of Mind", "section": "main"}, "card": self.card_sleight},
            # Sol Ring -> Self-focused
            {"entry": {"count": 1, "name": "Sol Ring", "section": "main"}, "card": self.card_sol_ring},
        ]
        dyn = deck.analyze_table_dynamic(items)
        self.assertEqual(dyn["symmetrical_count"], 1)
        self.assertEqual(dyn["targeted_count"], 2)
        self.assertEqual(dyn["self_count"], 1)
        self.assertIn("posture", dyn)

    def test_engine_balance(self):
        items = [
            # Enabler: draws a card
            {"entry": {"count": 4, "name": "Howling Mine", "section": "main"}, "card": self.card_howling_mine},
            # Payoff: whenever you draw
            {"entry": {"count": 2, "name": "Tam, Mindful First-Year", "section": "main"}, "card": self.card_commander},
        ]
        eng = deck.analyze_engine_balance(items)
        self.assertEqual(eng["fuel_count"], 4)
        self.assertEqual(eng["payoff_count"], 2)
        self.assertEqual(eng["ratio"], 2.0)
        self.assertEqual(eng["diagnostic"], "Stable Flow Buffer")

    def test_heritage(self):
        items = [
            # Premodern legal -> Classic era
            {"entry": {"count": 1, "name": "Howling Mine", "section": "main"}, "card": self.card_howling_mine},
            # Predh legal -> Modern frame era
            {"entry": {"count": 1, "name": "Sol Ring", "section": "main"}, "card": self.card_sol_ring},
            # Neither -> Contemporary era
            {"entry": {"count": 1, "name": "Tam, Mindful First-Year", "section": "main"}, "card": self.card_commander},
        ]
        her = deck.analyze_heritage(items)
        self.assertEqual(her["classic_count"], 1)
        self.assertEqual(her["modern_count"], 1)
        self.assertEqual(her["contemporary_count"], 1)
        self.assertIn("Howling Mine", her["anchor_card"])

    def test_audit_legality(self):
        items = [
            {"entry": {"count": 1, "name": "Mana Crypt", "section": "main"}, "card": self.card_banned},
            {"entry": {"count": 1, "name": "Lightning Bolt", "section": "main"}, "card": self.card_off_color},
            {"entry": {"count": 2, "name": "Counterspell", "section": "main"}, "card": self.card_counterspell},
        ]
        audit = deck.audit_legality(items, commander_card=self.card_commander, target_format="commander")
        self.assertFalse(audit["is_legal"])
        self.assertIn("Mana Crypt", audit["banned_cards"])
        self.assertEqual(len(audit["color_identity_violations"]), 1)
        self.assertEqual(audit["color_identity_violations"][0]["card"], "Lightning Bolt")
        self.assertIn("Counterspell (2 copies)", audit["singleton_violations"])


class TestDeckResolutionFallback(unittest.TestCase):

    def setUp(self):
        self._orig_cards = state.CARDS
        self._orig_db_mode = state.DB_MODE
        self._orig_force = state.FORCE_NO_DB
        self._orig_db = state.DB

    def tearDown(self):
        state.CARDS = self._orig_cards
        state.DB_MODE = self._orig_db_mode
        state.FORCE_NO_DB = self._orig_force
        state.DB = self._orig_db

    def test_offline_fallback_with_memory_cards(self):
        state.CARDS = [
            {
                "name": "Delver of Secrets // Insectile Aberration",
                "mana_cost": "{U}",
                "cmc": 1.0,
                "type_line": "Creature — Human Wizard // Creature — Insectile Aberration",
                "colors": ["U"],
                "color_identity": ["U"],
                "oracle_text": "Transform at upkeep.",
                "legalities": {"commander": "legal"},
                "prices": {},
            }
        ]
        state.DB_MODE = False

        entries = [{"count": 1, "name": "Delver of Secrets", "section": "main"}]
        resolved, unresolved = deck.resolve_deck_cards(entries)
        self.assertEqual(len(resolved), 1)
        self.assertEqual(len(unresolved), 0)
        self.assertEqual(resolved[0]["card"]["name"], "Delver of Secrets // Insectile Aberration")

    def test_alias_resolution_master_emerald_shrine(self):
        state.CARDS = [
            {
                "name": "Command Tower",
                "mana_cost": "",
                "cmc": 0.0,
                "type_line": "Land",
                "colors": [],
                "color_identity": [],
                "oracle_text": "{T}: Add one mana of any color in your commander's color identity.",
                "legalities": {"commander": "legal"},
                "prices": {"usd": "0.25"},
            }
        ]
        state.DB_MODE = False

        entries = [{"count": 1, "name": "Master Emerald Shrine", "section": "main"}]
        resolved, unresolved = deck.resolve_deck_cards(entries)
        self.assertEqual(len(unresolved), 0)
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["card"]["name"], "Command Tower")
        self.assertEqual(resolved[0]["original_alias"], "Master Emerald Shrine")

    def test_clean_card_name_dual_alias(self):
        # Dual-name syntax like "Master Emerald Shrine (Command Tower)"
        cleaned = deck.clean_card_name("Master Emerald Shrine (Command Tower)")
        self.assertIn(cleaned, ("Master Emerald Shrine", "Command Tower"))

    def test_run_deck_analysis_reports_resolved_aliases(self):
        state.CARDS = [
            {
                "name": "Command Tower",
                "mana_cost": "",
                "cmc": 0.0,
                "type_line": "Land",
                "colors": [],
                "color_identity": [],
                "oracle_text": "{T}: Add one mana of any color.",
                "legalities": {"commander": "legal"},
                "prices": {"usd": "0.25"},
            },
            {
                "name": "Baral, Chief of Compliance",
                "mana_cost": "{1}{U}",
                "cmc": 2.0,
                "type_line": "Legendary Creature — Human Wizard",
                "colors": ["U"],
                "color_identity": ["U"],
                "oracle_text": "Spells cost {1} less.",
                "legalities": {"commander": "legal"},
                "prices": {"usd": "2.00"},
            }
        ]
        state.DB_MODE = False

        deck_txt = """
        // Commander
        1 Baral, Chief of Compliance

        // Mainboard
        1 Master Emerald Shrine
        """
        res = deck.run_deck_analysis(deck_txt, deck_name="Test Deck", target_format="commander")
        self.assertEqual(len(res["unresolved_cards"]), 0)
        self.assertEqual(len(res["resolved_aliases"]), 1)
        self.assertEqual(res["resolved_aliases"][0]["alias"], "Master Emerald Shrine")
        self.assertEqual(res["resolved_aliases"][0]["canonical"], "Command Tower")

    @mock.patch("scry_cli.api.scryfall_fuzzy")
    def test_online_fallback_resolution(self, mock_fuzzy):
        mock_fuzzy.return_value = {
            "name": "Sword of Truth and Justice",
            "flavor_name": "Tidus's Ancient Relic",
            "mana_cost": "{3}",
            "cmc": 3.0,
            "type_line": "Artifact — Equipment",
            "colors": [],
            "color_identity": [],
            "oracle_text": "Equipped creature gets +2/+2.",
            "legalities": {"commander": "legal"},
            "prices": {"usd": "12.00"},
        }
        state.CARDS = []
        state.DB_MODE = False

        entries = [{"count": 1, "name": "Tidus's Ancient Relic", "section": "main"}]
        with mock.patch("scry_cli.aliases.save_user_alias") as mock_save:
            resolved, unresolved = deck.resolve_deck_cards(entries, offline=False)
            self.assertEqual(len(unresolved), 0)
            self.assertEqual(len(resolved), 1)
            self.assertEqual(resolved[0]["card"]["name"], "Sword of Truth and Justice")
            self.assertTrue(resolved[0].get("discovered_online"))
            mock_save.assert_called_once_with("tidus's ancient relic", "Sword of Truth and Justice")


if __name__ == "__main__":
    unittest.main()

