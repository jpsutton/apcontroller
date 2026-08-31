from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path

from apctl.models import Host, RootConfig
from apctl.ssh_runner import SshConfig, scp_upload, ssh_exec
from apctl.validation import confine_path

# Cap the untrusted stdout a managed AP can push back, so a compromised/hostile
# AP cannot exhaust controller memory or disk via a giant agent payload.
MAX_AGENT_BYTES = 256 * 1024
POLL_CONCURRENCY = 8


def _hour_bucket_ts(ts: float) -> int:
    dt = datetime.fromtimestamp(ts)
    floor = dt.replace(minute=0, second=0, microsecond=0)
    return int(floor.timestamp())


def _activity_append(basepath: Path, ipaddr: str, now_ts: float, val: int) -> None:
    line_ts = _hour_bucket_ts(now_ts)
    path = confine_path(basepath, f"{ipaddr}.txt")
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"{line_ts} {val}\n"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if line.strip() not in {l.strip() for l in existing.splitlines()}:
        with path.open("a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(line)


def _per_host_timeout(ssh_cfg: SshConfig) -> float:
    # scp + ssh, each bounded by ssh_cfg.timeout, plus a little slack.
    return ssh_cfg.timeout * 2 + 10


async def poll_host(host: Host, *, basepath: Path, agent_path: Path, ssh_cfg: SshConfig) -> None:
    if not host.enabled or not host.ipaddr or not host.username:
        return
    use_key = host.usekeyfile
    key_path = Path(host.keyfile) if host.keyfile else None
    pw = host.password

    rc, _, _ = await scp_upload(
        agent_path,
        "/tmp/apcontroller-agent",
        user=host.username,
        host=host.ipaddr,
        port=host.port,
        use_key=use_key,
        keyfile=key_path,
        password=pw,
        cfg=ssh_cfg,
    )
    out_path = confine_path(basepath, f"{host.ipaddr}-{host.id}")
    now = time.time()
    if rc == 0:
        code, out, _ = await ssh_exec(
            "/tmp/apcontroller-agent",
            user=host.username,
            host=host.ipaddr,
            port=host.port,
            use_key=use_key,
            keyfile=key_path,
            password=pw,
            cfg=ssh_cfg,
        )
        # Shell always truncates via ssh redirect when scp succeeded. Cap the
        # size of untrusted agent output before persisting it.
        payload = out[:MAX_AGENT_BYTES] if code == 0 else ""
        out_path.write_text(payload, encoding="utf-8")
        try:
            out_path.chmod(0o600)
        except OSError:
            pass
    # if scp fails, leave existing cache file untouched (matches OpenWrt shell)

    val = 0
    if out_path.is_file() and out_path.stat().st_size > 0:
        mtime = out_path.stat().st_mtime
        if now - mtime <= 60:
            val = 1
    _activity_append(basepath, host.ipaddr, now, val)


async def poll_all(cfg: RootConfig, *, bundle_path: Path, state_dir: Path, ssh_cfg: SshConfig) -> None:
    base = state_dir
    base.mkdir(parents=True, exist_ok=True)
    try:
        base.chmod(0o700)
    except OSError:
        pass
    agent = bundle_path / "apcontroller-agent"
    if not agent.is_file():
        raise FileNotFoundError(f"Missing agent at {agent}")

    sem = asyncio.Semaphore(POLL_CONCURRENCY)
    per_host = _per_host_timeout(ssh_cfg)

    async def _one(h: Host) -> None:
        async with sem:
            try:
                await asyncio.wait_for(
                    poll_host(h, basepath=base, agent_path=agent, ssh_cfg=ssh_cfg),
                    timeout=per_host,
                )
            except (asyncio.TimeoutError, OSError):
                # A single dead/hostile host must not wedge the others or the
                # scheduler; skip it this cycle.
                return

    # Run hosts concurrently (bounded) so one unreachable AP can't stall polling.
    await asyncio.gather(*(_one(h) for h in cfg.hosts))
