# vNCRCC — virtual National Capitol Region Command Center (prototype)

This small project polls the VATSIM data feed and records snapshots. It's
designed to run on a Raspberry Pi or a small VM and act as the backbone for
geofence/detection logic (SFRA/FRZ/P-56) and a small dashboard.

Quick start (virtualenv)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# Run the worker which polls VATSIM and saves snapshots to sqlite
python -m src.vncrcc.worker
```

Run the API (FastAPI + uvicorn)

```bash
uvicorn src.vncrcc.api:app --host 0.0.0.0 --port 8000
```

Config
- Edit `config/example_config.yaml` or set `VNCRCC_CONFIG` to a custom YAML
  path. Keys: `vatsim_url`, `poll_interval`, `db_path`.

Notes
- The `VatsimDataFetcher` is a single shared poller — other modules should
  not fetch the JSON themselves. Register a callback with
  `FETCHER.register_callback(cb)` or read the latest snapshot from
  `STORAGE` in `src/vncrcc/storage.py`.
