#!/bin/bash
# Run every 60s by vncrcc-deploy.timer on the production host (JY5).
# Cheap check: only invokes deploy.sh when origin/main has moved.
cd /home/JY/vNCRCC || exit 1

git fetch origin --quiet 2>/dev/null || exit 0

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "[$(date -Is)] New commits detected ($LOCAL -> $REMOTE), deploying..."
    exec /bin/bash /home/JY/vNCRCC/scripts/server/deploy.sh
fi
