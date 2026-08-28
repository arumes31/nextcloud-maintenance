#!/usr/bin/env python3
import logging
import os
from pathlib import Path
import signal
import sys
import threading
import time

import docker


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

NEXTCLOUD_PATH = "/var/www/html"
HEARTBEAT_PATH = Path("/var/lib/nextcloud-maintenance/heartbeat")


def positive_int_env(name, default):
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} must be a positive integer") from error
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def run_occ(client, command, container_name):
    try:
        container = client.containers.get(container_name)
        result = container.exec_run(
            ["php", f"{NEXTCLOUD_PATH}/occ", *command],
            user="www-data",
            stdout=True,
            stderr=True,
        )
        output = result.output.decode("utf-8", errors="replace").strip()
        if result.exit_code != 0:
            log.error("occ command failed with exit code %s: %s", result.exit_code, " ".join(command))
            if output:
                log.error("%s", output)
            return None
        return output
    except Exception as error:  # Docker SDK exception subclasses vary by transport.
        log.error("cannot reach Nextcloud container (%s)", type(error).__name__)
        return None


def maintenance_cycle(client, container_name, sleeper=time.sleep):
    log.info("%s", "=" * 70)
    log.info("Nextcloud automatic maintenance")
    log.info("Target: %s", container_name)
    log.info("%s", "=" * 70)

    maintenance_mode = run_occ(client, ["maintenance:mode"], container_name)
    if maintenance_mode is None:
        return False
    if "enabled" in maintenance_mode.lower():
        log.warning("maintenance mode is on; turning it off")
        if run_occ(client, ["maintenance:mode", "--off"], container_name) is None:
            return False
        log.info("waiting 10 minutes after disabling maintenance mode")
        sleeper(600)

    status = run_occ(client, ["status"], container_name)
    if status is None:
        return False
    if "update needed" in status.lower() or "update available" in status.lower():
        log.warning("core upgrade available; running upgrade")
        if run_occ(client, ["upgrade"], container_name) is None:
            return False
    else:
        log.info("no core upgrade needed")

    log.info("updating all apps")
    if run_occ(client, ["app:update", "--all"], container_name) is None:
        return False

    log.info("maintenance finished successfully")
    return True


def write_heartbeat(path=HEARTBEAT_PATH):
    path.touch(mode=0o600)


def main():
    try:
        interval_minutes = positive_int_env("INTERVAL_MINUTES", 30)
    except ValueError as error:
        log.error("%s", error)
        return 2

    container_name = os.getenv("NEXTCLOUD_CONTAINER", "nextcloud-cron-1").strip()
    if not container_name:
        log.error("NEXTCLOUD_CONTAINER must not be empty")
        return 2

    stop_event = threading.Event()

    def stop(_signum, _frame):
        log.info("shutdown requested")
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    try:
        client = docker.from_env(timeout=30)
        client.ping()
    except Exception as error:
        log.error("cannot connect to the Docker API (%s)", type(error).__name__)
        return 1

    log.info("Nextcloud maintenance service started; interval=%s minutes", interval_minutes)
    write_heartbeat()
    try:
        while not stop_event.is_set():
            try:
                if maintenance_cycle(client, container_name):
                    write_heartbeat()
            except Exception:
                log.exception("unexpected maintenance error")

            if not stop_event.is_set():
                log.info("sleeping %s minutes", interval_minutes)
                stop_event.wait(interval_minutes * 60)
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
