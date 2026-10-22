import unittest

from app.mapsvg import levels, render_level
from app.routing import graph, route, route_range, shortest_path
from app.venue import assess_transition, route_details, venue

try:
    from starlette.testclient import TestClient
    from app.asgi import app
except ImportError:  # optional deps not installed
    app = None


class RoutingTests(unittest.TestCase):
    def test_every_venue_zone_is_in_graph(self):
        self.assertEqual([z for z in venue()["zones"] if z not in graph()["nodes"]], [])

    def test_every_node_reachable_from_hall_g(self):
        for node in graph()["nodes"]:
            self.assertIsNotNone(shortest_path("hall_g", node), node)

    def test_edges_and_links_reference_nodes(self):
        g = graph()
        for a, b in g["edges"]:
            self.assertIn(a, g["nodes"])
            self.assertIn(b, g["nodes"])
        for a, b, kind in g["links"]:
            self.assertIn(a, g["nodes"])
            self.assertIn(b, g["nodes"])
            self.assertIn(kind, ("escalator", "elevator"))
            self.assertNotEqual(g["nodes"][a]["level"], g["nodes"][b]["level"])

    def test_symmetry(self):
        for a, b in [("hall_g", "titian"), ("galileo", "palazzo_ballroom"), ("hall_a", "hall_d")]:
            self.assertAlmostEqual(route(a, b)["walkMinutes"], route(b, a)["walkMinutes"], places=1)

    def test_level_change_route(self):
        r = route("hall_g", "titian")
        self.assertEqual(r["levels"], [1, 2])
        self.assertTrue(any(s.get("levelChange") for s in r["steps"]))
        self.assertEqual({p["level"] for p in r["polylines"]}, {1, 2})
        self.assertEqual(r["steps"][0]["text"], "Leave Hall G")
        self.assertTrue(r["steps"][-1]["text"].startswith("Arrive at"))

    def test_same_level_stays_on_level(self):
        r = route("hall_a", "hall_d")
        self.assertEqual(r["levels"], [2])
        self.assertFalse(any(s.get("levelChange") for s in r["steps"]))

    def test_farther_is_slower(self):
        self.assertGreater(route("hall_a", "hall_d")["walkMinutes"], route("hall_a", "hall_b")["walkMinutes"])
        self.assertGreater(route("marco_polo", "palazzo_ballroom")["walkMinutes"], route("marco_polo", "casanova")["walkMinutes"])

    def test_hub_range(self):
        r = route_range("marco_polo", "hub")
        self.assertLess(r["bestMinutes"], r["worstMinutes"])

    def test_unknown_zone(self):
        self.assertIsNone(route("hall_g", "nowhere"))

    def test_route_details_and_transition(self):
        d = route_details("hall_g", "titian")
        self.assertEqual([m["level"] for m in d["mapUrls"]], [1, 2])
        self.assertIn("/venue/route?from=hall_g&to=titian&level=2", d["mapUrls"][1]["url"])

    def test_svg_renders_every_level(self):
        r = route("hall_g", "titian")
        for lv in levels():
            svg = render_level(lv, r)
            self.assertTrue(svg.startswith("<svg"))
            self.assertTrue(svg.endswith("</svg>"))
        self.assertIn("route", render_level(2, r))
        self.assertNotIn('class="route"', render_level(3, r))


@unittest.skipIf(app is None, "mcp/starlette not installed")
class RoutingWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_map_endpoints(self):
        r = self.client.get("/venue/map/2.svg")
        self.assertEqual(200, r.status_code)
        self.assertIn("image/svg+xml", r.headers["content-type"])
        self.assertEqual(404, self.client.get("/venue/map/9.svg").status_code)
        r = self.client.get("/venue/route?from=hall_g&to=titian&level=2")
        self.assertEqual(200, r.status_code)
        self.assertIn('class="route"', r.text)
        self.assertEqual(404, self.client.get("/venue/route?from=zzz&to=titian").status_code)
        self.assertEqual(400, self.client.get("/venue/route?from=hall_g&to=titian&level=x").status_code)

    def test_route_endpoint(self):
        r = self.client.post("/sessions/route", json={"from": "Hall G", "to": "Titian"})
        self.assertEqual(200, r.status_code)
        body = r.json()
        self.assertIn("disclaimer", body)
        self.assertEqual(body["routeDetail"]["levels"], [1, 2])
        self.assertEqual(404, self.client.post("/sessions/route", json={"from": "x", "to": "y"}).status_code)

    def test_transition_has_route_detail(self):
        r = self.client.post("/sessions/transition", json={"codeA": "LRN1128", "codeB": "LRN2162"}).json()
        self.assertIn("routeDetail", r)


class McpRouteTests(unittest.TestCase):
    @unittest.skipIf(app is None, "mcp/starlette not installed")
    def test_tool(self):
        from app.mcp_server import get_walk_route

        r = get_walk_route("Hall G", "Titian")
        self.assertIn("disclaimer", r)
        self.assertTrue(r["routeDetail"]["mapUrls"][0]["url"].startswith("http"))
        self.assertNotIn("polylines", r["routeDetail"])
        self.assertIn("error", get_walk_route("nowhere", "Titian"))


if __name__ == "__main__":
    unittest.main()
