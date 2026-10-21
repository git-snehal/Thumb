"""Stop leftover copies of this bot.

Two copies polling the same token answer alternately (one might be an old version), which looks like
"the design changes every other time". On Google Colab a stopped cell can leave its Python process
running, so on start we stop any other `python -m bot` process we can see.
"""
from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path

log = logging.getLogger(__name__)


def is_bot_cmdline(args: list[str]) -> bool:
    """True for `python -m bot` (any python executable, any extra flags before -m)."""
    if not args or "python" not in Path(args[0]).name:
        return False
    try:
        i = args.index("-m")
    except ValueError:
        return False
    return len(args) > i + 1 and args[i + 1] == "bot"


def on_colab() -> bool:
    return any(k.startswith("COLAB_") for k in os.environ)


def stop_stale_instances(wait: float = 6.0) -> list[int]:
    proc = Path("/proc")
    if not proc.is_dir():
        return []
    me, found = os.getpid(), []
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == me:
            continue
        try:
            args = [a.decode(errors="ignore") for a in (entry / "cmdline").read_bytes().split(b"\0") if a]
        except OSError:
            continue
        if is_bot_cmdline(args):
            found.append(int(entry.name))
    for pid in found:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.time() + wait
    while found and time.time() < deadline:
        found = [p for p in found if Path(f"/proc/{p}").exists()]
        if found:
            time.sleep(0.3)
    for pid in found:                       # still alive: force it
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    return found
