#!/usr/bin/env python3
import os
from pathlib import Path
import time


HEARTBEAT_PATH = Path("/var/lib/nextcloud-maintenance/heartbeat")


def maximum_age_seconds():
    interval = int(os.getenv("INTERVAL_MINUTES", "30"))
    configured = os.getenv("HEALTH_MAX_AGE_SECONDS")
    return int(configured) if configured else interval * 60 + 900


def healthy(path=HEARTBEAT_PATH, now=time.time):
    try:
        age = now() - path.stat().st_mtime
        return 0 <= age <= maximum_age_seconds()
    except (OSError, ValueError):
        return False


if __name__ == "__main__":
    raise SystemExit(0 if healthy() else 1)
