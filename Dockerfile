FROM python:3.15.2-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Keep Debian security upgrades fresh when CI restores the GHA build cache.
ARG RUNTIME_APT_REFRESH=manual
RUN printf 'Runtime package refresh: %s\n' "$RUNTIME_APT_REFRESH" \
    && groupadd --gid 10001 maintenance \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin maintenance \
    && install -d -o 10001 -g 10001 -m 0700 /var/lib/nextcloud-maintenance \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade --yes \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade "pip==26.2.1" \
    && python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip uninstall --yes pip setuptools

COPY --chown=10001:10001 maintenance.py healthcheck.py ./

USER 10001:10001

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "/app/healthcheck.py"]

CMD ["python", "/app/maintenance.py"]
