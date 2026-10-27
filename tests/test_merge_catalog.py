import unittest
from datetime import datetime

from scripts.merge_catalog import base_id, merge, merge_rooms, pick_occurrence

NOW = datetime(2026, 10, 27, 7, 0)


def s(code, date, start="09:00", end="10:00", **kw):
    return {"code": code, "title": code, "date": date, "startTime": start, "endTime": end, "dateLabel": date, **kw}


class MergeTests(unittest.TestCase):
    def test_past_days_without_dates_are_kept(self):
        cur = [s("LRN1", "2026-10-26"), s("LRN2", "2026-10-27")]
        tiles = [dict(s("LRN1", None, None, None), date=None, rawClasses=["day-monday-oct-26"]), s("LRN2", "2026-10-27")]
        merged, rep = merge(cur, tiles, "2026-10-27", NOW)
        self.assertEqual({"LRN1", "LRN2"}, {x["code"] for x in merged})
        self.assertEqual(["LRN1"], rep["kept"])
        self.assertEqual("2026-10-26", next(x for x in merged if x["code"] == "LRN1")["date"])

    def test_dated_tiles_update_and_new_sessions_are_added(self):
        cur = [s("LRN2", "2026-10-27", "09:00", "10:00")]
        tiles = [s("LRN2", "2026-10-27", "09:30", "10:30"), s("ANC9", "2026-10-28")]
        merged, rep = merge(cur, tiles, "2026-10-27", NOW)
        self.assertEqual(["ANC9"], rep["added"])
        self.assertEqual("09:30", next(x for x in merged if x["code"] == "LRN2")["startTime"])
        self.assertEqual(["LRN2"], [c for c, _ in rep["changed"]])

    def test_missing_future_session_is_removed_but_past_one_stays(self):
        cur = [s("OLD1", "2026-10-25"), s("GONE", "2026-10-28")]
        merged, rep = merge(cur, [s("X1", "2026-10-28")], "2026-10-27", NOW)
        self.assertEqual(["GONE"], rep["removed"])
        self.assertIn("OLD1", {x["code"] for x in merged})

    def test_repeat_takes_the_earliest_open_occurrence(self):
        opts = [s("T1", "2026-10-27", "08:30", "08:50"), s("T1", "2026-10-28", "13:40", "14:00")]
        self.assertEqual("2026-10-28", pick_occurrence(opts, NOW.replace(hour=9))["date"])
        self.assertEqual("2026-10-27", pick_occurrence(opts, NOW.replace(hour=8, minute=40))["date"])
        self.assertEqual("2026-10-28", pick_occurrence(opts, datetime(2026, 10, 29))["date"])  # all over: the latest

    def test_session_filed_under_a_past_day_without_time_is_dropped(self):
        cur = [s("HOL1", "2026-10-27", "13:00", "14:30")]
        tile = dict(s("HOL1", None, None, None), date=None, rawClasses=["day-monday-oct-26"])
        merged, rep = merge(cur, [tile], "2026-10-27", NOW)
        self.assertEqual(["HOL1"], rep["moved"])
        self.assertEqual([], merged)

    def test_repeat_ids_and_rooms(self):
        self.assertEqual("session-1791582502797001vqMx", base_id("session-1791582502797001vqMx-1792173198503001jBQ9"))
        rows = merge_rooms({"A": {"code": "A", "location": "old"}, "B": {"code": "B", "location": "keep"}},
                           {"A": "Titian 2204, Level 2"}, {"A", "B"}, "2026-10-27")
        self.assertEqual("Titian 2204, Level 2", rows["A"]["location"])
        self.assertEqual("keep", rows["B"]["location"])


if __name__ == "__main__":
    unittest.main()
