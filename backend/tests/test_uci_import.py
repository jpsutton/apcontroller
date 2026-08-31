from apctl.uci_import import parse_uci_export

SAMPLE = """
package apcontroller

config global
	option interval '5'
	option path '/tmp/apcontroller'
	list column 'enabled'
	list column 'name'

config host 'host1'
	option enabled '1'
	option name 'AP1'
	option ipaddr '192.168.1.2'
	option port '22'
	option username 'root'
	option password 'secret'
	option usekeyfile '0'
	option trunk_port 'lan1'
	option mgmt_vlan '1'

config vlan 'vlan10'
	option name 'Guest'
	option vlan_id '10'
	option device 'br-lan'

config wifi 'wifi1'
	option name 'Guest'
	option enabled '1'
	list band '2g'
	list band '5g'
	option ssid 'GuestSSID'
	option encryption 'psk2'
	option key 'pass'
	option hidden '0'
	option isolate '0'
	option network 'lan'
	option vlan 'vlan10'

config group 'group1'
	option name 'Main'
	list host 'host1'
	list wifi 'wifi1'
	option delete '0'
	option useadditionalscript '0'
"""


def test_parse_uci_roundtrip_fields() -> None:
    cfg = parse_uci_export(SAMPLE)
    assert cfg.global_.interval == 5
    assert len(cfg.hosts) == 1
    assert cfg.hosts[0].id == "host1"
    assert cfg.hosts[0].password == "secret"
    assert cfg.hosts[0].trunk_port == "lan1"
    assert cfg.hosts[0].mgmt_vlan == 1
    assert len(cfg.wifis) == 1
    assert cfg.wifis[0].band == ["2g", "5g"]
    assert cfg.wifis[0].vlan == "vlan10"
    assert len(cfg.vlans) == 1
    assert cfg.vlans[0].id == "vlan10"
    assert cfg.vlans[0].vlan_id == 10
    assert cfg.vlans[0].device == "br-lan"
    assert len(cfg.groups) == 1
    assert cfg.groups[0].host == ["host1"]
