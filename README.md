# Nextcloud Maintenance

This repository contains a Python script designed to automate essential maintenance tasks for your Nextcloud instance running in a Docker container. It uses the Docker SDK for Python to connect to your Nextcloud container and execute `occ` commands periodically, ensuring your instance stays updated and healthy.

## Features

-   **Automatic Maintenance Mode Handling:** Detects if Nextcloud is stuck in maintenance mode and disables it automatically. Includes a configurable waiting period after disabling maintenance mode to prevent conflicts.
-   **Core Upgrade Detection & Execution:** Checks for available Nextcloud core upgrades and performs the `occ upgrade` command when an update is needed.
-   **Application Updates:** Automatically updates all installed Nextcloud applications using `occ app:update --all`.
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
-   The maintenance bot container needs access to the Docker socket to communicate with other containers.

### Build the Docker Image

Navigate to the root of this repository and build the Docker image:

```bash
docker build -t nextcloud-maintenance .
```

### Run the Docker Container

You can run the maintenance bot as a Docker container. It requires access to the Docker socket to manage the Nextcloud container. The socket is root-equivalent host control even though the process itself runs as a non-root user, so do not expose this container to untrusted users or networks.

```bash
docker run -d \
  --name nextcloud-maintenance \
  --restart always \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --group-add "$(stat -c '%g' /var/run/docker.sock)" \
  --tmpfs /var/lib/nextcloud-maintenance:rw,noexec,nosuid,nodev,uid=10001,gid=10001,mode=0700 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e NEXTCLOUD_CONTAINER="nextcloud-cron-1" \
  -e INTERVAL_MINUTES="60" \
  ghcr.io/arumes31/nextcloud-maintenance:latest
```

### Docker Compose

Alternatively, you can use Docker Compose to manage the service:

```yaml
services:
  nextcloud-maintenance:
    image: ghcr.io/arumes31/nextcloud-maintenance:latest
    container_name: nextcloud-maintenance
    restart: always
    read_only: true
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    group_add:
      - "${DOCKER_GID}"
    tmpfs:
      - /var/lib/nextcloud-maintenance:rw,noexec,nosuid,nodev,uid=10001,gid=10001,mode=0700
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - NEXTCLOUD_CONTAINER=nextcloud-cron-1
      - INTERVAL_MINUTES=60
```

**Note:** Replace `nextcloud-cron-1` with the actual name of your Nextcloud Docker container.
Set `DOCKER_GID` before starting Compose, for example
`export DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)`, so UID 10001 can access
the mounted socket without running the process as root.

## Environment Variables

You can configure the bot's behavior using the following environment variables:

-   `NEXTCLOUD_CONTAINER`: **(Optional)** The name of your Nextcloud Docker container. Defaults to `nextcloud-cron-1`.
-   `INTERVAL_MINUTES`: **(Optional)** The interval in minutes between each maintenance cycle. Defaults to `30` minutes.
-   `HEALTH_MAX_AGE_SECONDS`: **(Optional)** Maximum heartbeat age. Defaults to the configured interval plus 15 minutes.

`INTERVAL_MINUTES` must be a positive integer. Docker API requests use a
30-second client timeout, and `occ` is executed as an argument vector rather
than through a shell.

## Contributing

Feel free to open issues or submit pull requests if you have suggestions or improvements.

## License

This project is open-source and available under the [MIT License](LICENSE).
