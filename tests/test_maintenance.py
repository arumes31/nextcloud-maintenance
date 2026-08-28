import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import healthcheck
import maintenance


class Result:
    def __init__(self, output="", exit_code=0):
        self.output = output.encode()
        self.exit_code = exit_code


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
            Result("Update needed"),
            Result(),
            Result("updated"),
        ])
        sleeps = []

        self.assertTrue(maintenance.maintenance_cycle(Client(container), "nextcloud", sleeps.append))
        self.assertEqual(sleeps, [600])
        self.assertEqual(
            [entry[0][2:] for entry in container.commands],
            [
                ["maintenance:mode"],
                ["maintenance:mode", "--off"],
                ["status"],
                ["upgrade"],
                ["app:update", "--all"],
            ],
        )
        for command, kwargs in container.commands:
            self.assertIsInstance(command, list)
            self.assertEqual(kwargs["user"], "www-data")

    def test_no_upgrade_path(self):
        container = Container([Result("disabled"), Result("installed: true"), Result("updated")])

        self.assertTrue(maintenance.maintenance_cycle(Client(container), "nextcloud"))
        self.assertEqual(
            [entry[0][2:] for entry in container.commands],
            [["maintenance:mode"], ["status"], ["app:update", "--all"]],
        )

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
