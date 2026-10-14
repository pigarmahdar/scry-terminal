#!/usr/bin/env python3
"""Unit tests for CLI argument parsing and help invocation."""
import io
import os
import subprocess
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from scry_cli import cli


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


if __name__ == "__main__":
    unittest.main()
