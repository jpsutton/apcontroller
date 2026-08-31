# AP Controller

A standalone management host for OpenWrt access points: a FastAPI service plus a React SPA, packaged as a normal Linux app or OCI container. Access points keep running the stock `apcontroller-agent` scripts (shipped under `share/apcontroller/`); only the controller itself leaves LuCI.

## Credits

This project is a standalone extraction of **[apcontroller](https://github.com/obsy/apcontroller)** by **Cezary Jackiewicz** (`cezary@eko.one.pl`). The original work is an OpenWrt/LuCI application for monitoring access points and deploying Wi‑Fi configuration without installing extra packages on the APs.

Almost everything useful here comes from that project:

- The on-AP agent scripts (`apcontroller-agent`, `apcontroller-agent-setconfig`, and the default device scripts)
- The polling, deploy, and grouping model
- The UCI configuration schema this app still imports

If you want the controller to run **on** OpenWrt itself, use Cezary’s original packages (`apcontroller` and `luci-app-apcontroller`) from [obsy/apcontroller](https://github.com/obsy/apcontroller). This repository only rehosts the management plane as a normal Linux or container app.

This standalone port is released under the same **GNU GPLv3** license as the original.

## Features

- REST API under `/api/v1/*` (OpenAPI: [openapi.json](openapi.json), live `/docs` when the server runs).
- JSON config file (no UCI on the controller): hosts, Wi‑Fi definitions, AP groups, global interval/path/columns, additional shell script text.
- Scheduled polling (same SSH/`apcontroller-agent` flow as the original `/usr/bin/apcontroller`).
- Deploy to groups (same JSON + `apcontroller-agent-setconfig` flow as `apcontroller-sendconfig`).
- Per-device ping, activity log, and script execution.

## Quick start (development)

1. **Backend** (from `backend/`):

   ```bash
   pipenv install --dev
   mkdir -p ../data
   APCTRL_CONFIG_PATH=../data/config.json pipenv run uvicorn apctl.main:app --reload --port 8080
   ```

2. **Frontend** (from `frontend/`):

   ```bash
   npm install
   npm run dev
   ```

   Vite proxies `/api` and `/health` to `http://127.0.0.1:8080`.

3. **API key / exposure.** By default the server binds `127.0.0.1` and needs no
   key for local use. Binding a non-loopback interface **requires** an API key
   (see [Security](#security)):

   ```bash
   export APCTRL_API_KEY=$(openssl rand -hex 32)
   export APCTRL_HOST=0.0.0.0   # only behind a TLS reverse proxy
   ```

   When a key is set, send header `X-API-Key: <key>` on every `/api/v1/*`
   request. The SPA itself sends no key: serve it same-origin on loopback, or
   put a reverse proxy in front that supplies auth (and injects `X-API-Key`).
   There is no `VITE_API_KEY` — a key must never be baked into the browser bundle.

## Single-process demo (API + built UI)

```bash
cd frontend && npm install && npm run build && cd ..
cd backend && pipenv install
APCTRL_STATIC_DIR=../frontend/dist APCTRL_CONFIG_PATH=../data/config.json pipenv run uvicorn apctl.main:app --port 8080
```

Open `http://127.0.0.1:8080/`.

## Container

From the repository root:

```bash
docker compose build
docker compose up
```

Mount a volume on `/data` for persistent `config.json`. Mount host SSH keys if you use key-based login and set each device’s **Key file** path to the in-container mount (for example `/ssh/id_ed25519`).

## Deploy from the published image (GHCR)

CI builds a multi-arch image (`linux/amd64`, `linux/arm64`) and publishes it to the
GitHub Container Registry on every push to `main` and every `v*` tag. You don't
need to build locally — just pull and run.

**Image:** `ghcr.io/jpsutton/apcontroller`

| Tag | Points at |
|-----|-----------|
| `latest` | newest build of the default branch |
| `vX.Y.Z`, `X.Y`, `X` | a released version tag (`v1.2.3`) |
| `sha-<short>` | a specific commit |
| `main` | the default branch |

For production, pin to a version tag or a digest (`ghcr.io/jpsutton/apcontroller@sha256:…`)
rather than `latest`.

### Pull

The package is **private by default**. Either make it public (GitHub → repo →
*Packages* → the package → *Package settings* → *Change visibility*), after which
no auth is needed to pull:

```bash
docker pull ghcr.io/jpsutton/apcontroller:latest
```

…or, to keep it private, log in first with a token that has the `read:packages`
scope:

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io -u <your-github-username> --password-stdin
docker pull ghcr.io/jpsutton/apcontroller:latest
```

### Run

The image **fails closed**: it refuses to start on a non-loopback bind unless
`APCTRL_API_KEY` is set (see [Security](#security)). Set a key for any exposed
deployment:

```bash
docker run -d --name apcontroller \
  -p 8080:8080 \
  -v apctrl-data:/data \
  -e APCTRL_API_KEY="$(openssl rand -hex 32)" \
  ghcr.io/jpsutton/apcontroller:latest
```

- `/data` holds the persistent `config.json` — keep it on a named volume or bind mount.
- Send `X-API-Key` on every `/api/v1/*` request (see
  [Environment variables](#environment-variables)); put the app behind a TLS
  reverse proxy for anything beyond localhost.
- To use SSH key-based device login, mount your key read-only and set each
  device's **Key file** path accordingly:
  `-v $HOME/.ssh:/ssh:ro` then use `/ssh/id_ed25519` in the UI.

Or with Compose, swap `build: .` for the published image:

```yaml
services:
  apcontroller:
    image: ghcr.io/jpsutton/apcontroller:latest   # or :vX.Y.Z
    # Published on host loopback only. To expose on the LAN, set APCTRL_API_KEY
    # and map "0.0.0.0:8084:8080" (then drop APCTRL_ALLOW_INSECURE_BIND).
    ports:
      - "127.0.0.1:8084:8080"
    volumes:
      - apctrl-data:/data
    environment:
      APCTRL_API_KEY: ${APCTRL_API_KEY:-}
      APCTRL_ALLOW_INSECURE_BIND: ${APCTRL_ALLOW_INSECURE_BIND:-1}
volumes:
  apctrl-data:
```

### Cutting a release

Push a semver tag; the workflow publishes the matching `vX.Y.Z` / `X.Y` / `X`
image tags:

```bash
git tag v1.0.0
git push origin v1.0.0
```

## Security

This controller holds AP SSH credentials and Wi-Fi PSKs and can run scripts as
root on every managed AP, so treat it as sensitive infrastructure.

- **Fail-closed bind.** Default bind is `127.0.0.1`. Binding a non-loopback
  interface (e.g. `APCTRL_HOST=0.0.0.0`) with **no** `APCTRL_API_KEY` set is
  refused at startup. Set a strong key, or set `APCTRL_ALLOW_INSECURE_BIND=1`
  only when exposure is controlled externally (e.g. a host-loopback container
  port map).
- **Transport.** The app speaks plain HTTP. For any non-loopback access put it
  behind a TLS-terminating reverse proxy — otherwise the API key and all
  secrets (`GET /api/v1/config`, `GET /api/v1/status?include_secrets=true`
  return plaintext passwords/PSKs) travel the network in the clear. Example
  **Caddy**:

  ```caddy
  apcontroller.example.com {
      reverse_proxy 127.0.0.1:8080
      # Optionally add auth here and inject the key upstream:
      # reverse_proxy 127.0.0.1:8080 { header_up X-API-Key {env.APCTRL_API_KEY} }
  }
  ```

- **CORS** is off by default (the SPA is served same-origin). Set
  `APCTRL_CORS_ORIGINS` to explicit origins only if you serve the UI
  cross-origin; a wildcard is never combined with credentials.
- **SSH host keys** are pinned on first contact (`accept-new` TOFU) in
  `<state_dir>/known_hosts`; a later key change is refused. Override with
  `APCTRL_SSH_STRICT` (`yes` = strict, `no` = disabled, lab only). If an AP is
  reflashed, remove its line from `known_hosts`.
- **Input validation.** Host/Wi-Fi/VLAN config fields are validated (IP/hostname,
  identifier, and length/charset rules) so a config value cannot be turned into
  an SSH/ping argument or path-traversal payload.
- Config and on-disk artifacts are written `0600`; run the service as an
  unprivileged user (the container and systemd unit already do).

## Migrating from UCI (`uci export apcontroller`)

On the OpenWrt box that currently holds config:

```sh
uci export apcontroller
```

Pipe the output into the API:

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/import/uci \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $APCTRL_API_KEY" \
  -d "{\"uci_text\": $(jq -Rs . < uci-export.txt)}"
```

Or convert offline:

```bash
cd backend && pipenv run python -m apctl.uci_import < uci-export.txt > ../data/config.json
```

(`uci_import` prints JSON to stdout.)

## systemd

See [deploy/apcontroller-standalone.service](deploy/apcontroller-standalone.service). Adjust `User`, paths, and use `pipenv run uvicorn` from the checked-out `backend` tree, or install into a venv and point `ExecStart` at that `uvicorn`.

## Environment variables

| Variable | Meaning |
|----------|---------|
| `APCTRL_CONFIG_PATH` | JSON config file (default `./data/config.json` in dev) |
| `APCTRL_STATE_DIR` | Status cache / activity logs / SSH `known_hosts` (default: config dir) |
| `APCTRL_BUNDLE_PATH` | Directory with `apcontroller-agent`, `apcontroller-agent-setconfig`, `scripts/` |
| `APCTRL_STATIC_DIR` | Built SPA directory (`frontend/dist`) |
| `APCTRL_HOST` | Bind address (default `127.0.0.1`) |
| `APCTRL_PORT` | Bind port (default `8080`) |
| `APCTRL_API_KEY` | If set, required `X-API-Key` on `/api/v1/*`. Required to bind non-loopback |
| `APCTRL_ALLOW_INSECURE_BIND` | Set `1` to permit a non-loopback bind with no key (exposure controlled externally) |
| `APCTRL_SSH_STRICT` | SSH host-key policy: `accept-new` (default), `yes`, or `no` |
| `APCTRL_CORS_ORIGINS` | Comma-separated origins (empty = none). Wildcard allowed only without credentials |

## Regenerating OpenAPI JSON

```bash
cd backend && pipenv run python -c "import json; from apctl.main import create_app; print(json.dumps(create_app().openapi(), indent=2))" > ../openapi.json
```

## License

Copyright (C) Cezary Jackiewicz and contributors of [obsy/apcontroller](https://github.com/obsy/apcontroller).  
Copyright (C) Jared Sutton for this standalone port.

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. See [LICENSE](LICENSE).
