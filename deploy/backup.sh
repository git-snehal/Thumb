#!/usr/bin/env bash
# Backs up everything people saved in the bot (brands, logos, characters, titles, text edits) into one .tgz.
# The AI model cache and the heartbeat file are left out (they are re-created automatically).
#
#   Docker:    bash deploy/backup.sh docker [output_folder]
#   systemd:   sudo bash deploy/backup.sh /opt/anime-thumb-bot/data [output_folder]
#
# Restore: stop the bot, then  tar xzf <backup>.tgz -C <data folder>   (see DEPLOY.md for the Docker command).
set -euo pipefail

SRC="${1:-docker}"
OUT="${2:-.}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
FILE="anime-thumb-bot-data-$(date +%Y%m%d-%H%M%S).tgz"

if [ "$SRC" = "docker" ]; then
    VOL="$(docker volume ls -q | grep -E '(^|_)botdata$' | head -n1 || true)"
    if [ -z "$VOL" ]; then
        echo "Couldn't find the Docker volume 'botdata'. Is the bot running with docker compose?" >&2
        exit 1
    fi
    docker run --rm -v "$VOL":/data:ro -v "$OUT":/out alpine \
        tar czf "/out/$FILE" -C /data --exclude=./rembg --exclude=./heartbeat .
else
    tar czf "$OUT/$FILE" -C "$SRC" --exclude=./rembg --exclude=./heartbeat .
fi
echo "Saved $OUT/$FILE"
