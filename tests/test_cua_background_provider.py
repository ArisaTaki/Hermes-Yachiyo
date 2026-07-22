"""Contract tests for the optional Cua background desktop provider."""

from __future__ import annotations

import hashlib
import json
import queue
import threading
from typing import Any, Callable, Mapping

import pytest

from apps.shell.agent.runtime import cua_background_provider as cua_background_provider_module
from apps.shell.agent.runtime.cua_background_provider import (
    CUA_BACKGROUND_PROVIDER_KIND,
    CuaBackgroundDesktopExecutionProviderAdapter,
    CuaMcpClient,
    CuaMcpTimeoutError,
    CuaMcpToolError,
    CuaMcpTransportError,
    cua_background_provider_adapter_from_env,
    cua_background_provider_status,
    invalidate_cua_background_provider_caches,
    resolve_cua_mcp_command,
)
from apps.shell.agent.runtime.desktop_execution_providers import (
    DesktopExecutionProviderRegistry,
)
from apps.shell.agent.runtime.tool_execution import RuntimeToolCallExecutor
from apps.shell.agent.runtime.verification_receipts import (
    RUNTIME_PRIVATE_VERIFICATION_AUTHORITY,
)


class _QueueTextStream:
    def __init__(self) -> None:
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._closed = False

    def push_json(self, payload: Mapping[str, Any]) -> None:
        self._lines.put(json.dumps(dict(payload)) + "\n")

    def readline(self) -> str:
        line = self._lines.get()
        return "" if line is None else line

    def read(self) -> str:
        lines: list[str] = []
        while True:
            line = self.readline()
            if not line:
                return "".join(lines)
            lines.append(line)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._lines.put(None)


class _FakeStdin:
    def __init__(self, on_message: Callable[[dict[str, Any]], None]) -> None:
        self._on_message = on_message
        self._buffer = ""
        self.closed = False

    def write(self, chunk: str) -> int:
        assert not self.closed
        self._buffer += chunk
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._on_message(json.loads(line))
        return len(chunk)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class FakeMcpProcess:
    """Small line-delimited JSON-RPC peer; it never starts an OS process."""

    def __init__(
        self,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_results: Mapping[str, Mapping[str, Any]] | None = None,
        tool_result_sequences: Mapping[
            str,
            list[Mapping[str, Any]],
        ]
        | None = None,
        hang_methods: set[str] | None = None,
        exit_methods: set[str] | None = None,
    ) -> None:
        self.tools = list(tools or [])
        tool_names = {str(tool.get("name") or "") for tool in self.tools}
        if (
            "launch_app" in tool_names
            and tool_names.intersection(
                {"click", "get_window_state", "hotkey", "press_key", "scroll", "type_text"}
            )
            and "list_apps" not in tool_names
        ):
            self.tools.append(_list_apps_tool())
        self.tool_results = {
            str(name): dict(result) for name, result in (tool_results or {}).items()
        }
        self.tool_result_sequences = {
            str(name): [dict(result) for result in results]
            for name, results in (tool_result_sequences or {}).items()
        }
        self.hang_methods = set(hang_methods or set())
        self.exit_methods = set(exit_methods or set())
        self.requests: list[dict[str, Any]] = []
        self.stdout = _QueueTextStream()
        self.stderr = _QueueTextStream()
        self.stdin = _FakeStdin(self._receive)
        self.returncode: int | None = None
        self.pid = 4242
        self._exited = threading.Event()
        self._last_launch_arguments: dict[str, Any] = {}
        self._last_launch_result: dict[str, Any] = {}

    def _receive(self, request: dict[str, Any]) -> None:
        self.requests.append(request)
        method = str(request.get("method") or "")
        if method in self.exit_methods:
            self.force_exit(17)
            return
        if method in self.hang_methods or "id" not in request:
            return
        request_id = request["id"]
        if method == "initialize":
            result: dict[str, Any] = {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-cua-driver", "version": "0-test"},
            }
        elif method == "tools/list":
            result = {"tools": self.tools}
        elif method == "tools/call":
            name = str((request.get("params") or {}).get("name") or "")
            arguments = (request.get("params") or {}).get("arguments")
            result_sequence = self.tool_result_sequences.get(name) or []
            if result_sequence:
                result = dict(result_sequence.pop(0))
            elif name == "list_apps" and name not in self.tool_results:
                structured = self._last_launch_result
                pid = structured.get("pid")
                app_name = (
                    structured.get("name")
                    or self._last_launch_arguments.get("name")
                    or "Unknown"
                )
                bundle_id = str(structured.get("bundle_id") or "")
                result = (
                    _list_apps_identity_result(
                        int(pid),
                        name=str(app_name),
                        bundle_id=bundle_id,
                    )
                    if pid is not None
                    else {
                        "content": [{"type": "text", "text": "ok"}],
                        "structuredContent": {"apps": []},
                        "isError": False,
                    }
                )
            else:
                result = dict(
                    self.tool_results.get(
                        name,
                        {
                            "content": [{"type": "text", "text": "ok"}],
                            "structuredContent": {"ok": True},
                            "isError": False,
                        },
                    )
                )
            if name == "launch_app":
                if isinstance(arguments, Mapping):
                    self._last_launch_arguments = dict(arguments)
                structured = result.get("structuredContent")
                if (
                    isinstance(structured, Mapping)
                    and structured.get("pid") is not None
                    and "self_activation_suppressed" not in structured
                ):
                    structured = {
                        **dict(structured),
                        "self_activation_suppressed": True,
                    }
                    result = {**result, "structuredContent": structured}
                self._last_launch_result = (
                    dict(structured) if isinstance(structured, Mapping) else {}
                )
        else:
            self.stdout.push_json(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": "method not found"},
                }
            )
            return
        self.stdout.push_json(
            {"jsonrpc": "2.0", "id": request_id, "result": result}
        )

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None and not self._exited.wait(timeout):
            raise TimeoutError("fake process did not exit")
        return int(self.returncode or 0)

    def terminate(self) -> None:
        self.force_exit(-15)

    def kill(self) -> None:
        self.force_exit(-9)

    def force_exit(self, returncode: int) -> None:
        if self.returncode is not None:
            return
        self.returncode = returncode
        self.stdout.close()
        self.stderr.close()
        self._exited.set()


class _ExecutorBudget:
    def claim_tool_call(self, _tool_name: str, **_kwargs: Any) -> None:
        return None


class _NoopToolCallEvents:
    def __getattr__(self, _name: str) -> Callable[..., None]:
        return lambda *_args, **_kwargs: None


class _NoopTraceEvents:
    @staticmethod
    def memory_skill_trace_event(
        _tool_name: str,
        _input_preview: Any,
        _tool_result: Mapping[str, Any],
    ) -> None:
        return None


class _FailingLocalBroker:
    def call(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("trusted Cua requests must not fall through locally")


def _runtime_executor_for_cua(
    adapter: CuaBackgroundDesktopExecutionProviderAdapter,
) -> RuntimeToolCallExecutor:
    return RuntimeToolCallExecutor(
        normalize_tool_name=lambda value: str(value or "").strip(),
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: _ExecutorBudget(),
        validate_tool_payload=lambda _tool_name, _payload: None,
        limit_tool_result=lambda result: result,
        timeline_factory=lambda event, detail="", **extra: {
            "event": event,
            "detail": detail,
            **extra,
        },
        tool_call_events=_NoopToolCallEvents(),
        trace_events=_NoopTraceEvents(),
        append_run_event=lambda _run_id, _event_type, _payload: None,
        desktop_provider_registry=DesktopExecutionProviderRegistry([adapter]),
    )


class _CompletedProcess:
    def __init__(
        self,
        *,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _client_for(
    process: FakeMcpProcess,
    *,
    timeout: float = 0.25,
    transport_kind: str = "mcp_stdio",
) -> CuaMcpClient:
    def fake_popen(*_args: Any, **_kwargs: Any) -> FakeMcpProcess:
        return process

    return CuaMcpClient(
        command=("never-run-cua-driver", "mcp"),
        environ={"CUA_DRIVER_RS_TELEMETRY_ENABLED": "0"},
        timeout=timeout,
        popen_factory=fake_popen,
        transport_kind=transport_kind,
    )


def _tool_request(tool_name: str) -> dict[str, Any]:
    return {
        "tool": tool_name,
        "sandbox_provider": {
            "provider_id": "cua-driver",
            "provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
            "supported_tools": [tool_name],
        },
    }


def _route(tool_name: str) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "selected_provider_id": "cua-driver",
        "selected_provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
        "foreground_takeover_required": False,
    }


def _type_text_tool() -> dict[str, Any]:
    return {
        "name": "type_text",
        "description": "Type into a PID-targeted background window",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pid": {"type": "integer"},
                "text": {"type": "string"},
                "delivery_mode": {
                    "type": "string",
                    "enum": ["background", "foreground"],
                },
            },
            "required": ["pid", "text"],
        },
    }


def _launch_app_tool() -> dict[str, Any]:
    return {
        "name": "launch_app",
        "description": "Launch an application without foreground takeover",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "creates_new_application_instance": {"type": "boolean"},
                "delivery_mode": {
                    "type": "string",
                    "enum": ["background", "foreground"],
                },
            },
            "required": ["name"],
        },
    }


def _list_apps_tool() -> dict[str, Any]:
    return {
        "name": "list_apps",
        "description": "List applications known to Cua Driver",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    }


def _health_report_tool(*, supports_skip: bool = True) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "include": {
            "type": "array",
            "items": {"type": "string"},
        }
    }
    if supports_skip:
        properties["skip"] = {
            "type": "array",
            "items": {"type": "string"},
        }
    return {
        "name": "health_report",
        "description": "Report readiness without prompting",
        "inputSchema": {
            "type": "object",
            "properties": properties,
        },
    }


def _check_permissions_tool() -> dict[str, Any]:
    return {
        "name": "check_permissions",
        "inputSchema": {
            "type": "object",
            "properties": {"prompt": {"type": "boolean"}},
            "additionalProperties": False,
        },
    }


def _embedded_permissions_result(
    *,
    accessibility: bool = True,
    screen_recording: bool = True,
    attribution: str = "host",
    embedded: bool = True,
) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": "permissions checked"}],
        "structuredContent": {
            "accessibility": accessibility,
            "screen_recording": screen_recording,
            "source": {
                "attribution": attribution,
                "embedded": embedded,
            },
        },
        "isError": False,
    }


def _list_apps_identity_result(
    pid: int,
    *,
    name: str = "TextEdit",
    bundle_id: str = "",
) -> dict[str, Any]:
    app = {"pid": pid, "running": True, "name": name}
    if bundle_id:
        app["bundle_id"] = bundle_id
    return {
        "content": [{"type": "text", "text": "listed"}],
        "structuredContent": {"apps": [app]},
        "isError": False,
    }


def _list_windows_tool() -> dict[str, Any]:
    return {
        "name": "list_windows",
        "description": "List top-level windows, optionally filtered by pid",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pid": {"type": "integer"},
                "on_screen_only": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    }


def _get_window_state_tool() -> dict[str, Any]:
    return {
        "name": "get_window_state",
        "description": "Read one PID-targeted background window",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pid": {"type": "integer"},
                "window_id": {"type": "integer"},
            },
            "required": ["pid", "window_id"],
        },
    }


def _click_tool() -> dict[str, Any]:
    return {
        "name": "click",
        "description": "Click a window-relative Cua target",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pid": {"type": "integer"},
                "window_id": {"type": "integer"},
                "element_index": {"type": "integer"},
                "element_token": {"type": "string"},
                "x": {"type": "number"},
                "y": {"type": "number"},
                "delivery_mode": {"type": "string"},
            },
            "required": ["pid"],
        },
    }


def _grounded_type_text_tool() -> dict[str, Any]:
    return {
        "name": "type_text",
        "description": "Type into one target-bound Cua element",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pid": {"type": "integer"},
                "window_id": {"type": "integer"},
                "element_index": {"type": "integer"},
                "element_token": {"type": "string"},
                "text": {"type": "string"},
                "delivery_mode": {"type": "string"},
            },
            "required": ["pid", "window_id", "text"],
        },
    }


def _scroll_tool() -> dict[str, Any]:
    return {
        "name": "scroll",
        "description": "Scroll the focused region of a PID-targeted window",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pid": {"type": "integer"},
                "direction": {"type": "string"},
                "amount": {"type": "integer"},
                "by": {"type": "string"},
                "delivery_mode": {"type": "string"},
            },
            "required": ["pid", "direction"],
        },
    }


def _background_input_tool(
    name: str,
    *argument_names: str,
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "pid": {"type": "integer"},
        "delivery_mode": {
            "type": "string",
            "enum": ["background", "foreground"],
        },
    }
    for argument_name in argument_names:
        properties[argument_name] = (
            {"type": "array", "items": {"type": "string"}}
            if argument_name in {"keys", "modifiers"}
            else {"type": "string"}
        )
    return {
        "name": name,
        "description": f"PID-targeted background {name}",
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": ["pid", *argument_names],
        },
    }


def _scoped_tool_request(tool_name: str, core_id: str) -> dict[str, Any]:
    return {
        **_tool_request(tool_name),
        "core_id": core_id,
        "task_id": f"task:{core_id}",
        "_runtime_execution_scope": {
            "run_id": f"run:{core_id}",
            "task_id": f"task:{core_id}",
            "core_id": core_id,
        },
    }


def _trusted_verification_context(
    core_id: str,
    *,
    predicate: Mapping[str, Any] | None = None,
    source_tool: str = "app.open",
) -> dict[str, Any]:
    return {
        "version": 1,
        "_authority": RUNTIME_PRIVATE_VERIFICATION_AUTHORITY,
        "run_id": f"run:{core_id}",
        "plan_id": "plan-notes",
        "tool_plan_id": "tool-plan-notes",
        "source_tool_call_id": "call-open-notes",
        "source_step_id": "open-notes",
        "source_tool": source_tool,
        "provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
        "provider_id": "cua-driver",
        "target": {
            "pid": 731011,
            "window_id": 1911,
            "app_name": "Notes",
            "agent_owned_target": True,
        },
        "predicate": dict(
            predicate
            or {"kind": "app_window_present", "app_name": "Notes"}
        ),
    }


def _mcp_tool_calls(process: FakeMcpProcess) -> list[dict[str, Any]]:
    return [
        request
        for request in process.requests
        if request.get("method") == "tools/call"
    ]


def test_command_discovery_prefers_explicit_environment_configuration() -> None:
    discovery_calls: list[str] = []

    def unexpected_run(*_args: Any, **_kwargs: Any) -> _CompletedProcess:
        discovery_calls.append("run")
        return _CompletedProcess()

    def unexpected_which(_name: str) -> str:
        discovery_calls.append("which")
        return "/usr/local/bin/cua-driver"

    command = resolve_cua_mcp_command(
        {
            "OHA_YACHIYO_CUA_DRIVER_COMMAND": (
                "'/Applications/Cua Driver.app/Contents/MacOS/cua-driver' mcp"
            )
        },
        run=unexpected_run,
        which=unexpected_which,
        path_exists=lambda _path: True,
    )

    assert command == (
        "/Applications/Cua Driver.app/Contents/MacOS/cua-driver",
        "mcp",
    )
    assert discovery_calls == []


def test_command_discovery_prefers_path_driver_manifest_mcp_invocation() -> None:
    manifest_commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: Any) -> _CompletedProcess:
        manifest_commands.append(command)
        return _CompletedProcess(
            stdout=json.dumps(
                {
                    "mcp_invocation": [
                        "/Applications/CuaDriver.app/Contents/MacOS/cua-driver",
                        "mcp",
                        "--stdio",
                    ]
                }
            )
        )

    command = resolve_cua_mcp_command(
        {},
        run=fake_run,
        which=lambda name: (
            "/opt/homebrew/bin/cua-driver" if name == "cua-driver" else None
        ),
        path_exists=lambda _path: False,
    )

    assert manifest_commands == [["/opt/homebrew/bin/cua-driver", "manifest"]]
    assert command == (
        "/Applications/CuaDriver.app/Contents/MacOS/cua-driver",
        "mcp",
        "--stdio",
    )


def test_command_discovery_uses_common_path_and_falls_back_to_mcp() -> None:
    checked_paths: list[str] = []

    def fake_path_exists(path: str) -> bool:
        checked_paths.append(path)
        return path.endswith("/.local/bin/cua-driver")

    command = resolve_cua_mcp_command(
        {"HOME": "/Users/tester"},
        run=lambda *_args, **_kwargs: _CompletedProcess(
            stdout="not-json",
            returncode=0,
        ),
        which=lambda _name: None,
        path_exists=fake_path_exists,
    )

    assert command is not None
    assert command[-1] == "mcp"
    assert command[0].endswith("/.local/bin/cua-driver")
    assert command[0] in checked_paths


