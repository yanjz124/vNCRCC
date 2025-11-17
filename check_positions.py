import sqlite3
import sys
from datetime import datetime

conn = sqlite3.connect('data/vncrcc.db')

# Check total positions
total = conn.execute('SELECT COUNT(*) FROM aircraft_positions').fetchone()[0]
print(f'Total positions in database: {total}')

# Check N1615A positions
n1615a_count = conn.execute('SELECT COUNT(*) FROM aircraft_positions WHERE cid=1421245').fetchone()[0]
print(f'N1615A (CID 1421245) positions: {n1615a_count}')

# Check recent positions for N1615A
print('\nRecent N1615A positions:')
rows = conn.execute('''
    SELECT timestamp, latitude, longitude, altitude, ground_speed, heading
    FROM aircraft_positions 
    WHERE cid=1421245 
    ORDER BY timestamp DESC 
    LIMIT 20
''').fetchall()

for row in rows:
    ts = datetime.fromtimestamp(row[0])
    print(f'  {ts} - Lat: {row[1]:.4f}, Lon: {row[2]:.4f}, Alt: {row[3]}, GS: {row[4]}, Hdg: {row[5]}')

# Check if positions exist around intrusion time (04:19:59 = 1763359199)
intrusion_ts = 1763359199
print(f'\nPositions around intrusion time ({datetime.fromtimestamp(intrusion_ts)}):')
rows = conn.execute('''
    SELECT timestamp, latitude, longitude, altitude
    FROM aircraft_positions 
    WHERE cid=1421245 
    AND timestamp BETWEEN ? AND ?
    ORDER BY timestamp
''', (intrusion_ts - 120, intrusion_ts + 60)).fetchall()

for row in rows:
    ts = datetime.fromtimestamp(row[0])
    print(f'  {ts} - Lat: {row[1]:.4f}, Lon: {row[2]:.4f}, Alt: {row[3]}')

conn.close()
