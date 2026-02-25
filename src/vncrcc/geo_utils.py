"""Shared geospatial utility functions.

Centralizes DCA coordinates, haversine distance, and radial/range calculations
that were previously duplicated across precompute.py, sfra.py, frz.py,
aircraft.py, and dashboard.py.
"""
import math

# DCA bullseye (lat, lon)
DCA_LAT = 38.8514403
DCA_LON = -77.0377214


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in nautical miles between two coordinates."""
    R = 6371.0  # Earth radius in km

    lat1_r = math.radians(lat1)
    lon1_r = math.radians(lon1)
    lat2_r = math.radians(lat2)
    lon2_r = math.radians(lon2)

    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1 - a)))

    km = R * c
    return km / 1.852


def dca_radial_range(lat: float, lon: float) -> dict:
    """Return bearing (degrees) and distance (nautical miles) from DCA to (lat, lon).

    Also return a compact string like 'DCA280010' (bearing 280 deg, range 10 nm).
    """
    lat1 = math.radians(DCA_LAT)
    lon1 = math.radians(DCA_LON)
    lat2 = math.radians(lat)
    lon2 = math.radians(lon)

    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    brng = math.degrees(math.atan2(x, y))
    brng = (brng + 360) % 360

    dist_nm = haversine_nm(DCA_LAT, DCA_LON, lat, lon)

    brng_i = int(round(brng)) % 360
    dist_i = int(round(dist_nm))
    compact = f"DCA{brng_i:03d}{dist_i:03d}"
    return {"radial_range": compact, "bearing": brng_i, "range_nm": round(dist_nm, 1)}
