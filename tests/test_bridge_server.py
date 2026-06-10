"""Bridge Server 测试。"""

import asyncio
import base64
import importlib.util
import inspect
import json
import re
import sys
import threading
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
from apps.core.chat_session import ChatSession, MessageStatus
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


def test_set_runtime_populates_bridge_app_state():
    deps_path = Path(__file__).resolve().parents[1] / "apps" / "bridge" / "deps.py"
    spec = importlib.util.spec_from_file_location("_oha_bridge_deps_under_test", deps_path)
    assert spec is not None
    assert spec.loader is not None
    bridge_deps = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = bridge_deps
    spec.loader.exec_module(bridge_deps)

    runtime = SimpleNamespace(agent_runtime_service=object())
    previous_runtime = getattr(bridge_deps, "_runtime", None)
    state = getattr(app, "state", None)
    sentinel = object()
    previous_app_runtime = getattr(state, "runtime", sentinel) if state is not None else sentinel

    try:
        bridge_deps.set_runtime(runtime)

        assert bridge_deps.get_runtime() is runtime
        if state is not None:
            assert state.runtime is runtime
    finally:
        bridge_deps._runtime = previous_runtime
        if state is not None:
            if previous_app_runtime is sentinel:
                try:
                    delattr(state, "runtime")
                except AttributeError:
                    pass
            else:
                state.runtime = previous_app_runtime
        sys.modules.pop("_oha_bridge_deps_under_test", None)


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
        monkeypatch.setattr(
            run_route_module,
            "get_native_run_engine",
            lambda: (_ for _ in ()).throw(AssertionError("run routes should use AppRuntime service")),
        )
        route_app = FastAPI()
        route_app.state.runtime = SimpleNamespace(agent_runtime_service=service)
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

        service = FakeRunEngine()
        monkeypatch.setattr(
            run_route_module,
            "get_native_run_engine",
            lambda: (_ for _ in ()).throw(AssertionError("run routes should use AppRuntime service")),
        )
        route_app = FastAPI()
        route_app.state.runtime = SimpleNamespace(agent_runtime_service=service)
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


def test_chat_cancel_http_route_returns_ui_cancel_projection(monkeypatch):
    saved_modules = _unload_module_prefixes(("fastapi",))
    try:
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ModuleNotFoundError as exc:
            pytest.skip(f"FastAPI/TestClient dependency is not installed: {exc.name}")

        route_path = Path(__file__).resolve().parents[1] / "apps" / "bridge" / "routes" / "ui.py"
        spec = importlib.util.spec_from_file_location("_oha_ui_cancel_route_http_under_test", route_path)
        assert spec is not None
        assert spec.loader is not None
        ui_route_module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = ui_route_module
        spec.loader.exec_module(ui_route_module)

        class FakeChatAPI:
            def __init__(self, runtime):
                assert runtime is fake_runtime

            def cancel_current_tasks(self):
                return {
                    "ok": True,
                    "cancelled_tasks": 1,
                    "processing_count": 0,
                    "is_processing": False,
                    "token_count": 128,
                    "messages": [
                        {
                            "id": "assistant-cancelled",
                            "role": "assistant",
                            "task_id": "task-cancelled",
                            "status": "failed",
                            "content": "任务已取消",
                        }
                    ],
                }

        fake_runtime = SimpleNamespace()
        monkeypatch.setattr(ui_route_module, "get_runtime", lambda: fake_runtime)
        monkeypatch.setattr(ui_route_module, "ChatAPI", FakeChatAPI)
        route_app = FastAPI()
        route_app.include_router(ui_route_module.router)

        with TestClient(route_app) as client:
            response = client.post("/ui/chat/session/cancel")

        payload = response.json()
        assert response.status_code == 200
        assert payload["ok"] is True
        assert payload["cancelled_tasks"] == 1
        assert payload["processing_count"] == 0
        assert payload["is_processing"] is False
        assert payload["token_count"] == 128
        assert payload["messages"][0]["task_id"] == "task-cancelled"
        assert payload["messages"][0]["status"] == "failed"
        assert "任务已取消" in payload["messages"][0]["content"]
    finally:
        sys.modules.pop("_oha_ui_cancel_route_http_under_test", None)
        _restore_module_prefixes(("fastapi",), saved_modules)


def test_chat_delegated_summary_http_route_returns_followup_projection(monkeypatch):
    saved_modules = _unload_module_prefixes(("fastapi",))
    try:
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ModuleNotFoundError as exc:
            pytest.skip(f"FastAPI/TestClient dependency is not installed: {exc.name}")

        route_path = Path(__file__).resolve().parents[1] / "apps" / "bridge" / "routes" / "ui.py"
        spec = importlib.util.spec_from_file_location("_oha_ui_delegated_summary_route_http_under_test", route_path)
        assert spec is not None
        assert spec.loader is not None
        ui_route_module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = ui_route_module
        spec.loader.exec_module(ui_route_module)

        class FakeChatAPI:
            def __init__(self, runtime):
                assert runtime is fake_runtime

            def summarize_delegated_run(self, run_id):
                assert run_id == "run_delegate_http"
                return {
                    "ok": True,
                    "summary_created": True,
                    "run_id": run_id,
                    "run_status": "completed",
                    "task_id": "summary-task-http",
                }

        fake_runtime = SimpleNamespace()
        monkeypatch.setattr(ui_route_module, "get_runtime", lambda: fake_runtime)
        monkeypatch.setattr(ui_route_module, "ChatAPI", FakeChatAPI)
        route_app = FastAPI()
        route_app.include_router(ui_route_module.router)

        with TestClient(route_app) as client:
            response = client.post(
                "/ui/chat/delegated-run-summary",
                json={"run_id": "run_delegate_http"},
            )

        payload = response.json()
        assert response.status_code == 200
        assert payload == {
            "ok": True,
            "summary_created": True,
            "run_id": "run_delegate_http",
            "run_status": "completed",
            "task_id": "summary-task-http",
        }
    finally:
        sys.modules.pop("_oha_ui_delegated_summary_route_http_under_test", None)
        _restore_module_prefixes(("fastapi",), saved_modules)


