from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from apctl.models import GlobalSection, RootConfig


def default_root_config() -> RootConfig:
    return RootConfig.model_validate(
        {
            "global": GlobalSection().model_dump(),
            "hosts": [],
            "wifis": [],
            "groups": [],
            "additional_script": "",
        }
    )


class ConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    def _ensure_parent(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> RootConfig:
        with self._lock:
            self._ensure_parent()
            if not self.path.is_file():
                cfg = default_root_config()
                self._write_unlocked(cfg)
                return cfg
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return RootConfig.model_validate(raw)

    def save(self, cfg: RootConfig) -> None:
        with self._lock:
            self._ensure_parent()
            self._write_unlocked(cfg)

    def _write_unlocked(self, cfg: RootConfig) -> None:
        data: dict[str, Any] = cfg.model_dump(by_alias=True, mode="json")
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def mutate(self, fn: Callable[[RootConfig], RootConfig]) -> RootConfig:
        with self._lock:
            self._ensure_parent()
            if not self.path.is_file():
                cfg = default_root_config()
                self._write_unlocked(cfg)
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            cfg = RootConfig.model_validate(raw)
            cfg = fn(cfg)
            self._write_unlocked(cfg)
            return cfg
