import time, json, asyncio
from vncrcc import storage
from vncrcc.api.v1 import sfra as sfra_mod

# Ensure STORAGE is initialized
if storage.STORAGE is None:
    from vncrcc.storage import Storage
    storage.STORAGE = Storage()

# Build synthetic snapshot: one aircraft inside SFRA (lon -77.02, lat 38.9, alt 15000)
snapshot = {
    "general": {"version":3, "update_timestamp":"2025-11-04T02:29:46.998817Z"},
    "pilots": [
        {
            "cid": 999999,
            "name": "Test Pilot Inside",
            "callsign": "TEST1",
            "latitude": 38.9,
            "longitude": -77.02,
            "altitude": 15000,
            "last_updated": "2025-11-04T02:29:46.000Z"
        },
        {
            "cid": 888888,
            "name": "High Pilot",
            "callsign": "HIGH1",
            "latitude": 38.9,
            "longitude": -77.02,
            "altitude": 30000,
            "last_updated": "2025-11-04T02:29:46.000Z"
        },
        {
            "cid": 777777,
            "name": "Outside Pilot",
            "callsign": "OUT1",
            "latitude": 40.0,
            "longitude": -78.0,
            "altitude": 12000,
            "last_updated": "2025-11-04T02:29:46.000Z"
        }
    ]
}

# Save snapshot to DB
ts = time.time()
print('Saving synthetic snapshot to DB...')
storage.STORAGE.save_snapshot(snapshot, ts)

# Call the SFRA endpoint function (pass the name string since the endpoint
# uses FastAPI's Query default which isn't callable directly)
print('Calling sfra_aircraft()...')
res = asyncio.run(sfra_mod.sfra_aircraft(name="sfra"))
print('Result:')
print(json.dumps(res, indent=2))
