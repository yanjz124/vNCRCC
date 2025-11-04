import os
import json
from vncrcc import storage as storage_mod
from vncrcc.geo.loader import find_geo_by_keyword, point_from_aircraft
from shapely.geometry import Point

STORAGE = storage_mod.STORAGE
if STORAGE is None:
    print('No STORAGE available; cannot inspect live DB')
    raise SystemExit(1)

snap = STORAGE.get_latest_snapshot()
if not snap:
    print('No snapshot found in DB')
    raise SystemExit(0)

print('Snapshot fetched_at:', snap.get('fetched_at'))

data = snap.get('data') or {}
aircraft = data.get('pilots') or data.get('aircraft') or []
print('Aircraft count in snapshot:', len(aircraft))

shapes = find_geo_by_keyword('frz')
if not shapes:
    print('FRZ shapes not found')
    raise SystemExit(1)

# use first shape
shp, props = shapes[0]
print('Using FRZ shape geom_type:', getattr(shp, 'geom_type', None))
print('FRZ props:', props)

def check_ac(a, tol=0.001):
    pt = point_from_aircraft(a)
    if not pt:
        return {'ok': False, 'reason': 'no coords', 'pt': None}
    lat = a.get('latitude') or a.get('lat') or a.get('y')
    lon = a.get('longitude') or a.get('lon') or a.get('x')
    alt = a.get('altitude') or a.get('alt')
    try:
        altv = float(alt) if alt is not None else None
    except Exception:
        altv = None
    contains = False
    touches = False
    near = False
    intersects = False
    try:
        contains = shp.contains(pt)
        touches = shp.touches(pt)
        d = pt.distance(shp)
        near = d <= tol
        intersects = shp.intersects(pt)
    except Exception as e:
        return {'ok': False, 'reason': f'geom error: {e}'}
    return {
        'ok': True,
        'callsign': a.get('callsign') or a.get('call_sign') or a.get('cid'),
        'lat': lat,
        'lon': lon,
        'alt': altv,
        'contains': contains,
        'touches': touches,
        'near_tol': near,
        'distance': d,
        'intersects': intersects,
    }

matches = []
for i, a in enumerate(aircraft[:200]):
    res = check_ac(a)
    print(i, res['callsign'], 'lat', res['lat'], 'lon', res['lon'], 'alt', res.get('alt'), 'contains', res['contains'], 'touches', res['touches'], 'near', res['near_tol'], 'dist', round(res['distance'],6))
    if res['contains'] or res['touches'] or res['near_tol']:
        matches.append(res)

print('\nTotal matches:', len(matches))
if matches:
    print('Sample match:', matches[0])
