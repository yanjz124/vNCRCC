#!/usr/bin/env python3
"""Simulate P56 penetrations for testing.

This script creates two snapshots (previous and latest) and saves them to
the project's Storage singleton so the API's P56 detection logic can be
exercised locally without live network traffic. It runs two scenarios:

- line-cross: both positions are outside the P56 polygon but the straight
  line between them intersects the polygon (tests LineString detection).
- point-in: previous position outside, latest position inside the polygon
  (tests point-in-polygon detection).

The script records the DB incidents and the p56 history state before the
test and restores them afterwards so it cleans up after itself.

Usage: run from the repository root with PYTHONPATH=src so the package
imports resolve. Example (PowerShell):

  $env:PYTHONPATH='src'; python tools/sim_p56_test.py

"""
import asyncio
import json
import time
from copy import deepcopy

from vncrcc import storage
from vncrcc.geo.loader import find_geo_by_keyword
from vncrcc.api.v1 import p56 as p56_mod
import vncrcc.p56_history as p56_history


def ensure_storage():
    if getattr(storage, "STORAGE", None) is None:
        from vncrcc.storage import Storage

        storage.STORAGE = Storage()


def save_snapshot_and_get_id(snapshot):
    ts = time.time()
    sid = storage.STORAGE.save_snapshot(snapshot, ts)
    return sid, ts


def build_snapshot_with_aircraft(ac_list):
    # minimal snapshot structure expected by the code
    return {"general": {"version": 3, "update_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "pilots": ac_list}


def get_incident_ids():
    return {i["id"] for i in storage.STORAGE.list_incidents(limit=1000)}


def delete_incidents(ids):
    cur = storage.STORAGE.conn.cursor()
    for _id in ids:
        cur.execute("DELETE FROM incidents WHERE id = ?", (_id,))
    storage.STORAGE.conn.commit()


def write_history(obj):
    # overwrite history file atomically
    path = p56_history.HISTORY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str))


def find_p56_shape():
    shapes = find_geo_by_keyword("p56")
    if not shapes:
        raise RuntimeError("No P56 geo found in src/vncrcc/geo")
    # prefer first polygon feature
    for shp, props in shapes:
        return shp, props
    raise RuntimeError("P56 shapes not found")


def choose_outside_and_inside_points(shp):
    # Prefer to find two outside points such that the straight line between
    # them intersects the shape. We'll sample points on a circle around the
    # shape centroid and look for a pair whose LineString intersects `shp`.
    from shapely.geometry import Point, LineString
    import math

    inside_pt = shp.representative_point()
    cx, cy = inside_pt.x, inside_pt.y
    minx, miny, maxx, maxy = shp.bounds
    # radius: a bit larger than the max dimension
    radius = max(maxx - minx, maxy - miny) * 1.5
    if radius <= 0:
        radius = 0.01

    # sample points around the centroid
    samples = []
    for deg in range(0, 360, 10):
        rad = math.radians(deg)
        px = cx + math.cos(rad) * radius
        py = cy + math.sin(rad) * radius
        samples.append(Point(px, py))

    # find any pair of sample points that are both outside and whose line intersects
    for i, p1 in enumerate(samples):
        if shp.contains(p1):
            continue
        for j in range(i + 1, len(samples)):
            p2 = samples[j]
            if shp.contains(p2):
                continue
            line = LineString([(p1.x, p1.y), (p2.x, p2.y)])
            try:
                if shp.intersects(line):
                    return (p1, p2, inside_pt)
            except Exception:
                continue

    # fallback: use bbox-west/east if no crossing pair found
    west = Point(minx - 0.01, cy)
    east = Point(maxx + 0.01, cy)
    return (west, east, inside_pt)


async def run_p56_check(name="p56"):
    res = await p56_mod.p56_breaches(name=name)
    return res


def scenario_line_cross(shp, cid_base=900000):
    west, east, inside = choose_outside_and_inside_points(shp)
    # build 2 snapshots: prev at west, latest at east
    prev_ac = [
        {
            "cid": cid_base,
            "callsign": "SIMLINE",
            "latitude": west.y,
            "longitude": west.x,
            "altitude": 15000,
        }
    ]
    latest_ac = [
        {
            "cid": cid_base,
            "callsign": "SIMLINE",
            "latitude": east.y,
            "longitude": east.x,
            "altitude": 15000,
        }
    ]
    return prev_ac, latest_ac


def scenario_point_in(shp, cid_base=910000):
    _, _, inside = choose_outside_and_inside_points(shp)
    # prev outside (west), latest inside (inside)
    west = shp.representative_point()
    # find an outside point quickly
    from shapely.geometry import Point

    minx, miny, maxx, maxy = shp.bounds
    outside = Point(minx - 0.02, inside.y)
    prev_ac = [
        {
            "cid": cid_base,
            "callsign": "SIMPOINT_PREV",
            "latitude": outside.y,
            "longitude": outside.x,
            "altitude": 15000,
        }
    ]
    latest_ac = [
        {
            "cid": cid_base,
            "callsign": "SIMPOINT",
            "latitude": inside.y,
            "longitude": inside.x,
            "altitude": 15000,
        }
    ]
    return prev_ac, latest_ac


def run_scenario(prev_ac, latest_ac):
    # Save previous then latest snapshot
    prev_snap = build_snapshot_with_aircraft(prev_ac)
    latest_snap = build_snapshot_with_aircraft(latest_ac)
    t0 = time.time() - 10
    t1 = time.time()
    storage.STORAGE.save_snapshot(prev_snap, t0)
    storage.STORAGE.save_snapshot(latest_snap, t1)

    # run detection
    res = asyncio.run(run_p56_check(name="p56"))
    return res


def main():
    ensure_storage()
    shp, props = find_p56_shape()

    # snapshot pre-test state for cleanup
    pre_incidents = get_incident_ids()
    pre_history = deepcopy(p56_history.get_history())

    print("Running line-cross scenario...")
    prev_ac, latest_ac = scenario_line_cross(shp, cid_base=900001)
    out_line = run_scenario(prev_ac, latest_ac)
    print("Line-cross result:")
    print(json.dumps(out_line, indent=2, default=str))

    print("Running point-in scenario...")
    prev_ac2, latest_ac2 = scenario_point_in(shp, cid_base=910001)
    out_point = run_scenario(prev_ac2, latest_ac2)
    print("Point-in result:")
    print(json.dumps(out_point, indent=2, default=str))

    # cleanup: remove any new incidents
    post_incidents = storage.STORAGE.list_incidents(limit=1000)
    post_ids = {i["id"] for i in post_incidents}
    new_ids = post_ids - pre_incidents
    if new_ids:
        print(f"Cleaning up {len(new_ids)} incident(s): {new_ids}")
        delete_incidents(new_ids)
    else:
        print("No new incidents to clean up.")

    # restore p56 history
    write_history(pre_history)
    print("Restored p56 history to pre-test state.")

    print("Simulation complete.")


if __name__ == "__main__":
    main()