def test_adapter_discovery_returns_installed_provider_without_starting_it() -> None:
    popen_calls: list[dict[str, Any]] = []

    def forbidden_popen(*_args: Any, **kwargs: Any) -> FakeMcpProcess:
        popen_calls.append(kwargs)
        raise AssertionError("adapter discovery must not start Cua MCP")

    adapter = cua_background_provider_adapter_from_env(
        {},
        run=lambda *_args, **_kwargs: _CompletedProcess(
            stdout=json.dumps(
                {"mcp_invocation": ["/opt/homebrew/bin/cua-driver", "mcp"]}
            )
        ),
        which=lambda name: (
            "/opt/homebrew/bin/cua-driver" if name == "cua-driver" else None
        ),
        path_exists=lambda _path: False,
        popen_factory=forbidden_popen,
    )

    assert isinstance(adapter, CuaBackgroundDesktopExecutionProviderAdapter)
    assert adapter.client.command == ("/opt/homebrew/bin/cua-driver", "mcp")
    assert popen_calls == []
    adapter.close()


def test_adapter_discovery_returns_none_when_cua_driver_is_missing() -> None:
    adapter = cua_background_provider_adapter_from_env(
        {},
        run=lambda *_args, **_kwargs: _CompletedProcess(returncode=127),
        which=lambda _name: None,
        path_exists=lambda _path: False,
        popen_factory=lambda *_args, **_kwargs: pytest.fail(
            "missing provider must not start Cua MCP"
        ),
    )

    assert adapter is None


def test_provider_status_does_not_start_mcp_without_health_probe() -> None:
    popen_calls: list[dict[str, Any]] = []
    manifest_calls: list[list[str]] = []

    def forbidden_popen(*_args: Any, **kwargs: Any) -> FakeMcpProcess:
        popen_calls.append(kwargs)
        raise AssertionError("default provider status must be side-effect free")

    def fake_run(command: list[str], **_kwargs: Any) -> _CompletedProcess:
        manifest_calls.append(command)
        return _CompletedProcess(
            stdout=json.dumps(
                {"mcp_invocation": ["/opt/homebrew/bin/cua-driver", "mcp"]}
            )
        )

    def fake_which(name: str) -> str | None:
        return (
            "/opt/homebrew/bin/cua-driver" if name == "cua-driver" else None
        )

    def path_exists(_path: str) -> bool:
        return False

    invalidate_cua_background_provider_caches()
    status = {}
    for _index in range(2):
        status = cua_background_provider_status(
            {},
            run=fake_run,
            which=fake_which,
            path_exists=path_exists,
            popen_factory=forbidden_popen,
        )

    assert status["provider_kind"] == CUA_BACKGROUND_PROVIDER_KIND
    assert status["configured"] is True
    assert status["available"] is False
    assert status["adapter_ready"] is False
    assert status["status"] == "installed_not_checked"
    assert status["setup_state"] == "installed"
    assert status["foreground_takeover_required"] is False
    assert status["health"]["checked"] is False
    assert manifest_calls == [["/opt/homebrew/bin/cua-driver", "manifest"]]
    assert popen_calls == []


def test_missing_provider_status_requires_background_desktop_setup() -> None:
    status = cua_background_provider_status(
        {},
        run=lambda *_args, **_kwargs: _CompletedProcess(returncode=127),
        which=lambda _name: None,
        path_exists=lambda _path: False,
        popen_factory=lambda *_args, **_kwargs: pytest.fail(
            "missing provider status must not start Cua MCP"
        ),
    )

    assert status["provider_kind"] == CUA_BACKGROUND_PROVIDER_KIND
    assert status["available"] is False
    assert status["adapter_ready"] is False
    assert status["status"] == "provider_required"
    assert status["setup_state"] == "required"
    assert "cua_driver_not_installed" in status["blocking_conditions"]


def test_health_uses_noninteractive_health_report_and_never_permission_prompt() -> None:
    process = FakeMcpProcess(
        tools=[
            _launch_app_tool(),
            _list_apps_tool(),
            _health_report_tool(),
            _check_permissions_tool(),
        ],
        tool_results={
            "health_report": {
                "content": [{"type": "text", "text": "ready"}],
                "structuredContent": {
                    "schema_version": "1",
                    "overall": "ok",
                    "checks": [
                        {
                            "name": "tcc_accessibility",
                            "status": "pass",
                            "message": "Accessibility is available.",
                        },
                        {
                            "name": "tcc_screen_recording",
                            "status": "pass",
                            "message": "Screen Recording is available.",
                        }
                    ],
                },
                "isError": False,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open"],
    )
    try:
        health = adapter.health()
    finally:
        client.close()

    assert health["ok"] is True
    assert health["status"] == "healthy"
    assert health["supported_tools"] == ["app.open"]
    assert [call["params"] for call in _mcp_tool_calls(process)] == [
        {"name": "health_report", "arguments": {}}
    ]


@pytest.mark.parametrize(
    ("transport_kind", "expected_arguments", "bundle_identity_status"),
    [
        (
            "electron_bridge",
            {"skip": ["bundle_identity"]},
            "skip",
        ),
        ("mcp_stdio", {}, "pass"),
    ],
)
def test_health_skips_bundle_identity_only_for_embedded_electron_bridge(
    transport_kind: str,
    expected_arguments: dict[str, Any],
    bundle_identity_status: str,
) -> None:
    process = FakeMcpProcess(
        tools=[
            _launch_app_tool(),
            _list_apps_tool(),
            _health_report_tool(),
            _check_permissions_tool(),
        ],
        tool_results={
            "health_report": {
                "content": [{"type": "text", "text": "ready"}],
                "structuredContent": {
                    "schema_version": "1",
                    "overall": "ok",
                    "checks": [
                        {
                            "name": "tcc_accessibility",
                            "status": "pass",
                            "message": "Accessibility is available.",
                        },
                        {
                            "name": "tcc_screen_recording",
                            "status": "pass",
                            "message": "Screen Recording is available.",
                        },
                        {
                            "name": "bundle_identity",
                            "status": bundle_identity_status,
                            "message": "Bundle identity check completed.",
                        },
                    ],
                },
                "isError": False,
            },
            "check_permissions": _embedded_permissions_result(),
        },
    )
    client = _client_for(process, transport_kind=transport_kind)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open"],
    )
    try:
        health = adapter.health()
    finally:
        client.close()

    assert health["ok"] is True
    assert health["status"] == "healthy"
    expected_calls = [
        {"name": "health_report", "arguments": expected_arguments}
    ]
    if transport_kind == "electron_bridge":
        expected_calls.append(
            {"name": "check_permissions", "arguments": {"prompt": False}}
        )
    assert [call["params"] for call in _mcp_tool_calls(process)] == expected_calls


@pytest.mark.parametrize(
    "schema_fields",
    [
        pytest.param({}, id="missing"),
        pytest.param({"schema_version": 1}, id="integer-one"),
        pytest.param({"schema_version": "2"}, id="future-version"),
        pytest.param({"schema_version": "unknown"}, id="unknown-version"),
    ],
)
def test_health_rejects_unsupported_health_report_schema_even_when_overall_ok(
    schema_fields: dict[str, Any],
) -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _list_apps_tool(), _health_report_tool()],
        tool_results={
            "health_report": {
                "content": [{"type": "text", "text": "ready"}],
                "structuredContent": {
                    **schema_fields,
                    "overall": "ok",
                    "checks": [
                        {
                            "name": "tcc_accessibility",
                            "status": "pass",
                            "message": "Accessibility is available.",
                        }
                    ],
                },
                "isError": False,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open"],
    )
    try:
        health = adapter.health()
    finally:
        client.close()

    assert health["ok"] is False
    assert health["status"] == "health_report_contract_unsupported"
    assert health["blocking_conditions"] == [
        "cua_health_report_contract_unsupported"
    ]


def test_embedded_health_requires_health_report_skip_contract_before_calling_it() -> None:
    process = FakeMcpProcess(
        tools=[
            _launch_app_tool(),
            _list_apps_tool(),
            _health_report_tool(supports_skip=False),
            _check_permissions_tool(),
        ],
    )
    client = _client_for(process, transport_kind="electron_bridge")
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open"],
    )
    try:
        health = adapter.health()
    finally:
        client.close()

    assert health["ok"] is False
    assert health["status"] == "health_report_contract_unsupported"
    assert health["blocking_conditions"] == [
        "cua_health_report_contract_unsupported"
    ]
    assert _mcp_tool_calls(process) == []


@pytest.mark.parametrize(
    ("attribution", "embedded"),
    [
        pytest.param("caller", True, id="caller-attribution"),
        pytest.param("host", False, id="not-embedded"),
    ],
)
def test_embedded_health_rejects_non_host_permission_attribution(
    attribution: str,
    embedded: bool,
) -> None:
    process = FakeMcpProcess(
        tools=[
            _launch_app_tool(),
            _list_apps_tool(),
            _health_report_tool(),
            _check_permissions_tool(),
        ],
        tool_results={
            "health_report": {
                "content": [{"type": "text", "text": "ready"}],
                "structuredContent": {
                    "schema_version": "1",
                    "overall": "ok",
                    "checks": [],
                },
                "isError": False,
            },
            "check_permissions": _embedded_permissions_result(
                attribution=attribution,
                embedded=embedded,
            ),
        },
    )
    client = _client_for(process, transport_kind="electron_bridge")
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open"],
    )
    try:
        health = adapter.health()
    finally:
        client.close()

    assert health["ok"] is False
    assert health["status"] == "embedded_permission_attribution_invalid"
    assert health["blocking_conditions"] == [
        "cua_embedded_host_attribution_failed"
    ]
    assert [call["params"] for call in _mcp_tool_calls(process)] == [
        {
            "name": "health_report",
            "arguments": {"skip": ["bundle_identity"]},
        },
        {"name": "check_permissions", "arguments": {"prompt": False}},
    ]


@pytest.mark.parametrize(
    ("permission_fields", "expected_blocker"),
    [
        pytest.param(
            {"accessibility": False, "screen_recording": True},
            "desktop_permission_accessibility_required",
            id="accessibility-false",
        ),
        pytest.param(
            {"accessibility": True, "screen_recording": False},
            "desktop_permission_screen_recording_required",
            id="screen-recording-false",
        ),
        pytest.param(
            {"screen_recording": True},
            "desktop_permission_accessibility_required",
            id="accessibility-field-missing",
        ),
        pytest.param(
            {"accessibility": "true", "screen_recording": True},
            "desktop_permission_accessibility_required",
            id="accessibility-not-boolean",
        ),
        pytest.param(
            {"accessibility": True},
            "desktop_permission_screen_recording_required",
            id="screen-recording-field-missing",
        ),
        pytest.param(
            {"accessibility": True, "screen_recording": 1},
            "desktop_permission_screen_recording_required",
            id="screen-recording-not-boolean",
        ),
    ],
)
def test_embedded_health_fails_closed_when_host_permissions_are_not_true(
    permission_fields: dict[str, Any],
    expected_blocker: str,
) -> None:
    process = FakeMcpProcess(
        tools=[
            _launch_app_tool(),
            _list_apps_tool(),
            _health_report_tool(),
            _check_permissions_tool(),
        ],
        tool_results={
            "health_report": {
                "content": [{"type": "text", "text": "ready"}],
                "structuredContent": {
                    "schema_version": "1",
                    "overall": "ok",
                    "checks": [],
                },
                "isError": False,
            },
            "check_permissions": {
                "content": [{"type": "text", "text": "permissions checked"}],
                "structuredContent": {
                    **permission_fields,
                    "source": {
                        "attribution": "host",
                        "embedded": True,
                    },
                },
                "isError": False,
            },
        },
    )
    client = _client_for(process, transport_kind="electron_bridge")
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open"],
    )
    try:
        health = adapter.health()
    finally:
        client.close()

    assert health["ok"] is False
    assert health["status"] != "healthy"
    assert expected_blocker in health["blocking_conditions"]


def test_health_without_health_report_does_not_claim_provider_ready() -> None:
    process = FakeMcpProcess(tools=[_launch_app_tool(), _list_apps_tool()])
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open"],
    )
    try:
        health = adapter.health()
    finally:
        client.close()

    assert health["ok"] is False
    assert health["status"] == "health_report_unavailable"
    assert health["blocking_conditions"] == [
        "desktop_execution_provider_health_unavailable"
    ]
    assert _mcp_tool_calls(process) == []


def test_health_does_not_advertise_composite_with_missing_dependency() -> None:
    process = FakeMcpProcess(
        tools=[
            _launch_app_tool(),
            _list_apps_tool(),
            _background_input_tool("hotkey", "keys"),
            _health_report_tool(),
        ],
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open_and_safe_shortcut"],
    )
    try:
        health = adapter.health()
    finally:
        client.close()

    assert health["ok"] is False
    assert health["status"] == "required_tools_missing"
    assert health["supported_tools"] == []
    assert _mcp_tool_calls(process) == []


def test_official_degraded_health_report_blocks_readiness() -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _list_apps_tool(), _health_report_tool()],
        tool_results={
            "health_report": {
                "content": [{"type": "text", "text": "degraded"}],
                "structuredContent": {
                    "schema_version": "1",
                    "overall": "degraded",
                    "checks": [
                        {
                            "name": "tcc_accessibility",
                            "status": "fail",
                            "message": "Accessibility is unavailable.",
                            "hint": "Grant Accessibility to the host app.",
                        }
                    ],
                },
                "isError": False,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open"],
    )
    try:
        health = adapter.health()
    finally:
        client.close()

    assert health["ok"] is False
    assert health["status"] == "not_ready"
    assert health["blocking_conditions"] == [
        "cua_health_check_tcc_accessibility_failed"
    ]


def test_provider_status_reuses_short_lived_last_known_health() -> None:
    processes = [
        FakeMcpProcess(
            tools=[_launch_app_tool(), _list_apps_tool(), _health_report_tool()],
            tool_results={
                "health_report": {
                    "content": [{"type": "text", "text": "ready"}],
                    "structuredContent": {
                        "schema_version": "1",
                        "overall": "ok",
                        "checks": [
                            {
                                "name": "tcc_accessibility",
                                "status": "pass",
                                "message": "Accessibility is available.",
                            }
                        ],
                    },
                    "isError": False,
                }
            },
        ),
        FakeMcpProcess(
            tools=[_launch_app_tool(), _list_apps_tool(), _health_report_tool()],
            tool_results={
                "health_report": {
                    "content": [{"type": "text", "text": "ready"}],
                    "structuredContent": {
                        "schema_version": "1",
                        "overall": "ok",
                        "checks": [
                            {
                                "name": "tcc_accessibility",
                                "status": "pass",
                                "message": "Accessibility is available.",
                            }
                        ],
                    },
                    "isError": False,
                }
            },
        ),
    ]
    popen_calls: list[FakeMcpProcess] = []
    manifest_calls: list[list[str]] = []

    def fake_popen(*_args: Any, **_kwargs: Any) -> FakeMcpProcess:
        process = processes.pop(0)
        popen_calls.append(process)
        return process

    def fake_run(command: list[str], **_kwargs: Any) -> _CompletedProcess:
        manifest_calls.append(command)
        return _CompletedProcess(
            stdout=json.dumps(
                {"mcp_invocation": ["/opt/homebrew/bin/cua-driver", "mcp"]}
            )
        )

    def fake_which(name: str) -> str | None:
        return "/opt/homebrew/bin/cua-driver" if name == "cua-driver" else None

    def path_exists(_path: str) -> bool:
        return False

    kwargs = {
        "run": fake_run,
        "which": fake_which,
        "path_exists": path_exists,
        "popen_factory": fake_popen,
    }
    invalidate_cua_background_provider_caches()
    first = cua_background_provider_status({}, probe_health=True, **kwargs)
    second = cua_background_provider_status({}, probe_health=True, **kwargs)
    passive = cua_background_provider_status({}, probe_health=False, **kwargs)

    assert first["available"] is True
    assert second["available"] is True
    assert second["health"]["cached"] is True
    assert passive["available"] is True
    assert passive["health"]["checked"] is True
    assert len(popen_calls) == 1
    assert len(manifest_calls) == 1

    invalidate_cua_background_provider_caches()
    refreshed = cua_background_provider_status({}, probe_health=True, **kwargs)
    assert refreshed["available"] is True
    assert len(popen_calls) == 2
    assert len(manifest_calls) == 2


def test_mcp_initializes_before_listing_tools_and_caches_the_manifest() -> None:
    process = FakeMcpProcess(tools=[_type_text_tool()])
    client = _client_for(process)
    try:
        first = client.list_tools()
        second = client.list_tools()
    finally:
        client.close()

    assert first == [_type_text_tool()]
    assert second == first
    assert [request.get("method") for request in process.requests] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
    ]
    initialize = process.requests[0]
    assert initialize["params"]["protocolVersion"] == "2025-06-18"
    assert "id" not in process.requests[1]


def test_mcp_call_preserves_structured_content() -> None:
    tool_result = {
        "content": [{"type": "text", "text": "typed in background"}],
        "structuredContent": {"ok": True, "typed": True, "window_id": 81},
        "isError": False,
    }
    process = FakeMcpProcess(
        tools=[_type_text_tool()],
        tool_results={"type_text": tool_result},
    )
    client = _client_for(process)
    try:
        result = client.call_tool(
            "type_text",
            {"pid": 9001, "text": "hello", "delivery_mode": "background"},
        )
    finally:
        client.close()

    assert result == tool_result
    call = next(
        request for request in process.requests if request.get("method") == "tools/call"
    )
    assert call["params"] == {
        "name": "type_text",
        "arguments": {
            "pid": 9001,
            "text": "hello",
            "delivery_mode": "background",
        },
    }


