#!/usr/bin/env bash
# Simple deploy script to run on the Raspberry Pi. Intended to be invoked by
# GitHub Actions via SSH or run manually on the Pi after pulling new code.

set -euo pipefail

REPO_DIR="/home/pi/vNCRCC"
LOGFILE="/var/log/vncrcc-deploy.log"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting deploy" | tee -a "$LOGFILE"

if [ ! -d "$REPO_DIR" ]; then
  echo "Repository directory $REPO_DIR not found" | tee -a "$LOGFILE"
  exit 1
fi

cd "$REPO_DIR"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Fetching latest from origin/main" | tee -a "$LOGFILE"
git fetch --all --prune
git reset --hard origin/main

# Activate virtualenv if present
if [ -x "venv/bin/activate" ] || [ -f "venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
else
  echo "venv not found; creating a virtualenv" | tee -a "$LOGFILE"
  python3 -m venv venv
  # shellcheck disable=SC1091
  source venv/bin/activate
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Installing requirements" | tee -a "$LOGFILE"
pip install --upgrade pip
pip install -r requirements.txt

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Restarting systemd service vncrcc" | tee -a "$LOGFILE"
sudo systemctl restart vncrcc.service

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Deploy finished" | tee -a "$LOGFILE"

exit 0
