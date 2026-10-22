# Nextcloud Maintenance

This repository contains a Python script designed to automate essential maintenance tasks for your Nextcloud instance running in a Docker container. It uses the Docker SDK for Python to connect to your Nextcloud container and execute `occ` commands periodically, ensuring your instance stays updated and healthy.

## Features

-   **Stale Maintenance Mode Handling:** Disables maintenance mode only after it has been observed continuously for `MAINTENANCE_STALE_MINUTES` (default 60), so a deliberate maintenance window (backup, migration) is not interrupted. While maintenance mode is on, the cycle is skipped. Can be turned off entirely with `AUTO_DISABLE_MAINTENANCE=false`.
-   **Core Upgrade Detection & Execution:** Checks for available Nextcloud core upgrades and performs the `occ upgrade` command when an update is needed. An optional pre-upgrade hook (for example a backup) must succeed first. Can be turned off with `AUTO_UPGRADE=false`.
-   **Application Updates:** Automatically updates all installed Nextcloud applications using `occ app:update --all`. Can be turned off with `AUTO_APP_UPDATE=false`.
-   **Containerized Operation:** Provided with a `Dockerfile` for easy deployment as a standalone Docker container.
-   **Configurable Interval:** Runs maintenance cycles at a user-defined interval.
-   **Health and Shutdown Support:** Publishes a heartbeat health check and handles `SIGTERM` without waiting for the full maintenance interval.
-   **Least-Privilege Runtime:** Runs as UID/GID `10001` with no Docker CLI in the image.

## How It Works

The script operates by:
1.  Connecting to the Docker daemon to identify the specified Nextcloud container.
2.  Periodically executing `php /var/www/html/occ <command>` within the Nextcloud container as the `www-data` user.
3.  Logging all actions and outputs to the console.

## Installation and Setup

### Prerequisites

-   Docker installed and running on your host system.
-   An existing Nextcloud Docker container.
-   The maintenance bot container needs access to the Docker API to run `occ` in the Nextcloud container. Access to the Docker socket is equivalent to root on the host, so prefer the filtering socket proxy shown below over mounting the socket directly.

### Build the Docker Image

Navigate to the root of this repository and build the Docker image:

```bash
docker build -t nextcloud-maintenance .
```

### Docker Compose (recommended: filtering socket proxy)

The bot only needs to inspect containers and create/start `exec` sessions.
Instead of mounting `/var/run/docker.sock` into the bot, run
[`tecnativa/docker-socket-proxy`](https://github.com/Tecnativa/docker-socket-proxy)
on an internal network and point the bot at it with `DOCKER_HOST`. The proxy
denies image, volume, network, swarm, system and other API sections:

```yaml
services:
  docker-socket-proxy:
    # Pin the proxy by digest as well in production.
    image: tecnativa/docker-socket-proxy:latest
    restart: always
    read_only: true
    tmpfs:
      - /run
    environment:
      - CONTAINERS=1
      - EXEC=1
      - POST=1
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - docker-api

  nextcloud-maintenance:
    # Pin by digest, e.g. ghcr.io/arumes31/nextcloud-maintenance@sha256:<digest>
    image: ghcr.io/arumes31/nextcloud-maintenance:latest
    container_name: nextcloud-maintenance
    restart: always
    read_only: true
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    tmpfs:
      - /var/lib/nextcloud-maintenance:rw,noexec,nosuid,nodev,uid=10001,gid=10001,mode=0700
    depends_on:
      - docker-socket-proxy
    environment:
      - DOCKER_HOST=tcp://docker-socket-proxy:2375
      - NEXTCLOUD_CONTAINER=nextcloud-cron-1
      - INTERVAL_MINUTES=60
    networks:
      - docker-api

networks:
  docker-api:
    internal: true
```

The proxy narrows the reachable API but is not a full sandbox: `CONTAINERS=1`
with `POST=1` still allows container lifecycle calls, and `exec` can run any
command in any container. Keep the proxy on an internal network that only the
bot can reach. If you do not want any Docker API access at all, run
`php occ maintenance:mode`, `php occ upgrade` and `php occ app:update --all`
from a cron job inside the Nextcloud stack instead of using this bot.

### Direct socket mount (not recommended)

Mounting the socket directly also works. The socket is root-equivalent host
control even though the process itself runs as a non-root user, so any
compromise of this container or its dependencies is a host compromise. Do not
expose this container to untrusted users or networks.

```bash
docker run -d   --name nextcloud-maintenance   --restart always   --read-only   --cap-drop ALL   --security-opt no-new-privileges:true   --group-add "$(stat -c '%g' /var/run/docker.sock)"   --tmpfs /var/lib/nextcloud-maintenance:rw,noexec,nosuid,nodev,uid=10001,gid=10001,mode=0700   -v /var/run/docker.sock:/var/run/docker.sock   -e NEXTCLOUD_CONTAINER="nextcloud-cron-1"   -e INTERVAL_MINUTES="60"   ghcr.io/arumes31/nextcloud-maintenance@sha256:<digest>
```

**Note:** Replace `nextcloud-cron-1` with the actual name of your Nextcloud Docker container.
With a direct socket mount, add the socket's group (`--group-add`, or
`group_add: ["${DOCKER_GID}"]` in Compose with
`export DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)`) so UID 10001 can
access it without running the process as root.

