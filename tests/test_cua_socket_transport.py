"""Contract tests for the authenticated Electron-owned Cua MCP bridge."""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Mapping
from typing import Any

import pytest

from apps.shell.agent.runtime.cua_background_provider import (
    CUA_MCP_BRIDGE_GENERATION_ENV,
    CUA_MCP_BRIDGE_TOKEN_ENV,
    CUA_MCP_BRIDGE_URL_ENV,
    CUA_MCP_TRANSPORT_ENV,
    CuaMcpClient,
    CuaMcpProtocolError,
    CuaMcpTransportError,
    _cua_health_cache_key,
    _CuaElectronBridgeConfiguration,
    cua_background_provider_adapter_from_env,
    cua_background_provider_status,
    resolve_cua_mcp_command,
)

_TOKEN = "a" * 64


class _ScriptedJsonLineTransport:
    def __init__(self, response: Mapping[str, Any]) -> None:
        self.response = dict(response)
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    def send(self, payload: Mapping[str, Any]) -> None:
        self.sent.append(dict(payload))

    def receive(self, timeout: float) -> dict[str, Any]:
        del timeout
        return dict(self.response)

    def close(self) -> None:
        self.closed = True


class _FakeElectronBridge:
    """Tiny authenticated line-JSON bridge; it never starts Cua Driver."""

    def __init__(
        self,
        *,
        token: str = _TOKEN,
        ack: Mapping[str, Any] | None = None,
        drop_first_initialize: bool = False,
    ) -> None:
        self.token = token
        self.ack = dict(
            ack
            or {
                "protocol": "oha-yachiyo-cua-mcp-bridge",
                "version": 1,
                "ok": True,
            }
        )
        self.drop_first_initialize = drop_first_initialize
        self.handshakes: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []
        self.connection_count = 0
        self._stopping = threading.Event()
        self._accepted = threading.Event()
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen()
        self._server.settimeout(0.1)
        self.port = int(self._server.getsockname()[1])
        self._threads: list[threading.Thread] = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"tcp://127.0.0.1:{self.port}"

    def wait_for_connection(self, timeout: float = 1.0) -> bool:
        return self._accepted.wait(timeout)

    def close(self) -> None:
        self._stopping.set()
        try:
            self._server.close()
        except OSError:
            pass
        self._thread.join(timeout=1.0)
        for thread in self._threads:
            thread.join(timeout=1.0)

    def _serve(self) -> None:
        while not self._stopping.is_set():
            try:
                connection, _address = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            self.connection_count += 1
            self._accepted.set()
            thread = threading.Thread(
                target=self._serve_connection,
                args=(connection, self.connection_count),
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()

    def _serve_connection(self, connection: socket.socket, ordinal: int) -> None:
        try:
            stream = connection.makefile("rwb")
            handshake_line = stream.readline()
            if not handshake_line:
                return
            handshake = json.loads(handshake_line.decode("utf-8"))
            self.handshakes.append(dict(handshake))
            if handshake.get("token") != self.token:
                return
            stream.write(json.dumps(self.ack).encode("utf-8") + b"\n")
            stream.flush()
            while True:
                line = stream.readline()
                if not line:
                    return
                request = json.loads(line.decode("utf-8"))
                self.requests.append(dict(request))
                method = str(request.get("method") or "")
                if method == "notifications/initialized":
                    continue
                if method == "initialize" and self.drop_first_initialize and ordinal == 1:
                    return
                if "id" not in request:
                    continue
                result: dict[str, Any]
                if method == "initialize":
                    result = {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "fake-electron-cua", "version": "0"},
                    }
                elif method == "tools/list":
                    result = {"tools": []}
                else:
                    result = {}
                response = {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "result": result,
                }
                stream.write(json.dumps(response).encode("utf-8") + b"\n")
                stream.flush()
        finally:
            try:
                connection.close()
            except OSError:
                pass


def _bridge_env(bridge: _FakeElectronBridge, **overrides: str) -> dict[str, str]:
    environ = {
        CUA_MCP_TRANSPORT_ENV: "electron-bridge-v1",
        CUA_MCP_BRIDGE_URL_ENV: bridge.url,
        CUA_MCP_BRIDGE_TOKEN_ENV: _TOKEN,
        CUA_MCP_BRIDGE_GENERATION_ENV: "backend-generation-1",
    }
    environ.update(overrides)
    return environ


