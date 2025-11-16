# vNCRCC — virtual National Capitol Region Command Center (prototype)

vNCRCC polls the VATSIM data feed, saves periodic snapshots to a local
database, and exposes a small FastAPI-based dashboard and a set of
geofence/analysis endpoints. The project is intended to run on a Raspberry
Pi (origin) or a small VM and be accessible via Cloudflare Tunnel / nginx.

This README explains how to run locally, deploy to the Pi, and what the
Pi's runtime looks like (systemd, virtualenv, Cloudflare tunnel).

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

Developer notes
---------------
- The fetcher is a singleton: use `FETCHER.register_callback(cb)` or read
  snapshots via the `STORAGE` singleton in `src/vncrcc/storage.py`.
- Tests: `pytest -q` from the repository root (activate the venv first).

If you'd like, I can (A) add a small diagnostic step to the GitHub Actions
deploy workflow to print SSH diagnostics, or (B) prepare a sample
`vncrcc.service` drop-in tailored to your current systemd override. Tell me
which and I'll produce the change.
