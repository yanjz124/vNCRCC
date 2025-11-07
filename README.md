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

Run locally — quick reference
-----------------------------

These steps give a concise recipe to run the API and worker locally on either
Windows (PowerShell) or Unix-like systems (macOS / Linux). Use whichever set of
commands matches the machine you'll run on.

PowerShell (Windows)

1. Open PowerShell in the repository root.
2. Create and activate the virtual environment (the helper script does this for you, but here are the manual steps if you want them):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3. Run the API (recommended helper):

```powershell
.\dev-run.ps1 -Mode api -Port 8000
```

4. Or run the worker (polls VATSIM and stores snapshots):

```powershell
.\dev-run.ps1 -Mode worker
```

5. Open the dashboard in a browser:

Point your browser to http://localhost:8000/ (or the port you chose) to open the SPA and API docs.

Unix / macOS (bash)

1. From the project root:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# Run the API
uvicorn vncrcc.app:app --host 0.0.0.0 --port 8000 --reload
# Or run the worker
python -m src.vncrcc.worker
```

Notes & tips
- The project uses `config/example_config.yaml` by default. To use a different config file, set the `VNCRCC_CONFIG` environment variable to the YAML path before starting the API or worker.
- If you use the PowerShell helper (`dev-run.ps1`) it creates/uses a local `.venv` and sets `PYTHONPATH` to include `src` so module imports resolve.
- To run tests locally: `pytest -q` from the repository root (activate the virtualenv first).
- If the SPA shows stale assets after an update, do a hard refresh (Ctrl+F5) or open DevTools → Network → Disable cache before reloading.

Local raster elevation data
---------------------------

If you have the `rasters_COP30.tar` archive included under `src/vncrcc/geo/` the API can sample elevations from the contained GeoTIFF(s) locally instead of calling the remote Open-Meteo elevation API. This is optional and uses `rasterio` when available.

To enable local raster sampling:

1. Install rasterio in your environment (note: rasterio requires GDAL and may need system packages):

```powershell
# Windows (using pip; make sure GDAL is available on the system)
pip install rasterio
```

2. Ensure `src/vncrcc/geo/rasters_COP30.tar` is present. On first import the server will extract the archive into `src/vncrcc/geo/rasters/` and attempt to open the first TIFF file it finds.

3. The elevation endpoint will prefer local raster values when available and fall back to the remote service when not.

If you prefer not to install rasterio, no action is needed — the API continues to use the remote elevation provider as before.