### Image tags

The daily build pushes a `candidate` tag, scans that exact digest with Trivy
for fixable HIGH/CRITICAL vulnerabilities, and only then points `latest`, the
commit SHA tag and the date tag (`DDMMYYYY`) at the scanned digest. Pin the
image by digest (`@sha256:...`) in production and update it deliberately
rather than following `latest`.

## Environment Variables

You can configure the bot's behavior using the following environment variables:

-   `NEXTCLOUD_CONTAINER`: **(Optional)** The name of your Nextcloud Docker container. Defaults to `nextcloud-cron-1`.
-   `INTERVAL_MINUTES`: **(Optional)** The interval in minutes between each maintenance cycle. Defaults to `30` minutes.
-   `HEALTH_MAX_AGE_SECONDS`: **(Optional)** Maximum heartbeat age. Defaults to the configured interval plus 15 minutes.
-   `DOCKER_HOST`: **(Optional)** Docker API endpoint, e.g. `tcp://docker-socket-proxy:2375`. Defaults to the local socket.
-   `AUTO_DISABLE_MAINTENANCE`: **(Optional)** Disable maintenance mode once it is stale. Defaults to `true`. Set to `false` to never touch maintenance mode; cycles are then skipped while it is on.
-   `MAINTENANCE_STALE_MINUTES`: **(Optional)** How long maintenance mode must be observed continuously before it is disabled. Defaults to `60`; `0` restores the previous behaviour of disabling it immediately. The window is measured from the first cycle that sees it enabled, so the effective delay is rounded up to the next cycle.
-   `AUTO_UPGRADE`: **(Optional)** Run `occ upgrade` when a core upgrade is needed. Defaults to `true`.
-   `AUTO_APP_UPDATE`: **(Optional)** Run `occ app:update --all` each cycle. Defaults to `true`.
-   `PRE_UPGRADE_COMMAND`: **(Optional)** Command run via `docker exec` before `occ upgrade`, for example a backup script. It is split shell-style into an argument vector (no shell). If it exits non-zero, the upgrade and the rest of the cycle are skipped.
-   `PRE_UPGRADE_CONTAINER`: **(Optional)** Container in which `PRE_UPGRADE_COMMAND` runs. Defaults to `NEXTCLOUD_CONTAINER`. Requires `PRE_UPGRADE_COMMAND`.

`INTERVAL_MINUTES` must be a positive integer and `MAINTENANCE_STALE_MINUTES` a
non-negative integer; boolean flags accept `true/false`, `yes/no`, `on/off` or
`1/0`. Docker API requests use a
30-second client timeout, and `occ` is executed as an argument vector rather
than through a shell.

## Contributing

Feel free to open issues or submit pull requests if you have suggestions or improvements.

## License

This project is open-source and available under the [MIT License](LICENSE).