def test_chat_group_http_routes_preserve_create_update_payloads(monkeypatch):
    saved_modules = _unload_module_prefixes(("fastapi",))
    try:
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ModuleNotFoundError as exc:
            pytest.skip(f"FastAPI/TestClient dependency is not installed: {exc.name}")

        route_path = Path(__file__).resolve().parents[1] / "apps" / "bridge" / "routes" / "ui.py"
        spec = importlib.util.spec_from_file_location("_oha_ui_group_route_http_under_test", route_path)
        assert spec is not None
        assert spec.loader is not None
        ui_route_module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = ui_route_module
        spec.loader.exec_module(ui_route_module)

        calls: list[tuple[str, dict[str, object]]] = []

        class FakeChatAPI:
            def __init__(self, runtime):
                assert runtime is fake_runtime

            def create_group_session(self, *, name="", avatar_url="", participant_ids=None):
                payload = {
                    "name": name,
                    "avatar_url": avatar_url,
                    "participant_ids": participant_ids or [],
                }
                calls.append(("create", payload))
                return {"ok": True, "session_id": "group-http-1", **payload}

            def update_group_session(self, session_id, *, name="", avatar_url="", participant_ids=None):
                payload = {
                    "session_id": session_id,
                    "name": name,
                    "avatar_url": avatar_url,
                    "participant_ids": participant_ids or [],
                }
                calls.append(("update", payload))
                return {"ok": True, **payload}

        fake_runtime = SimpleNamespace()
        monkeypatch.setattr(ui_route_module, "get_runtime", lambda: fake_runtime)
        monkeypatch.setattr(ui_route_module, "ChatAPI", FakeChatAPI)
        route_app = FastAPI()
        route_app.include_router(ui_route_module.router)

        avatar = "data:image/png;base64,AAAA"
        with TestClient(route_app) as client:
            created = client.post(
                "/ui/chat/groups",
                json={
                    "name": "HTTP 产品群聊",
                    "avatar_url": avatar,
                    "participant_ids": ["agent_design", "agent_coding"],
                },
            )
            updated = client.patch(
                "/ui/chat/groups/group-http-1",
                json={
                    "name": "HTTP 产品群聊 v2",
                    "avatar_url": "https://example.test/group.png",
                    "participant_ids": ["agent_design"],
                },
            )

        assert created.status_code == 200
        assert created.json() == {
            "ok": True,
            "session_id": "group-http-1",
            "name": "HTTP 产品群聊",
            "avatar_url": avatar,
            "participant_ids": ["agent_design", "agent_coding"],
        }
        assert updated.status_code == 200
        assert updated.json() == {
            "ok": True,
            "session_id": "group-http-1",
            "name": "HTTP 产品群聊 v2",
            "avatar_url": "https://example.test/group.png",
            "participant_ids": ["agent_design"],
        }
        assert calls == [
            (
                "create",
                {
                    "name": "HTTP 产品群聊",
                    "avatar_url": avatar,
                    "participant_ids": ["agent_design", "agent_coding"],
                },
            ),
            (
                "update",
                {
                    "session_id": "group-http-1",
                    "name": "HTTP 产品群聊 v2",
                    "avatar_url": "https://example.test/group.png",
                    "participant_ids": ["agent_design"],
                },
            ),
        ]
    finally:
        sys.modules.pop("_oha_ui_group_route_http_under_test", None)
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


def test_chat_delegated_summary_bridge_route_runs_native_followup(tmp_path, monkeypatch):
    monkeypatch.setenv("OHA_YACHIYO_HOME", str(tmp_path / "oha-yachiyo-home"))
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "agent-runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="bridge-delegated-summary-session")
    session.attach_store(store, load_existing=False)
    state = AppState()
    captured_messages: list[list[dict]] = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        captured_messages.append(messages)
        content = str(messages[-1].get("content") or "")
        assert "[Oha-Yachiyo 自动委派 Run 汇总]" in content
        assert "NativeRunEngine delegated route result." in content
        assert "run_oha_agent" not in content
        return {"role": "assistant", "content": "主模型总结：Native delegated route result 已整理。"}

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
        activity_store=activity_store,
        agent_runtime_service=service,
    )
    monkeypatch.setattr(ui_routes, "get_runtime", lambda: runtime)

    try:
        run_group = service._insert_run_group(
            title="Bridge delegated summary",
            source="delegation",
        )
        delegated = service._insert_run(
            kind="agent_run",
            runnable_id="agent_bridge_summary",
            user_goal="整理 Bridge delegated summary evidence",
            run_group_id=run_group["run_group_id"],
        )
        service._update_run(
            delegated["run_id"],
            status="completed",
            result="NativeRunEngine delegated route result.",
            timeline=[
                {
                    "event": "agent.tool.call",
                    "detail": "artifact.write",
                    "input_preview": {"path": "reports/bridge-summary.md"},
                    "result": {"ok": True, "path": "reports/bridge-summary.md"},
                },
                {
                    "event": "agent.run.completed",
                    "detail": "done",
                    "result": "NativeRunEngine delegated route result.",
                },
            ],
            artifacts=[
                {"path": "agent-context.md", "kind": "context"},
                {"path": "reports/bridge-summary.md", "kind": "report"},
            ],
        )

        async def scenario():
            sent = await ui_routes.send_chat_message(
                ui_routes.SendChatMessageRequest(
                    text="请自动委派一个 Agent 整理 Bridge summary evidence",
                    client_message_id="bridge-delegated-summary-source",
                )
            )
            assert sent["ok"] is True
            source_task = state.get_task(sent["task_id"])
            assert source_task is not None
            state.update_task_status(
                source_task.task_id,
                TaskStatus.COMPLETED,
                result="我会交给 Bridge Summary Agent 处理。",
            )
            session.upsert_assistant_message(
                task_id=source_task.task_id,
                content=(
                    "我会交给 Bridge Summary Agent 处理。\n"
                    '<oha_delegation>{"action":"run_oha_agent","agent":"Bridge Summary Agent",'
                    '"goal":"整理 Bridge summary evidence"}</oha_delegation>'
                ),
                status=MessageStatus.COMPLETED,
            )
            activity_store.record_event(
                session_id=session.session_id,
                task_id=source_task.task_id,
                tool_name="oha.delegation",
                phase="subagent",
                title="Bridge Summary Agent completed",
                detail=f"run_id={delegated['run_id']}",
                status="completed",
                metadata={
                    "run_id": delegated["run_id"],
                    "run_group_id": run_group["run_group_id"],
                    "run_status": "completed",
                },
            )

            summary = await ui_routes.summarize_delegated_run(
                ui_routes.SummarizeDelegatedRunRequest(run_id=delegated["run_id"])
            )
            repeat = await ui_routes.summarize_delegated_run(
                ui_routes.SummarizeDelegatedRunRequest(run_id=delegated["run_id"])
            )
            assert summary["ok"] is True
            assert summary["summary_created"] is True
            assert summary["run_status"] == "completed"
            assert repeat["summary_created"] is False
            summary_task = state.get_task(summary["task_id"])
            assert summary_task is not None
            assert summary_task.chat_session_id == session.session_id
            assert "[Oha-Yachiyo 自动委派 Run 汇总]" in summary_task.description
            assert "用户原始请求：请自动委派一个 Agent 整理 Bridge summary evidence" in summary_task.description
            assert "run_oha_agent" not in summary_task.description
            assert "agent_bridge_summary：已完成" in summary_task.description
            assert "reports/bridge-summary.md" in summary_task.description
            assert "agent-context.md" not in summary_task.description

            await runner._execute_with_state(summary_task.task_id)

            completed_task = state.get_task(summary_task.task_id)
            assert completed_task is not None
            assert completed_task.status == TaskStatus.COMPLETED
            assert completed_task.result == "主模型总结：Native delegated route result 已整理。"
            summary_run = service.get_run(service.get_task_run_link(summary_task.task_id)["run_id"])
            detail = await agent_routes.get_any_run(summary_run["run_id"])
            replay = await run_routes.list_run_events(summary_run["run_id"], after_sequence=0, limit=200)
            event_types = [event["event_type"] for event in replay["events"]]

            assert summary_run["run_id"] != delegated["run_id"]
            assert detail["kind"] == "main_chat_run"
            assert detail["status"] == "completed"
            assert detail["task_id"] == summary_task.task_id
            assert detail["session_id"] == session.session_id
            assert detail["task_run_link_created_at"]
            assert event_types.count("model.output.completed") == 1
            assert "task.linked" in event_types
            assert "run.completed" in event_types

            messages = await ui_routes.get_chat_messages()
            final_summary = next(
                message
                for message in messages["messages"]
                if message["task_id"] == summary_task.task_id
            )
            assert final_summary["status"] == "completed"
            assert final_summary["content"] == "主模型总结：Native delegated route result 已整理。"
            assert final_summary["metadata"]["delegated_run_summary_for_run_id"] == delegated["run_id"]
            assert final_summary["metadata"]["run_status"] == "completed"

        asyncio.run(scenario())
        assert len(captured_messages) == 1
    finally:
        service.close()
        activity_store.close()
        store.close()


