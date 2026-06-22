"""Main chat runtime config helpers for the legacy engine entrypoint."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence


class MainChatRuntimeConfigBuilder:
    """Builds the runtime agent config used by the daily Chat entrypoint."""

    def __init__(
        self,
        *,
        main_chat_agent_id: str,
        agent_workspaces_dir: Path,
        workspace_status: Callable[[], dict[str, Any]],
        compile_tool_policy: Callable[[str, Any], dict[str, Any]],
        compile_workspace_policy: Callable[[Any], dict[str, Any]],
        trust_workspace_from_policy: Callable[..., None],
        memory_tool_names: Sequence[str],
        future_task_tool_names: Sequence[str],
        desktop_tool_names: Sequence[str] = (),
        default_workspace_name: str = "builtin-yachiyo-main",
    ) -> None:
        self._main_chat_agent_id = main_chat_agent_id
        self._agent_workspaces_dir = agent_workspaces_dir
        self._workspace_status = workspace_status
        self._compile_tool_policy = compile_tool_policy
        self._compile_workspace_policy = compile_workspace_policy
        self._trust_workspace_from_policy = trust_workspace_from_policy
        self._memory_tool_names = list(memory_tool_names)
        self._future_task_tool_names = list(future_task_tool_names)
        self._desktop_tool_names = list(desktop_tool_names)
        self._default_workspace_name = default_workspace_name

    def _default_workspace_dir(self) -> Path:
        return self._agent_workspaces_dir / self._default_workspace_name

    def workspace_policy(self, policy: dict[str, Any] | None = None) -> dict[str, Any]:
        if isinstance(policy, dict):
            compiled = self._compile_workspace_policy(policy)
        else:
            workspace = self._workspace_status()
            dirs = workspace.get("dirs") if isinstance(workspace.get("dirs"), dict) else {}
            if workspace.get("initialized") and dirs.get("projects"):
                workdir = Path(str(dirs["projects"]))
            else:
                workdir = self._default_workspace_dir()
            workdir.mkdir(parents=True, exist_ok=True)
            compiled = self._compile_workspace_policy(
                {
                    "default_workdir": str(workdir),
                    "readable_scopes": ["."],
                    "writable_scopes": [],
                }
            )
        if not str(compiled.get("default_workdir") or "").strip():
            workdir = self._default_workspace_dir()
            workdir.mkdir(parents=True, exist_ok=True)
            compiled = {**compiled, "default_workdir": str(workdir)}
        self._trust_workspace_from_policy(compiled, source="main_chat", commit=True)
        return compiled

    def virtual_workspace_policy(self) -> dict[str, Any]:
        return self._compile_workspace_policy(
            {
                "default_workdir": str(self._default_workspace_dir()),
                "readable_scopes": ["."],
                "writable_scopes": [],
            }
        )

    def tool_policy(self, policy: dict[str, Any] | None = None) -> dict[str, Any]:
        raw = policy if isinstance(policy, dict) else {
            "allowed_tools": [
                "workspace.list",
                "workspace.read",
                *self._desktop_tool_names,
                *self._memory_tool_names,
                *self._future_task_tool_names,
                "artifact.write",
            ]
        }
        return self._compile_tool_policy("custom", raw)

    def agent_config(
        self,
        *,
        model_profile_id: str,
        tool_policy: dict[str, Any] | None = None,
        workspace_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "agent_id": self._main_chat_agent_id,
            "name": "Yachiyo",
            "nickname": "Yachiyo",
            "category": "orchestrator",
            "instructions": "Main chat native agent.",
            "persona_prompt": "",
            "model_mode": "profile",
            "execution_backend": "native_profile",
            "model_profile_id": str(model_profile_id or "").strip(),
            "vision_model_profile_id": "",
            "model_config": {},
            "tool_policy": self.tool_policy(tool_policy),
            "workspace_policy": self.workspace_policy(workspace_policy),
            "skill_ids": [],
            "output_contract": "chat",
            "enabled": True,
        }

    def virtual_agent(self, *, default_profile_id: str = "") -> dict[str, Any]:
        clean_profile_id = str(default_profile_id or "").strip()
        return {
            "agent_id": self._main_chat_agent_id,
            "name": "Yachiyo",
            "nickname": "Yachiyo",
            "description": "Oha-Yachiyo main chat system agent.",
            "avatar_url": "",
            "category": "orchestrator",
            "instructions": "Main chat native agent.",
            "persona_prompt": "",
            "model_mode": "profile",
            "execution_backend": "native_profile",
            "model_profile_id": clean_profile_id,
            "vision_model_profile_id": "",
            "model_config": {
                "provider": "model_profile",
                "base_url": "",
                "model": "",
                "api_key_configured": bool(clean_profile_id),
            },
            "tool_policy": self.tool_policy(),
            "workspace_policy": self.virtual_workspace_policy(),
            "skill_ids": [],
            "output_contract": "chat",
            "enabled": True,
            "virtual": True,
            "system": True,
            "builtin": True,
            "editable": False,
            "deletable": False,
            "created_at": "",
            "updated_at": "",
        }


class MainChatVirtualAgentProjector:
    """Projects the built-in daily chat Agent with the current default profile."""

    def __init__(
        self,
        *,
        main_chat_config: MainChatRuntimeConfigBuilder,
        default_profile_id: Callable[[], str],
    ) -> None:
        self._main_chat_config = main_chat_config
        self._default_profile_id = default_profile_id

    def virtual_agent(self) -> dict[str, Any]:
        try:
            default_profile_id = str(self._default_profile_id() or "").strip()
        except Exception:
            default_profile_id = ""
        return self._main_chat_config.virtual_agent(default_profile_id=default_profile_id)
