from __future__ import annotations

import asyncio
import json
from pathlib import Path

from apctl.models import Group, Host, RootConfig, Vlan, Wifi
from apctl.ssh_runner import scp_upload, ssh_exec

# Seconds the on-device watchdog waits before auto-restoring the pre-deploy
# network config. The controller must re-verify connectivity and disarm within
# this window; keep the verify budget comfortably below it.
ROLLBACK_SECS = 180
VERIFY_BUDGET_SECS = 120
VERIFY_INTERVAL_SECS = 10
VERIFY_CONNECT_TIMEOUT = 8


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
    target: str,
    *,
    port: int,
    use_key: bool,
    keyfile: Path | None,
    password: str,
) -> bool:
    """Re-establish SSH after a VLAN apply and cancel the on-device rollback.

    Returns True once the host is reachable again and the watchdog is disarmed.
    If the host never comes back within the verify budget we leave the watchdog
    armed; it restores the pre-deploy config and the host self-heals.
    """
    deadline = VERIFY_BUDGET_SECS
    waited = 0
    # Give the detached apply (short delay + network restart) time to flap and
    # settle before the first probe.
    await asyncio.sleep(VERIFY_INTERVAL_SECS)
    waited += VERIFY_INTERVAL_SECS
    while waited <= deadline:
        code, out, _ = await ssh_exec(
            target,
            "touch /tmp/apctl-rollback-disarm && echo ok",
            port=port,
            use_key=use_key,
            keyfile=keyfile,
            password=password,
            connect_timeout=VERIFY_CONNECT_TIMEOUT,
        )
        if code == 0 and "ok" in out:
            return True
        await asyncio.sleep(VERIFY_INTERVAL_SECS)
        waited += VERIFY_INTERVAL_SECS
    return False


async def deploy_group(
    cfg: RootConfig,
    group: Group,
    *,
    bundle_path: Path,
    verbose: bool = False,
) -> str:
    base = Path(cfg.global_.path)
    base.mkdir(parents=True, exist_ok=True)
    # The wifi list is identical for every host; bail early if there's nothing
    # to deploy. The per-host document (built below) only differs in the
    # host-specific trunk/management VLAN fields.
    if not any(_wifi_by_id(cfg, wid) for wid in group.wifi):
        return "No Wi-Fi definitions for this group.\n"

    setconfig = bundle_path / "apcontroller-agent-setconfig"
    agent_as = bundle_path / "apcontroller-agent-as"
    user_script_local = base / "apcontroller.user"
    user_script_local.write_text(cfg.additional_script or "", encoding="utf-8")

    cmd_file = base / f"cmds-{group.id}"
    lines: list[str] = []
    for hid in group.host:
        host = _host_by_id(cfg, hid)
        if not host or not host.enabled or not host.ipaddr or not host.username:
            continue
        doc = build_deploy_document(cfg, group, host)
        cmd_file.write_text(json.dumps(doc), encoding="utf-8")
        use_key = host.usekeyfile
        key_path = Path(host.keyfile) if host.keyfile else None
        pw = host.password or '""'
        target = f"{host.username}@{host.ipaddr}"
        remote_cmd_file = f"/tmp/cmds-{group.id}"

        if group.useadditionalscript:
            await scp_upload(
                user_script_local,
                f"{target}:/tmp/apcontroller.user",
                port=host.port,
                use_key=use_key,
                keyfile=key_path,
                password=pw,
            )
            if agent_as.is_file():
                await scp_upload(
                    agent_as,
                    f"{target}:/tmp/apcontroller-agent-as",
                    port=host.port,
                    use_key=use_key,
                    keyfile=key_path,
                    password=pw,
                )

        rc1, _, _ = await scp_upload(
            cmd_file,
            f"{target}:{remote_cmd_file}",
            port=host.port,
            use_key=use_key,
            keyfile=key_path,
            password=pw,
        )
        if rc1 != 0:
            if verbose:
                lines.append(f"{host.name} ({host.ipaddr}): ERROR\n")
            continue
        rc2, _, _ = await scp_upload(
            setconfig,
            f"{target}:/tmp/apcontroller-agent-setconfig",
            port=host.port,
            use_key=use_key,
            keyfile=key_path,
            password=pw,
        )
        if rc2 != 0:
            if verbose:
                lines.append(f"{host.name} ({host.ipaddr}): ERROR\n")
            continue
        code, _, _ = await ssh_exec(
            target,
            f"/tmp/apcontroller-agent-setconfig {remote_cmd_file}",
            port=host.port,
            use_key=use_key,
            keyfile=key_path,
            password=pw,
        )

        # When this deploy provisions VLANs the agent arms a self-healing
        # rollback before flapping the network. Re-verify reachability and
        # disarm it; if the host never returns we leave it armed so the AP
        # restores the previous config on its own.
        armed_rollback = bool(host.trunk_port and doc["vlans"])
        if armed_rollback:
            ok = await _verify_and_disarm(
                target,
                port=host.port,
                use_key=use_key,
                keyfile=key_path,
                password=pw,
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
