import json
from pathlib import Path

from fastapi.testclient import TestClient

from apctl.main import create_app
from apctl.settings import Settings


def test_health_and_status(tmp_path: Path) -> None:
    cfgp = tmp_path / "config.json"
    cfgp.write_text(
        json.dumps(
            {
                "global": {
                    "interval": 5,
                    "path": str(tmp_path / "d"),
                    "column": ["name"],
                    "clientcolumn": ["mac"],
                },
                "hosts": [],
                "wifis": [],
                "groups": [],
                "additional_script": "",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "d").mkdir()
    s = Settings(config_path=cfgp, bundle_path=tmp_path / "bundle")
    (s.bundle_path / "scripts").mkdir(parents=True)
    app = create_app(s)
    c = TestClient(app)
    r = c.get("/health")
    assert r.status_code == 200
    r2 = c.get("/api/v1/status")
    assert r2.status_code == 200
    assert r2.json() == {"hosts": []}
