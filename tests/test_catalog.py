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


class HideStartedTest(unittest.TestCase):
    def at(self, stamp):
        import app.catalog as c
        from datetime import datetime

        self._orig = c.now_local
        c.now_local = lambda: datetime.fromisoformat(stamp)
        self.addCleanup(lambda: setattr(c, "now_local", self._orig))

    def test_paid_after_start_others_after_end(self):
        from app.catalog import hide_now

        paid = {"date": "2026-10-25", "startTime": "09:00", "endTime": "17:00", "paid": True}
        free = {"date": "2026-10-25", "startTime": "09:00", "endTime": "10:00"}
        self.at("2026-10-25T09:30:00"); self.assertFalse(hide_now(paid)); self.assertFalse(hide_now(free))  # 30 min grace
        self.at("2026-10-25T09:31:00"); self.assertTrue(hide_now(paid)); self.assertFalse(hide_now(free))
        self.at("2026-10-25T10:00:00"); self.assertFalse(hide_now(free))  # ends exactly now
        self.at("2026-10-25T10:01:00"); self.assertTrue(hide_now(free))
        self.at("2026-10-24T20:00:00"); self.assertFalse(hide_now(paid)); self.assertFalse(hide_now(free))
        self.assertFalse(hide_now({"date": "2026-10-25"}))

    def test_search_planner_optimizer(self):
        from app.mcp_server import optimize_agenda_tool, plan_strict_day, search_sessions_tool

        self.at("2026-10-25T12:30:00")  # Sunday lunchtime
        every = search_sessions_tool(query="oracle", limit=200)["results"]
        hidden = search_sessions_tool(query="oracle", limit=200, hide_started=True)["results"]
        self.assertTrue(any(r["code"].startswith("OUT") for r in every))
        self.assertFalse(any(r["code"].startswith("OUT") for r in hidden))  # paid and started
        self.assertTrue(all(r["date"] > "2026-10-25" or r["endTime"] >= "12:30" for r in hidden))
        # a session that began earlier but is still running stays
        self.assertTrue(any(r["date"] == "2026-10-25" and r["startTime"] <= "12:00" and r["endTime"] > "12:30" for r in hidden))
        done = search_sessions_tool(query="LRN2159", limit=5)["results"][0]  # ended 11:45
        self.assertEqual("11:45", done["endTime"])
        self.assertNotIn("LRN2159", [r["code"] for r in search_sessions_tool(query="", date="2026-10-25", limit=200, hide_started=True)["results"]])
        self.assertEqual("OUT1017", search_sessions_tool(query="OUT1017", limit=5)["results"][0]["code"])
        plan = plan_strict_day("2026-10-25", ["ai"], hide_started=True)
        self.assertTrue(all(i["endTime"] >= "12:30" for i in plan["schedule"] if i["type"] == "session"))
        opt = optimize_agenda_tool("2026-10-25", ["ai"], hide_started=True)
        self.assertTrue(all(a["session"]["endTime"] >= "12:30" for a in opt["agenda"]))
        self.at("2026-10-24T08:00:00")
        self.assertTrue(any(r["code"].startswith("OUT") for r in search_sessions_tool(query="oracle", limit=200, hide_started=True)["results"]))


class SortTest(unittest.TestCase):
    def test_date_order_default(self):
        from app.mcp_server import search_sessions_tool

        res = search_sessions_tool(query="agentic ai", limit=200)["results"]
        keys = [(r["date"], r["startTime"]) for r in res]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual("2026-10-25", res[0]["date"])
        rel = search_sessions_tool(query="agentic ai", limit=200, sort="relevance")["results"]
        self.assertEqual({r["code"] for r in res}, {r["code"] for r in rel})  # same sessions, other order
        self.assertNotEqual([r["code"] for r in res], [r["code"] for r in rel])


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


class ArriveEarlyTest(unittest.TestCase):
    def test_flags_and_types(self):
        from app.mcp_server import sessions

        flagged = {s["sessionType"] for s in sessions() if s.get("arriveEarlyMinutes")}
        self.assertEqual({"Hands On Lab", "Product Bootcamp", "Hackathon"}, flagged)
        self.assertTrue(all(s["arriveEarlyMinutes"] == 30 for s in sessions() if s.get("arriveEarlyMinutes")))
        self.assertFalse(any(s.get("arriveEarlyMinutes") for s in sessions() if s["sessionType"] == "Learning Session"))

    def test_soft_rule_in_transition(self):
        from app.mcp_server import check_transition

        t = check_transition("LRN1174", "HOL2765").structuredContent  # ends 13:30, lab at 14:00
        self.assertEqual(30, t["arriveEarlyMinutes"])
        self.assertIn("arrive about 30 min early", t["earlyNote"])
        self.assertEqual("tight", t["verdict"])  # soft: still possible, just not the early arrival
        self.assertEqual("13:30", t["arriveBy"])
        off = check_transition("LRN1174", "HOL2765", early_arrival=False).structuredContent
        self.assertNotIn("arriveEarlyMinutes", off)
        self.assertNotIn("arriveBy", off)
        self.assertEqual("ok", off["verdict"])
        talks = check_transition("LRN2138", "LRN6075").structuredContent  # two talks: no early arrival
        self.assertNotIn("arriveEarlyMinutes", talks)
        self.assertNotIn("earlyNote", talks)

    def test_planner_warns_or_enforces(self):
        from app.mcp_server import plan_strict_day

        soft = plan_strict_day("2026-10-26", ["ai agents", "mcp"])
        self.assertTrue(any("arrive about 30 min early" in w for w in soft["warnings"]))
        self.assertTrue(any(m.get("earlyArrivalPossible") is False for m in soft["moves"]))
        strict = plan_strict_day("2026-10-26", ["ai agents", "mcp"], strict_early=True)
        self.assertTrue(strict["rules"]["strictEarly"])
        self.assertTrue(all(m["earlyArrivalPossible"] for m in strict["moves"] if "arriveEarlyMinutes" in m))
