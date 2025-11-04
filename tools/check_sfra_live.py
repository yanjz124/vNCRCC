"""Simple live SFRA checker.

Fetches the VATSIM v3 JSON feed and filters pilots inside the SFRA geojson
(found in `src/vncrcc/geo/`) and below a configurable altitude (default
18,000 ft). Prints matching aircraft.

Usage:
    python tools/check_sfra_live.py [--url URL] [--name sfra] [--max-alt 18000]
"""
import argparse
import json
import sys
from urllib.request import urlopen
from urllib.error import URLError, HTTPError
from typing import Any, Dict, List

from vncrcc.geo.loader import find_geo_by_keyword, point_from_aircraft

DEFAULT_URL = "https://data.vatsim.net/v3/vatsim-data.json"


def fetch_vatsim(url: str) -> Dict[str, Any]:
    try:
        with urlopen(url, timeout=15) as resp:
            return json.load(resp)
    except HTTPError as e:
        print(f"HTTP error fetching {url}: {e}", file=sys.stderr)
        raise
    except URLError as e:
        print(f"URL error fetching {url}: {e}", file=sys.stderr)
        raise


def filter_sfra(data: Dict[str, Any], geo_name: str = "sfra", max_alt: float = 18000) -> List[Dict[str, Any]]:
    shapes = find_geo_by_keyword(geo_name)
    if not shapes:
        raise RuntimeError(f"No geo named like '{geo_name}' found in geo directory")

    pilots = data.get("pilots") or data.get("aircraft") or []
    matches: List[Dict[str, Any]] = []
    for p in pilots:
        pt = point_from_aircraft(p)
        if not pt:
            continue
        alt = p.get("altitude") or p.get("alt")
        try:
            alt_val = float(alt) if alt is not None else None
        except Exception:
            alt_val = None
        if alt_val is None or alt_val > max_alt:
            continue
        for shp, props in shapes:
            if shp.contains(pt):
                matches.append({"pilot": p, "matched_props": props})
                break
    return matches


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL, help="VATSIM JSON URL")
    parser.add_argument("--name", default="sfra", help="Keyword to find geo file (default 'sfra')")
    parser.add_argument("--max-alt", default=18000, type=float, help="Maximum altitude in feet to include")
    args = parser.parse_args(argv)

    print(f"Fetching VATSIM data from {args.url} ...")
    data = fetch_vatsim(args.url)
    print("Filtering SFRA ...")
    try:
        matches = filter_sfra(data, geo_name=args.name, max_alt=args.max_alt)
    except Exception as e:
        print("Error:", e, file=sys.stderr)
        return 2

    print(f"Found {len(matches)} matching aircraft (max_alt={args.max_alt})")
    if matches:
        print(json.dumps(matches, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
