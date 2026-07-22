"""Release invariants for consent-bound durable memory retrieval."""

from __future__ import annotations

import hashlib
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.core.executor import build_cross_session_memory_context
from apps.shell.agent.repositories.memories import MemoryQuery
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.memory_services import issue_user_memory_consent_capability
from apps.shell.agent.tools.broker import ToolBroker
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def _service(tmp_path) -> AgentRuntimeService:
    return AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def test_model_unconfirmed_memory_is_not_retrieved_by_agent_query(tmp_path) -> None:
    service = _service(tmp_path)
    try:
        candidate = service.memory_services.memory_store(
            source_run_id="run-agent",
            source_session_id="session-a",
            source_message_id="message-a",
        ).add(
            content="The user prefers cobalt blue.",
            kind="preference",
            scope="session",
        )

        assert candidate["memory"]["user_confirmed"] is False
        assert candidate["memory"]["actor"] == "agent_tool"
        assert service.memory_services.query_items(
            MemoryQuery(session_id="session-a")
        ) == []
        assert "cobalt blue" not in service.memory_services.context_for(
            session_id="session-a"
        )
        missing_replace = service.memory_services.memory_store(
            source_run_id="run-agent",
            source_session_id="session-a",
            source_message_id="message-a",
        ).replace(
            memory_id="missing",
            content="replacement",
        )
        assert all(
            item["memory_id"] != candidate["memory"]["memory_id"]
            for item in missing_replace["available_memories"]
        )
    finally:
        service.close()


def test_explicit_user_consent_confirms_candidate_with_bound_receipt(tmp_path) -> None:
    service = _service(tmp_path)
    content = "The user prefers concise Chinese replies."
    try:
        candidate = service.memory_services.memory_store(
            source_run_id="run-consent",
            source_session_id="session-consent",
            source_message_id="message-consent",
        ).add(content=content, kind="preference", scope="session")["memory"]

        issued = issue_user_memory_consent_capability(
            service.memory_services,
            candidate["memory_id"],
        )
        confirmed = service.memory_services.confirm_item(
            candidate["memory_id"],
            issued["consent_receipt"],
        )

        assert confirmed["memory"]["user_confirmed"] is True
        assert confirmed["memory"]["actor"] == "agent_tool"
        assert confirmed["consent_receipt"]["run_id"] == "run-consent"
        assert confirmed["consent_receipt"]["source_message_id"] == "message-consent"
        assert [
            item["memory_id"]
            for item in service.memory_services.query_items(
                MemoryQuery(session_id="session-consent")
            )
        ] == [candidate["memory_id"]]
    finally:
        service.close()


def test_agent_replace_stays_candidate_until_bound_user_confirmation(tmp_path) -> None:
    service = _service(tmp_path)
    replacement_content = "The user prefers detailed release reports."
    try:
        store = service.memory_services.memory_store(
            source_run_id="run-replace",
            source_message_id="message-replace",
        )
        candidate = store.add(
            content="The user prefers concise release reports.",
            scope="global",
        )["memory"]
        replacement = store.replace(
            memory_id=candidate["memory_id"],
            content=replacement_content,
        )["memory"]

        before_confirmation = service.memory_services.query_items(MemoryQuery())
        assert replacement["memory_id"] == candidate["memory_id"]
        assert replacement["user_confirmed"] is False
        assert before_confirmation == []

        issued = issue_user_memory_consent_capability(
            service.memory_services,
            replacement["memory_id"],
        )
        confirmed = service.memory_services.confirm_item(
            replacement["memory_id"],
            issued["consent_receipt"],
        )
        after_confirmation = service.memory_services.query_items(MemoryQuery())

        assert confirmed["ok"] is True
        assert [item["memory_id"] for item in after_confirmation] == [
            replacement["memory_id"]
        ]
    finally:
        service.close()


