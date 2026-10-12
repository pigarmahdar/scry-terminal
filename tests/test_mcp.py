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

from scryfall_cli import mcp


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


if __name__ == "__main__":
    unittest.main()
