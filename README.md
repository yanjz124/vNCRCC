# vNCRCC — virtual National Capitol Region Command Center

**Live Dashboard**: [p56buster.club](https://p56buster.club) | [vncrcc.org](https://vncrcc.org)

vNCRCC is a real-time flight tracking and airspace monitoring system for the National Capital Region (Washington, DC area) on the VATSIM network. It provides automated detection and logging of aircraft in restricted airspace zones (P-56, FRZ, SFRA) with a responsive web dashboard featuring live maps, continuous position tracking, and comprehensive flight data with telemetry labels.

> **Note**: This project is primarily AI-assisted development, with most code generated and refined through AI collaboration.

## Key Features

### Real-Time Airspace Monitoring
- **Live Aircraft Tracking**: Position updates every ~12 seconds from VATSIM data feed
- **Automated Geofencing**: Continuous P-56 intrusion detection with line-crossing validation
- **Dual Interactive Maps**: Side-by-side P-56 and SFRA/FRZ visualization using Leaflet.js
- **Four-Zone Classification**: P-56 (red), FRZ/Flight Restricted Zone (orange), SFRA/Special Flight Rules Area (blue), Vicinity (green)
- **On-Ground Detection**: Automatic identification of ground traffic using groundspeed and altitude heuristics

### Position History & Flight Tracking
- **Continuous Position Capture**: Full intrusion tracks with "P56 buster" flag tracking
  - 7 pre-intrusion positions (approach context)
  - All positions while inside P-56 (capped at 200 for safety)
  - 10-cycle exit confirmation (prevents false exits from GPS jitter)
  - 1-second minimum position spacing
- **Visual Flight Tracks**: Click any aircraft to show full historical path with telemetry labels
  - Heading°/Altitude ft/Groundspeed kts displayed on sampled positions
  - Max 50 labels per track (intelligently sampled)
  - Yellow tracks on both maps with synchronized display
- **Aircraft History**: JSON-based position log with last 10 positions per aircraft within 300nm

### Analytics & Leaderboard
- **P-56 Buster Leaderboard**: Ranked intrusion counts per pilot with first/last timestamps
- **Detailed Event History**: Expandable intrusion details with complete position tracks
- **Online ATC Display**: Live controller list from ZDC ARTCC area with friendly facility names

### User Experience
- **Performance Optimized**: Parallel icon creation, minimal console logging, fast DOM operations
- **Responsive Design**: Sticky headers, auto-sizing columns, mobile-friendly tables
- **Flight Plan Integration**: Expandable details with full route, remarks, and squawk codes
- **Rate Limiting**: DDoS protection at nginx and FastAPI levels (6 requests/minute per IP)

## Technical Stack

- **Backend**: FastAPI, Python 3.8+, SQLite/PostgreSQL
- **Frontend**: Vanilla JavaScript, Leaflet.js for maps
- **Geospatial**: Shapely for polygon operations, GeoJSON for airspace boundaries
- **Deployment**: Systemd service, nginx reverse proxy
- **Rate Limiting**: SlowAPI (FastAPI) + nginx limit_req zones

## Quick Start

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# Run the worker which polls VATSIM and saves snapshots to sqlite
python -m src.vncrcc.worker
```

### Run the API (FastAPI + uvicorn)

```bash
# Development: run the FastAPI app with uvicorn
uvicorn vncrcc.app:app --host 0.0.0.0 --port 8000 --reload
```

The app mounts the `web/` directory at `/`, so the SPA (`web/index.html`, `web/app.js`, `web/static/*`) is served from the same process. API routes remain under `/api/...`.

### Configuration

- Default config: `config/example_config.yaml`
- Override by setting environment variable `VNCRCC_CONFIG=/path/to/config.yaml`
- Keys commonly used: `vatsim_url`, `poll_interval`, `db_path`

### Local Development Helper (Windows PowerShell)

Use the included PowerShell helper to create a virtualenv and run either the API or the worker on Windows:

```powershell
# Run the API (creates/uses .venv and sets PYTHONPATH)
.\dev-run.ps1 -Mode api -Port 8000

# Run the worker
.\dev-run.ps1 -Mode worker
```

The helper will create `.venv` in the repo root and set `PYTHONPATH` to include `src` so imports like `python -m src.vncrcc.worker` work.

## Deployment

### Deployment to Raspberry Pi (automatic helper)

The repo includes `scripts/deploy.sh` which the Pi (or GitHub Actions) can call to: pull the latest code, ensure a `venv` is present, install requirements, and restart the systemd service `vncrcc.service`.

### Recommended manual deploy steps on the Pi

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

### GitHub Actions deploy

This repo includes a workflow `.github/workflows/deploy.yml` that SSHes to the Pi and runs `/home/<user>/vNCRCC/scripts/deploy.sh`. For it to succeed you must configure the repository secrets:

- `PI_HOST` — Pi hostname/IP
- `PI_USER` — user on the Pi (e.g. `pi`)
- `DEPLOY_KEY` — private SSH key (PEM) whose public key is in `/home/<PI_USER>/.ssh/authorized_keys` on the Pi
- (optional) `PI_PORT` — SSH port (defaults to 22)

**Common failure modes with Actions deploy:**

- `Permission denied` / SSH auth: ensure `DEPLOY_KEY` is the private key and the corresponding public key is installed in `authorized_keys`
- `deploy.sh` not found or not executable: make sure the repo exists at `/home/<PI_USER>/vNCRCC` on the Pi and `scripts/deploy.sh` is executable
- `deploy.sh` itself failing: check `~/vNCRCC/logs/vncrcc-deploy.log` on the Pi or run the script manually to see the error

### Systemd unit (what runs on the Pi)

The Pi runs a systemd unit named `vncrcc.service` which starts uvicorn (the FastAPI process) from the repo venv. Typical lifecycle:

- systemd starts the uvicorn process on boot
- uvicorn loads `vncrcc.app:app`, which mounts `web/` and registers the Vatsim fetcher

Sample systemd unit:

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

Adjust `ExecStart` flags (workers, bind address) as appropriate for your hardware. If you're behind nginx or Cloudflare Tunnel, bind to 127.0.0.1 and let the external proxy forward requests.

### Cloudflare Tunnel / nginx notes

- The Pi historically uses `cloudflared` to expose the origin via a Cloudflare Tunnel. If you're using cloudflared, ensure the service is running and the tunnel is connected: `sudo systemctl status cloudflared` and `sudo journalctl -u cloudflared -f`
- If the browser shows a JSON response at `/` or `Unexpected token '<'` for a JS file, check that the origin (curl 127.0.0.1:8000/) returns HTML and that nginx or the tunnel is forwarding to the correct backend port

### Troubleshooting checklist

- If Actions deploy fails: inspect the workflow logs to see whether SSH authentication failed or the remote script errored. Test SSH locally with the same key you configured in `DEPLOY_KEY`
- If the web UI serves JSON or wrong content: `curl -i http://127.0.0.1:8000/app.js` should return the JavaScript file; if it returns HTML, your static mount or proxy mapping is wrong
- If the app times out after hours: monitor `journalctl -u cloudflared` and system resources (`top`, `vmstat`) and consider increasing uvicorn workers, ulimits, or tuning the cloudflared receive buffer and nginx proxy timeouts

## Advanced Features

### Airspace Classification & Geofencing

**Four-Zone System:**

Aircraft are automatically categorized in real-time based on their geographic position:

1. **P-56 (Red)** - Prohibited Area around White House/Capitol
   - Most restrictive zone, triggers intrusion logging
   - 2-mile radius around sensitive government buildings
   
2. **FRZ (Orange)** - Flight Restricted Zone
   - 13-15 mile radius around Ronald Reagan Washington National Airport (KDCA)
   - Requires special authorization to operate
   
3. **SFRA (Blue)** - Special Flight Rules Area  
   - 30-mile radius around KDCA
   - Requires flight plan and two-way radio communication
   
4. **Vicinity (Green)** - Within monitoring range but outside restricted zones
   - Up to 300nm from DCA for performance optimization

**Classification Logic:**

```python
# Priority order (higher priority overrides lower)
if point_in_polygon(position, P56_boundary):
    return 'p56'  # Red marker
elif point_in_polygon(position, FRZ_boundary):
    return 'frz'  # Orange marker
elif point_in_polygon(position, SFRA_boundary):
    return 'sfra'  # Blue marker
else:
    return 'vicinity'  # Green marker
```

**On-Ground Detection:**

Ground aircraft are identified using multi-rule heuristics:
- Groundspeed ≤ 10 kt (stationary/slow taxi)
- Groundspeed < 40 kt AND altitude < 500 ft (fast taxi)
- Groundspeed < 60 kt AND altitude < 200 ft (runway operations)

Ground aircraft appear as gray markers and are listed separately in tables.

### Automated P-56 Intrusion Detection & Logging

**Continuous Background Monitoring:**

The service detects and logs P-56 intrusions **every ~12 seconds**, independent of web dashboard viewers.

**Line-Crossing Detection:**

- Compares consecutive VATSIM snapshots to detect boundary crossings
- Requires 2 snapshots for validation (prevents false positives from GPS jitter)
- Uses Shapely's `intersects()` and `contains()` for precise geofence testing

**"P56 Buster" Tracking System:**

When an aircraft enters P-56, the system activates continuous position capture:

1. **Entry Detection**: 
   - Seed `intrusion_positions` array with 7 pre-approach positions from aircraft history
   - Set `p56_buster` flag to `True` for this aircraft
   - Record entry point with full telemetry (lat, lon, alt, heading, groundspeed)

2. **Continuous Capture** (while inside or within exit confirmation window):
   - Append position every cycle (1-second minimum spacing)
   - Include full aircraft state: latitude, longitude, altitude, heading, groundspeed, callsign
   - Safety cap at 200 positions to prevent unbounded growth

3. **Exit Confirmation**:
   - Requires 10 consecutive "outside P-56" positions to confirm exit
   - Prevents false exits from GPS jitter or brief boundary touches
   - Once confirmed, set `p56_buster` flag to `False` and finalize event

**Position History Architecture:**

- **Pre-intrusion**: 7 positions captured from `aircraft_history.json` lookback
- **During intrusion**: Unlimited positions (200-position safety cap) with 1s minimum spacing
- **Exit tracking**: 10-cycle confirmation window continues capture until validated exit

**Deduplication Logic:**

- 60-second deduplication window prevents duplicate logs for quick re-entries
- If same pilot re-enters within 60s, positions merge into existing event rather than creating new entry

**Data Persistence:**

- Events stored in `data/p56_history.json` with full position arrays
- State tracking in `current_inside` object maintains `p56_buster` flags across service restarts
- Frontend displays complete tracks with telemetry labels (heading°/altitude ft/groundspeed kts)

**View Intrusion History:**

```bash
# Last 100 logged intrusions with full position data
curl https://p56buster.club/api/v1/p56/incidents

# Specific limit
curl https://p56buster.club/api/v1/p56/incidents?limit=50

# Current active intrusions with live position tracking
curl https://p56buster.club/api/v1/p56/
```

**Performance:**

- P-56 detection adds ~0.1-0.2s to precompute cycle
- Only aircraft within 300nm of DCA processed
- Sequential execution: aircraft history updates before intrusion detection runs

### Flight Path Visualization & Telemetry Labels

**Live Flight Tracks:**

- Click any aircraft marker to toggle its historical flight path
- Green dashed polylines with up to 10 positions from `aircraft_history.json`
- Yellow polylines for P-56 intrusion tracks (pre + during + post positions)
- Synchronized display on both P56 and SFRA maps simultaneously
- Tracks auto-update every ~12 seconds with latest positions

**Telemetry Labels on P-56 Intrusion Tracks:**

Each intrusion track displays sampled position labels with full aircraft state:

- **Format**: `heading°/altitude ft/groundspeed kts`
- **Example**: `240°/3500ft/180kts`
- **Sampling**: Max 50 labels per track (intelligently spaced), always includes last position
- **Styling**: White text on semi-transparent black background, positioned above each point

**Implementation:**

```javascript
// Frontend creates Leaflet divIcon markers for each sampled position
const label = L.divIcon({
  html: `<div class="p56-point-label">${heading}°/${alt}ft/${gs}kts</div>`,
  className: 'p56-point-label-wrapper',
  iconAnchor: [0, 15]
});
```

Labels help analysts reconstruct the flight profile and understand pilot intent during intrusions.

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
