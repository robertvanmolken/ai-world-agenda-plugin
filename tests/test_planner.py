import unittest

from app.mcp_server import check_walk, plan_strict_day, sessions
from app.planner import plan_day
from app.venue import check_move, late_minutes, resolve_place

TOPICS = ["oracle integration", "integration", "goldengate", "mcp"]
MON = "2026-10-26"


def _m(t):
    return int(t[:2]) * 60 + int(t[3:])


class PlannerTests(unittest.TestCase):
    def test_late_minutes(self):
        self.assertEqual(late_minutes(5, 6, 14), {"best": 1, "worst": 9})
        self.assertEqual(late_minutes(30, 6, 14), {"best": 0, "worst": 0})

    def test_resolve_place(self):
        self.assertEqual(resolve_place("Hall G"), "hall_g")
        self.assertEqual(resolve_place("Oracle AI World Hub"), "hub")
        self.assertEqual(resolve_place("Galileo 1001, Level 1"), "galileo")
        self.assertEqual(resolve_place("Titian 2204"), "titian")
        self.assertIsNone(resolve_place("Moon base"))

    def test_check_move_unknown_place(self):
        self.assertEqual(check_move("Hall G", "Moon base", 10)["verdict"], "unknown")
        self.assertEqual(check_walk("Hall G", "Galileo 1001, Level 1", 5)["lateIfWalking"]["worst"], 1)

    def test_strict_plan_has_no_overlap_and_respects_lateness(self):
        r = plan_day(sessions(), MON, TOPICS)
        rows = r["schedule"]
        self.assertTrue(rows)
        for a, b in zip(rows, rows[1:]):
            self.assertLessEqual(_m(a["endTime"]), _m(b["startTime"]))
        for mv in r["moves"]:
            self.assertLessEqual(mv["lateIfWalking"]["worst"], 2)
        types = [x["type"] for x in rows]
        self.assertEqual(types.count("lunch"), 1)
        self.assertEqual(types.count("networking"), 2)

    def test_strict_plan_excludes_not_in_app(self):
        r = plan_day(sessions(), MON, ["warehouse", "agents"])
        self.assertNotIn("THR1579", {x["code"] for x in r["schedule"]})

    def test_zero_tolerance_is_stricter(self):
        loose = plan_day(sessions(), MON, ["agent"], late_tolerance_minutes=10)
        tight = plan_day(sessions(), MON, ["agent"], late_tolerance_minutes=0)
        for mv in tight["moves"]:
            self.assertEqual(mv["lateIfWalking"]["worst"], 0)
        self.assertGreaterEqual(len(loose["schedule"]), len(tight["schedule"]))

    def test_mcp_tool_and_hub_talks_toggle(self):
        r = plan_strict_day(MON, ["agent"], include_hub_talks=False)
        self.assertFalse(any("Hub" in (x["location"] or "") and x["type"] == "session" for x in r["schedule"]))
        self.assertIn("dropped", r)


if __name__ == "__main__":
    unittest.main()


class DisclaimerTests(unittest.TestCase):
    def test_every_json_tool_result_has_disclaimer(self):
        import json

        from app import mcp_server as m

        results = [
            m.search_sessions_tool(query="integration", limit=2),
            m.get_session_by_code("LRN2138"),
            m.get_session_by_code("NOPE"),
            m.find_session_conflicts(["LRN2138", "LRN6075"]),
            m.check_transition("LRN2138", "LRN6075"),
            m.check_walk("Hall G", "Titian 2204", 10),
            m.plan_strict_day("2026-10-26", ["integration"]),
            m.optimize_agenda_tool("2026-10-26", ["integration"]),
            m.get_catalog_metadata(),
            json.loads(m.search("integration")),
            json.loads(m.fetch("LRN2138")),
        ]
        for r in results:
            self.assertEqual(r.get("disclaimer"), m.DISCLAIMER)
        self.assertIn("disclaimer", m.mcp.instructions)
