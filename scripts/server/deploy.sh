#!/bin/bash
# Production deploy for vNCRCC (JY5). Invoked by check-deploy.sh.
#
# - Pulls origin/main (fast-forward only).
# - web/ changes: rsync into the nginx docroot /var/www/html/web. nginx does
#   NOT serve this checkout directly. No --delete: that docroot also holds
#   other content (vatsim2m/, vatsim3m/).
# - src/ or requirements.txt changes: pip install (if needed) + restart.
#
# Everything lives inside main() so bash parses the whole script before
# running it: the git pull below may rewrite this very file.
set -euo pipefail

REPO=/home/JY/vNCRCC
DOCROOT=/var/www/html/web
SERVICE=vncrcc.service

main() {
    cd "$REPO"
    local prev new changed
    prev=$(git rev-parse HEAD)
    git pull --quiet --ff-only origin main
    new=$(git rev-parse HEAD)
    if [ "$prev" = "$new" ]; then
        echo "[Deploy] Already up to date"
        return 0
    fi
    echo "[Deploy] Updated ${prev:0:7} -> ${new:0:7}"
    changed=$(git diff --name-only "$prev" "$new")

    if grep -qE '^web/' <<<"$changed"; then
        echo "[Deploy] Syncing web/ -> $DOCROOT"
        rsync -a --no-group --no-owner "$REPO/web/" "$DOCROOT/"
    fi

    local restart=false
    if grep -qE '^requirements\.txt$' <<<"$changed"; then
        echo "[Deploy] requirements.txt changed, updating venv"
        "$REPO/venv/bin/pip" install --quiet -r "$REPO/requirements.txt"
        restart=true
    fi
    if grep -qE '^src/' <<<"$changed"; then
        restart=true
    fi

    if [ "$restart" = true ]; then
        echo "[Deploy] Restarting $SERVICE"
        sudo /usr/bin/systemctl restart "$SERVICE"
        # Fail loudly (visible in journalctl -u vncrcc-deploy) if it doesn't come up.
        for _ in $(seq 1 30); do
            if curl -fsS -o /dev/null http://127.0.0.1:8000/health; then
                echo "[Deploy] $SERVICE healthy"
                return 0
            fi
            sleep 1
        done
        echo "[Deploy] ERROR: $SERVICE did not become healthy after restart" >&2
        return 1
    fi
    echo "[Deploy] No backend changes; no restart needed"
}

main "$@"
exit $?
