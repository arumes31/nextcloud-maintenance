import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import healthcheck
import maintenance


class Result:
    def __init__(self, output="", exit_code=0, stderr=""):
        # exec_run(demux=True) returns (stdout, stderr), with None for an empty stream.
        self.output = (output.encode() or None, stderr.encode() or None)
        self.exit_code = exit_code


UPGRADE = '{"installed":true,"maintenance":false,"needsDbUpgrade":true}'
CURRENT = '{"installed":true,"maintenance":false,"needsDbUpgrade":false}'
STATUS = ["status", "--output=json"]


class Container:
    def __init__(self, results):
        self.results = iter(results)
        self.commands = []

    def exec_run(self, command, **kwargs):
        self.commands.append((command, kwargs))
        return next(self.results)


class Client:
    def __init__(self, container):
        self.container = container
        self.containers = mock.Mock()
        self.containers.get.return_value = container


class MaintenanceTests(unittest.TestCase):
    def test_enabled_maintenance_and_upgrade(self):
        container = Container([
            Result("Maintenance mode is enabled"),
            Result(),
            Result(UPGRADE),
            Result(),
            Result("updated"),
        ])
        sleeps = []

        settings = maintenance.Settings(maintenance_stale_minutes=0)

        self.assertTrue(maintenance.maintenance_cycle(
            Client(container), "nextcloud", sleeps.append, settings,
        ))
        self.assertEqual(sleeps, [600])
        self.assertEqual(
            [entry[0][2:] for entry in container.commands],
            [
                ["maintenance:mode"],
                ["maintenance:mode", "--off"],
                STATUS,
                ["upgrade"],
                ["app:update", "--all"],
            ],
        )
        for command, kwargs in container.commands:
            self.assertIsInstance(command, list)
            self.assertEqual(kwargs["user"], "www-data")

    def test_no_upgrade_path(self):
        container = Container([Result("disabled"), Result(CURRENT), Result("updated")])

        self.assertTrue(maintenance.maintenance_cycle(Client(container), "nextcloud"))
        self.assertEqual(
            [entry[0][2:] for entry in container.commands],
            [["maintenance:mode"], STATUS, ["app:update", "--all"]],
        )

    def test_shutdown_during_maintenance_delay_stops_commands(self):
        container = Container([
            Result("Maintenance mode is enabled"), Result(),
            Result(UPGRADE), Result(), Result("updated"),
        ])
        wait_for_shutdown = mock.Mock(return_value=True)

        self.assertFalse(maintenance.maintenance_cycle(
            Client(container), "nextcloud", wait_for_shutdown,
            maintenance.Settings(maintenance_stale_minutes=0),
        ))
        wait_for_shutdown.assert_called_once_with(600)
        self.assertEqual(
            [entry[0][2:] for entry in container.commands],
            [["maintenance:mode"], ["maintenance:mode", "--off"]],
        )

    def test_maintenance_mode_disabled_only_after_stale_window(self):
        container = Container([
            Result("Maintenance mode is enabled"),
            Result("Maintenance mode is enabled"),
            Result(), Result(CURRENT), Result("updated"),
        ])
        client = Client(container)
        state = {}
        now = [1000.0]
        sleeps = []

        def cycle():
            return maintenance.maintenance_cycle(
                client, "nextcloud", sleeps.append, maintenance.Settings(), state, lambda: now[0],
            )

        self.assertTrue(cycle())
        self.assertEqual([entry[0][2:] for entry in container.commands], [["maintenance:mode"]])
        now[0] += 3600
        self.assertTrue(cycle())
        self.assertEqual(
            [entry[0][2:] for entry in container.commands][1:],
            [["maintenance:mode"], ["maintenance:mode", "--off"], STATUS, ["app:update", "--all"]],
        )
        self.assertEqual(sleeps, [600])
        self.assertNotIn("maintenance_since", state)

    def test_stale_window_resets_when_maintenance_mode_clears(self):
        container = Container([
            Result("Maintenance mode is enabled"),
            Result("disabled"), Result(CURRENT), Result("updated"),
            Result("Maintenance mode is enabled"),
        ])
        client = Client(container)
        state = {}
        now = [0.0]

        def cycle():
            return maintenance.maintenance_cycle(
                client, "nextcloud", settings=maintenance.Settings(), state=state, clock=lambda: now[0],
            )

        cycle()
        now[0] += 1800
        cycle()
        now[0] += 1800
        self.assertTrue(cycle())
        self.assertEqual(container.commands[-1][0][2:], ["maintenance:mode"])
        self.assertEqual(state["maintenance_since"], 3600)

    def test_auto_disable_maintenance_off_never_disables(self):
        container = Container([Result("Maintenance mode is enabled")])
        settings = maintenance.Settings(auto_disable_maintenance=False, maintenance_stale_minutes=0)

        self.assertTrue(maintenance.maintenance_cycle(Client(container), "nextcloud", settings=settings))
        self.assertEqual([entry[0][2:] for entry in container.commands], [["maintenance:mode"]])

    def test_auto_upgrade_and_app_update_off(self):
        container = Container([Result("disabled"), Result(UPGRADE)])
        settings = maintenance.Settings(auto_upgrade=False, auto_app_update=False)

        self.assertTrue(maintenance.maintenance_cycle(Client(container), "nextcloud", settings=settings))
        self.assertEqual(
            [entry[0][2:] for entry in container.commands],
            [["maintenance:mode"], STATUS],
        )

    def test_pre_upgrade_hook_runs_before_upgrade(self):
        container = Container([
            Result("disabled"), Result(UPGRADE), Result("backup ok"), Result(), Result("updated"),
        ])
        settings = maintenance.Settings(
            pre_upgrade_container="nextcloud", pre_upgrade_command=("/backup.sh", "--now"),
        )

        self.assertTrue(maintenance.maintenance_cycle(Client(container), "nextcloud", settings=settings))
        self.assertEqual(container.commands[2][0], ["/backup.sh", "--now"])
        self.assertEqual(container.commands[3][0][2:], ["upgrade"])

    def test_failed_pre_upgrade_hook_blocks_upgrade(self):
        container = Container([Result("disabled"), Result(UPGRADE), Result("disk full", exit_code=1)])
        settings = maintenance.Settings(
            pre_upgrade_container="nextcloud", pre_upgrade_command=("/backup.sh",),
        )

        self.assertFalse(maintenance.maintenance_cycle(Client(container), "nextcloud", settings=settings))
        self.assertEqual(len(container.commands), 3)

    def test_load_settings(self):
        environment = {
            "AUTO_DISABLE_MAINTENANCE": "false",
            "MAINTENANCE_STALE_MINUTES": "0",
            "AUTO_UPGRADE": "no",
            "PRE_UPGRADE_COMMAND": "/usr/local/bin/backup --label 'pre upgrade'",
        }
        with mock.patch.dict(os.environ, environment, clear=True):
            settings = maintenance.load_settings("nextcloud")
        self.assertFalse(settings.auto_disable_maintenance)
        self.assertEqual(settings.maintenance_stale_minutes, 0)
        self.assertFalse(settings.auto_upgrade)
        self.assertTrue(settings.auto_app_update)
        self.assertEqual(settings.pre_upgrade_container, "nextcloud")
        self.assertEqual(settings.pre_upgrade_command, ("/usr/local/bin/backup", "--label", "pre upgrade"))

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(maintenance.load_settings("nextcloud").maintenance_stale_minutes, 60)
        with mock.patch.dict(os.environ, {"AUTO_UPGRADE": "maybe"}, clear=True):
            with self.assertRaises(ValueError):
                maintenance.load_settings("nextcloud")
        with mock.patch.dict(os.environ, {"PRE_UPGRADE_CONTAINER": "backup"}, clear=True):
            with self.assertRaises(ValueError):
                maintenance.load_settings("nextcloud")

    def test_stderr_text_cannot_trigger_upgrade(self):
        container = Container([
            Result("disabled"),
            Result(CURRENT, stderr="update needed / update available"),
            Result("updated"),
        ])
        settings = maintenance.Settings(pre_upgrade_container="nextcloud", pre_upgrade_command=("/backup.sh",))

        self.assertTrue(maintenance.maintenance_cycle(Client(container), "nextcloud", settings=settings))
        self.assertEqual(
            [entry[0][2:] for entry in container.commands],
            [["maintenance:mode"], STATUS, ["app:update", "--all"]],
        )

    def test_free_text_status_is_not_trusted(self):
        for output in ["Update needed", "update available", '{"needsDbUpgrade":"yes"}', ""]:
            with self.subTest(output=output):
                container = Container([Result("disabled"), Result(output)])
                self.assertFalse(maintenance.maintenance_cycle(Client(container), "nextcloud"))
                self.assertEqual(len(container.commands), 2)

    def test_status_json_after_warning_lines(self):
        self.assertTrue(maintenance.needs_db_upgrade("PHP Warning: something\n" + UPGRADE))
        self.assertFalse(maintenance.needs_db_upgrade(CURRENT + "\n"))

    def test_pre_upgrade_hook_user_and_output_not_logged_at_info(self):
        container = Container([Result("secret-token", exit_code=1, stderr="secret-error")])
        settings = maintenance.Settings(
            pre_upgrade_container="nextcloud", pre_upgrade_command=("/backup.sh",), pre_upgrade_user="backup",
        )
        with self.assertLogs(maintenance.log, level="INFO") as logs:
            self.assertFalse(maintenance.run_pre_upgrade_hook(Client(container), settings))
        self.assertNotIn("secret", " ".join(logs.output))
        self.assertEqual(container.commands[0][1]["user"], "backup")
        with mock.patch.dict(os.environ, {"PRE_UPGRADE_COMMAND": "/b", "PRE_UPGRADE_USER": " www-data "}, clear=True):
            self.assertEqual(maintenance.load_settings("nextcloud").pre_upgrade_user, "www-data")

    def test_occ_failure_stops_cycle(self):
        container = Container([Result("permission denied", exit_code=1)])
        self.assertFalse(maintenance.maintenance_cycle(Client(container), "nextcloud"))
        self.assertEqual(len(container.commands), 1)

    def test_positive_interval_validation(self):
        with mock.patch.dict(os.environ, {"INTERVAL_MINUTES": "0"}):
            with self.assertRaises(ValueError):
                maintenance.positive_int_env("INTERVAL_MINUTES", 30)
        with mock.patch.dict(os.environ, {"INTERVAL_MINUTES": "15"}):
            self.assertEqual(maintenance.positive_int_env("INTERVAL_MINUTES", 30), 15)

    def test_heartbeat_age(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "heartbeat"
            path.touch()
            with mock.patch.dict(os.environ, {"HEALTH_MAX_AGE_SECONDS": "60"}):
                self.assertTrue(healthcheck.healthy(path, now=lambda: path.stat().st_mtime + 59))
                self.assertFalse(healthcheck.healthy(path, now=lambda: path.stat().st_mtime + 61))


if __name__ == "__main__":
    unittest.main()
