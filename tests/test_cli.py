#!/usr/bin/env python3
"""Unit tests for CLI argument parsing and help invocation."""
import io
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from scry_cli import cli  # noqa: E402


class TestCLIHelp(unittest.TestCase):

    def test_parse_args_help_flags(self):
        cmd, query, opts = cli.parse_args(["--help"])
        self.assertTrue(opts["help"])

        cmd, query, opts = cli.parse_args(["-h"])
        self.assertTrue(opts["help"])

        cmd, query, opts = cli.parse_args(["name", "Sol Ring", "--help"])
        self.assertEqual(cmd, "name")
        self.assertEqual(query, "Sol Ring")
        self.assertTrue(opts["help"])

        cmd, query, opts = cli.parse_args(["name", "Sol Ring"])
        self.assertFalse(opts["help"])

    def test_main_help_invocations(self):
        for arg in ["--help", "-h", "help"]:
            with self.subTest(arg=arg):
                buf = io.StringIO()
                with mock.patch("sys.argv", ["scry", arg]), mock.patch("sys.stdout", buf):
                    # Should return cleanly without sys.exit(1)
                    cli.main()
                out = buf.getvalue()
                self.assertIn("Usage:", out)
                self.assertIn("scry <command> <query> [options]", out)
                self.assertNotIn("unknown_flag", out)

    def test_subprocess_help(self):
        for flag in ["--help", "-h", "help"]:
            with self.subTest(flag=flag):
                res = subprocess.run(
                    [sys.executable, os.path.join(REPO, "scry"), flag],
                    capture_output=True,
                    text=True,
                    cwd=REPO,
                )
                self.assertEqual(res.returncode, 0)
                self.assertIn("Usage:", res.stdout)
                self.assertIn("scry (Scry Terminal)", res.stdout)
                self.assertNotIn("unknown_flag", res.stdout)
                self.assertEqual(res.stderr.strip(), "")


class TestCLIErgonomics(unittest.TestCase):

    def test_version_flags_and_command(self):
        for flag in ["--version", "-v", "-V"]:
            with self.subTest(flag=flag):
                cmd, query, opts = cli.parse_args([flag])
                self.assertTrue(opts["version"])

        # CLI invocation in human mode
        for arg in ["--version", "-v", "version"]:
            with self.subTest(arg=arg):
                buf = io.StringIO()
                with mock.patch("sys.argv", ["scry", arg, "--pretty"]), mock.patch("sys.stdout", buf):
                    cli.main()
                self.assertIn("scry ", buf.getvalue())

        # CLI invocation in json mode
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scry", "--version", "--json"]), mock.patch("sys.stdout", buf):
            cli.main()
        data = json.loads(buf.getvalue().strip())
        self.assertIn("version", data)

    def test_unknown_command_suggestions(self):
        # Typo match (orcle -> oracle)
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scry", "orcle", "Sol Ring", "--pretty"]), mock.patch("sys.stdout", buf):
            with self.assertRaises(SystemExit) as ctx:
                cli.main()
            self.assertEqual(ctx.exception.code, 1)
        out = buf.getvalue()
        self.assertIn("Did you mean: scry oracle \"Sol Ring\"?", out)

        # Machine mode typo match
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scry", "orcle", "Sol Ring", "--json"]), mock.patch("sys.stdout", buf):
            with self.assertRaises(SystemExit) as ctx:
                cli.main()
            self.assertEqual(ctx.exception.code, 1)
        data = json.loads(buf.getvalue().strip())
        self.assertEqual(data["error"], "unknown_command")
        self.assertEqual(data["suggestion"], "oracle")

        # Unknown card name query without command
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scry", "Sol Ring", "--pretty"]), mock.patch("sys.stdout", buf):
            with self.assertRaises(SystemExit) as ctx:
                cli.main()
            self.assertEqual(ctx.exception.code, 1)
        out = buf.getvalue()
        self.assertIn("scry search \"sol ring\"", out)
        self.assertIn("scry name \"sol ring\"", out)

        # Machine mode card name query without command
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scry", "Sol Ring", "--json"]), mock.patch("sys.stdout", buf):
            with self.assertRaises(SystemExit) as ctx:
                cli.main()
            self.assertEqual(ctx.exception.code, 1)
        data = json.loads(buf.getvalue().strip())
        self.assertEqual(data["error"], "unknown_command")
        self.assertIn("scry search \"sol ring\"", data["suggestions"])

    def test_completion_generation(self):
        for shell, signature in [
            ("zsh", "#compdef scry scryfall"),
            ("bash", "complete -F _scry_completions scry scryfall"),
            ("fish", "complete -c scry -c scryfall"),
        ]:
            with self.subTest(shell=shell):
                buf = io.StringIO()
                with mock.patch("sys.argv", ["scry", "completion", shell]), mock.patch("sys.stdout", buf):
                    cli.main()
                self.assertIn(signature, buf.getvalue())

        # Bad shell in human mode
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scry", "completion", "invalid_shell", "--pretty"]), mock.patch("sys.stdout", buf):
            with self.assertRaises(SystemExit) as ctx:
                cli.main()
            self.assertEqual(ctx.exception.code, 1)
        self.assertIn("Invalid or missing shell", buf.getvalue())

        # Bad shell in machine mode
        buf = io.StringIO()
        with mock.patch("sys.argv", ["scry", "completion", "invalid_shell", "--json"]), mock.patch("sys.stdout", buf):
            with self.assertRaises(SystemExit) as ctx:
                cli.main()
            self.assertEqual(ctx.exception.code, 1)
        data = json.loads(buf.getvalue().strip())
        self.assertEqual(data["error"], "invalid_shell")


