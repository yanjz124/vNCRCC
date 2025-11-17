import sys
from datetime import datetime

# Intrusion time from the API
intrusion_ts_est = "11/17/2025 04:19:59"  # This was displayed as EST
intrusion_dt = datetime.strptime(intrusion_ts_est, "%m/%d/%Y %H:%M:%S")
intrusion_unix = intrusion_dt.timestamp()

print(f"Intrusion time (EST): {intrusion_ts_est}")
print(f"Intrusion timestamp (Unix): {intrusion_unix}")

# Service restart time
restart_dt = datetime.strptime("2025-11-17 01:21:34", "%Y-%m-%d %H:%M:%S")
restart_unix = restart_dt.timestamp()
print(f"\nService restart: {restart_dt}")
print(f"Restart timestamp: {restart_unix}")

# Check database for positions after restart
sys.path.insert(0, "/home/JY/vNCRCC/src")
from vncrcc.storage import STORAGE

print(f"\nChecking positions for CID 1421245 after restart ({restart_dt}):")
rows = STORAGE.conn.execute('''
    SELECT timestamp, latitude, longitude, altitude, groundspeed, callsign
    FROM aircraft_positions 
    WHERE cid=1421245 
    AND timestamp > ?
    ORDER BY timestamp
''', (restart_unix,)).fetchall()

if rows:
    print(f"Found {len(rows)} positions after restart:")
    for row in rows:
        ts = datetime.fromtimestamp(row[0])
        print(f'  {ts} ({row[0]}) - {row[5]} - Lat: {row[1]:.4f}, Lon: {row[2]:.4f}, Alt: {row[3]}, GS: {row[4]}')
else:
    print("No positions found after restart")

# Check if intrusion was before or after restart
if intrusion_unix > restart_unix:
    print(f"\nIntrusion occurred {(intrusion_unix - restart_unix) / 3600:.1f} hours AFTER restart")
else:
    print(f"\nIntrusion occurred {(restart_unix - intrusion_unix) / 3600:.1f} hours BEFORE restart")

# Check what positions would be found with the 120-second lookback
lookback_ts = intrusion_unix - 120
print(f"\nLooking for positions between {datetime.fromtimestamp(lookback_ts)} and {datetime.fromtimestamp(intrusion_unix)}:")
rows = STORAGE.conn.execute('''
    SELECT timestamp, latitude, longitude, altitude
    FROM aircraft_positions 
    WHERE cid=1421245 
    AND timestamp BETWEEN ? AND ?
    ORDER BY timestamp
''', (lookback_ts, intrusion_unix)).fetchall()

if rows:
    print(f"Found {len(rows)} positions in lookback window:")
    for row in rows:
        ts = datetime.fromtimestamp(row[0])
        print(f'  {ts} - Lat: {row[1]:.4f}, Lon: {row[2]:.4f}, Alt: {row[3]}')
else:
    print("No positions in lookback window")
