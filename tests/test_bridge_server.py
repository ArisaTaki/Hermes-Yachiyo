"""Bridge Server 测试。"""

import asyncio
import base64
import importlib.util
import inspect
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import apps.core.activity_store as activity_store_mod
import apps.core.chat_store as chat_store_mod
import apps.locald.screenshot as screenshot_mod
from apps.bridge.routes import agents as agent_routes
from apps.bridge.routes import live2d as live2d_route
from apps.bridge.routes import model_profiles as model_profile_routes
from apps.bridge.routes import runs as run_routes
from apps.bridge.routes import ui as ui_routes
from apps.bridge.server import (
    _bridge_access_log_enabled,
    app,
    bridge_request_violation,
    debug_routes_enabled,
    get_live2d_asset_token,
    regenerate_live2d_asset_token,
)
import apps.shell.chat_api as chat_api_mod
from apps.core.activity_store import ActivityStore
from apps.core.chat_session import ChatSession
from apps.core.chat_store import ChatStore
from apps.core.executor import NativeAgentExecutor
from apps.core.state import AppState
from apps.core.task_runner import TaskRunner
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore
from packages.protocol.enums import TaskStatus


class _FakeDefaultProfileService:
    def get_defaults(self):
        return {"chat": "profile_default"}

    def get_profile_private(self, profile_id):
        assert profile_id == "profile_default"
        return {
            "profile_id": profile_id,
            "provider": "openai_compatible",
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
            "capability": "chat",
            "status": "available",
            "enabled": True,
        }