def test_chat_group_dispatch_bridge_route_runs_native_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("OHA_YACHIYO_HOME", str(tmp_path / "oha-yachiyo-home"))
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "agent-runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="bridge-group-dispatch-session")
    session.attach_store(store, load_existing=False)
    state = AppState()
    model_calls: list[list[dict]] = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        model_calls.append(messages)
        last_content = str(messages[-1]["content"])
        if "[Oha-Yachiyo 群组 Agent 汇总]" in last_content:
            assert "Coding：已完成" in last_content
            assert "汇报：Coding bridge dispatch result" in last_content
            return {"role": "assistant", "content": "群组总结：Coding 已完成 Bridge route Native 派发。"}
        if "# Agent\nName: Coding Agent" in last_content:
            assert "# User Goal\n做 Bridge route Native 群聊派发验证" in last_content
            assert "[Oha-Yachiyo 群组执行约定]" in last_content
            assert "你在群内身份是：Coding" in last_content
            return {"role": "assistant", "content": "Coding bridge dispatch result"}
        assert "请安排 Coding 做 Bridge route Native 群聊派发验证" in last_content
        assert "oha.group_dispatch" in str(messages[0]["content"])
        return {
            "role": "assistant",
            "content": (
                "我会让 Coding 处理这件事。\n"
                '{"tool":"oha.group_dispatch","input":{"tasks":[{"kind":"agent","target":"Coding",'
                '"goal":"做 Bridge route Native 群聊派发验证"}]}}'
            ),
        }

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

    coding = service.create_agent(
        {
            "name": "Coding Agent",
            "nickname": "Coding",
            "description": "runs native group dispatch route tests",
            "model_mode": "custom_api",
            "model_config": {
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-secret",
            },
        }
    )
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
        activity_store=activity_store,
        agent_runtime_service=service,
    )
    monkeypatch.setattr(ui_routes, "get_runtime", lambda: runtime)

    async def wait_for(condition):
        last = None
        for _ in range(150):
            try:
                last = condition()
            except Exception as exc:
                last = exc
            if last:
                return last
            await asyncio.sleep(0.02)
        raise AssertionError(f"condition not met; last={last!r}")

    async def scenario():
        created = await ui_routes.create_chat_group(
            ui_routes.CreateChatGroupRequest(
                name="Bridge Native Dispatch Group",
                participant_ids=[coding["agent_id"]],
            )
        )
        assert created["ok"] is True
        assert created["session_context"]["conversation_kind"] == "group"
        assert created["session_context"]["participants"][1]["id"] == coding["agent_id"]

        sent = await ui_routes.send_chat_message(
            ui_routes.SendChatMessageRequest(
                text="@主模型 请安排 Coding 做 Bridge route Native 群聊派发验证",
                client_message_id="bridge-group-dispatch-client-1",
            )
        )
        assert sent["ok"] is True
        await runner._execute_with_state(sent["task_id"])

        main_task = state.get_task(sent["task_id"])
        assert main_task is not None
        assert main_task.status == TaskStatus.COMPLETED
        main_run = service.get_run(service.get_task_run_link(sent["task_id"])["run_id"])
        assert main_run["kind"] == "main_chat_run"
        assert main_run["status"] == "completed"

        dispatch_payload = await ui_routes.get_chat_messages()
        parent = next(
            message
            for message in dispatch_payload["messages"]
            if message["role"] == "assistant" and message["task_id"] == sent["task_id"]
        )
        agent_message = next(
            message
            for message in dispatch_payload["messages"]
            if message["role"] == "assistant"
            and message["metadata"].get("sender", {}).get("nickname") == "Coding"
        )
        assert parent["metadata"]["group_dispatch_count"] == 1
        assert parent["metadata"]["group_dispatch_run_group_id"] == agent_message["metadata"]["run_group_id"]
        assert "oha.group_dispatch" not in parent["content"]
        assert agent_message["metadata"]["runnable_id"] == coding["agent_id"]
        assert agent_message["metadata"]["delegated_by_task_id"] == sent["task_id"]
        assert agent_message["metadata"]["delegated_goal"] == "做 Bridge route Native 群聊派发验证"

        agent_run_id = agent_message["metadata"]["run_id"]
        agent_run = await wait_for(
            lambda: (
                service.get_run(agent_run_id)
                if service.get_run(agent_run_id)["status"] in {"completed", "failed", "cancelled", "approval_required"}
                else None
            )
        )
        assert agent_run["status"] == "completed"
        assert agent_run["runnable_id"] == coding["agent_id"]
        assert agent_run["result"] == "Coding bridge dispatch result"

        completed_agent = None
        for _ in range(150):
            payload = await ui_routes.get_chat_messages()
            completed_agent = next(
                (
                    message
                    for message in payload["messages"]
                    if message["role"] == "assistant"
                    and "Coding bridge dispatch result" in str(message["content"] or "")
                ),
                None,
            )
            if completed_agent is not None:
                break
            await asyncio.sleep(0.02)
        assert completed_agent is not None
        assert completed_agent["metadata"]["run_id"] == agent_run_id
        assert completed_agent["metadata"]["run_status"] == "completed"
        assert completed_agent["metadata"]["agent_report"] == "Coding bridge dispatch result"

        final_payload = await ui_routes.get_chat_messages()
        summary_message = next(
            message
            for message in final_payload["messages"]
            if message["metadata"].get("group_agent_summary_for_task_id") == sent["task_id"]
        )
        summary_task = state.get_task(summary_message["task_id"])
        assert summary_message["status"] == "processing"
        assert summary_task is not None
        assert summary_task.chat_session_id == runtime.chat_session.session_id
        assert "[Oha-Yachiyo 群组 Agent 汇总]" in summary_task.description
        assert "Coding：已完成" in summary_task.description
        assert "汇报：Coding bridge dispatch result" in summary_task.description

        await runner._execute_with_state(summary_task.task_id)

        completed_summary_task = state.get_task(summary_task.task_id)
        assert completed_summary_task is not None
        assert completed_summary_task.status == TaskStatus.COMPLETED
        assert completed_summary_task.result == "群组总结：Coding 已完成 Bridge route Native 派发。"
        summary_run = service.get_run(service.get_task_run_link(summary_task.task_id)["run_id"])
        detail = await agent_routes.get_any_run(summary_run["run_id"])
        replay = await run_routes.list_run_events(summary_run["run_id"], after_sequence=0, limit=200)
        summary_event_types = [event["event_type"] for event in replay["events"]]
        assert summary_run["kind"] == "main_chat_run"
        assert summary_run["status"] == "completed"
        assert summary_run["run_id"] != main_run["run_id"]
        assert detail["task_id"] == summary_task.task_id
        assert detail["session_id"] == runtime.chat_session.session_id
        assert "task.linked" in summary_event_types
        assert summary_event_types.count("model.output.completed") == 1
        assert "run.completed" in summary_event_types

        settled_parent = None
        settled_summary = None
        for _ in range(150):
            settled_payload = await ui_routes.get_chat_messages()
            settled_parent = next(
                message
                for message in settled_payload["messages"]
                if message["role"] == "assistant" and message["task_id"] == sent["task_id"]
            )
            settled_summary = next(
                message
                for message in settled_payload["messages"]
                if message["task_id"] == summary_task.task_id
            )
            if (
                "group_agent_summary_pending" not in settled_parent["metadata"]
                and settled_parent["metadata"].get("group_agent_summary_status") == "completed"
                and settled_summary["status"] == "completed"
            ):
                break
            await asyncio.sleep(0.02)
        assert settled_parent is not None
        assert settled_summary is not None
        assert "group_agent_summary_pending" not in settled_parent["metadata"]
        assert settled_parent["metadata"]["group_agent_summary_status"] == "completed"
        assert settled_summary["status"] == "completed"
        assert settled_summary["content"] == "群组总结：Coding 已完成 Bridge route Native 派发。"

    try:
        asyncio.run(scenario())
        assert len(model_calls) == 3
    finally:
        service.close()
        activity_store.close()
        store.close()


