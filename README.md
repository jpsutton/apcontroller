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

3. Optional **API key** (recommended outside localhost):

   ```bash
   export APCTRL_API_KEY=change-me
   ```

   Send header `X-API-Key: change-me` on every `/api/v1/*` request. The Vite dev server does not inject this automatically: create `frontend/.env.local` with `VITE_API_KEY=change-me`.

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

## TLS (reverse proxy)

Terminate TLS in front of the app (recommended). Example **Caddy**:

```caddy
apcontroller.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

Set `APCTRL_API_KEY` and require `X-API-Key` from the proxy, or add application-level auth later.

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
| `APCTRL_BUNDLE_PATH` | Directory with `apcontroller-agent`, `apcontroller-agent-setconfig`, `scripts/` |
| `APCTRL_STATIC_DIR` | Built SPA directory (`frontend/dist`) |
| `APCTRL_API_KEY` | If set, required `X-API-Key` on `/api/v1/*` |
| `APCTRL_CORS_ORIGINS` | Comma-separated origins or `*` |

## Regenerating OpenAPI JSON

```bash
cd backend && pipenv run python -c "import json; from apctl.main import create_app; print(json.dumps(create_app().openapi(), indent=2))" > ../openapi.json
```

## License

Copyright (C) Cezary Jackiewicz and contributors of [obsy/apcontroller](https://github.com/obsy/apcontroller).  
Copyright (C) Jared Sutton for this standalone port.

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. See [LICENSE](LICENSE).