def _load_status_route_module():
    path = Path(__file__).resolve().parents[1] / "apps" / "bridge" / "routes" / "status.py"
    spec = importlib.util.spec_from_file_location("_oha_status_route_under_test", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module_matches_prefix(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes)


def _unload_module_prefixes(prefixes: tuple[str, ...]) -> dict[str, object]:
    saved = {
        name: module
        for name, module in list(sys.modules.items())
        if _module_matches_prefix(name, prefixes)
    }
    for name in list(sys.modules):
        if _module_matches_prefix(name, prefixes):
            sys.modules.pop(name, None)
    return saved


def _restore_module_prefixes(prefixes: tuple[str, ...], saved: dict[str, object]) -> None:
    for name in list(sys.modules):
        if _module_matches_prefix(name, prefixes):
            sys.modules.pop(name, None)
    sys.modules.update(saved)


def test_bridge_app_enables_local_webview_cors():
    middleware = getattr(app, "user_middleware", [])
    cors_entry = next(
        (item for item in middleware if getattr(getattr(item, "cls", None), "__name__", "") == "CORSMiddleware"),
        None,
    )

    assert cors_entry is not None
    assert cors_entry.options["allow_origins"] == []
    assert cors_entry.options["allow_origin_regex"] == r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$"
    assert cors_entry.options["allow_methods"] == ["*"]
    assert cors_entry.options["allow_headers"] == ["*"]


def test_bridge_registers_redacting_http_exception_handler():
    try:
        from fastapi import HTTPException
    except ModuleNotFoundError:
        pytest.skip("FastAPI is not installed")

    handlers = getattr(app, "exception_handlers", None)
    if handlers is None:
        pytest.skip("FastAPI test double does not expose exception handler registry")

    assert HTTPException in handlers


def test_bridge_bad_request_helpers_redact_secret_details():
    secret_error = RuntimeError("provider failed api_key=sk-route-secret123456")

    agent_exc = agent_routes._bad_request(secret_error)
    model_exc = model_profile_routes._bad_request(secret_error)

    assert "sk-route-secret123456" not in agent_exc.detail
    assert "api_key=[redacted]" in agent_exc.detail
    assert "sk-route-secret123456" not in model_exc.detail
    assert "api_key=[redacted]" in model_exc.detail


def test_run_events_http_route_paginates_and_hides_non_user_events(tmp_path, monkeypatch):
    saved_modules = _unload_module_prefixes(("fastapi",))
    try:
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ModuleNotFoundError as exc:
            pytest.skip(f"FastAPI/TestClient dependency is not installed: {exc.name}")

        route_path = Path(__file__).resolve().parents[1] / "apps" / "bridge" / "routes" / "runs.py"
        spec = importlib.util.spec_from_file_location("_oha_runs_route_http_under_test", route_path)
        assert spec is not None
        assert spec.loader is not None
        run_route_module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = run_route_module
        spec.loader.exec_module(run_route_module)

        service = AgentRuntimeService(
            db_path=tmp_path / "agent-runtime.db",
            workspace_dir=tmp_path / "runtime",
            credential_store=MemoryCredentialStore(),
            seed_templates=False,
        )
        monkeypatch.setattr(run_route_module, "get_native_run_engine", lambda: service)
        route_app = FastAPI()
        route_app.include_router(run_route_module.router)
        try:
            run = service._insert_run(kind="main_chat_run", runnable_id="builtin:yachiyo-main", user_goal="http replay")
            service.append_run_event(run["run_id"], "public.one", {"value": "one"})
            service.append_run_event(run["run_id"], "internal.hidden", {"value": "two"}, visibility="internal")
            service.append_run_event(
                run["run_id"],
                "secret.hidden",
                {"value": "sk-route-secret123456"},
                sensitivity="secret",
            )
            service.append_run_event(run["run_id"], "public.two", {"value": "three"})

            with TestClient(route_app) as client:
                page = client.get(f"/runs/{run['run_id']}/events?after_sequence=1&limit=1")
                clamped = client.get(f"/runs/{run['run_id']}/events?after_sequence=-10&limit=5000")

            assert page.status_code == 200
            assert page.json()["limit"] == 1
            assert [event["event_type"] for event in page.json()["events"]] == ["public.two"]
            assert clamped.status_code == 200
            assert clamped.json()["after_sequence"] == 0
            assert clamped.json()["limit"] == 1000
            assert [event["event_type"] for event in clamped.json()["events"]] == ["public.one", "public.two"]
            assert "sk-route-secret123456" not in json.dumps(clamped.json(), ensure_ascii=False)
        finally:
            service.close()
    finally:
        sys.modules.pop("_oha_runs_route_http_under_test", None)
        _restore_module_prefixes(("fastapi",), saved_modules)


def test_post_runs_http_route_maps_idempotency_key(monkeypatch):
    saved_modules = _unload_module_prefixes(("fastapi",))
    try:
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ModuleNotFoundError as exc:
            pytest.skip(f"FastAPI/TestClient dependency is not installed: {exc.name}")

        route_path = Path(__file__).resolve().parents[1] / "apps" / "bridge" / "routes" / "runs.py"
        spec = importlib.util.spec_from_file_location("_oha_runs_create_route_http_under_test", route_path)
        assert spec is not None
        assert spec.loader is not None
        run_route_module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = run_route_module
        spec.loader.exec_module(run_route_module)

        recorded: dict[str, str] = {}

        class FakeRunEngine:
            def create_run_for_runnable(self, **kwargs):
                recorded.update({key: str(value) for key, value in kwargs.items()})
                return {
                    "ok": True,
                    "run_id": "run_post_runs_http",
                    "client_request_id": kwargs.get("client_run_id") or kwargs.get("client_request_id") or "",
                }

        monkeypatch.setattr(run_route_module, "get_native_run_engine", lambda: FakeRunEngine())
        route_app = FastAPI()
        route_app.include_router(run_route_module.router)

        with TestClient(route_app) as client:
            response = client.post(
                "/runs",
                json={"runnable_id": "agent_coding", "user_goal": "Run from HTTP"},
                headers={"Idempotency-Key": "post-runs-http-client-1"},
            )

        assert response.status_code == 200
        assert response.json()["run_id"] == "run_post_runs_http"
        assert response.json()["client_request_id"] == "post-runs-http-client-1"
        assert recorded["runnable_id"] == "agent_coding"
        assert recorded["user_goal"] == "Run from HTTP"
        assert recorded["client_run_id"] == "post-runs-http-client-1"
    finally:
        sys.modules.pop("_oha_runs_create_route_http_under_test", None)
        _restore_module_prefixes(("fastapi",), saved_modules)


def test_screen_current_http_route_returns_structured_permission_error(monkeypatch):
    saved_modules = _unload_module_prefixes(("fastapi",))
    try:
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ModuleNotFoundError as exc:
            pytest.skip(f"FastAPI/TestClient dependency is not installed: {exc.name}")

        route_path = Path(__file__).resolve().parents[1] / "apps" / "bridge" / "routes" / "screen.py"
        spec = importlib.util.spec_from_file_location("_oha_screen_route_http_under_test", route_path)
        assert spec is not None
        assert spec.loader is not None
        screen_route_module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = screen_route_module
        spec.loader.exec_module(screen_route_module)

        async def fake_capture():
            raise screenshot_mod.ScreenCapturePermissionError("没有屏幕录制权限，请授权")

        monkeypatch.setattr(screenshot_mod, "capture_screenshot", fake_capture)
        route_app = FastAPI()
        route_app.include_router(screen_route_module.router)

        with TestClient(route_app) as client:
            response = client.get("/screen/current")

        assert response.status_code == 403
        detail = response.json()["detail"]
        assert detail["error"] == "screen_capture_permission_denied"
        assert detail["message"].startswith("屏幕录制权限不足")
        assert "授权" in detail["detail"]
    finally:
        sys.modules.pop("_oha_screen_route_http_under_test", None)
        _restore_module_prefixes(("fastapi",), saved_modules)


def test_bridge_http_middleware_enforces_host_origin_and_session_token(monkeypatch):
    saved_modules = _unload_module_prefixes(("fastapi", "uvicorn"))
    monkeypatch.setenv("OHA_YACHIYO_BRIDGE_TOKEN", "token-123")
    try:
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError as exc:
            pytest.skip(f"FastAPI/TestClient dependency is not installed: {exc.name}")

        server_path = Path(__file__).resolve().parents[1] / "apps" / "bridge" / "server.py"
        spec = importlib.util.spec_from_file_location("_oha_bridge_server_http_under_test", server_path)
        assert spec is not None
        assert spec.loader is not None
        bridge_server = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = bridge_server
        spec.loader.exec_module(bridge_server)

        @bridge_server.app.get("/probe")
        async def get_probe():
            return {"ok": True}

        @bridge_server.app.post("/probe")
        async def post_probe():
            return {"ok": True}

        trusted_headers = {"host": "127.0.0.1:8420", "origin": "http://localhost:5174"}
        token_headers = {**trusted_headers, "X-Oha-Yachiyo-Bridge-Token": "token-123"}
        with TestClient(bridge_server.app) as client:
            get_response = client.get("/probe", headers=trusted_headers)
            bad_host_response = client.get(
                "/probe",
                headers={"host": "0.0.0.0:8420", "origin": "http://localhost:5174"},
            )
            bad_origin_response = client.get(
                "/probe",
                headers={"host": "127.0.0.1:8420", "origin": "https://evil.example"},
            )
            blocked_response = client.post("/probe", headers=trusted_headers)
            allowed_response = client.post("/probe", headers=token_headers)

        assert get_response.status_code == 200
        assert get_response.json() == {"ok": True}
        assert get_response.headers["access-control-allow-origin"] == "http://localhost:5174"
        assert bad_host_response.status_code == 403
        assert bad_host_response.json() == {"ok": False, "error": "untrusted_host"}
        assert bad_origin_response.status_code == 403
        assert bad_origin_response.json() == {"ok": False, "error": "untrusted_origin"}
        assert blocked_response.status_code == 403
        assert blocked_response.json() == {"ok": False, "error": "invalid_bridge_token"}
        assert allowed_response.status_code == 200
        assert allowed_response.json() == {"ok": True}
    finally:
        sys.modules.pop("_oha_bridge_server_http_under_test", None)
        _restore_module_prefixes(("fastapi", "uvicorn"), saved_modules)


def test_all_registered_mutating_routes_require_bridge_token(monkeypatch):
    saved_modules = _unload_module_prefixes(("fastapi", "uvicorn", "apps.bridge.routes"))
    monkeypatch.setenv("OHA_YACHIYO_BRIDGE_TOKEN", "token-123")
    try:
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError as exc:
            pytest.skip(f"FastAPI/TestClient dependency is not installed: {exc.name}")

        server_path = Path(__file__).resolve().parents[1] / "apps" / "bridge" / "server.py"
        spec = importlib.util.spec_from_file_location("_oha_bridge_server_routes_under_test", server_path)
        assert spec is not None
        assert spec.loader is not None
        bridge_server = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = bridge_server
        spec.loader.exec_module(bridge_server)
        bridge_server._register_routes()

        mutating_methods = {"POST", "PUT", "PATCH", "DELETE"}
        trusted_headers = {"host": "127.0.0.1:8420", "origin": "http://localhost:5174"}
        checked: list[tuple[str, str]] = []
        failures: list[tuple[str, str, int, object]] = []

        with TestClient(bridge_server.app) as client:
            for route in bridge_server.app.routes:
                methods = sorted((getattr(route, "methods", None) or set()) & mutating_methods)
                path = getattr(route, "path", "")
                if not methods or not path:
                    continue
                sample_path = re.sub(r"\{[^{}]+?\}", "test-id", path)
                for method in methods:
                    response = client.request(method, sample_path, headers=trusted_headers)
                    checked.append((method, path))
                    if response.status_code != 403 or response.json().get("error") != "invalid_bridge_token":
                        failures.append((method, path, response.status_code, response.json()))

        assert len(checked) >= 80
        assert failures == []
    finally:
        sys.modules.pop("_oha_bridge_server_routes_under_test", None)
        _restore_module_prefixes(("fastapi", "uvicorn", "apps.bridge.routes"), saved_modules)


def test_chat_message_http_route_maps_idempotency_key_header(monkeypatch):
    saved_modules = _unload_module_prefixes(("fastapi",))
    try:
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ModuleNotFoundError as exc:
            pytest.skip(f"FastAPI/TestClient dependency is not installed: {exc.name}")

        route_path = Path(__file__).resolve().parents[1] / "apps" / "bridge" / "routes" / "ui.py"
        spec = importlib.util.spec_from_file_location("_oha_ui_route_http_under_test", route_path)
        assert spec is not None
        assert spec.loader is not None
        ui_route_module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = ui_route_module
        spec.loader.exec_module(ui_route_module)

        class FakeChatAPI:
            def __init__(self, runtime):
                assert runtime is fake_runtime

            def send_message(self, text, attachments=None, runnable_id="", client_message_id=""):
                return {
                    "ok": True,
                    "text": text,
                    "attachments": attachments or [],
                    "runnable_id": runnable_id,
                    "client_message_id": client_message_id,
                }

        fake_runtime = SimpleNamespace()
        monkeypatch.setattr(ui_route_module, "get_runtime", lambda: fake_runtime)
        monkeypatch.setattr(ui_route_module, "ChatAPI", FakeChatAPI)
        route_app = FastAPI()
        route_app.include_router(ui_route_module.router)

        with TestClient(route_app) as client:
            response = client.post(
                "/ui/chat/messages",
                json={"text": "hello"},
                headers={"Idempotency-Key": "header-message-1"},
            )

        assert response.status_code == 200
        assert response.json()["client_message_id"] == "header-message-1"
    finally:
        sys.modules.pop("_oha_ui_route_http_under_test", None)
        _restore_module_prefixes(("fastapi",), saved_modules)


def test_chat_image_bridge_route_reaches_native_run_events(tmp_path, monkeypatch):
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except ModuleNotFoundError:
        FastAPI = None  # type: ignore[assignment]
        TestClient = None  # type: ignore[assignment]

    monkeypatch.setenv("OHA_YACHIYO_HOME", str(tmp_path / "oha-yachiyo-home"))
    monkeypatch.setenv("OHA_YACHIYO_BRIDGE_URL", "http://127.0.0.1:9999")
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "agent-runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="http-chat-image-session")
    session.attach_store(store, load_existing=False)
    state = AppState()
    captured_messages: list[list[dict]] = []
    image_bytes = b"fake-http-image"
    data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        captured_messages.append(messages)
        content = messages[-1]["content"]
        assert isinstance(content, list)
        assert content[0] == {"type": "text", "text": "请从 HTTP route 看图"}
        image_parts = [part for part in content if part.get("type") == "image_url"]
        assert len(image_parts) == 1
        assert image_parts[0]["image_url"]["url"] == data_url
        return {"role": "assistant", "content": "HTTP route image reply"}

    monkeypatch.setattr(chat_store_mod, "get_chat_store", lambda: store)
    monkeypatch.setattr(activity_store_mod, "get_activity_store", lambda: activity_store)
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr(run_routes, "get_native_run_engine", lambda: service)
    monkeypatch.setattr(chat_api_mod, "get_native_image_input_capability", lambda: {"can_attach_images": True, "route": "chat"})
    monkeypatch.setattr(
        "apps.shell.native_capabilities.get_native_image_input_capability",
        lambda: {"can_attach_images": True, "route": "chat"},
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeDefaultProfileService(),
    )
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)

    executor = NativeAgentExecutor(
        chat_session=session,
        runtime_service_getter=lambda: service,
        tool_policy_getter=lambda: {"allowed_tools": []},
        workspace_policy_getter=lambda: {},
        activity_store_getter=lambda: activity_store,
    )
    runner = TaskRunner(state, executor=executor, activity_store=activity_store)
    runtime = SimpleNamespace(
        state=state,
        chat_session=session,
        store=store,
        task_runner=runner,
        agent_runtime_service=service,
    )
    monkeypatch.setattr(ui_routes, "get_runtime", lambda: runtime)

    try:
        if FastAPI is not None and TestClient is not None:
            route_app = FastAPI()
            route_app.include_router(ui_routes.router)
            route_app.include_router(run_routes.router)
            with TestClient(route_app) as client:
                sent = client.post(
                    "/ui/chat/messages",
                    json={
                        "text": "请从 HTTP route 看图",
                        "attachments": [{"name": "screen.png", "data_url": data_url}],
                        "client_message_id": "http-image-client-1",
                    },
                )
                assert sent.status_code == 200
                payload = sent.json()
        else:
            payload = asyncio.run(
                ui_routes.send_chat_message(
                    ui_routes.SendChatMessageRequest(
                        text="请从 HTTP route 看图",
                        attachments=[{"name": "screen.png", "data_url": data_url}],
                        client_message_id="http-image-client-1",
                    )
                )
            )

        assert payload["ok"] is True
        assert payload["status"] == "pending"
        assert payload["attachments"][0]["url"].startswith("http://127.0.0.1:9999/ui/chat/attachments/")
        assert "path" not in payload["attachments"][0]

        task = state.get_task(payload["task_id"])
        assert task is not None
        assert task.attachments[0]["kind"] == "image"

        asyncio.run(runner._execute_with_state(task.task_id))

        updated = state.get_task(task.task_id)
        assert updated is not None
        assert updated.status == TaskStatus.COMPLETED
        assert updated.result == "HTTP route image reply"
        run = service.get_run(service.get_task_run_link(task.task_id)["run_id"])

        if FastAPI is not None and TestClient is not None:
            route_app = FastAPI()
            route_app.include_router(ui_routes.router)
            route_app.include_router(run_routes.router)
            with TestClient(route_app) as client:
                replay_payload = client.get(f"/runs/{run['run_id']}/events?after_sequence=0&limit=200").json()
                messages_payload = client.get("/ui/chat/messages").json()
        else:
            replay_payload = asyncio.run(run_routes.list_run_events(run["run_id"], after_sequence=0, limit=200))
            messages_payload = asyncio.run(ui_routes.get_chat_messages())

        assert len(captured_messages) == 1
        event_types = [event["event_type"] for event in replay_payload["events"]]
        assert "task.linked" in event_types
        assert event_types.count("model.output.completed") == 1
        assert "run.completed" in event_types
        assistant = next(message for message in messages_payload["messages"] if message["role"] == "assistant")
        assert assistant["task_id"] == task.task_id
        assert assistant["content"] == "HTTP route image reply"
        assert assistant["status"] == "completed"
    finally:
        service.close()
        activity_store.close()
        store.close()