def _fail_discovery(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("Electron bridge mode must never use Cua discovery or Popen")


def test_electron_bridge_configuration_repr_excludes_token() -> None:
    configuration = _CuaElectronBridgeConfiguration(
        host="127.0.0.1",
        port=43123,
        token=_TOKEN,
        generation="backend-generation-1",
    )

    rendered = repr(configuration)

    assert _TOKEN not in rendered
    assert "backend-generation-1" in rendered


@pytest.mark.parametrize(
    "response",
    [
        {"jsonrpc": "2.0", "id": True, "result": {}},
        {"id": 1, "result": {}},
        {"jsonrpc": "1.0", "id": 1, "result": {}},
    ],
    ids=("boolean-id", "missing-jsonrpc", "wrong-jsonrpc"),
)
def test_mcp_client_rejects_noncanonical_json_rpc_responses(
    response: Mapping[str, Any],
) -> None:
    transports: list[_ScriptedJsonLineTransport] = []

    def transport_factory() -> _ScriptedJsonLineTransport:
        transport = _ScriptedJsonLineTransport(response)
        transports.append(transport)
        return transport

    client = CuaMcpClient(
        command=("never-run-cua-driver", "mcp"),
        timeout=0.1,
        transport_factory=transport_factory,
    )
    try:
        with pytest.raises(CuaMcpProtocolError):
            client.initialize()
    finally:
        client.close()

    assert transports[0].sent[0]["id"] == 1
    assert transports[0].closed is True


def test_electron_bridge_is_lazy_authenticated_and_has_nonsecret_identity() -> None:
    bridge = _FakeElectronBridge()
    environ = _bridge_env(bridge)
    try:
        adapter = cua_background_provider_adapter_from_env(
            environ,
            run=_fail_discovery,
            which=_fail_discovery,
            path_exists=_fail_discovery,
            popen_factory=_fail_discovery,
            timeout=0.5,
        )

        assert adapter is not None
        assert bridge.wait_for_connection(0.05) is False
        assert adapter.client.transport_kind == "electron_bridge"
        assert adapter.client.command == ("electron-cua-mcp-bridge",)
        assert _TOKEN not in repr(adapter.client.transport_identity)
        assert _TOKEN not in repr(adapter.client.command)

        initialized = adapter.client.initialize()

        assert initialized["serverInfo"]["name"] == "fake-electron-cua"
        assert bridge.handshakes == [
            {
                "protocol": "oha-yachiyo-cua-mcp-bridge",
                "version": 1,
                "token": _TOKEN,
            }
        ]
        status = adapter.configured_status(probe_health=False)
        assert status["source"] == "cua_mcp_electron_bridge"
        assert status["transport"] == "electron_bridge"
        assert status["authentication_configured"] is True
        assert _TOKEN not in json.dumps(status, sort_keys=True)
        adapter.close()
    finally:
        bridge.close()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        (CUA_MCP_TRANSPORT_ENV, "stdio"),
        (CUA_MCP_BRIDGE_URL_ENV, "tcp://localhost:1234"),
        (CUA_MCP_BRIDGE_URL_ENV, "tcp://127.0.0.1:1234/path"),
        (CUA_MCP_BRIDGE_URL_ENV, "tcp://127.0.0.1:1234?query=1"),
        (CUA_MCP_BRIDGE_URL_ENV, "tcp://127.0.0.1:1234#fragment"),
        (CUA_MCP_BRIDGE_URL_ENV, "tcp://user@127.0.0.1:1234"),
        (CUA_MCP_BRIDGE_URL_ENV, "tcp://127.0.0.1:0"),
        (CUA_MCP_BRIDGE_URL_ENV, "tcp://127.0.0.1:65536"),
        (CUA_MCP_BRIDGE_TOKEN_ENV, "A" * 64),
        (CUA_MCP_BRIDGE_TOKEN_ENV, "a" * 63),
        (CUA_MCP_BRIDGE_GENERATION_ENV, ""),
        (CUA_MCP_BRIDGE_GENERATION_ENV, "generation contains spaces"),
    ],
)
def test_malformed_electron_bridge_config_fails_closed_without_discovery(
    key: str,
    value: str,
) -> None:
    bridge = _FakeElectronBridge()
    environ = _bridge_env(bridge, **{key: value})
    try:
        assert resolve_cua_mcp_command(
            environ,
            run=_fail_discovery,
            which=_fail_discovery,
            path_exists=_fail_discovery,
        ) is None
        assert cua_background_provider_adapter_from_env(
            environ,
            run=_fail_discovery,
            which=_fail_discovery,
            path_exists=_fail_discovery,
            popen_factory=_fail_discovery,
        ) is None

        status = cua_background_provider_status(
            environ,
            run=_fail_discovery,
            which=_fail_discovery,
            path_exists=_fail_discovery,
            popen_factory=_fail_discovery,
        )

        assert status["status"] == "electron_bridge_unavailable"
        assert status["health"]["status"] == "electron_bridge_unavailable"
        assert status["configured"] is True
        assert "cua_electron_bridge_unavailable" in status["blocking_conditions"]
        assert _TOKEN not in json.dumps(status, sort_keys=True)
        assert bridge.wait_for_connection(0.05) is False
    finally:
        bridge.close()


