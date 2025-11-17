import json
from datetime import datetime

with open("/home/JY/vNCRCC/data/p56_history.json") as f:
    data = json.load(f)

events = [e for e in data.get("events", []) if e.get("cid") == 1421245]
print(f"Found {len(events)} events for CID 1421245")

if events:
    for i, event in enumerate(events[:3]):
        print(f"\nEvent {i+1}:")
        print(f"  Full event keys: {list(event.keys())}")
        print(f"  Callsign: {event.get('callsign')}")
        print(f"  Name: {event.get('name')}")
        
        # Check all possible timestamp fields
        for ts_field in ['detected_at', 'recorded_at', 'latest_ts']:
            if ts_field in event and event[ts_field]:
                dt = datetime.fromtimestamp(event[ts_field])
                print(f"  {ts_field}: {event[ts_field]} = {dt}")
        
        print(f"  Pre-positions: {len(event.get('pre_positions', []))}")
        print(f"  Post-positions: {len(event.get('post_positions', []))}")
        
        # Check position fields
        if 'latest_position' in event:
            print(f"  Latest position: {event['latest_position']}")
        else:
            print(f"  Lat: {event.get('lat')}, Lon: {event.get('lon')}, Alt: {event.get('altitude')}")
