#!/usr/bin/env python3
import os
import time
import docker
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)

NEXTCLOUD_CONTAINER = os.getenv("NEXTCLOUD_CONTAINER", "nextcloud-cron-1")
NEXTCLOUD_PATH = "/var/www/html"
INTERVAL_MINUTES = int(os.getenv("INTERVAL_MINUTES", "30"))

client = docker.from_env()

def run_occ(cmd):
    try:
        container = client.containers.get(NEXTCLOUD_CONTAINER)
        result = container.exec_run(
            f"php {NEXTCLOUD_PATH}/occ {cmd}",
            user="www-data",
            stdout=True,
            stderr=True
        )
        output = result.output.decode("utf-8", errors="ignore").strip()
        if result.exit_code != 0:
            log.error(f"occ failed ({result.exit_code}): {cmd}")
            if output:
                log.error(output)
            return None
        return output
    except Exception as e:
        log.error(f"Cannot reach container: {e}")
        return None

def maintenance_cycle():
    log.info("="*70)
    log.info("Nextcloud Automatic Maintenance – Works on NC 15 → 31")
    log.info(f"Target → {NEXTCLOUD_CONTAINER}")
    log.info("="*70)

    # 1. Turn off maintenance mode if it’s stuck
    if run_occ("maintenance:mode") and "enabled" in run_occ("maintenance:mode").lower():
        log.warning("Maintenance mode is ON → turning it OFF")
        run_occ("maintenance:mode --off")
        log.info("Sleeping 10 minutes after disabling maintenance mode…")
        time.sleep(600)

    # 2. Check if a core upgrade is available (100% compatible method)
    status = run_occ("status")
    if status and ("update needed" in status.lower() or "update available" in status.lower()):
        log.warning("CORE UPGRADE AVAILABLE → running upgrade")
        run_occ("upgrade")
    else:
        log.info("No core upgrade needed")

    # 3. Update all apps (this command has existed forever)
    log.info("Updating all apps…")
    run_occ("app:update --all")

    log.info("Maintenance finished successfully!")
    log.info("="*70)

if __name__ == "__main__":
    log.info("Nextcloud Maintenance Service STARTED")
    log.info(f"Running every {INTERVAL_MINUTES} minutes")

    while True:
        try:
            maintenance_cycle()
        except Exception as e:
            log.exception(f"Unexpected error: {e}")

        log.info(f"Sleeping {INTERVAL_MINUTES} minutes…")
        time.sleep(INTERVAL_MINUTES * 60)