def test_chat_approval_bridge_route_resumes_native_run(tmp_path, monkeypatch):
    monkeypatch.setenv("OHA_YACHIYO_HOME", str(tmp_path / "oha-yachiyo-home"))
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "agent-runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    workdir = tmp_path / "workspace"
    (workdir / "src").mkdir(parents=True)
    target_file = workdir / "src" / "app.txt"
    target_file.write_text("before\n", encoding="utf-8")
    session = ChatSession(session_id="bridge-approval-session")
    session.attach_store(store, load_existing=False)
    state = AppState()
    model_calls: list[list[dict]] = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        model_calls.append(messages)
        if len(model_calls) == 1:
            assert any((tool.get("function") or {}).get("name") == "workspace_write_patch" for tool in tools or [])
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_patch",
                        "type": "function",
                        "function": {
                            "name": "workspace_write_patch",
                            "arguments": json.dumps(
                                {
                                    "path": "src/app.txt",
                                    "patch": "--- src/app.txt\n+++ src/app.txt\n@@ -1 +1 @@\n-before\n+after\n",
                                },
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            }
        return {"role": "assistant", "content": "Bridge approval route finished."}

    monkeypatch.setattr(chat_store_mod, "get_chat_store", lambda: store)
    monkeypatch.setattr(activity_store_mod, "get_activity_store", lambda: activity_store)
    monkeypatch.setattr(chat_api_mod, "get_activity_store", lambda: activity_store)
    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr(run_routes, "get_native_run_engine", lambda: service)
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeDefaultProfileService(),
    )
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)

    executor = NativeAgentExecutor(
        chat_session=session,
        runtime_service_getter=lambda: service,
        tool_policy_getter=lambda: {
            "allowed_tools": ["workspace.read", "workspace.write_patch"],
            "approval_required": {"workspace.write_patch": True},
        },
        workspace_policy_getter=lambda: {
            "default_workdir": str(workdir),
            "readable_scopes": ["."],
            "writable_scopes": ["."],
        },
        activity_store_getter=lambda: activity_store,
    )
    runner = TaskRunner(state, executor=executor, activity_store=activity_store)
    runtime = SimpleNamespace(
        state=state,
        chat_session=session,
        store=store,
        task_runner=runner,
        agent_runtime_service=service,
    )
    monkeypatch.setattr(ui_routes, "get_runtime", lambda: runtime)

    async def scenario():
        sent = await ui_routes.send_chat_message(
            ui_routes.SendChatMessageRequest(
                text="请把 src/app.txt 改成 after",
                client_message_id="bridge-approval-client-1",
            )
        )
        assert sent["ok"] is True
        task = state.get_task(sent["task_id"])
        assert task is not None
        runner_task = asyncio.create_task(runner._execute_with_state(task.task_id))
        try:
            run = None
            for _ in range(150):
                try:
                    candidate = service.get_run(service.get_task_run_link(task.task_id)["run_id"])
                except KeyError:
                    await asyncio.sleep(0.02)
                    continue
                if candidate["status"] == "approval_required":
                    run = candidate
                    break
                await asyncio.sleep(0.02)
            assert run is not None

            waiting_messages = await ui_routes.get_chat_messages()
            assistant = next(message for message in waiting_messages["messages"] if message["role"] == "assistant")
            assert waiting_messages["approval_count"] == 1
            assert assistant["status"] == "processing"
            assert assistant["metadata"]["run_id"] == run["run_id"]
            assert assistant["metadata"]["run_status"] == "approval_required"
            assert assistant["metadata"]["pending_approval"]["tool"] == "workspace.write_patch"

            approved = await agent_routes.approve_run_approval(run["run_id"])
            assert approved["status"] == "running"
            await runner_task

            updated = state.get_task(task.task_id)
            assert updated is not None
            assert updated.status == TaskStatus.COMPLETED
            assert updated.result == "Bridge approval route finished."
            assert target_file.read_text(encoding="utf-8") == "after\n"

            replay = await run_routes.list_run_events(run["run_id"], after_sequence=0, limit=200)
            event_types = [event["event_type"] for event in replay["events"]]
            assert "agent.tool.approval_required" in event_types
            assert "agent.tool.approval_approved" in event_types
            assert "agent.tool.call" in event_types
            assert "model.output.completed" in event_types
            assert "run.completed" in event_types

            final_messages = await ui_routes.get_chat_messages()
            final_assistant = next(
                message
                for message in final_messages["messages"]
                if message["role"] == "assistant" and message["task_id"] == task.task_id
            )
            assert final_messages["approval_count"] == 0
            assert final_assistant["status"] == "completed"
            assert final_assistant["content"] == "Bridge approval route finished."
            assert final_assistant["metadata"].get("pending_approval") == {}
        finally:
            if not runner_task.done():
                runner_task.cancel()
                await asyncio.gather(runner_task, return_exceptions=True)

    try:
        asyncio.run(scenario())
    finally:
        service.close()
        activity_store.close()
        store.close()


