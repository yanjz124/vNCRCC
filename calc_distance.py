import math

def haversine_nm(lat1, lon1, lat2, lon2):
    """Calculate distance in nautical miles using haversine formula."""
    R_km = 6371.0
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    
    a = math.sin((lat2_rad - lat1_rad) / 2.0) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1 - a)))
    dist_km = R_km * c
    dist_nm = dist_km / 1.852
    return dist_nm

# DCA coordinates
DCA_LAT = 38.8514403
DCA_LON = -77.0377214

# N1615A current position
N1615A_LAT = 38.82175
N1615A_LON = -76.93989

distance = haversine_nm(DCA_LAT, DCA_LON, N1615A_LAT, N1615A_LON)
print(f"Distance from DCA to N1615A: {distance:.2f} nm")

# P56 center (approximate)
P56_LAT = 38.895
P56_LON = -77.04

distance_to_p56 = haversine_nm(DCA_LAT, DCA_LON, P56_LAT, P56_LON)
print(f"Distance from DCA to P56 center: {distance_to_p56:.2f} nm")

# Is N1615A within 300nm?
if distance <= 300:
    print(f"\n✓ N1615A IS within 300nm range filter")
else:
    print(f"\n✗ N1615A is NOT within 300nm range filter")
