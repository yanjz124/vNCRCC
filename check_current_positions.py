import sys
from datetime import datetime

sys.path.insert(0, "/home/JY/vNCRCC/src")
from vncrcc.storage import STORAGE

restart_ts = datetime.strptime("2025-11-17 01:21:34", "%Y-%m-%d %H:%M:%S").timestamp()

# Check for both CIDs (current N1615A is 1340265, old one was 1421245)
for cid in [1340265, 1421245]:
    rows = STORAGE.conn.execute('''
        SELECT timestamp, latitude, longitude, callsign
        FROM aircraft_positions 
        WHERE cid = ? AND timestamp > ?
        ORDER BY timestamp DESC 
        LIMIT 10
    ''', (cid, restart_ts)).fetchall()
    
    print(f"\nCID {cid}: {len(rows)} positions since restart")
    for row in rows:
        dt = datetime.fromtimestamp(row[0])
        print(f"  {dt} ({row[3]}): Lat {row[1]:.4f}, Lon {row[2]:.4f}")
