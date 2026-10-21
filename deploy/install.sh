#!/usr/bin/env bash
# Installs Anime Thumb Bot as a systemd service WITHOUT Docker (Ubuntu 22.04/24.04 or Debian 12).
# Run it as root from the unzipped project folder:
#     sudo bash deploy/install.sh
# It is safe to run again later to update (your .env and data/ are never touched).
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/anime-thumb-bot}"
APP_USER="${APP_USER:-animebot}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "$(id -u)" -ne 0 ]; then
    echo "Please run as root:  sudo bash deploy/install.sh" >&2
    exit 1
fi
if ! command -v apt-get >/dev/null 2>&1; then
    echo "This installer supports Debian/Ubuntu (apt). On other systems use Docker (see DEPLOY.md)." >&2
    exit 1
fi

echo "==> Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends python3 python3-venv python3-pip rsync ca-certificates fonts-noto-cjk

echo "==> Creating the '$APP_USER' user and $APP_DIR"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$APP_DIR/data"

echo "==> Copying the bot to $APP_DIR"
rsync -a --delete \
    --exclude 'venv/' --exclude 'browsers/' --exclude 'data/' --exclude '.env' \
    --exclude '__pycache__/' --exclude '*.zip' --exclude 'preview/' \
    "$SRC_DIR"/ "$APP_DIR"/

echo "==> Python environment"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip wheel
REQ="$APP_DIR/requirements.lock.txt"
[ -f "$REQ" ] || REQ="$APP_DIR/requirements.txt"
"$APP_DIR/venv/bin/pip" install --quiet -r "$REQ"

echo "==> Chromium for rendering (a few minutes the first time)"
PLAYWRIGHT_BROWSERS_PATH="$APP_DIR/browsers" "$APP_DIR/venv/bin/playwright" install --with-deps chromium

if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    echo "==> Created $APP_DIR/.env (you must set BOT_TOKEN in it)"
fi
chmod 600 "$APP_DIR/.env"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "==> systemd service"
install -m 644 "$APP_DIR/deploy/anime-thumb-bot.service" /etc/systemd/system/anime-thumb-bot.service
sed -i "s|/opt/anime-thumb-bot|$APP_DIR|g; s|^User=.*|User=$APP_USER|; s|^Group=.*|Group=$APP_USER|" \
    /etc/systemd/system/anime-thumb-bot.service
systemctl daemon-reload
systemctl enable anime-thumb-bot >/dev/null

if grep -Eq '^BOT_TOKEN=.+' "$APP_DIR/.env"; then
    systemctl restart anime-thumb-bot
    echo
    echo "Started. Watch it with:   journalctl -u anime-thumb-bot -f"
else
    echo
    echo "NEXT STEPS:"
    echo "  1. nano $APP_DIR/.env        (set BOT_TOKEN=...)"
    echo "  2. systemctl start anime-thumb-bot"
    echo "  3. journalctl -u anime-thumb-bot -f"
fi
