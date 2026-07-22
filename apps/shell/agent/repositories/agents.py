"""Agent definition persistence for Agent Studio."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from apps.shell.agent.repositories.sqlite import repository_transaction
from apps.shell.agent.runtime.errors import AgentRuntimeError


class AgentDefinitionRepository:
    """Stores Agent definitions while runtime policy callbacks own validation gates."""

    def __init__(
        self,
        conn: Any,
        *,
        ensure_row_factory: Callable[[], Any],
        row_to_agent: Callable[[Any], dict[str, Any]],
        row_to_agent_private: Callable[[Any], dict[str, Any]],
        coerce_named_row: Callable[[Any, Any], Any],
        main_chat_virtual_agent: Callable[[], dict[str, Any]],
        now: Callable[[], str],
        json_dump: Callable[[Any], str],
        agent_id_factory: Callable[[str], str],
        normalize_execution_backend: Callable[..., str],
        ensure_global_name_available: Callable[..., Any],
        validate_agent_profile_refs: Callable[[dict[str, Any]], Any],
        compile_tool_policy: Callable[[str, Any], dict[str, Any]],
        compile_workspace_policy: Callable[[Any], dict[str, Any]],
        assign_default_agent_workdir: Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]],
        trust_workspace_from_policy: Callable[..., Any],
        agent_model_credential_ref: Callable[[str], str],
        store_credential: Callable[[str, str], Any],
        delete_credential: Callable[[str], Any],
        record_studio_deletion: Callable[[str, str], Any],
        clear_studio_deletion: Callable[[str, str], Any],
        system_agent_ids: set[str],
        main_chat_agent_id: str,
        error_type: type[Exception] = AgentRuntimeError,
    ) -> None:
        self._conn = conn
        self._ensure_row_factory = ensure_row_factory
        self._row_to_agent = row_to_agent
        self._row_to_agent_private = row_to_agent_private
        self._coerce_named_row = coerce_named_row
        self._main_chat_virtual_agent = main_chat_virtual_agent
        self._now = now
        self._json_dump = json_dump
        self._agent_id_factory = agent_id_factory
        self._normalize_execution_backend = normalize_execution_backend
        self._ensure_global_name_available = ensure_global_name_available
        self._validate_agent_profile_refs = validate_agent_profile_refs
        self._compile_tool_policy = compile_tool_policy
        self._compile_workspace_policy = compile_workspace_policy
        self._assign_default_agent_workdir = assign_default_agent_workdir
        self._trust_workspace_from_policy = trust_workspace_from_policy
        self._agent_model_credential_ref = agent_model_credential_ref
        self._store_credential = store_credential
        self._delete_credential = delete_credential
        self._record_studio_deletion = record_studio_deletion
        self._clear_studio_deletion = clear_studio_deletion
        self._system_agent_ids = system_agent_ids
        self._main_chat_agent_id = main_chat_agent_id
        self._error_type = error_type

    def _delete_credential_quietly(self, ref: str) -> None:
        if not str(ref or "").strip():
            return
        try:
            self._delete_credential(ref)
        except Exception:
            # Credential cleanup is compensating and must not hide the primary
            # repository result. Native errors may also contain secret text.
            pass

    def _cleanup_staged_credential_if_unreferenced(
        self,
        *,
        agent_id: str,
        staged_ref: str,
    ) -> None:
        if not staged_ref:
            return
        try:
            row = self._conn.execute(
                "SELECT model_credential_ref FROM agents WHERE agent_id=?",
                (agent_id,),
            ).fetchone()
        except Exception:
            return
        current_ref = (
            str(row["model_credential_ref"] or "").strip()
            if row is not None
            else ""
        )
        if current_ref != staged_ref:
            self._delete_credential_quietly(staged_ref)

    def list(self) -> dict[str, Any]:
        self._ensure_row_factory()
        cursor = self._conn.execute("SELECT * FROM agents ORDER BY category, name")
        rows = cursor.fetchall()
        return {
            "ok": True,
            "agents": [
                self._main_chat_virtual_agent(),
                *[
                    self._row_to_agent(self._coerce_named_row(row, cursor.description))
                    for row in rows
                ],
            ],
        }

    def get(self, agent_id: str) -> dict[str, Any]:
        if str(agent_id or "").strip() == self._main_chat_agent_id:
            return self._main_chat_virtual_agent()
        self._ensure_row_factory()
        cursor = self._conn.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,))
        row = cursor.fetchone()
        if row is None:
            raise KeyError(agent_id)
        return self._row_to_agent(self._coerce_named_row(row, cursor.description))

    def get_private(self, agent_id: str) -> dict[str, Any]:
        if str(agent_id or "").strip() == self._main_chat_agent_id:
            agent = self._main_chat_virtual_agent()
            return {
                **agent,
                "model_config": {
                    **agent["model_config"],
                    "credential_ref": "",
                    "api_key": "",
                },
            }
        for _attempt in range(3):
            self._ensure_row_factory()
            cursor = self._conn.execute(
                "SELECT * FROM agents WHERE agent_id=?",
                (agent_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise KeyError(agent_id)
            named_row = self._coerce_named_row(row, cursor.description)
            credential_ref = str(
                named_row["model_credential_ref"] or ""
            ).strip()
            try:
                agent = self._row_to_agent_private(named_row)
            except Exception:
                if self._current_credential_ref(agent_id) != credential_ref:
                    continue
                raise
            if self._current_credential_ref(agent_id) != credential_ref:
                continue
            return agent
        raise self._error_type("Agent 模型凭据正在更新，请稍后重试")

    def _current_credential_ref(self, agent_id: str) -> str:
        row = self._conn.execute(
            "SELECT model_credential_ref FROM agents WHERE agent_id=?",
            (agent_id,),
        ).fetchone()
        if row is None:
            raise KeyError(agent_id)
        return str(row["model_credential_ref"] or "").strip()

    def create(self, payload: dict[str, Any], *, seed: bool = False) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        self._ensure_global_name_available(name)
        self._validate_agent_profile_refs(payload)
        now = self._now()
        agent_id = str(payload.get("agent_id") or self._agent_id_factory(name))
        if agent_id in self._system_agent_ids:
            raise self._error_type("系统 Agent 不能创建或覆盖")
        model_config = payload.get("model_config") or {}
        category = str(payload.get("category") or "custom")
        model_mode = str(payload.get("model_mode") or "profile")
        execution_backend = self._normalize_execution_backend(payload.get("execution_backend"), model_mode=model_mode)
        tool_policy = self._compile_tool_policy(category, payload.get("tool_policy"))
        workspace_policy = self._compile_workspace_policy(payload.get("workspace_policy"))
        workspace_policy = self._assign_default_agent_workdir(agent_id, workspace_policy, tool_policy)
        self._trust_workspace_from_policy(workspace_policy, source=f"agent:{agent_id}", commit=False)
        api_key = str(model_config.get("api_key") or "").strip()
        credential_ref = self._agent_model_credential_ref(agent_id) if api_key else ""
        if api_key:
            self._store_credential(credential_ref, api_key)
        try:
            self._conn.execute(
                """
                INSERT INTO agents (
                    agent_id, name, nickname, description, avatar_url, category, instructions, persona_prompt,
                    model_mode, execution_backend, model_profile_id, vision_model_profile_id, model_provider,
                    model_base_url, model_name, model_api_key, model_credential_ref,
                    tool_policy_json, workspace_policy_json, skill_ids_json, output_contract,
                    enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id,
                    name,
                    str(payload.get("nickname") or name),
                    str(payload.get("description") or ""),
                    str(payload.get("avatar_url") or ""),
                    category,
                    str(payload.get("instructions") or ""),
                    str(payload.get("persona_prompt") or ""),
                    model_mode,
                    execution_backend,
                    str(payload.get("model_profile_id") or ""),
                    str(payload.get("vision_model_profile_id") or ""),
                    str(model_config.get("provider") or "openai_compatible"),
                    str(model_config.get("base_url") or ""),
                    str(model_config.get("model") or ""),
                    "",
                    credential_ref,
                    self._json_dump(tool_policy),
                    self._json_dump(workspace_policy),
                    self._json_dump(payload.get("skill_ids") or []),
                    str(payload.get("output_contract") or "chat"),
                    1 if payload.get("enabled", True) else 0,
                    now,
                    now,
                ),
            )
        except sqlite3.Error:
            self._delete_credential(credential_ref)
            raise
        if not seed:
            self._clear_studio_deletion("agent", agent_id)
        self._conn.commit()
        return self.get(agent_id)

    def update(self, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if str(agent_id or "").strip() in self._system_agent_ids:
            raise self._error_type("系统 Agent 不能修改")
        rotation = {
            "previous_ref": "",
            "staged_ref": "",
            "credential_ref": "",
        }
        try:
            with repository_transaction(self._conn):
                self._update_in_transaction(agent_id, payload, rotation)
        except Exception:
            self._cleanup_staged_credential_if_unreferenced(
                agent_id=agent_id,
                staged_ref=rotation["staged_ref"],
            )
            raise
        if (
            rotation["previous_ref"]
            and rotation["previous_ref"] != rotation["credential_ref"]
        ):
            self._delete_credential_quietly(rotation["previous_ref"])
        return self.get(agent_id)

    def _update_in_transaction(
        self,
        agent_id: str,
        payload: dict[str, Any],
        rotation: dict[str, str],
    ) -> None:
        current = self.get(agent_id)
        ref_row = self._conn.execute(
            "SELECT model_credential_ref FROM agents WHERE agent_id=?",
            (agent_id,),
        ).fetchone()
        if ref_row is None:
            raise KeyError(agent_id)
        previous_credential_ref = str(
            ref_row["model_credential_ref"] or ""
        ).strip()
        rotation["previous_ref"] = previous_credential_ref
        if "name" in payload:
            self._ensure_global_name_available(str(payload.get("name") or ""), ignore_agent_id=agent_id)
        next_agent = {**current, **{key: value for key, value in payload.items() if key not in {"model_config"}}}
        self._validate_agent_profile_refs(next_agent)
        model_config_patch = payload.get("model_config") or {}
        model_config = {**current.get("model_config", {}), **model_config_patch}
        explicit_api_key = (
            str(model_config_patch.get("api_key") or "").strip()
            if "api_key" in model_config_patch
            else ""
        )
        credential_ref = previous_credential_ref
        now = self._now()
        category = str(next_agent.get("category") or "custom")
        model_mode = str(next_agent.get("model_mode") or "profile")
        execution_backend = self._normalize_execution_backend(next_agent.get("execution_backend"), model_mode=model_mode)
        tool_policy = self._compile_tool_policy(category, next_agent.get("tool_policy"))
        workspace_policy = self._compile_workspace_policy(next_agent.get("workspace_policy"))
        workspace_policy = self._assign_default_agent_workdir(agent_id, workspace_policy, tool_policy)
        self._trust_workspace_from_policy(workspace_policy, source=f"agent:{agent_id}", commit=False)
        staged_credential_ref = ""
        if explicit_api_key:
            staged_credential_ref = (
                f"{self._agent_model_credential_ref(agent_id)}:{uuid4().hex}"
            )
            credential_ref = staged_credential_ref
            rotation["staged_ref"] = staged_credential_ref
            self._store_credential(staged_credential_ref, explicit_api_key)
        rotation["credential_ref"] = credential_ref
        self._conn.execute(
            """
            UPDATE agents
               SET name=?, nickname=?, description=?, avatar_url=?, category=?, instructions=?, persona_prompt=?,
                   model_mode=?, execution_backend=?, model_profile_id=?, vision_model_profile_id=?, model_provider=?,
                   model_base_url=?, model_name=?, model_api_key='', model_credential_ref=?,
                   tool_policy_json=?, workspace_policy_json=?, skill_ids_json=?, output_contract=?,
                   enabled=?, updated_at=?
             WHERE agent_id=?
            """,
            (
                str(next_agent.get("name") or ""),
                str(next_agent.get("nickname") or next_agent.get("name") or ""),
                str(next_agent.get("description") or ""),
                str(next_agent.get("avatar_url") or ""),
                category,
                str(next_agent.get("instructions") or ""),
                str(next_agent.get("persona_prompt") or ""),
                model_mode,
                execution_backend,
                str(next_agent.get("model_profile_id") or ""),
                str(next_agent.get("vision_model_profile_id") or ""),
                str(model_config.get("provider") or "openai_compatible"),
                str(model_config.get("base_url") or ""),
                str(model_config.get("model") or ""),
                credential_ref,
                self._json_dump(tool_policy),
                self._json_dump(workspace_policy),
                self._json_dump(next_agent.get("skill_ids") or []),
                str(next_agent.get("output_contract") or "chat"),
                1 if next_agent.get("enabled", True) else 0,
                now,
                agent_id,
            ),
        )

    def delete(self, agent_id: str) -> dict[str, Any]:
        if str(agent_id or "").strip() in self._system_agent_ids:
            raise self._error_type("系统 Agent 不能删除")
        row = self._conn.execute("SELECT model_credential_ref FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
        if self._conn.execute("SELECT 1 FROM agents WHERE agent_id=?", (agent_id,)).fetchone() is not None:
            self._record_studio_deletion("agent", agent_id)
        self._conn.execute("DELETE FROM agents WHERE agent_id=?", (agent_id,))
        self._conn.commit()
        if row is not None:
            self._delete_credential(str(row["model_credential_ref"] or ""))
        return {"ok": True}
