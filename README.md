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
# If you prefer to use the package import, run the app module we've added:
uvicorn vncrcc.app:app --host 0.0.0.0 --port 8000 --reload
```

Config
- Edit `config/example_config.yaml` or set `VNCRCC_CONFIG` to a custom YAML
  path. Keys: `vatsim_url`, `poll_interval`, `db_path`.

Notes
- The `VatsimDataFetcher` is a single shared poller — other modules should
  not fetch the JSON themselves. Register a callback with
  `FETCHER.register_callback(cb)` or read the latest snapshot from
  `STORAGE` in `src/vncrcc/storage.py`.

Development (Windows)
---------------------

This repository includes a helper script to set up a local development
environment on Windows and run either the API or the worker.

PowerShell helper (recommended):

1. Open PowerShell in the project root.
2. Run (first run will create a `.venv` and install requirements):

```powershell
.\dev-run.ps1 -Mode api -Port 8000
```

To run the poller/worker instead:

```powershell
.\dev-run.ps1 -Mode worker
```

Notes:
- The script creates/uses `.venv` in the repository root.
- `PYTHONPATH` is set to include the `src` folder so you can run modules
  like `python -m src.vncrcc.worker` or start uvicorn the same way the
  README examples show.
- You can override the config path via the `VNCRCC_CONFIG` environment
  variable or by passing a different `-ConfigPath` to `dev-run.ps1`.

