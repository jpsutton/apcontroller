from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from apctl.deploy_service import deploy_group
from apctl.models import RootConfig
from apctl.poll_service import poll_all
from apctl.scripts_service import list_scripts
from apctl.settings import Settings, cors_list
from apctl.status_service import build_activity, build_status
from apctl.store import ConfigStore
from apctl.ssh_runner import run_cmd, scp_upload, ssh_exec
from apctl.uci_import import parse_uci_export

log = logging.getLogger("apctl")


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_store(request: Request) -> ConfigStore:
    return request.app.state.store


async def require_api_key(
    request: Request,
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    settings: Settings = request.app.state.settings
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])


@router.get("/status")
async def api_status(
    request: Request,
    include_secrets: bool = Query(False),
) -> dict:
    cfg = get_store(request).load()
    return build_status(cfg, include_secrets=include_secrets)


@router.get("/hosts/{section}/activity")
async def api_activity(request: Request, section: str) -> dict:
    cfg = get_store(request).load()
    for h in cfg.hosts:
        if h.id == section:
            return build_activity(h, cfg)
    raise HTTPException(404, "Unknown host section")


@router.get("/scripts")
async def api_scripts(request: Request) -> dict:
    scripts_dir = get_settings(request).bundle_path / "scripts"
    return list_scripts(scripts_dir)


@router.get("/config")
async def api_get_config(request: Request) -> dict:
    return get_store(request).load().model_dump(by_alias=True, mode="json")


@router.put("/config")
async def api_put_config(request: Request, body: RootConfig) -> dict:
    get_store(request).save(body)
    return {"ok": True}


@router.get("/additional-script", response_class=PlainTextResponse)
async def api_get_additional_script(request: Request) -> str:
    return get_store(request).load().additional_script


@router.put("/additional-script", response_class=PlainTextResponse)
async def api_put_additional_script(request: Request) -> str:
    body = (await request.body()).decode("utf-8")
    store = get_store(request)

    def fn(c: RootConfig) -> RootConfig:
        c.additional_script = body
        return c

    store.mutate(fn)
    return body


@router.post("/poll")
async def api_poll(request: Request) -> dict:
    settings = get_settings(request)
    cfg = get_store(request).load()
    await poll_all(cfg, bundle_path=settings.bundle_path)
    request.app.state.last_poll = time.monotonic()
    return {"ok": True}


@router.post("/groups/{group_id}/deploy")
async def api_deploy(
    request: Request,
    group_id: str,
    verbose: bool = Query(True),
) -> dict:
    settings = get_settings(request)
    cfg = get_store(request).load()
    group = next((g for g in cfg.groups if g.id == group_id), None)
    if not group:
        raise HTTPException(404, "Unknown group")
    out = await deploy_group(cfg, group, bundle_path=settings.bundle_path, verbose=verbose)
    return {"stdout": out, "stderr": ""}


@router.post("/hosts/{host_id}/ping")
async def api_ping(request: Request, host_id: str) -> dict:
    cfg = get_store(request).load()
    host = next((h for h in cfg.hosts if h.id == host_id), None)
    if not host:
        raise HTTPException(404, "Unknown host")
    code, out, err = await run_cmd(
        ["ping", "-4", "-c", "5", "-W", "1", host.ipaddr],
    )
    return {"code": code, "stdout": out, "stderr": err}


class ScriptRunResult(BaseModel):
    stdout: str = ""
    stderr: str = ""


@router.post("/hosts/{host_id}/scripts/{script_name}/run", response_model=ScriptRunResult)
async def api_run_script(request: Request, host_id: str, script_name: str) -> ScriptRunResult:
    settings = get_settings(request)
    cfg = get_store(request).load()
    host = next((h for h in cfg.hosts if h.id == host_id), None)
    if not host:
        raise HTTPException(404, "Unknown host")
    script_path = settings.bundle_path / "scripts" / script_name
    if not script_path.is_file():
        raise HTTPException(404, "Unknown script")
    use_key = host.usekeyfile
    key_path = Path(host.keyfile) if host.keyfile else None
    pw = host.password or '""'
    target = f"{host.username}@{host.ipaddr}"
    rc, _, e1 = await scp_upload(
        script_path,
        f"{target}:/tmp/{script_name}",
        port=host.port,
        use_key=use_key,
        keyfile=key_path,
        password=pw,
    )
    if rc != 0:
        return ScriptRunResult(stderr=e1 or "scp failed")
    code, o2, e2 = await ssh_exec(
        target,
        f"sh /tmp/{script_name}",
        port=host.port,
        use_key=use_key,
        keyfile=key_path,
        password=pw,
    )
    err = e2 or ""
    if err:
        err = err.replace("Caution, skipping hostkey check for ", "")
    return ScriptRunResult(stdout=o2, stderr=err)


@router.get("/host-hints")
async def api_host_hints() -> dict:
    return {}


class UciImportBody(BaseModel):
    uci_text: str = Field(..., description="Contents of `uci export apcontroller`")


@router.post("/import/uci")
async def api_import_uci(request: Request, body: UciImportBody) -> dict:
    cfg = parse_uci_export(body.uci_text)
    get_store(request).save(cfg)
    return {"ok": True, "hosts": len(cfg.hosts), "wifis": len(cfg.wifis), "groups": len(cfg.groups)}


async def _scheduler(app: FastAPI) -> None:
    await asyncio.sleep(5)
    while True:
        try:
            settings: Settings = app.state.settings
            store: ConfigStore = app.state.store
            cfg = store.load()
            interval_sec = max(60, int(cfg.global_.interval) * 60)
            now = time.monotonic()
            last = float(getattr(app.state, "last_poll", 0.0))
            if now - last >= interval_sec:
                await poll_all(cfg, bundle_path=settings.bundle_path)
                app.state.last_poll = time.monotonic()
        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("poll scheduler error")
        await asyncio.sleep(15)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.last_poll = 0.0
    app.state.poll_task = asyncio.create_task(_scheduler(app))
    yield
    app.state.poll_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await app.state.poll_task


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="AP Controller", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = ConfigStore(settings.config_path)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    app.include_router(router)

    static = settings.static_dir
    if static and static.is_dir() and (static / "index.html").is_file():
        assets = static / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/")
        async def spa_index() -> FileResponse:
            return FileResponse(static / "index.html")

    return app


app = create_app()


def run() -> None:
    import os

    import uvicorn

    uvicorn.run(
        "apctl.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        factory=False,
    )
