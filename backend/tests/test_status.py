import json
from pathlib import Path

from apctl.models import GlobalSection, Host, RootConfig
from apctl.status_service import build_status


def test_build_status_matches_agent_shape(tmp_path: Path) -> None:
    base = tmp_path / "st"
    base.mkdir()
    agent = {
        "hostname": "gw",
        "model": "Test",
        "load": "0.1 0.2 0.3",
        "uptime": 123,
        "mac": "aa:bb",
        "software": "OpenWrt",
        "channels2g": "6",
        "clientslist2g": [
            {
                "ssid": "S",
                "mac": "m",
                "rx": 1,
                "tx": 2,
                "signal": -40,
                "connected": 10,
                "wifi": 5,
                "ipaddr": "192.168.1.5",
                "name": "c",
            }
        ],
    }
    ip = "192.168.1.2"
    hid = "host1"
    (base / f"{ip}-{hid}").write_text(json.dumps(agent), encoding="utf-8")

    cfg = RootConfig.model_validate(
        {
            "global": {"interval": 5, "path": str(base), "column": [], "clientcolumn": []},
            "hosts": [
                {
                    "id": hid,
                    "enabled": True,
                    "name": "AP1",
                    "ipaddr": ip,
                    "port": 22,
                    "username": "root",
                    "password": "",
                }
            ],
            "wifis": [],
            "groups": [],
            "additional_script": "",
        }
    )
    st = build_status(cfg, state_dir=base, include_secrets=False)
    assert "hosts" in st
    h = st["hosts"][0]
    assert h["section"] == hid
    assert h["hostname"] == "gw"
    assert h["lastcontact"] >= 0
    assert len(h["clientslist2g"]) == 1
    assert h["clientslist2g"][0]["signal"] == -40
