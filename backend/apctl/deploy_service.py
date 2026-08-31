from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

from apctl.models import Group, Host, RootConfig, Vlan, Wifi
from apctl.ssh_runner import SshConfig, scp_upload, ssh_exec

# Seconds the on-device watchdog waits before auto-restoring the pre-deploy
# network config. The controller must re-verify connectivity and disarm within
# this window; keep the verify budget comfortably below it.
ROLLBACK_SECS = 180
VERIFY_BUDGET_SECS = 120
VERIFY_INTERVAL_SECS = 10
VERIFY_CONNECT_TIMEOUT = 8


def _chmod_600(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _wifi_by_id(cfg: RootConfig, wid: str) -> Wifi | None:
    for w in cfg.wifis:
        if w.id == wid:
            return w
    return None


def _host_by_id(cfg: RootConfig, hid: str) -> Host | None:
    for h in cfg.hosts:
        if h.id == hid:
            return h
    return None


def _vlan_by_id(cfg: RootConfig, vid: str) -> Vlan | None:
    for v in cfg.vlans:
        if v.id == vid:
            return v
    return None


def build_deploy_document(cfg: RootConfig, group: Group, host: Host) -> dict:
    """Build the JSON command document deployed to a single host.

    The wifi-iface ``network`` is resolved up front: an SSID mapped to a VLAN
    points at the VLAN's interface section (named after the Vlan id); otherwise
    it points at the untagged management network. The VLANs actually referenced
    by this group's Wi-Fi networks are emitted so the agent can provision the
    matching bridge-vlan + interface sections.
    """
    doc: dict = {"wifis": [], "vlans": []}
    if group.delete:
        doc["delete"] = 1
    doc["trunk_port"] = host.trunk_port
    doc["mgmt_vlan"] = host.mgmt_vlan
    doc["dumb_ap"] = 1 if host.dumb_ap else 0
    doc["rollback_secs"] = ROLLBACK_SECS

    used_vlans: dict[str, Vlan] = {}
    for wid in group.wifi:
        w = _wifi_by_id(cfg, wid)
        if not w:
            continue
        vlan = _vlan_by_id(cfg, w.vlan) if w.vlan else None
        network = vlan.id if vlan else w.network
        if vlan:
            used_vlans[vlan.id] = vlan
        for band in w.band:
            doc["wifis"].append(
                {
                    "enabled": 1 if w.enabled else 0,
                    "band": band,
                    "ssid": w.ssid,
                    "encryption": w.encryption,
                    "key": w.key,
                    "hidden": 1 if w.hidden else 0,
                    "isolate": 1 if w.isolate else 0,
                    "network": network,
                }
            )

    for vlan in used_vlans.values():
        doc["vlans"].append(
            {"name": vlan.id, "tag": vlan.vlan_id, "device": vlan.device}
        )
    return doc


async def _verify_and_disarm(
    *,
    user: str,
    host: str,
    port: int,
    use_key: bool,
    keyfile: Path | None,
    password: str,
    ssh_cfg: SshConfig,
) -> bool:
    """Re-establish SSH after a VLAN apply and cancel the on-device rollback.

    Returns True once the host is reachable again and the watchdog is disarmed.
    If the host never comes back within the verify budget we leave the watchdog
    armed; it restores the pre-deploy config and the host self-heals.

    The budget is measured in real wall-clock time (not just the sum of sleeps):
    each probe is bounded by the SSH connect/command timeout, so a hung probe
    can no longer push total verification past the on-device ROLLBACK window.
    """
    verify_cfg = replace(ssh_cfg, connect_timeout=VERIFY_CONNECT_TIMEOUT, timeout=VERIFY_CONNECT_TIMEOUT + 4)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + VERIFY_BUDGET_SECS
    # Give the detached apply (short delay + network restart) time to flap and
    # settle before the first probe.
    await asyncio.sleep(VERIFY_INTERVAL_SECS)
    while loop.time() < deadline:
        code, out, _ = await ssh_exec(
            "touch /tmp/apctl-rollback-disarm && echo ok",
            user=user,
            host=host,
            port=port,
            use_key=use_key,
            keyfile=keyfile,
            password=password,
            cfg=verify_cfg,
        )
        if code == 0 and "ok" in out:
            return True
        await asyncio.sleep(VERIFY_INTERVAL_SECS)
    return False


async def deploy_group(
    cfg: RootConfig,
    group: Group,
    *,
    bundle_path: Path,
    state_dir: Path,
    ssh_cfg: SshConfig,
    verbose: bool = False,
) -> str:
    base = state_dir
    base.mkdir(parents=True, exist_ok=True)
    try:
        base.chmod(0o700)
    except OSError:
        pass
    # The wifi list is identical for every host; bail early if there's nothing
    # to deploy. The per-host document (built below) only differs in the
    # host-specific trunk/management VLAN fields.
    if not any(_wifi_by_id(cfg, wid) for wid in group.wifi):
        return "No Wi-Fi definitions for this group.\n"

    setconfig = bundle_path / "apcontroller-agent-setconfig"
    agent_as = bundle_path / "apcontroller-agent-as"
    # apcontroller.user is operator shell run as root on the AP; cmds-* carries
    # Wi-Fi PSKs. Keep both non-world-readable on the controller.
    user_script_local = base / "apcontroller.user"
    user_script_local.write_text(cfg.additional_script or "", encoding="utf-8")
    _chmod_600(user_script_local)

    cmd_file = base / f"cmds-{group.id}"
    lines: list[str] = []
    for hid in group.host:
        host = _host_by_id(cfg, hid)
        if not host or not host.enabled or not host.ipaddr or not host.username:
            continue
        doc = build_deploy_document(cfg, group, host)
        cmd_file.write_text(json.dumps(doc), encoding="utf-8")
        _chmod_600(cmd_file)
        use_key = host.usekeyfile
        key_path = Path(host.keyfile) if host.keyfile else None
        pw = host.password
        remote_cmd_file = f"/tmp/cmds-{group.id}"

        def _up(local: Path, remote: str):
            return scp_upload(
                local,
                remote,
                user=host.username,
                host=host.ipaddr,
                port=host.port,
                use_key=use_key,
                keyfile=key_path,
                password=pw,
                cfg=ssh_cfg,
            )

        if group.useadditionalscript:
            await _up(user_script_local, "/tmp/apcontroller.user")
            if agent_as.is_file():
                await _up(agent_as, "/tmp/apcontroller-agent-as")

        rc1, _, _ = await _up(cmd_file, remote_cmd_file)
        if rc1 != 0:
            if verbose:
                lines.append(f"{host.name} ({host.ipaddr}): ERROR\n")
            continue
        rc2, _, _ = await _up(setconfig, "/tmp/apcontroller-agent-setconfig")
        if rc2 != 0:
            if verbose:
                lines.append(f"{host.name} ({host.ipaddr}): ERROR\n")
            continue
        code, _, _ = await ssh_exec(
            f"/tmp/apcontroller-agent-setconfig {remote_cmd_file}",
            user=host.username,
            host=host.ipaddr,
            port=host.port,
            use_key=use_key,
            keyfile=key_path,
            password=pw,
            cfg=ssh_cfg,
        )

        # When this deploy provisions VLANs the agent arms a self-healing
        # rollback before flapping the network. Re-verify reachability and
        # disarm it; if the host never returns we leave it armed so the AP
        # restores the previous config on its own.
        armed_rollback = bool(host.trunk_port and doc["vlans"])
        if armed_rollback:
            ok = await _verify_and_disarm(
                user=host.username,
                host=host.ipaddr,
                port=host.port,
                use_key=use_key,
                keyfile=key_path,
                password=pw,
                ssh_cfg=ssh_cfg,
            )
            if verbose:
                if ok:
                    lines.append(f"{host.name} ({host.ipaddr}): OK (VLAN apply verified)\n")
                else:
                    lines.append(
                        f"{host.name} ({host.ipaddr}): UNREACHABLE after VLAN apply — "
                        f"host will auto-restore its previous config\n"
                    )
        elif verbose:
            lines.append(f"{host.name} ({host.ipaddr}): {'OK' if code == 0 else 'ERROR'}\n")

    try:
        cmd_file.unlink(missing_ok=True)
    except OSError:
        pass
    return "".join(lines)
