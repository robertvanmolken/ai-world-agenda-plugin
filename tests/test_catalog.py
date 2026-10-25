import unittest
from app.catalog import find_conflicts, optimize_agenda

S = [
 {"code":"A","title":"AI Integration","description":"customer lessons","date":"2026-10-27","startTime":"10:00","endTime":"10:45","areasOfInterest":["Integration"]},
 {"code":"B","title":"AI Agents","description":"","date":"2026-10-27","startTime":"10:40","endTime":"11:20","areasOfInterest":["AI Agents"]},
 {"code":"C","title":"Partner Growth","description":"business outcomes","date":"2026-10-27","startTime":"12:00","endTime":"12:45","areasOfInterest":[]}
]

class CatalogTest(unittest.TestCase):
    def test_conflict(self):
        r = find_conflicts(S, ['A','B'], 0)
        self.assertEqual(1, len(r['conflicts']))
    def test_optimize(self):
        r = optimize_agenda(S, {"date":"2026-10-27","interests":["integration","partner"]})
        self.assertTrue(r['agenda'])

if __name__ == '__main__': unittest.main()


class ExactSearchTest(unittest.TestCase):
    def test_exact_title_and_quotes(self):
        from app.mcp_server import search_sessions_tool, sessions

        title = "Building Trusted Agentic AI with Oracle Integration"
        loose = search_sessions_tool(query="Building Trusted Agentic AI Oracle Integration", limit=50)["results"]
        self.assertGreater(len(loose), 1)
        for q in (title, f'"{title}"', f"\u201c{title}\u201d", title.lower()):
            res = search_sessions_tool(query=q, limit=50)["results"]
            self.assertTrue(res)
            self.assertTrue(all(r["title"] == title for r in res), q)
        self.assertEqual(1, len(search_sessions_tool(query="lrn2138")["results"]))
        self.assertGreater(len(search_sessions_tool(query=title.split(" with")[0], limit=50)["results"]), 1)  # partial: still loose
        quoted = search_sessions_tool(query='"trusted agentic ai"', limit=50)["results"]
        self.assertTrue(quoted)
        self.assertTrue(all("trusted agentic ai" in (r["title"] + " " + r["description"]).lower() for r in quoted))
        self.assertLess(len(quoted), len(search_sessions_tool(query="trusted agentic ai", limit=200)["results"]))
        self.assertEqual([], search_sessions_tool(query='"agentic trusted"', limit=50)["results"])  # order matters
        self.assertTrue(search_sessions_tool(query="Oracle Integration", exact=True, limit=50)["results"])


class PaidSessionTest(unittest.TestCase):
    def test_paid_sessions_flagged(self):
        from app.mcp_server import search_sessions_tool, sessions

        paid = [s for s in sessions() if s.get("paid")]
        self.assertTrue(paid)
        self.assertTrue(all(s["code"].startswith("OUT") for s in paid))
        self.assertTrue(all("My Account" in s["registrationNote"] for s in paid))
        self.assertFalse(any(s.get("paid") for s in sessions() if s["code"].startswith("LRN")))
        res = search_sessions_tool(query="paid registration", limit=50)["results"]
        self.assertEqual({s["code"] for s in paid}, {r["code"] for r in res if r.get("paid")})  # searchable by "paid"
