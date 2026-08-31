from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from apctl.models import Host, RootConfig
from apctl.ssh_runner import scp_upload, ssh_exec


def _hour_bucket_ts(ts: float) -> int:
    dt = datetime.fromtimestamp(ts)
    floor = dt.replace(minute=0, second=0, microsecond=0)
    return int(floor.timestamp())


def _activity_append(basepath: Path, ipaddr: str, now_ts: float, val: int) -> None:
    line_ts = _hour_bucket_ts(now_ts)
    path = basepath / f"{ipaddr}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"{line_ts} {val}\n"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if line.strip() not in {l.strip() for l in existing.splitlines()}:
        with path.open("a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(line)


async def poll_host(host: Host, *, basepath: Path, agent_path: Path) -> None:
    if not host.enabled or not host.ipaddr or not host.username:
        return
    use_key = host.usekeyfile
    key_path = Path(host.keyfile) if host.keyfile else None
    pw = host.password or '""'

    target = f"{host.username}@{host.ipaddr}"
    rc, _, _ = await scp_upload(
        agent_path,
        f"{target}:/tmp/apcontroller-agent",
        port=host.port,
        use_key=use_key,
        keyfile=key_path,
        password=pw,
    )
    out_path = basepath / f"{host.ipaddr}-{host.id}"
    now = time.time()
    if rc == 0:
        code, out, _ = await ssh_exec(
            target,
            "/tmp/apcontroller-agent",
            port=host.port,
            use_key=use_key,
            keyfile=key_path,
            password=pw,
        )
        # Shell always truncates via ssh redirect when scp succeeded
        out_path.write_text(out if code == 0 else "", encoding="utf-8")
    # if scp fails, leave existing cache file untouched (matches OpenWrt shell)

    val = 0
    if out_path.is_file() and out_path.stat().st_size > 0:
        mtime = out_path.stat().st_mtime
        if now - mtime <= 60:
            val = 1
    _activity_append(basepath, host.ipaddr, now, val)


async def poll_all(cfg: RootConfig, *, bundle_path: Path) -> None:
    base = Path(cfg.global_.path)
    base.mkdir(parents=True, exist_ok=True)
    agent = bundle_path / "apcontroller-agent"
    if not agent.is_file():
        raise FileNotFoundError(f"Missing agent at {agent}")
    for h in cfg.hosts:
        await poll_host(h, basepath=base, agent_path=agent)
