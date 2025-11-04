from vncrcc.geo.loader import find_geo_by_keyword
from vncrcc import storage as storage_mod
from vncrcc.storage import Storage
from vncrcc import app as vn_app
from fastapi.testclient import TestClient
import time
from shapely.geometry import Point

shapes = find_geo_by_keyword('frz')
print('shapes found', bool(shapes))
if not shapes:
    raise SystemExit('FRZ shapes not found')
shp = shapes[0][0]

# interior point helper
def interior(shp):
    c = shp.centroid
    if shp.contains(c):
        return c
    r = shp.representative_point()
    if shp.contains(r):
        return r
    minx, miny, maxx, maxy = shp.bounds
    for i in range(20):
        for j in range(20):
            x = minx + (maxx - minx) * (i + 0.5) / 20
            y = miny + (maxy - miny) * (j + 0.5) / 20
            p = Point(x, y)
            if shp.contains(p):
                return p
    return r

pt = interior(shp)
print('pt', pt.x, pt.y, 'contains?', shp.contains(pt), 'touches?', shp.touches(pt))
lat = pt.y
lon = pt.x

s = Storage(':memory:')
storage_mod.STORAGE = s

a_ok = {"callsign": "OK_TEST", "latitude": lat, "longitude": lon, "altitude": 5000}
s.save_snapshot({"pilots": [a_ok]}, time.time())

client = TestClient(vn_app.app)
r = client.get('/api/v1/frz/?name=frz')
print('status', r.status_code)
print(r.json())
