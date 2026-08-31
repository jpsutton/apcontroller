from __future__ import annotations

import asyncio
import contextlib
import hmac
import ipaddress
import logging
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from apctl.deploy_service import deploy_group
from apctl.models import RootConfig
from apctl.poll_service import poll_all
from apctl.scripts_service import list_scripts
from apctl.settings import Settings, cors_list
from apctl.ssh_runner import SshConfig
from apctl.status_service import build_activity, build_status
from apctl.store import ConfigStore
from apctl.ssh_runner import run_cmd, scp_upload, ssh_exec
from apctl.uci_import import parse_uci_export
from apctl.validation import safe_ident

log = logging.getLogger("apctl")

# Reject request bodies larger than this (memory-exhaustion guard).
MAX_BODY_BYTES = 1 * 1024 * 1024


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_store(request: Request) -> ConfigStore:
    return request.app.state.store


def _state_dir(settings: Settings) -> Path:
    return settings.resolved_state_dir()


def _ssh_cfg(settings: Settings) -> SshConfig:
    return SshConfig(
        strict=settings.ssh_strict,
        known_hosts=settings.resolved_state_dir() / "known_hosts",
    )


def resolve_bind(settings: Settings) -> tuple[str, int]:
    """Return (host, port) to bind, failing closed on unsafe exposure.

    A non-loopback bind with no API key and no explicit opt-out is refused so
    the service never comes up unauthenticated on a reachable interface.
    """
    host = settings.host
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.lower() in ("localhost", "localhost.localdomain")
    if not loopback and not settings.api_key and not settings.allow_insecure_bind:
        raise RuntimeError(
            f"Refusing to bind {host}:{settings.port} with no APCTRL_API_KEY set. "
            "Set APCTRL_API_KEY, bind 127.0.0.1, or (only if exposure is controlled "
            "externally) set APCTRL_ALLOW_INSECURE_BIND=1."
        )
    return host, settings.port


async def require_api_key(
    request: Request,
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    settings: Settings = request.app.state.settings
    if settings.api_key and not hmac.compare_digest(x_api_key or "", settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])


@router.get("/status")
async def api_status(
    request: Request,
    include_secrets: bool = Query(False),
) -> dict:
    settings = get_settings(request)
    cfg = get_store(request).load()
    return build_status(cfg, state_dir=_state_dir(settings), include_secrets=include_secrets)


@router.get("/hosts/{section}/activity")
async def api_activity(request: Request, section: str) -> dict:
    settings = get_settings(request)
    cfg = get_store(request).load()
    for h in cfg.hosts:
        if h.id == section:
            return build_activity(h, state_dir=_state_dir(settings))
    raise HTTPException(404, "Unknown host section")


@router.get("/scripts")
async def api_scripts(request: Request) -> dict:
    scripts_dir = get_settings(request).bundle_path / "scripts"
    return list_scripts(scripts_dir)


def _strip_config_secrets(data: dict) -> dict:
    for h in data.get("hosts", []):
        if "password" in h:
            h["password"] = ""
    for w in data.get("wifis", []):
        if "key" in w:
            w["key"] = ""
    return data


@router.get("/config")
async def api_get_config(request: Request, include_secrets: bool = Query(False)) -> dict:
    data = get_store(request).load().model_dump(by_alias=True, mode="json")
    if not include_secrets:
        return _strip_config_secrets(data)
    return data


def _preserve_secrets(incoming: RootConfig, current: RootConfig) -> None:
    """Carry stored secrets forward when the client sends a blank value.

    The UI (and other clients) may hold a secret-stripped copy of the config; a
    blank password/key on save means "unchanged", not "erase", so a stripped GET
    can never wipe stored credentials on the next PUT.
    """
    old_hosts = {h.id: h for h in current.hosts}
    for h in incoming.hosts:
        if not h.password and old_hosts.get(h.id) and old_hosts[h.id].password:
            h.password = old_hosts[h.id].password
    old_wifis = {w.id: w for w in current.wifis}
    for w in incoming.wifis:
        if not w.key and old_wifis.get(w.id) and old_wifis[w.id].key:
            w.key = old_wifis[w.id].key


@router.put("/config")
async def api_put_config(request: Request, body: RootConfig) -> dict:
    store = get_store(request)
    _preserve_secrets(body, store.load())
    store.save(body)
    return {"ok": True}


@router.get("/additional-script", response_class=PlainTextResponse)
async def api_get_additional_script(request: Request) -> str:
    return get_store(request).load().additional_script


