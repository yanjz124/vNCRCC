import os
import tempfile
import time
import unittest
import json
import asyncio

from vncrcc.geo.loader import find_geo_by_keyword
from vncrcc.api.v1 import p56 as p56_mod
import vncrcc.p56_history as p56_history
from vncrcc import storage as storage_module
from vncrcc.storage import Storage


def build_snapshot_with_aircraft(ac_list):
    return {"general": {"version": 3, "update_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "pilots": ac_list}


class TestP56Detection(unittest.TestCase):
    def setUp(self):
        # Create a temp sqlite DB file for isolation
        self.tmp_db_fd, self.tmp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.tmp_db_fd)
        # Create isolated Storage and patch module STORAGE
        self.orig_storage = getattr(storage_module, "STORAGE", None)
        self.storage = Storage(db_path=self.tmp_db_path)
        storage_module.STORAGE = self.storage

        # Use a temp history path
        self.tmp_hist = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self.tmp_hist.close()
        self.orig_history_path = p56_history.HISTORY_PATH
        p56_history.HISTORY_PATH = os.path.abspath(self.tmp_hist.name)

    def tearDown(self):
        # restore original STORAGE
        storage_module.STORAGE = self.orig_storage
        try:
            os.remove(self.tmp_db_path)
        except Exception:
            pass
        # restore original history path
        p56_history.HISTORY_PATH = self.orig_history_path
        try:
            os.remove(self.tmp_hist.name)
        except Exception:
            pass

    def _find_p56_shape(self):
        shapes = find_geo_by_keyword("p56")
        self.assertTrue(shapes, "P56 geo must exist for tests")
        return shapes[0][0]

    def _choose_crossing_pair(self, shp):
        # Sample points around centroid and return a pair whose line intersects shp
        from shapely.geometry import Point, LineString
        import math

        inside_pt = shp.representative_point()
        cx, cy = inside_pt.x, inside_pt.y
        minx, miny, maxx, maxy = shp.bounds
        radius = max(maxx - minx, maxy - miny) * 1.5
        if radius <= 0:
            radius = 0.01
        samples = []
        for deg in range(0, 360, 15):
            rad = math.radians(deg)
            samples.append(Point(cx + math.cos(rad) * radius, cy + math.sin(rad) * radius))

        for i, p1 in enumerate(samples):
            if shp.contains(p1):
                continue
            for j in range(i + 1, len(samples)):
                p2 = samples[j]
                if shp.contains(p2):
                    continue
                if shp.intersects(LineString([(p1.x, p1.y), (p2.x, p2.y)])):
                    return p1, p2, inside_pt

        # fallback: return two bbox-side points
        from shapely.geometry import Point as _P

        return _P(minx - 0.01, cy), _P(maxx + 0.01, cy), inside_pt

    def test_line_cross_detection(self):
        shp = self._find_p56_shape()
        p1, p2, _inside = self._choose_crossing_pair(shp)

        cid = 999001
        prev_ac = [{"cid": cid, "callsign": "TESTLINE", "latitude": p1.y, "longitude": p1.x, "altitude": 15000}]
        latest_ac = [{"cid": cid, "callsign": "TESTLINE", "latitude": p2.y, "longitude": p2.x, "altitude": 15000}]

        # save two snapshots
        t0 = time.time() - 5
        t1 = time.time()
        self.storage.save_snapshot(build_snapshot_with_aircraft(prev_ac), t0)
        self.storage.save_snapshot(build_snapshot_with_aircraft(latest_ac), t1)

        res = asyncio.get_event_loop().run_until_complete(p56_mod.p56_breaches(name="p56"))
        # Expect at least one breach for this CID
        breaches = res.get("breaches", [])
        ids = {b.get("identifier") for b in breaches}
        self.assertIn(str(cid), ids)

    def test_point_in_detection(self):
        shp = self._find_p56_shape()
        _, _, inside = self._choose_crossing_pair(shp)

        cid = 999002
        # prev outside point (use bounding box outside)
        minx, miny, maxx, maxy = shp.bounds
        prev = {"cid": cid, "callsign": "TESTP_PREV", "latitude": inside.y + (maxy - miny) + 0.02, "longitude": inside.x + (maxx - minx) + 0.02, "altitude": 15000}
        latest = {"cid": cid, "callsign": "TESTP", "latitude": inside.y, "longitude": inside.x, "altitude": 15000}

        t0 = time.time() - 5
        t1 = time.time()
        self.storage.save_snapshot(build_snapshot_with_aircraft([prev]), t0)
        self.storage.save_snapshot(build_snapshot_with_aircraft([latest]), t1)

        res = asyncio.get_event_loop().run_until_complete(p56_mod.p56_breaches(name="p56"))
        breaches = res.get("breaches", [])
        ids = {b.get("identifier") for b in breaches}
        self.assertIn(str(cid), ids)


if __name__ == "__main__":
    unittest.main()
