"""Tests for scry_cli/chart.py and price history store functions."""

import os
import tempfile
import unittest

from scry_cli.chart import render_sparkline, render_trend_chart
from scry_cli.store import get_price_history, record_daily_prices
import scry_cli.state as state


class TestChart(unittest.TestCase):
    def test_sparkline_empty(self):
        self.assertEqual(render_sparkline([]), "")
        self.assertEqual(render_sparkline([None]), "")

    def test_sparkline_flat(self):
        # All same values should produce middle block
        res = render_sparkline([5.0, 5.0, 5.0])
        self.assertEqual(res, "▄▄▄")

    def test_sparkline_dynamic(self):
        res = render_sparkline([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertEqual(len(res), 5)
        self.assertEqual(res[0], " ")
        self.assertEqual(res[-1], "█")

    def test_trend_chart_empty(self):
        self.assertEqual(render_trend_chart([]), "")
        self.assertEqual(render_trend_chart([("2026-10-01", None)]), "")

    def test_trend_chart_single_point(self):
        res = render_trend_chart([("2026-10-01", 12.50)], currency="$")
        self.assertIn("1 snapshot recorded", res)
        self.assertIn("$12.50", res)

    def test_trend_chart_rising(self):
        pts = [
            ("2026-10-01", 10.0),
            ("2026-10-08", 12.0),
            ("2026-10-15", 15.0),
            ("2026-10-22", 18.0),
            ("2026-10-28", 22.0),
        ]
        res = render_trend_chart(pts, title="Rising Test", width=45, height=5, currency="$", use_color=False)
        self.assertIn("Rising Test", res)
        self.assertIn("Low: $10.00", res)
        self.assertIn("High: $22.00", res)
        self.assertIn("+120.0%", res)
        self.assertIn("┼", res)
        self.assertIn("┤", res)

    def test_trend_chart_falling(self):
        pts = [
            ("2026-10-01", 50.0),
            ("2026-10-15", 35.0),
            ("2026-10-28", 25.0),
        ]
        res = render_trend_chart(pts, title="Falling Test", width=45, height=5, currency="€", use_color=False)
        self.assertIn("Falling Test", res)
        self.assertIn("Low: €25.00", res)
        self.assertIn("High: €50.00", res)
        self.assertIn("-50.0%", res)


class TestPriceHistoryStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.orig_price_db = state.PRICE_DB_PATH
        state.PRICE_DB_PATH = os.path.join(self.temp_dir.name, "test_price_history.db")

    def tearDown(self):
        state.PRICE_DB_PATH = self.orig_price_db
        self.temp_dir.cleanup()

    def test_record_and_get_price_history(self):
        mock_cards = [
            {"name": "Sol Ring", "prices": {"usd": "1.20", "eur": "1.05", "tix": "0.02"}},
            {"name": "Black Lotus", "prices": {"usd": "15000.00", "eur": "12000.00"}},
        ]
        # Record day 1
        recorded = record_daily_prices(source=mock_cards, date_int=20261001)
        self.assertEqual(recorded, 2)

        # Record day 2 with price increase
        mock_cards[0]["prices"]["usd"] = "1.50"
        record_daily_prices(source=mock_cards, date_int=20261002)

        # Query Sol Ring
        hist = get_price_history("sol ring", currency="usd")
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[0], ("2026-10-01", 1.20))
        self.assertEqual(hist[1], ("2026-10-02", 1.50))

        # Query EUR
        hist_eur = get_price_history("sol ring", currency="eur")
        self.assertEqual(len(hist_eur), 2)
        self.assertEqual(hist_eur[0], ("2026-10-01", 1.05))

        # Query unknown card
        hist_unknown = get_price_history("nonexistent card")
        self.assertEqual(hist_unknown, [])


if __name__ == "__main__":
    unittest.main()
