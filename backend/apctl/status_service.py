from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from apctl.models import Host, RootConfig
from apctl.poll_service import MAX_AGENT_BYTES
from apctl.validation import confine_path, safe_int

# Cap the number of client rows parsed from a single (untrusted) AP payload.
MAX_CLIENTS_PER_BAND = 512


def _strip_secrets(host_obj: dict[str, Any]) -> dict[str, Any]:
    out = dict(host_obj)
    if "password" in out:
        out["password"] = ""
    return out


def _load_agent(data_path: Path) -> dict[str, Any]:
    """Parse the cached agent JSON defensively.

    The file content is whatever a managed AP returned, so treat it as hostile:
    cap the bytes read and swallow any parse error (including RecursionError from
    a deeply nested document) rather than letting it 500 the status endpoint.
    """
    try:
        raw = data_path.read_bytes()[:MAX_AGENT_BYTES]
        parsed = json.loads(raw.decode("utf-8", "replace"))
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, RecursionError, OSError):
        return {}


def build_host_payload(
    host: Host,
    *,
    state_dir: Path,
    include_secrets: bool,
) -> dict[str, Any]:
    data_path = confine_path(state_dir, f"{host.ipaddr}-{host.id}")
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
        agent = _load_agent(data_path)
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
                for c in agent[ck][:MAX_CLIENTS_PER_BAND]:
                    if not isinstance(c, dict):
                        continue
                    clients.append(
                        {
                            "ssid": str(c.get("ssid", "")),
                            "mac": str(c.get("mac", "")),
                            "rx": safe_int(c.get("rx", 0)),
                            "tx": safe_int(c.get("tx", 0)),
                            "signal": safe_int(c.get("signal", 0)),
                            "connected": safe_int(c.get("connected", 0)),
                            "wifi": safe_int(c.get("wifi", 0)),
                            "ipaddr": str(c.get("ipaddr", "") or ""),
                            "name": str(c.get("name", "") or ""),
                        }
                    )
                payload[ck] = clients

    payload["lastcontact"] = lastcontact
    if not include_secrets:
        return _strip_secrets(payload)
    return payload


def build_status(cfg: RootConfig, *, state_dir: Path, include_secrets: bool = False) -> dict[str, Any]:
    return {
        "hosts": [
            build_host_payload(h, state_dir=state_dir, include_secrets=include_secrets)
            for h in cfg.hosts
        ]
    }


def build_activity(host: Host, *, state_dir: Path) -> dict[str, Any]:
    path = confine_path(state_dir, f"{host.ipaddr}.txt")
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