class TestOnboarding(unittest.TestCase):

    def setUp(self):
        from scry_cli import state
        self._orig_db = state.DB
        self._orig_db_mode = state.DB_MODE
        self._orig_cards = state.CARDS
        state.DB = None
        state.DB_MODE = False
        state.CARDS = []

    def tearDown(self):
        from scry_cli import state
        state.DB = self._orig_db
        state.DB_MODE = self._orig_db_mode
        state.CARDS = self._orig_cards

    def test_missing_cache_machine_mode(self):
        buf = io.StringIO()
        with mock.patch("os.path.exists", return_value=False), \
             mock.patch("sys.argv", ["scry", "search", "Sol Ring", "--json"]), \
             mock.patch("sys.stdout", buf):
            with self.assertRaises(SystemExit) as ctx:
                cli.main()
            self.assertEqual(ctx.exception.code, 1)
        data = json.loads(buf.getvalue().strip())
        self.assertEqual(data["error"], "missing_cache")
        self.assertIn("scry update", data["action"])

    def test_missing_cache_interactive_decline(self):
        buf = io.StringIO()
        buf.isatty = lambda: True
        with mock.patch("os.path.exists", return_value=False), \
             mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", return_value="n"), \
             mock.patch("sys.argv", ["scry", "search", "Sol Ring", "--pretty"]), \
             mock.patch("sys.stdout", buf):
            with self.assertRaises(SystemExit) as ctx:
                cli.main()
            self.assertEqual(ctx.exception.code, 0)
        self.assertIn("Happy brewing!", buf.getvalue())

    def test_missing_cache_interactive_interrupt(self):
        buf = io.StringIO()
        buf.isatty = lambda: True
        with mock.patch("os.path.exists", return_value=False), \
             mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", side_effect=KeyboardInterrupt), \
             mock.patch("sys.argv", ["scry", "search", "Sol Ring", "--pretty"]), \
             mock.patch("sys.stdout", buf):
            with self.assertRaises(SystemExit) as ctx:
                cli.main()
            self.assertEqual(ctx.exception.code, 0)
        self.assertIn("Setup cancelled", buf.getvalue())

    def test_missing_cache_interactive_accept(self):
        buf = io.StringIO()
        buf.isatty = lambda: True
        mock_update = mock.MagicMock()
        # check_cache_age and load_cards both check exists initially
        exists_mock = mock.MagicMock(side_effect=[False, False, True, True, True, True, True])
        with mock.patch("scry_cli.store.os.path.exists", exists_mock), \
             mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", return_value="y"), \
             mock.patch("scry_cli.cli.handle_update", mock_update), \
             mock.patch("scry_cli.store.open_db", return_value=mock.MagicMock()), \
             mock.patch("scry_cli.store.db_status", return_value=(False, "fresh")), \
             mock.patch("sys.argv", ["scry", "search", "Sol Ring", "--pretty"]), \
             mock.patch("sys.stdout", buf):
            try:
                cli.main()
            except Exception:
                pass
        self.assertIn("Welcome to Scry Terminal", buf.getvalue())
        self.assertIn("Database ready", buf.getvalue())
        mock_update.assert_called_once()


if __name__ == "__main__":
    unittest.main()
