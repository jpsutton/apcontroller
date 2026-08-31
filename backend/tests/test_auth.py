import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apctl.main import create_app, resolve_bind
from apctl.settings import Settings


def _make_app(tmp_path: Path, **settings_kw):
    cfgp = tmp_path / "config.json"
    cfgp.write_text(
        json.dumps(
            {
                "global": {"interval": 5, "path": "x", "column": ["name"], "clientcolumn": ["mac"]},
                "hosts": [],
                "wifis": [],
                "vlans": [],
                "groups": [],
                "additional_script": "",
            }
        ),
        encoding="utf-8",
    )
    s = Settings(config_path=cfgp, bundle_path=tmp_path / "bundle", state_dir=tmp_path / "state", **settings_kw)
    (s.bundle_path / "scripts").mkdir(parents=True)
    return create_app(s)


def test_no_key_configured_allows_requests(tmp_path: Path) -> None:
    c = TestClient(_make_app(tmp_path))
    assert c.get("/api/v1/status").status_code == 200


def test_key_required_when_configured(tmp_path: Path) -> None:
    c = TestClient(_make_app(tmp_path, api_key="topsecret"))
    assert c.get("/api/v1/status").status_code == 401
    assert c.get("/api/v1/status", headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.get("/api/v1/status", headers={"X-API-Key": "topsecret"}).status_code == 200
    # health stays unauthenticated so probes/SPA load work
    assert c.get("/health").status_code == 200


def test_mutating_route_behind_key(tmp_path: Path) -> None:
    c = TestClient(_make_app(tmp_path, api_key="k"))
    body = {"global": {}, "hosts": [], "wifis": [], "vlans": [], "groups": [], "additional_script": ""}
    assert c.put("/api/v1/config", json=body).status_code == 401
    assert c.put("/api/v1/config", headers={"X-API-Key": "k"}, json=body).status_code == 200


def test_resolve_bind_fails_closed(tmp_path: Path) -> None:
    cfgp = tmp_path / "c.json"
    with pytest.raises(RuntimeError):
        resolve_bind(Settings(config_path=cfgp, host="0.0.0.0"))
    assert resolve_bind(Settings(config_path=cfgp, host="0.0.0.0", api_key="k")) == ("0.0.0.0", 8080)
    assert resolve_bind(
        Settings(config_path=cfgp, host="0.0.0.0", allow_insecure_bind=True)
    ) == ("0.0.0.0", 8080)
    assert resolve_bind(Settings(config_path=cfgp, host="127.0.0.1")) == ("127.0.0.1", 8080)


def test_cors_off_by_default(tmp_path: Path) -> None:
    c = TestClient(_make_app(tmp_path))
    r = c.options(
        "/api/v1/config",
        headers={"Origin": "https://evil.test", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


def test_config_secret_gating_and_preserve(tmp_path: Path) -> None:
    c = TestClient(_make_app(tmp_path, api_key="k"))
    H = {"X-API-Key": "k"}
    cfg = {
        "global": {},
        "hosts": [{"id": "host1", "ipaddr": "192.168.1.2", "username": "root", "password": "s3cret"}],
        "wifis": [{"id": "wifi1", "ssid": "Net", "key": "psk-secret", "encryption": "psk2"}],
        "vlans": [],
        "groups": [],
        "additional_script": "",
    }
    assert c.put("/api/v1/config", headers=H, json=cfg).status_code == 200

    stripped = c.get("/api/v1/config", headers=H).json()
    assert stripped["hosts"][0]["password"] == ""
    assert stripped["wifis"][0]["key"] == ""

    full = c.get("/api/v1/config?include_secrets=true", headers=H).json()
    assert full["hosts"][0]["password"] == "s3cret"

    # Saving the stripped copy must NOT wipe stored secrets.
    assert c.put("/api/v1/config", headers=H, json=stripped).status_code == 200
    after = c.get("/api/v1/config?include_secrets=true", headers=H).json()
    assert after["hosts"][0]["password"] == "s3cret"
    assert after["wifis"][0]["key"] == "psk-secret"


def test_injection_rejected_on_put_config(tmp_path: Path) -> None:
    c = TestClient(_make_app(tmp_path, api_key="k"))
    H = {"X-API-Key": "k"}
    bad = {
        "global": {},
        "hosts": [{"id": "host1", "ipaddr": "-oProxyCommand=touch /tmp/pwn", "username": "root"}],
        "wifis": [],
        "vlans": [],
        "groups": [],
        "additional_script": "",
    }
    assert c.put("/api/v1/config", headers=H, json=bad).status_code == 422


def test_body_size_limit(tmp_path: Path) -> None:
    c = TestClient(_make_app(tmp_path))
    big = "x" * (2 * 1024 * 1024)
    assert c.put("/api/v1/additional-script", content=big).status_code == 413
    assert c.put("/api/v1/additional-script", content="echo hi").status_code == 200


def test_uci_import_bad_returns_422(tmp_path: Path) -> None:
    c = TestClient(_make_app(tmp_path))
    r = c.post("/api/v1/import/uci", json={"uci_text": "config host 'h'\n\toption port 'notanint'\n"})
    assert r.status_code == 422