def test_chat_cancel_bridge_route_cancels_native_run_and_ignores_late_output(tmp_path, monkeypatch):
    monkeypatch.setenv("OHA_YACHIYO_HOME", str(tmp_path / "oha-yachiyo-home"))
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    activity_store = ActivityStore(db_path=str(tmp_path / "activity.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "agent-runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="bridge-cancel-session")
    session.attach_store(store, load_existing=False)
    state = AppState()
    model_started = threading.Event()
    release_model = threading.Event()
    model_calls: list[list[dict]] = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        model_calls.append(messages)
        model_started.set()
        assert release_model.wait(timeout=3), "test did not release slow model call"
        return {"role": "assistant", "content": "late model output should be ignored"}

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
        cancel_task_runner_task=lambda task_id: runner.cancel_task(task_id),
    )
    monkeypatch.setattr(ui_routes, "get_runtime", lambda: runtime)

    async def scenario():
        sent = await ui_routes.send_chat_message(
            ui_routes.SendChatMessageRequest(
                text="请开始一个可以被停止的慢请求",
                client_message_id="bridge-cancel-client-1",
            )
        )
        assert sent["ok"] is True
        task = state.get_task(sent["task_id"])
        assert task is not None
        runner_task = asyncio.create_task(runner._execute_with_state(task.task_id))
        runner._in_progress[task.task_id] = runner_task
        runner_task.add_done_callback(lambda _future: runner._in_progress.pop(task.task_id, None))
        try:
            assert await asyncio.to_thread(model_started.wait, 3)
            run = service.get_run(service.get_task_run_link(task.task_id)["run_id"])
            assert run["status"] == "running"

            cancelled = await ui_routes.cancel_chat_session_tasks()
            assert cancelled["ok"] is True
            assert cancelled["cancelled_tasks"] == 1
            assert cancelled["processing_count"] == 0
            assert cancelled["is_processing"] is False

            cancelled_task = state.get_task(task.task_id)
            assert cancelled_task is not None
            assert cancelled_task.status == TaskStatus.CANCELLED
            cancelled_assistant = next(message for message in cancelled["messages"] if message["role"] == "assistant")
            assert cancelled_assistant["task_id"] == task.task_id
            assert cancelled_assistant["status"] == "failed"
            assert "任务已取消" in cancelled_assistant["content"]

            for _ in range(150):
                stored = service.get_run(run["run_id"])
                if stored["status"] == "cancelled":
                    break
                await asyncio.sleep(0.02)
            else:
                raise AssertionError("linked Native Run did not enter cancelled state")

            release_model.set()
            await asyncio.gather(runner_task, return_exceptions=True)

            replay = await run_routes.list_run_events(run["run_id"], after_sequence=0, limit=200)
            event_types = [event["event_type"] for event in replay["events"]]
            stored = service.get_run(run["run_id"])
            assert stored["status"] == "cancelled"
            assert "run.cancelled" in event_types
            assert "model.output.completed" not in event_types
            assert "run.completed" not in event_types

            listed_runs = await agent_routes.list_runs(limit=20)
            detail = await agent_routes.get_any_run(run["run_id"])
            listed = next(item for item in listed_runs["runs"] if item["run_id"] == run["run_id"])
            assert listed["kind"] == "main_chat_run"
            assert listed["status"] == "cancelled"
            assert listed["task_id"] == task.task_id
            assert listed["session_id"] == session.session_id
            assert listed["task_run_link_created_at"]
            assert detail["run_id"] == run["run_id"]
            assert detail["kind"] == "main_chat_run"
            assert detail["status"] == "cancelled"
            assert detail["task_id"] == task.task_id
            assert detail["session_id"] == session.session_id
            assert detail["task_run_link_created_at"]
            assert any(event.get("event") == "run.cancelled" for event in detail["timeline"])

            final_messages = await ui_routes.get_chat_messages()
            final_assistant = next(message for message in final_messages["messages"] if message["role"] == "assistant")
            assert final_messages["processing_count"] == 0
            assert final_assistant["task_id"] == task.task_id
            assert final_assistant["status"] == "failed"
            assert "late model output" not in final_assistant["content"]
        finally:
            release_model.set()
            if not runner_task.done():
                runner_task.cancel()
                await asyncio.gather(runner_task, return_exceptions=True)

    try:
        asyncio.run(scenario())
        assert len(model_calls) == 1
    finally:
        release_model.set()
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
            def __init__(self):
                self.calls: list[tuple[str, dict]] = []

            def create_agent_run(self, payload):
                self.calls.append(("create_agent_run", dict(payload)))
                return {"ok": True, "client_run_id": payload.get("client_run_id", "")}

            def create_workflow_run(self, payload):
                self.calls.append(("create_workflow_run", dict(payload)))
                return {"ok": True, "client_run_id": payload.get("client_run_id", "")}

            def list_runs(self, limit):
                self.calls.append(("list_runs", {"limit": limit}))
                return {"runs": [{"run_id": "run-1"}], "limit": limit}

            def get_run(self, run_id):
                self.calls.append(("get_run", {"run_id": run_id}))
                return {"run_id": run_id, "status": "approval_required"}

            def approve_run_approval(self, run_id):
                self.calls.append(("approve_run_approval", {"run_id": run_id}))
                return {"run_id": run_id, "status": "running"}

            def reject_run_approval(self, run_id, reason):
                self.calls.append(("reject_run_approval", {"run_id": run_id, "reason": reason}))
                return {"run_id": run_id, "status": "cancelled", "result": reason}

            def cancel_run(self, run_id):
                self.calls.append(("cancel_run", {"run_id": run_id}))
                return {"run_id": run_id, "status": "cancelled"}

        service = FakeRuntimeService()
        monkeypatch.setattr(
            agent_route_module,
            "get_agent_runtime_service",
            lambda: (_ for _ in ()).throw(AssertionError("agent routes should use AppRuntime service")),
        )
        route_app = FastAPI()
        route_app.state.runtime = SimpleNamespace(agent_runtime_service=service)
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
            runs_response = client.get("/ui/runs?limit=7")
            detail_response = client.get("/ui/runs/run-1")
            approve_response = client.post("/ui/runs/run-1/approval/approve")
            reject_response = client.post(
                "/ui/runs/run-1/approval/reject",
                json={"reason": "Rejected from HTTP"},
            )
            cancel_response = client.post("/ui/runs/run-1/cancel")

        assert agent_response.status_code == 200
        assert agent_response.json()["client_run_id"] == "header-run-1"
        assert workflow_response.status_code == 200
        assert workflow_response.json()["client_run_id"] == "header-workflow-run-1"
        assert runs_response.status_code == 200
        assert runs_response.json()["limit"] == 7
        assert detail_response.status_code == 200
        assert detail_response.json()["run_id"] == "run-1"
        assert approve_response.status_code == 200
        assert approve_response.json()["status"] == "running"
        assert reject_response.status_code == 200
        assert reject_response.json()["result"] == "Rejected from HTTP"
        assert cancel_response.status_code == 200
        assert cancel_response.json()["status"] == "cancelled"
        assert service.calls == [
            (
                "create_agent_run",
                {
                    "agent_id": "agent-1",
                    "user_goal": "hello",
                    "client_run_id": "header-run-1",
                },
            ),
            (
                "create_workflow_run",
                {
                    "workflow_id": "workflow-1",
                    "user_goal": "hello",
                    "client_run_id": "header-workflow-run-1",
                },
            ),
            ("list_runs", {"limit": 7}),
            ("get_run", {"run_id": "run-1"}),
            ("approve_run_approval", {"run_id": "run-1"}),
            ("reject_run_approval", {"run_id": "run-1", "reason": "Rejected from HTTP"}),
            ("cancel_run", {"run_id": "run-1"}),
        ]
    finally:
        sys.modules.pop("_oha_agent_route_http_under_test", None)
        _restore_module_prefixes(("fastapi",), saved_modules)


