import json
import re
import unittest
from pathlib import Path

from app.catalog import find_conflicts, get_by_code, optimize_agenda, search_sessions

DATA = Path(__file__).resolve().parents[1] / "data" / "sessions.json"
TIME_RE = re.compile(r"^\d{2}:\d{2}$")
DATE_RE = re.compile(r"^2026-10-\d{2}$")


class BundledCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(DATA.read_text(encoding="utf-8"))
        cls.sessions = cls.data["sessions"]

    def test_metadata_count_matches(self):
        self.assertEqual(self.data["catalog"]["sessionCount"], len(self.sessions))
        self.assertGreater(len(self.sessions), 700)

    def test_codes_unique_and_present(self):
        codes = [s["code"] for s in self.sessions]
        self.assertTrue(all(codes))
        self.assertEqual(len(codes), len(set(codes)))

    def test_all_sessions_have_valid_schedule(self):
        for s in self.sessions:
            self.assertRegex(s["date"], DATE_RE, s["code"])
            self.assertRegex(s["startTime"], TIME_RE, s["code"])
            self.assertRegex(s["endTime"], TIME_RE, s["code"])
            self.assertLess(s["startTime"], s["endTime"], s["code"])
            self.assertTrue(s["title"], s["code"])

    def test_get_by_code_case_insensitive(self):
        code = self.sessions[0]["code"]
        self.assertEqual(code, get_by_code(self.sessions, code.lower())["code"])
        self.assertIsNone(get_by_code(self.sessions, "NOPE0000"))

    def test_search_filters_by_date_and_query(self):
        r = search_sessions(self.sessions, {"date": "2026-10-27", "query": "integration", "limit": 10})
        self.assertTrue(r)
        self.assertLessEqual(len(r), 10)
        self.assertTrue(all(s["date"] == "2026-10-27" for s in r))

    def test_conflicts_on_real_sessions(self):
        s = self.sessions[0]
        r = find_conflicts(self.sessions, [s["code"], s["code"]], 0)
        self.assertIn("conflicts", r)

    def test_optimize_real_day(self):
        r = optimize_agenda(self.sessions, {"date": "2026-10-27", "interests": ["integration", "AI agents"]})
        self.assertTrue(r["agenda"])


if __name__ == "__main__":
    unittest.main()
