from pathlib import Path
from typing import Annotated

from pydantic import BeforeValidator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _path_or_none(v: object) -> Path | None:
    if v is None or v == "":
        return None
    return Path(v)


def _default_bundle_path() -> Path:
    # backend/apctl/settings.py -> controller-web/share/apcontroller
    return Path(__file__).resolve().parents[2] / "share" / "apcontroller"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APCTRL_", case_sensitive=False)

    config_path: Path = Path("./data/config.json")
    bundle_path: Path = _default_bundle_path()
    """Directory containing apcontroller-agent, apcontroller-agent-setconfig, apcontroller-agent-as, scripts/."""

    state_dir: Annotated[Path | None, BeforeValidator(_path_or_none)] = None
    """Operator-controlled directory for the status cache / activity logs / SSH
    known_hosts. Defaults to config_path.parent when unset. This replaces the
    former API-writable global.path so an attacker cannot redirect root-level
    filesystem writes."""

    api_key: str | None = None
    """If set, require X-API-Key header matching this value for mutating and sensitive routes."""

    host: str = "127.0.0.1"
    """Bind address. Defaults to loopback; a non-loopback bind requires api_key
    (see resolve_bind) unless allow_insecure_bind is set."""

    port: int = 8080

    allow_insecure_bind: bool = False
    """Escape hatch: permit binding a non-loopback interface with no api_key
    (e.g. when a host-loopback Docker port map or external network controls
    exposure). Off by default so the service fails closed."""

    ssh_strict: str = "accept-new"
    """SSH host-key policy: 'accept-new' (TOFU, default), 'yes' (strict), or
    'no' (disabled — documented lab opt-out only)."""

    cors_origins: str = ""
    """Comma-separated list of allowed origins. Empty (default) = no cross-origin
    access; the SPA is served same-origin and needs none. '*' is accepted only
    without credentials."""

    static_dir: Annotated[Path | None, BeforeValidator(_path_or_none)] = None
    """If set, serve SPA index.html from this directory at /."""

    def resolved_state_dir(self) -> Path:
        return (self.state_dir or self.config_path.parent).resolve()


def cors_list(raw: str) -> list[str]:
    raw = raw.strip()
    if not raw:
        return []
    if raw == "*":
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]
