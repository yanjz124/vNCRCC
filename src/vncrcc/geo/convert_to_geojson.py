"""Simple converter to normalize the provided FAA NOTAM XML and Prohibited Areas GeoJSON
into per-zone GeoJSON files (SFRA, FRZ, P-56) and a combined GeoJSON for DC restricted areas.

Run from the repository root with PYTHONPATH pointing to src, e.g.:

$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m vncrcc.geo.convert_to_geojson

The script is intentionally small and dependency-light. It requires `shapely` which is
already in `requirements.txt`.
"""
from pathlib import Path
import json
import xml.etree.ElementTree as ET
from typing import List, Tuple, Optional
from math import sin, cos, radians

from shapely.geometry import Polygon, mapping, MultiPolygon

GEO_DIR = Path(__file__).parent
PROHIBITED = GEO_DIR / "Prohibited_Areas.geojson"
SFRA_XML = GEO_DIR / "detail_4_9433.xml"
FRZ_XML = GEO_DIR / "detail_4_2565.xml"

OUT_P56 = GEO_DIR / "p56.geojson"
OUT_SFRA = GEO_DIR / "sfra.geojson"
OUT_FRZ = GEO_DIR / "frz.geojson"
OUT_COMBINED = GEO_DIR / "dc_restricted_areas.geojson"


def parse_decimal_with_cardinal(s: str) -> Optional[float]:
    """Parse strings like 38.35990574N or 077.03638889W into signed floats (lon/lat).

    Returns None if parsing fails.
    """
    if not s:
        return None
    s = s.strip()
    cardinal = s[-1].upper()
    if cardinal in ("N", "S", "E", "W"):
        try:
            val = float(s[:-1])
        except Exception:
            return None
        if cardinal in ("S", "W"):
            val = -val
        return val
    # fallback: try plain float
    try:
        return float(s)
    except Exception:
        return None


def parse_notam_xml(path: Path) -> List[Tuple[float, float]]:
    """Extract sequence of (lon, lat) points from the NOTAM XML Avx elements.

    Looks for Avx elements under abdMergedArea and aseShapes and returns a list
    of coordinates in lon, lat order.
    """
    if not path.exists():
        return []
    tree = ET.parse(str(path))
    root = tree.getroot()
    ns = {}  # default namespace not expected in these files
    coords: List[Tuple[float, float]] = []
    # find all Avx elements anywhere under the document
    for avx in root.findall('.//Avx', ns):
        lat_el = avx.find('geoLat')
        lon_el = avx.find('geoLong')
        if lat_el is None or lon_el is None:
            continue
        lat = parse_decimal_with_cardinal(lat_el.text)
        lon = parse_decimal_with_cardinal(lon_el.text)
        if lat is None or lon is None:
            continue
        coords.append((lon, lat))
    return coords


def extract_p56_from_geojson(path: Path) -> List[Polygon]:
    """Find features named P-56 in the Prohibited_Areas.geojson and return polygons."""
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    feats = raw.get('features', [])
    out: List[Polygon] = []
    for f in feats:
        props = f.get('properties') or {}
        name = props.get('NAME') or props.get('Name') or props.get('name')
        if not name:
            continue
        if str(name).strip().upper().startswith('P-56') or str(name).strip().upper() == 'P-56':
            geom = f.get('geometry')
            if not geom:
                continue
            try:
                poly = Polygon(geom.get('coordinates')[0]) if geom.get('type') == 'Polygon' else None
                if poly is None:
                    # support MultiPolygon
                    if geom.get('type') == 'MultiPolygon':
                        coords = geom.get('coordinates')
                        polys = [Polygon(p[0]) for p in coords if p]
                        out.extend(polys)
                    continue
                out.append(poly)
            except Exception:
                continue
    return out


def circle_coords(center_lon: float, center_lat: float, radius_nm: float, num_points: int = 128) -> List[Tuple[float, float]]:
    """Approximate a circle (in lon/lat) by sampling points around center.

    Uses a simple equirectangular approximation: 1 degree lat ~= 60 NM; lon scale reduced by cos(lat).
    This is plenty accurate for the SFRA 30 NM circle.
    """
    pts: List[Tuple[float, float]] = []
    lat_rad = radians(center_lat)
    lat_factor = radius_nm / 60.0  # degrees latitude per NM
    lon_factor = radius_nm / (60.0 * cos(lat_rad)) if cos(lat_rad) != 0 else radius_nm / 60.0
    for i in range(num_points):
        theta = 2.0 * 3.141592653589793 * float(i) / float(num_points)
        dy = lat_factor * sin(theta)
        dx = lon_factor * cos(theta)
        pts.append((center_lon + dx, center_lat + dy))
    # ensure closed
    if pts and pts[0] != pts[-1]:
        pts.append(pts[0])
    return pts


def build_and_write_geojson(features: List[dict], out_path: Path) -> None:
    fc = {"type": "FeatureCollection", "features": features}
    out_path.write_text(json.dumps(fc, indent=2))
    print(f"Wrote {out_path}")


def main() -> None:
    p56_polys = extract_p56_from_geojson(PROHIBITED)

    sfra_pts = parse_notam_xml(SFRA_XML)
    frz_pts = parse_notam_xml(FRZ_XML)

    features = []
    # P-56
    if p56_polys:
        p56_feats = []
        for poly in p56_polys:
            feat = {"type": "Feature", "properties": {"name": "P-56"}, "geometry": mapping(poly)}
            p56_feats.append(feat)
            features.append(feat)
        build_and_write_geojson(p56_feats, OUT_P56)
    else:
        print("No P-56 found in Prohibited_Areas.geojson")

    # SFRA
    if sfra_pts:
        try:
            poly = Polygon(sfra_pts)
            feat = {"type": "Feature", "properties": {"name": "SFRA", "source": SFRA_XML.name}, "geometry": mapping(poly)}
            build_and_write_geojson([feat], OUT_SFRA)
            features.append(feat)
        except Exception as e:
            print("Failed to build SFRA polygon:", e)
    else:
        print("No coordinates found in SFRA XML")

    # FRZ
    if frz_pts:
        try:
            poly = Polygon(frz_pts)
            feat = {"type": "Feature", "properties": {"name": "FRZ", "source": FRZ_XML.name}, "geometry": mapping(poly)}
            build_and_write_geojson([feat], OUT_FRZ)
            features.append(feat)
        except Exception as e:
            print("Failed to build FRZ polygon:", e)
    else:
        print("No coordinates found in FRZ XML")

    # Combined
    if features:
        build_and_write_geojson(features, OUT_COMBINED)
    else:
        print("No features to write for combined file")


if __name__ == '__main__':
    main()
