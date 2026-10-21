import unittest

try:
    from starlette.testclient import TestClient
    from app.asgi import app
except ImportError:  # optional deps not installed
    app = None


@unittest.skipIf(app is None, "mcp/starlette not installed")
class WebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_landing_page(self):
        r = self.client.get("/")
        self.assertEqual(200, r.status_code)
        self.assertIn("text/html", r.headers["content-type"])
        self.assertIn("Oracle AI World 2026 Agenda Assistant", r.text)
        self.assertIn('id="f"', r.text)
        self.assertIn('id="chk"', r.text)

    def test_offer_section(self):
        r = self.client.get("/").text
        self.assertIn('id="work-with-us"', r)
        self.assertIn("Monday at your table. Friday, a working demo.", r)
        self.assertIn("Built by Exoblock B.V.", r)
        self.assertIn("not affiliated with or endorsed by Oracle", r)

    def test_icons_served_but_not_original(self):
        for p in ["/icon.png", "/icon-192.png", "/favicon.ico", "/logo.png"]:
            r = self.client.get(p)
            self.assertEqual(200, r.status_code, p)
            self.assertEqual("image/png", r.headers["content-type"], p)
            self.assertTrue(r.content.startswith(b"\x89PNG"), p)
        self.assertLess(len(self.client.get("/icon.png").content), 1_000_000)
        self.assertNotEqual(200, self.client.get("/AI World Agenda Assistant Emblem.png").status_code)

    def test_fonts_are_local(self):
        page = self.client.get("/").text
        self.assertNotIn("fonts.googleapis.com", page)
        self.assertNotIn("fonts.gstatic.com", page)
        for f in ["plus-jakarta-sans", "source-serif-4", "source-serif-4-italic"]:
            r = self.client.get(f"/fonts/{f}.woff2")
            self.assertEqual(200, r.status_code, f)
            self.assertEqual("font/woff2", r.headers["content-type"], f)
            self.assertTrue(r.content.startswith(b"wOF2"), f)
        self.assertEqual(404, self.client.get("/fonts/../app/catalog.py").status_code)

    def test_status_json(self):
        r = self.client.get("/status")
        self.assertEqual("ok", r.json()["status"])

    def test_schedule_check_endpoints(self):
        c = self.client.post("/sessions/conflicts", json={"codes": ["LRN1128", "LRN2162"]}).json()
        self.assertEqual(2, len(c["sessions"]))
        self.assertIn("disclaimer", c)
        t = self.client.post("/sessions/transition", json={"codeA": "LRN1128", "codeB": "LRN2162"}).json()
        self.assertEqual("ok", t["verdict"])

    def test_health_and_search(self):
        self.assertTrue(self.client.get("/health").json()["ok"])
        r = self.client.post("/sessions/search", json={"query": "integration", "limit": 5})
        self.assertTrue(r.json()["results"])


if __name__ == "__main__":
    unittest.main()
