from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from apctl.models import Host, RootConfig


def _strip_secrets(host_obj: dict[str, Any]) -> dict[str, Any]:
    out = dict(host_obj)
    if "password" in out:
        out["password"] = ""
    return out


def build_host_payload(
    host: Host,
    cfg: RootConfig,
    *,
    include_secrets: bool,
) -> dict[str, Any]:
    base = Path(cfg.global_.path)
    data_path = base / f"{host.ipaddr}-{host.id}"
    now = int(time.time())
    lastcontact = -1
    payload: dict[str, Any] = {
        "section": host.id,
        "enabled": bool(host.enabled),
        "name": host.name,
        "ipaddr": host.ipaddr,
        "port": host.port,
        "username": host.username,
        "password": host.password if include_secrets else "",
    }

    if host.enabled and data_path.is_file() and data_path.stat().st_size > 0:
        lastcontact = now - int(data_path.stat().st_mtime)
        try:
            agent = json.loads(data_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            agent = {}
        for key in (
            "hostname",
            "model",
            "load",
            "uptime",
            "mac",
            "software",
            "channels2g",
            "channels5g",
            "channels6g",
        ):
            if key in agent and agent[key] is not None:
                payload[key] = agent[key]
        for band in ("2g", "5g", "6g"):
            ck = f"clientslist{band}"
            if ck in agent and isinstance(agent[ck], list):
                clients: list[dict[str, Any]] = []
                for c in agent[ck]:
                    if not isinstance(c, dict):
                        continue
                    clients.append(
                        {
                            "ssid": c.get("ssid", ""),
                            "mac": c.get("mac", ""),
                            "rx": int(c.get("rx", 0) or 0),
                            "tx": int(c.get("tx", 0) or 0),
                            "signal": int(c.get("signal", 0) or 0),
                            "connected": int(c.get("connected", 0) or 0),
                            "wifi": int(c.get("wifi", 0) or 0),
                            "ipaddr": c.get("ipaddr", "") or "",
                            "name": c.get("name", "") or "",
                        }
                    )
                payload[ck] = clients

    payload["lastcontact"] = lastcontact
    if not include_secrets:
        return _strip_secrets(payload)
    return payload


def build_status(cfg: RootConfig, *, include_secrets: bool = False) -> dict[str, Any]:
    return {"hosts": [build_host_payload(h, cfg, include_secrets=include_secrets) for h in cfg.hosts]}


def build_activity(host: Host, cfg: RootConfig) -> dict[str, Any]:
    base = Path(cfg.global_.path)
    path = base / f"{host.ipaddr}.txt"
    activity: list[dict[str, Any]] = []
    if host.enabled and host.ipaddr and path.is_file() and path.stat().st_size > 0:
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in lines[-672:]:
            parts = line.split()
            if len(parts) >= 2:
                try:
                    activity.append({"timestamp": int(parts[0]), "value": int(parts[1])})
                except ValueError:
                    continue
    return {"activity": activity}
