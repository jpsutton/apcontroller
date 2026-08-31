# OCI image: FastAPI backend + built SPA + OpenWrt agent payloads for SSH push.
# Tip: for reproducible/pinned builds, replace the tags below with digests
# (e.g. node:22-alpine@sha256:... and python:3.12-slim@sha256:...).
FROM node:22-alpine AS frontend
WORKDIR /build
# Copy the lockfile and use `npm ci` for a reproducible install from it.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client sshpass ca-certificates iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir "pipenv==2024.4.0"

COPY backend/Pipfile backend/Pipfile.lock ./
RUN pipenv install --system --deploy

COPY backend/ /app/
# Repo layout is share/apcontroller/* (not share/* at bundle root).
COPY share/apcontroller/ /app/share/apcontroller/
RUN test -f /app/share/apcontroller/apcontroller-agent \
    && test -f /app/share/apcontroller/apcontroller-agent-setconfig
COPY --from=frontend /build/dist /app/static

ENV APCTRL_BUNDLE_PATH=/app/share/apcontroller
ENV APCTRL_STATIC_DIR=/app/static
ENV APCTRL_CONFIG_PATH=/data/config.json
ENV APCTRL_STATE_DIR=/data
# The container binds all interfaces; container network isolation means host
# exposure is governed by the published-port mapping (see docker-compose.yml).
# Because 0.0.0.0 is non-loopback, the app fails closed unless APCTRL_API_KEY is
# set (or APCTRL_ALLOW_INSECURE_BIND=1 when the port is mapped to host loopback).
ENV APCTRL_HOST=0.0.0.0
ENV APCTRL_PORT=8080

# Run as an unprivileged user; /data (config + known_hosts + status cache) is writable by it.
RUN useradd --system --uid 10001 --create-home apctl \
    && mkdir -p /data \
    && chown -R apctl:apctl /app /data
USER apctl

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)" || exit 1
# Launch via the module so resolve_bind() enforces the fail-closed bind guard.
CMD ["python", "-m", "apctl"]