def test_agent_and_workflow_run_http_routes_map_idempotency_key_header(monkeypatch):
    saved_modules = _unload_module_prefixes(("fastapi",))
    try:
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ModuleNotFoundError as exc:
            pytest.skip(f"FastAPI/TestClient dependency is not installed: {exc.name}")

        route_path = Path(__file__).resolve().parents[1] / "apps" / "bridge" / "routes" / "agents.py"
        spec = importlib.util.spec_from_file_location("_oha_agent_route_http_under_test", route_path)
        assert spec is not None
        assert spec.loader is not None
        agent_route_module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = agent_route_module
        spec.loader.exec_module(agent_route_module)

        class FakeRuntimeService:
            def create_agent_run(self, payload):
                return {"ok": True, "client_run_id": payload.get("client_run_id", "")}

            def create_workflow_run(self, payload):
                return {"ok": True, "client_run_id": payload.get("client_run_id", "")}

        monkeypatch.setattr(agent_route_module, "get_agent_runtime_service", lambda: FakeRuntimeService())
        route_app = FastAPI()
        route_app.include_router(agent_route_module.router)

        with TestClient(route_app) as client:
            agent_response = client.post(
                "/ui/agent-runs",
                json={"agent_id": "agent-1", "user_goal": "hello"},
                headers={"Idempotency-Key": "header-run-1"},
            )
            workflow_response = client.post(
                "/ui/workflow-runs",
                json={"workflow_id": "workflow-1", "user_goal": "hello"},
                headers={"Idempotency-Key": "header-workflow-run-1"},
            )

        assert agent_response.status_code == 200
        assert agent_response.json()["client_run_id"] == "header-run-1"
        assert workflow_response.status_code == 200
        assert workflow_response.json()["client_run_id"] == "header-workflow-run-1"
    finally:
        sys.modules.pop("_oha_agent_route_http_under_test", None)
        _restore_module_prefixes(("fastapi",), saved_modules)