def test_mcp_is_error_result_raises_a_tool_error_with_the_original_result() -> None:
    tool_result = {
        "content": [{"type": "text", "text": "target window disappeared"}],
        "structuredContent": {"ok": False, "code": "window_not_found"},
        "isError": True,
    }
    process = FakeMcpProcess(
        tools=[_type_text_tool()],
        tool_results={"type_text": tool_result},
    )
    client = _client_for(process)
    try:
        with pytest.raises(CuaMcpToolError) as raised:
            client.call_tool("type_text", {"pid": 9001, "text": "hello"})
    finally:
        client.close()

    assert raised.value.result == tool_result


def test_mcp_timeout_fails_without_waiting_indefinitely() -> None:
    process = FakeMcpProcess(hang_methods={"initialize"})
    client = _client_for(process, timeout=0.02)
    try:
        with pytest.raises(CuaMcpTimeoutError):
            client.initialize()
    finally:
        client.close()


def test_timeout_discards_late_response_and_next_call_uses_fresh_transport() -> None:
    first = FakeMcpProcess(hang_methods={"initialize"})
    second = FakeMcpProcess()
    processes = [first, second]
    popen_calls: list[FakeMcpProcess] = []

    def fake_popen(*_args: Any, **_kwargs: Any) -> FakeMcpProcess:
        process = processes.pop(0)
        popen_calls.append(process)
        return process

    client = CuaMcpClient(
        command=("never-run-cua-driver", "mcp"),
        timeout=0.02,
        popen_factory=fake_popen,
    )
    try:
        with pytest.raises(CuaMcpTimeoutError):
            client.initialize()
        first.stdout.push_json(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"serverInfo": {"name": "late-old-process"}},
            }
        )
        result = client.initialize()
    finally:
        client.close()

    assert result["serverInfo"]["name"] == "fake-cua-driver"
    assert popen_calls == [first, second]


def test_mcp_process_exit_fails_the_pending_request() -> None:
    process = FakeMcpProcess(exit_methods={"initialize"})
    client = _client_for(process)
    try:
        with pytest.raises(CuaMcpTransportError):
            client.initialize()
    finally:
        client.close()


def test_mcp_process_exit_restarts_transport_for_the_next_request() -> None:
    first = FakeMcpProcess(exit_methods={"initialize"})
    second = FakeMcpProcess()
    processes = [first, second]
    popen_calls: list[FakeMcpProcess] = []

    def fake_popen(*_args: Any, **_kwargs: Any) -> FakeMcpProcess:
        process = processes.pop(0)
        popen_calls.append(process)
        return process

    client = CuaMcpClient(
        command=("never-run-cua-driver", "mcp"),
        timeout=0.25,
        popen_factory=fake_popen,
    )
    try:
        with pytest.raises(CuaMcpTransportError):
            client.initialize()
        result = client.initialize()
    finally:
        client.close()

    assert result["serverInfo"]["name"] == "fake-cua-driver"
    assert popen_calls == [first, second]


def test_mcp_subprocess_environment_disables_telemetry_and_drops_model_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
    ):
        monkeypatch.setenv(key, f"host-{key.lower()}")
    monkeypatch.setenv("CUA_DRIVER_RS_TELEMETRY_ENABLED", "1")
    monkeypatch.setenv("PATH", "/safe/test/bin")
    process = FakeMcpProcess()
    popen_kwargs: dict[str, Any] = {}

    def fake_popen(*_args: Any, **kwargs: Any) -> FakeMcpProcess:
        popen_kwargs.update(kwargs)
        return process

    client = CuaMcpClient(
        command=("never-run-cua-driver", "mcp"),
        environ={
            "CUA_DRIVER_RS_TELEMETRY_ENABLED": "1",
            "OPENAI_API_KEY": "explicit-openai-secret",
            "OHA_YACHIYO_CUA_SESSION_MODE": "background",
        },
        timeout=0.25,
        popen_factory=fake_popen,
    )
    try:
        client.initialize()
    finally:
        client.close()

    child_env = popen_kwargs["env"]
    assert child_env["CUA_DRIVER_RS_TELEMETRY_ENABLED"] == "0"
    assert child_env["PATH"] == "/safe/test/bin"
    assert child_env["OHA_YACHIYO_CUA_SESSION_MODE"] == "background"
    for key in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
    ):
        assert key not in child_env


def test_adapter_forces_mapped_input_delivery_to_background() -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _type_text_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {"ok": True, "pid": 9001},
                "isError": False,
            },
            "type_text": {
                "content": [{"type": "text", "text": "typed"}],
                "structuredContent": {"ok": True, "typed": True},
                "isError": False,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        provider_id="cua-driver",
        supported_tools=["app.open", "desktop.safe_type_text"],
        tool_name_map={"desktop.safe_type_text": "type_text"},
    )
    tool_name = "desktop.safe_type_text"
    try:
        launch_result = adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-explicit-pid"),
            route=_route("app.open"),
            broker=object(),
        )
        result = adapter.execute(
            tool_name,
            {
                "pid": 9001,
                "text": "hello",
                "delivery_mode": "foreground",
            },
            tool_request=_scoped_tool_request(tool_name, "core-explicit-pid"),
            route=_route(tool_name),
            broker=object(),
            approved=True,
        )
    finally:
        client.close()

    assert launch_result["ok"] is True
    assert result["ok"] is True
    assert result["typed"] is True
    assert result["desktop_execution_provider_transport"]["provider_kind"] == (
        CUA_BACKGROUND_PROVIDER_KIND
    )
    call = next(
        request
        for request in process.requests
        if request.get("method") == "tools/call"
        and (request.get("params") or {}).get("name") == "type_text"
    )
    assert call["params"]["name"] == "type_text"
    assert call["params"]["arguments"] == {
        "pid": 9001,
        "text": "hello",
        "delivery_mode": "background",
    }


def test_adapter_does_not_turn_mcp_is_error_into_success() -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _type_text_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {"ok": True, "pid": 9001},
                "isError": False,
            },
            "type_text": {
                "content": [{"type": "text", "text": "window not found"}],
                "structuredContent": {
                    "ok": False,
                    "code": "window_not_found",
                },
                "isError": True,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        provider_id="cua-driver",
        supported_tools=["app.open", "desktop.safe_type_text"],
        tool_name_map={"desktop.safe_type_text": "type_text"},
    )
    tool_name = "desktop.safe_type_text"
    try:
        launch_result = adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-tool-error"),
            route=_route("app.open"),
            broker=object(),
        )
        result = adapter.execute(
            tool_name,
            {"pid": 9001, "text": "hello"},
            tool_request=_scoped_tool_request(tool_name, "core-tool-error"),
            route=_route(tool_name),
            broker=object(),
        )
    finally:
        client.close()

    assert launch_result["ok"] is True
    assert result["ok"] is False
    assert result["status"] in result["blocking_conditions"]
    assert "window" in (result["error"] + result.get("summary", "")).lower()


def test_adapter_fails_closed_when_the_mapped_cua_tool_is_missing() -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _list_apps_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {"ok": True, "pid": 9001},
                "isError": False,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        provider_id="cua-driver",
        supported_tools=["app.open", "desktop.safe_type_text"],
        tool_name_map={"desktop.safe_type_text": "type_text"},
    )
    tool_name = "desktop.safe_type_text"
    try:
        launch_result = adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-missing-tool"),
            route=_route("app.open"),
            broker=object(),
        )
        assert adapter.can_execute(
            tool_name,
            _route(tool_name),
            _tool_request(tool_name),
        ) is False
        result = adapter.execute(
            tool_name,
            {"pid": 9001, "text": "hello"},
            tool_request=_scoped_tool_request(tool_name, "core-missing-tool"),
            route=_route(tool_name),
            broker=object(),
        )
    finally:
        client.close()

    assert launch_result["ok"] is True
    assert result["ok"] is False
    assert result["status"]
    assert result["error"]
    assert result["status"] in result["blocking_conditions"]
    assert not any(
        request.get("method") == "tools/call"
        and (request.get("params") or {}).get("name") == "type_text"
        for request in process.requests
    )


@pytest.mark.parametrize("tool_name", ["desktop.read_ui", "desktop.inspect_app"])
def test_default_adapter_advertises_reads_but_rejects_standalone_driver_state(
    tool_name: str,
) -> None:
    process = FakeMcpProcess(tools=[_get_window_state_tool()])
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(client=client)
    try:
        assert tool_name in adapter.supported_tools
        # get_window_state alone is not enough: the adapter also needs the
        # run-owned launch target and list_apps identity revalidation.
        assert adapter.can_execute(
            tool_name,
            _route(tool_name),
            _tool_request(tool_name),
        ) is False
    finally:
        client.close()


@pytest.mark.parametrize("forbidden_tool", ["foreground", "bring_to_front"])
def test_adapter_never_invokes_explicit_foreground_tools(
    forbidden_tool: str,
) -> None:
    process = FakeMcpProcess(
        tools=[
            _type_text_tool(),
            {"name": "foreground", "inputSchema": {"type": "object"}},
            {"name": "bring_to_front", "inputSchema": {"type": "object"}},
        ]
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        provider_id="cua-driver",
        supported_tools=[forbidden_tool],
        tool_name_map={forbidden_tool: forbidden_tool},
    )
    try:
        assert adapter.can_execute(
            forbidden_tool,
            _route(forbidden_tool),
            _tool_request(forbidden_tool),
        ) is False
        result = adapter.execute(
            forbidden_tool,
            {},
            tool_request=_tool_request(forbidden_tool),
            route=_route(forbidden_tool),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["status"] in result["blocking_conditions"]
    assert not any(
        request.get("method") == "tools/call" for request in process.requests
    )


def test_adapter_never_honors_bring_to_front_payload() -> None:
    process = FakeMcpProcess(tools=[_type_text_tool()])
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        provider_id="cua-driver",
        supported_tools=["desktop.safe_type_text"],
        tool_name_map={"desktop.safe_type_text": "type_text"},
    )
    tool_name = "desktop.safe_type_text"
    try:
        result = adapter.execute(
            tool_name,
            {"pid": 9001, "text": "hello", "bring_to_front": True},
            tool_request=_tool_request(tool_name),
            route=_route(tool_name),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["status"] in result["blocking_conditions"]
    assert not any(
        request.get("method") == "tools/call" for request in process.requests
    )


def test_app_open_maps_app_name_and_sends_only_launch_app_schema_fields() -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _list_apps_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {
                    "ok": True,
                    "pid": 7301,
                    "window_id": 81,
                },
                "isError": False,
            },
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open"],
    )
    try:
        result = adapter.execute(
            "app.open",
            {
                "app_name": "Music",
                "core_id": "payload-must-not-become-scope",
                "delivery_mode": "foreground",
                "wait_for_ready": True,
                "oha_private_field": "must-not-cross-mcp-boundary",
            },
            tool_request=_scoped_tool_request("app.open", "core-music"),
            route=_route("app.open"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is True
    assert [call["params"]["name"] for call in _mcp_tool_calls(process)] == [
        "list_apps",
        "launch_app",
    ]
    assert _mcp_tool_calls(process)[1]["params"] == {
        "name": "launch_app",
        "arguments": {
            "name": "Music",
            "creates_new_application_instance": True,
        },
    }


def test_app_open_uses_bundle_fast_path_when_preflight_proves_target_not_running() -> None:
    launch_tool = _launch_app_tool()
    launch_tool["inputSchema"]["properties"]["bundle_id"] = {"type": "string"}
    process = FakeMcpProcess(
        tools=[launch_tool, _list_apps_tool()],
        tool_results={
            "list_apps": {
                "content": [{"type": "text", "text": "listed"}],
                "structuredContent": {
                    "apps": [
                        {
                            "bundle_id": "com.apple.Music",
                            "name": "Music",
                            "pid": 0,
                            "running": False,
                            "active": False,
                            "launch_path": "/System/Applications/Music.app",
                        }
                    ]
                },
                "isError": False,
            },
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {
                    "ok": True,
                    "pid": 7303,
                    "window_id": 83,
                    "self_activation_suppressed": True,
                },
                "isError": False,
            },
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open"],
    )
    try:
        result = adapter.execute(
            "app.open",
            {"app_name": "Music", "bring_to_front": False},
            tool_request=_scoped_tool_request("app.open", "core-music-fast"),
            route=_route("app.open"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is True
    assert result["agent_owned_target"] is True
    assert result["bundle_id"] == "com.apple.music"
    assert [call["params"]["name"] for call in _mcp_tool_calls(process)] == [
        "list_apps",
        "launch_app",
    ]
    assert _mcp_tool_calls(process)[1]["params"] == {
        "name": "launch_app",
        "arguments": {"bundle_id": "com.apple.music"},
    }


def test_app_open_keeps_forced_isolation_when_target_is_already_running() -> None:
    launch_tool = _launch_app_tool()
    launch_tool["inputSchema"]["properties"]["bundle_id"] = {"type": "string"}
    process = FakeMcpProcess(
        tools=[launch_tool, _list_apps_tool()],
        tool_results={
            "list_apps": _list_apps_identity_result(
                7200,
                name="Music",
                bundle_id="com.apple.Music",
            ),
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {
                    "ok": True,
                    "pid": 7304,
                    "window_id": 84,
                    "self_activation_suppressed": True,
                },
                "isError": False,
            },
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open"],
    )
    try:
        result = adapter.execute(
            "app.open",
            {"app_name": "Music", "bring_to_front": False},
            tool_request=_scoped_tool_request("app.open", "core-music-isolated"),
            route=_route("app.open"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is True
    assert result["agent_owned_target"] is True
    assert _mcp_tool_calls(process)[1]["params"] == {
        "name": "launch_app",
        "arguments": {
            "bundle_id": "com.apple.music",
            "creates_new_application_instance": True,
        },
    }


def test_launch_pid_is_reused_for_background_typing_in_the_same_core() -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _type_text_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {"ok": True, "pid": 7302},
                "isError": False,
            },
            "type_text": {
                "content": [{"type": "text", "text": "typed"}],
                "structuredContent": {"ok": True, "typed": True},
                "isError": False,
            },
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.safe_type_text"],
    )
    try:
        launch_result = adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-compose"),
            route=_route("app.open"),
            broker=object(),
        )
        type_result = adapter.execute(
            "desktop.safe_type_text",
            {"text": "hello from the background"},
            tool_request=_scoped_tool_request(
                "desktop.safe_type_text",
                "core-compose",
            ),
            route=_route("desktop.safe_type_text"),
            broker=object(),
        )
    finally:
        client.close()

    assert launch_result["ok"] is True
    assert type_result["ok"] is True
    calls = _mcp_tool_calls(process)
    type_call = next(call for call in calls if call["params"]["name"] == "type_text")
    assert type_call["params"] == {
        "name": "type_text",
        "arguments": {
            "pid": 7302,
            "text": "hello from the background",
            "delivery_mode": "background",
        },
    }


def test_launch_pid_is_never_reused_across_core_scopes() -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _type_text_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {"ok": True, "pid": 7303},
                "isError": False,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.safe_type_text"],
    )
    try:
        adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-owner"),
            route=_route("app.open"),
            broker=object(),
        )
        result = adapter.execute(
            "desktop.safe_type_text",
            {"text": "must not reach the other core's window"},
            tool_request=_scoped_tool_request(
                "desktop.safe_type_text",
                "core-other",
            ),
            route=_route("desktop.safe_type_text"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["status"] == "provider_target_unavailable"
    assert result["error"] == "cua_background_target_required"
    assert result["blocking_condition"] == "desktop_background_target_required"
    assert [call["params"]["name"] for call in _mcp_tool_calls(process)] == [
        "list_apps",
        "launch_app"
    ]


def test_background_input_rejects_payload_scope_when_tool_request_has_no_scope() -> None:
    process = FakeMcpProcess(tools=[_type_text_tool()])
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["desktop.safe_type_text"],
    )
    try:
        result = adapter.execute(
            "desktop.safe_type_text",
            {
                "core_id": "model-supplied-scope-is-not-trusted",
                "pid": 7304,
                "text": "do not type",
            },
            tool_request=_tool_request("desktop.safe_type_text"),
            route=_route("desktop.safe_type_text"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["status"] == "provider_target_unavailable"
    assert result["error"] == "cua_task_scope_required"
    assert result["blocking_condition"] == "desktop_background_target_required"
    assert _mcp_tool_calls(process) == []


def test_background_input_fails_closed_when_scope_has_no_target_pid() -> None:
    process = FakeMcpProcess(tools=[_type_text_tool()])
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["desktop.safe_type_text"],
    )
    try:
        result = adapter.execute(
            "desktop.safe_type_text",
            {"text": "do not type"},
            tool_request=_scoped_tool_request(
                "desktop.safe_type_text",
                "core-without-target",
            ),
            route=_route("desktop.safe_type_text"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["status"] == "provider_target_unavailable"
    assert result["error"] == "cua_background_target_required"
    assert result["blocking_condition"] == "desktop_background_target_required"
    assert _mcp_tool_calls(process) == []


def test_background_input_cannot_bootstrap_a_target_from_payload_pid() -> None:
    process = FakeMcpProcess(tools=[_type_text_tool()])
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["desktop.safe_type_text"],
    )
    try:
        result = adapter.execute(
            "desktop.safe_type_text",
            {"pid": 9911, "text": "do not type into an arbitrary process"},
            tool_request=_scoped_tool_request(
                "desktop.safe_type_text",
                "core-with-untrusted-pid",
            ),
            route=_route("desktop.safe_type_text"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["status"] == "provider_target_unavailable"
    assert result["error"] == "cua_background_target_required"
    assert result["blocking_condition"] == "desktop_background_target_required"
    assert _mcp_tool_calls(process) == []


def test_list_apps_drops_query_trace_and_delivery_fields_not_in_cua_schema() -> None:
    process = FakeMcpProcess(tools=[_list_apps_tool()])
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["desktop.list_apps"],
    )
    try:
        result = adapter.execute(
            "desktop.list_apps",
            {
                "query": "Music",
                "limit": 20,
                "core_id": "payload-trace",
                "delivery_mode": "foreground",
                "oha_private_field": {"must": "stay local"},
            },
            tool_request=_scoped_tool_request("desktop.list_apps", "core-discover"),
            route=_route("desktop.list_apps"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is True
    assert _mcp_tool_calls(process)[0]["params"] == {
        "name": "list_apps",
        "arguments": {},
    }


def test_list_apps_filters_and_limits_cua_results_locally() -> None:
    process = FakeMcpProcess(
        tools=[_list_apps_tool()],
        tool_results={
            "list_apps": {
                "content": [{"type": "text", "text": "listed"}],
                "structuredContent": {
                    "apps": [
                        {
                            "name": "Calculator",
                            "bundle_id": "com.apple.calculator",
                            "path": "/Applications/Calculator.app",
                        },
                        {
                            "name": "Apple Music",
                            "bundle_id": "com.apple.Music",
                            "path": "/Applications/Music.app",
                            "pid": 401,
                            "running": True,
                        },
                        {
                            "name": "MusicBox",
                            "bundle_id": "com.example.musicbox",
                            "path": "/Applications/MusicBox.app",
                        },
                    ]
                },
                "isError": False,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["desktop.list_apps"],
    )
    try:
        result = adapter.execute(
            "desktop.list_apps",
            {"query": "Music", "limit": 1},
            tool_request=_scoped_tool_request(
                "desktop.list_apps",
                "core-filter-apps",
            ),
            route=_route("desktop.list_apps"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is True
    assert result["data"]["count"] == 1
    assert result["data"]["total_count"] == 2
    assert result["data"]["truncated"] is True
    assert [app["name"] for app in result["data"]["apps"]] == ["Apple Music"]
    assert result["data"]["best_match"]["name"] == "Apple Music"
    assert result["desktop_execution_provider_evidence"] == {
        "mcp_tool": "list_apps",
        "unfiltered_count": 3,
        "filtered_locally": True,
    }


def test_new_launch_pid_is_agent_owned_and_can_receive_background_input() -> None:
    target_pid = 7304
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _type_text_tool(), _list_apps_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "name": "TextEdit",
                    "bundle_id": "com.apple.TextEdit",
                },
                "isError": False,
            }
        },
        tool_result_sequences={
            "list_apps": [
                _list_apps_identity_result(
                    7000,
                    name="TextEdit",
                    bundle_id="com.apple.TextEdit",
                ),
                _list_apps_identity_result(
                    target_pid,
                    name="TextEdit",
                    bundle_id="com.apple.TextEdit",
                ),
            ]
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.safe_type_text"],
    )
    try:
        launch_result = adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-owned-target"),
            route=_route("app.open"),
            broker=object(),
        )
        input_result = adapter.execute(
            "desktop.safe_type_text",
            {"text": "agent-only text"},
            tool_request=_scoped_tool_request(
                "desktop.safe_type_text",
                "core-owned-target",
            ),
            route=_route("desktop.safe_type_text"),
            broker=object(),
        )
    finally:
        client.close()

    assert launch_result["agent_owned_target"] is True
    assert input_result["ok"] is True
    assert [call["params"]["name"] for call in _mcp_tool_calls(process)] == [
        "list_apps",
        "launch_app",
        "list_apps",
        "type_text",
    ]


def test_launch_placeholder_identity_uses_canonical_preflight_bundle_for_localized_observation(
) -> None:
    target_pid = 73041
    target_window_id = 3041
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _list_apps_tool(), _get_window_state_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "window_id": target_window_id,
                    "name": "?",
                    "bundle_id": "?",
                    "self_activation_suppressed": True,
                },
                "isError": False,
            },
            "get_window_state": {
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "window_id": target_window_id,
                    "app_name": "文本编辑",
                    "title": "未命名",
                    "elements": [
                        {
                            "role": "AXTextArea",
                            "label": "First Text View",
                            "element_index": 1,
                        }
                    ],
                },
                "isError": False,
            },
        },
        tool_result_sequences={
            "list_apps": [
                {
                    "structuredContent": {
                        "apps": [
                            {
                                "pid": 0,
                                "running": False,
                                "name": "TextEdit",
                                "bundle_id": "com.apple.TextEdit",
                                "launch_path": "/System/Applications/TextEdit.app",
                            }
                        ]
                    },
                    "isError": False,
                },
                _list_apps_identity_result(
                    target_pid,
                    name="文本编辑",
                    bundle_id="com.apple.TextEdit",
                ),
            ]
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.ui_elements"],
    )
    scope = "core-placeholder-localized-identity"
    try:
        launch_result = adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", scope),
            route=_route("app.open"),
            broker=object(),
        )
        observe_result = adapter.execute(
            "desktop.ui_elements",
            {"app_name": "TextEdit", "role_filter": "text"},
            tool_request=_scoped_tool_request("desktop.ui_elements", scope),
            route=_route("desktop.ui_elements"),
            broker=object(),
        )
    finally:
        client.close()

    assert launch_result["ok"] is True
    assert launch_result["agent_owned_target"] is True
    assert observe_result["ok"] is True
    assert observe_result["target_bound"] is True
    assert observe_result["data"]["pid"] == target_pid
    assert observe_result["data"]["window_id"] == target_window_id
    assert [call["params"]["name"] for call in _mcp_tool_calls(process)] == [
        "list_apps",
        "launch_app",
        "list_apps",
        "get_window_state",
    ]


def test_reused_preexisting_pid_is_never_a_writable_background_target() -> None:
    shared_pid = 7305
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _type_text_tool(), _list_apps_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "reused running app"}],
                "structuredContent": {
                    "ok": True,
                    "pid": shared_pid,
                    "name": "TextEdit",
                    "bundle_id": "com.apple.TextEdit",
                },
                "isError": False,
            }
        },
        tool_result_sequences={
            "list_apps": [
                _list_apps_identity_result(
                    shared_pid,
                    name="TextEdit",
                    bundle_id="com.apple.TextEdit",
                )
            ]
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.safe_type_text"],
    )
    try:
        launch_result = adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-shared-target"),
            route=_route("app.open"),
            broker=object(),
        )
        input_result = adapter.execute(
            "desktop.safe_type_text",
            {"text": "must not touch user window"},
            tool_request=_scoped_tool_request(
                "desktop.safe_type_text",
                "core-shared-target",
            ),
            route=_route("desktop.safe_type_text"),
            broker=object(),
        )
    finally:
        client.close()

    assert launch_result["ok"] is False
    assert launch_result["agent_owned_target"] is False
    assert launch_result["error"] == "cua_background_target_not_agent_owned"
    assert launch_result["requires_user_handoff"] is True
    assert input_result["ok"] is False
    assert input_result["error"] in {
        "cua_background_target_not_agent_owned",
        "cua_background_target_required",
    }
    assert input_result["requires_user_handoff"] is True
    assert [call["params"]["name"] for call in _mcp_tool_calls(process)] == [
        "list_apps",
        "launch_app",
    ]


