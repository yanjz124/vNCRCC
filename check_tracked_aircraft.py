import sys
from datetime import datetime

sys.path.insert(0, "/home/JY/vNCRCC/src")
from vncrcc.storage import STORAGE

# Get restart time
restart_dt = datetime.strptime("2025-11-17 01:21:34", "%Y-%m-%d %H:%M:%S")
restart_unix = restart_dt.timestamp()

# Check what aircraft HAVE been tracked since restart
print("Aircraft with positions since restart:")
rows = STORAGE.conn.execute('''
    SELECT cid, callsign, COUNT(*) as count, MIN(timestamp) as first_seen, MAX(timestamp) as last_seen
    FROM aircraft_positions
    WHERE timestamp > ?
    GROUP BY cid
    ORDER BY last_seen DESC
    LIMIT 20
''', (restart_unix,)).fetchall()

for row in rows:
    first_ts = datetime.fromtimestamp(row[3])
    last_ts = datetime.fromtimestamp(row[4])
    print(f"  CID {row[0]:7} ({row[1]:8}): {row[2]:3} positions, first: {first_ts}, last: {last_ts}")

print(f"\nTotal unique aircraft tracked since restart: {len(rows)}")

# Check the aircraft_history.json file to see if N1615A is there
import json
try:
    with open("/home/JY/vNCRCC/data/aircraft_history.json", "r") as f:
        history = json.load(f)
    
    print(f"\nAircraft in history JSON file: {len(history)}")
    if "1421245" in history:
        print(f"  N1615A (CID 1421245) is in history file with {len(history['1421245'])} positions")
        positions = history['1421245']
        for pos in positions[-5:]:  # Show last 5
            print(f"    Lat: {pos['lat']:.4f}, Lon: {pos['lon']:.4f}, Alt: {pos.get('alt')}")
    else:
        print(f"  N1615A (CID 1421245) is NOT in history file")
        print(f"  CIDs in history file: {list(history.keys())[:10]}")
except Exception as e:
    print(f"\nError reading history file: {e}")
