#!/usr/bin/env python3
"""Repair GeoJSON geometries under src/vncrcc/geo using Shapely.buffer(0).

Creates a .bak backup of each file changed and writes the repaired GeoJSON
with pretty JSON formatting. Keeps properties and feature order intact.

Usage: python tools/fix_geojson.py
"""
from pathlib import Path
import json
from shapely.geometry import shape, mapping
import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("fix_geojson")

ROOT = Path(__file__).resolve().parents[1]
GEO_DIR = ROOT / "src" / "vncrcc" / "geo"


def _load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception as e:
        logger.error("Failed to read %s: %s", path, e)
        return None


def _write_atomic(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=False))
    # backup original
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        path.replace(bak)
        tmp.replace(path)
    else:
        # if bak exists already, overwrite original and keep bak
        tmp.replace(path)


def _repair_feature_geom(geom_obj):
    try:
        shp = shape(geom_obj)
    except Exception:
        return geom_obj, False

    try:
        if not getattr(shp, "is_valid", True):
            repaired = shp.buffer(0)
            if getattr(repaired, "is_valid", False):
                return mapping(repaired), True
            else:
                return geom_obj, False
        else:
            # still return original mapping
            return geom_obj, False
    except Exception:
        return geom_obj, False


def repair_file(path: Path) -> bool:
    obj = _load_json(path)
    if obj is None:
        return False

    changed = False

    # Case 1: FeatureCollection
    if isinstance(obj, dict) and obj.get("features"):
        features = obj.get("features")
        for f in features:
            geom = f.get("geometry")
            if not geom:
                continue
            new_geom, repaired = _repair_feature_geom(geom)
            if repaired:
                logger.info("Repaired geometry in %s feature id=%s", path.name, f.get("id"))
                f["geometry"] = new_geom
                changed = True
    else:
        # maybe the file is a raw geometry object
        if isinstance(obj, dict) and obj.get("type") in ("Polygon", "MultiPolygon", "LineString", "MultiLineString", "Point"):
            new_geom, repaired = _repair_feature_geom(obj)
            if repaired:
                logger.info("Repaired top-level geometry in %s", path.name)
                obj = new_geom
                changed = True

    if changed:
        _write_atomic(path, obj)
    return changed


def main():
    if not GEO_DIR.exists():
        logger.error("Geo directory not found: %s", GEO_DIR)
        return

    files = list(GEO_DIR.glob("*.geojson")) + list(GEO_DIR.glob("*.json"))
    if not files:
        logger.info("No geojson/json files found in %s", GEO_DIR)
        return

    total = 0
    repaired_files = []
    for f in files:
        logger.info("Checking %s", f.name)
        try:
            if repair_file(f):
                repaired_files.append(f.name)
                total += 1
        except Exception as e:
            logger.error("Error repairing %s: %s", f.name, e)

    logger.info("")
    logger.info("Repaired %d file(s)", total)
    if repaired_files:
        logger.info("Files repaired: %s", ", ".join(repaired_files))


if __name__ == "__main__":
    main()