def test_agent_run_http_routes_roundtrip_approval_detail_and_replay(tmp_path, monkeypatch):
    saved_modules = _unload_module_prefixes(("fastapi",))
    try:
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ModuleNotFoundError as exc:
            pytest.skip(f"FastAPI/TestClient dependency is not installed: {exc.name}")

        route_root = Path(__file__).resolve().parents[1] / "apps" / "bridge" / "routes"
        agent_spec = importlib.util.spec_from_file_location(
            "_oha_agent_route_http_roundtrip_under_test",
            route_root / "agents.py",
        )
        run_spec = importlib.util.spec_from_file_location(
            "_oha_run_route_http_roundtrip_under_test",
            route_root / "runs.py",
        )
        assert agent_spec is not None and agent_spec.loader is not None
        assert run_spec is not None and run_spec.loader is not None
        agent_route_module = importlib.util.module_from_spec(agent_spec)
        run_route_module = importlib.util.module_from_spec(run_spec)
        sys.modules[agent_spec.name] = agent_route_module
        sys.modules[run_spec.name] = run_route_module
        agent_spec.loader.exec_module(agent_route_module)
        run_spec.loader.exec_module(run_route_module)

        service = AgentRuntimeService(
            db_path=tmp_path / "agent-runtime.db",
            workspace_dir=tmp_path / "runtime",
            credential_store=MemoryCredentialStore(),
            seed_templates=False,
        )
        workdir = tmp_path / "workspace"
        workdir.mkdir()
        model_calls: list[list[dict[str, object]]] = []

        def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
            model_calls.append(messages)
            if len(model_calls) == 1:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_terminal_http",
                            "type": "function",
                            "function": {
                                "name": "terminal_run",
                                "arguments": json.dumps({"command": "printf route-approved"}),
                            },
                        }
                    ],
                }
            assert messages[-1]["role"] == "tool"
            assert "route-approved" in messages[-1]["content"]
            return {"content": "HTTP approved command complete"}

        monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
        monkeypatch.setattr(
            agent_route_module,
            "get_agent_runtime_service",
            lambda: (_ for _ in ()).throw(AssertionError("agent routes should use AppRuntime service")),
        )
        monkeypatch.setattr(
            run_route_module,
            "get_native_run_engine",
            lambda: (_ for _ in ()).throw(AssertionError("run routes should use AppRuntime service")),
        )

        route_app = FastAPI()
        route_app.state.runtime = SimpleNamespace(agent_runtime_service=service)
        route_app.include_router(agent_route_module.router)
        route_app.include_router(run_route_module.router)
        try:
            with TestClient(route_app) as client:
                agent_response = client.post(
                    "/ui/agents",
                    json={
                        "name": "HTTP Approval Agent",
                        "model_mode": "custom_api",
                        "model_config": {
                            "base_url": "https://api.example.test/v1",
                            "model": "demo-model",
                            "api_key": "sk-secret",
                        },
                        "tool_policy": {"allowed_tools": ["terminal.run"]},
                        "workspace_policy": {
                            "default_workdir": str(workdir),
                            "readable_scopes": ["."],
                        },
                    },
                )
                agent_response.raise_for_status()
                agent_id = agent_response.json()["agent_id"]

                run_response = client.post(
                    "/ui/agent-runs",
                    json={"agent_id": agent_id, "user_goal": "Run approved command"},
                    headers={"Idempotency-Key": "http-approval-run-1"},
                )
                run_response.raise_for_status()
                waiting = run_response.json()
                run_id = waiting["run_id"]

                detail_before = client.get(f"/ui/runs/{run_id}")
                replay_before = client.get(f"/runs/{run_id}/events?after_sequence=0&limit=200")
                approve_response = client.post(f"/ui/runs/{run_id}/approval/approve")
                detail_after = client.get(f"/ui/runs/{run_id}")
                replay_after = client.get(f"/runs/{run_id}/events?after_sequence=0&limit=200")

            assert waiting["client_request_id"] == "http-approval-run-1"
            assert waiting["status"] == "approval_required"
            assert waiting["pending_approval"]["tool"] == "terminal.run"
            assert detail_before.status_code == 200
            assert detail_before.json()["status"] == "approval_required"
            assert detail_before.json()["pending_approval"]["tool"] == "terminal.run"
            assert replay_before.status_code == 200
            assert "agent.tool.approval_required" in [
                event["event_type"] for event in replay_before.json()["events"]
            ]

            assert approve_response.status_code == 200
            approved = approve_response.json()
            assert approved["status"] == "completed"
            assert approved["pending_approval"] == {}
            assert approved["result"] == "HTTP approved command complete"
            assert detail_after.status_code == 200
            assert detail_after.json()["status"] == "completed"
            assert detail_after.json()["result"] == "HTTP approved command complete"
            assert detail_after.json()["pending_approval"] == {}

            replay_after_payload = replay_after.json()
            replay_after_types = [event["event_type"] for event in replay_after_payload["events"]]
            assert replay_after.status_code == 200
            assert replay_after_types.count("agent.tool.approval_required") == 1
            assert replay_after_types.count("agent.tool.approval_approved") == 1
            assert "agent.tool.call" in replay_after_types
            assert "agent.run.completed" in replay_after_types
            approved_fact = next(
                event
                for event in replay_after_payload["events"]
                if event["event_type"] == "agent.tool.approval_approved"
            )
            tool_facts = [
                event
                for event in replay_after_payload["events"]
                if event["event_type"] == "agent.tool.call"
            ]
            assert approved_fact["payload"]["tool"] == "terminal.run"
            assert approved_fact["payload"]["input_preview"]["command"] == "printf route-approved"
            assert tool_facts[-1]["payload"]["tool"] == "terminal.run"
            assert tool_facts[-1]["payload"]["approved"] is True
            assert len(model_calls) == 2
        finally:
            service.close()
    finally:
        sys.modules.pop("_oha_agent_route_http_roundtrip_under_test", None)
        sys.modules.pop("_oha_run_route_http_roundtrip_under_test", None)
        _restore_module_prefixes(("fastapi",), saved_modules)


