from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def load_project_env() -> None:
    project_root = Path(__file__).resolve().parents[2]
    load_env_file(project_root / ".env")
    load_env_file(project_root / "backend" / ".env")
