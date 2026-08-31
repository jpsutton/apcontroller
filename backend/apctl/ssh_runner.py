from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

DEFAULT_CONNECT_TIMEOUT = 8
DEFAULT_TIMEOUT = 60.0


@dataclass(frozen=True)
class SshConfig:
    """Per-connection SSH policy threaded from Settings by the callers.

    ``strict`` selects the host-key policy: ``accept-new`` (TOFU, the default)
    pins each AP's key in ``known_hosts`` on first contact and refuses a later
    mismatch (MITM); ``yes`` is fully strict; ``no`` disables verification
    (documented lab opt-out only).
    """

    strict: str = "accept-new"
    known_hosts: Path | None = None
    connect_timeout: int = DEFAULT_CONNECT_TIMEOUT
    timeout: float = DEFAULT_TIMEOUT


def _prepare_known_hosts(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch(mode=0o600)
    else:
        try:
            path.chmod(0o600)
        except OSError:
            pass


def _hostkey_opts(cfg: SshConfig) -> list[str]:
    if cfg.strict == "no":
        return ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null"]
    mode = "yes" if cfg.strict == "yes" else "accept-new"
    opts = ["-o", f"StrictHostKeyChecking={mode}", "-o", "GlobalKnownHostsFile=/dev/null"]
    if cfg.known_hosts is not None:
        _prepare_known_hosts(cfg.known_hosts)
        opts += ["-o", f"UserKnownHostsFile={os.fspath(cfg.known_hosts)}"]
    return opts


def _common_opts(cfg: SshConfig) -> list[str]:
    return [*_hostkey_opts(cfg), "-o", f"ConnectTimeout={cfg.connect_timeout}", "-o", "BatchMode=no"]


async def run_cmd(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: float | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=os.fspath(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=dict(env) if env is not None else None,
    )
    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        return 124, "", f"command timed out after {timeout}s"
    return proc.returncode or 0, out_b.decode(errors="replace"), err_b.decode(errors="replace")


def _sshpass_env(password: str) -> dict[str, str]:
    # sshpass -e reads the password from SSHPASS instead of argv, so it never
    # appears in the host process table.
    return {**os.environ, "SSHPASS": password}


async def scp_upload(
    local: Path,
    remote_path: str,
    *,
    user: str,
    host: str,
    port: int,
    use_key: bool,
    keyfile: Path | None,
    password: str,
    cfg: SshConfig | None = None,
) -> tuple[int, str, str]:
    """Upload ``local`` to ``user@host:remote_path``.

    ``user``/``host`` are model-validated (no leading '-', no metachars) before
    reaching here, so they cannot be reparsed as scp options.
    """
    cfg = cfg or SshConfig()
    dest = f"{user}@{host}:{remote_path}"
    if use_key and keyfile and keyfile.is_file():
        args = [
            "scp",
            "-O",
            "-i",
            os.fspath(keyfile),
            *_common_opts(cfg),
            "-P",
            str(port),
            "--",
            os.fspath(local),
            dest,
        ]
        return await run_cmd(args, timeout=cfg.timeout)
    args = [
        "sshpass",
        "-e",
        "scp",
        "-O",
        *_common_opts(cfg),
        "-P",
        str(port),
        "--",
        os.fspath(local),
        dest,
    ]
    return await run_cmd(args, timeout=cfg.timeout, env=_sshpass_env(password))


async def ssh_exec(
    remote_cmd: str,
    *,
    user: str,
    host: str,
    port: int,
    use_key: bool,
    keyfile: Path | None,
    password: str,
    cfg: SshConfig | None = None,
) -> tuple[int, str, str]:
    """Run ``remote_cmd`` on ``host`` as ``user``.

    Uses ``-l <user> <host>`` (not a ``user@host`` token) and validated inputs so
    a stray '-' can never be parsed as an ssh option on the controller.
    """
    cfg = cfg or SshConfig()
    if use_key and keyfile and keyfile.is_file():
        args = [
            "ssh",
            "-q",
            "-i",
            os.fspath(keyfile),
            *_common_opts(cfg),
            "-p",
            str(port),
            "-l",
            user,
            host,
            remote_cmd,
        ]
        return await run_cmd(args, timeout=cfg.timeout)
    args = [
        "sshpass",
        "-e",
        "ssh",
        "-q",
        *_common_opts(cfg),
        "-p",
        str(port),
        "-l",
        user,
        host,
        remote_cmd,
    ]
    return await run_cmd(args, timeout=cfg.timeout, env=_sshpass_env(password))
