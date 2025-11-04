"""Generate a simple Leaflet HTML map showing the FRZ, SFRA, and P56 polygons and aircraft from latest snapshot.

Produces: frz_map.html in the repository root.

Usage:
    python tools/generate_frz_map.py

This script uses the project's package (vncrcc) so run it with PYTHONPATH set to src or from the project venv.
"""
import json
from pathlib import Path
from datetime import datetime

OUT = Path("dc_restricted_areas_map.html")
ROOT = Path(__file__).parent.parent

# Import project modules
import sys
sys.path.insert(0, str(ROOT / "src"))

from vncrcc.geo.loader import find_geo_by_keyword
from vncrcc import storage as storage_mod
from vncrcc.geo.loader import point_from_aircraft

from shapely.geometry import mapping


def load_data():
    # Load FRZ
    frz_shapes = find_geo_by_keyword("frz")
    frz_feature = None
    if frz_shapes:
        shp, props = frz_shapes[0]
        frz_feature = {"type": "Feature", "properties": props or {}, "geometry": mapping(shp)}
    
    # Load SFRA
    sfra_shapes = find_geo_by_keyword("sfra")
    sfra_feature = None
    if sfra_shapes:
        shp, props = sfra_shapes[0]
        sfra_feature = {"type": "Feature", "properties": props or {}, "geometry": mapping(shp)}
    
    # Load P56 - all features (P56A and P56B)
    p56_shapes = find_geo_by_keyword("p56")
    p56_features = []
    if p56_shapes:
        for shp, props in p56_shapes:
            p56_features.append({"type": "Feature", "properties": props or {}, "geometry": mapping(shp)})

    STORAGE = storage_mod.STORAGE
    if not STORAGE:
        raise SystemExit("No STORAGE available")
    snap = STORAGE.get_latest_snapshot()
    if not snap:
        raise SystemExit("No snapshot available in DB")
    aircraft = (snap.get("data") or {}).get("pilots") or (snap.get("data") or {}).get("aircraft") or []

    pts = []
    for a in aircraft:
        pt = point_from_aircraft(a)
        if not pt:
            continue
        # compute distance to FRZ geometry (for color coding)
        dist = None
        if frz_shapes:
            try:
                dist = pt.distance(frz_shapes[0][0])
            except Exception:
                pass
        callsign = a.get("callsign") or a.get("call_sign") or a.get("cid")
        pts.append({
            "type": "Feature",
            "properties": {"callsign": callsign, "alt": a.get("altitude") or a.get("alt"), "raw": a, "dist": dist},
            "geometry": {"type": "Point", "coordinates": [pt.x, pt.y]},
        })

    return frz_feature, sfra_feature, p56_features, pts, snap.get("fetched_at")


HTML_TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>DC Restricted Areas Map</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <style> #map { height: 100vh; } </style>
</head>
<body>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const frz = __FRZ__;
const sfra = __SFRA__;
const p56 = __P56__;
const aircraft = __AC__;

const map = L.map('map').setView([39.0, -77.0], 9);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(map);

// Add layer control
const overlays = {};

// Style functions for different areas
function styleFRZ(feature) { return { color: '#ff7800', weight: 3, fillOpacity: 0.1 }; }
function styleSFRA(feature) { return { color: '#ff0000', weight: 2, fillOpacity: 0.1 }; }
function styleP56(feature) { return { color: '#0000ff', weight: 2, fillOpacity: 0.1 }; }

// Add polygons if they exist
if (frz && frz.features && frz.features.length > 0) {
    const frzLayer = L.geoJSON(frz, { style: styleFRZ });
    frzLayer.addTo(map);
    overlays["FRZ (Flight Restricted Zone)"] = frzLayer;
}

if (sfra && sfra.features && sfra.features.length > 0) {
    const sfraLayer = L.geoJSON(sfra, { style: styleSFRA });
    sfraLayer.addTo(map);
    overlays["SFRA (Special Flight Rules Area)"] = sfraLayer;
}

if (p56 && p56.features && p56.features.length > 0) {
    const p56Layer = L.geoJSON(p56, { style: styleP56 });
    p56Layer.addTo(map);
    overlays["P56 (Prohibited Area)"] = p56Layer;
}

// Add layer control
L.control.layers(null, overlays).addTo(map);

function pointToLayer(feature, latlng) {
    const dist = feature.properties.dist;
    // classify: inside (dist==0 or undefined but intersects) -> red, near (<0.01) -> orange, far -> blue
    let color = 'blue';
    if (dist === 0 || dist === null) color = 'red';
    else if (dist <= 0.001) color = 'orange';
    else if (dist <= 0.01) color = 'yellow';
    const marker = L.circleMarker(latlng, { radius: 6, fillColor: color, color: '#000', weight:1, fillOpacity: 0.9 });
    return marker;
}

function onEachFeature(feature, layer) {
    if (!feature.properties) return;
    const p = feature.properties;
    let html = '';
    if (p.callsign) html += '<b>' + p.callsign + '</b><br/>';
    if (p.alt !== undefined) html += 'alt: ' + p.alt + '<br/>';
    if (p.dist !== null) html += 'dist to FRZ: ' + (Math.round(p.dist*1000000)/1000000) + '°<br/>';
    layer.bindPopup(html);
}

L.geoJSON(aircraft, { pointToLayer: pointToLayer, onEachFeature: onEachFeature }).addTo(map);

</script>
</body>
</html>
"""


def main():
    frz_feature, sfra_feature, p56_features, aircraft_pts, fetched_at = load_data()
    
    # Create GeoJSON FeatureCollections, handling None values
    frz_json = json.dumps({"type": "FeatureCollection", "features": [frz_feature] if frz_feature else []})
    sfra_json = json.dumps({"type": "FeatureCollection", "features": [sfra_feature] if sfra_feature else []})
    p56_json = json.dumps({"type": "FeatureCollection", "features": p56_features})
    aircraft_json = json.dumps({"type": "FeatureCollection", "features": aircraft_pts})
    
    # substitute placeholders
    html = HTML_TEMPLATE.replace('__FRZ__', frz_json).replace('__SFRA__', sfra_json).replace('__P56__', p56_json).replace('__AC__', aircraft_json)
    OUT.write_text(html, encoding='utf-8')
    print('Wrote', OUT.resolve())


if __name__ == '__main__':
    main()
