import sys
from datetime import datetime
import time

sys.path.insert(0, "/home/JY/vNCRCC/src")
from vncrcc.storage import STORAGE

# Check current time
now = time.time()
print(f"Current Unix timestamp: {now}")
print(f"Current time (local): {datetime.fromtimestamp(now)}")
print(f"Current time (UTC): {datetime.utcfromtimestamp(now)}")

# Check incidents table for CID 1421245
print("\nIncidents for CID 1421245:")
rows = STORAGE.conn.execute('''
    SELECT id, detected_at, callsign, cid, name, lat, lon, altitude, zone
    FROM incidents
    WHERE cid=1421245
    ORDER BY detected_at DESC
    LIMIT 5
''').fetchall()

if rows:
    for row in rows:
        incident_id, detected_at, callsign, cid, name, lat, lon, alt, zone = row
        dt_local = datetime.fromtimestamp(detected_at)
        dt_utc = datetime.utcfromtimestamp(detected_at)
        time_diff = (now - detected_at) / 60  # minutes ago
        print(f"  ID {incident_id}: {callsign} at {dt_local} (UTC: {dt_utc})")
        print(f"    {time_diff:.1f} minutes ago, Zone: {zone}, Alt: {alt}")
        print(f"    Lat: {lat:.4f}, Lon: {lon:.4f}")
else:
    print("  No incidents found")
