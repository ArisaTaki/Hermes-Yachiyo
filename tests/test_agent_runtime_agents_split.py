"""Tests for AgentDefinitionRepository split out of the legacy runtime."""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.repositories.agents import AgentDefinitionRepository
from apps.shell.agent.repositories.sqlite import LockedConnection
from apps.shell.agent_runtime import AgentRuntimeError, AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_load(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return fallback


def _connect_agents_db(
    *,
    check_same_thread: bool = True,
    isolation_level: str | None = "",
) -> sqlite3.Connection:
    conn = sqlite3.connect(
        ":memory:",
        check_same_thread=check_same_thread,
        isolation_level=isolation_level,
    )
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE agents (
            agent_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            nickname TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            avatar_url TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT 'custom',
            instructions TEXT NOT NULL DEFAULT '',
            persona_prompt TEXT NOT NULL DEFAULT '',
            model_mode TEXT NOT NULL DEFAULT 'profile',
            execution_backend TEXT NOT NULL DEFAULT 'native_profile',
            model_profile_id TEXT NOT NULL DEFAULT '',
            vision_model_profile_id TEXT NOT NULL DEFAULT '',
            model_provider TEXT NOT NULL DEFAULT '',
            model_base_url TEXT NOT NULL DEFAULT '',
            model_name TEXT NOT NULL DEFAULT '',
            model_api_key TEXT NOT NULL DEFAULT '',
            model_credential_ref TEXT NOT NULL DEFAULT '',
            tool_policy_json TEXT NOT NULL DEFAULT '{}',
            workspace_policy_json TEXT NOT NULL DEFAULT '{}',
            skill_ids_json TEXT NOT NULL DEFAULT '[]',
            output_contract TEXT NOT NULL DEFAULT 'chat',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    return conn


def _row_to_agent(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "agent_id": str(row["agent_id"]),
        "name": str(row["name"]),
        "nickname": str(row["nickname"] or row["name"]),
        "description": str(row["description"]),
        "avatar_url": str(row["avatar_url"]),
        "category": str(row["category"]),
        "instructions": str(row["instructions"]),
        "persona_prompt": str(row["persona_prompt"]),
        "model_mode": str(row["model_mode"]),
        "execution_backend": str(row["execution_backend"]),
        "model_profile_id": str(row["model_profile_id"]),
        "vision_model_profile_id": str(row["vision_model_profile_id"]),
        "model_config": {
            "provider": str(row["model_provider"]),
            "base_url": str(row["model_base_url"]),
            "model": str(row["model_name"]),
            "api_key_configured": bool(str(row["model_credential_ref"] or "").strip() or str(row["model_api_key"] or "").strip()),
        },
        "tool_policy": _json_load(row["tool_policy_json"], {}),
        "workspace_policy": _json_load(row["workspace_policy_json"], {}),
        "skill_ids": _json_load(row["skill_ids_json"], []),
        "output_contract": str(row["output_contract"]),
        "enabled": bool(row["enabled"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


class _RecordingConnection:
    def __init__(self, conn: sqlite3.Connection, events: list[tuple[str, str]]) -> None:
        self._conn = conn
        self._events = events
        self.fail_update = False
        self.fail_commit = False

    def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
        if self.fail_update and sql.lstrip().upper().startswith("UPDATE AGENTS"):
            raise sqlite3.OperationalError("forced agent update failure")
        return self._conn.execute(sql, parameters)

    def commit(self) -> None:
        self._events.append(("commit", ""))
        if self.fail_commit:
            raise sqlite3.OperationalError("forced agent commit failure")
        self._conn.commit()

    def rollback(self) -> None:
        self._events.append(("rollback", ""))
        self._conn.rollback()


class _PostCommitFailureConnection(_RecordingConnection):
    def __init__(self, conn: sqlite3.Connection, events: list[tuple[str, str]]) -> None:
        super().__init__(conn, events)
        self.fail_after_commit = False

    def commit(self) -> None:
        self._events.append(("commit", ""))
        self._conn.commit()
        if self.fail_after_commit:
            raise sqlite3.OperationalError("forced post-commit acknowledgement failure")


class _RecordingCredentials:
    def __init__(self, events: list[tuple[str, str]]) -> None:
        self.events = events
        self.secrets: dict[str, str] = {}
        self.deleted_refs: list[str] = []
        self.unreadable_refs: set[str] = set()

    def store(self, ref: str, secret: str) -> None:
        self.events.append(("store", ref))
        self.secrets[ref] = secret

    def read(self, ref: str) -> str:
        self.events.append(("read", ref))
        if ref in self.unreadable_refs:
            raise AgentRuntimeError("应用更新后无法读取原有钥匙串凭据")
        return self.secrets.get(ref, "")

    def delete(self, ref: str) -> None:
        self.events.append(("delete", ref))
        self.deleted_refs.append(ref)
        self.secrets.pop(ref, None)


class _BlockingReadCredentials(_RecordingCredentials):
    def __init__(self, events: list[tuple[str, str]]) -> None:
        super().__init__(events)
        self.block_ref = ""
        self.read_started = threading.Event()
        self.release_read = threading.Event()

    def read(self, ref: str) -> str:
        self.events.append(("read", ref))
        secret_snapshot = self.secrets.get(ref, "")
        if ref == self.block_ref:
            self.read_started.set()
            if not self.release_read.wait(timeout=3):
                raise AssertionError("timed out waiting to release credential read")
        if ref in self.unreadable_refs:
            raise AgentRuntimeError("应用更新后无法读取原有钥匙串凭据")
        return secret_snapshot


def _agent_repository(
    conn: Any,
    credentials: _RecordingCredentials,
    *,
    trust_workspace_from_policy: Any = None,
) -> AgentDefinitionRepository:
    def row_to_agent_private(row: sqlite3.Row) -> dict[str, Any]:
        agent = _row_to_agent(row)
        credential_ref = str(row["model_credential_ref"] or "")
        agent["model_config"]["credential_ref"] = credential_ref
        agent["model_config"]["api_key"] = credentials.read(credential_ref) if credential_ref else ""
        return agent

    return AgentDefinitionRepository(
        conn,
        ensure_row_factory=lambda: None,
        row_to_agent=_row_to_agent,
        row_to_agent_private=row_to_agent_private,
        coerce_named_row=lambda row, _description: row,
        main_chat_virtual_agent=lambda: {
            "agent_id": "builtin:yachiyo-main",
            "name": "Yachiyo",
            "model_config": {},
        },
        now=lambda: "2026-07-14T10:00:00Z",
        json_dump=_json_dump,
        agent_id_factory=lambda name: f"agent_{name.lower().replace(' ', '_')}",
        normalize_execution_backend=lambda value, *, model_mode: str(value or model_mode),
        ensure_global_name_available=lambda *_args, **_kwargs: None,
        validate_agent_profile_refs=lambda _payload: None,
        compile_tool_policy=lambda _category, policy: policy or {},
        compile_workspace_policy=lambda policy: dict(policy or {}),
        assign_default_agent_workdir=lambda _agent_id, workspace_policy, _tool_policy: workspace_policy,
        trust_workspace_from_policy=(
            trust_workspace_from_policy
            if trust_workspace_from_policy is not None
            else (lambda *_args, **_kwargs: None)
        ),
        agent_model_credential_ref=lambda agent_id: f"agent:{agent_id}:model_api_key",
        store_credential=credentials.store,
        delete_credential=credentials.delete,
        record_studio_deletion=lambda *_args: None,
        clear_studio_deletion=lambda *_args: None,
        system_agent_ids={"builtin:yachiyo-main"},
        main_chat_agent_id="builtin:yachiyo-main",
        error_type=AgentRuntimeError,
    )


def _create_custom_api_agent(repo: AgentDefinitionRepository, api_key: str) -> dict[str, Any]:
    return repo.create(
        {
            "name": "Credential Agent",
            "model_mode": "custom_api",
            "model_config": {
                "provider": "openai_compatible",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": api_key,
            },
        }
    )


def test_agent_definition_repository_remains_exported_from_legacy_runtime_module() -> None:
    assert agent_runtime.AgentDefinitionRepository is AgentDefinitionRepository


def test_agent_definition_repository_lifecycle_and_policy_callbacks() -> None:
    conn = _connect_agents_db()
    now_values = iter(["2026-06-15T10:00:00Z", "2026-06-15T10:01:00Z"])
    credentials: dict[str, str] = {}
    deleted_credentials: list[str] = []
    name_checks: list[tuple[str, str]] = []
    trusted_workspaces: list[tuple[dict[str, Any], str, bool]] = []
    deletion_events: list[tuple[str, str, str]] = []

    def row_to_agent_private(row: sqlite3.Row) -> dict[str, Any]:
        agent = _row_to_agent(row)
        credential_ref = str(row["model_credential_ref"] or "")
        agent["model_config"]["credential_ref"] = credential_ref
        agent["model_config"]["api_key"] = credentials.get(credential_ref, str(row["model_api_key"] or ""))
        return agent

    def ensure_name(name: str, *, ignore_agent_id: str = "", **_: Any) -> None:
        name_checks.append((name, ignore_agent_id))
        if name.strip().lower() == "duplicate":
            raise AgentRuntimeError("Agent/Workflow 名称必须全局唯一")

    repo = AgentDefinitionRepository(
        conn,
        ensure_row_factory=lambda: None,
        row_to_agent=_row_to_agent,
        row_to_agent_private=row_to_agent_private,
        coerce_named_row=lambda row, _description: row,
        main_chat_virtual_agent=lambda: {"agent_id": "builtin:yachiyo-main", "name": "Yachiyo", "model_config": {}},
        now=lambda: next(now_values),
        json_dump=_json_dump,
        agent_id_factory=lambda name: f"agent_{name.lower().replace(' ', '_')}",
        normalize_execution_backend=lambda value, *, model_mode: f"backend:{value or model_mode}",
        ensure_global_name_available=ensure_name,
        validate_agent_profile_refs=lambda payload: payload.setdefault("_profiles_validated", True),
        compile_tool_policy=lambda category, policy: {"allowed_tools": [category], "approval_required": policy or {}},
        compile_workspace_policy=lambda policy: {"default_workdir": str((policy or {}).get("default_workdir") or "")},
        assign_default_agent_workdir=lambda agent_id, workspace_policy, _tool_policy: {
            **workspace_policy,
            "default_workdir": workspace_policy.get("default_workdir") or f"/workspaces/{agent_id}",
        },
        trust_workspace_from_policy=lambda policy, *, source, commit: trusted_workspaces.append((policy, source, commit)),
        agent_model_credential_ref=lambda agent_id: f"agent:{agent_id}:model_api_key",
        store_credential=lambda ref, secret: credentials.__setitem__(ref, secret),
        delete_credential=lambda ref: deleted_credentials.append(ref),
        record_studio_deletion=lambda kind, key: deletion_events.append(("record", kind, key)),
        clear_studio_deletion=lambda kind, key: deletion_events.append(("clear", kind, key)),
        system_agent_ids={"builtin:yachiyo-main"},
        main_chat_agent_id="builtin:yachiyo-main",
        error_type=AgentRuntimeError,
    )

    assert repo.list()["agents"][0]["agent_id"] == "builtin:yachiyo-main"
    created = repo.create(
        {
            "name": "Design Agent",
            "category": "design",
            "model_mode": "custom_api",
            "execution_backend": "external_cli",
            "model_config": {
                "provider": "openai_compatible",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-create",
            },
            "skill_ids": ["skill-1"],
        }
    )

    assert created["agent_id"] == "agent_design_agent"
    assert created["execution_backend"] == "backend:external_cli"
    assert created["model_config"]["api_key_configured"] is True
    assert created["skill_ids"] == ["skill-1"]
    assert credentials == {"agent:agent_design_agent:model_api_key": "sk-create"}
    assert trusted_workspaces == [
        ({"default_workdir": "/workspaces/agent_design_agent"}, "agent:agent_design_agent", False)
    ]
    assert deletion_events == [("clear", "agent", "agent_design_agent")]
    assert repo.get_private("agent_design_agent")["model_config"]["api_key"] == "sk-create"

    updated = repo.update(
        "agent_design_agent",
        {
            "name": "Design Agent v2",
            "enabled": False,
            "model_config": {"model": "demo-model-v2"},
        },
    )
    assert updated["name"] == "Design Agent v2"
    assert updated["enabled"] is False
    assert updated["model_config"]["model"] == "demo-model-v2"
    assert name_checks[-1] == ("Design Agent v2", "agent_design_agent")
    assert credentials == {"agent:agent_design_agent:model_api_key": "sk-create"}

    assert repo.delete("agent_design_agent") == {"ok": True}
    assert deletion_events[-1] == ("record", "agent", "agent_design_agent")
    assert deleted_credentials == ["agent:agent_design_agent:model_api_key"]
    with pytest.raises(AgentRuntimeError, match="系统 Agent"):
        repo.delete("builtin:yachiyo-main")


def test_agent_api_key_recovery_does_not_read_inaccessible_previous_credential() -> None:
    events: list[tuple[str, str]] = []
    credentials = _RecordingCredentials(events)
    conn = _RecordingConnection(_connect_agents_db(), events)
    repo = _agent_repository(conn, credentials)
    old_secret = "sk-old-agent-secret123456"
    new_secret = "sk-new-agent-secret123456"
    created = _create_custom_api_agent(repo, old_secret)
    old_ref = str(
        conn.execute(
            "SELECT model_credential_ref FROM agents WHERE agent_id=?",
            (created["agent_id"],),
        ).fetchone()["model_credential_ref"]
    )
    credentials.unreadable_refs.add(old_ref)
    events.clear()

    updated = repo.update(
        created["agent_id"],
        {"model_config": {"api_key": new_secret}},
    )

    assert ("read", old_ref) not in events
    assert updated["model_config"]["api_key_configured"] is True
    public_output = json.dumps(updated, ensure_ascii=False)
    assert old_secret not in public_output
    assert new_secret not in public_output


def test_agent_api_key_update_rotates_ref_then_deletes_old_ref_after_commit() -> None:
    events: list[tuple[str, str]] = []
    credentials = _RecordingCredentials(events)
    conn = _RecordingConnection(_connect_agents_db(), events)
    repo = _agent_repository(conn, credentials)
    old_secret = "sk-old-agent-secret123456"
    new_secret = "sk-new-agent-secret123456"
    created = _create_custom_api_agent(repo, old_secret)
    old_ref = str(
        conn.execute(
            "SELECT model_credential_ref FROM agents WHERE agent_id=?",
            (created["agent_id"],),
        ).fetchone()["model_credential_ref"]
    )
    events.clear()

    updated = repo.update(
        created["agent_id"],
        {"model_config": {"api_key": new_secret}},
    )
    new_ref = str(
        conn.execute(
            "SELECT model_credential_ref FROM agents WHERE agent_id=?",
            (created["agent_id"],),
        ).fetchone()["model_credential_ref"]
    )

    assert new_ref != old_ref
    assert credentials.secrets[new_ref] == new_secret
    assert old_ref not in credentials.secrets
    assert events.index(("store", new_ref)) < events.index(("commit", ""))
    assert events.index(("commit", "")) < events.index(("delete", old_ref))
    public_output = json.dumps(updated, ensure_ascii=False)
    assert old_secret not in public_output
    assert new_secret not in public_output


@pytest.mark.parametrize("failure_phase", ["update", "commit"])
def test_agent_api_key_update_failure_preserves_old_ref_and_cleans_only_staged_ref(
    failure_phase: str,
) -> None:
    events: list[tuple[str, str]] = []
    credentials = _RecordingCredentials(events)
    raw_conn = _connect_agents_db()
    conn = _RecordingConnection(raw_conn, events)
    repo = _agent_repository(conn, credentials)
    old_secret = "sk-old-agent-secret123456"
    new_secret = "sk-new-agent-secret123456"
    created = _create_custom_api_agent(repo, old_secret)
    old_ref = str(
        conn.execute(
            "SELECT model_credential_ref FROM agents WHERE agent_id=?",
            (created["agent_id"],),
        ).fetchone()["model_credential_ref"]
    )
    events.clear()
    conn.fail_update = failure_phase == "update"
    conn.fail_commit = failure_phase == "commit"

    with pytest.raises(sqlite3.Error) as update_error:
        repo.update(
            created["agent_id"],
            {"model_config": {"api_key": new_secret}},
        )

    staged_refs = [
        ref
        for event, ref in events
        if event == "store"
    ]
    assert len(staged_refs) == 1
    staged_ref = staged_refs[0]
    assert staged_ref != old_ref
    assert credentials.deleted_refs == [staged_ref]
    assert credentials.secrets == {old_ref: old_secret}
    persisted_ref = str(
        raw_conn.execute(
            "SELECT model_credential_ref FROM agents WHERE agent_id=?",
            (created["agent_id"],),
        ).fetchone()["model_credential_ref"]
    )
    assert persisted_ref == old_ref
    error_output = str(update_error.value)
    assert old_secret not in error_output
    assert new_secret not in error_output


def test_agent_concurrent_plain_update_cannot_restore_deleted_credential_ref() -> None:
    events: list[tuple[str, str]] = []
    credentials = _RecordingCredentials(events)
    raw_conn = _connect_agents_db(check_same_thread=False, isolation_level=None)
    conn = LockedConnection(raw_conn, threading.RLock())
    plain_update_paused = threading.Event()
    release_plain_update = threading.Event()
    rotation_reached_policy = threading.Event()
    rotation_done = threading.Event()
    errors: dict[str, BaseException] = {}

    def trust_workspace_from_policy(*_args: Any, **_kwargs: Any) -> None:
        thread_name = threading.current_thread().name
        if thread_name == "plain-agent-update":
            plain_update_paused.set()
            if not release_plain_update.wait(timeout=3):
                raise AssertionError("timed out waiting to release plain agent update")
        elif thread_name == "rotate-agent-key":
            rotation_reached_policy.set()

    repo = _agent_repository(
        conn,
        credentials,
        trust_workspace_from_policy=trust_workspace_from_policy,
    )
    created = _create_custom_api_agent(repo, "sk-old-agent-secret123456")
    agent_id = created["agent_id"]
    old_ref = str(
        conn.execute(
            "SELECT model_credential_ref FROM agents WHERE agent_id=?",
            (agent_id,),
        ).fetchone()["model_credential_ref"]
    )

    def run_plain_update() -> None:
        try:
            repo.update(agent_id, {"description": "plain metadata save"})
        except BaseException as exc:  # pragma: no cover - asserted below
            errors["plain"] = exc

    def run_rotation() -> None:
        try:
            repo.update(
                agent_id,
                {"model_config": {"api_key": "sk-new-agent-secret123456"}},
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors["rotation"] = exc
        finally:
            rotation_done.set()

    plain_thread = threading.Thread(target=run_plain_update, name="plain-agent-update")
    rotation_thread = threading.Thread(target=run_rotation, name="rotate-agent-key")
    plain_thread.start()
    assert plain_update_paused.wait(timeout=2)
    rotation_thread.start()

    # The broken implementation lets rotation finish against the stale snapshot.
    # A transaction-based implementation blocks here; an optimistic one may race
    # but must preserve the newly committed credential ref when the plain save resumes.
    if rotation_reached_policy.wait(timeout=0.5):
        assert rotation_done.wait(timeout=2)
    release_plain_update.set()
    plain_thread.join(timeout=3)
    rotation_thread.join(timeout=3)

    assert not plain_thread.is_alive()
    assert not rotation_thread.is_alive()
    assert errors == {}
    final_ref = str(
        conn.execute(
            "SELECT model_credential_ref FROM agents WHERE agent_id=?",
            (agent_id,),
        ).fetchone()["model_credential_ref"]
    )
    assert final_ref != old_ref
    assert final_ref in credentials.secrets
    assert old_ref not in credentials.secrets


def test_agent_get_private_retries_rotated_ref_without_blocking_public_reads() -> None:
    events: list[tuple[str, str]] = []
    credentials = _BlockingReadCredentials(events)
    raw_conn = _connect_agents_db(check_same_thread=False, isolation_level=None)
    conn = LockedConnection(raw_conn, threading.RLock())
    repo = _agent_repository(conn, credentials)
    old_secret = "sk-old-agent-secret123456"
    new_secret = "sk-new-agent-secret123456"
    created = _create_custom_api_agent(repo, old_secret)
    agent_id = created["agent_id"]
    old_ref = str(
        conn.execute(
            "SELECT model_credential_ref FROM agents WHERE agent_id=?",
            (agent_id,),
        ).fetchone()["model_credential_ref"]
    )
    credentials.block_ref = old_ref
    events.clear()
    results: dict[str, dict[str, Any]] = {}
    errors: dict[str, BaseException] = {}
    public_done = threading.Event()
    rotation_done = threading.Event()

    def run_private_read() -> None:
        try:
            results["private"] = repo.get_private(agent_id)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors["private"] = exc

    def run_public_read() -> None:
        try:
            results["public"] = repo.get(agent_id)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors["public"] = exc
        finally:
            public_done.set()

    def run_rotation() -> None:
        try:
            results["rotation"] = repo.update(
                agent_id,
                {"model_config": {"api_key": new_secret}},
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors["rotation"] = exc
        finally:
            rotation_done.set()

    private_thread = threading.Thread(target=run_private_read, name="private-agent-read")
    public_thread = threading.Thread(target=run_public_read, name="public-agent-read")
    rotation_thread = threading.Thread(target=run_rotation, name="rotate-agent-key")
    private_thread.start()
    assert credentials.read_started.wait(timeout=2)
    public_thread.start()
    public_finished_before_keychain_release = public_done.wait(timeout=1)
    rotation_thread.start()
    rotation_finished_before_keychain_release = rotation_done.wait(timeout=1)
    credentials.release_read.set()

    private_thread.join(timeout=3)
    public_thread.join(timeout=3)
    rotation_thread.join(timeout=3)
    assert public_finished_before_keychain_release
    assert rotation_finished_before_keychain_release
    assert not private_thread.is_alive()
    assert not public_thread.is_alive()
    assert not rotation_thread.is_alive()
    assert errors == {}

    new_ref = str(
        conn.execute(
            "SELECT model_credential_ref FROM agents WHERE agent_id=?",
            (agent_id,),
        ).fetchone()["model_credential_ref"]
    )
    assert new_ref != old_ref
    assert results["private"]["model_config"]["credential_ref"] == new_ref
    assert results["private"]["model_config"]["api_key"] == new_secret
    read_refs = [ref for event, ref in events if event == "read"]
    assert read_refs[0] == old_ref
    assert read_refs[-1] == new_ref


def test_agent_post_commit_error_keeps_persisted_staged_credential() -> None:
    events: list[tuple[str, str]] = []
    credentials = _RecordingCredentials(events)
    raw_conn = _connect_agents_db()
    conn = _PostCommitFailureConnection(raw_conn, events)
    repo = _agent_repository(conn, credentials)
    old_secret = "sk-old-agent-secret123456"
    new_secret = "sk-new-agent-secret123456"
    created = _create_custom_api_agent(repo, old_secret)
    agent_id = created["agent_id"]
    old_ref = str(
        raw_conn.execute(
            "SELECT model_credential_ref FROM agents WHERE agent_id=?",
            (agent_id,),
        ).fetchone()["model_credential_ref"]
    )
    events.clear()
    conn.fail_after_commit = True

    with pytest.raises(sqlite3.OperationalError, match="post-commit"):
        repo.update(
            agent_id,
            {"model_config": {"api_key": new_secret}},
        )

    staged_refs = [ref for event, ref in events if event == "store"]
    assert len(staged_refs) == 1
    staged_ref = staged_refs[0]
    persisted_ref = str(
        raw_conn.execute(
            "SELECT model_credential_ref FROM agents WHERE agent_id=?",
            (agent_id,),
        ).fetchone()["model_credential_ref"]
    )
    assert persisted_ref == staged_ref
    assert staged_ref in credentials.secrets
    assert old_ref in credentials.secrets
    assert staged_ref not in credentials.deleted_refs


def test_native_runtime_uses_split_agent_definition_repository(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
    )
    try:
        agent = service.create_agent({"name": "Runtime Agent"})

        assert isinstance(service.agent_definitions, AgentDefinitionRepository)
        assert service.get_agent(agent["agent_id"])["name"] == "Runtime Agent"
        assert service.update_agent(agent["agent_id"], {"enabled": False})["enabled"] is False
        assert service.delete_agent(agent["agent_id"]) == {"ok": True}
    finally:
        service.close()