def test_malformed_launch_baseline_never_proves_agent_ownership() -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _type_text_tool(), _list_apps_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {
                    "ok": True,
                    "pid": 7308,
                    "name": "TextEdit",
                    "bundle_id": "com.apple.TextEdit",
                },
                "isError": False,
            }
        },
        tool_result_sequences={
            "list_apps": [
                {
                    "content": [{"type": "text", "text": "not-json"}],
                    "structuredContent": {"ok": True},
                    "isError": False,
                }
            ]
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.safe_type_text"],
    )
    try:
        launch_result = adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-malformed-baseline"),
            route=_route("app.open"),
            broker=object(),
        )
        input_result = adapter.execute(
            "desktop.safe_type_text",
            {"text": "must not touch an unproven target"},
            tool_request=_scoped_tool_request(
                "desktop.safe_type_text",
                "core-malformed-baseline",
            ),
            route=_route("desktop.safe_type_text"),
            broker=object(),
        )
    finally:
        client.close()

    assert launch_result["ok"] is False
    assert launch_result["agent_owned_target"] is False
    assert launch_result["error"] == "cua_background_target_not_agent_owned"
    assert launch_result["requires_user_handoff"] is True
    assert input_result["ok"] is False
    assert input_result["error"] in {
        "cua_background_target_not_agent_owned",
        "cua_background_target_required",
    }
    assert [call["params"]["name"] for call in _mcp_tool_calls(process)] == [
        "list_apps",
        "launch_app",
    ]


def test_background_launch_requires_explicit_activation_suppression_evidence() -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _list_apps_tool()],
        tool_results={
            "launch_app": {
                "structuredContent": {
                    "ok": True,
                    "pid": 7318,
                    "window_id": 108,
                    "name": "TextEdit",
                    "bundle_id": "com.apple.TextEdit",
                    "self_activation_suppressed": None,
                },
                "isError": False,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open"],
    )
    try:
        result = adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-unverified-launch"),
            route=_route("app.open"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["error"] == "cua_launch_background_delivery_unverified"
    assert result["agent_owned_target"] is True
    assert result["self_activation_suppressed"] is None
    assert result["requires_user_handoff"] is True


def test_background_launch_preflights_identity_dependency_before_dispatch() -> None:
    process = FakeMcpProcess(tools=[_launch_app_tool()])
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open"],
    )
    try:
        assert adapter.can_execute(
            "app.open",
            _route("app.open"),
            _tool_request("app.open"),
        ) is False
        result = adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-no-list-apps"),
            route=_route("app.open"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["error"] == "cua_mcp_tool_dependency_unavailable"
    assert _mcp_tool_calls(process) == []


@pytest.mark.parametrize(
    (
        "composite_tool",
        "remote_tool",
        "payload",
        "expected_action_name",
        "expected_action_arguments",
        "expected_action_calls",
    ),
    [
        (
            "app.open_and_safe_type_text",
            _type_text_tool(),
            {"app_name": "TextEdit", "text": "hello"},
            "type_text",
            {"pid": 7306, "text": "hello", "delivery_mode": "background"},
            1,
        ),
        (
            "app.open_and_safe_shortcut",
            _background_input_tool("hotkey", "keys"),
            {"app_name": "TextEdit", "action": "copy"},
            "hotkey",
            {
                "pid": 7306,
                "keys": ["cmd", "c"],
                "delivery_mode": "background",
            },
            1,
        ),
        (
            "app.open_and_safe_key",
            _background_input_tool("press_key", "key"),
            {
                "app_name": "TextEdit",
                "action": "arrow_down",
                "repeat_count": 2,
            },
            "press_key",
            {"pid": 7306, "key": "down", "delivery_mode": "background"},
            2,
        ),
        (
            "app.open_and_safe_scroll",
            _scroll_tool(),
            {"app_name": "TextEdit", "direction": "down", "pages": 2},
            "scroll",
            {
                "pid": 7306,
                "direction": "down",
                "amount": 2,
                "by": "page",
                "delivery_mode": "background",
            },
            1,
        ),
    ],
)
def test_open_composites_launch_an_owned_target_then_use_background_input(
    composite_tool: str,
    remote_tool: dict[str, Any],
    payload: dict[str, Any],
    expected_action_name: str,
    expected_action_arguments: dict[str, Any],
    expected_action_calls: int,
) -> None:
    tools = [_launch_app_tool(), remote_tool]
    if expected_action_name in {"hotkey", "press_key", "scroll"}:
        tools.append(_get_window_state_tool())
    process = FakeMcpProcess(
        tools=tools,
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {
                    "ok": True,
                    "pid": 7306,
                    "window_id": 61,
                    "name": "TextEdit",
                    "bundle_id": "com.apple.TextEdit",
                },
                "isError": False,
            },
            expected_action_name: {
                "content": [{"type": "text", "text": "dispatched"}],
                "structuredContent": {"ok": True, "verified": True},
                "isError": False,
            },
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(client=client)
    try:
        assert adapter.can_execute(
            composite_tool,
            _route(composite_tool),
            _tool_request(composite_tool),
        ) is True
        result = adapter.execute(
            composite_tool,
            payload,
            tool_request=_scoped_tool_request(
                composite_tool,
                f"core-{expected_action_name}",
            ),
            route=_route(composite_tool),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is True
    assert result["tool"] == composite_tool
    assert result["action"] == composite_tool
    assert [step["tool"] for step in result["composite_steps"]] == [
        "app.open",
        {
            "type_text": "desktop.safe_type_text",
            "hotkey": "desktop.safe_shortcut",
            "press_key": "desktop.safe_key",
            "scroll": "desktop.safe_scroll",
        }[expected_action_name],
    ]
    action_calls = [
        call
        for call in _mcp_tool_calls(process)
        if call["params"]["name"] == expected_action_name
    ]
    assert len(action_calls) == expected_action_calls
    assert all(
        call["params"]["arguments"] == expected_action_arguments
        for call in action_calls
    )


def test_open_composite_stops_when_launch_takes_the_user_foreground() -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _type_text_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "foreground launch"}],
                "structuredContent": {
                    "ok": True,
                    "pid": 7307,
                    "name": "TextEdit",
                    "self_activation_suppressed": False,
                },
                "isError": False,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(client=client)
    tool_name = "app.open_and_safe_type_text"
    try:
        result = adapter.execute(
            tool_name,
            {"app_name": "TextEdit", "text": "must not type"},
            tool_request=_scoped_tool_request(tool_name, "core-composite-takeover"),
            route=_route(tool_name),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["error"] == "cua_launch_foreground_takeover_detected"
    assert result["failed_step"] == "app.open"
    assert [call["params"]["name"] for call in _mcp_tool_calls(process)] == [
        "list_apps",
        "launch_app",
    ]


def test_open_composite_preflights_every_dependency_before_launch() -> None:
    process = FakeMcpProcess(tools=[_launch_app_tool()])
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(client=client)
    tool_name = "app.open_and_safe_type_text"
    try:
        result = adapter.execute(
            tool_name,
            {"app_name": "TextEdit", "text": "must not partially run"},
            tool_request=_scoped_tool_request(
                tool_name,
                "core-composite-preflight",
            ),
            route=_route(tool_name),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["status"] == "provider_tool_unavailable"
    assert _mcp_tool_calls(process) == []


@pytest.mark.parametrize(
    ("tool_name", "cua_tool_name", "remote_tool", "payload", "expected"),
    [
        (
            "desktop.safe_shortcut",
            "hotkey",
            _background_input_tool("hotkey", "keys"),
            {"action": "copy"},
            {
                "pid": 7305,
                "keys": ["cmd", "c"],
                "delivery_mode": "background",
            },
        ),
        (
            "desktop.safe_key",
            "press_key",
            _background_input_tool("press_key", "key"),
            {"action": "arrow_down"},
            {
                "pid": 7306,
                "key": "down",
                "delivery_mode": "background",
            },
        ),
    ],
)
def test_safe_shortcut_and_key_force_cua_background_delivery(
    tool_name: str,
    cua_tool_name: str,
    remote_tool: dict[str, Any],
    payload: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    target_pid = int(expected["pid"])
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), remote_tool, _get_window_state_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {"ok": True, "pid": target_pid},
                "isError": False,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", tool_name],
    )
    try:
        launch_result = adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-input"),
            route=_route("app.open"),
            broker=object(),
        )
        result = adapter.execute(
            tool_name,
            payload,
            tool_request=_scoped_tool_request(tool_name, "core-input"),
            route=_route(tool_name),
            broker=object(),
        )
    finally:
        client.close()

    assert launch_result["ok"] is True
    assert result["ok"] is True
    action_call = next(
        call
        for call in _mcp_tool_calls(process)
        if call["params"]["name"] == cua_tool_name
    )
    assert action_call["params"] == {
        "name": cua_tool_name,
        "arguments": expected,
    }


def test_launch_windows_result_targets_the_first_valid_window_for_read_ui() -> None:
    target_pid = 7310
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _get_window_state_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "windows": [
                        {"pid": target_pid, "window_id": 0},
                        {"pid": 9999, "window_id": 90},
                        {
                            "pid": target_pid,
                            "window_id": 190,
                            "title": "",
                            "is_on_screen": False,
                            "layer": 0,
                            "bounds": {"width": 1920, "height": 30},
                        },
                        {"pid": target_pid, "window_id": 91},
                    ],
                },
                "isError": False,
            },
            "get_window_state": {
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "window_id": 91,
                    "title": "TextEdit",
                    "elements": [],
                },
                "isError": False,
            },
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.read_ui"],
        tool_name_map={"desktop.read_ui": "get_window_state"},
    )
    try:
        launch_result = adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-window-read"),
            route=_route("app.open"),
            broker=object(),
        )
        read_result = adapter.execute(
            "desktop.read_ui",
            {},
            tool_request=_scoped_tool_request(
                "desktop.read_ui",
                "core-window-read",
            ),
            route=_route("desktop.read_ui"),
            broker=object(),
        )
    finally:
        client.close()

    assert launch_result["ok"] is True
    assert read_result["ok"] is True
    read_call = next(
        call
        for call in _mcp_tool_calls(process)
        if call["params"]["name"] == "get_window_state"
    )
    assert read_call["params"] == {
        "name": "get_window_state",
        "arguments": {"pid": target_pid, "window_id": 91},
    }