def test_run_cancel_route_handler_is_idempotent(tmp_path, monkeypatch):
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    try:
        run = service._insert_run(
            kind="main_chat_run",
            runnable_id="builtin:yachiyo-main",
            user_goal="cancel via http",
        )

        first = asyncio.run(agent_routes.cancel_run(run["run_id"]))
        second = asyncio.run(agent_routes.cancel_run(run["run_id"]))

        assert first["status"] == "cancelled"
        assert second["status"] == "cancelled"

        stored = service.get_run(run["run_id"])
        events = service.list_run_events(run["run_id"])["events"]
        cancel_facts = [event for event in events if event["event_type"] == "run.cancelled"]
        cancel_timeline = [event for event in stored["timeline"] if event["event"] == "run.cancelled"]

        assert len(cancel_facts) == 1
        assert len(cancel_timeline) == 1
    finally:
        service.close()


def test_fastapi_request_parameters_do_not_use_optional_union_annotations():
    endpoints = [
        agent_routes.create_agent_run,
        agent_routes.create_workflow_run,
        ui_routes.send_chat_message,
    ]

    for endpoint in endpoints:
        parameter = inspect.signature(endpoint).parameters["http_request"]
        assert parameter.annotation in {"Request", agent_routes.Request, ui_routes.Request}