def test_consent_receipt_rejects_tool_or_mismatched_identity(tmp_path) -> None:
    service = _service(tmp_path)
    content = "The user prefers short updates."
    try:
        candidate = service.memory_services.memory_store(
            source_run_id="run-bound",
            source_session_id="session-bound",
            source_message_id="message-bound",
        ).add(content=content, scope="session")["memory"]

        for receipt in (
            {
                "actor": "agent_tool",
                "run_id": "run-bound",
                "source_message_id": "message-bound",
                "content_hash": _hash(content),
                "scope": "session",
            },
            {
                "actor": "user",
                "run_id": "another-run",
                "source_message_id": "message-bound",
                "content_hash": _hash(content),
                "scope": "session",
            },
        ):
            result = service.memory_services.confirm_item(candidate["memory_id"], receipt)
            assert result["ok"] is False

        assert service.memory_services.query_items(
            MemoryQuery(session_id="session-bound")
        ) == []
    finally:
        service.close()


def test_predictable_memory_consent_receipt_cannot_confirm_agent_candidate(tmp_path) -> None:
    service = _service(tmp_path)
    content = "The user prefers release notes in Chinese."
    try:
        candidate = service.memory_services.memory_store(
            source_run_id="run-forged",
            source_session_id="session-forged",
            source_message_id="message-forged",
        ).add(content=content, scope="session")["memory"]

        forged = service.memory_services.confirm_item(
            candidate["memory_id"],
            {
                "actor": "user",
                "run_id": "run-forged",
                "source_message_id": "message-forged",
                "content_hash": _hash(content),
                "scope": "session",
            },
        )

        assert forged == {
            "ok": False,
            "action": "memory.confirm",
            "error": "consent_capability_invalid",
        }
        assert service.memory_services.query_items(
            MemoryQuery(session_id="session-forged")
        ) == []
    finally:
        service.close()


@pytest.mark.asyncio
async def test_user_api_issues_single_use_memory_consent_capability(
    tmp_path,
    monkeypatch,
) -> None:
    from apps.bridge.routes import agents as agent_routes

    service = _service(tmp_path)
    content = "The user prefers explicit consent capabilities."
    monkeypatch.setattr(agent_routes, "_agent_runtime_service", lambda _request=None: service)
    try:
        candidate = service.memory_services.memory_store(
            source_run_id="run-capability",
            source_session_id="session-capability",
            source_message_id="message-capability",
        ).add(content=content, scope="session")["memory"]

        with pytest.raises(
            AgentRuntimeError,
            match="^memory_consent_user_action_required$",
        ):
            service.memory_services.issue_consent_capability(candidate["memory_id"])

        issued = await agent_routes.issue_memory_consent_capability(
            candidate["memory_id"]
        )
        receipt = issued["consent_receipt"]
        listed = await agent_routes.list_memories()
        confirmed = await agent_routes.update_memory(
            candidate["memory_id"],
            agent_routes.MemoryRequest(
                user_confirmed=True,
                consent_receipt=receipt,
            ),
        )
        replayed = await agent_routes.update_memory(
            candidate["memory_id"],
            agent_routes.MemoryRequest(
                user_confirmed=True,
                consent_receipt=receipt,
            ),
        )

        assert receipt["token"]
        assert receipt["memory_id"] == candidate["memory_id"]
        assert receipt["run_id"] == "run-capability"
        assert receipt["source_message_id"] == "message-capability"
        assert receipt["content_hash"] == _hash(content)
        assert receipt["scope"] == "session"
        assert receipt["version"]
        assert "token" not in listed["memories"][0]
        assert "consent_receipt" not in listed["memories"][0]
        assert confirmed["ok"] is True
        assert confirmed["memory"]["user_confirmed"] is True
        assert replayed == {
            "ok": False,
            "action": "memory.confirm",
            "error": "consent_capability_invalid",
        }
    finally:
        service.close()


def test_main_chat_run_binds_agent_candidate_to_user_message_receipt(tmp_path) -> None:
    service = _service(tmp_path)
    content = "Remember this only after explicit confirmation."
    try:
        run = service.start_main_chat_run(
            task_id="task-chat-memory",
            session_id="session-chat-memory",
            user_goal="Remember my preference",
            metadata={"source_message_id": "message-chat-memory"},
        )
        candidate = service._memory_store(source_run_id=run["run_id"]).add(
            content=content,
            scope="session",
        )["memory"]

        assert candidate["source_session_id"] == "session-chat-memory"
        assert candidate["source_message_id"] == "message-chat-memory"
        assert candidate["source_task_id"] == "task-chat-memory"
        issued = issue_user_memory_consent_capability(
            service.memory_services,
            candidate["memory_id"],
        )
        assert service.memory_services.confirm_item(
            candidate["memory_id"],
            issued["consent_receipt"],
        )["ok"] is True
    finally:
        service.close()


