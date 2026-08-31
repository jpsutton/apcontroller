from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from apctl.validation import (
    enc_token,
    host_or_ip,
    safe_ident,
    safe_key_path,
    safe_url,
    ssid_field,
    text_field,
)


class GlobalSection(BaseModel):
    interval: int = Field(5, ge=1, le=9999)
    # Retained for UCI/JSON back-compat but INERT server-side: the controller
    # writes its status cache under the operator-controlled state_dir (Settings),
    # never a path chosen by an API client. See settings.state_dir.
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
    port: int = Field(22, ge=1, le=65535)
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

    @field_validator("id")
    @classmethod
    def _v_id(cls, v: str) -> str:
        return safe_ident(v, field="host id")

    @field_validator("ipaddr")
    @classmethod
    def _v_ipaddr(cls, v: str) -> str:
        return host_or_ip(v, field="ipaddr")

    @field_validator("username")
    @classmethod
    def _v_username(cls, v: str) -> str:
        return safe_ident(v, field="username", maxlen=64)

    @field_validator("trunk_port")
    @classmethod
    def _v_trunk_port(cls, v: str) -> str:
        return safe_ident(v, field="trunk_port", maxlen=32, allow_empty=True)

    @field_validator("keyfile")
    @classmethod
    def _v_keyfile(cls, v: str) -> str:
        return safe_key_path(v, field="keyfile")

    @field_validator("name", "password")
    @classmethod
    def _v_text(cls, v: str) -> str:
        # Passwords may contain most printable characters; reject only control
        # chars/newlines and cap length so they stay a single safe token.
        return text_field(v, field="host text", maxlen=256)

    @field_validator("url")
    @classmethod
    def _v_url(cls, v: str) -> str:
        return safe_url(v, field="url")


class Vlan(BaseModel):
    id: str
    name: str = ""
    vlan_id: int = Field(ge=1, le=4094)
    device: str = "br-lan"

    @field_validator("id", "device")
    @classmethod
    def _v_ident(cls, v: str) -> str:
        return safe_ident(v, field="vlan id/device", maxlen=64)

    @field_validator("name")
    @classmethod
    def _v_name(cls, v: str) -> str:
        return text_field(v, field="vlan name", maxlen=128)


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

    @field_validator("id", "network")
    @classmethod
    def _v_ident(cls, v: str) -> str:
        return safe_ident(v, field="wifi id/network", maxlen=64)

    @field_validator("vlan")
    @classmethod
    def _v_vlan(cls, v: str) -> str:
        return safe_ident(v, field="vlan ref", maxlen=64, allow_empty=True)

    @field_validator("band")
    @classmethod
    def _v_band(cls, v: list[str]) -> list[str]:
        allowed = {"2g", "5g", "6g"}
        for b in v:
            if b not in allowed:
                raise ValueError(f"band must be one of {sorted(allowed)}")
        return v

    @field_validator("ssid")
    @classmethod
    def _v_ssid(cls, v: str) -> str:
        return ssid_field(v, field="ssid", maxlen=32)

    @field_validator("key")
    @classmethod
    def _v_key(cls, v: str) -> str:
        return text_field(v, field="wifi key", maxlen=63)

    @field_validator("name")
    @classmethod
    def _v_name(cls, v: str) -> str:
        return text_field(v, field="wifi name", maxlen=128)

    @field_validator("encryption")
    @classmethod
    def _v_encryption(cls, v: str) -> str:
        return enc_token(v, field="encryption")


class Group(BaseModel):
    id: str
    name: str = ""
    host: list[str] = Field(default_factory=list)
    wifi: list[str] = Field(default_factory=list)
    delete: bool = False
    useadditionalscript: bool = False

    @field_validator("id")
    @classmethod
    def _v_id(cls, v: str) -> str:
        return safe_ident(v, field="group id")

    @field_validator("name")
    @classmethod
    def _v_name(cls, v: str) -> str:
        return text_field(v, field="group name", maxlen=128)

    @field_validator("host", "wifi")
    @classmethod
    def _v_refs(cls, v: list[str]) -> list[str]:
        return [safe_ident(x, field="group ref", maxlen=64) for x in v]


class RootConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    global_: GlobalSection = Field(alias="global", default_factory=GlobalSection)
    hosts: list[Host] = Field(default_factory=list)
    wifis: list[Wifi] = Field(default_factory=list)
    vlans: list[Vlan] = Field(default_factory=list)
    groups: list[Group] = Field(default_factory=list)
    additional_script: str = ""