def test_pid_only_launch_rebinds_eventual_window_for_inspect_app() -> None:
    target_pid = 73103
    target_window_id = 913
    process = FakeMcpProcess(
        tools=[
            _launch_app_tool(),
            _list_apps_tool(),
            _list_windows_tool(),
            _get_window_state_tool(),
        ],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "name": "PixelForge",
                    "bundle_id": "com.example.PixelForge",
                    "windows": [],
                    "self_activation_suppressed": True,
                },
                "isError": False,
            },
            "get_window_state": {
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "window_id": target_window_id,
                    "app_name": "PixelForge",
                    "title": "Draft 1",
                    "elements": [],
                },
                "isError": False,
            },
        },
        tool_result_sequences={
            "list_apps": [
                {
                    "structuredContent": {"apps": []},
                    "isError": False,
                },
                {
                    "structuredContent": {
                        "apps": [
                            {
                                "pid": target_pid,
                                "running": True,
                                "name": "PixelForge",
                                "bundle_id": "com.example.PixelForge",
                            }
                        ]
                    },
                    "isError": False,
                },
            ],
            "list_windows": [
                {
                    "structuredContent": {
                        "windows": [
                            {
                                "pid": target_pid,
                                "window_id": 912,
                                "title": "",
                                "is_on_screen": False,
                                "layer": 0,
                                "bounds": {"width": 1920, "height": 30},
                            }
                        ]
                    },
                    "isError": False,
                },
                {
                    "structuredContent": {
                        "windows": [
                            {
                                "pid": target_pid,
                                "window_id": 912,
                                "title": "",
                                "is_on_screen": False,
                                "layer": 0,
                                "bounds": {"width": 1920, "height": 30},
                            },
                            {
                                "pid": target_pid,
                                "window_id": target_window_id,
                                "app_name": "PixelForge",
                                "title": "Draft 1",
                                "is_on_screen": False,
                            }
                        ]
                    },
                    "isError": False,
                },
            ],
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.inspect_app"],
    )
    scope = "core-pid-only-inspect-app"
    try:
        launch_result = adapter.execute(
            "app.open",
            {"app_name": "PixelForge"},
            tool_request=_scoped_tool_request("app.open", scope),
            route=_route("app.open"),
            broker=object(),
        )
        inspect_result = adapter.execute(
            "desktop.inspect_app",
            {},
            tool_request=_scoped_tool_request("desktop.inspect_app", scope),
            route=_route("desktop.inspect_app"),
            broker=object(),
        )
    finally:
        client.close()

    assert launch_result["ok"] is True
    assert launch_result["pid"] == target_pid
    assert launch_result["window_id"] == target_window_id
    assert launch_result["agent_owned_target"] is True
    assert launch_result["self_activation_suppressed"] is True
    assert inspect_result["ok"] is True
    assert inspect_result["agent_owned_target"] is True
    assert inspect_result["target_bound"] is True
    assert inspect_result["data"]["pid"] == target_pid
    assert inspect_result["data"]["window_id"] == target_window_id
    inspect_call = next(
        call
        for call in _mcp_tool_calls(process)
        if call["params"]["name"] == "get_window_state"
    )
    assert inspect_call["params"] == {
        "name": "get_window_state",
        "arguments": {"pid": target_pid, "window_id": target_window_id},
    }
    window_calls = [
        call
        for call in _mcp_tool_calls(process)
        if call["params"]["name"] == "list_windows"
    ]
    assert len(window_calls) == 2
    assert all(
        call["params"]["arguments"].get("pid") == target_pid
        and call["params"]["arguments"].get("on_screen_only") is not True
        for call in window_calls
    )


