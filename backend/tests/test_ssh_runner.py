import asyncio
import time
from pathlib import Path

import apctl.ssh_runner as R
from apctl.ssh_runner import SshConfig, run_cmd, scp_upload, ssh_exec


def _capture(monkeypatch):
    box = {}

    async def fake_run_cmd(args, *, cwd=None, timeout=None, env=None):
        box["args"] = list(args)
        box["env"] = env
        box["timeout"] = timeout
        return 0, "ok", ""

    monkeypatch.setattr(R, "run_cmd", fake_run_cmd)
    return box


def test_ssh_exec_argv_hardened(monkeypatch, tmp_path: Path):
    box = _capture(monkeypatch)
    cfg = SshConfig(strict="accept-new", known_hosts=tmp_path / "known_hosts")
    asyncio.run(
        ssh_exec("id", user="root", host="192.168.1.2", port=22, use_key=False, keyfile=None, password="pw", cfg=cfg)
    )
    args = box["args"]
    assert "StrictHostKeyChecking=no" not in args
    assert "StrictHostKeyChecking=accept-new" in args
    assert args[0] == "sshpass" and "-e" in args
    assert "-l" in args and "root" in args
    assert "pw" not in args  # password never on argv
    assert box["env"]["SSHPASS"] == "pw"
    assert any("known_hosts" in a for a in args)
    assert (tmp_path / "known_hosts").exists()


def test_scp_uses_end_of_options(monkeypatch, tmp_path: Path):
    box = _capture(monkeypatch)
    cfg = SshConfig(known_hosts=tmp_path / "kh")
    asyncio.run(
        scp_upload(
            tmp_path / "f", "/tmp/x", user="root", host="10.0.0.1", port=2222,
            use_key=False, keyfile=None, password="pw", cfg=cfg,
        )
    )
    assert "--" in box["args"]
    assert box["args"][0] == "sshpass"


def test_run_cmd_timeout_kills():
    t0 = time.time()
    rc, out, err = asyncio.run(run_cmd(["sleep", "5"], timeout=0.5))
    assert rc == 124
    assert time.time() - t0 < 2
    assert "timed out" in err