@pytest.mark.asyncio
async def test_status_route_uses_app_version(monkeypatch):
    status_route = _load_status_route_module()
    monkeypatch.setattr(status_route, "get_app_version", lambda: "9.8.7")
    monkeypatch.setattr(
        status_route,
        "get_runtime",
        lambda: SimpleNamespace(
            uptime=1.25,
            state=SimpleNamespace(get_task_counts=lambda: {}),
            is_native_agent_ready=lambda: True,
        ),
    )

    response = await status_route.get_status()

    assert response.version == "9.8.7"
    assert response.service == "oha-yachiyo"
    assert response.native_agent_ready is True


def test_live2d_asset_token_can_rotate():
    first = get_live2d_asset_token()
    second = regenerate_live2d_asset_token()

    assert second
    assert second != first


def test_bridge_access_log_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OHA_YACHIYO_BRIDGE_ACCESS_LOG", raising=False)

    assert _bridge_access_log_enabled() is False


def test_bridge_access_log_can_be_enabled_for_http_debug(monkeypatch):
    monkeypatch.setenv("OHA_YACHIYO_BRIDGE_ACCESS_LOG", "1")

    assert _bridge_access_log_enabled() is True


def test_bridge_start_and_restart_reject_non_loopback_host_before_binding(monkeypatch):
    saved_modules = _unload_module_prefixes(("fastapi", "uvicorn"))
    try:
        server_path = Path(__file__).resolve().parents[1] / "apps" / "bridge" / "server.py"
        spec = importlib.util.spec_from_file_location("_oha_bridge_server_host_guard_under_test", server_path)
        assert spec is not None
        assert spec.loader is not None
        bridge_server = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = bridge_server
        spec.loader.exec_module(bridge_server)

        with pytest.raises(ValueError, match="回环地址"):
            bridge_server.start_bridge(host="0.0.0.0", port=8420)
        assert bridge_server.get_bridge_state() == "failed"

        class ExistingThread:
            def is_alive(self):
                return True

            def join(self, timeout=None):
                raise AssertionError("invalid host must be rejected before stopping the current bridge")

        class NewThread:
            def __init__(self, *args, **kwargs):
                raise AssertionError("invalid host must be rejected before starting a bridge thread")

        running_server = SimpleNamespace(should_exit=False)
        bridge_server._server = running_server
        bridge_server._state = "running"
        bridge_server._bridge_thread = ExistingThread()
        monkeypatch.setattr(bridge_server.threading, "Thread", NewThread)

        result = bridge_server.restart_bridge(host="192.168.1.20", port=8420)

        assert result == {"ok": False, "error": "Bridge 只允许监听回环地址"}
        assert running_server.should_exit is False
        assert bridge_server.get_bridge_state() == "running"
    finally:
        sys.modules.pop("_oha_bridge_server_host_guard_under_test", None)
        _restore_module_prefixes(("fastapi", "uvicorn"), saved_modules)