def test_memory_query_enforces_exact_project_and_session_scope(tmp_path) -> None:
    service = _service(tmp_path)
    try:
        global_memory = service.create_memory_item(
            {"content": "Global preference", "scope": "global"}
        )["memory"]
        project_a = service.create_memory_item(
            {
                "content": "Project A preference",
                "scope": "project",
                "project_id": "project-a",
            }
        )["memory"]
        service.create_memory_item(
            {
                "content": "Project B preference",
                "scope": "project",
                "project_id": "project-b",
            }
        )
        session_a = service.create_memory_item(
            {
                "content": "Session A preference",
                "scope": "session",
                "source_session_id": "session-a",
            }
        )["memory"]
        service.create_memory_item(
            {
                "content": "Session B preference",
                "scope": "session",
                "source_session_id": "session-b",
            }
        )

        retrieved = service.memory_services.query_items(
            MemoryQuery(session_id="session-a", project_id="project-a")
        )

        assert {item["memory_id"] for item in retrieved} == {
            global_memory["memory_id"],
            project_a["memory_id"],
            session_a["memory_id"],
        }
        assert all(item["user_confirmed"] and item["enabled"] for item in retrieved)
    finally:
        service.close()


def test_agent_tool_cannot_delete_memory_from_another_session_by_id(tmp_path) -> None:
    service = _service(tmp_path)
    try:
        other_session = service.create_memory_item(
            {
                "content": "Session B private preference",
                "scope": "session",
                "source_session_id": "session-b",
            }
        )["memory"]
        broker = ToolBroker(
            {"default_workdir": str(tmp_path), "readable_scopes": ["."]},
            tmp_path / "artifacts",
            memory_store=service.memory_services.memory_store(
                source_run_id="run-session-a",
                source_session_id="session-a",
                source_message_id="message-session-a",
            ),
        )

        denied = broker.call(
            "memory.remove",
            {"memory_id": other_session["memory_id"], "reason": "cross-scope attempt"},
        )

        assert denied["ok"] is False
        assert [
            item["memory_id"]
            for item in service.memory_services.query_items(
                MemoryQuery(session_id="session-b", include_global=False)
            )
        ] == [other_session["memory_id"]]
    finally:
        service.close()


def test_agent_tool_cannot_replace_memory_from_another_project_by_content(tmp_path) -> None:
    service = _service(tmp_path)
    try:
        other_project = service.create_memory_item(
            {
                "content": "Shared-looking project preference",
                "scope": "project",
                "project_id": "project-b",
            }
        )["memory"]
        broker = ToolBroker(
            {"default_workdir": str(tmp_path), "readable_scopes": ["."]},
            tmp_path / "artifacts",
            memory_store=service.memory_services.memory_store(
                source_run_id="run-project-a",
                source_message_id="message-project-a",
                project_id="project-a",
            ),
        )

        denied = broker.call(
            "memory.replace",
            {
                "old_content": "Shared-looking project preference",
                "content": "Cross-project replacement",
            },
        )

        assert denied["ok"] is False
        assert [
            item["content"]
            for item in service.memory_services.query_items(
                MemoryQuery(project_id="project-b", include_global=False)
            )
        ] == [other_project["content"]]
    finally:
        service.close()


def test_agent_tool_requires_approval_to_replace_confirmed_visible_memory(tmp_path) -> None:
    service = _service(tmp_path)
    try:
        confirmed = service.create_memory_item(
            {
                "content": "Original session preference",
                "scope": "session",
                "source_session_id": "session-a",
            }
        )["memory"]
        broker = ToolBroker(
            {"default_workdir": str(tmp_path), "readable_scopes": ["."]},
            tmp_path / "artifacts",
            memory_store=service.memory_services.memory_store(
                source_run_id="run-session-a",
                source_session_id="session-a",
                source_message_id="message-session-a",
            ),
        )

        pending = broker.call(
            "memory.replace",
            {
                "memory_id": confirmed["memory_id"],
                "content": "Approved replacement preference",
            },
        )
        before_approval = service.memory_services.query_items(
            MemoryQuery(session_id="session-a", include_global=False)
        )
        replaced = broker.call(
            "memory.replace",
            {
                "memory_id": confirmed["memory_id"],
                "content": "Approved replacement preference",
            },
            approved=True,
        )

        assert pending["approval_required"] is True
        assert [item["content"] for item in before_approval] == ["Original session preference"]
        assert replaced["ok"] is True
        assert replaced["memory"]["memory_id"] == confirmed["memory_id"]
        assert replaced["memory"]["content"] == "Approved replacement preference"
        assert replaced["memory"]["user_confirmed"] is True
    finally:
        service.close()


