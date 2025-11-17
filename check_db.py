import os
import sys
from datetime import datetime

# Check database URL
db_url = os.environ.get("VNCRCC_DATABASE_URL", "sqlite:///vncrcc.db")
print(f"Database URL: {db_url}")

# Try to initialize storage and check tables
sys.path.insert(0, "/home/JY/vNCRCC/src")
from vncrcc.storage import STORAGE

print(f"\nUsing {'SQLAlchemy' if hasattr(STORAGE, 'engine') else 'fallback sqlite'} storage")
print(f"Database path: {STORAGE.db_path if hasattr(STORAGE, 'db_path') else 'N/A'}")

# Check positions using the STORAGE methods
total_positions = STORAGE.conn.execute('SELECT COUNT(*) FROM aircraft_positions').fetchone()[0]
print(f"\nTotal positions in database: {total_positions}")

# Check N1615A positions
n1615a_count = STORAGE.conn.execute('SELECT COUNT(*) FROM aircraft_positions WHERE cid=1421245').fetchone()[0]
print(f"N1615A (CID 1421245) positions: {n1615a_count}")

if n1615a_count > 0:
    print('\nRecent N1615A positions:')
    rows = STORAGE.conn.execute('''
        SELECT timestamp, latitude, longitude, altitude, groundspeed, heading
        FROM aircraft_positions 
        WHERE cid=1421245 
        ORDER BY timestamp DESC 
        LIMIT 20
    ''').fetchall()
    
    for row in rows:
        ts = datetime.fromtimestamp(row[0])
        print(f'  {ts} - Lat: {row[1]:.4f}, Lon: {row[2]:.4f}, Alt: {row[3]}, GS: {row[4]}, Hdg: {row[5]}')
    
    # Check if positions exist around intrusion time (04:19:59 EST = 1763359199 UTC... wait, need to check timezone)
    # Let's just look for any positions in the last hour
    recent_ts = datetime.now().timestamp() - 3600
    print(f'\nPositions in last hour for N1615A:')
    rows = STORAGE.conn.execute('''
        SELECT timestamp, latitude, longitude, altitude
        FROM aircraft_positions 
        WHERE cid=1421245 
        AND timestamp > ?
        ORDER BY timestamp
    ''', (recent_ts,)).fetchall()
    
    if rows:
        for row in rows:
            ts = datetime.fromtimestamp(row[0])
            print(f'  {ts} - Lat: {row[1]:.4f}, Lon: {row[2]:.4f}, Alt: {row[3]}')
    else:
        print('  (no positions in last hour)')
else:
    print('\nNo positions found for N1615A. Checking recent positions from any aircraft:')
    rows = STORAGE.conn.execute('''
        SELECT cid, callsign, COUNT(*) as count, MAX(timestamp) as last_seen
        FROM aircraft_positions
        GROUP BY cid
        ORDER BY last_seen DESC
        LIMIT 10
    ''').fetchall()
    
    for row in rows:
        ts = datetime.fromtimestamp(row[3])
        print(f'  CID {row[0]} ({row[1]}): {row[2]} positions, last seen {ts}')
