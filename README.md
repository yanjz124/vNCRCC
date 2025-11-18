# vNCRCC — virtual National Capitol Region Command Center

**Live Dashboard**: [vncrcc.org](https://vncrcc.org)

vNCRCC is a real-time flight tracking and airspace monitoring system for the National Capital Region (Washington, DC area) on the VATSIM network. It provides automated detection and logging of aircraft in restricted airspace zones (P-56, FRZ, SFRA) with a responsive web dashboard featuring live maps, position history tracking, and comprehensive flight data.

> **Note**: This project is primarily AI-assisted development, with most code generated and refined through AI collaboration.

## Key Features

- **Real-time Aircraft Tracking**: Live position updates every 15 seconds from VATSIM data feed
- **Automated P-56 Intrusion Detection**: Continuous background monitoring with line-crossing detection
- **Dual Interactive Maps**: Side-by-side P-56 and SFRA/FRZ visualization using Leaflet
- **Flight History Tracking**: Visual track overlays with up to 10 historical positions per aircraft
- **Comprehensive Airspace Zones**: P-56, FRZ (Flight Restricted Zone), SFRA (Special Flight Rules Area), VSO (Virtual Security Officer range)
- **P-56 Leaderboard**: Track intrusion counts and timestamps per pilot
- **Position History**: Pre/inside/post-intrusion position capture (5 before, unlimited inside capped at 100, 5 after exit)
- **Rate Limiting**: DDoS protection at both nginx and FastAPI levels (6 requests/minute)
- **Responsive Design**: Compact tables with auto-sizing columns and text wrapping
- **Flight Plan Integration**: Expandable flight plan details with route and remarks

## Technical Stack

- **Backend**: FastAPI, Python 3.8+, SQLite/PostgreSQL
- **Frontend**: Vanilla JavaScript, Leaflet.js for maps
- **Geospatial**: Shapely for polygon operations, GeoJSON for airspace boundaries
- **Deployment**: Systemd service, nginx reverse proxy
- **Rate Limiting**: SlowAPI (FastAPI) + nginx limit_req zones

This README explains how to run locally, deploy to a server, and what the
production runtime looks like (systemd, virtualenv, nginx).

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
# Development: run the FastAPI app with uvicorn
uvicorn vncrcc.app:app --host 0.0.0.0 --port 8000 --reload
```

Important: the app now mounts the `web/` directory at `/`, so the SPA
(`web/index.html`, `web/app.js`, `web/static/*`) is served from the same
process. API routes remain under `/api/...`.

Configuration
-------------
- Default config: `config/example_config.yaml`.
- Override by setting environment variable `VNCRCC_CONFIG=/path/to/config.yaml`.
  Keys commonly used: `vatsim_url`, `poll_interval`, `db_path`.

Local development helper (Windows PowerShell)
-------------------------------------------
Use the included PowerShell helper to create a virtualenv and run either the
API or the worker on Windows.

```powershell
# Run the API (creates/uses .venv and sets PYTHONPATH)
.\dev-run.ps1 -Mode api -Port 8000

# Run the worker
.\dev-run.ps1 -Mode worker
```

The helper will create `.venv` in the repo root and set `PYTHONPATH` to
include `src` so imports like `python -m src.vncrcc.worker` work.

Run locally — quick reference (Unix / macOS / Linux)
--------------------------------------------------
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# Run the API
uvicorn vncrcc.app:app --host 0.0.0.0 --port 8000 --reload
# Or run the worker
python -m src.vncrcc.worker
```

Deployment to Raspberry Pi (automatic helper)
--------------------------------------------
The repo includes `scripts/deploy.sh` which the Pi (or GitHub Actions) can
call to: pull the latest code, ensure a `venv` is present, install
requirements, and restart the systemd service `vncrcc.service`.

Recommended manual deploy steps on the Pi

```bash
ssh pi@<PI_HOST>
cd ~/vNCRCC
git fetch --all --prune
git reset --hard origin/main
# create/activate venv and install requirements
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
# restart the service that runs the app
sudo systemctl restart vncrcc.service

# quick checks
sudo systemctl status vncrcc.service --no-pager
sudo journalctl -u vncrcc.service -n 200 --no-pager
curl -I http://127.0.0.1:8000/        # expecting 200 and text/html
curl -I http://127.0.0.1:8000/app.js   # expecting 200 and javascript
```

GitHub Actions deploy
---------------------
This repo includes a workflow `.github/workflows/deploy.yml` that SSHes to
the Pi and runs `/home/<user>/vNCRCC/scripts/deploy.sh`. For it to succeed
you must configure the repository secrets:

- `PI_HOST` — Pi hostname/IP
- `PI_USER` — user on the Pi (e.g. `pi`)
- `DEPLOY_KEY` — private SSH key (PEM) whose public key is in
  `/home/<PI_USER>/.ssh/authorized_keys` on the Pi
- (optional) `PI_PORT` — SSH port (defaults to 22)

Common failure modes with Actions deploy
- `Permission denied` / SSH auth: ensure `DEPLOY_KEY` is the private key
  and the corresponding public key is installed in `authorized_keys`.
- `deploy.sh` not found or not executable: make sure the repo exists at
  `/home/<PI_USER>/vNCRCC` on the Pi and `scripts/deploy.sh` is executable.
- `deploy.sh` itself failing: check `~/vNCRCC/logs/vncrcc-deploy.log` on the
  Pi or run the script manually to see the error.

Systemd unit (what runs on the Pi)
---------------------------------
The Pi runs a systemd unit named `vncrcc.service` which starts uvicorn (the
FastAPI process) from the repo venv. Typical lifecycle:

- systemd starts the uvicorn process on boot
- uvicorn loads `vncrcc.app:app`, which mounts `web/` and registers the
  Vatsim fetcher

If you want a sample unit for comparison, a minimal example looks like:

```ini
[Unit]
Description=vNCRCC FastAPI service
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/vNCRCC
Environment="VNCRCC_CONFIG=/home/pi/vNCRCC/config/production.yaml"
ExecStart=/home/pi/vNCRCC/venv/bin/uvicorn vncrcc.app:app --host 127.0.0.1 --port 8000 --workers 3
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Adjust `ExecStart` flags (workers, bind address) as appropriate for your
hardware. If you're behind nginx or Cloudflare Tunnel, bind to 127.0.0.1 and
let the external proxy forward requests.

Cloudflare Tunnel / nginx notes
------------------------------
- The Pi historically uses `cloudflared` to expose the origin via a Cloudflare
  Tunnel. If you're using cloudflared, ensure the service is running and the
  tunnel is connected: `sudo systemctl status cloudflared` and
  `sudo journalctl -u cloudflared -f`.
- If the browser shows a JSON response at `/` or `Unexpected token '<'` for
  a JS file, check that the origin (curl 127.0.0.1:8000/) returns HTML and
  that nginx or the tunnel is forwarding to the correct backend port.

Troubleshooting checklist
-------------------------
- If Actions deploy fails: inspect the workflow logs to see whether SSH
  authentication failed or the remote script errored. Test SSH locally with
  the same key you configured in `DEPLOY_KEY`.
- If the web UI serves JSON or wrong content: `curl -i http://127.0.0.1:8000/app.js`
  should return the JavaScript file; if it returns HTML, your static mount
  or proxy mapping is wrong.
- If the app times out after hours: monitor `journalctl -u cloudflared` and
  system resources (`top`, `vmstat`) and consider increasing uvicorn
  workers, ulimits, or tuning the cloudflared receive buffer and nginx proxy
  timeouts.

## Advanced Features

### Automatic P-56 Intrusion Logging
The service automatically detects and logs P-56 intrusions **every ~12 seconds**
in the background, even when nobody is viewing the webpage.

**How it works:**
- Compares current and previous VATSIM snapshots to detect aircraft crossing P-56 boundaries
- Uses line-crossing detection (requires 2 consecutive snapshots) for accurate penetration detection
- Automatically saves intrusions to the database with full details (callsign, CID, position, timestamp, zones)
- Maintains P-56 state tracking with 60-second deduplication to prevent duplicate logs
- Captures position history: 5 datapoints before entry, unlimited inside (capped at 100), 5 after exit

**Position History Tracking:**
- Maintains `aircraft_history.json` with last 10 positions per aircraft within 300nm of DCA
- Includes latitude, longitude, altitude, groundspeed, and heading
- Pre-intrusion positions captured from history lookback
- Post-exit positions tracked for 2 minutes after leaving P-56 to capture full departure path

**View logged incidents:**
```bash
# API endpoint (returns last 100 incidents)
curl https://vncrcc.org/api/v1/p56/incidents

# Or specify a limit
curl https://vncrcc.org/api/v1/p56/incidents?limit=50
```

**Performance notes:**
- P-56 detection adds ~0.1-0.2s to the precompute cycle
- Only aircraft within 300nm of DCA are processed
- Sequential execution ensures history updates before intrusion detection runs

### Flight Path Visualization
- Click any aircraft marker or table row to show its flight history track
- Green dashed polylines show historical path with up to 10 positions
- Tracks update automatically every 15 seconds in sync with position data
- Synchronized display on both P56 and SFRA maps simultaneously
- Click again to hide the track

### Rate Limiting & DDoS Protection
**nginx Level:**
- API endpoints: 6 requests/minute (1 every 10 seconds), burst of 3
- Static files: 30 requests/minute, burst of 10
- Page loads: 10 requests/minute, burst of 5
- Localhost exempted for internal API calls

**FastAPI Level (SlowAPI):**
- All API v1 endpoints protected: 6 requests/minute
- Returns 429 Too Many Requests when exceeded
- Localhost (127.0.0.1, ::1) fully exempted
- Custom key function uses X-Forwarded-For header

See `RATE_LIMITING_DEPLOY.md` for deployment details.

## Configuration

### Environment Variables
The following environment variables control service behavior:

- `VNCRCC_CONFIG` — Path to config YAML (default: config/example_config.yaml)
- `VNCRCC_TRIM_RADIUS_NM` — Radius in NM around DCA to process (default: 300)
- `VNCRCC_WRITE_JSON_HISTORY` — Enable JSON history files (default: 1/enabled in production)
- `VNCRCC_TRACK_POSITIONS` — Track aircraft positions for P-56 intrusions (default: 1/enabled)
- `VNCRCC_ADMIN_PASSWORD` — Password for admin endpoints like `/api/v1/p56/clear`

**Production Configuration:**
Set these in the systemd override file:
```bash
sudo systemctl edit vncrcc.service
# Add:
# [Service]
# Environment=VNCRCC_TRIM_RADIUS_NM=300
# Environment=VNCRCC_WRITE_JSON_HISTORY=1
# Environment=VNCRCC_TRACK_POSITIONS=1
```

### API Endpoints

**Aircraft Data:**
- `GET /api/v1/aircraft/list` - Filtered aircraft within range
- `GET /api/v1/aircraft/list/history?range_nm=300` - Position history for all aircraft
- `GET /api/v1/aircraft/latest` - Full VATSIM snapshot

**Airspace Zones:**
- `GET /api/v1/p56/` - Current P-56 intrusions with position history
- `GET /api/v1/p56/incidents?limit=100` - Logged P-56 intrusion events
- `GET /api/v1/sfra/` - SFRA traffic
- `GET /api/v1/frz/` - FRZ traffic
- `GET /api/v1/vso/` - Virtual Security Officer range aircraft

**Utilities:**
- `GET /api/v1/geo/` - GeoJSON for airspace boundaries
- `GET /api/v1/elevation/?lat=38.85&lon=-77.04` - Elevation lookup
- `POST /api/v1/p56/clear` - Clear P-56 history (requires admin password)

All endpoints are rate-limited to 6 requests/minute per IP.

## Architecture & Data Flow

```
VATSIM API (~12s poll)
    ↓
VatsimClient (singleton fetcher)
    ↓
Update aircraft_history.json (if enabled)
    ↓
Precompute airspace detection (P-56, FRZ, SFRA, VSO)
    ↓
Storage (SQLite/PostgreSQL)
    ↓
FastAPI endpoints (rate-limited)
    ↓
Frontend (15s refresh, Leaflet maps)
```

**Key Design Decisions:**
- **Sequential history updates**: History written before precompute runs to ensure position data availability
- **In-memory caching**: Precomputed results cached for instant API responses
- **Line-crossing detection**: Requires 2 consecutive snapshots for accurate boundary crossing
- **State persistence**: P-56 intrusion state maintained across service restarts via JSON file
- **Dual map display**: Separate Leaflet instances for P-56 focus and SFRA/FRZ context

## Development Notes

**Architecture:**
- The fetcher is a singleton: use `FETCHER.register_callback(cb)` or read snapshots via `STORAGE`
- All API modules use the shared `rate_limit.py` for consistent rate limiting
- Frontend polling at 15 seconds (matches backend precompute cycle)
- Tests: `pytest -q` from the repository root (activate venv first)

**Frontend Structure:**
- `web/index.html` - Main SPA with dual map layout
- `web/app.js` - ~2100 lines of vanilla JavaScript
- `web/styles.css` - Responsive design with sticky headers, scrollable tables
- Maps use Leaflet 1.9.4 with custom markers and polyline overlays

**Backend Modules:**
- `app.py` - FastAPI application, mounts web/ and API routes
- `vatsim_client.py` - Singleton fetcher with callback registration
- `precompute.py` - Airspace detection and caching logic
- `p56_history.py` - P-56 state tracking and position capture
- `aircraft_history.py` - JSON-based position history maintenance
- `storage.py` - Database abstraction (SQLite/PostgreSQL)

## Contributing

This project is primarily developed through AI-assisted coding sessions. Most features, bug fixes, and optimizations are generated through collaborative AI development.

**Development Workflow:**
1. Features discussed and designed through natural language
2. Code generated and refined iteratively
3. Testing and debugging via AI analysis of logs and errors
4. Deployment automated via systemd and nginx

**Recent AI-Assisted Improvements:**
- Synchronized flight path updates across both maps
- Parallel data fetching for reduced latency
- Comprehensive rate limiting implementation
- Position history tracking with pre/inside/post capture
- Responsive table design with auto-sizing columns
- Real-time debugging through console logging

## License & Acknowledgments

This project uses VATSIM data and is intended for flight simulation purposes only.

**AI Development**: Most of this codebase is AI-generated and refined through collaborative development sessions.

**Technologies**: FastAPI, Leaflet.js, Shapely, SlowAPI, SQLAlchemy, uvicorn
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


#   A u t o - d e p l o y   v i a   s e l f - h o s t e d   r u n n e r   i s   n o w   a c t i v e 
 
 