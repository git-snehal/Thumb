#!/usr/bin/env bash
# Updates a systemd install (deploy/install.sh) from a newly unzipped folder. Keeps .env and data/.
#     sudo bash deploy/update.sh
# (Docker users: just run  docker compose up -d --build  in the new folder.)
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/anime-thumb-bot}"
APP_USER="${APP_USER:-animebot}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "$(id -u)" -ne 0 ]; then
    echo "Please run as root:  sudo bash deploy/update.sh" >&2
    exit 1
fi
if [ ! -d "$APP_DIR/venv" ]; then
    echo "$APP_DIR isn't installed yet. Run  sudo bash deploy/install.sh  first." >&2
    exit 1
fi

rsync -a --delete \
    --exclude 'venv/' --exclude 'browsers/' --exclude 'data/' --exclude '.env' \
    --exclude '__pycache__/' --exclude '*.zip' --exclude 'preview/' \
    "$SRC_DIR"/ "$APP_DIR"/
REQ="$APP_DIR/requirements.lock.txt"
[ -f "$REQ" ] || REQ="$APP_DIR/requirements.txt"
"$APP_DIR/venv/bin/pip" install --quiet -r "$REQ"
PLAYWRIGHT_BROWSERS_PATH="$APP_DIR/browsers" "$APP_DIR/venv/bin/playwright" install chromium
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
systemctl restart anime-thumb-bot
sleep 3
systemctl --no-pager --lines=8 status anime-thumb-bot || true
echo "Updated. Send /version to the bot to confirm the new version."
