# OCI image: FastAPI backend + built SPA + OpenWrt agent payloads for SSH push.
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client sshpass ca-certificates iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir pipenv

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

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)" || exit 1
CMD ["uvicorn", "apctl.main:app", "--host", "0.0.0.0", "--port", "8080"]
