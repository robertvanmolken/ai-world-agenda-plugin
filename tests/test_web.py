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

    def test_status_json(self):
        r = self.client.get("/status")
        self.assertEqual("ok", r.json()["status"])

    def test_health_and_search(self):
        self.assertTrue(self.client.get("/health").json()["ok"])
        r = self.client.post("/sessions/search", json={"query": "integration", "limit": 5})
        self.assertTrue(r.json()["results"])


if __name__ == "__main__":
    unittest.main()
