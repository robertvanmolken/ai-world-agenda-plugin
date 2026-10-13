import asyncio
import json
import unittest

try:
    from mcp.shared.memory import create_connected_server_and_client_session as connect
    from app.mcp_server import mcp
except ImportError:  # mcp not installed
    mcp = None


@unittest.skipIf(mcp is None, "mcp package not installed")
class McpTests(unittest.TestCase):
    def _run(self, fn):
        async def go():
            async with connect(mcp._mcp_server) as client:
                return await fn(client)
        return asyncio.run(go())

    def test_tools_listed(self):
        res = self._run(lambda c: c.list_tools())
        names = {t.name for t in res.tools}
        for n in ["search_sessions", "get_session_by_code", "find_session_conflicts",
                  "optimize_agenda", "get_catalog_metadata", "search", "fetch"]:
            self.assertIn(n, names)

    def test_server_icons(self):
        self.assertTrue(mcp._mcp_server.icons)
        self.assertTrue(mcp._mcp_server.icons[0].src.endswith("/icon.png"))
        self.assertTrue(mcp._mcp_server.website_url)

    def test_search_and_fetch(self):
        res = self._run(lambda c: c.call_tool("search", {"query": "integration"}))
        results = json.loads(res.content[0].text)["results"]
        self.assertTrue(results)
        res = self._run(lambda c: c.call_tool("fetch", {"id": results[0]["id"]}))
        self.assertEqual(json.loads(res.content[0].text)["id"], results[0]["id"])


if __name__ == "__main__":
    unittest.main()
