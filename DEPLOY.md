# Deploying Anime Thumb Bot to a VPS

The bot talks to Telegram by **long polling**, so the server needs **no open ports and no domain**: it only makes
outgoing connections. Everything people save (brands, logos, characters, titles, text edits) lives in one `data/` folder.

## What you need

| | |
|---|---|
| **Server** | Ubuntu 22.04 / 24.04 (or Debian 12), 1 vCPU |
| **RAM** | **2 GB recommended.** A 1 GB server works with `RENDER_CONCURRENCY=1` and `AUTO_CUTOUT=false` (and a swap file, below) |
| **Disk** | ~10 GB free (the Docker image with Chromium is a few GB; the AI cutout model adds ~180 MB) |
| **Token** | from @BotFather: `/mybots` → your bot → *API Token* |

> **Stop the Colab bot first.** One token can only be polled by one copy. If a Colab session is still running you will
> see `Conflict: terminated by other getUpdates request` in the logs. Colab's saved settings do not carry over to the
> server (Colab wipes its files), so people set their brand once more.

---

## Option A: Docker (recommended)

**1. Install Docker** (official convenience script from docker.com):

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER        # then log out and back in once
```

**2. Upload and unzip** (from your computer, then on the server):

```bash
scp anime-thumb-bot.zip youruser@SERVER_IP:~/
# on the server:
sudo apt-get install -y unzip
unzip anime-thumb-bot.zip && cd anime-thumb-bot
```

**3. Configure:**

```bash
cp .env.example .env
nano .env                  # set BOT_TOKEN=...  (everything else is optional)
chmod 600 .env             # it holds your token
```

**4. Start:**

```bash
docker compose up -d --build       # first build takes 5-10 minutes
docker compose logs -f             # look for: Anime Thumb Bot v2.0.0 as @yourbot ... Bot is up
```

Open your bot in Telegram, send `/start`, then `/version` (it shows the version, what is switched on, and which
copy answered). Then try `/poster Solo Leveling`.

**Day to day**

| | |
|---|---|
| Logs | `docker compose logs -f --tail 100` |
| Status / health | `docker compose ps` (shows *healthy* once it is running well) |
| Restart / stop | `docker compose restart` / `docker compose stop` |
| **Update** | upload the new zip, unzip it over the folder (keep your `.env`), then `docker compose up -d --build` |
| Backup | `bash deploy/backup.sh docker ~/backups` |
| Restore | `docker compose down`, then `docker run --rm -v anime-thumb-bot_botdata:/data -v "$PWD":/in alpine sh -c "cd /data && tar xzf /in/YOUR-BACKUP.tgz"`, then `docker compose up -d` |

The volume name is `<folder name>_botdata`; check it with `docker volume ls`. The bot restarts by itself after a crash
and after a server reboot (`restart: unless-stopped`).

---

## Option B: without Docker (systemd)

```bash
unzip anime-thumb-bot.zip && cd anime-thumb-bot
sudo bash deploy/install.sh          # installs everything under /opt/anime-thumb-bot, creates a service user
sudo nano /opt/anime-thumb-bot/.env  # set BOT_TOKEN=...
sudo systemctl start anime-thumb-bot
journalctl -u anime-thumb-bot -f
```

Update later with `sudo bash deploy/update.sh` from the newly unzipped folder (your `.env` and `data/` are kept).
Backup: `sudo bash deploy/backup.sh /opt/anime-thumb-bot/data ~/backups`.

---

## Settings you may want

All of them go in `.env` (see `.env.example` for the full list with comments).

| Setting | Meaning |
|---|---|
| `ALLOWED_USER_IDS` | Make the bot **private**: only these Telegram user IDs can use it (find yours with @userinfobot). Empty = everyone |
| `ADMIN_IDS` | Always allowed, never rate-limited |
| `RATE_LIMIT_PER_MIN` | Protects the server when the bot is public. Normal render = 1 point, HD file = 2, Preview all = 3. Default 20 |
| `RENDER_CONCURRENCY` | Banners rendered at once. **Each needs ~300-500 MB RAM.** 1 on a 1 GB server, 2 on 2-4 GB |
| `AUTO_CUTOUT` | AI background removal for uploaded characters. Needs ~1 GB extra RAM while it runs; `false` turns it off (plain white backgrounds are still removed) |
| `TMDB_API_KEY` | HD backdrops **and a backup search when AniList is down or doesn't have a title** (free key from themoviedb.org) |
| `FANART_API_KEY` | Automatic transparent characters for the Special Design and real title logos (free key from fanart.tv) |
| `EXTRA_ART_SOURCES`, `UPSCALE_SMALL_ART`, `TITLE_LOGOS` | Feature switches, all `true` by default |
| `WATERMARK_TEXT`, `WATERMARK_KEY` | Optional visible / invisible owner watermark (off while empty) |
| `LOG_LEVEL` | `INFO` normally, `DEBUG` when hunting a problem |

After editing `.env`: `docker compose up -d` (Docker) or `sudo systemctl restart anime-thumb-bot` (systemd).

## Security checklist

- Allow only SSH in the firewall: `sudo ufw allow OpenSSH && sudo ufw enable`. The bot needs no inbound port.
- Keep `.env` private (`chmod 600`). If the token ever leaks, create a new one in @BotFather (`/revoke`) and update `.env`.
- Running it for yourself and friends? Set `ALLOWED_USER_IDS`. Public? Keep `RATE_LIMIT_PER_MIN` on.
- Don't put the token in `settings.py` on a server: it would be copied into the Docker image. Use `.env`.
- Keep the server updated: `sudo apt-get update && sudo apt-get upgrade`, or enable `unattended-upgrades`.

## Troubleshooting

| Problem | What to do |
|---|---|
| `Conflict: terminated by other getUpdates request` | Another copy uses the same token: a Colab session, an old container, a second server. Stop it. `/version` shows which copy answered |
| `Telegram rejected BOT_TOKEN` | Wrong or revoked token. Copy it again from @BotFather into `.env` |
| `Telegram unreachable ... Retrying` | The server can't reach api.telegram.org yet. The bot keeps retrying by itself; test with `curl -I https://api.telegram.org` |
| Container killed / `OOMKilled` | Out of memory. Lower `RENDER_CONCURRENCY`, set `AUTO_CUTOUT=false`, or add swap (below) |
| Blank or broken renders | Chromium needs shared memory: keep `shm_size: "1gb"` in `docker-compose.yml`. Check `docker stats` for memory |
| Boxes instead of Japanese letters | Docker image already includes the fonts. On systemd run `sudo apt-get install fonts-noto-cjk` and restart |
| First character upload is slow | The AI model (~180 MB) downloads once, at the first start, and is kept in the data volume |
| TMDB art never appears | Test the key and a title: `docker compose exec bot python -m scripts.tmdb_check "The Eminence in Shadow"` |
| `permission denied` on `data/` (systemd) | `sudo chown -R animebot:animebot /opt/anime-thumb-bot/data` |

**Add swap on a small server** (once):

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## What runs where

- `docker-compose.yml` / `Dockerfile`: the container, health check (`deploy/healthcheck.py` reads the heartbeat file the bot touches every 30 s), log rotation (5 x 10 MB), non-root user.
- `deploy/anime-thumb-bot.service`: the systemd unit (auto-restart, hardening). `install.sh`, `update.sh`, `backup.sh` are plain, readable shell scripts.
- `requirements.lock.txt`: the exact dependency versions this release was tested with. `requirements.txt` is the looser list for development and Colab.
