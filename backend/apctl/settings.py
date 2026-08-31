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

    api_key: str | None = None
    """If set, require X-API-Key header matching this value for mutating and sensitive routes."""

    cors_origins: str = "*"
    """Comma-separated list or * for development."""

    static_dir: Annotated[Path | None, BeforeValidator(_path_or_none)] = None
    """If set, serve SPA index.html from this directory at /."""


def cors_list(raw: str) -> list[str]:
    if raw.strip() == "*":
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]
