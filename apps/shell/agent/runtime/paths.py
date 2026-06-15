from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def oha_yachiyo_home() -> Path:
    root = Path(os.getenv("OHA_YACHIYO_HOME", os.path.expanduser("~/.oha-yachiyo"))).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def native_skill_home() -> Path:
    return oha_yachiyo_home() / "skill-library"


def agent_workspace_dir(agent: dict[str, Any]) -> str:
    workspace = agent.get("workspace_policy") or {}
    return str(workspace.get("default_workdir") or "").strip()
