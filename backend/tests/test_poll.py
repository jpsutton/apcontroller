import asyncio
import contextlib
import json
from pathlib import Path

import apctl.poll_service as P
from apctl.models import Host, RootConfig
from apctl.ssh_runner import SshConfig
from apctl.status_service import build_host_payload


def test_one_hung_host_does_not_wedge_others(tmp_path: Path, monkeypatch):
    """A host whose SSH hangs must not block polling of the others."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "apcontroller-agent").write_text("#!/bin/sh\n")
    state = tmp_path / "state"

    async def fake_scp(local, remote_path, *, user, host, port, use_key, keyfile, password, cfg=None):
        if host == "10.0.0.1":  # the "dead" host: hang past the per-host timeout
            await asyncio.sleep(30)
        return 0, "", ""

    async def fake_ssh(remote_cmd, *, user, host, port, use_key, keyfile, password, cfg=None):
        return 0, json.dumps({"hostname": host}), ""

    monkeypatch.setattr(P, "scp_upload", fake_scp)
    monkeypatch.setattr(P, "ssh_exec", fake_ssh)

    cfg = RootConfig(
        hosts=[
            Host(id="dead", ipaddr="10.0.0.1", username="root"),
            Host(id="live", ipaddr="10.0.0.2", username="root"),
        ]
    )
    ssh_cfg = SshConfig(timeout=0.2)

    async def go():
        task = asyncio.create_task(
            P.poll_all(cfg, bundle_path=bundle, state_dir=state, ssh_cfg=ssh_cfg)
        )
        # The live host must be polled promptly even while the dead host hangs
        # (concurrent, not serial). Poll for its cache file to appear.
        for _ in range(50):
            if (state / "10.0.0.2-live").is_file():
                break
            await asyncio.sleep(0.1)
        assert (state / "10.0.0.2-live").is_file()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(go())


def test_status_survives_hostile_agent_output(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    h = Host(id="host1", ipaddr="1.2.3.4", enabled=True)
    cache = state / "1.2.3.4-host1"

    for payload in [
        "not json{{{",
        "[" * 20000,  # would RecursionError a naive json.loads
        json.dumps({"clientslist2g": [{"rx": "abc", "tx": None, "signal": "x", "mac": "m"}]}),
        "A" * (2 * 1024 * 1024),  # oversized
    ]:
        cache.write_text(payload)
        p = build_host_payload(h, state_dir=state, include_secrets=False)
        assert p["lastcontact"] >= 0  # never raises / 500s
