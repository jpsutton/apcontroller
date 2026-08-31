"""Import OpenWrt UCI text export into standalone JSON config."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from apctl.models import GlobalSection, Group, Host, RootConfig, Vlan, Wifi


def _strip_quotes(val: str) -> str:
    v = val.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    return v


def parse_uci_export(text: str) -> RootConfig:  # noqa: PLR0912
    current_type: str | None = None
    current_name: str | None = None
    sections: list[tuple[str, str | None, dict[str, Any]]] = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^package\s+(\S+)", line)
        if m:
            continue
        m = re.match(r"^config\s+(\S+)\s+(\S+)\s*$", line)
        if m:
            current_type = m.group(1)
            current_name = _strip_quotes(m.group(2))
            sections.append((current_type, current_name, {}))
            continue
        m = re.match(r"^config\s+(\S+)\s*$", line)
        if m:
            current_type = m.group(1)
            current_name = None
            sections.append((current_type, current_name, {}))
            continue
        m = re.match(r"^\s*option\s+(\S+)\s+'(.*)'\s*$", line)
        if not m:
            m = re.match(r'^\s*option\s+(\S+)\s+"(.*)"\s*$', line)
        if m and sections:
            sections[-1][2][m.group(1)] = _strip_quotes(m.group(2))
            continue
        m = re.match(r"^\s*list\s+(\S+)\s+'(.*)'\s*$", line)
        if not m:
            m = re.match(r'^\s*list\s+(\S+)\s+"(.*)"\s*$', line)
        if m and sections:
            k, v = m.group(1), _strip_quotes(m.group(2))
            d = sections[-1][2]
            if k not in d:
                d[k] = []
            if isinstance(d[k], list):
                d[k].append(v)
            continue

    hosts: list[Host] = []
    wifis: list[Wifi] = []
    vlans: list[Vlan] = []
    groups: list[Group] = []
    global_opts: dict[str, Any] = {}

    for typ, name, opts in sections:
        if typ == "global" and name is None:
            global_opts = opts
            continue
        sid = name or typ
        if typ == "host":
            hosts.append(
                Host(
                    id=sid,
                    enabled=_bool(opts.get("enabled", "1")),
                    name=opts.get("name", ""),
                    ipaddr=opts.get("ipaddr", ""),
                    port=int(opts.get("port", "22") or 22),
                    username=opts.get("username", "root"),
                    password=opts.get("password", ""),
                    usekeyfile=_bool(opts.get("usekeyfile", "0")),
                    keyfile=opts.get("keyfile", "/root/.ssh/id_dropbear"),
                    url=opts.get("url", ""),
                    trunk_port=opts.get("trunk_port", ""),
                    mgmt_vlan=int(opts.get("mgmt_vlan", "1") or 1),
                )
            )
        elif typ == "wifi":
            bands = opts.get("band")
            if isinstance(bands, str):
                bands = [bands]
            elif not isinstance(bands, list):
                bands = ["2g", "5g"]
            wifis.append(
                Wifi(
                    id=sid,
                    name=opts.get("name", ""),
                    enabled=_bool(opts.get("enabled", "1")),
                    band=list(bands),
                    ssid=opts.get("ssid", ""),
                    encryption=opts.get("encryption", "psk2"),
                    key=opts.get("key", ""),
                    hidden=_bool(opts.get("hidden", "0")),
                    isolate=_bool(opts.get("isolate", "0")),
                    network=opts.get("network", "lan"),
                    vlan=opts.get("vlan", ""),
                )
            )
        elif typ == "vlan":
            vlans.append(
                Vlan(
                    id=sid,
                    name=opts.get("name", ""),
                    vlan_id=int(opts.get("vlan_id", "1") or 1),
                    device=opts.get("device", "br-lan"),
                )
            )
        elif typ == "group":
            hl = opts.get("host")
            if isinstance(hl, str):
                hl = [hl]
            elif not isinstance(hl, list):
                hl = []
            wl = opts.get("wifi")
            if isinstance(wl, str):
                wl = [wl]
            elif not isinstance(wl, list):
                wl = []
            groups.append(
                Group(
                    id=sid,
                    name=opts.get("name", ""),
                    host=list(hl),
                    wifi=list(wl),
                    delete=_bool(opts.get("delete", "0")),
                    useadditionalscript=_bool(opts.get("useadditionalscript", "0")),
                )
            )

    col = global_opts.get("column")
    if isinstance(col, str):
        col = [col]
    ccol = global_opts.get("clientcolumn")
    if isinstance(ccol, str):
        ccol = [ccol]
    gs = GlobalSection(
        interval=int(global_opts.get("interval", "5") or 5),
        path=global_opts.get("path", "/tmp/apcontroller"),
        column=list(col) if isinstance(col, list) else GlobalSection().column,
        clientcolumn=list(ccol) if isinstance(ccol, list) else GlobalSection().clientcolumn,
    )

    return RootConfig(
        **{
            "global": gs,
            "hosts": hosts,
            "wifis": wifis,
            "vlans": vlans,
            "groups": groups,
            "additional_script": "",
        }
    )


def _bool(v: str) -> bool:
    return v in ("1", "true", "yes", "on")


def main() -> None:
    data = sys.stdin.read()
    cfg = parse_uci_export(data)
    print(json.dumps(cfg.model_dump(by_alias=True, mode="json"), indent=2))


if __name__ == "__main__":
    main()