@pytest.mark.parametrize("channel", ["release", "alpha", "stable"])
def test_bridge_debug_routes_are_disabled_for_release_metadata(monkeypatch, tmp_path, channel):
    metadata_path = tmp_path / "oha-yachiyo-build.json"
    metadata_path.write_text(json.dumps({"channel": channel}), encoding="utf-8")
    monkeypatch.setenv("OHA_YACHIYO_DEV", "1")
    monkeypatch.setenv("OHA_YACHIYO_BUILD_METADATA", str(metadata_path))

    assert debug_routes_enabled() is False


def test_bridge_security_accepts_loopback_without_token_when_disabled(monkeypatch):
    monkeypatch.delenv("OHA_YACHIYO_BRIDGE_TOKEN", raising=False)
    monkeypatch.delenv("OHA_YACHIYO_BRIDGE_TOKEN", raising=False)

    assert bridge_request_violation(
        "POST",
        {"host": "127.0.0.1:8420", "origin": "http://localhost:5174"},
    ) == ""


def test_bridge_security_rejects_untrusted_host(monkeypatch):
    monkeypatch.delenv("OHA_YACHIYO_BRIDGE_TOKEN", raising=False)

    assert bridge_request_violation("GET", {"host": "0.0.0.0:8420"}) == "untrusted_host"


def test_bridge_security_rejects_untrusted_origin(monkeypatch):
    monkeypatch.delenv("OHA_YACHIYO_BRIDGE_TOKEN", raising=False)

    assert bridge_request_violation(
        "GET",
        {"host": "127.0.0.1:8420", "origin": "https://evil.example"},
    ) == "untrusted_origin"


def test_bridge_security_requires_token_for_mutating_requests(monkeypatch):
    monkeypatch.setenv("OHA_YACHIYO_BRIDGE_TOKEN", "token-123")

    assert bridge_request_violation("POST", {"host": "127.0.0.1:8420"}) == "invalid_bridge_token"
    assert bridge_request_violation(
        "POST",
        {"host": "127.0.0.1:8420", "x-oha-yachiyo-bridge-token": "token-123"},
    ) == ""


def test_rewrite_live2d_manifest_paths_appends_token():
    manifest = {
        "Version": 3,
        "FileReferences": {
            "Moc": "model.moc3",
            "Textures": ["textures/tex_00.png"],
            "Physics": "physics.json",
            "Motions": {
                "Idle": [{"File": "motions/idle.motion3.json", "Sound": "sounds/idle.wav"}],
            },
        },
    }

    rewritten = live2d_route._rewrite_live2d_manifest_paths(manifest, "token-123")
    refs = rewritten["FileReferences"]

    assert refs["Moc"].endswith("model.moc3?token=token-123")
    assert refs["Textures"][0].endswith("textures/tex_00.png?token=token-123")
    assert refs["Physics"].endswith("physics.json?token=token-123")
    assert refs["Motions"]["Idle"][0]["File"].endswith("motions/idle.motion3.json?token=token-123")
    assert refs["Motions"]["Idle"][0]["Sound"].endswith("sounds/idle.wav?token=token-123")


def test_resolve_live2d_asset_rejects_path_escape(tmp_path, monkeypatch):
    model_root = tmp_path / "models"
    model_root.mkdir()
    (model_root / "ok.txt").write_text("ok", encoding="utf-8")

    monkeypatch.setattr(live2d_route, "_get_live2d_model_root", lambda: model_root)

    with pytest.raises(live2d_route.HTTPException) as exc_info:
        live2d_route._resolve_live2d_asset("../secret.txt")

    assert exc_info.value.status_code == 403


