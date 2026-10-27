import unittest

from app.hub import booth_info, booths, find_booths, match_company
from app.routing import graph, place_room, room_key, room_rect, route_range
from app.venue import resolve_place

try:
    from starlette.testclient import TestClient
    from app.asgi import app
except ImportError:  # mcp/starlette not installed
    app = None


class HubDataTests(unittest.TestCase):
    def test_every_booth_has_a_rectangle_inside_the_hub(self):
        rooms = graph()["rooms"]["hub"]
        x, y, w, h = graph()["nodes"]["hub"]["rect"]
        self.assertEqual(168, len(booths()))
        for number in booths():
            self.assertIn(number, rooms, number)
        for name, (rx, ry, rw, rh) in rooms.items():
            self.assertTrue(x <= rx and rx + rw <= x + w and y <= ry and ry + rh <= y + h, name)

    def test_theaters_one_to_twelve(self):
        for n in range(1, 13):
            self.assertIn(f"T{n}", graph()["rooms"]["hub"])
            self.assertEqual(f"T{n}", room_key("hub", f"Theater {n}"))
        self.assertEqual("T12", room_key("hub", "Built to Win Theater 12"))
        self.assertEqual("T3", place_room("Theater 3, Oracle AI World Hub", "hub"))

    def test_numbering_rules(self):
        r = graph()["rooms"]["hub"]
        # slots rise away from the entrance (up the plan = smaller y). Row 1 is clean; in the other rows only the
        # odd-slot side is checked, because the traced SVG puts some even-slot booths off their row (see the README)
        placed = lambda n: n.isdigit() and n not in graph()["roomStatus"]["hub"]
        row1 = sorted((int(n) % 100, v[1]) for n, v in r.items() if placed(n) and int(n) // 1000 == 1 and int(n) % 100 < 10)
        self.assertEqual([y for _, y in row1], sorted((y for _, y in row1), reverse=True))
        for row in (2, 5):
            odd = sorted((int(n) % 100, v[1]) for n, v in r.items() if placed(n) and int(n) // 1000 == row
                         and int(n) % 2 and int(n) % 100 < 14)
            self.assertEqual([y for _, y in odd], sorted((y for _, y in odd), reverse=True), row)
        self.assertLess(r["1001"][0], r["4009"][0])  # row 1 is left of row 4
        self.assertLess(r["2144"][1], r["2142"][1])  # 2142 and 2144 are at the far end, beside 2043 and 2045
        self.assertLess(abs(r["2043"][1] - r["2142"][1]), 40)

    def test_positions_come_from_the_svg_and_gaps_are_flagged(self):
        status = graph()["roomStatus"]["hub"]
        self.assertEqual(21, len(status))
        self.assertEqual({"estimated"}, set(status.values()))
        for n in ("2025", "8022", "13027"):
            self.assertIn(n, status)
            self.assertIn(n, graph()["rooms"]["hub"])
        rot = graph()["roomRotation"]["hub"]
        self.assertEqual({20.0, -30.0, 3.0}, set(rot.values()))
        self.assertNotIn("4008", {n for n in rot if n not in status})
        self.assertGreater(len(graph()["levels"]["6"]["outline"]), 10)

    def test_hub_is_in_hall_c(self):
        route = route_range("hall_c", "hub")
        self.assertEqual(["hall_c", "hub_entry", "hub"], route["path"])
        self.assertEqual("hub", resolve_place("Oracle AI World Hub"))
        self.assertEqual("hub", resolve_place("Theater 7"))
        self.assertEqual("hub", resolve_place("booth 4009"))
        self.assertEqual("hub", resolve_place("NVIDIA"))
        self.assertIsNone(resolve_place("Nowhere Inc"))


class BoothSearchTests(unittest.TestCase):
    def test_by_number_name_and_prefix(self):
        self.assertEqual("NVIDIA", find_booths("4009")[0]["name"])
        self.assertEqual("4009", find_booths("booth 4009")[0]["number"])
        self.assertEqual("4009", find_booths("nvidia")[0]["number"])
        self.assertEqual("2003", find_booths("accen")[0]["number"])
        self.assertEqual([], find_booths("zzzzzz"))
        self.assertEqual([], find_booths("9999"))
        self.assertEqual("4009", match_company("the NVIDIA booth"))
        self.assertIsNone(match_company("hall"))
        self.assertEqual({"number": "4009", "name": "NVIDIA", "row": 4, "slot": 9}, booth_info("4009"))


class AreaSearchTests(unittest.TestCase):
    def test_areas_by_name_and_part(self):
        from app.hub import find_areas

        for q in ("ACE", "ace", "ACE LOUNGE", "the ACE lounge"):
            self.assertEqual(["ACE LOUNGE"], [a["number"] for a in find_areas(q)], q)
        self.assertEqual("ORACLE TV", find_areas("Oracle TV")[0]["number"])
        self.assertEqual("ORACLE TV", find_areas("tv")[0]["number"])
        self.assertEqual("SWAG STATION", find_areas("swag")[0]["number"])
        self.assertEqual("THE SHOP", find_areas("shop")[0]["number"])
        self.assertEqual("ZF", find_areas("zone F")[0]["number"])
        self.assertEqual("ZD", find_areas("customer success")[0]["number"])
        self.assertEqual({"ACE LOUNGE", "MULTICLOUD LOUNGE"}, {a["number"] for a in find_areas("lounge")})
        self.assertEqual("theater", find_areas("Theater 3")[0]["kind"])
        self.assertEqual("area", find_areas("ACE")[0]["kind"])
        self.assertEqual([], find_areas("a"))
        self.assertEqual([], find_areas("xyzzy"))

    def test_ace_is_not_a_sponsor_booth(self):
        self.assertEqual([], find_booths("ACE"))

    def test_areas_as_places(self):
        self.assertEqual("hub", resolve_place("ACE Lounge"))
        self.assertEqual("hub", resolve_place("zone F"))
        self.assertEqual("ACE LOUNGE", place_room("ACE Lounge", "hub"))
        self.assertEqual("ACE LOUNGE", room_key("hub", "ACE LOUNGE"))
        r = route_range("hub", "hub", False, "4009", "ACE LOUNGE")
        self.assertEqual([6], r["levels"])
        self.assertIn("ACE Lounge", r["steps"][0]["text"])
        self.assertGreater(r["meters"], 50)


def hub_view_for(route):
    from app.routing import hub_view

    return hub_view(route)


class HubRouteTests(unittest.TestCase):
    def test_booth_to_booth_walks_between_aisle_sides(self):
        r = route_range("hub", "hub", False, "2003", "4009")
        self.assertEqual([6], r["levels"])
        self.assertGreater(r["meters"], 20)
        self.assertLess(r["meters"], 120)
        self.assertIn("Booth 2003 (Accenture)", r["steps"][0]["text"])
        self.assertIn("Booth 4009 (NVIDIA)", r["steps"][0]["text"])
        self.assertEqual(r["meters"], route_range("hub", "hub", False, "4009", "2003")["meters"])
        self.assertGreater(route_range("hub", "hub", False, "1001", "13029")["meters"], r["meters"])

    def test_view_holds_the_whole_plan_and_the_legend(self):
        view = graph()["levels"]["6"]["view"]
        outline = graph()["levels"]["6"]["outline"]
        x, y, w, h = view
        self.assertTrue(all(x <= px <= x + w and y <= py <= y + h for px, py in outline))
        entry = graph()["nodes"]["hub_entry"]
        self.assertLessEqual(entry["y"] + 40, y + h)
        for name, (rx, ry, rw, rh) in graph()["rooms"]["hub"].items():
            self.assertTrue(x <= rx and rx + rw <= x + w and y <= ry and ry + rh <= y + h, name)
        from app.mapsvg import _legend

        legend = _legend(x, y, w, h)  # the legend box spans y-24 .. y+94 and must stay inside the view
        top = float(__import__("re").search(r'<rect x="[\d.]+" y="([\d.]+)"', legend).group(1))
        self.assertGreaterEqual(top, y)
        self.assertLessEqual(top + 118, y + h)

    def test_map_urls_carry_the_data_version(self):
        from app.routing import data_version
        from app.venue import route_details

        d = route_details("hub", "hub", False, None, "ACE LOUNGE")
        self.assertIn(f"&v={data_version()}", d["mapUrls"][0]["url"])
        self.assertIn(f"&v={data_version()}", d["mapUrls"][0]["pngUrl"])
        self.assertEqual(8, len(data_version()))

    def test_ace_lounge_sits_below_the_multicloud_lounge(self):
        r = graph()["rooms"]["hub"]
        ace, lounge = r["ACE LOUNGE"], r["MULTICLOUD LOUNGE"]
        self.assertAlmostEqual(ace[0] + ace[2] / 2, lounge[0] + lounge[2] / 2, delta=1)  # same centre line
        self.assertGreaterEqual(ace[1], lounge[1] + lounge[3])  # below it, not overlapping

    def test_label_of_the_found_stand_is_drawn_last(self):
        from app.mapsvg import found_labels, render_level

        r = route_range("hub", "hub", False, None, "4009")
        svg = render_level(6, r)
        label = svg.rindex("4009 NVIDIA")
        self.assertGreater(label, svg.rindex('class="route"'))   # above the route line
        self.assertGreater(label, svg.index('r="20" fill="#B8321F"'))  # above the A/B markers
        self.assertGreater(label, svg.rindex('rx="1.5"'))              # above every booth box
        self.assertEqual(1, svg.count("4009 NVIDIA"))
        self.assertEqual(["4009 NVIDIA"], [t for _, _, t, _ in found_labels(r, 6, hub_view_for(r))])

    def test_label_stays_inside_the_map(self):
        from app.mapsvg import found_labels

        for room in ("ACE LOUNGE", "1001", "13029", "T1"):
            r = route_range("hub", "hub", False, None, room)
            x, y, w, h = hub_view_for(r)
            (cx, cy, text, size), = found_labels(r, 6, [x, y, w, h])
            half = len(text) * size * 0.31
            self.assertTrue(x <= cx - half and cx + half <= x + w, room)
            self.assertTrue(y <= cy - size and cy <= y + h, room)

    def test_estimated_booths_are_noted(self):
        from app.venue import route_details

        d = route_details("hub", "hub", False, None, "8022")
        self.assertEqual(["8022"], d["estimatedPosition"])
        self.assertIn("estimated", d["positionNote"])
        self.assertNotIn("estimatedPosition", route_details("hub", "hub", False, None, "4009"))

    def test_map_is_cropped_to_the_route(self):
        from app.routing import hub_view

        whole = hub_view(None)
        near = hub_view(route_range("hub", "hub", False, "2003", "4009"))
        self.assertLess(near[2] * near[3], whole[2] * whole[3] / 2)
        self.assertTrue(whole[0] <= near[0] and near[0] + near[2] <= whole[0] + whole[2])

    def test_from_outside_into_the_hub(self):
        r = route_range("hall_g", "hub", False, None, "4009")
        self.assertEqual([1, 2, 6], r["levels"])
        self.assertIn("Arrive at Booth 4009 (NVIDIA)", r["steps"][-1]["text"])
        near = route_range("hall_g", "hub", False, None, "1001")["meters"]
        far = route_range("hall_g", "hub", False, None, "13029")["meters"]
        self.assertGreater(far, near)
        t = route_range("hub", "titian", False, "T3", "2204")
        self.assertEqual([6, 2], t["levels"])
        self.assertIn("Leave Theater 3", t["steps"][0]["text"])

    def test_room_rect_for_booths(self):
        self.assertEqual(graph()["rooms"]["hub"]["4009"], room_rect("hub", "4009"))
        self.assertEqual(graph()["rooms"]["hub"]["T3"], room_rect("hub", "Theater 3".upper().replace(" ", "")) or room_rect("hub", "T3"))


@unittest.skipIf(app is None, "mcp/starlette not installed")
class HubWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_booth_search_endpoint(self):
        r = self.client.get("/booths/search?q=nvidia").json()
        self.assertEqual(1, r["count"])
        self.assertEqual("4009", r["results"][0]["number"])
        self.assertTrue(r["results"][0]["routeDetail"]["steps"][0]["text"].startswith("Walk from the Hub entrance"))
        t = self.client.post("/booths/search", json={"query": "Theater 3"}).json()
        self.assertEqual("Theater 3", t["results"][0]["name"])
        self.assertEqual(0, self.client.get("/booths/search?q=zzzz").json()["count"])
        self.assertEqual(400, self.client.get("/booths/search?q=a&limit=x").status_code)

    def test_area_search_endpoint_and_tools(self):
        from app.mcp_server import check_walk, find_booth, get_walk_route

        for q in ("ACE", "ACE LOUNGE"):
            r = self.client.get("/booths/search", params={"q": q}).json()
            self.assertEqual(1, r["count"], q)
            self.assertEqual(("ACE LOUNGE", "area"), (r["results"][0]["number"], r["results"][0]["kind"]))
            self.assertIn("ACE Lounge", r["results"][0]["routeDetail"]["steps"][0]["text"])
        f = find_booth("ace lounge")["results"][0]
        self.assertEqual("area", f["kind"])
        self.assertIn("/venue/route/page?", f["routeDetail"]["pageUrl"])
        w = get_walk_route("NVIDIA", "ACE Lounge").structuredContent["routeDetail"]
        self.assertEqual([6], w["levels"])
        self.assertEqual("ok", check_walk("Oracle TV", "ACE Lounge", 10)["verdict"])
        self.assertEqual(200, self.client.get("/venue/route.png?from=hub&to=hub&toRoom=ACE%20LOUNGE&level=6").status_code)

    def test_hub_maps(self):
        for url in ("/venue/route.png?from=hub&to=hub&fromRoom=2003&toRoom=4009&level=6", "/venue/map/6.png"):
            r = self.client.get(url)
            self.assertEqual(200, r.status_code, url)
            self.assertEqual(b"\x89PNG", r.content[:4])
        svg = self.client.get("/venue/route?from=hub&to=hub&fromRoom=2003&toRoom=4009&level=6").text
        self.assertIn("Booth", svg) if False else self.assertIn("Accenture", svg)
        self.assertIn("NVIDIA", svg)
        self.assertEqual(200, self.client.get("/venue/route/page?from=hub&to=hub&toRoom=4009").status_code)

    def test_mcp_tools(self):
        from app.mcp_server import find_booth, get_walk_route

        f = find_booth("NVIDIA")
        self.assertEqual("4009", f["results"][0]["number"])
        self.assertIn("/venue/route/page?", f["results"][0]["routeDetail"]["pageUrl"])
        w = get_walk_route("Booth 2003", "NVIDIA")
        self.assertEqual("image", [c.type for c in w.content][1])
        self.assertEqual([6], w.structuredContent["routeDetail"]["levels"])
        self.assertEqual("Hub plan", w.structuredContent["routeDetail"]["mapUrls"][0]["label"])


if __name__ == "__main__":
    unittest.main()