@router.put("/additional-script", response_class=PlainTextResponse)
async def api_put_additional_script(request: Request) -> str:
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(413, "Request body too large")
    body = raw.decode("utf-8")
    store = get_store(request)

    def fn(c: RootConfig) -> RootConfig:
        c.additional_script = body
        return c

    store.mutate(fn)
    return body


@router.post("/poll")
async def api_poll(request: Request) -> dict:
    settings = get_settings(request)
    lock: asyncio.Lock = request.app.state.poll_lock
    if lock.locked():
        raise HTTPException(409, "A poll is already in progress")
    async with lock:
        cfg = get_store(request).load()
        await poll_all(
            cfg,
            bundle_path=settings.bundle_path,
            state_dir=_state_dir(settings),
            ssh_cfg=_ssh_cfg(settings),
        )
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
    lock: asyncio.Lock = request.app.state.deploy_lock
    if lock.locked():
        raise HTTPException(409, "A deploy is already in progress")
    async with lock:
        out = await deploy_group(
            cfg,
            group,
            bundle_path=settings.bundle_path,
            state_dir=_state_dir(settings),
            ssh_cfg=_ssh_cfg(settings),
            verbose=verbose,
        )
    return {"stdout": out, "stderr": ""}


@router.post("/hosts/{host_id}/ping")
async def api_ping(request: Request, host_id: str) -> dict:
    cfg = get_store(request).load()
    host = next((h for h in cfg.hosts if h.id == host_id), None)
    if not host:
        raise HTTPException(404, "Unknown host")
    if not host.ipaddr:
        raise HTTPException(400, "Host has no address")
    # host.ipaddr is model-validated (valid IP/hostname, no leading '-'), so it
    # cannot be reparsed as a ping option.
    code, out, err = await run_cmd(
        ["ping", "-4", "-c", "5", "-W", "1", host.ipaddr],
        timeout=20,
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
    # Reject anything that is not a plain script basename (blocks path traversal
    # and shell metacharacters reaching the remote `sh /tmp/<name>`).
    try:
        safe_ident(script_name, field="script_name", maxlen=128)
    except ValueError:
        raise HTTPException(400, "Invalid script name")
    script_path = settings.bundle_path / "scripts" / script_name
    if not script_path.is_file():
        raise HTTPException(404, "Unknown script")
    use_key = host.usekeyfile
    key_path = Path(host.keyfile) if host.keyfile else None
    pw = host.password
    ssh_cfg = _ssh_cfg(settings)
    rc, _, e1 = await scp_upload(
        script_path,
        f"/tmp/{script_name}",
        user=host.username,
        host=host.ipaddr,
        port=host.port,
        use_key=use_key,
        keyfile=key_path,
        password=pw,
        cfg=ssh_cfg,
    )
    if rc != 0:
        return ScriptRunResult(stderr=e1 or "scp failed")
    code, o2, e2 = await ssh_exec(
        f"sh /tmp/{script_name}",
        user=host.username,
        host=host.ipaddr,
        port=host.port,
        use_key=use_key,
        keyfile=key_path,
        password=pw,
        cfg=ssh_cfg,
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
    try:
        cfg = parse_uci_export(body.uci_text)
    except (ValueError, ValidationError) as e:
        raise HTTPException(422, f"Invalid UCI export: {e}")
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
            lock: asyncio.Lock = app.state.poll_lock
            if now - last >= interval_sec and not lock.locked():
                async with lock:
                    await poll_all(
                        cfg,
                        bundle_path=settings.bundle_path,
                        state_dir=_state_dir(settings),
                        ssh_cfg=_ssh_cfg(settings),
                    )
                    app.state.last_poll = time.monotonic()
        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("poll scheduler error")
        await asyncio.sleep(15)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.last_poll = 0.0
    app.state.poll_lock = asyncio.Lock()
    app.state.deploy_lock = asyncio.Lock()
    app.state.poll_task = asyncio.create_task(_scheduler(app))
    yield
    app.state.poll_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await app.state.poll_task


async def _limit_body_size(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            if int(cl) > MAX_BODY_BYTES:
                return PlainTextResponse("Request body too large", status_code=413)
        except ValueError:
            return PlainTextResponse("Invalid Content-Length", status_code=400)
    return await call_next(request)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="AP Controller", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = ConfigStore(settings.config_path)

    app.middleware("http")(_limit_body_size)

    # Same-origin SPA needs no CORS; only enable it when explicit origins are
    # configured, and never combine a wildcard with credentials.
    origins = cors_list(settings.cors_origins)
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
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
    import uvicorn

    settings: Settings = app.state.settings
    host, port = resolve_bind(settings)
    uvicorn.run(app, host=host, port=port)
