import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from shapely.geometry import shape, Point, mapping, base
import logging

logger = logging.getLogger("vncrcc.geo.loader")

GEO_DIR = Path(__file__).parent


def _load_geojson(path: Path) -> List[Tuple[base.BaseGeometry, Dict]]:
    """Load a geojson file and return a list of (shapely_shape, properties)."""
    try:
        raw = json.loads(path.read_text())
    except Exception:
        return []
    features = raw.get("features") if isinstance(raw, dict) else None
    shapes: List[Tuple[base.BaseGeometry, Dict]] = []
    if features:
        for f in features:
            geom = f.get("geometry")
            props = f.get("properties") or {}
            if geom:
                try:
                    shp = shape(geom)
                    # Try to repair invalid geometries (self-intersections) using buffer(0)
                    if not getattr(shp, "is_valid", True):
                        try:
                            repaired = shp.buffer(0)
                            if getattr(repaired, "is_valid", False):
                                logger.warning("Repaired invalid geometry in %s using buffer(0)", path.name)
                                shp = repaired
                        except Exception:
                            logger.exception("Failed to repair geometry in %s", path.name)
                    shapes.append((shp, props))
                except Exception:
                    continue
    else:
        # maybe the file itself is a geometry object
        if isinstance(raw, dict) and raw.get("type") in ("Polygon", "MultiPolygon", "Point", "LineString"):
            try:
                shp = shape(raw)
                shapes.append((shp, {}))
            except Exception:
                pass
    return shapes


def load_all_geojson() -> Dict[str, List[Tuple[base.BaseGeometry, Dict]]]:
    """Load all .geojson and .json files in the geo directory.

    Returns a dict mapping filename stem -> list of (shape, properties).
    """
    out: Dict[str, List[Tuple[base.BaseGeometry, Dict]]] = {}
    for ext in ("*.geojson", "*.json"):
        for p in GEO_DIR.glob(ext):
            key = p.stem.lower()
            out[key] = _load_geojson(p)
    return out


def find_geo_by_keyword(keyword: str) -> Optional[List[Tuple[base.BaseGeometry, Dict]]]:
    """Find a loaded geo by a keyword match on filename stem (case-insensitive).

    Example: keyword 'sfra' will match 'SFRA.geojson'.
    """
    allg = load_all_geojson()
    k = keyword.lower()
    for name, shapes in allg.items():
        if k in name:
            return shapes
    return None


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
 