import sys
from datetime import datetime

sys.path.insert(0, "/home/JY/vNCRCC/src")
from vncrcc.storage import STORAGE

# Check recent P56 events for CID 1340265
import json
with open("/home/JY/vNCRCC/data/p56_history.json") as f:
    data = json.load(f)

events = [e for e in data.get("events", []) if e.get("cid") == 1340265]
print(f"Found {len(events)} P56 events for CID 1340265 (Junzhe Yan)")

# Show most recent ones
restart_ts = datetime.strptime("2025-11-17 01:21:34", "%Y-%m-%d %H:%M:%S").timestamp()
recent_events = [e for e in events if e.get('recorded_at', 0) > restart_ts]

print(f"\nEvents since restart ({datetime.fromtimestamp(restart_ts)}):")
print(f"Found {len(recent_events)} events")

for i, event in enumerate(recent_events[:3]):
    recorded_dt = datetime.fromtimestamp(event['recorded_at']) if 'recorded_at' in event else None
    latest_dt = datetime.fromtimestamp(event['latest_ts']) if 'latest_ts' in event else None
    
    print(f"\nEvent {i+1}:")
    print(f"  Callsign: {event.get('callsign')}")
    print(f"  Recorded at: {recorded_dt}")
    print(f"  Latest timestamp: {latest_dt}")
    print(f"  Pre-positions: {len(event.get('pre_positions', []))}")
    print(f"  Post-positions: {len(event.get('post_positions', []))}")
    if event.get('latest_position'):
        print(f"  Latest position: Lat {event['latest_position']['lat']:.4f}, Lon {event['latest_position']['lon']:.4f}")

# Now check what positions exist in the database for this CID around the intrusion time
if recent_events:
    latest_event = recent_events[0]
    event_ts = latest_event.get('latest_ts', latest_event.get('recorded_at'))
    
    print(f"\n\nChecking database positions around intrusion time ({datetime.fromtimestamp(event_ts)}):")
    
    # Look 120 seconds before the event
    lookback_ts = event_ts - 120
    
    rows = STORAGE.conn.execute('''
        SELECT timestamp, latitude, longitude, altitude, groundspeed
        FROM aircraft_positions 
        WHERE cid = ? AND timestamp BETWEEN ? AND ?
        ORDER BY timestamp ASC
    ''', (1340265, lookback_ts, event_ts + 60)).fetchall()
    
    print(f"Found {len(rows)} positions in database (from {datetime.fromtimestamp(lookback_ts)} to {datetime.fromtimestamp(event_ts + 60)}):")
    for row in rows:
        dt = datetime.fromtimestamp(row[0])
        print(f"  {dt}: Lat {row[1]:.4f}, Lon {row[2]:.4f}, Alt {row[3]}, GS {row[4]}")