def test_electron_bridge_rejects_an_invalid_ack_without_leaking_token() -> None:
    bridge = _FakeElectronBridge(
        ack={
            "protocol": "wrong-protocol",
            "version": 1,
            "ok": True,
        }
    )
    try:
        adapter = cua_background_provider_adapter_from_env(
            _bridge_env(bridge),
            run=_fail_discovery,
            which=_fail_discovery,
            path_exists=_fail_discovery,
            popen_factory=_fail_discovery,
            timeout=0.5,
        )
        assert adapter is not None
        with pytest.raises(CuaMcpProtocolError) as raised:
            adapter.client.initialize()
        assert _TOKEN not in str(raised.value)
        adapter.close()
    finally:
        bridge.close()


def test_unreachable_configured_bridge_is_not_reported_as_not_installed() -> None:
    bridge = _FakeElectronBridge(token="b" * 64)
    try:
        status = cua_background_provider_status(
            _bridge_env(bridge),
            probe_health=True,
            refresh_health=True,
            run=_fail_discovery,
            which=_fail_discovery,
            path_exists=_fail_discovery,
            popen_factory=_fail_discovery,
            timeout=0.5,
        )

        assert status["configured"] is True
        assert status["status"] == "electron_bridge_unavailable"
        assert status["setup_state"] == "unavailable"
        assert status["health"]["status"] == "electron_bridge_unavailable"
        assert status["source"] == "cua_mcp_electron_bridge"
        assert "cua_electron_bridge_unavailable" in status["blocking_conditions"]
        assert _TOKEN not in json.dumps(status, sort_keys=True)
    finally:
        bridge.close()


def test_electron_bridge_client_reconnects_after_the_socket_closes() -> None:
    bridge = _FakeElectronBridge(drop_first_initialize=True)
    try:
        adapter = cua_background_provider_adapter_from_env(
            _bridge_env(bridge),
            run=_fail_discovery,
            which=_fail_discovery,
            path_exists=_fail_discovery,
            popen_factory=_fail_discovery,
            timeout=0.5,
        )
        assert adapter is not None
        with pytest.raises(CuaMcpTransportError):
            adapter.client.initialize()

        initialized = adapter.client.initialize()

        assert initialized["serverInfo"]["name"] == "fake-electron-cua"
        assert bridge.connection_count == 2
        adapter.close()
    finally:
        bridge.close()


def test_electron_bridge_health_cache_identity_excludes_token_and_uses_generation() -> None:
    identity_1 = (
        "electron-bridge-v1",
        "tcp://127.0.0.1:43123",
        "generation-1",
    )
    identity_2 = (*identity_1[:2], "generation-2")
    common = {
        "command": ("electron-cua-mcp-bridge",),
        "transport_kind": "electron_bridge",
        "popen_factory": _fail_discovery,
    }

    first = _cua_health_cache_key(
        environ={CUA_MCP_BRIDGE_TOKEN_ENV: "a" * 64},
        transport_identity=identity_1,
        **common,
    )
    rotated_token = _cua_health_cache_key(
        environ={CUA_MCP_BRIDGE_TOKEN_ENV: "b" * 64},
        transport_identity=identity_1,
        **common,
    )
    next_generation = _cua_health_cache_key(
        environ={CUA_MCP_BRIDGE_TOKEN_ENV: "b" * 64},
        transport_identity=identity_2,
        **common,
    )

    assert first == rotated_token
    assert first != next_generation
