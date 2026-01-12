# ─────────────────────────────────────────────────────────────
# Nextcloud Maintenance Container – Python SDK Only
# Uses Debian's native docker-cli (no official Docker repo needed)
# ─────────────────────────────────────────────────────────────
FROM python:3.14-slim

# Install Debian's native docker-cli (available in trixie repos)
# No apt-transport-https or extra repos – keeps it tiny
RUN apt-get update && \
    apt-get install -y --no-install-recommends docker-cli && \
    rm -rf /var/lib/apt/lists/*

# App setup
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY maintenance.py .

# Run as root (full socket access – safe for internal tool)
CMD ["python", "/app/maintenance.py"]
