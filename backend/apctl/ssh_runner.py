from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Sequence

_STRICT = ("StrictHostKeyChecking=no",)


async def run_cmd(args: Sequence[str], *, cwd: Path | None = None) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=os.fspath(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_b, err_b = await proc.communicate()
    return proc.returncode or 0, out_b.decode(errors="replace"), err_b.decode(errors="replace")


async def scp_upload(
    local: Path,
    remote_spec: str,
    *,
    port: int,
    use_key: bool,
    keyfile: Path | None,
    password: str,
) -> tuple[int, str, str]:
    """remote_spec like user@host:/tmp/file"""
    if use_key and keyfile and keyfile.is_file():
        args = [
            "scp",
            "-O",
            "-i",
            os.fspath(keyfile),
            "-o",
            *_STRICT,
            "-P",
            str(port),
            os.fspath(local),
            remote_spec,
        ]
        return await run_cmd(args)
    args = [
        "sshpass",
        "-p",
        password,
        "scp",
        "-O",
        "-o",
        *_STRICT,
        "-P",
        str(port),
        os.fspath(local),
        remote_spec,
    ]
    return await run_cmd(args)


async def ssh_exec(
    remote_target: str,
    remote_cmd: str,
    *,
    port: int,
    use_key: bool,
    keyfile: Path | None,
    password: str,
    connect_timeout: int | None = None,
) -> tuple[int, str, str]:
    timeout_opts: list[str] = []
    if connect_timeout is not None:
        timeout_opts = ["-o", f"ConnectTimeout={connect_timeout}"]
    if use_key and keyfile and keyfile.is_file():
        args = [
            "ssh",
            "-q",
            "-i",
            os.fspath(keyfile),
            "-o",
            *_STRICT,
            *timeout_opts,
            "-p",
            str(port),
            remote_target,
            remote_cmd,
        ]
        return await run_cmd(args)
    args = [
        "sshpass",
        "-p",
        password,
        "ssh",
        "-q",
        "-o",
        *_STRICT,
        *timeout_opts,
        "-p",
        str(port),
        remote_target,
        remote_cmd,
    ]
    return await run_cmd(args)
