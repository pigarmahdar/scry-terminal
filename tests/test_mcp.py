#!/usr/bin/env python3
"""Tests for scryfall-mcp (Model Context Protocol JSON-RPC server).

Verifies protocol lifecycle, tool schema exposure, and tool execution.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

# These tests exercise real tool behaviour, so they need card data. Point the
# cache at a small committed fixture BEFORE importing scry_cli: state.py reads
# SCRY_ORACLE_PATH at import and store.py binds it by value, so setting it
# later has no effect. Without this, CI (which has no ~/.hermes cache) failed
# all seven tool-call tests while a developer machine with a cache passed.
os.environ["SCRY_ORACLE_PATH"] = os.path.join(HERE, "fixtures", "oracle_min.jsonl")
os.environ.setdefault("SCRY_DB_PATH", os.path.join(HERE, "fixtures", "oracle_min.db"))

from scry_cli import mcp  # noqa: E402


class TestMCPServer(unittest.TestCase):

    def test_initialize(self):
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        }
        resp = mcp.handle_request(req)
        self.assertIsNotNone(resp)
        self.assertEqual(resp.get("jsonrpc"), "2.0")
        self.assertEqual(resp.get("id"), 1)
        res = resp.get("result", {})
        self.assertEqual(res.get("protocolVersion"), "2024-11-05")
        self.assertIn("tools", res.get("capabilities", {}))
        self.assertEqual(res.get("serverInfo", {}).get("name"), "scryfall-mcp")

    def test_notifications_initialized(self):
        req = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        resp = mcp.handle_request(req)
        self.assertIsNone(resp, "Notifications must not produce a JSON-RPC response")

    def test_ping(self):
        req = {
            "jsonrpc": "2.0",
            "id": 42,
            "method": "ping",
        }
        resp = mcp.handle_request(req)
        self.assertEqual(resp, {"jsonrpc": "2.0", "id": 42, "result": {}})

    def test_tools_list(self):
        req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        }
        resp = mcp.handle_request(req)
        self.assertIsNotNone(resp)
        tools = resp.get("result", {}).get("tools", [])
        tool_names = {t["name"] for t in tools}
        expected = {
            "scryfall_oracle",
            "scryfall_search",
            "scryfall_fuzzy",
            "scryfall_price",
            "scryfall_doctor",
        }
        self.assertTrue(expected.issubset(tool_names), f"Missing tools in: {tool_names}")

        for tool in tools:
            self.assertIn("description", tool)
            self.assertIn("inputSchema", tool)
            self.assertEqual(tool["inputSchema"]["type"], "object")

    def test_tool_call_doctor(self):
        req = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "scryfall_doctor",
                "arguments": {},
            },
        }
        resp = mcp.handle_request(req)
        self.assertIsNotNone(resp)
        result = resp.get("result", {})
        self.assertFalse(result.get("isError", True))
        content = result.get("content", [])
        self.assertEqual(len(content), 1)
        data = json.loads(content[0]["text"])
        self.assertIn("schema_version", data)
        self.assertIn("db_path", data)

    def test_tool_call_unknown_tool(self):
        req = {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {
                "name": "non_existent_tool_xyz",
                "arguments": {},
            },
        }
        resp = mcp.handle_request(req)
        self.assertIsNotNone(resp)
        result = resp.get("result", {})
        self.assertTrue(result.get("isError"))
        self.assertIn("Unknown tool", result["content"][0]["text"])

    def test_unknown_method(self):
        req = {
            "jsonrpc": "2.0",
            "id": 101,
            "method": "some_random_method",
            "params": {},
        }
        resp = mcp.handle_request(req)
        self.assertIsNotNone(resp)
        err = resp.get("error", {})
        self.assertEqual(err.get("code"), -32601)

    def test_invalid_request(self):
        resp = mcp.handle_request("not-a-dict")
        self.assertIsNotNone(resp)
        err = resp.get("error", {})
        self.assertEqual(err.get("code"), -32600)

    def test_tool_call_oracle(self):
        req = {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "scryfall_oracle",
                "arguments": {"name": "Sol Ring"},
            },
        }
        resp = mcp.handle_request(req)
        self.assertIsNotNone(resp)
        res = resp.get("result", {})
        self.assertFalse(res.get("isError", True))
        data = json.loads(res["content"][0]["text"])
        self.assertEqual(data["query"], "Sol Ring")
        self.assertGreater(data["total_matches"], 0)
        self.assertTrue(any(c["name"] == "Sol Ring" for c in data["cards"]))

    def test_tool_call_search(self):
        req = {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {
                "name": "scryfall_search",
                "arguments": {"query": "counter target spell", "limit": 2},
            },
        }
        resp = mcp.handle_request(req)
        self.assertIsNotNone(resp)
        res = resp.get("result", {})
        self.assertFalse(res.get("isError", True))
        data = json.loads(res["content"][0]["text"])
        self.assertEqual(data["shown_matches"], 2)
        self.assertEqual(len(data["cards"]), 2)

    def test_tool_call_fuzzy_sol_rng(self):
        # Issue 1: "Sol Rng" must resolve to Sol Ring, not Oathsworn Giant
        req = {
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {
                "name": "scryfall_fuzzy",
                "arguments": {"name": "Sol Rng"},
            },
        }
        resp = mcp.handle_request(req)
        self.assertIsNotNone(resp)
        res = resp.get("result", {})
        self.assertFalse(res.get("isError", True))
        data = json.loads(res["content"][0]["text"])
        self.assertEqual(data["query"], "Sol Rng")
        self.assertIsNotNone(data.get("match"))
        self.assertEqual(data["match"]["name"], "Sol Ring")
        self.assertIsInstance(data.get("candidates"), list)
        self.assertGreater(len(data["candidates"]), 0)

    def test_tool_call_search_commander_wubrg(self):
        # Issue 2: commander with WUBRG letters
        req = {
            "jsonrpc": "2.0",
            "id": 14,
            "method": "tools/call",
            "params": {
                "name": "scryfall_search",
                "arguments": {"query": "destroy", "commander": "RGW", "limit": 10},
            },
        }
        resp = mcp.handle_request(req)
        self.assertIsNotNone(resp)
        res = resp.get("result", {})
        self.assertFalse(res.get("isError", True))
        data = json.loads(res["content"][0]["text"])
        allowed = {"R", "G", "W"}
        for card in data["cards"]:
            self.assertTrue(set(card.get("color_identity", [])).issubset(allowed))

    def test_tool_call_search_commander_card_name(self):
        # Issue 2: commander with card name (Kwain is White/Blue)
        req = {
            "jsonrpc": "2.0",
            "id": 15,
            "method": "tools/call",
            "params": {
                "name": "scryfall_search",
                "arguments": {"query": "destroy", "commander": "Kwain, Itinerant Meddler", "limit": 20},
            },
        }
        resp = mcp.handle_request(req)
        self.assertIsNotNone(resp)
        res = resp.get("result", {})
        self.assertFalse(res.get("isError", True))
        data = json.loads(res["content"][0]["text"])
        allowed = {"W", "U"}
        for card in data["cards"]:
            self.assertTrue(set(card.get("color_identity", [])).issubset(allowed))
            self.assertNotIn("G", card.get("color_identity", []))

    def test_tool_call_search_commander_invalid(self):
        # Issue 2: invalid commander returns an MCP error
        req = {
            "jsonrpc": "2.0",
            "id": 16,
            "method": "tools/call",
            "params": {
                "name": "scryfall_search",
                "arguments": {"query": "destroy", "commander": "NonExistentCardXYZ123"},
            },
        }
        resp = mcp.handle_request(req)
        self.assertIsNotNone(resp)
        res = resp.get("result", {})
        self.assertTrue(res.get("isError", False))
        self.assertIn("Invalid commander", res["content"][0]["text"])

    def test_tool_call_price(self):
        req = {
            "jsonrpc": "2.0",
            "id": 17,
            "method": "tools/call",
            "params": {
                "name": "scryfall_price",
                "arguments": {"name": "Lotus", "limit": 3},
            },
        }
        resp = mcp.handle_request(req)
        self.assertIsNotNone(resp)
        res = resp.get("result", {})
        self.assertFalse(res.get("isError", True))
        data = json.loads(res["content"][0]["text"])
        self.assertEqual(data["query"], "Lotus")
        self.assertEqual(len(data["cards"]), 3)


    def test_tool_call_deck(self):
        from scry_cli import state
        old_cards = state.CARDS
        old_db_mode = state.DB_MODE
        old_force = state.FORCE_NO_DB
        try:
            state.FORCE_NO_DB = True
            state.DB_MODE = False
            state.CARDS = [
                {
                    "name": "Sol Ring",
                    "mana_cost": "{1}",
                    "cmc": 1.0,
                    "type_line": "Artifact",
                    "colors": [],
                    "color_identity": [],
                    "oracle_text": "{T}: Add {C}{C}.",
                    "legalities": {"commander": "legal"},
                    "prices": {"usd": 1.5},
                }
            ]
            req = {
                "jsonrpc": "2.0",
                "id": 18,
                "method": "tools/call",
                "params": {
                    "name": "scryfall_deck",
                    "arguments": {"deck": "1 Sol Ring"},
                },
            }
            resp = mcp.handle_request(req)
            self.assertIsNotNone(resp)
            res = resp.get("result", {})
            self.assertFalse(res.get("isError", True))
            data = json.loads(res["content"][0]["text"])
            self.assertEqual(data["total_cards"], 1)
            self.assertIn("mana_architecture", data)
            self.assertIn("table_dynamic", data)
            self.assertIn("engine_profile", data)
            self.assertIn("heritage", data)
        finally:
            state.CARDS = old_cards
            state.DB_MODE = old_db_mode
            state.FORCE_NO_DB = old_force


if __name__ == "__main__":
    unittest.main()
