# Nextcloud Maintenance

This repository contains a Python script designed to automate essential maintenance tasks for your Nextcloud instance running in a Docker container. It uses the Docker SDK for Python to connect to your Nextcloud container and execute `occ` commands periodically, ensuring your instance stays updated and healthy.

## Features

-   **Automatic Maintenance Mode Handling:** Detects if Nextcloud is stuck in maintenance mode and disables it automatically. Includes a configurable waiting period after disabling maintenance mode to prevent conflicts.
-   **Core Upgrade Detection & Execution:** Checks for available Nextcloud core upgrades and performs the `occ upgrade` command when an update is needed.
-   **Application Updates:** Automatically updates all installed Nextcloud applications using `occ app:update --all`.
-   **Containerized Operation:** Provided with a `Dockerfile` for easy deployment as a standalone Docker container.
-   **Configurable Interval:** Runs maintenance cycles at a user-defined interval.

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

You can run the maintenance bot as a Docker container. It requires access to the Docker socket to manage the Nextcloud container.

```bash
docker run -d \
  --name nextcloud-maintenance \
  --restart always \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e NEXTCLOUD_CONTAINER="nextcloud-cron-1" \
  -e INTERVAL_MINUTES="60" \
  nextcloud-maintenance-bot
```

**Note:** Replace `nextcloud-cron-1` with the actual name of your Nextcloud Docker container.

## Environment Variables

You can configure the bot's behavior using the following environment variables:

-   `NEXTCLOUD_CONTAINER`: **(Required)** The name of your Nextcloud Docker container. Defaults to `nextcloud-cron-1` if not set.
-   `INTERVAL_MINUTES`: **(Optional)** The interval in minutes between each maintenance cycle. Defaults to `30` minutes.

## Contributing

Feel free to open issues or submit pull requests if you have suggestions or improvements.

## License

This project is open-source and available under the [MIT License](LICENSE).