def test_agent_tool_requires_approval_to_remove_confirmed_visible_memory(tmp_path) -> None:
    service = _service(tmp_path)
    try:
        confirmed = service.create_memory_item(
            {
                "content": "Keep until approved",
                "scope": "session",
                "source_session_id": "session-a",
            }
        )["memory"]
        broker = ToolBroker(
            {"default_workdir": str(tmp_path), "readable_scopes": ["."]},
            tmp_path / "artifacts",
            memory_store=service.memory_services.memory_store(
                source_run_id="run-session-a",
                source_session_id="session-a",
                source_message_id="message-session-a",
            ),
        )

        pending = broker.call("memory.remove", {"memory_id": confirmed["memory_id"]})
        still_present = service.memory_services.query_items(
            MemoryQuery(session_id="session-a", include_global=False)
        )
        removed = broker.call(
            "memory.remove",
            {"memory_id": confirmed["memory_id"], "reason": "approved forget"},
            approved=True,
        )

        assert pending["approval_required"] is True
        assert [item["memory_id"] for item in still_present] == [confirmed["memory_id"]]
        assert removed["ok"] is True
        assert service.memory_services.query_items(
            MemoryQuery(session_id="session-a", include_global=False)
        ) == []
    finally:
        service.close()


def test_manual_memory_records_user_actor_and_source_provenance(tmp_path) -> None:
    service = _service(tmp_path)
    try:
        created = service.create_memory_item(
            {
                "content": "Manual durable preference",
                "kind": "preference",
                "scope": "session",
                "source_session_id": "session-manual",
                "source_message_id": "message-manual",
            }
        )["memory"]
        event = service._conn.execute(
            "SELECT actor FROM memory_events WHERE memory_id=? ORDER BY created_at LIMIT 1",
            (created["memory_id"],),
        ).fetchone()

        assert created["actor"] == "user"
        assert created["user_confirmed"] is True
        assert created["source_session_id"] == "session-manual"
        assert created["source_message_id"] == "message-manual"
        assert event["actor"] == "user"
    finally:
        service.close()


def test_explicit_invalid_memory_scope_is_rejected_instead_of_widened_to_global(
    tmp_path,
) -> None:
    service = _service(tmp_path)
    try:
        with pytest.raises(AgentRuntimeError, match="^memory_scope_invalid$"):
            service.create_memory_item(
                {"content": "Must not become global", "scope": "sessoin"}
            )

        assert service.list_memory_items()["memories"] == []
        assert service.create_memory_item({"content": "Compatible default"})["memory"][
            "scope"
        ] == "global"
    finally:
        service.close()


@pytest.mark.asyncio
async def test_agent_memory_api_reports_stable_invalid_scope_error(
    tmp_path,
    monkeypatch,
) -> None:
    from apps.bridge.routes import agents as agent_routes

    service = _service(tmp_path)
    monkeypatch.setattr(agent_routes, "_agent_runtime_service", lambda _request=None: service)
    try:
        with pytest.raises(HTTPException) as exc_info:
            await agent_routes.create_memory(
                agent_routes.MemoryRequest(
                    content="Must not become global through API",
                    scope="not-a-scope",
                )
            )

        error = exc_info.value
        assert getattr(error, "status_code", None) == 400
        assert getattr(error, "detail", None) == "memory_scope_invalid"
        assert service.list_memory_items()["memories"] == []
    finally:
        service.close()


