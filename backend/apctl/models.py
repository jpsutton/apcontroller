from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GlobalSection(BaseModel):
    interval: int = Field(5, ge=1, le=9999)
    path: str = "/tmp/apcontroller"
    column: list[str] = Field(
        default_factory=lambda: [
            "enabled",
            "name",
            "ipaddr",
            "lastcontact",
        ]
    )
    clientcolumn: list[str] = Field(
        default_factory=lambda: [
            "ap",
            "name",
            "mac",
            "ipaddr",
            "band",
            "wifi",
            "signal",
            "connected",
            "rx",
            "tx",
        ]
    )


class Host(BaseModel):
    id: str
    enabled: bool = True
    name: str = ""
    ipaddr: str = ""
    port: int = 22
    username: str = "root"
    password: str = ""
    usekeyfile: bool = False
    keyfile: str = "/root/.ssh/id_dropbear"
    url: str = ""
    # Uplink/trunk port that carries tagged VLANs (e.g. "lan1"). Empty disables
    # VLAN provisioning on this host to avoid stranding the management link.
    trunk_port: str = ""
    # Untagged management VLAN tag, kept reachable on every br-lan port.
    mgmt_vlan: int = Field(1, ge=1, le=4094)
    # Disable dnsmasq, odhcpd, and firewall so the AP acts as a pure L2 bridge.
    dumb_ap: bool = True


class Vlan(BaseModel):
    id: str
    name: str = ""
    vlan_id: int = Field(ge=1, le=4094)
    device: str = "br-lan"


class Wifi(BaseModel):
    id: str
    name: str = ""
    enabled: bool = True
    band: list[str] = Field(default_factory=lambda: ["2g", "5g"])
    ssid: str = ""
    encryption: str = "psk2"
    key: str = ""
    hidden: bool = False
    isolate: bool = False
    network: str = "lan"
    # References a Vlan.id. Empty means the untagged management network above.
    vlan: str = ""


class Group(BaseModel):
    id: str
    name: str = ""
    host: list[str] = Field(default_factory=list)
    wifi: list[str] = Field(default_factory=list)
    delete: bool = False
    useadditionalscript: bool = False


class RootConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    global_: GlobalSection = Field(alias="global", default_factory=GlobalSection)
    hosts: list[Host] = Field(default_factory=list)
    wifis: list[Wifi] = Field(default_factory=list)
    vlans: list[Vlan] = Field(default_factory=list)
    groups: list[Group] = Field(default_factory=list)
    additional_script: str = ""
