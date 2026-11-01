import os
import unittest
from datetime import datetime

from app import clock

try:
    from starlette.testclient import TestClient
    from app.asgi import app
except ImportError:  # mcp/starlette not installed
    app = None


class ClockTests(unittest.TestCase):
    def setUp(self):
        self._real = clock.real_now
        self._status = os.environ.pop("EVENT_STATUS", None)
        self._sim = os.environ.pop("SIMULATE_NOW", None)
        self.addCleanup(self.restore)

    def restore(self):
        clock.real_now = self._real
        for k, v in (("EVENT_STATUS", self._status), ("SIMULATE_NOW", self._sim)):
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def at(self, stamp):
        clock.real_now = lambda: datetime.fromisoformat(stamp)

    def test_live_until_the_last_session_ends(self):
        end = clock.event_end()
        self.assertEqual("2026-10-28", end.date().isoformat())
        self.at("2026-10-27T10:00:00")
        self.assertFalse(clock.event_ended())
        self.assertEqual(datetime(2026, 10, 27, 10), clock.now())  # real time while the conference runs
        self.assertEqual("live", clock.status()["eventStatus"])
        self.assertNotIn("note", clock.status())

    def test_simulated_after_the_event(self):
        self.at("2026-11-02T09:00:00")
        self.assertTrue(clock.event_ended())
        self.assertEqual(datetime(2026, 10, 26, 8), clock.now())  # default simulated moment
        st = clock.status()
        self.assertEqual("ended", st["eventStatus"])
        self.assertIn("Thank you for using the AI World Agenda Assistant", st["note"])
        self.assertTrue(st["simulation"])

    def test_switches_and_a_chosen_moment(self):
        self.at("2026-10-27T10:00:00")
        os.environ["EVENT_STATUS"] = "ended"
        self.assertTrue(clock.event_ended())
        os.environ["EVENT_STATUS"] = "live"
        self.at("2026-12-01T10:00:00")
        self.assertFalse(clock.event_ended())
        os.environ["EVENT_STATUS"] = "auto"
        os.environ["SIMULATE_NOW"] = "2026-10-27T13:30"
        self.assertEqual(datetime(2026, 10, 27, 13, 30), clock.now())
        token = clock.set_simulated("2026-10-28T09:00")
        try:
            self.assertEqual(datetime(2026, 10, 28, 9), clock.now())  # a request's own moment wins
        finally:
            clock.reset_simulated(token)
        self.assertEqual(datetime(2026, 10, 27, 13, 30), clock.now())
        self.assertIsNone(clock.set_simulated("not a date"))
        self.assertEqual(datetime(2026, 10, 27, 8), clock.parse_moment("2026-10-27"))

    def test_hide_rules_follow_the_simulated_time(self):
        from app.mcp_server import search_sessions_tool

        self.at("2026-11-02T09:00:00")
        mon = search_sessions_tool(query="MCP", limit=200, hide_started=True)["results"]
        late = search_sessions_tool(query="MCP", limit=200, hide_started=True, simulate_now="2026-10-28T09:00")["results"]
        self.assertLess(len(mon), 200)  # not cut by the limit, so the two counts can be compared
        self.assertGreater(len(mon), len(late))
        self.assertTrue(all(r["date"] >= "2026-10-28" for r in late))
        self.assertFalse(any(r["code"].startswith("OUT") for r in mon))  # the paid Sunday sessions are over by Monday 08:00

    def test_every_tool_result_says_the_event_has_ended(self):
        from app.mcp_server import DISCLAIMER, check_walk, find_booth, plan_strict_day, search_sessions_tool

        self.at("2026-11-02T09:00:00")
        for r in (search_sessions_tool(query="MCP"), check_walk("Hall G", "Titian 2204", 10),
                  plan_strict_day("2026-10-27", ["ai"]), find_booth("NVIDIA").structuredContent):
            self.assertEqual("ended", r["eventStatus"])
            self.assertEqual("2026-10-26T08:00", r["now"])
            self.assertIn("has ended", r["disclaimer"])
            self.assertIn("thank them", r["disclaimer"])
            self.assertTrue(r["disclaimer"].endswith(DISCLAIMER))
        self.at("2026-10-27T10:00:00")
        live = search_sessions_tool(query="MCP")
        self.assertEqual("live", live["eventStatus"])
        self.assertEqual(DISCLAIMER, live["disclaimer"])

    def test_the_planner_works_in_the_simulation(self):
        from app.mcp_server import check_transition, plan_strict_day

        self.at("2026-11-02T09:00:00")
        plan = plan_strict_day("2026-10-27", ["ai agents"], hide_started=True, simulate_now="2026-10-27T08:00")
        self.assertTrue([r for r in plan["schedule"] if r["type"] == "session"])
        self.assertEqual("2026-10-27T08:00", plan["now"])
        self.assertIn(check_transition("LRN2138", "LRN6075").structuredContent["verdict"], ("ok", "tight", "unlikely", "overlap"))


@unittest.skipIf(app is None, "mcp/starlette not installed")
class ClockWebTests(unittest.TestCase):
    def setUp(self):
        self._real = clock.real_now
        clock.real_now = lambda: datetime(2026, 11, 2, 9, 0)
        self.addCleanup(lambda: setattr(clock, "real_now", self._real))
        self.client = TestClient(app)

    def test_health_banner_data_and_per_request_moments(self):
        h = self.client.get("/health").json()
        self.assertEqual("ended", h["eventStatus"])
        self.assertEqual("2026-10-26T08:00", h["now"])
        self.assertIn("Thank you", h["note"])
        body = {"query": "MCP", "limit": 200, "hideStarted": True}
        default = self.client.post("/sessions/search", json=body).json()
        query = self.client.post("/sessions/search?simulateNow=2026-10-28T09:00", json=body).json()
        header = self.client.post("/sessions/search", json=body, headers={"X-Simulate-Now": "2026-10-27T12:00"}).json()
        self.assertEqual(["2026-10-26T08:00", "2026-10-28T09:00", "2026-10-27T12:00"], [default["now"], query["now"], header["now"]])
        self.assertLess(len(default["results"]), 200)
        self.assertGreater(len(default["results"]), len(header["results"]))  # Monday 08:00 shows more than Tuesday 12:00
        self.assertGreater(len(header["results"]), len(query["results"]))    # which shows more than Wednesday 09:00
        self.assertEqual("2026-10-26T08:00", self.client.post("/sessions/search", json=body).json()["now"])  # not sticky

    def test_page_has_the_ended_banner_and_selector(self):
        page = self.client.get("/").text
        for needle in ('id="ended"', "has ended", "Thank you for using the AI World Agenda Assistant", 'id="simday"',
                       "X-Simulate-Now", 'fetch("/health")', "Explore the Oracle AI World 2026"):
            self.assertIn(needle, page)


if __name__ == "__main__":
    unittest.main()
