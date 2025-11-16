import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from shapely.geometry import shape, Point, mapping, base
import logging

logger = logging.getLogger("vncrcc.geo.loader")

GEO_DIR = Path(__file__).parent
_GEO_CACHE: Optional[Dict[str, List[Tuple[base.BaseGeometry, Dict]]]] = None


def _load_geojson(path: Path) -> List[Tuple[base.BaseGeometry, Dict]]:
    """Load a geojson file and return a list of (shapely_shape, properties)."""
    try:
        raw = json.loads(path.read_text())
    except Exception:
        logger.exception("Failed to read/parse %s", path)
        return []

    shapes_out: List[Tuple[base.BaseGeometry, Dict]] = []

    if isinstance(raw, dict) and raw.get("type") == "FeatureCollection":
        features = raw.get("features") or []
        for f in features:
            geom = f.get("geometry") if isinstance(f, dict) else None
            props = f.get("properties") or {} if isinstance(f, dict) else {}
            if not geom:
                continue
            try:
                shp = shape(geom)
                if not getattr(shp, "is_valid", True):
                    try:
                        repaired = shp.buffer(0)
                        if getattr(repaired, "is_valid", False):
                            logger.warning("Repaired invalid geometry in %s using buffer(0)", path.name)
                            shp = repaired
                    except Exception:
                        logger.exception("Failed to repair geometry in %s", path.name)
                shapes_out.append((shp, props))
            except Exception:
                logger.exception("Failed to parse geometry in %s", path.name)

    elif isinstance(raw, dict) and raw.get("type") == "Feature":
        geom = raw.get("geometry")
        props = raw.get("properties") or {}
        if geom:
            try:
                shp = shape(geom)
                shapes_out.append((shp, props))
            except Exception:
                logger.exception("Failed to parse feature in %s", path.name)

    elif isinstance(raw, dict) and raw.get("type") in ("Polygon", "MultiPolygon", "Point", "LineString", "MultiLineString"):
        try:
            shp = shape(raw)
            shapes_out.append((shp, {}))
        except Exception:
            logger.exception("Failed to parse geometry in %s", path.name)

    return shapes_out


def load_all_geojson() -> Dict[str, List[Tuple[base.BaseGeometry, Dict]]]:
    """Load all .geojson and .json files in the geo directory.

    Returns a dict mapping filename stem -> list of (shape, properties).
    Uses a module-level cache to avoid repeated disk I/O.
    """
    global _GEO_CACHE
    if _GEO_CACHE is not None:
        return _GEO_CACHE

    out: Dict[str, List[Tuple[base.BaseGeometry, Dict]]] = {}
    for ext in ("*.geojson", "*.json"):
        for p in GEO_DIR.glob(ext):
            key = p.stem.lower()
            out[key] = _load_geojson(p)

    _GEO_CACHE = out
    try:
        total_shapes = sum(len(v) for v in out.values())
        logger.info("Loaded %d shapes from %d GeoJSON files into cache", total_shapes, len(out))
    except Exception:
        pass
    return _GEO_CACHE


def find_geo_by_keyword(keyword: str) -> Optional[List[Tuple[base.BaseGeometry, Dict]]]:
    """Find a loaded geo by a keyword match on filename stem (case-insensitive).

    Example: keyword 'sfra' will match 'SFRA.geojson'.
    """
    allg = load_all_geojson()
    k = keyword.lower()
    matched: List[Tuple[base.BaseGeometry, Dict]] = []
    for name, shapes in allg.items():
        if k in name:
            matched.extend(shapes)
    return matched if matched else None


def point_from_aircraft(item: dict) -> Optional[Point]:
    """Create a Shapely Point from a VATSIM aircraft/pilot dict.

    Tries a few common key names for latitude/longitude.
    """
    lat = item.get("latitude") or item.get("lat") or item.get("y")
    lon = item.get("longitude") or item.get("lon") or item.get("x")
    try:
        if lat is None or lon is None:
            return None
        return Point(float(lon), float(lat))
    except Exception:
        return None
 