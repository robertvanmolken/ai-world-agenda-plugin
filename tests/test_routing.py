import unittest

from app.mapsvg import levels, render_level
from app.routing import graph, place_room, room_key, room_rect, route, route_range, shortest_path
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

    def test_north_core_connects_level_one_and_two(self):
        r = route("marco_polo", "titian")
        self.assertEqual(r["levels"], [1, 2])
        self.assertIn("l1_esc_n", r["path"])
        self.assertLess(r["meters"], 150)
        self.assertLess(route("galileo", "veronese")["walkMinutes"], 3)

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

    def test_png_endpoints(self):
        for url in ("/venue/map/2.png", "/venue/route.png?from=hall_g&to=titian&level=2", "/venue/route.png?from=hall_g&to=titian"):
            r = self.client.get(url)
            self.assertEqual(200, r.status_code, url)
            self.assertEqual("image/png", r.headers["content-type"])
            self.assertEqual(b"\x89PNG", r.content[:4])
        self.assertEqual(404, self.client.get("/venue/map/9.png").status_code)
        self.assertEqual(404, self.client.get("/venue/route.png?from=zzz&to=titian").status_code)
        self.assertEqual(400, self.client.get("/venue/route.png?from=hall_g&to=titian&level=x").status_code)

    def test_every_catalog_room_has_a_rectangle(self):
        from app.mcp_server import sessions
        from app.venue import session_room, session_zone

        missing = set()
        for s in sessions():
            z = session_zone(s)
            if z in graph()["rooms"] and not session_room(s, z):
                missing.add((z, s.get("room")))
        self.assertEqual(sorted(missing), [])

    def test_rooms_sit_inside_their_block(self):
        for zone, rooms in graph()["rooms"].items():
            x, y, w, h = graph()["nodes"][zone]["rect"]
            for name, (rx, ry, rw, rh) in rooms.items():
                self.assertTrue(x <= rx and rx + rw <= x + w and y <= ry and ry + rh <= y + h, (zone, name))

    def test_room_lookup(self):
        self.assertEqual(room_key("titian", "2204"), "2204")
        self.assertEqual(room_key("veronese", "2401A/B"), "2401A")
        self.assertIsNone(room_key("titian", "9999"))
        self.assertEqual(place_room("Galileo 1001, Level 1", "galileo"), "1001")
        self.assertEqual(place_room("Venetian Ballroom HI", "venetian_ballroom"), "HI")
        hi, h, i = room_rect("venetian_ballroom", "HI"), room_rect("venetian_ballroom", "H"), room_rect("venetian_ballroom", "I")
        self.assertEqual(hi[0], i[0])
        self.assertAlmostEqual(hi[0] + hi[2], h[0] + h[2])

    def test_walk_ends_at_the_room(self):
        r = route("titian", "casanova", False, "2204", "607")
        self.assertEqual((r["fromRoom"], r["toRoom"]), ("2204", "607"))
        self.assertEqual(r["steps"][0]["text"], "Leave Titian 2204")
        self.assertEqual(r["steps"][-1]["text"], "Arrive at Casanova 607")
        self.assertNotEqual(r["meters"], route("titian", "casanova")["meters"])
        near, far = route("galileo", "galileo", False, "1001", "1002"), route("galileo", "galileo", False, "1001", "1007")
        self.assertLess(near["meters"], far["meters"])
        self.assertEqual(route("galileo", "galileo")["meters"], 0)

    def test_route_page_and_images(self):
        from app.mcp_server import get_route_map_images, get_walk_route
        r = self.client.get("/venue/route/page?from=hall_g&to=titian")
        self.assertEqual(200, r.status_code)
        self.assertIn("text/html", r.headers["content-type"])
        self.assertIn("/venue/route.png?from=hall_g&amp;to=titian&amp;level=2", r.text)
        self.assertIn("<li>", r.text)
        self.assertEqual(404, self.client.get("/venue/route/page?from=zzz&to=titian").status_code)
        d = get_walk_route("Hall G", "Titian").structuredContent["routeDetail"]
        self.assertTrue(d["pageUrl"].startswith("http") and "/venue/route/page?from=hall_g&to=titian" in d["pageUrl"])
        imgs = get_route_map_images("Hall G", "Titian")
        self.assertEqual(2, len(imgs))
        self.assertEqual("image/png", imgs[0].to_image_content().mimeType)
        self.assertEqual(["No walking route known between these places"], get_route_map_images("zzz", "Titian"))

    def test_stairs_wording_and_markers(self):
        steps = " ".join(s["text"] for s in route_range("hall_g", "hall_b")["steps"])
        self.assertIn("escalator or stairs up to Level 2", steps)
        self.assertIn("Take the escalator up", " ".join(s["text"] for s in route_range("hall_g", "titian")["steps"]))
        self.assertNotIn("stairs", " ".join(s["text"] for s in route_range("hall_g", "hall_b", True)["steps"]))
        self.assertEqual(sorted(k for k, n in graph()["nodes"].items() if n.get("stairs")), ["g_esc_n", "g_esc_s", "l2_esc_ba", "l2_esc_hc"])
        self.assertIn("Stairs next to escalator", render_level(1))

    def test_room_maps(self):
        r = route("titian", "casanova", False, "2204", "607")
        svg = render_level(2, r)
        self.assertIn(">2204</text>", svg)
        self.assertIn("Leave", " ".join(s["text"] for s in r["steps"]))
        self.assertEqual(svg.count('stroke="#B8321F" stroke-width="1.6"'), 1)

    def test_step_free_uses_no_escalator(self):
        g = graph()
        for a, b in ("hall_g", "titian"), ("galileo", "zeno"), ("hub", "palazzo_ballroom"), ("casanova", "titian"):
            d, s = route_range(a, b), route_range(a, b, True)
            self.assertTrue(s["stepFree"])
            self.assertNotIn("escalator", " ".join(x["text"] for x in s["steps"]).lower())
            self.assertLessEqual(d["bestMinutes"], s["bestMinutes"])
            self.assertLessEqual(d["worstMinutes"], s["worstMinutes"])
        self.assertIn("elevator", " ".join(x["text"] for x in route_range("galileo", "zeno", True)["steps"]))
        self.assertGreater(route_range("casanova", "titian", True)["bestMinutes"], route_range("casanova", "titian")["bestMinutes"])
        self.assertTrue(g["model"]["elevatorExtraLevelMinutes"] < g["model"]["elevatorMinutes"])

    def test_room_in_endpoints(self):
        d = self.client.post("/sessions/route", json={"from": "Titian 2204", "to": "Casanova 607"}).json()["routeDetail"]
        self.assertIn("fromRoom=2204", d["mapUrls"][0]["url"])
        self.assertIn("toRoom=607", d["mapUrls"][0]["pngUrl"])
        for url in ("/venue/route?from=titian&to=casanova&fromRoom=2204&toRoom=607&level=1", "/venue/route.png?from=Titian%202204&to=Casanova%20607&level=2"):
            self.assertEqual(200, self.client.get(url).status_code)
        t = assess_transition({"code": "A", "date": "2026-10-26", "startTime": "09:00", "endTime": "10:00", "room": "2204", "area": "Titian", "level": 2},
                              {"code": "B", "date": "2026-10-26", "startTime": "10:00", "endTime": "11:00", "room": "607", "area": "Casanova", "level": 1})
        self.assertEqual(t["routeDetail"]["steps"][-1]["text"], "Arrive at Casanova 607")

    def test_step_free_endpoints_and_maps(self):
        r = self.client.post("/sessions/route", json={"from": "Galileo", "to": "Zeno", "stepFree": True})
        self.assertEqual(200, r.status_code)
        d = r.json()["routeDetail"]
        self.assertTrue(d["stepFree"])
        self.assertTrue(all("stepFree=1" in m["url"] and "stepFree=1" in m["pngUrl"] for m in d["mapUrls"]))
        self.assertFalse(self.client.post("/sessions/route", json={"from": "Galileo", "to": "Zeno"}).json()["routeDetail"]["stepFree"])
        for url in ("/venue/route?from=galileo&to=zeno&level=2&stepFree=1", "/venue/route.png?from=galileo&to=zeno&level=2&stepFree=1"):
            self.assertEqual(200, self.client.get(url).status_code)
        self.assertIn("Elevator (step-free)", self.client.get("/venue/map/2.svg").text)

    def test_step_free_in_mcp_tools(self):
        from app.mcp_server import check_walk, get_walk_route

        r = get_walk_route("Galileo", "Zeno", step_free=True).structuredContent
        self.assertTrue(r["routeDetail"]["stepFree"])
        self.assertIn("stepFree=1", r["routeDetail"]["mapUrls"][0]["url"])
        w = check_walk("Hall G", "Titian", 5, step_free=True)
        self.assertTrue(w["stepFree"])
        self.assertGreater(w["estimatedMinutes"]["best"], check_walk("Hall G", "Titian", 5)["estimatedMinutes"]["best"])

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

        r = get_walk_route("Hall G", "Titian").structuredContent
        self.assertIn("disclaimer", r)
        m = r["routeDetail"]["mapUrls"][0]
        self.assertTrue(m["url"].startswith("http") and ".png" in m["url"])
        self.assertIn("/venue/route?", m["svgUrl"])
        self.assertNotIn("polylines", r["routeDetail"])
        self.assertIn("error", get_walk_route("nowhere", "Titian").structuredContent)

    def test_tool_returns_image_blocks(self):
        import base64
        from app.mcp_server import check_transition, get_walk_route

        for res in (get_walk_route("Titian 2204", "Casanova 607"), check_transition("LRN2138", "LRN6075")):
            kinds = [c.type for c in res.content]
            self.assertEqual("text", kinds[0])
            imgs = [c for c in res.content if c.type == "image"]
            self.assertEqual(len(res.structuredContent["routeDetail"]["mapUrls"]), len(imgs))
            self.assertTrue(imgs)
            for c in imgs:
                self.assertEqual("image/png", c.mimeType)
                self.assertFalse(c.data.startswith("data:"))
                self.assertEqual(b"\x89PNG", base64.b64decode(c.data)[:4])
            self.assertIn("pageUrl", res.content[0].text)
        self.assertEqual(["text"], [c.type for c in get_walk_route("nowhere", "Titian").content])


if __name__ == "__main__":
    unittest.main()