def test_memory_privacy_migration_preserves_manual_items_as_confirmed(tmp_path) -> None:
    db_path = tmp_path / "agent-runtime.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE memory_items (
            memory_id TEXT PRIMARY KEY,
            scope TEXT NOT NULL DEFAULT 'global',
            kind TEXT NOT NULL DEFAULT 'fact',
            content TEXT NOT NULL,
            project_id TEXT NOT NULL DEFAULT '',
            source_session_id TEXT NOT NULL DEFAULT '',
            source_message_id TEXT NOT NULL DEFAULT '',
            source_task_id TEXT NOT NULL DEFAULT '',
            source_run_id TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL DEFAULT 1.0,
            pinned INTEGER NOT NULL DEFAULT 0,
            user_confirmed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO memory_items (
            memory_id, content, source_run_id, created_at, updated_at
        ) VALUES (
            'memory-legacy-manual', 'Legacy manual preference', 'manual',
            '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'
        );
        """
    )
    conn.commit()
    conn.close()

    service = AgentRuntimeService(
        db_path=db_path,
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        recalled = service.memory_services.query_items(MemoryQuery())

        assert recalled[0]["memory_id"] == "memory-legacy-manual"
        assert recalled[0]["enabled"] is True
        assert recalled[0]["user_confirmed"] is True
        assert recalled[0]["actor"] == "user"
    finally:
        service.close()


def test_delete_and_disable_immediately_remove_memory_from_chat_and_agent_context(
    tmp_path,
) -> None:
    service = _service(tmp_path)
    try:
        disabled = service.create_memory_item(
            {"content": "Disable me", "scope": "global"}
        )["memory"]
        deleted = service.create_memory_item(
            {"content": "Delete me", "scope": "global"}
        )["memory"]
        service.update_memory_item(disabled["memory_id"], {"enabled": False})
        service.delete_memory_item(deleted["memory_id"], reason="user forget request")

        agent_context = service._long_term_memory_context()
        chat_context = build_cross_session_memory_context(
            "session-current",
            memory_service=service.memory_services,
        )

        assert "Disable me" not in agent_context
        assert "Delete me" not in agent_context
        assert "Disable me" not in chat_context
        assert "Delete me" not in chat_context
    finally:
        service.close()


def test_main_chat_does_not_bypass_managed_memory_with_raw_history() -> None:
    raw_store = SimpleNamespace(
        list_sessions=lambda limit=80: [SimpleNamespace(session_id="old")],
        load_messages=lambda _session_id, limit=0: [
            SimpleNamespace(
                role="user",
                content="请记住：raw history must never become durable memory",
            )
        ],
    )
    managed = SimpleNamespace(context_for=lambda **_query: "")

    context = build_cross_session_memory_context(
        "current",
        store=raw_store,
        memory_service=managed,
    )

    assert context == ""
    assert "raw history" not in context


def test_workflow_agent_retrieves_only_authoritative_confirmed_memory(
    tmp_path,
    monkeypatch,
) -> None:
    service = _service(tmp_path)
    calls: list[list[dict]] = []
    try:
        service.create_memory_item(
            {"content": "Confirmed workflow preference", "scope": "global"}
        )
        service._memory_store(source_run_id="run-untrusted-workflow").add(
            content="Unconfirmed workflow candidate",
            scope="global",
        )

        def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
            calls.append(messages)
            visible = "\n".join(str(message.get("content") or "") for message in messages)
            assert "Confirmed workflow preference" in visible
            assert "Unconfirmed workflow candidate" not in visible
            return {"content": "Used confirmed memory only"}

        monkeypatch.setattr(
            "apps.shell.agent_runtime.openai_compatible_chat_message",
            fake_chat,
        )
        agent = service.create_agent(
            {
                "name": "Memory Privacy Workflow Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "test-key",
                },
            }
        )
        workflow = service.create_workflow(
            {
                "name": "Memory Privacy Workflow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "agent",
                        "type": "agent",
                        "data": {
                            "label": "Recall",
                            "agent_id": agent["agent_id"],
                            "task": "Summarize the confirmed preference",
                        },
                    },
                ],
                "edges": [{"source": "start", "target": "agent"}],
            }
        )

        run = service.create_workflow_run(
            {
                "workflow_id": workflow["workflow_id"],
                "user_goal": "Summarize the confirmed preference",
            }
        )

        assert run["status"] == "completed"
        assert calls
    finally:
        service.close()
