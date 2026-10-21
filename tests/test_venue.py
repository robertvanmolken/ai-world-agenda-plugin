import unittest

from app.catalog import find_conflicts, search_sessions
from app.mcp_server import sessions
from app.venue import assess_transition, resolve_zone, travel_minutes


def _s(code):
    return next(s for s in sessions() if s["code"] == code)


class VenueTests(unittest.TestCase):
    def test_all_rooms_valid(self):
        from scripts.validate_rooms import validate
        errors, _ = validate()
        self.assertEqual(errors, [])

    def test_resolve_zone(self):
        self.assertEqual(resolve_zone("2404", "Veronese", 2), "veronese")
        self.assertEqual(resolve_zone("704", "Marco Polo", 1), "marco_polo")
        self.assertEqual(resolve_zone("A", "Hall", 2), "hall_a")
        self.assertEqual(resolve_zone("Theater 6", "Oracle AI World Hub", None), "hub")
        self.assertIsNone(resolve_zone("9999", "Nowhere", 2))

    def test_rooms_merged_and_searchable(self):
        self.assertEqual(_s("LRN2267")["level"], 2)
        found = search_sessions(sessions(), {"room": "veronese"})
        self.assertIn("LRN2267", {s["code"] for s in found})
        self.assertTrue(search_sessions(sessions(), {"level": "2"}))

    def test_same_level_walk_is_capped(self):
        from app.venue import _walk, venue

        cap = venue()["model"]["sameLevelMaxMinutes"]
        self.assertLessEqual(_walk("hall_a", "titian"), cap)
        self.assertLessEqual(_walk("hall_g", "marco_polo"), cap)

    def test_no_room_clashes(self):
        from scripts.validate_rooms import validate

        errors, _ = validate()
        self.assertEqual([e for e in errors if "same room" in e], [])

    def test_travel_ranges(self):
        lo, hi = travel_minutes("marco_polo", "hub")  # Hub hall unknown, so a range from a Level 1 room
        self.assertLess(lo, hi)
        self.assertEqual(travel_minutes("hub", "hub")[0], travel_minutes("hub", "hub")[1])
        self.assertGreater(travel_minutes("veronese", "galileo")[0], travel_minutes("veronese", "bellini")[0])

    def test_hub_is_on_level_two(self):
        from app.venue import venue

        hub = venue()["hub"]
        self.assertEqual(hub["level"], 2)
        for z in hub["candidates"]:
            self.assertEqual(venue()["zones"][z]["level"], 2)
        # Level 2 room: walk to the Hub is a same-level walk, so the range is tight.
        lo, hi = travel_minutes("titian", "hub")
        self.assertLessEqual(hi - lo, 1)
        # Level 1 room: always includes a level change, so even the best case is longer.
        lo1, hi1 = travel_minutes("marco_polo", "hub")
        self.assertGreater(lo1, lo)
        self.assertGreater(hi1, hi)

    def test_hub_theaters_are_on_level_two(self):
        theaters = [s for s in sessions() if "theater" in (s.get("room") or "").lower()]
        self.assertTrue(theaters)
        self.assertTrue(all(s["level"] == 2 for s in theaters))
        found = {s["code"] for s in search_sessions(sessions(), {"level": "2", "limit": 1000})}
        self.assertIn(theaters[0]["code"], found)

    def test_known_conflict_pair(self):
        t = assess_transition(_s("LRN2267"), _s("MET2649"))
        self.assertEqual(t["verdict"], "overlap")

    def test_unknown_when_no_room(self):
        a = _s("LRN2267")
        no_room = {"code": "X1", "date": a["date"], "startTime": "23:00", "endTime": "23:45"}
        self.assertEqual(assess_transition(a, no_room)["verdict"], "unknown")

    def test_conflicts_include_travel(self):
        res = find_conflicts(sessions(), ["LRN2267", "MET2649"])
        self.assertIn("travel", res)


if __name__ == "__main__":
    unittest.main()