def test_workflow_run_http_routes_roundtrip_child_approval_detail_and_replay(tmp_path, monkeypatch):
    saved_modules = _unload_module_prefixes(("fastapi",))
    try:
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ModuleNotFoundError as exc:
            pytest.skip(f"FastAPI/TestClient dependency is not installed: {exc.name}")

        route_root = Path(__file__).resolve().parents[1] / "apps" / "bridge" / "routes"
        agent_spec = importlib.util.spec_from_file_location(
            "_oha_agent_workflow_route_http_roundtrip_under_test",
            route_root / "agents.py",
        )
        run_spec = importlib.util.spec_from_file_location(
            "_oha_run_workflow_route_http_roundtrip_under_test",
            route_root / "runs.py",
        )
        assert agent_spec is not None and agent_spec.loader is not None
        assert run_spec is not None and run_spec.loader is not None
        agent_route_module = importlib.util.module_from_spec(agent_spec)
        run_route_module = importlib.util.module_from_spec(run_spec)
        sys.modules[agent_spec.name] = agent_route_module
        sys.modules[run_spec.name] = run_route_module
        agent_spec.loader.exec_module(agent_route_module)
        run_spec.loader.exec_module(run_route_module)

        service = AgentRuntimeService(
            db_path=tmp_path / "agent-runtime.db",
            workspace_dir=tmp_path / "runtime",
            credential_store=MemoryCredentialStore(),
            seed_templates=False,
        )
        workdir = tmp_path / "workspace"
        workdir.mkdir()
        model_calls: list[list[dict[str, object]]] = []

        def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
            model_calls.append(messages)
            if len(model_calls) == 1:
                assert any((tool.get("function") or {}).get("name") == "terminal_run" for tool in tools or [])
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_workflow_terminal_http",
                            "type": "function",
                            "function": {
                                "name": "terminal_run",
                                "arguments": json.dumps({"command": "printf workflow-http-approved"}),
                            },
                        }
                    ],
                }
            assert messages[-1]["role"] == "tool"
            assert "workflow-http-approved" in messages[-1]["content"]
            return {"content": "Workflow HTTP approved result"}

        monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
        monkeypatch.setattr(
            agent_route_module,
            "get_agent_runtime_service",
            lambda: (_ for _ in ()).throw(AssertionError("agent routes should use AppRuntime service")),
        )
        monkeypatch.setattr(
            run_route_module,
            "get_native_run_engine",
            lambda: (_ for _ in ()).throw(AssertionError("run routes should use AppRuntime service")),
        )

        route_app = FastAPI()
        route_app.state.runtime = SimpleNamespace(agent_runtime_service=service)
        route_app.include_router(agent_route_module.router)
        route_app.include_router(run_route_module.router)
        try:
            with TestClient(route_app) as client:
                agent_response = client.post(
                    "/ui/agents",
                    json={
                        "name": "HTTP Workflow Approval Child",
                        "model_mode": "custom_api",
                        "model_config": {
                            "base_url": "https://api.example.test/v1",
                            "model": "demo-model",
                            "api_key": "sk-secret",
                        },
                        "tool_policy": {"allowed_tools": ["terminal.run"]},
                        "workspace_policy": {
                            "default_workdir": str(workdir),
                            "readable_scopes": ["."],
                        },
                    },
                )
                agent_response.raise_for_status()
                agent_id = agent_response.json()["agent_id"]

                workflow_response = client.post(
                    "/ui/workflows",
                    json={
                        "name": "HTTP Workflow Approval Flow",
                        "nodes": [
                            {"id": "start", "type": "start", "data": {"label": "Start"}},
                            {
                                "id": "agent",
                                "type": "agent",
                                "data": {"label": "HTTP Workflow Approval Child", "agent_id": agent_id},
                            },
                            {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                        ],
                        "edges": [
                            {"source": "start", "target": "agent"},
                            {"source": "agent", "target": "summary"},
                        ],
                    },
                )
                workflow_response.raise_for_status()
                workflow_id = workflow_response.json()["workflow_id"]

                run_response = client.post(
                    "/ui/workflow-runs",
                    json={"workflow_id": workflow_id, "user_goal": "Run workflow approval through HTTP"},
                    headers={"Idempotency-Key": "http-workflow-approval-run-1"},
                )
                run_response.raise_for_status()
                waiting_parent = run_response.json()
                parent_run_id = waiting_parent["run_id"]

                group_response = client.get(f"/ui/run-groups/{waiting_parent['run_group_id']}")
                group_response.raise_for_status()
                child_run_id = next(
                    run_id
                    for run_id in group_response.json()["child_run_ids"]
                    if run_id != parent_run_id
                )

                parent_detail_before = client.get(f"/ui/workflow-runs/{parent_run_id}")
                child_detail_before = client.get(f"/ui/runs/{child_run_id}")
                parent_replay_before = client.get(f"/runs/{parent_run_id}/events?after_sequence=0&limit=200")
                child_replay_before = client.get(f"/runs/{child_run_id}/events?after_sequence=0&limit=200")
                approve_response = client.post(f"/ui/runs/{child_run_id}/approval/approve")
                parent_detail_after = client.get(f"/ui/workflow-runs/{parent_run_id}")
                child_detail_after = client.get(f"/ui/runs/{child_run_id}")
                group_after = client.get(f"/ui/run-groups/{waiting_parent['run_group_id']}")
                parent_replay_after = client.get(f"/runs/{parent_run_id}/events?after_sequence=0&limit=200")
                child_replay_after = client.get(f"/runs/{child_run_id}/events?after_sequence=0&limit=200")
                artifact_response = client.get(f"/ui/runs/{parent_run_id}/artifacts/summary.md")

            assert waiting_parent["client_request_id"] == "http-workflow-approval-run-1"
            assert waiting_parent["status"] == "approval_required"
            assert waiting_parent["pending_approval"] == {}
            assert parent_detail_before.status_code == 200
            assert parent_detail_before.json()["status"] == "approval_required"
            assert child_detail_before.status_code == 200
            assert child_detail_before.json()["status"] == "approval_required"
            assert child_detail_before.json()["pending_approval"]["tool"] == "terminal.run"
            assert child_detail_before.json()["pending_approval"]["input_preview"]["command"] == (
                "printf workflow-http-approved"
            )

            parent_before_types = [event["event_type"] for event in parent_replay_before.json()["events"]]
            child_before_types = [event["event_type"] for event in child_replay_before.json()["events"]]
            assert parent_replay_before.status_code == 200
            assert child_replay_before.status_code == 200
            assert "workflow.run.approval_required" in parent_before_types
            assert "agent.tool.approval_required" in child_before_types

            assert approve_response.status_code == 200
            assert approve_response.json()["status"] == "completed"
            assert approve_response.json()["result"] == "Workflow HTTP approved result"
            assert parent_detail_after.status_code == 200
            assert parent_detail_after.json()["status"] == "completed"
            assert parent_detail_after.json()["result"] == "Workflow HTTP approved result"
            assert child_detail_after.status_code == 200
            assert child_detail_after.json()["status"] == "completed"
            assert child_detail_after.json()["pending_approval"] == {}
            assert group_after.status_code == 200
            assert group_after.json()["status"] == "completed"

            parent_after_events = parent_replay_after.json()["events"]
            parent_after_types = [event["event_type"] for event in parent_after_events]
            child_after_types = [event["event_type"] for event in child_replay_after.json()["events"]]
            assert parent_replay_after.status_code == 200
            assert child_replay_after.status_code == 200
            assert parent_after_types.count("workflow.run.approval_required") == 1
            assert parent_after_types.count("workflow.run.child_resumed") == 1
            assert parent_after_types.count("workflow.run.resumed") == 1
            assert "workflow.run.completed" in parent_after_types
            assert child_after_types.count("agent.tool.approval_required") == 1
            assert child_after_types.count("agent.tool.approval_approved") == 1
            assert "agent.run.completed" in child_after_types
            agent_node_events = [
                event
                for event in parent_after_events
                if event["event_type"] == "workflow.node.agent"
                and event["payload"].get("child_run_id") == child_run_id
            ]
            assert [event["payload"].get("status") for event in agent_node_events] == [
                "approval_required",
                "running",
                "completed",
            ]
            assert artifact_response.status_code == 200
            assert artifact_response.json()["path"] == "summary.md"
            assert artifact_response.json()["content"] == "Workflow HTTP approved result"
            assert len(model_calls) == 2
        finally:
            service.close()
    finally:
        sys.modules.pop("_oha_agent_workflow_route_http_roundtrip_under_test", None)
        sys.modules.pop("_oha_run_workflow_route_http_roundtrip_under_test", None)
        _restore_module_prefixes(("fastapi",), saved_modules)


def test_agent_studio_crud_http_routes_use_app_runtime_service(monkeypatch):
    saved_modules = _unload_module_prefixes(("fastapi",))
    try:
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ModuleNotFoundError as exc:
            pytest.skip(f"FastAPI/TestClient dependency is not installed: {exc.name}")

        route_path = Path(__file__).resolve().parents[1] / "apps" / "bridge" / "routes" / "agents.py"
        spec = importlib.util.spec_from_file_location("_oha_agent_crud_route_http_under_test", route_path)
        assert spec is not None
        assert spec.loader is not None
        agent_route_module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = agent_route_module
        spec.loader.exec_module(agent_route_module)

        class FakeRuntimeService:
            def __init__(self):
                self.calls: list[str] = []

            def list_agents(self):
                self.calls.append("list_agents")
                return {"agents": [{"agent_id": "agent-1"}]}

            def create_agent(self, payload):
                self.calls.append("create_agent")
                return {"agent_id": "agent-1", **payload}

            def get_agent(self, agent_id):
                self.calls.append("get_agent")
                return {"agent_id": agent_id}

            def update_agent(self, agent_id, payload):
                self.calls.append("update_agent")
                return {"agent_id": agent_id, **payload}

            def delete_agent(self, agent_id):
                self.calls.append("delete_agent")
                return {"ok": True, "agent_id": agent_id}

            def test_agent_model(self, agent_id):
                self.calls.append("test_agent_model")
                return {"ok": True, "agent_id": agent_id}

            def attach_skill(self, agent_id, skill_id):
                self.calls.append("attach_skill")
                return {"ok": True, "agent_id": agent_id, "skill_id": skill_id}

            def detach_skill(self, agent_id, skill_id):
                self.calls.append("detach_skill")
                return {"ok": True, "agent_id": agent_id, "skill_id": skill_id}

            def list_skills(self):
                self.calls.append("list_skills")
                return {"skills": [{"skill_id": "skill-1"}]}

            def import_skill(self, source_path, folder_id):
                self.calls.append("import_skill")
                return {"ok": True, "source_path": source_path, "folder_id": folder_id}

            def list_native_skill_sources(self):
                self.calls.append("list_native_skill_sources")
                return {"sources": [{"source": "installed"}]}

            def list_skill_folders(self):
                self.calls.append("list_skill_folders")
                return {"folders": [{"folder_id": "folder-1"}]}

            def create_skill_folder(self, payload):
                self.calls.append("create_skill_folder")
                return {"folder_id": "folder-1", **payload}

            def update_skill_folder(self, folder_id, payload):
                self.calls.append("update_skill_folder")
                return {"folder_id": folder_id, **payload}

            def delete_skill_folder(self, folder_id, *, delete_skills=False):
                self.calls.append("delete_skill_folder")
                return {"ok": True, "folder_id": folder_id, "delete_skills": delete_skills}

            def sync_native_skills(self):
                self.calls.append("sync_native_skills")
                return {"ok": True}

            def install_skill_command(self, command, folder_id):
                self.calls.append("install_skill_command")
                return {"ok": True, "command": command, "folder_id": folder_id}

            def get_skill(self, skill_id):
                self.calls.append("get_skill")
                return {"skill_id": skill_id}

            def update_skill(self, skill_id, payload):
                self.calls.append("update_skill")
                return {"skill_id": skill_id, **payload}

            def delete_skill(self, skill_id):
                self.calls.append("delete_skill")
                return {"ok": True, "skill_id": skill_id}

            def list_workflows(self):
                self.calls.append("list_workflows")
                return {"workflows": [{"workflow_id": "workflow-1"}]}

            def create_workflow(self, payload):
                self.calls.append("create_workflow")
                return {"workflow_id": "workflow-1", **payload}

            def get_workflow(self, workflow_id):
                self.calls.append("get_workflow")
                return {"workflow_id": workflow_id}

            def update_workflow(self, workflow_id, payload):
                self.calls.append("update_workflow")
                return {"workflow_id": workflow_id, **payload}

            def delete_workflow(self, workflow_id):
                self.calls.append("delete_workflow")
                return {"ok": True, "workflow_id": workflow_id}

            def list_runnables(self):
                self.calls.append("list_runnables")
                return {"runnables": [{"id": "agent-1"}]}

        service = FakeRuntimeService()
        monkeypatch.setattr(
            agent_route_module,
            "get_agent_runtime_service",
            lambda: (_ for _ in ()).throw(AssertionError("agent studio CRUD routes should use AppRuntime service")),
        )
        route_app = FastAPI()
        route_app.state.runtime = SimpleNamespace(agent_runtime_service=service)
        route_app.include_router(agent_route_module.router)

        with TestClient(route_app) as client:
            responses = [
                client.get("/ui/agents"),
                client.post("/ui/agents", json={"name": "Agent 1"}),
                client.get("/ui/agents/agent-1"),
                client.patch("/ui/agents/agent-1", json={"name": "Agent 2"}),
                client.delete("/ui/agents/agent-1"),
                client.post("/ui/agents/agent-1/test-model"),
                client.post("/ui/agents/agent-1/skills", json={"skill_id": "skill-1"}),
                client.delete("/ui/agents/agent-1/skills/skill-1"),
                client.get("/ui/skills"),
                client.post("/ui/skills", json={"source_path": "/tmp/skill.md", "folder_id": "folder-1"}),
                client.post("/ui/skills/import", json={"source_path": "/tmp/skill-2.md"}),
                client.get("/ui/skills/sources"),
                client.get("/ui/skill-folders"),
                client.post("/ui/skill-folders", json={"name": "Folder"}),
                client.patch("/ui/skill-folders/folder-1", json={"name": "Folder 2"}),
                client.delete("/ui/skill-folders/folder-1?delete_skills=true"),
                client.post("/ui/skills/sync"),
                client.post("/ui/skills/install", json={"command": "install skill", "folder_id": "folder-1"}),
                client.get("/ui/skills/skill-1"),
                client.patch("/ui/skills/skill-1", json={"enabled": False}),
                client.delete("/ui/skills/skill-1"),
                client.get("/ui/workflows"),
                client.post("/ui/workflows", json={"name": "Workflow 1"}),
                client.get("/ui/workflows/workflow-1"),
                client.patch("/ui/workflows/workflow-1", json={"name": "Workflow 2"}),
                client.delete("/ui/workflows/workflow-1"),
                client.get("/ui/runnables"),
            ]

        assert all(response.status_code == 200 for response in responses)
        assert service.calls == [
            "list_agents",
            "create_agent",
            "get_agent",
            "update_agent",
            "delete_agent",
            "test_agent_model",
            "attach_skill",
            "detach_skill",
            "list_skills",
            "import_skill",
            "import_skill",
            "list_native_skill_sources",
            "list_skill_folders",
            "create_skill_folder",
            "update_skill_folder",
            "delete_skill_folder",
            "sync_native_skills",
            "install_skill_command",
            "get_skill",
            "update_skill",
            "delete_skill",
            "list_workflows",
            "create_workflow",
            "get_workflow",
            "update_workflow",
            "delete_workflow",
            "list_runnables",
        ]
    finally:
        sys.modules.pop("_oha_agent_crud_route_http_under_test", None)
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
