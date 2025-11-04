import os
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

from vncrcc import app as vn_app
from vncrcc import storage as storage_mod
from vncrcc.geo.loader import find_geo_by_keyword
from vncrcc.storage import Storage
from shapely.geometry import Point


def _interior_point(shp, samples: int = 20):
    """Return a point strictly inside the polygon `shp` by sampling a grid
    inside its bounds. Falls back to centroid or representative_point.
    """
    # If this is a MultiPolygon or GeometryCollection, pick the largest polygon
    try:
        geoms = list(getattr(shp, "geoms", []))
    except Exception:
        geoms = []
    if geoms:
        # choose largest-area geometry for sampling
        shp = max(geoms, key=lambda g: getattr(g, "area", 0))

    minx, miny, maxx, maxy = shp.bounds
    pad_x = (maxx - minx) * 0.001 or 1e-6
    pad_y = (maxy - miny) * 0.001 or 1e-6
    minx += pad_x
    miny += pad_y
    maxx -= pad_x
    maxy -= pad_y
    if minx >= maxx or miny >= maxy:
        return shp.centroid
    for i in range(samples):
        for j in range(samples):
            x = minx + (maxx - minx) * (i + 0.5) / samples
            y = miny + (maxy - miny) * (j + 0.5) / samples
            p = Point(x, y)
            if shp.contains(p):
                return p
    c = shp.centroid
    if shp.contains(c):
        return c
    return shp.representative_point()


class TestGeoEndpoints(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db_path = path
        self.storage = Storage(self.db_path)
        # Replace module-level STORAGE singleton used by endpoints
        storage_mod.STORAGE = self.storage
        self.client = TestClient(vn_app.app)

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except Exception:
            pass

    def test_sfra_altitude_filtering(self):
        shapes = find_geo_by_keyword("sfra")
        self.assertTrue(shapes and len(shapes) > 0, "SFRA geo not found in geo directory")
        shp, _ = shapes[0]

        # Find a point that is strictly inside the shape (shp.contains returns True).
        # representative_point() sometimes lies on the boundary for complex polygons,
        # so sample a small grid inside the polygon bounds until an interior point is found.
        def _interior_point(shp, samples=20):
            minx, miny, maxx, maxy = shp.bounds
            # shrink bounds slightly to avoid exact boundary points
            pad_x = (maxx - minx) * 0.001 or 1e-6
            pad_y = (maxy - miny) * 0.001 or 1e-6
            minx += pad_x
            miny += pad_y
            maxx -= pad_x
            maxy -= pad_y
            if minx >= maxx or miny >= maxy:
                # degenerate bounds, fallback to centroid
                return shp.centroid
            for i in range(samples):
                for j in range(samples):
                    x = minx + (maxx - minx) * (i + 0.5) / samples
                    y = miny + (maxy - miny) * (j + 0.5) / samples
                    p = Point(x, y)
                    if shp.contains(p):
                        return p
            # last-resort: centroid or representative_point
            c = shp.centroid
            if shp.contains(c):
                return c
            r = shp.representative_point()
            return r

        pt = _interior_point(shp)
        lat = pt.y
        lon = pt.x

        a_ok = {"callsign": "OK1", "latitude": lat, "longitude": lon, "altitude": 10000}
        a_high = {"callsign": "HIGH1", "latitude": lat, "longitude": lon, "altitude": 30000}
        a_noalt = {"callsign": "NOALT", "latitude": lat, "longitude": lon}

        data = {"pilots": [a_ok, a_high, a_noalt]}
        self.storage.save_snapshot(data, time.time())

        r = self.client.get("/api/v1/sfra/?name=sfra")
        self.assertEqual(r.status_code, 200)
        aircrafts = r.json().get("aircraft", [])
        calls = [item["aircraft"]["callsign"] for item in aircrafts]
        self.assertIn("OK1", calls)
        self.assertNotIn("HIGH1", calls)
        self.assertNotIn("NOALT", calls)

    def test_frz_altitude_filtering(self):
        shapes = find_geo_by_keyword("frz")
        self.assertTrue(shapes and len(shapes) > 0, "FRZ geo not found in geo directory")
        shp, _ = shapes[0]

        # find an interior point for FRZ using the same sampling helper
        pt = _interior_point(shp)
        lat = pt.y
        lon = pt.x

        a_ok = {"callsign": "OK2", "latitude": lat, "longitude": lon, "altitude": 5000}
        a_high = {"callsign": "HIGH2", "latitude": lat, "longitude": lon, "altitude": 25000}

        data = {"pilots": [a_ok, a_high]}
        self.storage.save_snapshot(data, time.time())

        r = self.client.get("/api/v1/frz/?name=frz")
        self.assertEqual(r.status_code, 200)
        aircrafts = r.json().get("aircraft", [])
        calls = [item["aircraft"]["callsign"] for item in aircrafts]
        self.assertIn("OK2", calls)
        self.assertNotIn("HIGH2", calls)


if __name__ == "__main__":
    unittest.main()
