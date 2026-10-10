FROM python:3.14.8-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

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
    && python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip uninstall --yes pip setuptools

COPY --chown=10001:10001 maintenance.py healthcheck.py ./

USER 10001:10001

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "/app/healthcheck.py"]

CMD ["python", "/app/maintenance.py"]