def test_pid_only_launch_fails_closed_when_eventual_window_is_ambiguous() -> None:
    target_pid = 73104
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _list_apps_tool(), _list_windows_tool()],
        tool_results={
            "launch_app": {
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "name": "PixelForge",
                    "bundle_id": "com.example.PixelForge",
                    "windows": [],
                    "self_activation_suppressed": True,
                },
                "isError": False,
            },
            "list_windows": {
                "structuredContent": {
                    "windows": [
                        {
                            "pid": target_pid,
                            "window_id": 913,
                            "title": "",
                            "is_on_screen": False,
                            "layer": 0,
                            "bounds": {"width": 1920, "height": 30},
                        },
                        {"pid": target_pid, "window_id": 914},
                        {"pid": target_pid, "window_id": 915},
                        {"pid": 99999, "window_id": 916},
                    ]
                },
                "isError": False,
            },
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(client=client)
    try:
        result = adapter.execute(
            "app.open",
            {"app_name": "PixelForge"},
            tool_request=_scoped_tool_request("app.open", "core-ambiguous-window"),
            route=_route("app.open"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["error"] == "cua_background_window_target_ambiguous"
    assert result["blocking_condition"] == "desktop_background_target_required"
    assert result["match_count"] == 2
    assert result["rejected_window_counts"] == {"empty_offscreen_strip": 1}
    assert result["agent_owned_target"] is True


def test_window_resolution_ax_vets_menu_bar_only_pseudo_window() -> None:
    target_pid = 731041
    menu_window_id = 21238
    content_window_id = 21239
    process = FakeMcpProcess(
        tools=[
            _launch_app_tool(),
            _list_apps_tool(),
            _list_windows_tool(),
            _get_window_state_tool(),
        ],
        tool_results={
            "launch_app": {
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "name": "TextEdit",
                    "windows": [
                        {"pid": target_pid, "window_id": menu_window_id},
                        {"pid": target_pid, "window_id": content_window_id},
                    ],
                    "self_activation_suppressed": True,
                },
                "isError": False,
            },
            "list_windows": {
                "structuredContent": {
                    "windows": [
                        {
                            "pid": target_pid,
                            "window_id": menu_window_id,
                            "title": "",
                            "is_on_screen": False,
                            "bounds": {"width": 500, "height": 500},
                        },
                        {
                            "pid": target_pid,
                            "window_id": content_window_id,
                            "title": "Untitled",
                            "is_on_screen": True,
                            "bounds": {"width": 586, "height": 488},
                        },
                    ]
                },
                "isError": False,
            },
        },
        tool_result_sequences={
            "list_apps": [
                {"structuredContent": {"apps": []}, "isError": False},
                {
                    "structuredContent": {
                        "apps": [
                            {"pid": target_pid, "running": True, "name": "TextEdit"}
                        ]
                    },
                    "isError": False,
                },
            ],
            "get_window_state": [
                {
                    "structuredContent": {
                        "ok": True,
                        "pid": target_pid,
                        "window_id": menu_window_id,
                        "roots": [{"role": "AXMenuBar"}],
                    },
                    "isError": False,
                },
                {
                    "structuredContent": {
                        "ok": True,
                        "pid": target_pid,
                        "window_id": content_window_id,
                        "roots": [
                            {
                                "role": "AXWindow",
                                "children": [{"role": "AXTextArea"}],
                            }
                        ],
                    },
                    "isError": False,
                },
            ],
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(client=client)
    try:
        result = adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-ax-vetting"),
            route=_route("app.open"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is True
    assert result["window_id"] == content_window_id
    snapshot_calls = [
        call
        for call in _mcp_tool_calls(process)
        if call["params"]["name"] == "get_window_state"
    ]
    assert [call["params"]["arguments"]["window_id"] for call in snapshot_calls] == [
        menu_window_id,
        content_window_id,
    ]


def test_window_resolution_fails_closed_for_multiple_ax_content_windows() -> None:
    target_pid = 731042
    process = FakeMcpProcess(
        tools=[
            _launch_app_tool(),
            _list_apps_tool(),
            _list_windows_tool(),
            _get_window_state_tool(),
        ],
        tool_results={
            "launch_app": {
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "name": "TextEdit",
                    "windows": [],
                    "self_activation_suppressed": True,
                },
                "isError": False,
            },
            "list_windows": {
                "structuredContent": {
                    "windows": [
                        {"pid": target_pid, "window_id": 21240},
                        {"pid": target_pid, "window_id": 21241},
                    ]
                },
                "isError": False,
            },
        },
        tool_result_sequences={
            "list_apps": [
                {"structuredContent": {"apps": []}, "isError": False},
                {
                    "structuredContent": {
                        "apps": [
                            {"pid": target_pid, "running": True, "name": "TextEdit"}
                        ]
                    },
                    "isError": False,
                },
            ],
            "get_window_state": [
                {
                    "structuredContent": {
                        "ok": True,
                        "pid": target_pid,
                        "window_id": 21240,
                        "roots": [{"role": "AXWindow"}],
                    },
                    "isError": False,
                },
                {
                    "structuredContent": {
                        "ok": True,
                        "pid": target_pid,
                        "window_id": 21241,
                        "roots": [{"role": "AXWindow"}],
                    },
                    "isError": False,
                },
            ],
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(client=client)
    try:
        result = adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-ax-ambiguous"),
            route=_route("app.open"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["error"] == "cua_background_window_target_ambiguous"
    assert result["match_count"] == 2
    assert result["ax_window_evidence_counts"] == {"content": 2}


def test_pid_only_launch_fails_retryably_when_window_never_appears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cua_background_provider_module,
        "_TASK_TARGET_WINDOW_RESOLUTION_TIMEOUT_SECONDS",
        0.0,
    )
    target_pid = 73105
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _list_apps_tool(), _list_windows_tool()],
        tool_results={
            "launch_app": {
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "name": "PixelForge",
                    "bundle_id": "com.example.PixelForge",
                    "windows": [],
                    "self_activation_suppressed": True,
                },
                "isError": False,
            },
            "list_windows": {
                "structuredContent": {
                    "windows": [
                        {
                            "pid": target_pid,
                            "window_id": 917,
                            "title": "",
                            "is_on_screen": False,
                            "layer": 0,
                            "bounds": {"width": 1920, "height": 30},
                        }
                    ]
                },
                "isError": False,
            },
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(client=client)
    try:
        result = adapter.execute(
            "app.open",
            {"app_name": "PixelForge"},
            tool_request=_scoped_tool_request("app.open", "core-window-not-ready"),
            route=_route("app.open"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["error"] == "cua_background_window_not_ready"
    assert result["blocking_condition"] == "desktop_background_target_required"
    assert result["retryable"] is True
    assert result["agent_owned_target"] is True
    assert result["pid"] == target_pid
    assert result["rejected_window_counts"] == {"empty_offscreen_strip": 1}


def test_window_not_ready_launch_keeps_owned_pid_for_bounded_new_document_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cua_background_provider_module,
        "_TASK_TARGET_WINDOW_RESOLUTION_TIMEOUT_SECONDS",
        0.0,
    )
    target_pid = 73106
    target_window_id = 918
    process = FakeMcpProcess(
        tools=[
            _launch_app_tool(),
            _list_apps_tool(),
            _list_windows_tool(),
            _background_input_tool("hotkey", "keys"),
            _get_window_state_tool(),
        ],
        tool_results={
            "launch_app": {
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "name": "Sketchpad",
                    "bundle_id": "com.example.Sketchpad",
                    "windows": [],
                    "self_activation_suppressed": True,
                },
                "isError": False,
            },
            "hotkey": {
                "structuredContent": {
                    "ok": True,
                    "effect": "unverifiable",
                    "verified": False,
                },
                "isError": False,
            },
            "get_window_state": {
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "window_id": target_window_id,
                    "title": "Untitled",
                    "elements": [{"role": "AXTextArea", "value": ""}],
                },
                "isError": False,
            },
        },
        tool_result_sequences={
            "list_windows": [
                {
                    "structuredContent": {
                        "windows": [
                            {
                                "pid": target_pid,
                                "window_id": 917,
                                "title": "",
                                "is_on_screen": False,
                                "layer": 0,
                                "bounds": {"width": 1920, "height": 30},
                            }
                        ]
                    },
                    "isError": False,
                },
                {
                    "structuredContent": {
                        "windows": [
                            {
                                "pid": target_pid,
                                "window_id": target_window_id,
                                "title": "Untitled",
                                "is_on_screen": True,
                                "layer": 0,
                                "bounds": {"width": 900, "height": 650},
                            }
                        ]
                    },
                    "isError": False,
                },
            ]
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.safe_shortcut", "desktop.read_ui"],
    )
    scope = "core-window-materialization-recovery"
    try:
        launch_result = adapter.execute(
            "app.open",
            {"app_name": "Sketchpad"},
            tool_request=_scoped_tool_request("app.open", scope),
            route=_route("app.open"),
            broker=object(),
        )
        shortcut_result = adapter.execute(
            "desktop.safe_shortcut",
            {"action": "new_document"},
            tool_request=_scoped_tool_request("desktop.safe_shortcut", scope),
            route=_route("desktop.safe_shortcut"),
            broker=object(),
        )
        observe_result = adapter.execute(
            "desktop.read_ui",
            {},
            tool_request=_scoped_tool_request("desktop.read_ui", scope),
            route=_route("desktop.read_ui"),
            broker=object(),
        )
    finally:
        client.close()

    assert launch_result["ok"] is False
    assert launch_result["error"] == "cua_background_window_not_ready"
    assert launch_result["agent_owned_target"] is True
    assert launch_result["pid"] == target_pid
    assert shortcut_result["ok"] is True, shortcut_result
    assert observe_result["ok"] is True, observe_result
    assert observe_result["target_bound"] is True
    assert observe_result["data"]["pid"] == target_pid
    assert observe_result["data"]["window_id"] == target_window_id
    assert [call["params"]["name"] for call in _mcp_tool_calls(process)] == [
        "list_apps",
        "launch_app",
        "list_windows",
        "list_apps",
        "hotkey",
        "list_apps",
        "list_windows",
        "get_window_state",
    ]
    hotkey_call = next(
        call
        for call in _mcp_tool_calls(process)
        if call["params"]["name"] == "hotkey"
    )
    assert hotkey_call["params"]["arguments"] == {
        "pid": target_pid,
        "keys": ["cmd", "n"],
        "delivery_mode": "background",
    }
    read_call = _mcp_tool_calls(process)[-1]
    assert read_call["params"]["arguments"] == {
        "pid": target_pid,
        "window_id": target_window_id,
    }


def test_launch_tool_error_sticky_pins_scope_without_caching_target() -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _list_apps_tool(), _get_window_state_tool()],
        tool_results={
            "launch_app": {
                "content": [
                    {
                        "type": "text",
                        "text": "launch may have completed before the receipt failed",
                    }
                ],
                "isError": True,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(client=client)
    scope = "core-ambiguous-launch-receipt"
    launch_request = _scoped_tool_request("app.open", scope)
    try:
        launch_result = adapter.execute(
            "app.open",
            {"app_name": "Notes"},
            tool_request=launch_request,
            route=_route("app.open"),
            broker=object(),
        )
        owns_scope = adapter.owns_task_scope(launch_request)
        observation_result = adapter.execute(
            "desktop.read_ui",
            {},
            tool_request=_scoped_tool_request("desktop.read_ui", scope),
            route=_route("desktop.read_ui"),
            broker=object(),
        )
    finally:
        client.close()

    assert launch_result["ok"] is False
    assert launch_result["error"] == "cua_mcp_tool_error"
    assert owns_scope is True
    assert observation_result["ok"] is False
    assert observation_result["error"] == "cua_background_target_required"
    assert not any(
        call["params"]["name"] == "get_window_state"
        for call in _mcp_tool_calls(process)
    )


@pytest.mark.parametrize(
    ("tool_name", "expected_collection"),
    [
        ("desktop.active_window", ""),
        ("desktop.windows", "windows"),
        ("desktop.list_windows", "windows"),
        ("desktop.ui_elements", "elements"),
        ("desktop.read_ui", "elements"),
        ("desktop.inspect_app", "windows"),
        ("desktop.verify", ""),
    ],
)
def test_default_readonly_tools_observe_only_the_run_owned_background_window(
    tool_name: str,
    expected_collection: str,
) -> None:
    target_pid = 73101
    target_window_id = 191
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _get_window_state_tool()],
        tool_results={
            "launch_app": {
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "window_id": target_window_id,
                    "name": "Notes",
                    "bundle_id": "com.apple.Notes",
                },
                "isError": False,
            },
            "get_window_state": {
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "window_id": target_window_id,
                    "app_name": "Notes",
                    "title": "Agent Draft",
                    "elements": [
                        {"role": "AXTextArea", "label": "Body", "value": "draft"}
                    ],
                },
                "isError": False,
            },
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(client=client)
    scope = "core-target-bound-observe"
    try:
        launch_result = adapter.execute(
            "app.open",
            {"app_name": "Notes"},
            tool_request=_scoped_tool_request("app.open", scope),
            route=_route("app.open"),
            broker=object(),
        )
        assert adapter.can_execute(
            tool_name,
            _route(tool_name),
            _scoped_tool_request(tool_name, scope),
        ) is True
        result = adapter.execute(
            tool_name,
            {},
            tool_request=_scoped_tool_request(tool_name, scope),
            route=_route(tool_name),
            broker=object(),
        )
    finally:
        client.close()

    assert launch_result["ok"] is True
    assert result["ok"] is True
    assert result["action"] == tool_name
    assert result["agent_owned_target"] is True
    assert result["target_bound"] is True
    assert result["data"]["pid"] == target_pid
    assert result["data"]["window_id"] == target_window_id
    assert result["data"]["app_name"] == "Notes"
    assert result["data"]["desktop_scope"] == "agent_owned_background"
    assert result["data"]["frontmost"] is False
    if expected_collection:
        assert result["data"][expected_collection]
    if tool_name == "desktop.verify":
        assert result["postcondition_verified"] is False
        assert result["verification_inconclusive"] is True
        assert result["data"]["verified"] is False
        assert result["data"]["observation_verified"] is True
    observation_call = next(
        call
        for call in _mcp_tool_calls(process)
        if call["params"]["name"] == "get_window_state"
    )
    assert observation_call["params"]["arguments"] == {
        "pid": target_pid,
        "window_id": target_window_id,
    }


def test_background_verify_does_not_trust_public_source_identity() -> None:
    target_pid = 731011
    target_window_id = 1911
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _get_window_state_tool()],
        tool_results={
            "launch_app": {
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "window_id": target_window_id,
                    "name": "Notes",
                },
                "isError": False,
            },
            "get_window_state": {
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "window_id": target_window_id,
                    "app_name": "Notes",
                    "title": "Agent Draft",
                },
                "isError": False,
            },
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(client=client)
    scope = "core-correlated-window-verify"
    try:
        adapter.execute(
            "app.open",
            {"app_name": "Notes"},
            tool_request=_scoped_tool_request("app.open", scope),
            route=_route("app.open"),
            broker=object(),
        )
        verify_request = _scoped_tool_request("desktop.verify", scope)
        verify_request["source_tool_call_id"] = "call-open-notes"
        result = adapter.execute(
            "desktop.verify",
            {
                "verification_predicate": {
                    "kind": "app_window_present",
                    "app_name": "Notes",
                    "title": "Agent Draft",
                }
            },
            tool_request=verify_request,
            route=_route("desktop.verify"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is True
    assert result["postcondition_verified"] is False
    assert result["verification_method"] == "target_bound_window_observation"
    assert result["verification_failed"] is True
    assert result["verification_inconclusive"] is True
    assert result["data"]["frontmost"] is False
    assert result["data"]["focus_verified"] is False


def test_background_verify_accepts_executor_authorized_app_window_receipt() -> None:
    target_pid = 731011
    target_window_id = 1911
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _get_window_state_tool()],
        tool_results={
            "launch_app": {
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "window_id": target_window_id,
                    "name": "Notes",
                },
                "isError": False,
            },
            "get_window_state": {
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "window_id": target_window_id,
                    "app_name": "Notes",
                    "title": "Agent Draft",
                },
                "isError": False,
            },
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(client=client)
    scope = "core-trusted-window-verify"
    try:
        adapter.execute(
            "app.open",
            {"app_name": "Notes"},
            tool_request=_scoped_tool_request("app.open", scope),
            route=_route("app.open"),
            broker=object(),
        )
        verify_request = _scoped_tool_request("desktop.verify", scope)
        verify_request.update(
            {
                "source_tool_call_id": "call-open-notes",
                "source_step_id": "open-notes",
                "plan_id": "plan-notes",
                "tool_plan_id": "tool-plan-notes",
                "_runtime_verification_context": _trusted_verification_context(
                    scope
                ),
            }
        )
        result = adapter.execute(
            "desktop.verify",
            {
                "verification_predicate": {
                    "kind": "model_forged_predicate",
                    "app_name": "Other",
                }
            },
            tool_request=verify_request,
            route=_route("desktop.verify"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is True
    assert result["postcondition_verified"] is True
    assert result["verification_context_trusted"] is True
    assert result["verification_method"] == "trusted_app_window_present_receipt"
    assert result["verification_run_id"] == f"run:{scope}"
    assert result["verification_plan_id"] == "plan-notes"
    assert result["verification_tool_plan_id"] == "tool-plan-notes"
    assert result["source_tool_call_id"] == "call-open-notes"
    assert result["source_step_id"] == "open-notes"
    assert result["source_tool"] == "app.open"
    assert result["verification_predicate_kind"] == "app_window_present"
    assert result["verified_observed_state"] == "open"
    assert result["observed_target"] == {
        "app_name": "Notes",
        "pid": target_pid,
        "window_id": target_window_id,
        "agent_owned_target": True,
    }
    assert result["data"]["verification_context_trusted"] is True
    assert result["data"]["observed_target"] == result["observed_target"]


@pytest.mark.parametrize(
    "mismatch",
    [
        "serialized_authority",
        "run",
        "call",
        "step",
        "provider",
        "target",
        "predicate",
    ],
)
def test_background_verify_rejects_untrusted_or_mismatched_private_context(
    mismatch: str,
) -> None:
    target_pid = 731011
    target_window_id = 1911
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _get_window_state_tool()],
        tool_results={
            "launch_app": {
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "window_id": target_window_id,
                    "name": "Notes",
                },
                "isError": False,
            },
            "get_window_state": {
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "window_id": target_window_id,
                    "app_name": "Notes",
                    "title": "Agent Draft",
                },
                "isError": False,
            },
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(client=client)
    scope = f"core-private-context-{mismatch}"
    context = _trusted_verification_context(scope)
    verify_route = _route("desktop.verify")
    if mismatch == "serialized_authority":
        with pytest.raises(TypeError):
            json.dumps(context)
        context["_authority"] = "runtime-private-verification-authority"
    elif mismatch == "run":
        context["run_id"] = "run:other"
    elif mismatch == "call":
        context["source_tool_call_id"] = "call-other"
    elif mismatch == "step":
        context["source_step_id"] = "step-other"
    elif mismatch == "provider":
        context["provider_id"] = "other-provider"
    elif mismatch == "target":
        context["target"] = {**context["target"], "window_id": 999}
    elif mismatch == "predicate":
        context["predicate"] = {
            "kind": "arbitrary_model_predicate",
            "app_name": "Notes",
        }
    try:
        adapter.execute(
            "app.open",
            {"app_name": "Notes"},
            tool_request=_scoped_tool_request("app.open", scope),
            route=_route("app.open"),
            broker=object(),
        )
        verify_request = _scoped_tool_request("desktop.verify", scope)
        verify_request.update(
            {
                "source_tool_call_id": "call-open-notes",
                "source_step_id": "open-notes",
                "plan_id": "plan-notes",
                "tool_plan_id": "tool-plan-notes",
                "_runtime_verification_context": context,
            }
        )
        result = adapter.execute(
            "desktop.verify",
            {
                "verification_predicate": {
                    "kind": "app_window_present",
                    "app_name": "Notes",
                }
            },
            tool_request=verify_request,
            route=verify_route,
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is True
    assert result["postcondition_verified"] is False
    assert result["verification_inconclusive"] is True
    assert "verification_context_trusted" not in result
    assert "verified_observed_state" not in result
    assert "observed_target" not in result


def test_background_verify_accepts_exact_typed_content_from_trusted_context() -> None:
    target_pid = 731011
    target_window_id = 1911
    expected_text = "A private exact draft"
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _get_window_state_tool()],
        tool_results={
            "launch_app": {
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "window_id": target_window_id,
                    "name": "Notes",
                },
                "isError": False,
            },
            "get_window_state": {
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "window_id": target_window_id,
                    "app_name": "Notes",
                    "elements": [
                        {
                            "role": "AXTextArea",
                            "label": "Body",
                            "value": expected_text,
                        }
                    ],
                },
                "isError": False,
            },
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(client=client)
    scope = "core-trusted-exact-text"
    context = _trusted_verification_context(
        scope,
        source_tool="desktop.type_into_ui_element",
        predicate={
            "kind": "exact_typed_content_present",
            "expected_text": expected_text,
            "text_sha256": hashlib.sha256(expected_text.encode("utf-8")).hexdigest(),
        },
    )
    try:
        adapter.execute(
            "app.open",
            {"app_name": "Notes"},
            tool_request=_scoped_tool_request("app.open", scope),
            route=_route("app.open"),
            broker=object(),
        )
        verify_request = _scoped_tool_request("desktop.verify", scope)
        verify_request.update(
            {
                "source_tool_call_id": "call-open-notes",
                "source_step_id": "open-notes",
                "plan_id": "plan-notes",
                "tool_plan_id": "tool-plan-notes",
                "_runtime_verification_context": context,
            }
        )
        result = adapter.execute(
            "desktop.verify",
            {},
            tool_request=verify_request,
            route=_route("desktop.verify"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["postcondition_verified"] is True
    assert result["verification_context_trusted"] is True
    assert result["verification_predicate_kind"] == (
        "exact_typed_content_present"
    )
    assert result["verified_observed_state"] == "typed"
    assert result["verification_method"] == (
        "trusted_exact_typed_content_receipt"
    )


def test_executor_to_cua_verifies_exact_grounded_typed_content() -> None:
    target_pid = 731021
    target_window_id = 1921
    expected_text = "Executor-bound exact draft"
    before_snapshot = {
        "structuredContent": {
            "ok": True,
            "pid": target_pid,
            "window_id": target_window_id,
            "app_name": "Notes",
            "elements": [
                {
                    "role": "AXTextArea",
                    "label": "Body",
                    "value": "",
                    "element_index": 4,
                    "element_token": "owned-window:1921:element:4",
                }
            ],
        },
        "isError": False,
    }
    after_snapshot = {
        "structuredContent": {
            "ok": True,
            "pid": target_pid,
            "window_id": target_window_id,
            "app_name": "Notes",
            "elements": [
                {
                    "role": "AXTextArea",
                    "label": "Body",
                    "value": expected_text,
                    "element_index": 4,
                    "element_token": "owned-window:1921:element:4",
                }
            ],
        },
        "isError": False,
    }
    process = FakeMcpProcess(
        tools=[
            _launch_app_tool(),
            _list_apps_tool(),
            _get_window_state_tool(),
            _grounded_type_text_tool(),
        ],
        tool_results={
            "launch_app": {
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "window_id": target_window_id,
                    "name": "Notes",
                    "bundle_id": "com.apple.Notes",
                },
                "isError": False,
            },
            "type_text": {
                "structuredContent": {
                    "ok": True,
                    "effect": "delivery_dispatched",
                },
                "isError": False,
            },
        },
        tool_result_sequences={
            "get_window_state": [
                before_snapshot,
                after_snapshot,
                after_snapshot,
            ]
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(client=client)
    executor = _runtime_executor_for_cua(adapter)
    broker = _FailingLocalBroker()
    timeline: list[dict[str, Any]] = []
    run_id = "run-executor-grounded-type"
    allowed_tools = [
        "app.open",
        "desktop.type_into_ui_element",
        "desktop.verify",
    ]

    def request(tool_name: str, payload: Mapping[str, Any], step_id: str) -> dict[str, Any]:
        return {
            "tool": tool_name,
            "input": dict(payload),
            "step_id": step_id,
            "plan_id": "plan-grounded-type",
            "tool_plan_id": "tool-plan-grounded-type",
            "sandbox_provider": {
                "provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
                "provider_id": "cua-driver",
                "supported_tools": allowed_tools,
            },
            "desktop_execution_route": {
                "tool_name": tool_name,
                "selected_provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
                "selected_provider_id": "cua-driver",
                "provider_execution_required": True,
                "status": "provider_ready",
                "can_execute": True,
                "foreground_takeover_allowed": False,
                "foreground_takeover_required": False,
            },
        }

    try:
        open_result = executor.execute(
            request("app.open", {"app_name": "Notes"}, "open-notes"),
            allowed_tools,
            broker,
            timeline,
            run_id=run_id,
            budget=_ExecutorBudget(),
        )
        type_request = request(
            "desktop.type_into_ui_element",
            {
                "target": "Body",
                "role_filter": "text area",
                "text": expected_text,
            },
            "type-note",
        )
        type_result = executor.execute(
            type_request,
            allowed_tools,
            broker,
            timeline,
            run_id=run_id,
            budget=_ExecutorBudget(),
        )
        verify_request = request("desktop.verify", {}, "verify-note")
        verify_request.update(
            {
                "depends_on": ["type-note"],
                "source_tool_call_id": "model-forged-call",
                "source_step_id": "model-forged-step",
            }
        )
        verify_result = executor.execute(
            verify_request,
            allowed_tools,
            broker,
            timeline,
            run_id=run_id,
            budget=_ExecutorBudget(),
        )
    finally:
        client.close()

    assert open_result["ok"] is True
    assert type_result["ok"] is True
    assert type_result["agent_owned_target"] is True
    assert type_result["grounded_element"]["pid"] == target_pid
    assert type_result["grounded_element"]["window_id"] == target_window_id
    assert verify_result["postcondition_verified"] is True
    assert verify_result["verification_context_trusted"] is True
    assert verify_result["source_tool_call_id"] == type_request["tool_call_id"]
    assert verify_result["source_step_id"] == "type-note"
    assert verify_result["source_tool"] == "desktop.type_into_ui_element"
    assert verify_result["verification_predicate_kind"] == (
        "exact_typed_content_present"
    )
    assert verify_result["verified_observed_state"] == "typed"
    verifier_event = next(
        event
        for event in reversed(timeline)
        if event.get("event") == "agent.tool.call"
        and event.get("detail") == "desktop.verify"
    )
    assert verifier_event["step_id"] == "verify-note"
    assert verifier_event["source_tool_call_id"] == type_request["tool_call_id"]
    assert verifier_event["source_step_id"] == "type-note"
    assert verify_result["observed_target"] == {
        "app_name": "Notes",
        "pid": target_pid,
        "window_id": target_window_id,
        "agent_owned_target": True,
    }


def test_target_bound_observation_is_not_advertised_or_called_without_target_schema() -> None:
    unsafe_observer = {
        "name": "get_window_state",
        "description": "Reads whichever window happens to be active",
        "inputSchema": {"type": "object", "properties": {}},
    }
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), unsafe_observer],
        tool_results={
            "launch_app": {
                "structuredContent": {
                    "ok": True,
                    "pid": 731012,
                    "window_id": 1912,
                    "name": "Notes",
                },
                "isError": False,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.read_ui"],
    )
    scope = "core-unsafe-observer-schema"
    try:
        adapter.execute(
            "app.open",
            {"app_name": "Notes"},
            tool_request=_scoped_tool_request("app.open", scope),
            route=_route("app.open"),
            broker=object(),
        )
        assert adapter.can_execute(
            "desktop.read_ui",
            _route("desktop.read_ui"),
            _scoped_tool_request("desktop.read_ui", scope),
        ) is False
        result = adapter.execute(
            "desktop.read_ui",
            {},
            tool_request=_scoped_tool_request("desktop.read_ui", scope),
            route=_route("desktop.read_ui"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["error"] == "cua_mcp_tool_contract_unsupported"
    assert not any(
        call["params"]["name"] == "get_window_state"
        for call in _mcp_tool_calls(process)
    )


def test_background_window_observation_rejects_mismatched_driver_identity() -> None:
    target_pid = 73102
    target_window_id = 192
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _get_window_state_tool()],
        tool_results={
            "launch_app": {
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "window_id": target_window_id,
                    "name": "Notes",
                },
                "isError": False,
            },
            "get_window_state": {
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid + 1,
                    "window_id": target_window_id,
                    "title": "User Window",
                },
                "isError": False,
            },
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(client=client)
    scope = "core-target-mismatch"
    try:
        adapter.execute(
            "app.open",
            {"app_name": "Notes"},
            tool_request=_scoped_tool_request("app.open", scope),
            route=_route("app.open"),
            broker=object(),
        )
        mismatch = adapter.execute(
            "desktop.read_ui",
            {},
            tool_request=_scoped_tool_request("desktop.read_ui", scope),
            route=_route("desktop.read_ui"),
            broker=object(),
        )
        owns_after_mismatch = adapter.owns_task_scope(
            _scoped_tool_request("desktop.read_ui", scope)
        )
        after_forget = adapter.execute(
            "desktop.read_ui",
            {},
            tool_request=_scoped_tool_request("desktop.read_ui", scope),
            route=_route("desktop.read_ui"),
            broker=object(),
        )
    finally:
        client.close()

    assert mismatch["ok"] is False
    assert mismatch["error"] == "cua_window_state_target_mismatch"
    assert mismatch["requires_user_handoff"] is True
    assert owns_after_mismatch is True
    assert after_forget["ok"] is False
    assert after_forget["error"] == "cua_background_target_required"


def test_untrusted_top_level_and_metadata_ids_cannot_scope_background_input() -> None:
    target_pid = 7311
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _type_text_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {"ok": True, "pid": target_pid},
                "isError": False,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.safe_type_text"],
    )
    try:
        launch_request = {
            **_tool_request("app.open"),
            "run_id": "model-run",
            "task_id": "model-task",
            "metadata": {"core_id": "core-from-metadata"},
        }
        type_request = {
            **_tool_request("desktop.safe_type_text"),
            "run_id": "model-run",
            "task_id": "model-task",
            "metadata": {"core_id": "core-from-metadata"},
        }
        adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=launch_request,
            route=_route("app.open"),
            broker=object(),
        )
        result = adapter.execute(
            "desktop.safe_type_text",
            {"text": "metadata scoped"},
            tool_request=type_request,
            route=_route("desktop.safe_type_text"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["error"] == "cua_task_scope_required"
    assert [call["params"]["name"] for call in _mcp_tool_calls(process)] == [
        "list_apps",
        "launch_app"
    ]


def test_same_core_id_does_not_share_target_across_runtime_task_ids() -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _type_text_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {"ok": True, "pid": 7315},
                "isError": False,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.safe_type_text"],
    )
    try:
        launch_request = {
            **_tool_request("app.open"),
            "core_id": "deterministic-shared-core",
            "task_id": "task-a",
            "_runtime_execution_scope": {
                "run_id": "run-a",
                "task_id": "task-a",
                "core_id": "deterministic-shared-core",
            },
        }
        type_request = {
            **_tool_request("desktop.safe_type_text"),
            "core_id": "deterministic-shared-core",
            "task_id": "task-b",
            "_runtime_execution_scope": {
                "run_id": "run-b",
                "task_id": "task-b",
                "core_id": "deterministic-shared-core",
            },
        }
        adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=launch_request,
            route=_route("app.open"),
            broker=object(),
        )
        result = adapter.execute(
            "desktop.safe_type_text",
            {"text": "must stay isolated"},
            tool_request=type_request,
            route=_route("desktop.safe_type_text"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["error"] == "cua_background_target_required"
    assert [call["params"]["name"] for call in _mcp_tool_calls(process)] == [
        "list_apps",
        "launch_app"
    ]


def test_pidless_relaunch_clears_the_scope_previous_background_target() -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _type_text_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {"ok": True, "pid": 7312},
                "isError": False,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.safe_type_text"],
    )
    try:
        adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-relaunch"),
            route=_route("app.open"),
            broker=object(),
        )
        process.tool_results["launch_app"] = {
            "content": [{"type": "text", "text": "launched without target"}],
            "structuredContent": {"ok": True},
            "isError": False,
        }
        adapter.execute(
            "app.open",
            {"app_name": "Notes"},
            tool_request=_scoped_tool_request("app.open", "core-relaunch"),
            route=_route("app.open"),
            broker=object(),
        )
        result = adapter.execute(
            "desktop.safe_type_text",
            {"text": "must not reach TextEdit"},
            tool_request=_scoped_tool_request(
                "desktop.safe_type_text",
                "core-relaunch",
            ),
            route=_route("desktop.safe_type_text"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["error"] == "cua_background_target_required"
    assert [call["params"]["name"] for call in _mcp_tool_calls(process)] == [
        "list_apps",
        "launch_app",
        "list_apps",
        "launch_app",
    ]


def test_repeated_launch_reuses_the_run_owned_background_instance() -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _list_apps_tool()],
        tool_results={
            "launch_app": {
                "structuredContent": {
                    "ok": True,
                    "pid": 73120,
                    "window_id": 120,
                    "name": "Notes",
                    "bundle_id": "com.apple.Notes",
                },
                "isError": False,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open"],
    )
    scope = "core-idempotent-launch"
    try:
        first = adapter.execute(
            "app.open",
            {"app_name": "Notes"},
            tool_request=_scoped_tool_request("app.open", scope),
            route=_route("app.open"),
            broker=object(),
        )
        second = adapter.execute(
            "app.open",
            {"app_name": "Notes"},
            tool_request=_scoped_tool_request("app.open", scope),
            route=_route("app.open"),
            broker=object(),
        )
    finally:
        client.close()

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["status"] == "background_target_reused"
    assert second["launch_reused"] is True
    assert second["launch_verified"] is True
    assert second["agent_owned_target"] is True
    assert second["pid"] == 73120
    assert [call["params"]["name"] for call in _mcp_tool_calls(process)] == [
        "list_apps",
        "launch_app",
        "list_apps",
    ]


def test_payload_pid_mismatch_never_overrides_the_scoped_launch_target() -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _type_text_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {"ok": True, "pid": 7313},
                "isError": False,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.safe_type_text"],
    )
    try:
        adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-pid-mismatch"),
            route=_route("app.open"),
            broker=object(),
        )
        result = adapter.execute(
            "desktop.safe_type_text",
            {"pid": 9999, "text": "do not redirect"},
            tool_request=_scoped_tool_request(
                "desktop.safe_type_text",
                "core-pid-mismatch",
            ),
            route=_route("desktop.safe_type_text"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["error"] == "cua_background_target_mismatch"
    assert [call["params"]["name"] for call in _mcp_tool_calls(process)] == [
        "list_apps",
        "launch_app"
    ]


@pytest.mark.parametrize(
    "tool_name",
    ["desktop.safe_click", "desktop.click_ui_element"],
)
def test_background_provider_does_not_advertise_untranslatable_click_tools(
    tool_name: str,
) -> None:
    process = FakeMcpProcess(tools=[_click_tool()])
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(client=client)
    try:
        assert adapter.can_execute(
            tool_name,
            _route(tool_name),
            _tool_request(tool_name),
        ) is False
    finally:
        client.close()


def test_grounded_click_uses_unique_snapshot_token_on_owned_window_only() -> None:
    process = FakeMcpProcess(
        tools=[
            _launch_app_tool(),
            _list_apps_tool(),
            _get_window_state_tool(),
            _click_tool(),
        ],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {
                    "ok": True,
                    "pid": 7401,
                    "window_id": 91,
                    "name": "Notes",
                    "bundle_id": "com.apple.Notes",
                },
                "isError": False,
            },
            "click": {
                "content": [{"type": "text", "text": "clicked"}],
                "structuredContent": {
                    "ok": True,
                    "verified": False,
                    "effect": "unverifiable",
                    "summary": "Export completed",
                },
                "isError": False,
            },
        },
        tool_result_sequences={
            "get_window_state": [
                {
                    "structuredContent": {
                        "ok": True,
                        "pid": 7401,
                        "window_id": 91,
                        "title": "Notes",
                        "elements": [
                            {
                                "role": "AXButton",
                                "label": "Export Report",
                                "element_index": 4,
                                "element_token": "owned-window:91:element:4",
                            }
                        ],
                    },
                    "isError": False,
                },
                {
                    "structuredContent": {
                        "ok": True,
                        "pid": 7401,
                        "window_id": 91,
                        "title": "Export Sheet",
                        "elements": [],
                    },
                    "isError": False,
                },
            ]
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.click_ui_element"],
    )
    try:
        assert adapter.can_execute(
            "desktop.click_ui_element",
            _route("desktop.click_ui_element"),
            _scoped_tool_request("desktop.click_ui_element", "core-ground-click"),
        ) is True
        adapter.execute(
            "app.open",
            {"app_name": "Notes"},
            tool_request=_scoped_tool_request("app.open", "core-ground-click"),
            route=_route("app.open"),
            broker=object(),
        )
        result = adapter.execute(
            "desktop.click_ui_element",
            {
                "target": "  EXPORT   REPORT ",
                "role_filter": "button",
                "element_token": "model-authored-token",
                "element_index": 999,
                "x": 100,
                "y": 200,
            },
            tool_request=_scoped_tool_request(
                "desktop.click_ui_element",
                "core-ground-click",
            ),
            route=_route("desktop.click_ui_element"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is True
    assert result["status"] == "state_change_observed"
    assert result["postcondition_verified"] is False
    assert result["requires_postcondition_verification"] is True
    assert "completed" not in result["summary"].lower()
    assert result["grounded_element"] == {
        "label": "EXPORT   REPORT",
        "role": "AXButton",
        "selector_type": "element_token",
        "pid": 7401,
        "window_id": 91,
    }
    assert [call["params"]["name"] for call in _mcp_tool_calls(process)] == [
        "list_apps",
        "launch_app",
        "list_apps",
        "get_window_state",
        "click",
        "get_window_state",
    ]
    click_arguments = _mcp_tool_calls(process)[4]["params"]["arguments"]
    assert click_arguments == {
        "pid": 7401,
        "window_id": 91,
        "element_token": "owned-window:91:element:4",
        "delivery_mode": "background",
    }


@pytest.mark.parametrize(
    ("elements", "target", "expected_error"),
    [
        (
            [
                {"role": "AXButton", "label": "Export", "element_index": 1},
                {"role": "AXButton", "label": "Export", "element_index": 2},
            ],
            "Export",
            "cua_background_element_ambiguous",
        ),
        (
            [{"role": "AXButton", "label": "Export Report", "element_index": 1}],
            "Export",
            "cua_background_element_not_found",
        ),
    ],
)
def test_grounded_click_fails_closed_on_ambiguous_or_non_exact_label(
    elements: list[dict[str, Any]],
    target: str,
    expected_error: str,
) -> None:
    process = FakeMcpProcess(
        tools=[
            _launch_app_tool(),
            _list_apps_tool(),
            _get_window_state_tool(),
            _click_tool(),
        ],
        tool_results={
            "launch_app": {
                "structuredContent": {
                    "ok": True,
                    "pid": 7402,
                    "window_id": 92,
                    "name": "Notes",
                    "bundle_id": "com.apple.Notes",
                },
                "isError": False,
            },
            "get_window_state": {
                "structuredContent": {
                    "ok": True,
                    "pid": 7402,
                    "window_id": 92,
                    "elements": elements,
                },
                "isError": False,
            },
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.click_ui_element"],
    )
    try:
        adapter.execute(
            "app.open",
            {"app_name": "Notes"},
            tool_request=_scoped_tool_request("app.open", "core-ground-fail"),
            route=_route("app.open"),
            broker=object(),
        )
        result = adapter.execute(
            "desktop.click_ui_element",
            {"target": target, "role_filter": "AXButton"},
            tool_request=_scoped_tool_request(
                "desktop.click_ui_element",
                "core-ground-fail",
            ),
            route=_route("desktop.click_ui_element"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["error"] == expected_error
    assert result["requires_user_handoff"] is True
    assert "click" not in [
        call["params"]["name"] for call in _mcp_tool_calls(process)
    ]


def test_equivalent_duplicate_ax_projections_collapse_to_one_stable_element() -> None:
    duplicate_frame = {"x": 213.0, "y": 177.0, "w": 586.0, "h": 382.0}
    matches = [
        {
            "role": "AXTextArea",
            "label": "First Text View",
            "frame": duplicate_frame,
            "element_index": 378,
            "element_token": "window-root-token",
        },
        {
            "role": "AXTextArea",
            "label": "First Text View",
            "frame": duplicate_frame,
            "element_index": 1,
            "element_token": "app-root-token",
        },
    ]

    collapsed = (
        cua_background_provider_module._collapse_equivalent_cua_element_matches(
            matches
        )
    )

    assert len(collapsed) == 1
    assert collapsed[0]["element_index"] == 1
    assert collapsed[0]["element_token"] == "app-root-token"


def test_same_label_on_distinct_or_unframed_ax_elements_remains_ambiguous() -> None:
    distinct = [
        {
            "role": "AXButton",
            "label": "Export",
            "frame": {"x": 10, "y": 10, "w": 20, "h": 20},
            "element_index": 1,
        },
        {
            "role": "AXButton",
            "label": "Export",
            "frame": {"x": 40, "y": 10, "w": 20, "h": 20},
            "element_index": 2,
        },
    ]
    unframed = [
        {"role": "AXButton", "label": "Export", "element_index": 1},
        {"role": "AXButton", "label": "Export", "element_index": 2},
    ]

    assert len(
        cua_background_provider_module._collapse_equivalent_cua_element_matches(
            distinct
        )
    ) == 2
    assert len(
        cua_background_provider_module._collapse_equivalent_cua_element_matches(
            unframed
        )
    ) == 2
def test_grounded_click_rejects_snapshot_from_a_different_window() -> None:
    process = FakeMcpProcess(
        tools=[
            _launch_app_tool(),
            _list_apps_tool(),
            _get_window_state_tool(),
            _click_tool(),
        ],
        tool_results={
            "launch_app": {
                "structuredContent": {
                    "ok": True,
                    "pid": 7403,
                    "window_id": 93,
                    "name": "Notes",
                    "bundle_id": "com.apple.Notes",
                },
                "isError": False,
            },
            "get_window_state": {
                "structuredContent": {
                    "ok": True,
                    "pid": 7403,
                    "window_id": 999,
                    "elements": [
                        {"role": "AXButton", "label": "Export", "element_index": 1}
                    ],
                },
                "isError": False,
            },
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.click_ui_element"],
    )
    try:
        adapter.execute(
            "app.open",
            {"app_name": "Notes"},
            tool_request=_scoped_tool_request("app.open", "core-window-mismatch"),
            route=_route("app.open"),
            broker=object(),
        )
        result = adapter.execute(
            "desktop.click_ui_element",
            {"target": "Export"},
            tool_request=_scoped_tool_request(
                "desktop.click_ui_element",
                "core-window-mismatch",
            ),
            route=_route("desktop.click_ui_element"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["error"] == "cua_background_window_identity_mismatch"
    assert result["requires_user_handoff"] is True
    assert "click" not in [
        call["params"]["name"] for call in _mcp_tool_calls(process)
    ]


def test_grounded_click_never_targets_a_reused_user_process() -> None:
    process = FakeMcpProcess(
        tools=[
            _launch_app_tool(),
            _list_apps_tool(),
            _get_window_state_tool(),
            _click_tool(),
        ],
        tool_results={
            "launch_app": {
                "structuredContent": {
                    "ok": True,
                    "pid": 7406,
                    "window_id": 96,
                    "name": "Notes",
                    "bundle_id": "com.apple.Notes",
                },
                "isError": False,
            }
        },
        tool_result_sequences={
            "list_apps": [
                _list_apps_identity_result(
                    7406,
                    name="Notes",
                    bundle_id="com.apple.Notes",
                )
            ]
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.click_ui_element"],
    )
    try:
        launch_result = adapter.execute(
            "app.open",
            {"app_name": "Notes"},
            tool_request=_scoped_tool_request("app.open", "core-reused-click"),
            route=_route("app.open"),
            broker=object(),
        )
        result = adapter.execute(
            "desktop.click_ui_element",
            {"target": "Save"},
            tool_request=_scoped_tool_request(
                "desktop.click_ui_element",
                "core-reused-click",
            ),
            route=_route("desktop.click_ui_element"),
            broker=object(),
        )
    finally:
        client.close()

    assert launch_result["agent_owned_target"] is False
    assert result["ok"] is False
    assert result["error"] == "cua_background_target_required"
    assert result["requires_user_handoff"] is True
    assert "get_window_state" not in [
        call["params"]["name"] for call in _mcp_tool_calls(process)
    ]
    assert "click" not in [
        call["params"]["name"] for call in _mcp_tool_calls(process)
    ]


def test_open_and_grounded_click_never_claims_business_completion() -> None:
    snapshot = {
        "structuredContent": {
            "ok": True,
            "pid": 7404,
            "window_id": 94,
            "title": "Notes",
            "elements": [
                {
                    "role": "AXButton",
                    "label": "Save",
                    "element_index": 7,
                }
            ],
        },
        "isError": False,
    }
    process = FakeMcpProcess(
        tools=[
            _launch_app_tool(),
            _list_apps_tool(),
            _get_window_state_tool(),
            _click_tool(),
        ],
        tool_results={
            "launch_app": {
                "structuredContent": {
                    "ok": True,
                    "pid": 7404,
                    "window_id": 94,
                    "name": "Notes",
                    "bundle_id": "com.apple.Notes",
                },
                "isError": False,
            },
            "click": {
                "structuredContent": {
                    "ok": True,
                    "verified": True,
                    "effect": "business_completed",
                },
                "isError": False,
            },
        },
        tool_result_sequences={"get_window_state": [snapshot, snapshot]},
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open_and_click_ui_element"],
    )
    try:
        result = adapter.execute(
            "app.open_and_click_ui_element",
            {"app_name": "Notes", "target": "Save", "role_filter": "button"},
            tool_request=_scoped_tool_request(
                "app.open_and_click_ui_element",
                "core-open-ground-click",
            ),
            route=_route("app.open_and_click_ui_element"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is True
    assert result["status"] == "delivery_dispatched"
    assert result["postcondition_verified"] is False
    assert result["delivery_verified"] is False
    assert result["effect"] == "delivery_dispatched"
    assert result["tool"] == "app.open_and_click_ui_element"
    assert result["composite_steps"][-1]["tool"] == "desktop.click_ui_element"
    assert "business outcome is unverified" in result["summary"]


def test_grounded_type_uses_snapshot_element_without_focus_or_coordinates() -> None:
    process = FakeMcpProcess(
        tools=[
            _launch_app_tool(),
            _list_apps_tool(),
            _get_window_state_tool(),
            _grounded_type_text_tool(),
        ],
        tool_results={
            "launch_app": {
                "structuredContent": {
                    "ok": True,
                    "pid": 7405,
                    "window_id": 95,
                    "name": "Notes",
                    "bundle_id": "com.apple.Notes",
                },
                "isError": False,
            }
        },
        tool_result_sequences={
            "get_window_state": [
                {
                    "structuredContent": {
                        "ok": True,
                        "pid": 7405,
                        "window_id": 95,
                        "elements": [
                            {
                                "role": "AXTextField",
                                "label": "Search",
                                "frame": {"x": 10, "y": 20, "w": 200, "h": 30},
                                "element_index": 1,
                                "element_token": "owned-search-field",
                            },
                            {
                                "role": "AXTextField",
                                "label": "Search",
                                "frame": {"x": 10, "y": 20, "w": 200, "h": 30},
                                "element_index": 378,
                                "element_token": "duplicate-search-field",
                            }
                        ],
                    },
                    "isError": False,
                },
                {
                    "structuredContent": {
                        "ok": True,
                        "pid": 7405,
                        "window_id": 95,
                        "elements": [
                            {
                                "role": "AXTextField",
                                "label": "Search",
                                "value": "hello",
                                "frame": {"x": 10, "y": 20, "w": 200, "h": 30},
                                "element_index": 1,
                                "element_token": "owned-search-field",
                            },
                            {
                                "role": "AXTextField",
                                "label": "Search",
                                "value": "hello",
                                "frame": {"x": 10, "y": 20, "w": 200, "h": 30},
                                "element_index": 378,
                                "element_token": "duplicate-search-field",
                            }
                        ],
                    },
                    "isError": False,
                },
            ]
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.type_into_ui_element"],
    )
    try:
        adapter.execute(
            "app.open",
            {"app_name": "Notes"},
            tool_request=_scoped_tool_request("app.open", "core-ground-type"),
            route=_route("app.open"),
            broker=object(),
        )
        result = adapter.execute(
            "desktop.type_into_ui_element",
            {
                "target": "Search",
                "role_filter": "text field",
                "text": "hello",
                "x": 1,
                "y": 2,
            },
            tool_request=_scoped_tool_request(
                "desktop.type_into_ui_element",
                "core-ground-type",
            ),
            route=_route("desktop.type_into_ui_element"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is True
    assert result["status"] == "state_change_observed"
    assert result["grounded_element"]["equivalent_match_count"] == 2
    type_arguments = next(
        call["params"]["arguments"]
        for call in _mcp_tool_calls(process)
        if call["params"]["name"] == "type_text"
    )
    assert type_arguments == {
        "pid": 7405,
        "window_id": 95,
        "element_token": "owned-search-field",
        "text": "hello",
        "delivery_mode": "background",
    }


def test_grounded_tools_are_not_advertised_without_element_bound_schema() -> None:
    process = FakeMcpProcess(
        tools=[_list_apps_tool(), _get_window_state_tool(), _type_text_tool()]
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(client=client)
    try:
        assert adapter.can_execute(
            "desktop.type_into_ui_element",
            _route("desktop.type_into_ui_element"),
            _tool_request("desktop.type_into_ui_element"),
        ) is False
    finally:
        client.close()


def test_safe_key_repeat_count_dispatches_each_background_press_in_order() -> None:
    process = FakeMcpProcess(
        tools=[
            _launch_app_tool(),
            _background_input_tool("press_key", "key"),
            _get_window_state_tool(),
        ],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {"ok": True, "pid": 7314},
                "isError": False,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.safe_key"],
    )
    try:
        adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-repeat-key"),
            route=_route("app.open"),
            broker=object(),
        )
        result = adapter.execute(
            "desktop.safe_key",
            {"action": "arrow_down", "repeat_count": 3},
            tool_request=_scoped_tool_request(
                "desktop.safe_key",
                "core-repeat-key",
            ),
            route=_route("desktop.safe_key"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is True
    press_calls = [
        call
        for call in _mcp_tool_calls(process)
        if call["params"]["name"] == "press_key"
    ]
    assert len(press_calls) == 3
    assert all(
        call["params"]["arguments"]
        == {"pid": 7314, "key": "down", "delivery_mode": "background"}
        for call in press_calls
    )


def test_background_actions_do_not_create_implicit_cua_sessions() -> None:
    type_tool = _type_text_tool()
    type_tool["inputSchema"]["properties"]["session"] = {"type": "string"}
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), type_tool],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {"ok": True, "pid": 7316},
                "isError": False,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.safe_type_text"],
    )
    try:
        adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-no-session"),
            route=_route("app.open"),
            broker=object(),
        )
        adapter.execute(
            "desktop.safe_type_text",
            {"text": "hello", "session": "model-controlled-session"},
            tool_request=_scoped_tool_request(
                "desktop.safe_type_text",
                "core-no-session",
            ),
            route=_route("desktop.safe_type_text"),
            broker=object(),
        )
    finally:
        client.close()

    type_calls = [
        call
        for call in _mcp_tool_calls(process)
        if call["params"]["name"] == "type_text"
    ]
    assert len(type_calls) == 1
    assert "session" not in type_calls[0]["params"]["arguments"]


def test_reused_pid_with_a_different_app_identity_is_rejected_before_input() -> None:
    target_pid = 7317
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _list_apps_tool(), _type_text_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {
                    "ok": True,
                    "pid": target_pid,
                    "name": "TextEdit",
                    "bundle_id": "com.apple.TextEdit",
                },
                "isError": False,
            },
        },
        tool_result_sequences={
            "list_apps": [
                {
                    "structuredContent": {"apps": []},
                    "isError": False,
                },
                _list_apps_identity_result(
                    target_pid,
                    name="Calculator",
                    bundle_id="com.apple.calculator",
                ),
            ]
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.safe_type_text"],
    )
    try:
        adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-pid-reuse"),
            route=_route("app.open"),
            broker=object(),
        )
        result = adapter.execute(
            "desktop.safe_type_text",
            {"text": "must not reach Calculator"},
            tool_request=_scoped_tool_request(
                "desktop.safe_type_text",
                "core-pid-reuse",
            ),
            route=_route("desktop.safe_type_text"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["error"] == "cua_background_target_identity_mismatch"
    assert result["blocked_by_desktop_execution_provider"] is False
    assert result["blocked_by_desktop_target"] is True
    assert result["target_reacquisition_required"] is True
    assert result["retryable"] is True
    assert result["requires_user_handoff"] is False
    assert result["recommended_tools"] == ["app.open"]
    assert [call["params"]["name"] for call in _mcp_tool_calls(process)] == [
        "list_apps",
        "launch_app",
        "list_apps",
    ]


def test_background_input_has_no_target_when_launch_identity_dependency_is_missing() -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _type_text_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {"ok": True, "pid": 7325},
                "isError": False,
            }
        },
    )
    process.tools = [
        tool for tool in process.tools if tool.get("name") != "list_apps"
    ]
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.safe_type_text"],
    )
    try:
        adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-missing-list-apps"),
            route=_route("app.open"),
            broker=object(),
        )
        result = adapter.execute(
            "desktop.safe_type_text",
            {"text": "do not type without revalidation"},
            tool_request=_scoped_tool_request(
                "desktop.safe_type_text",
                "core-missing-list-apps",
            ),
            route=_route("desktop.safe_type_text"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["error"] == "cua_background_target_required"
    assert _mcp_tool_calls(process) == []


def test_read_ui_rejects_an_explicit_app_name_outside_the_scoped_target() -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _get_window_state_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {
                    "ok": True,
                    "pid": 7318,
                    "name": "Music",
                    "bundle_id": "com.apple.Music",
                    "window_id": 81,
                },
                "isError": False,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.read_ui"],
        tool_name_map={"desktop.read_ui": "get_window_state"},
    )
    try:
        adapter.execute(
            "app.open",
            {"app_name": "Music"},
            tool_request=_scoped_tool_request("app.open", "core-app-binding"),
            route=_route("app.open"),
            broker=object(),
        )
        result = adapter.execute(
            "desktop.read_ui",
            {"app_name": "Safari"},
            tool_request=_scoped_tool_request(
                "desktop.read_ui",
                "core-app-binding",
            ),
            route=_route("desktop.read_ui"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["error"] == "cua_background_app_mismatch"
    assert [call["params"]["name"] for call in _mcp_tool_calls(process)] == [
        "list_apps",
        "launch_app"
    ]


def test_launch_that_kept_foreground_is_a_policy_failure_and_caches_no_target() -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _type_text_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched in foreground"}],
                "structuredContent": {
                    "ok": True,
                    "pid": 7319,
                    "name": "TextEdit",
                    "self_activation_suppressed": False,
                },
                "isError": False,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.safe_type_text"],
    )
    try:
        launch_result = adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-launch-focus"),
            route=_route("app.open"),
            broker=object(),
        )
        type_result = adapter.execute(
            "desktop.safe_type_text",
            {"text": "must not continue"},
            tool_request=_scoped_tool_request(
                "desktop.safe_type_text",
                "core-launch-focus",
            ),
            route=_route("desktop.safe_type_text"),
            broker=object(),
        )
    finally:
        client.close()

    assert launch_result["ok"] is False
    assert launch_result["status"] == "foreground_delivery_violation"
    assert launch_result["error"] == "cua_launch_foreground_takeover_detected"
    assert type_result["ok"] is False
    assert type_result["error"] == "cua_background_target_required"
    assert [call["params"]["name"] for call in _mcp_tool_calls(process)] == [
        "list_apps",
        "launch_app"
    ]


def test_suspected_noop_is_a_retryable_unverified_failure() -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _type_text_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {"ok": True, "pid": 7320},
                "isError": False,
            },
            "type_text": {
                "content": [{"type": "text", "text": "suspected no-op"}],
                "structuredContent": {
                    "ok": True,
                    "effect": "suspected_noop",
                    "verified": False,
                },
                "isError": False,
            },
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.safe_type_text"],
    )
    try:
        adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-noop"),
            route=_route("app.open"),
            broker=object(),
        )
        result = adapter.execute(
            "desktop.safe_type_text",
            {"text": "hello"},
            tool_request=_scoped_tool_request(
                "desktop.safe_type_text",
                "core-noop",
            ),
            route=_route("desktop.safe_type_text"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["status"] == "provider_action_unverified"
    assert result["error"] == "cua_action_suspected_noop"
    assert result["retryable"] is True
    assert result["postcondition_verified"] is False


def test_verified_false_is_dispatched_but_not_terminal_success() -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _type_text_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {"ok": True, "pid": 7321},
                "isError": False,
            },
            "type_text": {
                "content": [{"type": "text", "text": "dispatched"}],
                "structuredContent": {
                    "ok": True,
                    "effect": "unverifiable",
                    "verified": False,
                },
                "isError": False,
            },
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.safe_type_text"],
    )
    try:
        adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-unverified"),
            route=_route("app.open"),
            broker=object(),
        )
        result = adapter.execute(
            "desktop.safe_type_text",
            {"text": "hello"},
            tool_request=_scoped_tool_request(
                "desktop.safe_type_text",
                "core-unverified",
            ),
            route=_route("desktop.safe_type_text"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["status"] == "dispatched_unverified"
    assert result["error"] == "cua_action_unverified"
    assert result["action_dispatched"] is True
    assert result["postcondition_verified"] is False
    assert result["requires_postcondition_verification"] is True


def test_unverifiable_hotkey_exposes_target_bound_state_change_evidence() -> None:
    process = FakeMcpProcess(
        tools=[
            _launch_app_tool(),
            _background_input_tool("hotkey", "keys"),
            _get_window_state_tool(),
        ],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {
                    "ok": True,
                    "pid": 7322,
                    "window_id": 82,
                    "name": "Notes",
                    "bundle_id": "com.apple.Notes",
                },
                "isError": False,
            },
            "hotkey": {
                "content": [{"type": "text", "text": "dispatched"}],
                "structuredContent": {
                    "ok": True,
                    "effect": "unverifiable",
                    "verified": False,
                },
                "isError": False,
            },
        },
        tool_result_sequences={
            "get_window_state": [
                {
                    "content": [{"type": "text", "text": "before"}],
                    "structuredContent": {
                        "ok": True,
                        "pid": 7322,
                        "window_id": 82,
                        "title": "Notes",
                    },
                    "isError": False,
                },
                {
                    "content": [{"type": "text", "text": "after"}],
                    "structuredContent": {
                        "ok": True,
                        "pid": 7322,
                        "window_id": 82,
                        "title": "New Note",
                    },
                    "isError": False,
                },
            ]
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.safe_shortcut"],
    )
    try:
        adapter.execute(
            "app.open",
            {"app_name": "Notes"},
            tool_request=_scoped_tool_request("app.open", "core-hotkey-snapshot"),
            route=_route("app.open"),
            broker=object(),
        )
        result = adapter.execute(
            "desktop.safe_shortcut",
            {"action": "new_note"},
            tool_request=_scoped_tool_request(
                "desktop.safe_shortcut",
                "core-hotkey-snapshot",
            ),
            route=_route("desktop.safe_shortcut"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["verification_evidence"]["available"] is True, result[
        "verification_evidence"
    ]
    assert result["ok"] is True, result
    assert result["status"] == "state_change_observed"
    assert result["delivery_verified"] is True
    assert result["postcondition_verified"] is False
    assert result["requires_postcondition_verification"] is True
    assert result["verification_evidence"]["state_changed"] is True
    assert [call["params"]["name"] for call in _mcp_tool_calls(process)] == [
        "list_apps",
        "launch_app",
        "list_apps",
        "get_window_state",
        "hotkey",
        "get_window_state",
    ]


def test_two_apps_in_one_run_make_an_unbound_input_target_ambiguous() -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _type_text_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched Notes"}],
                "structuredContent": {
                    "ok": True,
                    "pid": 7322,
                    "name": "Notes",
                    "bundle_id": "com.apple.Notes",
                },
                "isError": False,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.safe_type_text"],
    )
    scope = "core-multiple-apps"
    try:
        adapter.execute(
            "app.open",
            {"app_name": "Notes"},
            tool_request=_scoped_tool_request("app.open", scope),
            route=_route("app.open"),
            broker=object(),
        )
        process.tool_results["launch_app"] = {
            "content": [{"type": "text", "text": "launched Safari"}],
            "structuredContent": {
                "ok": True,
                "pid": 7323,
                "name": "Safari",
                "bundle_id": "com.apple.Safari",
            },
            "isError": False,
        }
        adapter.execute(
            "app.open",
            {"app_name": "Safari"},
            tool_request=_scoped_tool_request("app.open", scope),
            route=_route("app.open"),
            broker=object(),
        )
        result = adapter.execute(
            "desktop.safe_type_text",
            {"text": "do not guess Safari"},
            tool_request=_scoped_tool_request("desktop.safe_type_text", scope),
            route=_route("desktop.safe_type_text"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is False
    assert result["error"] == "cua_background_target_ambiguous"
    assert [call["params"]["name"] for call in _mcp_tool_calls(process)] == [
        "list_apps",
        "launch_app",
        "list_apps",
        "launch_app",
    ]


def test_safe_scroll_maps_pages_without_forwarding_screen_coordinates() -> None:
    process = FakeMcpProcess(
        tools=[_launch_app_tool(), _scroll_tool(), _get_window_state_tool()],
        tool_results={
            "launch_app": {
                "content": [{"type": "text", "text": "launched"}],
                "structuredContent": {"ok": True, "pid": 7324},
                "isError": False,
            }
        },
    )
    client = _client_for(process)
    adapter = CuaBackgroundDesktopExecutionProviderAdapter(
        client=client,
        supported_tools=["app.open", "desktop.safe_scroll"],
    )
    try:
        adapter.execute(
            "app.open",
            {"app_name": "TextEdit"},
            tool_request=_scoped_tool_request("app.open", "core-safe-scroll"),
            route=_route("app.open"),
            broker=object(),
        )
        result = adapter.execute(
            "desktop.safe_scroll",
            {"direction": "down", "pages": 2, "x": 900, "y": 700},
            tool_request=_scoped_tool_request(
                "desktop.safe_scroll",
                "core-safe-scroll",
            ),
            route=_route("desktop.safe_scroll"),
            broker=object(),
        )
    finally:
        client.close()

    assert result["ok"] is True
    scroll_call = next(
        call
        for call in _mcp_tool_calls(process)
        if call["params"]["name"] == "scroll"
    )
    assert scroll_call["params"]["arguments"] == {
        "pid": 7324,
        "direction": "down",
        "amount": 2,
        "by": "page",
        "delivery_mode": "background",
    }
