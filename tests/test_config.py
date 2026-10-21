"""Configuration and deployment checks. No network, no Telegram.   python -m tests.test_config"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
KEYS = ("BOT_TOKEN", "ALLOWED_USER_IDS", "ADMIN_IDS", "RATE_LIMIT_PER_MIN", "RENDER_CONCURRENCY", "AUTO_CUTOUT", "DB_PATH",
        "TMDB_API_KEY", "LOG_LEVEL", "BRAND_POSITION", "SPECIAL_BOXES_OPACITY", "KILL_OLD_INSTANCES", "ICONS")


def fresh_config(**env):
    """Reload bot.config with a clean environment plus `env`."""
    for k in KEYS:
        os.environ.pop(k, None)
    os.environ.update(env)
    sys.modules.pop("bot.config", None)
    import bot.config as config
    return config


# 1) environment variables win; the stock settings.py placeholder never shadows them
config = fresh_config(BOT_TOKEN=TOKEN, RENDER_CONCURRENCY="3", AUTO_CUTOUT="false", ALLOWED_USER_IDS="11, 22 33",
                      ADMIN_IDS="99", RATE_LIMIT_PER_MIN="30", DB_PATH="/data/x/bot.db", TMDB_API_KEY="k", LOG_LEVEL="debug",
                      BRAND_POSITION="BL", SPECIAL_BOXES_OPACITY="7")
c = config.load()
assert c.bot_token == TOKEN, "BOT_TOKEN from the environment (settings.py only has the PASTE placeholder)"
assert (c.render_concurrency, c.auto_cutout, c.rate_limit, c.log_level) == (3, False, 30, "DEBUG")
assert c.allowed_users == frozenset({11, 22, 33}) and c.admin_ids == frozenset({99})
assert c.db_path == Path("/data/x/bot.db") and c.data_dir == Path("/data/x") and c.heartbeat_file == Path("/data/x/heartbeat")
assert c.brand_position == "bl" and c.boxes_opacity == 1.0, "corners are case-insensitive; opacity is clamped to 0..1"
assert c.tmdb_key == "k"

# 2) defaults, and bad values fall back instead of crashing
config = fresh_config(BOT_TOKEN=TOKEN, RENDER_CONCURRENCY="lots", RATE_LIMIT_PER_MIN="-5", LOG_LEVEL="loud", BRAND_POSITION="middle")
c = config.load()
assert (c.render_concurrency, c.rate_limit, c.log_level, c.brand_position) == (2, 0, "INFO", "tr"), (c.render_concurrency, c.rate_limit, c.log_level, c.brand_position)
assert c.allowed_users == frozenset() and c.auto_cutout is True and c.special_defaults is True
assert c.db_path == ROOT / "data" / "bot.db"

# 3) a missing token stops with a clear message; a placeholder counts as missing
config = fresh_config()
try:
    config.load(); raise AssertionError("should exit")
except SystemExit as e:
    assert "BOT_TOKEN" in str(e) and ".env" in str(e)
config = fresh_config(BOT_TOKEN="PASTE_YOUR_BOT_TOKEN_HERE")
try:
    config.load(); raise AssertionError("placeholder must not count as a token")
except SystemExit:
    pass

# 4) optional JSON for animated icons from the environment
config = fresh_config(BOT_TOKEN=TOKEN, ICONS='{"template": "5368324170671202286"}')
assert config.load().icons.get("template") == "5368324170671202286"
print("config OK")

# 5) health check: fresh heartbeat = healthy, stale or missing = unhealthy
tmp = Path(tempfile.mkdtemp())
env = {**os.environ, "DB_PATH": str(tmp / "bot.db")}
run = lambda: subprocess.run([sys.executable, str(ROOT / "deploy" / "healthcheck.py")], env=env, capture_output=True, text=True)
assert run().returncode == 1, "no heartbeat yet -> unhealthy"
(tmp / "heartbeat").write_text(str(time.time()))
assert run().returncode == 0, "fresh heartbeat -> healthy"
(tmp / "heartbeat").write_text(str(time.time() - 300))
assert run().returncode == 1 and "300" in run().stdout.replace("301", "300").replace("299", "300"), "5-minute-old heartbeat -> unhealthy"
(tmp / "heartbeat").write_text("garbage")
assert run().returncode == 1
print("healthcheck OK")

# 6) the Docker image, the lock file and requirements.txt must agree on the Playwright version
docker = (ROOT / "Dockerfile").read_text()
image = re.search(r"playwright/python:v([\d.]+)-", docker).group(1)
lock = re.search(r"^playwright==([\d.]+)", (ROOT / "requirements.lock.txt").read_text(), re.M).group(1)
loose = re.search(r"^playwright==([\d.]+)", (ROOT / "requirements.txt").read_text(), re.M).group(1)
assert image == lock == loose, f"Docker image {image}, lock {lock}, requirements {loose} must match"
assert "USER pwuser" in docker and "HEALTHCHECK" in docker and "tini" in docker
compose = (ROOT / "docker-compose.yml").read_text()
assert "restart: unless-stopped" in compose and "shm_size" in compose and "botdata:/app/data" in compose and "env_file" in compose
assert not any(l.startswith(("BOT_TOKEN=1", "BOT_TOKEN=2")) for l in (ROOT / ".env.example").read_text().splitlines())
ignored = (ROOT / ".dockerignore").read_text()
assert ".env" in ignored and "data/" in ignored, "secrets and saved data never go into the image"
for name in ("install.sh", "update.sh", "backup.sh"):
    assert subprocess.run(["bash", "-n", str(ROOT / "deploy" / name)]).returncode == 0, name
unit = (ROOT / "deploy" / "anime-thumb-bot.service").read_text()
assert "Restart=always" in unit and "EnvironmentFile=" in unit and "NoNewPrivileges=true" in unit
print("deployment files OK: playwright", image, "everywhere")
print("ALL OK")
