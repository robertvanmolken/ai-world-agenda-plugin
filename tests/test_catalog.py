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