def test_render_live2d_manifest_keeps_json_structure(tmp_path):
    manifest_path = tmp_path / "model.model3.json"
    manifest_path.write_text(
        '{"FileReferences":{"Moc":"model.moc3","Textures":["tex.png"]}}',
        encoding="utf-8",
    )

    payload = live2d_route._render_live2d_manifest(manifest_path, "token-xyz")
    decoded = json.loads(payload.decode("utf-8"))

    assert decoded["FileReferences"]["Moc"].endswith("model.moc3?token=token-xyz")
    assert decoded["FileReferences"]["Textures"][0].endswith("tex.png?token=token-xyz")
    assert "Expressions" not in decoded["FileReferences"]
    assert "Motions" not in decoded["FileReferences"]


def test_render_live2d_manifest_injects_sidecar_expressions(tmp_path, monkeypatch):
    manifest_path = tmp_path / "model.model3.json"
    manifest_path.write_text(
        '{"FileReferences":{"Moc":"model.moc3","Textures":[]}}',
        encoding="utf-8",
    )
    (tmp_path / "笑咪咪.exp3.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        live2d_route,
        "get_runtime",
        lambda: SimpleNamespace(config=SimpleNamespace(live2d_mode=SimpleNamespace(enable_physics=True))),
    )

    payload = live2d_route._render_live2d_manifest(manifest_path, "token-xyz")
    refs = json.loads(payload.decode("utf-8"))["FileReferences"]

    assert refs["Expressions"] == [{"Name": "笑咪咪", "File": "笑咪咪.exp3.json?token=token-xyz"}]


def test_render_live2d_manifest_respects_physics_toggle(tmp_path, monkeypatch):
    manifest_path = tmp_path / "model.model3.json"
    manifest_path.write_text(
        '{"FileReferences":{"Moc":"model.moc3","Textures":[],"Physics":"model.physics3.json"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        live2d_route,
        "get_runtime",
        lambda: SimpleNamespace(config=SimpleNamespace(live2d_mode=SimpleNamespace(enable_physics=False))),
    )

    payload = live2d_route._render_live2d_manifest(manifest_path, "token-xyz")
    refs = json.loads(payload.decode("utf-8"))["FileReferences"]

    assert "Physics" not in refs


def test_render_live2d_manifest_keeps_physics_when_enabled(tmp_path, monkeypatch):
    manifest_path = tmp_path / "model.model3.json"
    manifest_path.write_text(
        '{"FileReferences":{"Moc":"model.moc3","Textures":[],"Physics":"model.physics3.json"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        live2d_route,
        "get_runtime",
        lambda: SimpleNamespace(config=SimpleNamespace(live2d_mode=SimpleNamespace(enable_physics=True))),
    )

    payload = live2d_route._render_live2d_manifest(manifest_path, "token-xyz")
    refs = json.loads(payload.decode("utf-8"))["FileReferences"]

    assert refs["Physics"].endswith("model.physics3.json?token=token-xyz")


def test_live2d_runtime_script_sources_prefer_cache(tmp_path, monkeypatch):
    cached_script = tmp_path / "pixi.min.js"
    cached_script.write_text("window.PIXI = {};", encoding="utf-8")
    missing_script = tmp_path / "cubism.js"

    monkeypatch.setattr(
        live2d_route.live2d_runtime,
        "get_live2d_runtime_dependency_specs",
        lambda: {
            "pixi_js": ("https://example.test/pixi.js", cached_script),
            "live2d_cubism_core": ("https://example.test/core.js", missing_script),
        },
    )

    scripts = live2d_route._live2d_runtime_script_sources()

    assert scripts == [
        {"id": "pixi_js", "source": "cache", "url": "/live2d/runtime/pixi_js"},
        {
            "id": "live2d_cubism_core",
            "source": "cdn",
            "url": "https://example.test/core.js",
        },
    ]


@pytest.mark.asyncio
async def test_get_live2d_runtime_primes_dependencies(tmp_path, monkeypatch):
    cached_script = tmp_path / "pixi.min.js"
    cached_script.write_text("window.PIXI = {};", encoding="utf-8")
    calls = []

    monkeypatch.setattr(
        live2d_route.live2d_runtime,
        "get_live2d_runtime_dependency_specs",
        lambda: {"pixi_js": ("https://example.test/pixi.js", cached_script)},
    )
    monkeypatch.setattr(
        live2d_route.live2d_runtime,
        "prime_live2d_runtime_dependencies",
        lambda: calls.append("prime") or (True, ""),
    )

    payload = await live2d_route.get_live2d_runtime()

    assert calls == ["prime"]
    assert payload["ready"] is True
    assert payload["scripts"] == [
        {"id": "pixi_js", "source": "cache", "url": "/live2d/runtime/pixi_js"}
    ]
