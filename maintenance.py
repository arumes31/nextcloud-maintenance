#!/usr/bin/env python3
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import shlex
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


def non_negative_int_env(name, default):
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} must be a non-negative integer") from error
    if value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def bool_env(name, default):
    raw_value = os.getenv(name, "").strip().lower()
    if not raw_value:
        return default
    if raw_value in ("1", "true", "yes", "on"):
        return True
    if raw_value in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True)
class Settings:
    auto_disable_maintenance: bool = True
    maintenance_stale_minutes: int = 60
    auto_upgrade: bool = True
    auto_app_update: bool = True
    pre_upgrade_container: str = ""
    pre_upgrade_command: tuple = ()


def load_settings(container_name):
    pre_upgrade_command = tuple(shlex.split(os.getenv("PRE_UPGRADE_COMMAND", "")))
    pre_upgrade_container = os.getenv("PRE_UPGRADE_CONTAINER", "").strip()
    if pre_upgrade_container and not pre_upgrade_command:
        raise ValueError("PRE_UPGRADE_CONTAINER requires PRE_UPGRADE_COMMAND")
    return Settings(
        auto_disable_maintenance=bool_env("AUTO_DISABLE_MAINTENANCE", True),
        maintenance_stale_minutes=non_negative_int_env("MAINTENANCE_STALE_MINUTES", 60),
        auto_upgrade=bool_env("AUTO_UPGRADE", True),
        auto_app_update=bool_env("AUTO_APP_UPDATE", True),
        pre_upgrade_container=pre_upgrade_container or container_name,
        pre_upgrade_command=pre_upgrade_command,
    )


def run_pre_upgrade_hook(client, settings):
    try:
        container = client.containers.get(settings.pre_upgrade_container)
        result = container.exec_run(list(settings.pre_upgrade_command), stdout=True, stderr=True)
        output = result.output.decode("utf-8", errors="replace").strip()
        if result.exit_code != 0:
            log.error("pre-upgrade hook failed with exit code %s", result.exit_code)
            if output:
                log.error("%s", output)
            return False
        return True
    except Exception as error:  # Docker SDK exception subclasses vary by transport.
        log.error("cannot run pre-upgrade hook (%s)", type(error).__name__)
        return False


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


def maintenance_cycle(client, container_name, sleeper=time.sleep, settings=None, state=None,
                      clock=time.monotonic):
    settings = settings or Settings()
    state = {} if state is None else state
    log.info("%s", "=" * 70)
    log.info("Nextcloud automatic maintenance")
    log.info("Target: %s", container_name)
    log.info("%s", "=" * 70)

    maintenance_mode = run_occ(client, ["maintenance:mode"], container_name)
    if maintenance_mode is None:
        return False
    if "enabled" not in maintenance_mode.lower():
        state.pop("maintenance_since", None)
    else:
        # Maintenance mode may be set deliberately (backup, migration), so only
        # clear it once it has been observed continuously for the stale window.
        now = clock()
        enabled_seconds = now - state.setdefault("maintenance_since", now)
        if not settings.auto_disable_maintenance:
            log.warning("maintenance mode is on and AUTO_DISABLE_MAINTENANCE is off; skipping cycle")
            return True
        if enabled_seconds < settings.maintenance_stale_minutes * 60:
            log.warning(
                "maintenance mode is on for %d of %d minutes before it counts as stale; skipping cycle",
                enabled_seconds // 60, settings.maintenance_stale_minutes,
            )
            return True
        log.warning("maintenance mode is stale; turning it off")
        if run_occ(client, ["maintenance:mode", "--off"], container_name) is None:
            return False
        state.pop("maintenance_since", None)
        log.info("waiting 10 minutes after disabling maintenance mode")
        if sleeper(600):
            log.info("shutdown interrupted the maintenance delay")
            return False

    status = run_occ(client, ["status"], container_name)
    if status is None:
        return False
    if "update needed" in status.lower() or "update available" in status.lower():
        if not settings.auto_upgrade:
            log.warning("core upgrade available; AUTO_UPGRADE is off, skipping upgrade")
        else:
            if settings.pre_upgrade_command:
                log.info("running pre-upgrade hook in %s", settings.pre_upgrade_container)
                if not run_pre_upgrade_hook(client, settings):
                    return False
            log.warning("core upgrade available; running upgrade")
            if run_occ(client, ["upgrade"], container_name) is None:
                return False
    else:
        log.info("no core upgrade needed")

    if settings.auto_app_update:
        log.info("updating all apps")
        if run_occ(client, ["app:update", "--all"], container_name) is None:
            return False
    else:
        log.info("AUTO_APP_UPDATE is off; skipping app updates")

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

    try:
        settings = load_settings(container_name)
    except ValueError as error:
        log.error("%s", error)
        return 2
    state = {}

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
                if maintenance_cycle(client, container_name, stop_event.wait, settings, state):
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
