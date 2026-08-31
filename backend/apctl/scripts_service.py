from __future__ import annotations

import re
from pathlib import Path


def list_scripts(scripts_dir: Path) -> dict:
    items: list[dict] = []
    if not scripts_dir.is_dir():
        return {"scripts": items}
    for p in sorted(scripts_dir.iterdir()):
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^#desc:\s*(.*)$", text, re.MULTILINE)
        desc = m.group(1).strip() if m else p.name
        warn = 1 if re.search(r"^#warn", text, re.MULTILINE) else 0
        items.append({"file": p.name, "description": desc, "warn": warn})
    return {"scripts": items}
