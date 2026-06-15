from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def oha_yachiyo_home() -> Path:
    root = Path(os.getenv("OHA_YACHIYO_HOME", os.path.expanduser("~/.oha-yachiyo"))).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def native_skill_home() -> Path:
    return oha_yachiyo_home() / "skill-library"


@dataclass(frozen=True)
class RuntimeDirectoryLayout:
    root: Path
    db_path: Path
    skills_dir: Path
    skill_installs_dir: Path
    skill_installs_native_home: Path
    agent_artifacts_dir: Path
    workflow_artifacts_dir: Path
    agent_workspaces_dir: Path

    def ensure(self) -> "RuntimeDirectoryLayout":
        for path in (
            self.root,
            self.skills_dir,
            self.skill_installs_dir,
            self.skill_installs_native_home,
            self.agent_artifacts_dir,
            self.workflow_artifacts_dir,
            self.agent_workspaces_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return self


def runtime_directory_layout(
    workspace_dir: Path | str | None = None,
    db_path: Path | str | None = None,
) -> RuntimeDirectoryLayout:
    root = Path(workspace_dir) if workspace_dir is not None else oha_yachiyo_home()
    skill_installs_dir = root / "skill-installs"
    return RuntimeDirectoryLayout(
        root=root,
        db_path=Path(db_path) if db_path is not None else root / "agent-runtime.db",
        skills_dir=root / "skills",
        skill_installs_dir=skill_installs_dir,
        skill_installs_native_home=skill_installs_dir / "native-home",
        agent_artifacts_dir=root / "artifacts" / "agent-runs",
        workflow_artifacts_dir=root / "artifacts" / "workflow-runs",
        agent_workspaces_dir=root / "workspaces" / "agents",
    ).ensure()


def agent_workspace_dir(agent: dict[str, Any]) -> str:
    workspace = agent.get("workspace_policy") or {}
    return str(workspace.get("default_workdir") or "").strip()
