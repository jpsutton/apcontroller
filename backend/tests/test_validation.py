from pathlib import Path

import pytest
from pydantic import ValidationError

from apctl.models import Group, Host, Vlan, Wifi
from apctl.ssh_runner import SshConfig
from apctl.validation import confine_path, safe_int


def test_defaults_and_real_fixtures_pass() -> None:
    Host(id="host1", ipaddr="192.168.1.2", trunk_port="lan1", mgmt_vlan=1)
    Host(id="host1", ipaddr="", username="root", keyfile="/root/.ssh/id_dropbear")
    Wifi(id="wifi1", ssid="GuestSSID", encryption="psk2", key="pass", band=["2g", "5g"])
    Wifi(id="wifi1", ssid="My Home 5G", encryption="sae-mixed")
    Vlan(id="vlan10", vlan_id=10, device="br-lan")
    Group(id="group1", host=["host1"], wifi=["wifi1"])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"id": "host1", "ipaddr": "-oProxyCommand=touch /tmp/x"},
        {"id": "host1", "username": "-l"},
        {"id": "host1", "username": "root; rm -rf /"},
        {"id": "../etc", "ipaddr": "1.2.3.4"},
        {"id": "host1", "keyfile": "-oProxyCommand=x"},
        {"id": "host1", "keyfile": "relative/path"},
        {"id": "host1", "port": 70000},
    ],
)
def test_host_rejects_bad_input(kwargs) -> None:
    with pytest.raises(ValidationError):
        Host(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"id": "w1", "ssid": "x/{system(1)}"},
        {"id": "w1", "ssid": "x" * 33},
        {"id": "w1", "ssid": "quote'd"},
        {"id": "w1", "encryption": "psk2; reboot"},
        {"id": "w1", "key": "x" * 64},
        {"id": "w1", "band": ["2g", "7g"]},
        {"id": "w1", "network": "lan;reboot"},
    ],
)
def test_wifi_rejects_bad_input(kwargs) -> None:
    with pytest.raises(ValidationError):
        Wifi(**kwargs)


def test_url_is_blanked_not_rejected() -> None:
    assert Host(id="h1", url="javascript:alert(1)").url == ""
    assert Host(id="h1", url="data:text/html,x").url == ""
    assert Host(id="h1", url="https://ap.local").url == "https://ap.local"
    assert Host(id="h1", url="http://ap.local").url == "http://ap.local"


def test_safe_int() -> None:
    assert safe_int("5") == 5
    assert safe_int("abc") == 0
    assert safe_int(None) == 0
    assert safe_int("", 7) == 7
    assert safe_int(3) == 3


def test_confine_path(tmp_path: Path) -> None:
    root = tmp_path / "state"
    root.mkdir()
    assert confine_path(root, "1.2.3.4-host1").parent == root.resolve()
    with pytest.raises(ValueError):
        confine_path(root, "../escape")
    with pytest.raises(ValueError):
        confine_path(root, "/etc/passwd")


def test_ssh_config_defaults() -> None:
    cfg = SshConfig()
    assert cfg.strict == "accept-new"
    assert cfg.connect_timeout > 0
