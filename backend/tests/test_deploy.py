from apctl.deploy_service import build_deploy_document
from apctl.models import Group, Host, RootConfig, Vlan, Wifi


def _cfg() -> RootConfig:
    return RootConfig(
        hosts=[Host(id="host1", ipaddr="192.168.1.2", trunk_port="lan1", mgmt_vlan=1)],
        vlans=[Vlan(id="vlan10", name="Guest", vlan_id=10, device="br-lan")],
        wifis=[
            Wifi(id="wifi1", ssid="Mgmt", band=["2g", "5g"], network="lan", vlan=""),
            Wifi(id="wifi2", ssid="Guest", band=["2g"], vlan="vlan10"),
        ],
        groups=[Group(id="group1", host=["host1"], wifi=["wifi1", "wifi2"])],
    )


def test_resolves_network_and_vlans() -> None:
    cfg = _cfg()
    doc = build_deploy_document(cfg, cfg.groups[0], cfg.hosts[0])

    assert doc["trunk_port"] == "lan1"
    assert doc["mgmt_vlan"] == 1

    # Untagged SSID keeps its management interface; one entry per band.
    mgmt = [w for w in doc["wifis"] if w["ssid"] == "Mgmt"]
    assert {w["network"] for w in mgmt} == {"lan"}
    assert len(mgmt) == 2

    # VLAN-mapped SSID points at the VLAN's interface section name.
    guest = [w for w in doc["wifis"] if w["ssid"] == "Guest"]
    assert len(guest) == 1
    assert guest[0]["network"] == "vlan10"

    # Only the referenced VLAN is provisioned, de-duplicated, with tag + device.
    assert doc["vlans"] == [{"name": "vlan10", "tag": 10, "device": "br-lan"}]


def test_unreferenced_vlan_is_omitted() -> None:
    cfg = _cfg()
    cfg.vlans.append(Vlan(id="vlan20", name="IoT", vlan_id=20))
    doc = build_deploy_document(cfg, cfg.groups[0], cfg.hosts[0])
    names = {v["name"] for v in doc["vlans"]}
    assert names == {"vlan10"}
