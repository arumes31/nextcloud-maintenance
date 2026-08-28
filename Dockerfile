FROM python:3.14-slim@sha256:cae66f2ef0ec51a9891263eeee7f987dacf0a9879e8aa9353d5606e0530619a5

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --gid 10001 maintenance \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin maintenance \
    && install -d -o 10001 -g 10001 -m 0700 /var/lib/nextcloud-maintenance \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade --yes \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade "pip==26.2.1" \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY --chown=10001:10001 maintenance.py healthcheck.py ./

USER 10001:10001

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "/app/healthcheck.py"]

CMD ["python", "/app/maintenance.py"]
