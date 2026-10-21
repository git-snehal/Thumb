"""Docker HEALTHCHECK: succeeds if the bot has touched its heartbeat file in the last 2 minutes."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bot import config  # noqa: E402

db = Path(config._str("DB_PATH", "data/bot.db"))
db = db if db.is_absolute() else config.ROOT / db
beat = db.parent / "heartbeat"
try:
    age = time.time() - float(beat.read_text())
except (OSError, ValueError):
    print("unhealthy: no heartbeat file yet")
    sys.exit(1)
if age > 120:
    print(f"unhealthy: heartbeat is {age:.0f}s old")
    sys.exit(1)
print(f"healthy: heartbeat {age:.0f}s old")
