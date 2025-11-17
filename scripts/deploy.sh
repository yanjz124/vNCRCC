#!/usr/bin/env bash
# Simple deploy script to run on the Raspberry Pi. Intended to be invoked by
# GitHub Actions via SSH or run manually on the Pi after pulling new code.

set -euo pipefail

###############################################################################
# Resolve repository directory robustly even when invoked via sudo.
# Using the script's location avoids $HOME changing to /root under sudo.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# Write logs into a repo-local logs directory by default so root isn't required.
LOGFILE="$REPO_DIR/logs/vncrcc-deploy.log"

# Ensure the log directory exists so tee can create the logfile without root
mkdir -p "$(dirname "$LOGFILE")"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting deploy" | tee -a "$LOGFILE"

if [ ! -d "$REPO_DIR" ]; then
  echo "Repository directory $REPO_DIR not found" | tee -a "$LOGFILE"
  exit 1
fi

cd "$REPO_DIR"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Fetching latest from origin/main" | tee -a "$LOGFILE"
git fetch --all --prune
git reset --hard origin/main

# Prefer the service venv at ./venv to match systemd ExecStart; fallback to .venv
if [ -f "venv/bin/activate" ]; then
  VENV_DIR="venv"
elif [ -f ".venv/bin/activate" ]; then
  VENV_DIR=".venv"
else
  VENV_DIR="venv"
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Creating virtualenv at $VENV_DIR" | tee -a "$LOGFILE"
  python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Installing requirements" | tee -a "$LOGFILE"
pip install --upgrade pip
pip install -r requirements.txt

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Copying web files to nginx document root" | tee -a "$LOGFILE"
sudo cp -r "$REPO_DIR/web"/* /var/www/html/web/ 2>&1 | tee -a "$LOGFILE" || true

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Restarting systemd service vncrcc" | tee -a "$LOGFILE"
sudo systemctl restart vncrcc.service

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Deploy finished" | tee -a "$LOGFILE"

exit 0
