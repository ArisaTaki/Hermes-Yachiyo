"""Background desktop execution through Cua Driver's line-JSON MCP server.

The adapter in this module is deliberately narrow: it only executes explicitly
mapped tools and always asks Cua Driver for background event delivery.  It never
falls back to the host's foreground mouse or keyboard path. Packaged builds use
an authenticated bridge to a driver spawned directly by Electron; development
builds may continue to launch a discovered MCP stdio process.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import queue
import re
import shlex
import shutil
import socket
import subprocess
import threading
import time
import unicodedata
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from apps.shell.agent.runtime.verification_receipts import (
    APP_WINDOW_PRESENT_PREDICATE,
    EXACT_TYPED_CONTENT_PRESENT_PREDICATE,
    RUNTIME_PRIVATE_VERIFICATION_AUTHORITY,
    RUNTIME_PRIVATE_VERIFICATION_CONTEXT_KEY,
    RUNTIME_PRIVATE_VERIFICATION_CONTEXT_VERSION,
)
from packages.security import scrubbed_subprocess_env

CUA_BACKGROUND_PROVIDER_KIND = "background_desktop"
CUA_BACKGROUND_PROVIDER_ID = "cua-driver"
CUA_MCP_PROTOCOL_VERSION = "2025-06-18"
CUA_TELEMETRY_ENV = "CUA_DRIVER_RS_TELEMETRY_ENABLED"
CUA_DRIVER_PATH_ENV = "OHA_YACHIYO_CUA_DRIVER_PATH"
CUA_DRIVER_COMMAND_ENV = "OHA_YACHIYO_CUA_DRIVER_COMMAND"
CUA_HOST_BUNDLE_ID_ENV = "OHA_YACHIYO_CUA_HOST_BUNDLE_ID"
CUA_MCP_TRANSPORT_ENV = "OHA_YACHIYO_CUA_MCP_TRANSPORT"
CUA_MCP_BRIDGE_URL_ENV = "OHA_YACHIYO_CUA_MCP_BRIDGE_URL"
CUA_MCP_BRIDGE_TOKEN_ENV = "OHA_YACHIYO_CUA_MCP_BRIDGE_TOKEN"
CUA_MCP_BRIDGE_GENERATION_ENV = "OHA_YACHIYO_CUA_MCP_BRIDGE_GENERATION"

_CUA_ELECTRON_BRIDGE_TRANSPORT = "electron-bridge-v1"
_CUA_ELECTRON_BRIDGE_PROTOCOL = "oha-yachiyo-cua-mcp-bridge"
_CUA_ELECTRON_BRIDGE_VERSION = 1
_CUA_ELECTRON_BRIDGE_URL_RE = re.compile(
    r"\Atcp://127\.0\.0\.1:([1-9][0-9]{0,4})\Z"
)
_CUA_ELECTRON_BRIDGE_TOKEN_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_CUA_ELECTRON_BRIDGE_GENERATION_RE = re.compile(
    r"\A[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z"
)
_CUA_ELECTRON_BRIDGE_MAX_ACK_LENGTH = 4 * 1024
_CUA_ELECTRON_BRIDGE_MAX_LINE_LENGTH = 8 * 1024 * 1024
_CUA_IDENTITY_PLACEHOLDERS = frozenset(
    {"?", "unknown", "<unknown>", "(unknown)", "n/a", "none", "null"}
)
_CUA_REACQUIRABLE_TARGET_ERRORS = frozenset(
    {
        "cua_background_target_identity_required",
        "cua_background_target_identity_mismatch",
    }
)

_COMMON_CUA_DRIVER_PATHS = (
    ".local/bin/cua-driver",
    ".cargo/bin/cua-driver",
)
_SYSTEM_CUA_DRIVER_PATHS = (
    "/opt/homebrew/bin/cua-driver",
    "/usr/local/bin/cua-driver",
    "/Applications/CuaDriver.app/Contents/MacOS/cua-driver",
)

DEFAULT_CUA_TOOL_NAME_MAP: dict[str, str] = {
    "app.open": "launch_app",
    "app.open_and_click_ui_element": "click",
    "app.open_and_safe_type_text": "type_text",
    "app.open_and_safe_shortcut": "hotkey",
    "app.open_and_safe_key": "press_key",
    "app.open_and_safe_scroll": "scroll",
    "app.open_and_type_into_ui_element": "type_text",
    "desktop.click_ui_element": "click",
    "desktop.active_window": "get_window_state",
    "desktop.inspect_app": "get_window_state",
    "desktop.list_windows": "get_window_state",
    "desktop.open_app": "launch_app",
    "desktop.list_apps": "list_apps",
    "desktop.read_ui": "get_window_state",
    "desktop.safe_key": "press_key",
    "desktop.safe_shortcut": "hotkey",
    "desktop.safe_type_text": "type_text",
    "desktop.safe_scroll": "scroll",
    "desktop.type_into_ui_element": "type_text",
    "desktop.ui_elements": "get_window_state",
    "desktop.verify": "get_window_state",
    "desktop.windows": "get_window_state",
}

_CUA_TARGET_BOUND_OBSERVATION_TOOLS = frozenset(
    {
        "desktop.active_window",
        "desktop.inspect_app",
        "desktop.list_windows",
        "desktop.read_ui",
        "desktop.ui_elements",
        "desktop.verify",
        "desktop.windows",
    }
)

_CUA_OPEN_COMPOSITE_TOOLS: dict[str, str] = {
    "app.open_and_click_ui_element": "desktop.click_ui_element",
    "app.open_and_safe_type_text": "desktop.safe_type_text",
    "app.open_and_safe_shortcut": "desktop.safe_shortcut",
    "app.open_and_safe_key": "desktop.safe_key",
    "app.open_and_safe_scroll": "desktop.safe_scroll",
    "app.open_and_type_into_ui_element": "desktop.type_into_ui_element",
}

_CUA_GROUNDED_ELEMENT_ACTION_TOOLS = {
    "desktop.click_ui_element",
    "desktop.type_into_ui_element",
}

_CUA_BACKGROUND_INPUT_TOOLS = {
    "click",
    "hotkey",
    "press_key",
    "scroll",
    "type_text",
}
_CUA_PID_TARGETED_TOOLS = {
    *_CUA_BACKGROUND_INPUT_TOOLS,
    "get_window_state",
}
_CUA_POINTER_TOOLS = {"click"}
_CUA_SNAPSHOT_VERIFICATION_TOOLS = {"hotkey", "press_key", "scroll"}
_RUNTIME_EXECUTION_SCOPE_KEY = "_runtime_execution_scope"
_RUNTIME_SCOPE_CONTEXT_KEYS = (
    "task_id",
    "workflow_run_id",
    "group_run_id",
    "execution_id",
    "session_id",
    "core_id",
    "plan_id",
)
_MAX_CACHED_TASK_TARGETS = 128
_TASK_TARGET_TTL_SECONDS = 5 * 60.0
_TASK_TARGET_WINDOW_RESOLUTION_TIMEOUT_SECONDS = 3.0
_TASK_TARGET_WINDOW_RESOLUTION_POLL_SECONDS = 0.1
_TASK_TARGET_WINDOW_MATERIALIZATION_RECOVERY_SECONDS = 30.0
_MAX_CUA_AX_WINDOW_VETTING_CANDIDATES = 8
_CUA_COMMAND_CACHE_TTL_SECONDS = 30.0
_CUA_HEALTH_CACHE_TTL_SECONDS = 5.0
_MAX_CUA_DISCOVERY_CACHE_ENTRIES = 32
_CUA_DISCOVERY_CACHE_LOCK = threading.RLock()
_CUA_COMMAND_CACHE: dict[
    tuple[Any, ...],
    tuple[float, tuple[str, ...]],
] = {}
_CUA_HEALTH_STATUS_CACHE: dict[
    tuple[Any, ...],
    tuple[float, dict[str, Any]],
] = {}

# Cua's manifest is used as the final intersection, but it is not allowed to
# turn arbitrary Oha planner fields into MCP arguments.  This small allowlist
# describes only the public Cua parameters this adapter knows how to preserve.
_CUA_OFFICIAL_ARGUMENTS: dict[str, frozenset[str]] = {
    "launch_app": frozenset(
        {
            "bundle_id",
            "creates_new_application_instance",
            "launch_path",
            "name",
            "urls",
            "webkit_inspector_port",
        }
    ),
    "list_apps": frozenset(),
    "list_windows": frozenset({"pid", "on_screen_only"}),
    "get_window_state": frozenset({"pid", "window_id"}),
    "click": frozenset(
        {
            "button",
            "delivery_mode",
            "element_index",
            "element_token",
            "from_zoom",
            "modifier",
            "pid",
            "window_id",
            "x",
            "y",
        }
    ),
    "type_text": frozenset(
        {
            "delay_ms",
            "delivery_mode",
            "element_index",
            "element_token",
            "pid",
            "text",
            "window_id",
            "x",
            "y",
        }
    ),
    "press_key": frozenset(
        {
            "delivery_mode",
            "element_index",
            "element_token",
            "key",
            "modifiers",
            "pid",
            "window_id",
            "x",
            "y",
        }
    ),
    "hotkey": frozenset(
        {
            # Current Cua uses ``keys``.  ``key`` + ``modifiers`` are retained
            # only when an installed driver's own schema advertises the older
            # public shape.
            "delivery_mode",
            "key",
            "keys",
            "modifiers",
            "pid",
            "window_id",
            "x",
            "y",
        }
    ),
    "scroll": frozenset(
        {
            "amount",
            "by",
            "delivery_mode",
            "direction",
            "element_index",
            "element_token",
            "pid",
            "window_id",
            "x",
            "y",
        }
    ),
}

_SAFE_KEY_ARGUMENTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "escape": ("escape", ()),
    "tab": ("tab", ()),
    "shift_tab": ("tab", ("shift",)),
    "arrow_up": ("up", ()),
    "arrow_down": ("down", ()),
    "arrow_left": ("left", ()),
    "arrow_right": ("right", ()),
    "home": ("home", ()),
    "end": ("end", ()),
    "page_up": ("pageup", ()),
    "page_down": ("pagedown", ()),
}

# Only app-local shortcuts are mapped.  Global actions such as Mission Control,
# app switching, Spotlight, screenshots, and screen locking cannot truthfully be
# delivered to one background pid and therefore remain fail-closed.
_SAFE_SHORTCUT_KEYS: dict[str, tuple[str, ...]] = {
    "copy": ("cmd", "c"),
    "paste": ("cmd", "v"),
    "select_all": ("cmd", "a"),
    "undo": ("cmd", "z"),
    "redo": ("cmd", "shift", "z"),
    "find": ("cmd", "f"),
    "focus_address_bar": ("cmd", "l"),
    "new_tab": ("cmd", "t"),
    "new_private_window": ("cmd", "shift", "n"),
    "close_tab": ("cmd", "w"),
    "next_tab": ("cmd", "shift", "]"),
    "previous_tab": ("cmd", "shift", "["),
    "next_window": ("cmd", "`"),
    "previous_window": ("cmd", "shift", "`"),
    "new_window": ("cmd", "n"),
    "new_document": ("cmd", "n"),
    "new_message": ("cmd", "n"),
    "new_folder": ("cmd", "shift", "n"),
    "rename_selected": ("return",),
    "parent_folder": ("cmd", "up"),
    "finder_get_info": ("cmd", "i"),
    "finder_airdrop": ("cmd", "shift", "r"),
    "finder_network": ("cmd", "shift", "k"),
    "finder_recents": ("cmd", "shift", "f"),
    "new_note": ("cmd", "n"),
    "new_task": ("cmd", "n"),
    "new_reminder": ("cmd", "n"),
    "new_event": ("cmd", "n"),
    "refresh": ("cmd", "r"),
    "bookmark_page": ("cmd", "d"),
    "show_history": ("cmd", "y"),
    "open_devtools": ("cmd", "option", "i"),
    "command_palette": ("cmd", "shift", "p"),
    "obsidian_command_palette": ("cmd", "p"),
    "preferences": ("cmd", ","),
    "zoom_in": ("cmd", "+"),
    "zoom_out": ("cmd", "-"),
    "reset_zoom": ("cmd", "0"),
    "browser_back": ("cmd", "["),
    "browser_forward": ("cmd", "]"),
    "reopen_closed_tab": ("cmd", "shift", "t"),
    "finder_quick_look": ("space",),
}

# These app-local shortcuts can materialize the first controllable window for
# an already-running document-style application.  They remain a deliberately
# small semantic allowlist: data mutations such as ``new_folder`` and ordinary
# shortcuts such as copy/paste must still prove their own postconditions.
_WINDOW_MATERIALIZATION_SHORTCUT_ACTIONS = frozenset(
    {
        "new_document",
        # Notes uses Cmd-N to materialize its first editable content surface;
        # this remains only a dispatched receipt until the later observation.
        "new_note",
        "new_window",
    }
)

_FOREGROUND_ONLY_TOOL_NAMES = {
    "bring_to_front",
    "foreground",
}


class CuaMcpError(RuntimeError):
    """Base class for Cua Driver MCP failures."""


class CuaMcpTransportError(CuaMcpError):
    """The MCP child process or its stdio transport failed."""


class CuaMcpTimeoutError(CuaMcpTransportError, TimeoutError):
    """An MCP response was not received within the configured deadline."""


class CuaMcpProtocolError(CuaMcpError):
    """The peer sent malformed or unexpected JSON-RPC data."""


class CuaMcpRemoteError(CuaMcpError):
    """The MCP peer returned a JSON-RPC error object."""

    def __init__(self, message: str, *, code: Any = None, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


class CuaMcpToolError(CuaMcpError):
    """A tools/call response explicitly reported ``isError``."""

    def __init__(self, message: str, *, result: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.result = dict(result)


class _CuaElectronBridgeConfigurationError(ValueError):
    """The Electron bridge sentinel was present but its contract was invalid."""


@dataclass(frozen=True)
class _CuaElectronBridgeConfiguration:
    host: str
    port: int
    token: str = field(repr=False)
    generation: str

    @property
    def url(self) -> str:
        return f"tcp://{self.host}:{self.port}"

    @property
    def transport_identity(self) -> tuple[str, str, str]:
        # The authentication token is deliberately absent. Electron rotates
        # generation whenever a new backend/bridge instance is created.
        return (_CUA_ELECTRON_BRIDGE_TRANSPORT, self.url, self.generation)


class _JsonLineTransport(Protocol):
    def send(self, payload: Mapping[str, Any]) -> None:
        ...

    def receive(self, timeout: float) -> dict[str, Any]:
        ...

    def close(self) -> None:
        ...


class _CuaMcpStdioTransport:
    """A long-lived, line-delimited JSON transport over a child process."""

    def __init__(
        self,
        *,
        command: Sequence[str],
        environ: Mapping[str, str],
        popen_factory: Callable[..., Any],
    ) -> None:
        self.command = tuple(command)
        self.environ = dict(environ)
        self._popen_factory = popen_factory
        self._process: Any | None = None
        self._messages: queue.Queue[object] = queue.Queue()
        self._start_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._closed = False
        self._stderr_tail: deque[str] = deque(maxlen=20)

    def send(self, payload: Mapping[str, Any]) -> None:
        self._start()
        encoded = json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"))
        with self._write_lock:
            process = self._process
            if process is None or process.poll() is not None:
                raise CuaMcpTransportError("Cua Driver MCP process is not running")
            stdin = getattr(process, "stdin", None)
            if stdin is None:
                raise CuaMcpTransportError("Cua Driver MCP stdin is unavailable")
            try:
                stdin.write(encoded + "\n")
                stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                raise CuaMcpTransportError(
                    "Failed to write to Cua Driver MCP stdin"
                ) from exc

    def receive(self, timeout: float) -> dict[str, Any]:
        try:
            item = self._messages.get(timeout=max(0.0, timeout))
        except queue.Empty as exc:
            raise CuaMcpTimeoutError("Timed out waiting for Cua Driver MCP") from exc
        if isinstance(item, BaseException):
            raise item
        if not isinstance(item, Mapping):
            raise CuaMcpProtocolError("Cua Driver MCP emitted a non-object message")
        return dict(item)

    def close(self) -> None:
        with self._start_lock:
            if self._closed:
                return
            self._closed = True
            process = self._process
            self._process = None
        if process is None:
            return
        stdin = getattr(process, "stdin", None)
        if stdin is not None:
            try:
                stdin.close()
            except (OSError, ValueError):
                pass
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=1.0)
        except Exception:
            try:
                process.kill()
                process.wait(timeout=1.0)
            except Exception:
                pass

    def _start(self) -> None:
        with self._start_lock:
            if self._closed:
                raise CuaMcpTransportError("Cua Driver MCP transport is closed")
            if self._process is not None:
                if self._process.poll() is not None:
                    raise CuaMcpTransportError(
                        "Cua Driver MCP process exited unexpectedly"
                    )
                return
            try:
                process = self._popen_factory(
                    list(self.command),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    env=self.environ,
                )
            except (OSError, ValueError) as exc:
                raise CuaMcpTransportError(
                    "Unable to start Cua Driver MCP process"
                ) from exc
            if getattr(process, "stdin", None) is None or getattr(
                process, "stdout", None
            ) is None:
                try:
                    process.terminate()
                except Exception:
                    pass
                raise CuaMcpTransportError(
                    "Cua Driver MCP process did not expose stdio pipes"
                )
            self._process = process
            threading.Thread(
                target=self._read_stdout,
                args=(process,),
                name="cua-mcp-stdout",
                daemon=True,
            ).start()
            if getattr(process, "stderr", None) is not None:
                threading.Thread(
                    target=self._drain_stderr,
                    args=(process,),
                    name="cua-mcp-stderr",
                    daemon=True,
                ).start()

    def _read_stdout(self, process: Any) -> None:
        stdout = process.stdout
        try:
            while True:
                line = stdout.readline()
                if line == "":
                    break
                line = str(line).strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except (TypeError, ValueError):
                    self._messages.put(
                        CuaMcpProtocolError("Cua Driver MCP emitted invalid JSON")
                    )
                    continue
                if not isinstance(message, Mapping):
                    self._messages.put(
                        CuaMcpProtocolError(
                            "Cua Driver MCP emitted a non-object JSON message"
                        )
                    )
                    continue
                self._messages.put(dict(message))
        except (OSError, ValueError):
            if not self._closed:
                self._messages.put(
                    CuaMcpTransportError("Failed to read Cua Driver MCP stdout")
                )
        finally:
            if not self._closed:
                returncode = process.poll()
                suffix = f" (exit code {returncode})" if returncode is not None else ""
                self._messages.put(
                    CuaMcpTransportError(
                        f"Cua Driver MCP stdout closed unexpectedly{suffix}"
                    )
                )

    def _drain_stderr(self, process: Any) -> None:
        stderr = process.stderr
        try:
            while True:
                line = stderr.readline()
                if line == "":
                    return
                clean_line = str(line).strip()
                if clean_line:
                    self._stderr_tail.append(clean_line)
        except (OSError, ValueError):
            return


class _CuaMcpElectronBridgeTransport:
    """Authenticated line-JSON MCP transport to an Electron-owned child."""

    def __init__(
        self,
        *,
        configuration: _CuaElectronBridgeConfiguration,
        connect_timeout: float,
        connection_factory: Callable[..., socket.socket] = socket.create_connection,
    ) -> None:
        self._configuration = configuration
        self._connect_timeout = max(0.05, float(connect_timeout))
        self._connection_factory = connection_factory
        self._socket: socket.socket | None = None
        self._reader: Any | None = None
        self._messages: queue.Queue[object] = queue.Queue()
        self._start_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._closed = False

    def send(self, payload: Mapping[str, Any]) -> None:
        self._start()
        encoded = (
            json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        with self._write_lock:
            connection = self._socket
            if connection is None:
                raise CuaMcpTransportError(
                    "Electron Cua MCP bridge is unavailable"
                )
            try:
                connection.sendall(encoded)
            except (OSError, ValueError) as exc:
                raise CuaMcpTransportError(
                    "Failed to write to Electron Cua MCP bridge"
                ) from exc

    def receive(self, timeout: float) -> dict[str, Any]:
        try:
            item = self._messages.get(timeout=max(0.0, timeout))
        except queue.Empty as exc:
            raise CuaMcpTimeoutError(
                "Timed out waiting for Electron Cua MCP bridge"
            ) from exc
        if isinstance(item, BaseException):
            raise item
        if not isinstance(item, Mapping):
            raise CuaMcpProtocolError(
                "Electron Cua MCP bridge emitted a non-object message"
            )
        return dict(item)

    def close(self) -> None:
        with self._start_lock:
            if self._closed:
                return
            self._closed = True
            connection = self._socket
            reader = self._reader
            self._socket = None
            self._reader = None
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if reader is not None:
            try:
                reader.close()
            except (OSError, ValueError):
                pass
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass

    def _start(self) -> None:
        with self._start_lock:
            if self._closed:
                raise CuaMcpTransportError(
                    "Electron Cua MCP bridge transport is closed"
                )
            if self._socket is not None:
                return
            connection: socket.socket | None = None
            reader: Any | None = None
            try:
                connection = self._connection_factory(
                    (self._configuration.host, self._configuration.port),
                    timeout=self._connect_timeout,
                )
                connection.settimeout(self._connect_timeout)
                reader = connection.makefile("r", encoding="utf-8", newline="\n")
                handshake = {
                    "protocol": _CUA_ELECTRON_BRIDGE_PROTOCOL,
                    "version": _CUA_ELECTRON_BRIDGE_VERSION,
                    "token": self._configuration.token,
                }
                connection.sendall(
                    (
                        json.dumps(handshake, separators=(",", ":"))
                        + "\n"
                    ).encode("utf-8")
                )
                acknowledgement = self._read_handshake_ack(reader)
                if (
                    acknowledgement.get("protocol")
                    != _CUA_ELECTRON_BRIDGE_PROTOCOL
                    or type(acknowledgement.get("version")) is not int
                    or acknowledgement.get("version")
                    != _CUA_ELECTRON_BRIDGE_VERSION
                    or acknowledgement.get("ok") is not True
                ):
                    raise CuaMcpProtocolError(
                        "Electron Cua MCP bridge returned an invalid acknowledgement"
                    )
                connection.settimeout(None)
                self._socket = connection
                self._reader = reader
                threading.Thread(
                    target=self._read_messages,
                    args=(reader,),
                    name="cua-mcp-electron-bridge",
                    daemon=True,
                ).start()
            except (CuaMcpProtocolError, CuaMcpTransportError):
                self._close_unstarted(connection, reader)
                raise
            except (OSError, TimeoutError, TypeError, ValueError) as exc:
                self._close_unstarted(connection, reader)
                raise CuaMcpTransportError(
                    "Electron Cua MCP bridge is unavailable"
                ) from exc

    def _read_handshake_ack(self, reader: Any) -> dict[str, Any]:
        try:
            line = reader.readline(_CUA_ELECTRON_BRIDGE_MAX_ACK_LENGTH + 1)
        except (OSError, TimeoutError, ValueError) as exc:
            raise CuaMcpTransportError(
                "Electron Cua MCP bridge acknowledgement was unavailable"
            ) from exc
        if (
            not line
            or len(line) > _CUA_ELECTRON_BRIDGE_MAX_ACK_LENGTH
            or not line.endswith("\n")
        ):
            raise CuaMcpProtocolError(
                "Electron Cua MCP bridge returned an invalid acknowledgement"
            )
        try:
            acknowledgement = json.loads(line)
        except (TypeError, ValueError) as exc:
            raise CuaMcpProtocolError(
                "Electron Cua MCP bridge returned an invalid acknowledgement"
            ) from exc
        if not isinstance(acknowledgement, Mapping):
            raise CuaMcpProtocolError(
                "Electron Cua MCP bridge returned an invalid acknowledgement"
            )
        return dict(acknowledgement)

    def _read_messages(self, reader: Any) -> None:
        try:
            while True:
                line = reader.readline(_CUA_ELECTRON_BRIDGE_MAX_LINE_LENGTH + 1)
                if line == "":
                    break
                if (
                    len(line) > _CUA_ELECTRON_BRIDGE_MAX_LINE_LENGTH
                    or not line.endswith("\n")
                ):
                    self._messages.put(
                        CuaMcpProtocolError(
                            "Electron Cua MCP bridge emitted an oversized message"
                        )
                    )
                    break
                if not line.strip():
                    continue
                try:
                    message = json.loads(line)
                except (TypeError, ValueError):
                    self._messages.put(
                        CuaMcpProtocolError(
                            "Electron Cua MCP bridge emitted invalid JSON"
                        )
                    )
                    continue
                if not isinstance(message, Mapping):
                    self._messages.put(
                        CuaMcpProtocolError(
                            "Electron Cua MCP bridge emitted a non-object JSON message"
                        )
                    )
                    continue
                self._messages.put(dict(message))
        except (OSError, TimeoutError, ValueError):
            if not self._closed:
                self._messages.put(
                    CuaMcpTransportError(
                        "Failed to read from Electron Cua MCP bridge"
                    )
                )
        finally:
            if not self._closed:
                self._messages.put(
                    CuaMcpTransportError(
                        "Electron Cua MCP bridge closed unexpectedly"
                    )
                )

    @staticmethod
    def _close_unstarted(connection: socket.socket | None, reader: Any | None) -> None:
        if reader is not None:
            try:
                reader.close()
            except (OSError, ValueError):
                pass
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass


class CuaMcpClient:
    """Minimal MCP client for a long-running ``cua-driver mcp`` process."""

    def __init__(
        self,
        command: Sequence[str] | str = ("cua-driver", "mcp"),
        *,
        environ: Mapping[str, str] | None = None,
        timeout: float = 20.0,
        popen_factory: Callable[..., Any] = subprocess.Popen,
        transport_factory: Callable[[], _JsonLineTransport] | None = None,
        transport_kind: str = "mcp_stdio",
        transport_identity: Sequence[str] | str | None = None,
    ) -> None:
        parsed_command = (
            tuple(shlex.split(command)) if isinstance(command, str) else tuple(command)
        )
        if not parsed_command or not all(str(part).strip() for part in parsed_command):
            raise ValueError("Cua MCP command must not be empty")
        self.command = tuple(str(part) for part in parsed_command)
        clean_transport_kind = str(transport_kind or "").strip()
        if not clean_transport_kind:
            raise ValueError("Cua MCP transport kind must not be empty")
        parsed_transport_identity = (
            (str(transport_identity),)
            if isinstance(transport_identity, str)
            else tuple(str(part) for part in (transport_identity or self.command))
        )
        if not parsed_transport_identity or not all(
            part.strip() for part in parsed_transport_identity
        ):
            raise ValueError("Cua MCP transport identity must not be empty")
        self.transport_kind = clean_transport_kind
        self.transport_identity = parsed_transport_identity
        self.timeout = max(0.05, float(timeout))
        explicit_environ = {
            str(key): str(value) for key, value in (environ or {}).items()
        }
        process_environ = _cua_subprocess_environ(explicit_environ)
        self.environ = process_environ
        self._transport_factory = transport_factory or (
            lambda: _CuaMcpStdioTransport(
                command=self.command,
                environ=self.environ,
                popen_factory=popen_factory,
            )
        )
        self._transport = self._transport_factory()
        self._rpc_lock = threading.RLock()
        self._next_request_id = 1
        self._initialize_result: dict[str, Any] | None = None
        self._tools_cache: tuple[dict[str, Any], ...] | None = None
        self._closed = False

    def initialize(self) -> dict[str, Any]:
        with self._rpc_lock:
            try:
                return dict(self._ensure_initialized_locked())
            except (CuaMcpTransportError, CuaMcpProtocolError):
                self._invalidate_transport_locked()
                raise

    def list_tools(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        with self._rpc_lock:
            try:
                self._ensure_initialized_locked()
                if self._tools_cache is not None and not refresh:
                    return [dict(tool) for tool in self._tools_cache]
                result = self._request_locked("tools/list", {})
                if not isinstance(result, Mapping) or not isinstance(
                    result.get("tools"), list
                ):
                    raise CuaMcpProtocolError(
                        "Cua Driver tools/list result did not contain a tools array"
                    )
                tools: list[dict[str, Any]] = []
                for item in result["tools"]:
                    if not isinstance(item, Mapping) or not str(item.get("name") or ""):
                        raise CuaMcpProtocolError(
                            "Cua Driver tools/list contained an invalid tool definition"
                        )
                    tools.append(dict(item))
                self._tools_cache = tuple(tools)
                return [dict(tool) for tool in tools]
            except (CuaMcpTransportError, CuaMcpProtocolError):
                self._invalidate_transport_locked()
                raise

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("Cua MCP tool name must not be empty")
        with self._rpc_lock:
            try:
                self._ensure_initialized_locked()
                result = self._request_locked(
                    "tools/call",
                    {"name": clean_name, "arguments": dict(arguments or {})},
                )
                if not isinstance(result, Mapping):
                    raise CuaMcpProtocolError(
                        "Cua Driver tools/call returned a non-object result"
                    )
                tool_result = dict(result)
                if tool_result.get("isError") is True:
                    raise CuaMcpToolError(
                        _mcp_result_message(tool_result)
                        or f"Cua tool {clean_name} failed",
                        result=tool_result,
                    )
                return tool_result
            except (CuaMcpTransportError, CuaMcpProtocolError):
                self._invalidate_transport_locked()
                raise

    def close(self) -> None:
        with self._rpc_lock:
            if self._closed:
                return
            self._closed = True
            self._initialize_result = None
            self._tools_cache = None
            self._transport.close()

    def __enter__(self) -> CuaMcpClient:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def _ensure_initialized_locked(self) -> dict[str, Any]:
        if self._closed:
            raise CuaMcpTransportError("Cua MCP client is closed")
        if self._initialize_result is not None:
            return self._initialize_result
        result = self._request_locked(
            "initialize",
            {
                "protocolVersion": CUA_MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "oha-yachiyo",
                    "version": "0.4.0",
                },
            },
        )
        if not isinstance(result, Mapping):
            raise CuaMcpProtocolError(
                "Cua Driver initialize returned a non-object result"
            )
        self._transport.send(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            }
        )
        self._initialize_result = dict(result)
        return self._initialize_result

    def _invalidate_transport_locked(self) -> None:
        stale_transport = self._transport
        self._initialize_result = None
        self._tools_cache = None
        try:
            stale_transport.close()
        finally:
            if not self._closed:
                self._transport = self._transport_factory()

    def _request_locked(self, method: str, params: Mapping[str, Any]) -> Any:
        if self._closed:
            raise CuaMcpTransportError("Cua MCP client is closed")
        request_id = self._next_request_id
        self._next_request_id += 1
        self._transport.send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": dict(params),
            }
        )
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CuaMcpTimeoutError(
                    f"Timed out waiting for Cua MCP response to {method}"
                )
            message = self._transport.receive(remaining)
            if "id" not in message:
                # Server notifications are allowed to interleave with responses.
                if (
                    message.get("jsonrpc") != "2.0"
                    or not isinstance(message.get("method"), str)
                    or not str(message.get("method") or "").strip()
                ):
                    raise CuaMcpProtocolError(
                        "Cua Driver MCP emitted an invalid notification"
                    )
                continue
            if type(message.get("id")) is not int or message.get("id") != request_id:
                raise CuaMcpProtocolError(
                    "Cua Driver MCP response id did not match the request"
                )
            if message.get("jsonrpc") != "2.0":
                raise CuaMcpProtocolError(
                    "Cua Driver MCP response used an unsupported JSON-RPC version"
                )
            has_error = "error" in message
            has_result = "result" in message
            if has_error == has_result:
                raise CuaMcpProtocolError(
                    "Cua Driver MCP response must contain exactly one result or error"
                )
            remote_error = message.get("error")
            if has_error and not isinstance(remote_error, Mapping):
                raise CuaMcpProtocolError(
                    "Cua Driver MCP response contained an invalid error"
                )
            if isinstance(remote_error, Mapping):
                raise CuaMcpRemoteError(
                    str(remote_error.get("message") or "Cua Driver MCP request failed"),
                    code=remote_error.get("code"),
                    data=remote_error.get("data"),
                )
            return message.get("result")


class CuaBackgroundDesktopExecutionProviderAdapter:
    """Desktop provider adapter that only uses Cua's background delivery path."""

    provider_kind = CUA_BACKGROUND_PROVIDER_KIND
    delivery_mode = "background"

    def __init__(
        self,
        client: CuaMcpClient,
        *,
        provider_id: str = CUA_BACKGROUND_PROVIDER_ID,
        supported_tools: Iterable[str] | None = None,
        tool_name_map: Mapping[str, str] | None = None,
    ) -> None:
        self.client = client
        self.provider_id = str(provider_id or CUA_BACKGROUND_PROVIDER_ID).strip()
        self.tool_name_map = dict(DEFAULT_CUA_TOOL_NAME_MAP)
        if tool_name_map is not None:
            self.tool_name_map.update(
                {
                    str(source).strip(): str(target).strip()
                    for source, target in tool_name_map.items()
                    if str(source).strip() and str(target).strip()
                }
            )
        self.supported_tools = _string_list(supported_tools) or list(
            self.tool_name_map
        )
        self._execution_lock = threading.RLock()
        self._target_lock = threading.RLock()
        self._task_targets: dict[str, dict[str, Any]] = {}
        # Provider affinity outlives the short-lived target snapshot.  A
        # transport/schema/identity failure may revoke the cached pid, but it
        # must never make the same trusted runtime scope silently eligible for
        # the user's local foreground broker.  Affinity is released only by an
        # explicit scope finalizer (or adapter shutdown).
        self._owned_task_scopes: set[str] = set()

    def owns_task_scope(self, tool_request: Mapping[str, Any]) -> bool:
        """Return whether this adapter is authoritative for a runtime scope.

        The scope key is derived exclusively from the executor-injected private
        runtime envelope.  Model-authored run/task ids therefore cannot pin a
        provider or claim authority over an existing process.
        """

        task_scope = _trusted_task_scope_key(tool_request)
        if not task_scope:
            return False
        with self._target_lock:
            return task_scope in self._owned_task_scopes

    def end_task_scope(self, tool_request: Mapping[str, Any]) -> None:
        """Release in-memory authority when the owning runtime finalizes."""

        task_scope = _trusted_task_scope_key(tool_request)
        if not task_scope:
            return
        with self._target_lock:
            self._task_targets.pop(task_scope, None)
            self._owned_task_scopes.discard(task_scope)

    def can_execute(
        self,
        tool_name: str,
        route: Mapping[str, Any],
        tool_request: Mapping[str, Any],
    ) -> bool:
        selected_provider_id = str(route.get("selected_provider_id") or "").strip()
        if selected_provider_id and selected_provider_id != self.provider_id:
            return False
        if _is_foreground_only_tool(tool_name):
            return False
        if tool_name not in self.supported_tools or tool_name not in self.tool_name_map:
            return False
        provider_supported_tools = _provider_supported_tools(tool_request)
        if (
            not self.owns_task_scope(tool_request)
            and provider_supported_tools
            and tool_name not in provider_supported_tools
        ):
            return False
        try:
            remote_tools = {
                str(tool.get("name") or ""): tool
                for tool in self.client.list_tools()
            }
        except (CuaMcpError, OSError):
            return False
        if not _cua_logical_tool_contract_supported(
            tool_name,
            self.tool_name_map[tool_name],
            remote_tools,
        ):
            return False
        return True

    def execute(
        self,
        tool_name: str,
        payload: Mapping[str, Any],
        *,
        tool_request: Mapping[str, Any],
        route: Mapping[str, Any],
        broker: Any,
        approved: bool = False,
    ) -> dict[str, Any]:
        # The MCP transport is request/response serial today.  Keeping target
        # resolution, the remote call, and the cache update in the same order
        # prevents a concurrent launch from changing a task's pid between
        # argument construction and dispatch.
        with self._execution_lock:
            return self._execute_locked(
                tool_name,
                payload,
                tool_request=tool_request,
                route=route,
                broker=broker,
                approved=approved,
            )

    def _execute_locked(
        self,
        tool_name: str,
        payload: Mapping[str, Any],
        *,
        tool_request: Mapping[str, Any],
        route: Mapping[str, Any],
        broker: Any,
        approved: bool = False,
        _internal_composite_step: bool = False,
    ) -> dict[str, Any]:
        if _is_foreground_only_tool(tool_name) or _requests_foreground_takeover(
            payload, route
        ):
            return self._failure(
                tool_name,
                status="foreground_delivery_forbidden",
                error="cua_foreground_delivery_forbidden",
                summary="Background desktop provider refused foreground takeover.",
                blocking_condition="desktop_foreground_takeover_forbidden",
                retryable=False,
            )
        cua_tool_name = str(self.tool_name_map.get(tool_name) or "").strip()
        if (
            tool_name not in self.supported_tools
            and not _internal_composite_step
        ) or not cua_tool_name:
            return self._failure(
                tool_name,
                status="provider_tool_unavailable",
                error="cua_mcp_tool_unmapped",
                summary="This desktop action is not mapped to a Cua background tool.",
                blocking_condition="desktop_execution_provider_tool_unavailable",
                retryable=False,
            )
        provider_supported_tools = _provider_supported_tools(tool_request)
        if (
            not self.owns_task_scope(tool_request)
            and provider_supported_tools
            and tool_name not in provider_supported_tools
        ):
            return self._failure(
                tool_name,
                status="provider_tool_unavailable",
                error="cua_mcp_tool_not_allowed",
                summary="The selected provider does not allow this desktop action.",
                blocking_condition="desktop_execution_provider_tool_unavailable",
                retryable=False,
            )
        if tool_name in _CUA_OPEN_COMPOSITE_TOOLS:
            return self._execute_open_composite_locked(
                tool_name,
                payload,
                tool_request=tool_request,
                route=route,
                broker=broker,
                approved=approved,
            )
        del broker, approved
        task_scope = _trusted_task_scope_key(tool_request)
        previous_launch_target: dict[str, Any] = {}
        preexisting_launch_pids: set[int] | None = None
        preflight_launch_identity: dict[str, Any] = {}
        pre_action_snapshot: dict[str, Any] | None = None
        snapshot_target_arguments: dict[str, Any] = {}
        grounded_element: dict[str, Any] = {}
        try:
            remote_tools = {
                str(tool.get("name") or ""): tool for tool in self.client.list_tools()
            }
            if cua_tool_name not in remote_tools:
                return self._failure(
                    tool_name,
                    status="provider_tool_unavailable",
                    error="cua_mcp_tool_unavailable",
                    summary="Cua Driver does not expose the required background tool.",
                    blocking_condition="desktop_execution_provider_tool_unavailable",
                    retryable=False,
                    cua_tool_name=cua_tool_name,
                )
            if cua_tool_name == "launch_app" and "list_apps" not in remote_tools:
                return self._failure(
                    tool_name,
                    status="provider_tool_unavailable",
                    error="cua_mcp_tool_dependency_unavailable",
                    summary=(
                        "Cua Driver does not expose required background "
                        "dependency: list_apps"
                    ),
                    blocking_condition="desktop_execution_provider_tool_unavailable",
                    retryable=False,
                    cua_tool_name=cua_tool_name,
                )
            if cua_tool_name == "launch_app" and not (
                _background_launch_contract_supported(remote_tools.get("launch_app"))
            ):
                return self._failure(
                    tool_name,
                    status="provider_tool_unavailable",
                    error="cua_background_launch_contract_unavailable",
                    summary=(
                        "Cua Driver cannot prove that launch_app creates a "
                        "separate background application instance."
                    ),
                    blocking_condition="desktop_execution_provider_tool_unavailable",
                    retryable=False,
                    cua_tool_name=cua_tool_name,
                )
            if payload.get("bring_to_front") is True:
                return self._failure(
                    tool_name,
                    status="foreground_delivery_forbidden",
                    error="cua_foreground_delivery_forbidden",
                    summary="Background desktop provider refused foreground takeover.",
                    blocking_condition="desktop_foreground_takeover_forbidden",
                    retryable=False,
                    cua_tool_name=cua_tool_name,
                )
            if cua_tool_name == "launch_app" and task_scope:
                previous_launch_target = self._task_target_record(task_scope)
                if _cached_target_matches_launch_request(
                    previous_launch_target,
                    payload,
                ):
                    identity_failure = self._verified_task_target_identity(
                        tool_name,
                        cua_tool_name,
                        task_scope=task_scope,
                        remote_tools=remote_tools,
                    )
                    if identity_failure is None:
                        if _positive_int(
                            previous_launch_target.get("window_id")
                        ) is None and "list_windows" in remote_tools:
                            window_resolution_failure = (
                                self._resolve_task_target_window(
                                    tool_name,
                                    cua_tool_name,
                                    task_scope=task_scope,
                                    remote_tools=remote_tools,
                                )
                            )
                            if window_resolution_failure is not None:
                                return window_resolution_failure
                            previous_launch_target = self._task_target_record(
                                task_scope
                            )
                        # Reuse the run-owned background instance on planner
                        # retries/recovery.  Re-launching with Cua's mandatory
                        # new-instance flag would otherwise leak hidden apps.
                        self._remember_task_target(task_scope, {})
                        app_name = str(
                            payload.get("app_name")
                            or payload.get("name")
                            or next(
                                iter(
                                    _string_list(
                                        previous_launch_target.get("app_names")
                                    )
                                ),
                                "",
                            )
                        ).strip()
                        reused_data = {
                            "app_name": app_name,
                            "pid": _positive_int(previous_launch_target.get("pid")),
                            "window_id": _positive_int(
                                previous_launch_target.get("window_id")
                            ),
                            "agent_owned_target": True,
                            "background_target": True,
                            "launch_reused": True,
                            "launch_verified": True,
                            "self_activation_suppressed": True,
                        }
                        return {
                            "ok": True,
                            "tool": tool_name,
                            "action": tool_name,
                            "status": "background_target_reused",
                            "summary": (
                                f"Reused the agent-owned background {app_name} instance."
                                if app_name
                                else "Reused the agent-owned background application instance."
                            ),
                            "data": reused_data,
                            **reused_data,
                            "desktop_execution_provider_transport": (
                                self._transport_metadata(cua_tool_name=cua_tool_name)
                            ),
                        }
                    # The cached process disappeared or changed identity.  The
                    # verifier has already revoked it; continue with a fresh,
                    # separately-owned launch rather than reusing stale state.
                    previous_launch_target = {}
                # A new launch supersedes the task's previous target.  Clear it
                # before dispatch so a failed or pid-less launch can never make
                # the next input action hit the earlier app.
                self._forget_task_target(task_scope)
            if cua_tool_name == "launch_app" and "list_apps" in remote_tools:
                baseline_result = self.client.call_tool("list_apps", {})
                preexisting_launch_pids = _cua_running_app_pids(baseline_result)
                preflight_launch_identity = _cua_launch_identity_from_list_apps(
                    baseline_result,
                    payload,
                )
            target_identity_preverified = False
            cached_target = self._task_target_record(task_scope)
            cached_pid = _positive_int(cached_target.get("pid"))
            if (
                cua_tool_name in _CUA_PID_TARGETED_TOOLS
                and task_scope
                and cached_pid is not None
                and _positive_int(cached_target.get("window_id")) is None
                and "window_id"
                in _missing_cua_required_arguments(
                    remote_tools[cua_tool_name],
                    {"pid": cached_pid},
                )
            ):
                identity_failure = self._verified_task_target_identity(
                    tool_name,
                    cua_tool_name,
                    task_scope=task_scope,
                    remote_tools=remote_tools,
                )
                if identity_failure is not None:
                    return identity_failure
                window_resolution_failure = self._resolve_task_target_window(
                    tool_name,
                    cua_tool_name,
                    task_scope=task_scope,
                    remote_tools=remote_tools,
                )
                if window_resolution_failure is not None:
                    return window_resolution_failure
                target_identity_preverified = True
            arguments, argument_failure = self._mapped_cua_arguments(
                tool_name,
                cua_tool_name,
                payload,
                remote_tool=remote_tools[cua_tool_name],
                task_scope=task_scope,
            )
            if argument_failure is not None:
                return argument_failure
            if cua_tool_name == "launch_app" and preflight_launch_identity:
                # Cua's forced-new-instance launch takes its slower URL-handoff
                # path.  On macOS that path can emit a second, late activation
                # even after the driver's immediate suppression receipt says it
                # stayed in the background.  When the exact installed bundle
                # was resolved and is provably not running, the ordinary
                # NSWorkspace ``activates=false`` path still creates a new
                # process, so forcing a second instance is unnecessary.
                canonical_bundle_id = _normalized_bundle_id(
                    preflight_launch_identity.get("bundle_id")
                )
                launch_properties = _cua_tool_schema_properties(
                    remote_tools[cua_tool_name]
                )
                if canonical_bundle_id and "bundle_id" in launch_properties:
                    arguments["bundle_id"] = canonical_bundle_id
                    arguments.pop("name", None)
                if (
                    canonical_bundle_id
                    and preflight_launch_identity.get("running_pids") == []
                ):
                    arguments.pop("creates_new_application_instance", None)
            if (
                cua_tool_name in _CUA_PID_TARGETED_TOOLS
                and not target_identity_preverified
            ):
                identity_failure = self._verified_task_target_identity(
                    tool_name,
                    cua_tool_name,
                    task_scope=task_scope,
                    remote_tools=remote_tools,
                )
                if identity_failure is not None:
                    return identity_failure
            if not _cua_logical_tool_contract_supported(
                tool_name,
                cua_tool_name,
                remote_tools,
            ):
                return self._failure(
                    tool_name,
                    status="provider_tool_unavailable",
                    error="cua_mcp_tool_contract_unsupported",
                    summary=(
                        "Cua Driver does not expose the target-bound schema "
                        "required for this background action."
                    ),
                    blocking_condition=(
                        "desktop_execution_provider_tool_unavailable"
                    ),
                    retryable=False,
                    cua_tool_name=cua_tool_name,
                )
            if (
                cua_tool_name in _CUA_BACKGROUND_INPUT_TOOLS
                and self._task_target_record(task_scope).get(
                    "agent_owned_target"
                )
                is not True
            ):
                failure = self._failure(
                    tool_name,
                    status="provider_target_unavailable",
                    error="cua_background_target_not_agent_owned",
                    summary=(
                        "Cua could not prove that this target is separate from "
                        "the user's existing app window."
                    ),
                    blocking_condition=(
                        "desktop_background_agent_owned_target_required"
                    ),
                    retryable=False,
                    cua_tool_name=cua_tool_name,
                )
                failure["requires_user_handoff"] = True
                failure["agent_owned_target"] = False
                return failure
            if tool_name in _CUA_GROUNDED_ELEMENT_ACTION_TOOLS:
                grounded_result = self._ground_element_action(
                    tool_name,
                    payload,
                    arguments=arguments,
                    remote_action_tool=remote_tools[cua_tool_name],
                    remote_snapshot_tool=remote_tools.get("get_window_state"),
                    task_scope=task_scope,
                    cua_tool_name=cua_tool_name,
                )
                grounded_failure = grounded_result.get("failure")
                if isinstance(grounded_failure, Mapping):
                    return dict(grounded_failure)
                grounded_arguments = grounded_result.get("arguments")
                grounded_snapshot = grounded_result.get("snapshot")
                grounded_match = grounded_result.get("match")
                if not isinstance(grounded_arguments, Mapping):
                    return self._grounded_element_failure(
                        tool_name,
                        error="cua_background_element_target_required",
                        summary="Cua could not derive a safe element target.",
                        cua_tool_name=cua_tool_name,
                    )
                arguments = dict(grounded_arguments)
                if isinstance(grounded_snapshot, Mapping):
                    pre_action_snapshot = dict(grounded_snapshot)
                if isinstance(grounded_match, Mapping):
                    grounded_element = dict(grounded_match)
                snapshot_target_arguments = {
                    key: arguments.get(key)
                    for key in ("pid", "window_id")
                    if arguments.get(key) is not None
                }
            if (
                cua_tool_name in _CUA_SNAPSHOT_VERIFICATION_TOOLS
                and tool_name not in _CUA_GROUNDED_ELEMENT_ACTION_TOOLS
                and "get_window_state" in remote_tools
            ):
                snapshot_target_arguments = dict(arguments)
                scoped_target = self._task_target_record(task_scope)
                if scoped_target.get("window_id") is not None:
                    snapshot_target_arguments["window_id"] = scoped_target[
                        "window_id"
                    ]
                pre_action_snapshot = self._target_bound_snapshot(
                    remote_tools["get_window_state"],
                    snapshot_target_arguments,
                )
            repeat_count = 1
            if tool_name == "desktop.safe_key":
                repeat_count = _bounded_repeat_count(payload.get("repeat_count", 1))
                if repeat_count is None:
                    return self._failure(
                        tool_name,
                        status="provider_input_invalid",
                        error="cua_safe_key_repeat_count_invalid",
                        summary="Safe key repeat_count must be an integer from 1 to 20.",
                        blocking_condition="desktop_execution_provider_input_invalid",
                        retryable=False,
                        cua_tool_name=cua_tool_name,
                    )
            mcp_result: dict[str, Any] = {}
            if cua_tool_name == "launch_app" and task_scope:
                # Crossing the remote launch boundary is an at-least-once
                # effect: the app may have been created even if the MCP receipt
                # is lost or reports an error.  Pin provider affinity before
                # dispatch, while keeping pid/window authority empty until the
                # existing launch receipt and ownership checks succeed.
                self._pin_task_scope(task_scope)
            for _index in range(repeat_count):
                mcp_result = self.client.call_tool(cua_tool_name, arguments)
                interim_result = _preferred_mcp_tool_result(mcp_result)
                if interim_result.get("ok") is False or _cua_effect(
                    interim_result
                ) == "suspected_noop":
                    break
        except CuaMcpToolError as exc:
            if task_scope and cua_tool_name in _CUA_PID_TARGETED_TOOLS:
                self._forget_task_target(task_scope)
            return self._failure(
                tool_name,
                status="provider_tool_failed",
                error="cua_mcp_tool_error",
                summary=_mcp_result_message(exc.result)
                or "Cua Driver reported that the background action failed.",
                blocking_condition="desktop_execution_provider_tool_failed",
                retryable=False,
                cua_tool_name=cua_tool_name,
                mcp_result=exc.result,
            )
        except (CuaMcpError, OSError) as exc:
            if task_scope and cua_tool_name in _CUA_PID_TARGETED_TOOLS:
                self._forget_task_target(task_scope)
            return self._failure(
                tool_name,
                status="provider_transport_failed",
                error="cua_mcp_transport_failed",
                summary=str(exc) or "Cua Driver MCP transport failed.",
                blocking_condition="desktop_execution_provider_transport_failed",
                retryable=True,
                cua_tool_name=cua_tool_name,
            )

        result = _preferred_mcp_tool_result(mcp_result)
        if cua_tool_name == "launch_app" and preflight_launch_identity:
            canonical_bundle_id = _normalized_bundle_id(
                preflight_launch_identity.get("bundle_id")
            )
            if canonical_bundle_id and not _normalized_bundle_id(
                result.get("bundle_id")
            ):
                result["bundle_id"] = canonical_bundle_id
            if not _normalized_app_name(result.get("name")):
                canonical_names = _string_list(
                    preflight_launch_identity.get("app_names")
                )
                if canonical_names:
                    result["name"] = canonical_names[0]
        if cua_tool_name == "list_apps":
            result = _normalized_cua_list_apps_result(
                mcp_result,
                query=payload.get("query"),
                limit=payload.get("limit", 200),
            )
        elif (
            cua_tool_name == "get_window_state"
            and tool_name in _CUA_TARGET_BOUND_OBSERVATION_TOOLS
        ):
            result = _normalized_cua_target_bound_observation_result(
                tool_name,
                mcp_result,
                payload=payload,
                target=self._task_target_record(task_scope),
                tool_request=tool_request,
                route=route,
                provider_kind=self.provider_kind,
                provider_id=self.provider_id,
            )
        result.setdefault("ok", True)
        result.setdefault("tool", tool_name)
        result.setdefault("action", tool_name)
        result.setdefault(
            "desktop_execution_provider_transport",
            self._transport_metadata(cua_tool_name=cua_tool_name),
        )
        if cua_tool_name == "launch_app":
            result["agent_owned_target"] = _launch_target_is_agent_owned(
                result,
                arguments,
                preexisting_launch_pids,
                preflight_launch_identity,
            )
        if cua_tool_name == "launch_app" and result.get("ok") is True and (
            result.get("agent_owned_target") is not True
            or result.get("self_activation_suppressed") is not True
        ):
            if task_scope:
                self._forget_task_target(task_scope)
            target_owned = result.get("agent_owned_target") is True
            activation_suppressed = result.get("self_activation_suppressed")
            activation_detected = activation_suppressed is False
            failure = self._failure(
                tool_name,
                status=(
                    "foreground_delivery_violation"
                    if activation_detected
                    else "provider_target_unavailable"
                ),
                error=(
                    "cua_launch_foreground_takeover_detected"
                    if activation_detected
                    else (
                        "cua_background_target_not_agent_owned"
                        if not target_owned
                        else "cua_launch_background_delivery_unverified"
                    )
                ),
                summary=(
                    "Cua launched the app but could not keep it from taking "
                    "the user's foreground."
                    if activation_detected
                    else (
                        "Cua could not prove that launch_app created a separate "
                        "agent-owned process."
                        if not target_owned
                        else "Cua did not prove that the new app stayed in the background."
                    )
                ),
                blocking_condition=(
                    "desktop_foreground_takeover_detected"
                    if activation_detected
                    else "desktop_background_agent_owned_target_required"
                ),
                retryable=False,
                cua_tool_name=cua_tool_name,
                mcp_result=mcp_result,
            )
            failure["agent_owned_target"] = target_owned
            failure["self_activation_suppressed"] = activation_suppressed
            failure["foreground_takeover_detected"] = activation_detected
            failure["requires_user_handoff"] = True
            return failure
        if (
            cua_tool_name == "launch_app"
            and result.get("ok") is True
            and task_scope
        ):
            # A newly launched process can be returned before WindowServer has
            # published its first top-level window. Cache only the trusted
            # process identity, then bind the eventual pid-owned window through
            # Cua's read-only list_windows contract before claiming launch
            # success to the runtime.
            self._remember_task_target_from_result(
                task_scope,
                result,
                launch_arguments=arguments,
                preflight_launch_identity=preflight_launch_identity,
                previous_target=previous_launch_target,
                agent_owned_target=True,
            )
            if _positive_int(
                self._task_target_record(task_scope).get("window_id")
            ) is None and "list_windows" in remote_tools:
                window_resolution_failure = self._resolve_task_target_window(
                    tool_name,
                    cua_tool_name,
                    task_scope=task_scope,
                    remote_tools=remote_tools,
                )
                if window_resolution_failure is not None:
                    window_resolution_failure.update(
                        {
                            "pid": _positive_int(result.get("pid")),
                            "agent_owned_target": True,
                            "self_activation_suppressed": True,
                        }
                    )
                    return window_resolution_failure
            bound_target = self._task_target_record(task_scope)
            bound_window_id = _positive_int(bound_target.get("window_id"))
            if bound_window_id is not None:
                result["window_id"] = bound_window_id
                if not result.get("windows"):
                    result["windows"] = [
                        {
                            "pid": _positive_int(bound_target.get("pid")),
                            "window_id": bound_window_id,
                        }
                    ]
        if tool_name in _CUA_GROUNDED_ELEMENT_ACTION_TOOLS:
            grounded_action_result = self._grounded_element_action_result(
                tool_name,
                result,
                mcp_result=mcp_result,
                cua_tool_name=cua_tool_name,
                before=pre_action_snapshot,
                remote_snapshot_tool=remote_tools.get("get_window_state"),
                target_arguments=snapshot_target_arguments or arguments,
                matched_element=grounded_element,
            )
            if task_scope:
                if grounded_action_result.get("ok") is True:
                    self._remember_task_target_from_arguments(task_scope, arguments)
                elif grounded_action_result.get("action_dispatched") is not True:
                    self._forget_task_target(task_scope)
            return grounded_action_result
        if cua_tool_name in _CUA_BACKGROUND_INPUT_TOOLS:
            effect = _cua_effect(result)
            if effect == "suspected_noop":
                failure = self._failure(
                    tool_name,
                    status="provider_action_unverified",
                    error="cua_action_suspected_noop",
                    summary="Cua dispatched the action but detected a suspected no-op.",
                    blocking_condition="desktop_action_verification_required",
                    retryable=True,
                    cua_tool_name=cua_tool_name,
                    mcp_result=mcp_result,
                )
                failure.update(
                    {
                        "action_dispatched": True,
                        "effect": effect,
                        "postcondition_verified": False,
                        "requires_postcondition_verification": True,
                    }
                )
                return failure
            if result.get("verified") is False or effect == "unverifiable":
                verification_evidence = self._state_change_verification_evidence(
                    pre_action_snapshot,
                    remote_tools.get("get_window_state"),
                    snapshot_target_arguments or arguments,
                )
                if verification_evidence.get("state_changed") is True:
                    result.update(
                        {
                            "ok": True,
                            "status": "state_change_observed",
                            "delivery_verified": True,
                            "postcondition_verified": False,
                            "requires_postcondition_verification": True,
                            "verification_method": (
                                "target_bound_window_state_change"
                            ),
                            "verification_evidence": verification_evidence,
                        }
                    )
                elif _pending_window_materialization_delivery(
                    tool_name,
                    payload,
                    result=result,
                    effect=effect,
                    target=(
                        self._task_target_record(task_scope)
                        if task_scope
                        else {}
                    ),
                    arguments=arguments,
                ):
                    target_pid = _positive_int(arguments.get("pid"))
                    self._remember_task_target(
                        task_scope,
                        {
                            "_window_materialization_recovery_phase": (
                                "delivery_dispatched"
                            ),
                            "_window_materialization_recovery_expires_at": (
                                time.monotonic()
                                + _TASK_TARGET_WINDOW_MATERIALIZATION_RECOVERY_SECONDS
                            ),
                        },
                    )
                    result.update(
                        {
                            "ok": True,
                            "status": "window_materialization_dispatched",
                            "summary": (
                                "Cua dispatched the background window-materialization "
                                "shortcut; a later target-bound observation must bind "
                                "the new window and verify the postcondition."
                            ),
                            "action_dispatched": True,
                            "delivery_dispatched": True,
                            "delivery_verified": False,
                            "effect": effect or "unverifiable",
                            "postcondition_verified": False,
                            "requires_postcondition_verification": True,
                            "window_materialization_pending": True,
                            "agent_owned_target": True,
                            "pid": target_pid,
                            "verification_method": (
                                "pending_target_bound_observation"
                            ),
                            "verification_evidence": verification_evidence,
                        }
                    )
                else:
                    failure = self._failure(
                        tool_name,
                        status="dispatched_unverified",
                        error="cua_action_unverified",
                        summary=(
                            "Cua dispatched the background action but could not "
                            "verify its postcondition."
                        ),
                        blocking_condition="desktop_action_verification_required",
                        retryable=False,
                        cua_tool_name=cua_tool_name,
                        mcp_result=mcp_result,
                    )
                    failure.update(
                        {
                            "action_dispatched": True,
                            "effect": effect or "unverifiable",
                            "postcondition_verified": False,
                            "requires_postcondition_verification": True,
                            "verification_evidence": verification_evidence,
                        }
                    )
                    return failure
        if (
            result.get("ok") is False
            and task_scope
            and cua_tool_name in _CUA_PID_TARGETED_TOOLS
        ):
            self._forget_task_target(task_scope)
        if result.get("ok") is True and task_scope:
            if cua_tool_name == "launch_app":
                self._remember_task_target_from_result(
                    task_scope,
                    result,
                    launch_arguments=arguments,
                    preflight_launch_identity=preflight_launch_identity,
                    previous_target=previous_launch_target,
                    agent_owned_target=result.get("agent_owned_target") is True,
                )
            elif cua_tool_name in _CUA_PID_TARGETED_TOOLS:
                self._remember_task_target_from_arguments(task_scope, arguments)
        return result

    def _execute_open_composite_locked(
        self,
        tool_name: str,
        payload: Mapping[str, Any],
        *,
        tool_request: Mapping[str, Any],
        route: Mapping[str, Any],
        broker: Any,
        approved: bool,
    ) -> dict[str, Any]:
        action_tool = _CUA_OPEN_COMPOSITE_TOOLS[tool_name]
        cua_tool_name = self.tool_name_map[tool_name]
        try:
            remote_tool_names = {
                str(tool.get("name") or "") for tool in self.client.list_tools()
            }
        except (CuaMcpError, OSError) as exc:
            return self._failure(
                tool_name,
                status="provider_transport_failed",
                error="cua_mcp_transport_failed",
                summary=str(exc) or "Cua Driver MCP transport failed.",
                blocking_condition="desktop_execution_provider_transport_failed",
                retryable=True,
                cua_tool_name=cua_tool_name,
            )
        missing_tools = sorted(
            _required_cua_tool_names(tool_name, cua_tool_name)
            - remote_tool_names
        )
        if missing_tools:
            return self._failure(
                tool_name,
                status="provider_tool_unavailable",
                error="cua_mcp_tool_unavailable",
                summary=(
                    "Cua Driver does not expose composite dependency: "
                    + ", ".join(missing_tools)
                ),
                blocking_condition="desktop_execution_provider_tool_unavailable",
                retryable=False,
                cua_tool_name=cua_tool_name,
            )
        steps: list[dict[str, Any]] = []
        launch_payload = {
            key: payload.get(key)
            for key in (
                "app_name",
                "bundle_id",
                "launch_path",
                "name",
                "urls",
                "webkit_inspector_port",
            )
            if key in payload
        }
        launch_result = self._execute_locked(
            "app.open",
            launch_payload,
            tool_request=_internal_composite_tool_request(
                tool_request,
                "app.open",
            ),
            route={**route, "tool_name": "app.open"},
            broker=broker,
            approved=approved,
            _internal_composite_step=True,
        )
        steps.append(_compact_composite_step("app.open", launch_result))
        if launch_result.get("ok") is not True:
            return _composite_result(
                tool_name,
                launch_result,
                steps=steps,
                failed_step="app.open",
            )

        action_result = self._execute_locked(
            action_tool,
            dict(payload),
            tool_request=_internal_composite_tool_request(
                tool_request,
                action_tool,
            ),
            route={**route, "tool_name": action_tool},
            broker=broker,
            approved=approved,
            _internal_composite_step=True,
        )
        steps.append(_compact_composite_step(action_tool, action_result))
        return _composite_result(
            tool_name,
            action_result,
            steps=steps,
            failed_step=(
                action_tool if action_result.get("ok") is not True else ""
            ),
        )

    def _target_bound_snapshot(
        self,
        remote_tool: Mapping[str, Any],
        target_arguments: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        allowed_arguments = set(
            _cua_tool_schema_properties(remote_tool)
        ).intersection(_CUA_OFFICIAL_ARGUMENTS["get_window_state"])
        arguments = {
            key: target_arguments.get(key)
            for key in ("pid", "window_id")
            if key in allowed_arguments and target_arguments.get(key) is not None
        }
        if _missing_cua_required_arguments(remote_tool, arguments):
            return None
        try:
            mcp_result = self.client.call_tool("get_window_state", arguments)
        except (CuaMcpError, OSError):
            return None
        snapshot = _preferred_mcp_tool_result(mcp_result)
        if snapshot.get("ok") is False:
            return None
        return snapshot

    def _state_change_verification_evidence(
        self,
        before: Mapping[str, Any] | None,
        remote_tool: Mapping[str, Any] | None,
        target_arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        evidence: dict[str, Any] = {
            "source": "get_window_state",
            "state_changed": False,
            "target": {
                key: target_arguments.get(key)
                for key in ("pid", "window_id")
                if target_arguments.get(key) is not None
            },
        }
        if before is None or remote_tool is None:
            evidence["available"] = False
            return evidence
        target_pid = _positive_int(target_arguments.get("pid"))
        target_window_id = _positive_int(target_arguments.get("window_id"))
        if target_pid is None or target_window_id is None:
            evidence["available"] = False
            evidence["target_bound"] = False
            return evidence
        after = self._target_bound_snapshot(remote_tool, target_arguments)
        if after is None:
            evidence["available"] = False
            return evidence
        target_bound = all(
            _positive_int(snapshot.get("pid")) == target_pid
            and _positive_int(snapshot.get("window_id")) == target_window_id
            for snapshot in (before, after)
        )
        if not target_bound:
            evidence["available"] = False
            evidence["target_bound"] = False
            return evidence
        before_digest = _cua_snapshot_digest(before)
        after_digest = _cua_snapshot_digest(after)
        evidence.update(
            {
                "available": True,
                "target_bound": True,
                "before_digest": before_digest,
                "after_digest": after_digest,
                "state_changed": before_digest != after_digest,
            }
        )
        return evidence

    def _ground_element_action(
        self,
        tool_name: str,
        payload: Mapping[str, Any],
        *,
        arguments: Mapping[str, Any],
        remote_action_tool: Mapping[str, Any],
        remote_snapshot_tool: Mapping[str, Any] | None,
        task_scope: str,
        cua_tool_name: str,
    ) -> dict[str, Any]:
        """Resolve one exact Cua snapshot element without touching host input."""

        target_record = self._task_target_record(task_scope)
        target_pid = _positive_int(target_record.get("pid"))
        target_window_id = _positive_int(target_record.get("window_id"))
        if (
            target_record.get("agent_owned_target") is not True
            or target_pid is None
            or target_window_id is None
        ):
            return {
                "failure": self._grounded_element_failure(
                    tool_name,
                    error="cua_background_owned_window_required",
                    summary=(
                        "Grounded background input requires an agent-owned "
                        "new process and one explicit window."
                    ),
                    cua_tool_name=cua_tool_name,
                )
            }
        if remote_snapshot_tool is None or not _grounded_element_contract_supported(
            remote_action_tool,
            remote_snapshot_tool,
        ):
            return {
                "failure": self._grounded_element_failure(
                    tool_name,
                    error="cua_background_element_contract_unavailable",
                    summary=(
                        "This Cua Driver cannot bind snapshots and element "
                        "input to the same pid/window."
                    ),
                    cua_tool_name=cua_tool_name,
                )
            }
        if tool_name == "desktop.click_ui_element":
            click_count = _bounded_repeat_count(payload.get("click_count", 1))
            if click_count != 1:
                return {
                    "failure": self._grounded_element_failure(
                        tool_name,
                        error="cua_background_click_count_unsupported",
                        summary=(
                            "Grounded background clicking supports one click "
                            "per fresh snapshot."
                        ),
                        cua_tool_name=cua_tool_name,
                    )
                }

        snapshot_arguments = {"pid": target_pid, "window_id": target_window_id}
        snapshot = self._target_bound_snapshot(
            remote_snapshot_tool,
            snapshot_arguments,
        )
        if snapshot is None:
            return {
                "failure": self._grounded_element_failure(
                    tool_name,
                    error="cua_background_window_snapshot_required",
                    summary="Cua could not snapshot the agent-owned target window.",
                    cua_tool_name=cua_tool_name,
                )
            }
        if (
            _positive_int(snapshot.get("pid")) != target_pid
            or _positive_int(snapshot.get("window_id")) != target_window_id
        ):
            return {
                "failure": self._grounded_element_failure(
                    tool_name,
                    error="cua_background_window_identity_mismatch",
                    summary=(
                        "Cua returned a snapshot for a different pid/window; "
                        "no input was sent."
                    ),
                    cua_tool_name=cua_tool_name,
                )
            }

        requested_label = _normalized_cua_element_label(payload.get("target"))
        requested_role = _normalized_cua_element_role(payload.get("role_filter"))
        if not requested_label:
            return {
                "failure": self._grounded_element_failure(
                    tool_name,
                    error="cua_background_element_label_required",
                    summary="Grounded background input requires an exact label.",
                    cua_tool_name=cua_tool_name,
                )
            }
        elements = snapshot.get("elements")
        if not isinstance(elements, list):
            return {
                "failure": self._grounded_element_failure(
                    tool_name,
                    error="cua_background_snapshot_elements_required",
                    summary="Cua's target-bound snapshot did not contain elements.",
                    cua_tool_name=cua_tool_name,
                )
            }
        matches: list[dict[str, Any]] = []
        for element in elements:
            if not isinstance(element, Mapping):
                continue
            labels = _cua_element_labels(element)
            if requested_label not in labels:
                continue
            if requested_role and _normalized_cua_element_role(
                element.get("role")
            ) != requested_role:
                continue
            matches.append(dict(element))
        exact_match_count = len(matches)
        matches = _collapse_equivalent_cua_element_matches(matches)
        if len(matches) != 1:
            return {
                "failure": self._grounded_element_failure(
                    tool_name,
                    error=(
                        "cua_background_element_not_found"
                        if not matches
                        else "cua_background_element_ambiguous"
                    ),
                    summary=(
                        "No exact element label/role match was found."
                        if not matches
                        else "More than one exact element label/role match was found."
                    ),
                    cua_tool_name=cua_tool_name,
                    match_count=exact_match_count,
                )
            }
        matched = matches[0]
        if any(
            matched.get(key) is False
            for key in ("enabled", "clickable", "actionable", "interactable")
        ):
            return {
                "failure": self._grounded_element_failure(
                    tool_name,
                    error="cua_background_element_not_interactable",
                    summary="The exact matched element is explicitly not interactable.",
                    cua_tool_name=cua_tool_name,
                )
            }

        action_properties = _cua_tool_schema_properties(remote_action_tool)
        element_token = _cua_element_token(matched)
        element_index = _cua_element_index(matched)
        selector: dict[str, Any] = {}
        selector_type = ""
        if element_token and "element_token" in action_properties:
            selector = {"element_token": element_token}
            selector_type = "element_token"
        elif element_index is not None and "element_index" in action_properties:
            selector = {"element_index": element_index}
            selector_type = "element_index"
        else:
            return {
                "failure": self._grounded_element_failure(
                    tool_name,
                    error="cua_background_element_identifier_required",
                    summary=(
                        "The exact matched element has no Cua token/index "
                        "accepted by this action."
                    ),
                    cua_tool_name=cua_tool_name,
                )
            }
        grounded_arguments = {
            **dict(arguments),
            "pid": target_pid,
            "window_id": target_window_id,
            **selector,
        }
        for forbidden_key in ("x", "y"):
            grounded_arguments.pop(forbidden_key, None)
        missing_required = _missing_cua_required_arguments(
            remote_action_tool,
            grounded_arguments,
        )
        if missing_required:
            return {
                "failure": self._grounded_element_failure(
                    tool_name,
                    error="cua_mcp_required_argument_missing",
                    summary=(
                        "Cua requires unmapped grounded argument(s): "
                        + ", ".join(missing_required)
                    ),
                    cua_tool_name=cua_tool_name,
                )
            }
        match = {
            "label": str(payload.get("target") or "").strip(),
            "role": str(matched.get("role") or "").strip(),
            "selector_type": selector_type,
            "pid": target_pid,
            "window_id": target_window_id,
        }
        if exact_match_count > 1:
            match["equivalent_match_count"] = exact_match_count
        return {
            "arguments": grounded_arguments,
            "snapshot": snapshot,
            "match": match,
        }

    def _grounded_element_action_result(
        self,
        tool_name: str,
        result: Mapping[str, Any],
        *,
        mcp_result: Mapping[str, Any],
        cua_tool_name: str,
        before: Mapping[str, Any] | None,
        remote_snapshot_tool: Mapping[str, Any] | None,
        target_arguments: Mapping[str, Any],
        matched_element: Mapping[str, Any],
    ) -> dict[str, Any]:
        verification_evidence = self._state_change_verification_evidence(
            before,
            remote_snapshot_tool,
            target_arguments,
        )
        effect = _cua_effect(result)
        if result.get("ok") is False or effect == "suspected_noop":
            failure = self._failure(
                tool_name,
                status=(
                    "provider_action_unverified"
                    if effect == "suspected_noop"
                    else "provider_tool_failed"
                ),
                error=(
                    "cua_action_suspected_noop"
                    if effect == "suspected_noop"
                    else "cua_mcp_tool_failed"
                ),
                summary=(
                    "Cua did not acknowledge grounded background delivery."
                ),
                blocking_condition="desktop_action_verification_required",
                retryable=False,
                cua_tool_name=cua_tool_name,
                mcp_result=mcp_result,
            )
            failure.update(
                {
                    "delivery_attempted": True,
                    "postcondition_verified": False,
                    "requires_postcondition_verification": True,
                    "verification_evidence": verification_evidence,
                }
            )
            return failure
        state_changed = verification_evidence.get("state_changed") is True
        target_pid = _positive_int(matched_element.get("pid"))
        target_window_id = _positive_int(matched_element.get("window_id"))
        return {
            "ok": True,
            "tool": tool_name,
            "action": tool_name,
            "status": (
                "state_change_observed" if state_changed else "delivery_dispatched"
            ),
            "summary": (
                "Cua dispatched the grounded background action and observed a "
                "target-window state change; the business outcome is unverified."
                if state_changed
                else "Cua dispatched the grounded background action; the business "
                "outcome is unverified."
            ),
            "action_dispatched": True,
            "delivery_status": (
                "state_change_observed" if state_changed else "dispatched"
            ),
            "delivery_verified": state_changed,
            "postcondition_verified": False,
            "requires_postcondition_verification": True,
            "verification_method": "target_bound_window_state_change",
            "verification_evidence": verification_evidence,
            "grounded_element": dict(matched_element),
            "agent_owned_target": bool(
                target_pid is not None and target_window_id is not None
            ),
            "target_bound": bool(
                target_pid is not None and target_window_id is not None
            ),
            "effect": (
                "state_change_observed" if state_changed else "delivery_dispatched"
            ),
            "desktop_execution_provider_evidence": {
                "mcp_tool": cua_tool_name,
                "desktop_scope": "agent_owned_background",
                "pid": target_pid,
                "window_id": target_window_id,
                "target_bound": bool(
                    target_pid is not None and target_window_id is not None
                ),
                "target_identity_source": "grounded_element_snapshot",
            },
            "desktop_execution_provider_transport": self._transport_metadata(
                cua_tool_name=cua_tool_name
            ),
        }

    def _grounded_element_failure(
        self,
        tool_name: str,
        *,
        error: str,
        summary: str,
        cua_tool_name: str,
        match_count: int | None = None,
    ) -> dict[str, Any]:
        failure = self._failure(
            tool_name,
            status="provider_target_unavailable",
            error=error,
            summary=summary,
            blocking_condition="desktop_background_target_required",
            retryable=False,
            cua_tool_name=cua_tool_name,
        )
        failure["requires_user_handoff"] = True
        failure["agent_owned_target_required"] = True
        if match_count is not None:
            failure["match_count"] = match_count
        return failure

    def health(self) -> dict[str, Any]:
        electron_bridge = self.client.transport_kind == "electron_bridge"
        try:
            remote_tools = {
                str(tool.get("name") or ""): tool
                for tool in self.client.list_tools()
            }
        except (CuaMcpError, OSError) as exc:
            return self._health_payload(
                ok=False,
                checked=True,
                status=(
                    "electron_bridge_unavailable"
                    if electron_bridge
                    else "unreachable"
                ),
                blocking_conditions=[
                    "cua_electron_bridge_unavailable"
                    if electron_bridge
                    else "desktop_execution_provider_unreachable"
                ],
                error=str(exc),
            )
        available_tools = [
            name
            for name in self.supported_tools
            if self.tool_name_map.get(name)
            and _cua_logical_tool_contract_supported(
                name,
                self.tool_name_map[name],
                remote_tools,
            )
        ]
        if not available_tools:
            return self._health_payload(
                ok=False,
                checked=True,
                status="required_tools_missing",
                blocking_conditions=[
                    "desktop_execution_provider_tool_unavailable"
                ],
                supported_tools=[],
            )
        health_tool = remote_tools.get("health_report")
        if health_tool is None:
            return self._health_payload(
                ok=False,
                checked=True,
                status="health_report_unavailable",
                blocking_conditions=[
                    "desktop_execution_provider_health_unavailable"
                ],
                supported_tools=available_tools,
            )
        if (
            electron_bridge
            and "skip" not in _cua_tool_schema_properties(health_tool)
        ):
            return self._health_payload(
                ok=False,
                checked=True,
                status="health_report_contract_unsupported",
                blocking_conditions=[
                    "cua_health_report_contract_unsupported"
                ],
                error=(
                    "Embedded health_report must support skipping the "
                    "bundle_identity check."
                ),
                supported_tools=available_tools,
            )
        health_arguments, required_arguments = _cua_health_report_arguments(
            health_tool,
            skip_bundle_identity=electron_bridge,
        )
        if required_arguments:
            return self._health_payload(
                ok=False,
                checked=True,
                status="health_report_contract_unsupported",
                blocking_conditions=[
                    "cua_health_report_contract_unsupported"
                ],
                error=(
                    "Unsupported health_report arguments: "
                    + ", ".join(required_arguments)
                ),
                supported_tools=available_tools,
            )
        try:
            health_result = self.client.call_tool(
                "health_report",
                health_arguments,
            )
        except (CuaMcpError, OSError) as exc:
            return self._health_payload(
                ok=False,
                checked=True,
                status="health_report_failed",
                blocking_conditions=[
                    "desktop_execution_provider_health_unavailable"
                ],
                error=str(exc),
                supported_tools=available_tools,
            )
        report = _preferred_mcp_tool_result(health_result)
        if report.get("schema_version") != "1":
            health = self._health_payload(
                ok=False,
                checked=True,
                status="health_report_contract_unsupported",
                blocking_conditions=[
                    "cua_health_report_contract_unsupported"
                ],
                error="Unsupported Cua health_report schema version.",
                supported_tools=available_tools,
            )
            health["health_report"] = report
            return health
        ready, blocking_conditions, report = _cua_health_report_readiness(
            health_result
        )
        if electron_bridge:
            permissions_tool = remote_tools.get("check_permissions")
            if (
                permissions_tool is None
                or "prompt" not in _cua_tool_schema_properties(permissions_tool)
            ):
                health = self._health_payload(
                    ok=False,
                    checked=True,
                    status="embedded_permission_attribution_invalid",
                    blocking_conditions=[
                        "cua_embedded_host_attribution_failed"
                    ],
                    error=(
                        "Embedded Cua must expose a noninteractive "
                        "check_permissions contract."
                    ),
                    supported_tools=available_tools,
                )
                health["health_report"] = report
                return health
            try:
                permissions_result = self.client.call_tool(
                    "check_permissions",
                    {"prompt": False},
                )
            except (CuaMcpError, OSError) as exc:
                health = self._health_payload(
                    ok=False,
                    checked=True,
                    status="embedded_permission_attribution_invalid",
                    blocking_conditions=[
                        "cua_embedded_host_attribution_failed"
                    ],
                    error=str(exc),
                    supported_tools=available_tools,
                )
                health["health_report"] = report
                return health
            permissions_report = _preferred_mcp_tool_result(
                permissions_result
            )
            source = permissions_report.get("source")
            if (
                not isinstance(source, Mapping)
                or source.get("attribution") != "host"
                or source.get("embedded") is not True
            ):
                health = self._health_payload(
                    ok=False,
                    checked=True,
                    status="embedded_permission_attribution_invalid",
                    blocking_conditions=[
                        "cua_embedded_host_attribution_failed"
                    ],
                    supported_tools=available_tools,
                )
                health["health_report"] = report
                return health
            if permissions_report.get("accessibility") is not True:
                blocking_conditions.append(
                    "desktop_permission_accessibility_required"
                )
            if permissions_report.get("screen_recording") is not True:
                blocking_conditions.append(
                    "desktop_permission_screen_recording_required"
                )
            blocking_conditions = _string_list(blocking_conditions)
            ready = ready and not blocking_conditions
        health = self._health_payload(
            ok=ready,
            checked=True,
            status="healthy" if ready else "not_ready",
            blocking_conditions=blocking_conditions,
            supported_tools=available_tools,
        )
        health["health_report"] = report
        return health

    def configured_status(self, *, probe_health: bool = False) -> dict[str, Any]:
        health = self.health() if probe_health else self._health_payload(
            ok=False,
            checked=False,
            status="not_checked",
            blocking_conditions=[],
            supported_tools=self.supported_tools,
        )
        available = bool(health.get("ok")) if probe_health else False
        checked = health.get("checked") is True
        bridge_unavailable = (
            self.client.transport_kind == "electron_bridge"
            and health.get("status") == "electron_bridge_unavailable"
        )
        status = (
            "available"
            if available
            else "electron_bridge_unavailable"
            if bridge_unavailable
            else "provider_unhealthy"
            if checked
            else "installed_not_checked"
        )
        return {
            "configured": True,
            "available": available,
            "adapter_ready": available,
            "provider_kind": self.provider_kind,
            "provider_id": self.provider_id,
            "authentication_configured": (
                self.client.transport_kind == "electron_bridge"
            ),
            "status": status,
            "reason": (
                "Cua Driver background execution is available."
                if available
                else "The Electron-owned Cua MCP bridge is unavailable."
                if bridge_unavailable
                else "Cua Driver background execution is unavailable."
                if checked
                else "Cua background execution is configured; readiness has not been checked."
            ),
            "blocking_conditions": (
                []
                if not checked or available
                else list(health.get("blocking_conditions") or [])
            ),
            "supported_tools": list(
                health.get("supported_tools") or self.supported_tools
            ),
            "capabilities": _background_capabilities(),
            "health": health,
            "source": (
                "cua_mcp_electron_bridge"
                if self.client.transport_kind == "electron_bridge"
                else "cua_mcp_stdio"
            ),
            "transport": self.client.transport_kind,
            **_background_status_fields(),
        }

    def close(self) -> None:
        with self._target_lock:
            self._task_targets.clear()
            self._owned_task_scopes.clear()
        self.client.close()

    def _mapped_cua_arguments(
        self,
        tool_name: str,
        cua_tool_name: str,
        payload: Mapping[str, Any],
        *,
        remote_tool: Mapping[str, Any],
        task_scope: str,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        schema_properties = _cua_tool_schema_properties(remote_tool)
        known_arguments = _CUA_OFFICIAL_ARGUMENTS.get(cua_tool_name)
        if known_arguments is None:
            return {}, self._failure(
                tool_name,
                status="provider_tool_unavailable",
                error="cua_mcp_tool_contract_unknown",
                summary="Oha does not know a safe argument contract for this Cua tool.",
                blocking_condition="desktop_execution_provider_tool_unavailable",
                retryable=False,
                cua_tool_name=cua_tool_name,
            )
        allowed_arguments = set(schema_properties).intersection(known_arguments)
        canonical = _canonical_cua_arguments(
            tool_name,
            cua_tool_name,
            payload,
            allowed_arguments=allowed_arguments,
        )

        if cua_tool_name in _CUA_PID_TARGETED_TOOLS:
            if not task_scope:
                return {}, self._target_failure(
                    tool_name,
                    error="cua_task_scope_required",
                    summary=(
                        "Background input requires a stable task scope before "
                        "a process target can be selected."
                    ),
                    cua_tool_name=cua_tool_name,
                )
            target, target_error = self._resolved_task_target(task_scope, payload)
            if target_error:
                return {}, self._target_failure(
                    tool_name,
                    error=target_error,
                    summary=(
                        "Background input requires a pid owned by this task's "
                        "Cua target."
                    ),
                    cua_tool_name=cua_tool_name,
                )
            canonical["pid"] = target["pid"]
            if "window_id" not in canonical and target.get("window_id"):
                canonical["window_id"] = target["window_id"]

        if cua_tool_name in _CUA_BACKGROUND_INPUT_TOOLS:
            # Never copy the requested mode.  Cua defaults to background, and
            # when the installed schema exposes the field we make the contract
            # explicit on every input action.
            canonical["delivery_mode"] = self.delivery_mode
        else:
            canonical.pop("delivery_mode", None)

        arguments = {
            key: value
            for key, value in canonical.items()
            if key in allowed_arguments and value is not None
        }
        if cua_tool_name in _CUA_POINTER_TOOLS and not _has_cua_pointer_target(
            arguments
        ) and tool_name not in _CUA_GROUNDED_ELEMENT_ACTION_TOOLS:
            return {}, self._failure(
                tool_name,
                status="provider_target_unavailable",
                error="cua_background_element_target_required",
                summary=(
                    "Cua needs an element index/token or window-relative x/y; "
                    "Oha will not guess one from a label."
                ),
                blocking_condition="desktop_background_target_required",
                retryable=False,
                cua_tool_name=cua_tool_name,
            )
        missing_required = _missing_cua_required_arguments(remote_tool, arguments)
        if tool_name in _CUA_GROUNDED_ELEMENT_ACTION_TOOLS:
            # A snapshot is deliberately read only after process ownership and
            # identity are revalidated.  Defer only the identifier that that
            # snapshot is allowed to provide.
            missing_required = [
                name
                for name in missing_required
                if name not in {"element_index", "element_token"}
            ]
        if missing_required:
            return {}, self._failure(
                tool_name,
                status="provider_input_invalid",
                error="cua_mcp_required_argument_missing",
                summary=(
                    "Cua requires mapped argument(s): " + ", ".join(missing_required)
                ),
                blocking_condition="desktop_execution_provider_input_invalid",
                retryable=False,
                cua_tool_name=cua_tool_name,
            )
        return arguments, None

    def _resolved_task_target(
        self,
        task_scope: str,
        payload: Mapping[str, Any],
    ) -> tuple[dict[str, int], str]:
        explicit_pid_present = "pid" in payload and payload.get("pid") is not None
        explicit_pid = _positive_int(payload.get("pid"))
        if explicit_pid_present and explicit_pid is None:
            return {}, "cua_background_target_required"
        explicit_window_present = (
            "window_id" in payload and payload.get("window_id") is not None
        )
        explicit_window_id = _positive_int(payload.get("window_id"))
        if explicit_window_present and explicit_window_id is None:
            return {}, "cua_background_target_required"
        cached = self._task_target_record(task_scope)
        cached_pid = _positive_int(cached.get("pid"))
        if cached_pid is None:
            # A model-authored pid cannot establish authority over an arbitrary
            # process.  The target must first come from this scope's successful
            # launch_app result (or a future explicitly trusted provider target).
            return {}, "cua_background_target_required"
        if cached.get("ambiguous") is True:
            return {}, "cua_background_target_ambiguous"
        if explicit_pid is not None and explicit_pid != cached_pid:
            return {}, "cua_background_target_mismatch"
        requested_bundle_id = _normalized_bundle_id(payload.get("bundle_id"))
        cached_bundle_id = _normalized_bundle_id(cached.get("bundle_id"))
        if requested_bundle_id and requested_bundle_id != cached_bundle_id:
            return {}, "cua_background_app_mismatch"
        requested_app_name = _normalized_app_name(
            payload.get("expected_app_name")
            or payload.get("app_name")
            or payload.get("name")
        )
        cached_app_names = {
            _normalized_app_name(value)
            for value in _string_list(cached.get("app_names"))
            if _normalized_app_name(value)
        }
        if requested_app_name and requested_app_name not in cached_app_names:
            return {}, "cua_background_app_mismatch"
        pid = cached_pid
        window_id = explicit_window_id or _positive_int(cached.get("window_id"))
        target = {"pid": pid}
        if window_id is not None:
            target["window_id"] = window_id
        return target, ""

    def _resolve_task_target_window(
        self,
        tool_name: str,
        cua_tool_name: str,
        *,
        task_scope: str,
        remote_tools: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any] | None:
        """Bind an asynchronously-created window to an already-owned pid.

        ``launch_app`` may prove a new background process before WindowServer
        exposes its first top-level window.  Only the driver's pid-filtered
        ``list_windows`` result may complete that target; the adapter never
        falls back to a frontmost window or a model-supplied identifier.
        """

        cached = self._task_target_record(task_scope)
        pid = _positive_int(cached.get("pid"))
        if pid is None or cached.get("agent_owned_target") is not True:
            return self._target_failure(
                tool_name,
                error="cua_background_target_not_agent_owned",
                summary="The cached Cua process is not an agent-owned target.",
                cua_tool_name=cua_tool_name,
            )
        if _positive_int(cached.get("window_id")) is not None:
            return None

        list_windows_tool = remote_tools.get("list_windows")
        list_windows_properties = (
            _cua_tool_schema_properties(list_windows_tool)
            if isinstance(list_windows_tool, Mapping)
            else {}
        )
        if not isinstance(list_windows_tool, Mapping) or "pid" not in list_windows_properties:
            return self._failure(
                tool_name,
                status="provider_tool_unavailable",
                error="cua_background_window_resolution_unavailable",
                summary=(
                    "Cua Driver does not expose pid-filtered list_windows, which is "
                    "required to bind the launched background window."
                ),
                blocking_condition="desktop_execution_provider_tool_unavailable",
                retryable=False,
                cua_tool_name=cua_tool_name,
            )
        list_windows_arguments: dict[str, Any] = {"pid": pid}
        if "on_screen_only" in list_windows_properties:
            # Background-launched windows can be off the current Space.
            list_windows_arguments["on_screen_only"] = False
        unsupported_required = _missing_cua_required_arguments(
            list_windows_tool,
            list_windows_arguments,
        )
        if unsupported_required:
            return self._failure(
                tool_name,
                status="provider_tool_unavailable",
                error="cua_background_window_resolution_contract_unsupported",
                summary=(
                    "Cua list_windows requires unsupported argument(s): "
                    + ", ".join(unsupported_required)
                ),
                blocking_condition="desktop_execution_provider_tool_unavailable",
                retryable=False,
                cua_tool_name=cua_tool_name,
            )

        deadline = (
            time.monotonic() + _TASK_TARGET_WINDOW_RESOLUTION_TIMEOUT_SECONDS
        )
        last_ax_window_evidence_counts: dict[str, int] = {}
        while True:
            list_windows_result = self.client.call_tool(
                "list_windows",
                list_windows_arguments,
            )
            records, payload_valid = _cua_list_windows_payload(list_windows_result)
            if not payload_valid:
                return self._failure(
                    tool_name,
                    status="provider_tool_failed",
                    error="cua_background_window_resolution_result_invalid",
                    summary="Cua list_windows returned an invalid result.",
                    blocking_condition="desktop_execution_provider_tool_failed",
                    retryable=False,
                    cua_tool_name=cua_tool_name,
                    mcp_result=list_windows_result,
                )
            candidate_ids = sorted(
                {
                    window_id
                    for record in records
                    if _positive_int(record.get("pid")) == pid
                    and not _cua_empty_offscreen_strip_scaffold(record)
                    for window_id in (
                        _positive_int(
                            record.get("window_id") or record.get("windowId")
                        ),
                    )
                    if window_id is not None
                }
            )
            rejected_window_counts = _cua_window_rejection_counts(records, pid)
            ax_window_evidence_counts: dict[str, int] = {}
            if (
                len(candidate_ids) > 1
                and len(candidate_ids) <= _MAX_CUA_AX_WINDOW_VETTING_CANDIDATES
                and _cua_target_bound_snapshot_available(
                    remote_tools.get("get_window_state")
                )
            ):
                proven_candidate_ids: list[int] = []
                ax_window_evidence_counts = {
                    "content": 0,
                    "menu_bar_only": 0,
                    "unproven": 0,
                }
                for candidate_id in candidate_ids:
                    snapshot = self._target_bound_snapshot(
                        remote_tools["get_window_state"],
                        {"pid": pid, "window_id": candidate_id},
                    )
                    evidence = _cua_window_ax_evidence(
                        snapshot,
                        pid=pid,
                        window_id=candidate_id,
                    )
                    ax_window_evidence_counts[evidence] += 1
                    if evidence == "content":
                        proven_candidate_ids.append(candidate_id)
                last_ax_window_evidence_counts = {
                    key: value
                    for key, value in ax_window_evidence_counts.items()
                    if value
                }
                candidate_ids = proven_candidate_ids
            if len(candidate_ids) == 1:
                self._remember_task_target(
                    task_scope,
                    {**cached, "window_id": candidate_ids[0]},
                )
                return None
            if len(candidate_ids) > 1:
                self._remember_task_target(
                    task_scope,
                    {**cached, "ambiguous": True},
                )
                failure = self._target_failure(
                    tool_name,
                    error="cua_background_window_target_ambiguous",
                    summary=(
                        "The launched agent-owned process exposes multiple windows; "
                        "Oha will not guess which one to control."
                    ),
                    cua_tool_name=cua_tool_name,
                )
                failure["match_count"] = len(candidate_ids)
                if rejected_window_counts:
                    failure["rejected_window_counts"] = rejected_window_counts
                if last_ax_window_evidence_counts:
                    failure["ax_window_evidence_counts"] = (
                        last_ax_window_evidence_counts
                    )
                return failure
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._remember_task_target(
                    task_scope,
                    {
                        "_window_materialization_recovery_phase": (
                            "window_not_ready"
                        ),
                        "_window_materialization_recovery_expires_at": (
                            time.monotonic()
                            + _TASK_TARGET_WINDOW_MATERIALIZATION_RECOVERY_SECONDS
                        ),
                    },
                )
                failure = self._failure(
                    tool_name,
                    status="provider_target_unavailable",
                    error="cua_background_window_not_ready",
                    summary=(
                        "The agent-owned process started, but Cua did not expose a "
                        "target window before the bounded wait expired."
                    ),
                    blocking_condition="desktop_background_target_required",
                    retryable=True,
                    cua_tool_name=cua_tool_name,
                )
                failure["agent_owned_target"] = True
                failure["pid"] = pid
                if rejected_window_counts:
                    failure["rejected_window_counts"] = rejected_window_counts
                if last_ax_window_evidence_counts:
                    failure["ax_window_evidence_counts"] = (
                        last_ax_window_evidence_counts
                    )
                return failure
            time.sleep(
                min(_TASK_TARGET_WINDOW_RESOLUTION_POLL_SECONDS, remaining)
            )

    def _forget_task_target(self, task_scope: str) -> None:
        with self._target_lock:
            self._task_targets.pop(task_scope, None)

    def _remember_task_target_from_result(
        self,
        task_scope: str,
        result: Mapping[str, Any],
        *,
        launch_arguments: Mapping[str, Any],
        preflight_launch_identity: Mapping[str, Any],
        previous_target: Mapping[str, Any],
        agent_owned_target: bool,
    ) -> None:
        pid = _positive_int(result.get("pid"))
        if pid is None:
            return
        target: dict[str, Any] = {
            "pid": pid,
            "agent_owned_target": bool(agent_owned_target),
        }
        window_id = _positive_int(result.get("window_id"))
        if window_id is not None and _cua_empty_offscreen_strip_scaffold(result):
            window_id = None
        if window_id is None:
            windows = result.get("windows")
            if isinstance(windows, list):
                candidates = {
                    candidate
                    for item in windows
                    if isinstance(item, Mapping)
                    and _positive_int(item.get("pid")) == pid
                    and not _cua_empty_offscreen_strip_scaffold(item)
                    for candidate in (_positive_int(item.get("window_id")),)
                    if candidate is not None
                }
                if len(candidates) == 1:
                    window_id = next(iter(candidates))
        if window_id is not None:
            target["window_id"] = window_id
        bundle_id = next(
            (
                normalized
                for value in (
                    result.get("bundle_id"),
                    launch_arguments.get("bundle_id"),
                    preflight_launch_identity.get("bundle_id"),
                )
                if (normalized := _normalized_bundle_id(value))
            ),
            "",
        )
        if bundle_id:
            target["bundle_id"] = bundle_id
        app_names = _string_list(
            (
                _normalized_app_name(result.get("name")),
                _normalized_app_name(launch_arguments.get("name")),
                *(
                    _normalized_app_name(value)
                    for value in _string_list(
                        preflight_launch_identity.get("app_names")
                    )
                ),
            )
        )
        if app_names:
            target["app_names"] = app_names
        if previous_target and (
            previous_target.get("ambiguous") is True
            or not _same_cached_app_identity(previous_target, target)
        ):
            target["ambiguous"] = True
        if agent_owned_target:
            self._pin_task_scope(task_scope)
        self._remember_task_target(task_scope, target)

    def _pin_task_scope(self, task_scope: str) -> None:
        if not task_scope:
            return
        with self._target_lock:
            self._owned_task_scopes.add(task_scope)

    def _remember_task_target_from_arguments(
        self,
        task_scope: str,
        arguments: Mapping[str, Any],
    ) -> None:
        pid = _positive_int(arguments.get("pid"))
        if pid is None:
            return
        target = {"pid": pid}
        window_id = _positive_int(arguments.get("window_id"))
        if window_id is not None:
            target["window_id"] = window_id
        self._remember_task_target(task_scope, target)

    def _remember_task_target(
        self,
        task_scope: str,
        target: Mapping[str, Any],
    ) -> None:
        with self._target_lock:
            existing = dict(self._task_targets.get(task_scope) or {})
            existing.pop("_cached_at", None)
            self._task_targets.pop(task_scope, None)
            self._task_targets[task_scope] = {
                **existing,
                **dict(target),
                "_cached_at": time.monotonic(),
            }
            while len(self._task_targets) > _MAX_CACHED_TASK_TARGETS:
                oldest_scope = next(iter(self._task_targets))
                self._task_targets.pop(oldest_scope, None)

    def _task_target_record(self, task_scope: str) -> dict[str, Any]:
        with self._target_lock:
            cached = dict(self._task_targets.get(task_scope) or {})
            cached_at = cached.get("_cached_at")
            if (
                not isinstance(cached_at, (int, float))
                or isinstance(cached_at, bool)
                or time.monotonic() - float(cached_at) > _TASK_TARGET_TTL_SECONDS
            ):
                self._task_targets.pop(task_scope, None)
                return {}
            return cached

    def _verified_task_target_identity(
        self,
        tool_name: str,
        cua_tool_name: str,
        *,
        task_scope: str,
        remote_tools: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any] | None:
        cached = self._task_target_record(task_scope)
        pid = _positive_int(cached.get("pid"))
        bundle_id = _normalized_bundle_id(cached.get("bundle_id"))
        app_names = {
            _normalized_app_name(value)
            for value in _string_list(cached.get("app_names"))
            if _normalized_app_name(value)
        }
        if pid is None or (not bundle_id and not app_names):
            self._forget_task_target(task_scope)
            return self._target_failure(
                tool_name,
                error="cua_background_target_identity_required",
                summary="The cached Cua target has no verifiable app identity.",
                cua_tool_name=cua_tool_name,
            )
        if "list_apps" not in remote_tools:
            self._forget_task_target(task_scope)
            return self._target_failure(
                tool_name,
                error="cua_background_target_verification_required",
                summary="Cua list_apps is required to revalidate the target pid.",
                cua_tool_name=cua_tool_name,
            )
        list_result = self.client.call_tool("list_apps", {})
        matching_record = next(
            (
                item
                for item in _cua_list_apps_records(list_result)
                if _positive_int(item.get("pid")) == pid
                and item.get("running") is not False
            ),
            None,
        )
        record_bundle_id = _normalized_bundle_id(
            matching_record.get("bundle_id") if matching_record else None
        )
        record_app_name = _normalized_app_name(
            matching_record.get("name") if matching_record else None
        )
        identity_matches = bool(
            matching_record
            and (
                (bundle_id and record_bundle_id == bundle_id)
                or (not bundle_id and record_app_name in app_names)
            )
        )
        if identity_matches:
            return None
        self._forget_task_target(task_scope)
        return self._target_failure(
            tool_name,
            error="cua_background_target_identity_mismatch",
            summary="The cached pid no longer belongs to the launched app.",
            cua_tool_name=cua_tool_name,
        )

    def _target_failure(
        self,
        tool_name: str,
        *,
        error: str,
        summary: str,
        cua_tool_name: str,
    ) -> dict[str, Any]:
        target_reacquisition_required = error in _CUA_REACQUIRABLE_TARGET_ERRORS
        failure = self._failure(
            tool_name,
            status=(
                "provider_target_invalidated"
                if target_reacquisition_required
                else "provider_target_unavailable"
            ),
            error=error,
            summary=summary,
            blocking_condition="desktop_background_target_required",
            retryable=target_reacquisition_required,
            cua_tool_name=cua_tool_name,
        )
        if target_reacquisition_required:
            # The provider is healthy; only the task-owned process binding is
            # stale.  Let Runtime reopen a fresh isolated instance instead of
            # misrouting this through provider installation/permission repair.
            failure.update(
                {
                    "blocked_by_desktop_execution_provider": False,
                    "blocked_by_desktop_target": True,
                    "target_reacquisition_required": True,
                    "requires_user_handoff": False,
                    "recommended_tools": ["app.open"],
                }
            )
        else:
            failure["requires_user_handoff"] = True
        return failure

    def _failure(
        self,
        tool_name: str,
        *,
        status: str,
        error: str,
        summary: str,
        blocking_condition: str,
        retryable: bool,
        cua_tool_name: str = "",
        mcp_result: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "tool": tool_name,
            "action": tool_name,
            "status": status,
            "error": error,
            "summary": summary,
            "blocked_by_desktop_execution_provider": True,
            "blocking_condition": blocking_condition,
            "blocking_conditions": _string_list((status, blocking_condition)),
            "retryable": bool(retryable),
            "desktop_execution_provider_transport": self._transport_metadata(
                cua_tool_name=cua_tool_name
            ),
        }
        if mcp_result is not None:
            result["mcp_result"] = dict(mcp_result)
        return result

    def _health_payload(
        self,
        *,
        ok: bool,
        checked: bool,
        status: str,
        blocking_conditions: Iterable[str],
        error: str = "",
        supported_tools: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": bool(ok),
            "checked": bool(checked),
            "status": status,
            "provider_kind": self.provider_kind,
            "provider_id": self.provider_id,
            "blocking_conditions": _string_list(blocking_conditions),
            "supported_tools": _string_list(supported_tools),
            "capabilities": _background_capabilities(),
            "transport": self.client.transport_kind,
            **_background_status_fields(),
        }
        if error:
            result["error"] = error
        return result

    def _transport_metadata(self, *, cua_tool_name: str = "") -> dict[str, Any]:
        result = {
            "provider_kind": self.provider_kind,
            "provider_id": self.provider_id,
            "transport": self.client.transport_kind,
            "delivery_mode": self.delivery_mode,
            "foreground_takeover_required": False,
        }
        if cua_tool_name:
            result["mcp_tool"] = cua_tool_name
        return result


def _electron_bridge_configuration_from_env(
    environ: Mapping[str, str] | None,
) -> _CuaElectronBridgeConfiguration | None:
    environment = dict(os.environ)
    environment.update(
        {str(key): str(value) for key, value in (environ or {}).items()}
    )
    if CUA_MCP_TRANSPORT_ENV not in environment:
        return None
    if environment.get(CUA_MCP_TRANSPORT_ENV) != _CUA_ELECTRON_BRIDGE_TRANSPORT:
        raise _CuaElectronBridgeConfigurationError(
            "Unsupported Electron Cua MCP bridge transport"
        )
    bridge_url = str(environment.get(CUA_MCP_BRIDGE_URL_ENV) or "")
    url_match = _CUA_ELECTRON_BRIDGE_URL_RE.fullmatch(bridge_url)
    if url_match is None:
        raise _CuaElectronBridgeConfigurationError(
            "Invalid Electron Cua MCP bridge URL"
        )
    port = int(url_match.group(1))
    if not 1 <= port <= 65535:
        raise _CuaElectronBridgeConfigurationError(
            "Invalid Electron Cua MCP bridge port"
        )
    token = str(environment.get(CUA_MCP_BRIDGE_TOKEN_ENV) or "")
    if _CUA_ELECTRON_BRIDGE_TOKEN_RE.fullmatch(token) is None:
        raise _CuaElectronBridgeConfigurationError(
            "Invalid Electron Cua MCP bridge token"
        )
    generation = str(environment.get(CUA_MCP_BRIDGE_GENERATION_ENV) or "")
    if _CUA_ELECTRON_BRIDGE_GENERATION_RE.fullmatch(generation) is None:
        raise _CuaElectronBridgeConfigurationError(
            "Invalid Electron Cua MCP bridge generation"
        )
    return _CuaElectronBridgeConfiguration(
        host="127.0.0.1",
        port=port,
        token=token,
        generation=generation,
    )


def _electron_bridge_unavailable_status() -> dict[str, Any]:
    blocking_conditions = ["cua_electron_bridge_unavailable"]
    health = {
        "ok": False,
        "checked": False,
        "status": "electron_bridge_unavailable",
        "provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
        "provider_id": CUA_BACKGROUND_PROVIDER_ID,
        "blocking_conditions": blocking_conditions,
        "supported_tools": [],
        "capabilities": _background_capabilities(),
        "transport": "electron_bridge",
        **_background_status_fields(),
    }
    return {
        "configured": True,
        "available": False,
        "adapter_ready": False,
        "provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
        "provider_id": CUA_BACKGROUND_PROVIDER_ID,
        "authentication_configured": False,
        "status": "electron_bridge_unavailable",
        "setup_state": "unavailable",
        "reason": "The Electron-owned Cua MCP bridge configuration is unavailable.",
        "blocking_conditions": blocking_conditions,
        "supported_tools": list(DEFAULT_CUA_TOOL_NAME_MAP),
        "capabilities": _background_capabilities(),
        "health": health,
        "source": "cua_mcp_electron_bridge",
        "transport": "electron_bridge",
        **_background_status_fields(),
    }


def resolve_cua_mcp_command(
    environ: Mapping[str, str] | None = None,
    *,
    run: Callable[..., Any] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    path_exists: Callable[[str], bool] = os.path.isfile,
) -> tuple[str, ...] | None:
    """Resolve Cua's MCP invocation without starting the MCP server.

    An explicit command is authoritative.  For discovered binaries, the
    driver's own manifest is preferred so application-bundle installations can
    redirect to their canonical executable and stdio arguments.
    """

    environment = dict(os.environ)
    environment.update(
        {str(key): str(value) for key, value in (environ or {}).items()}
    )
    # Presence of the transport sentinel is authoritative. Packaged builds must
    # never escape to PATH discovery or an externally configured driver when
    # the Electron-owned bridge contract is incomplete or malformed.
    if CUA_MCP_TRANSPORT_ENV in environment:
        return None
    if CUA_DRIVER_PATH_ENV in environment:
        embedded_path = str(environment.get(CUA_DRIVER_PATH_ENV) or "").strip()
        if not embedded_path or not path_exists(embedded_path):
            return None
        command = (embedded_path, "mcp", "--embedded")
        host_bundle_id = str(
            environment.get(CUA_HOST_BUNDLE_ID_ENV) or ""
        ).strip()
        if host_bundle_id:
            command = (*command, "--host-bundle-id", host_bundle_id)
        return command

    explicit_command = str(environment.get(CUA_DRIVER_COMMAND_ENV) or "").strip()
    if explicit_command:
        try:
            parsed = tuple(shlex.split(explicit_command))
        except ValueError:
            return None
        return parsed or None

    executable = str(which("cua-driver") or "").strip()
    if not executable:
        home = str(environment.get("HOME") or Path.home()).strip()
        candidates = [str(Path(home) / relative) for relative in _COMMON_CUA_DRIVER_PATHS]
        candidates.extend(_SYSTEM_CUA_DRIVER_PATHS)
        executable = next(
            (candidate for candidate in candidates if path_exists(candidate)),
            "",
        )
    if not executable:
        return None

    cache_key = _cua_command_cache_key(
        executable,
        environment=environment,
        run=run,
    )
    cached_command = _cached_cua_command(cache_key)
    if cached_command is not None:
        return cached_command
    with _CUA_DISCOVERY_CACHE_LOCK:
        cached_command = _cached_cua_command_locked(cache_key)
        if cached_command is not None:
            return cached_command
        manifest_invocation = _cua_manifest_mcp_invocation(
            executable,
            environ=environment,
            run=run,
        )
        command = manifest_invocation or (executable, "mcp")
        _store_cua_command_locked(cache_key, command)
        return command


def cua_background_provider_adapter_from_env(
    environ: Mapping[str, str] | None = None,
    *,
    run: Callable[..., Any] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    path_exists: Callable[[str], bool] = os.path.isfile,
    popen_factory: Callable[..., Any] = subprocess.Popen,
    timeout: float = 20.0,
) -> CuaBackgroundDesktopExecutionProviderAdapter | None:
    """Create a lazy Cua adapter when the driver can be discovered."""

    try:
        bridge_configuration = _electron_bridge_configuration_from_env(environ)
    except _CuaElectronBridgeConfigurationError:
        return None
    if bridge_configuration is not None:
        return CuaBackgroundDesktopExecutionProviderAdapter(
            CuaMcpClient(
                command=("electron-cua-mcp-bridge",),
                environ=None,
                timeout=timeout,
                transport_factory=lambda: _CuaMcpElectronBridgeTransport(
                    configuration=bridge_configuration,
                    connect_timeout=timeout,
                ),
                transport_kind="electron_bridge",
                transport_identity=bridge_configuration.transport_identity,
            )
        )

    command = resolve_cua_mcp_command(
        environ,
        run=run,
        which=which,
        path_exists=path_exists,
    )
    if command is None:
        return None
    return CuaBackgroundDesktopExecutionProviderAdapter(
        CuaMcpClient(
            command=command,
            environ=environ,
            timeout=timeout,
            popen_factory=popen_factory,
        )
    )


def cua_background_provider_status(
    environ: Mapping[str, str] | None = None,
    *,
    probe_health: bool = False,
    refresh_health: bool = False,
    run: Callable[..., Any] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    path_exists: Callable[[str], bool] = os.path.isfile,
    popen_factory: Callable[..., Any] = subprocess.Popen,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Report optional-provider readiness; MCP remains lazy by default."""

    try:
        _electron_bridge_configuration_from_env(environ)
    except _CuaElectronBridgeConfigurationError:
        return _electron_bridge_unavailable_status()

    adapter = cua_background_provider_adapter_from_env(
        environ,
        run=run,
        which=which,
        path_exists=path_exists,
        popen_factory=popen_factory,
        timeout=timeout,
    )
    if adapter is None:
        health = {
            "ok": False,
            "checked": False,
            "status": "not_installed",
            "provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
            "provider_id": CUA_BACKGROUND_PROVIDER_ID,
            "blocking_conditions": ["cua_driver_not_installed"],
            "supported_tools": [],
            "capabilities": _background_capabilities(),
            **_background_status_fields(),
        }
        return {
            "configured": False,
            "available": False,
            "adapter_ready": False,
            "provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
            "provider_id": CUA_BACKGROUND_PROVIDER_ID,
            "authentication_configured": False,
            "status": "provider_required",
            "setup_state": "required",
            "reason": "Cua Driver is required for background desktop control.",
            "blocking_conditions": ["cua_driver_not_installed"],
            "supported_tools": list(DEFAULT_CUA_TOOL_NAME_MAP),
            "capabilities": _background_capabilities(),
            "health": health,
            "source": "cua_driver_discovery",
            **_background_status_fields(),
        }
    cache_key = _cua_health_cache_key(
        adapter.client.command,
        transport_kind=adapter.client.transport_kind,
        transport_identity=adapter.client.transport_identity,
        environ=environ,
        popen_factory=popen_factory,
    )
    try:
        status = (
            None
            if refresh_health
            else _cached_cua_health_status(cache_key)
        )
        if status is None:
            status = adapter.configured_status(probe_health=probe_health)
            if probe_health:
                _store_cua_health_status(cache_key, status)
        else:
            health = status.get("health")
            if isinstance(health, dict):
                health["cached"] = True
    finally:
        adapter.close()
    status["setup_state"] = (
        "ready"
        if status.get("available")
        else "unavailable"
        if status.get("status") == "electron_bridge_unavailable"
        else "installed"
    )
    status["source"] = (
        "cua_mcp_electron_bridge"
        if adapter.client.transport_kind == "electron_bridge"
        else "cua_driver_discovery"
    )
    return status


def invalidate_cua_background_provider_caches() -> None:
    """Invalidate discovery/readiness state after install or permission changes."""

    with _CUA_DISCOVERY_CACHE_LOCK:
        _CUA_COMMAND_CACHE.clear()
        _CUA_HEALTH_STATUS_CACHE.clear()


def _cua_command_cache_key(
    executable: str,
    *,
    environment: Mapping[str, str],
    run: Callable[..., Any],
) -> tuple[Any, ...]:
    return (
        str(executable),
        _cua_executable_change_token(executable),
        str(environment.get("HOME") or ""),
        str(environment.get("PATH") or ""),
        _callable_cache_identity(run),
    )


def _cua_health_cache_key(
    command: Sequence[str],
    *,
    transport_kind: str = "mcp_stdio",
    transport_identity: Sequence[str] | None = None,
    environ: Mapping[str, str] | None,
    popen_factory: Callable[..., Any],
) -> tuple[Any, ...]:
    environment = dict(os.environ)
    environment.update(
        {str(key): str(value) for key, value in (environ or {}).items()}
    )
    return (
        str(transport_kind),
        tuple(
            str(part)
            for part in (transport_identity if transport_identity is not None else command)
        ),
        str(environment.get("HOME") or ""),
        str(environment.get("PATH") or ""),
        _callable_cache_identity(popen_factory),
    )


def _callable_cache_identity(value: Any) -> Any:
    try:
        hash(value)
    except TypeError:
        return (type(value).__qualname__, id(value))
    return value


def _cua_executable_change_token(executable: str) -> tuple[int, int, int, int]:
    try:
        stat = os.stat(executable)
    except OSError:
        return (0, 0, 0, 0)
    return (
        int(stat.st_dev),
        int(stat.st_ino),
        int(stat.st_size),
        int(stat.st_mtime_ns),
    )


def _cached_cua_command(
    cache_key: tuple[Any, ...],
) -> tuple[str, ...] | None:
    with _CUA_DISCOVERY_CACHE_LOCK:
        return _cached_cua_command_locked(cache_key)


def _cached_cua_command_locked(
    cache_key: tuple[Any, ...],
) -> tuple[str, ...] | None:
    entry = _CUA_COMMAND_CACHE.get(cache_key)
    if entry is None:
        return None
    expires_at, command = entry
    if expires_at <= time.monotonic():
        _CUA_COMMAND_CACHE.pop(cache_key, None)
        return None
    return tuple(command)


def _store_cua_command_locked(
    cache_key: tuple[Any, ...],
    command: Sequence[str],
) -> None:
    _prune_cua_cache_locked(_CUA_COMMAND_CACHE)
    _CUA_COMMAND_CACHE[cache_key] = (
        time.monotonic() + _CUA_COMMAND_CACHE_TTL_SECONDS,
        tuple(str(part) for part in command),
    )


def _cached_cua_health_status(
    cache_key: tuple[Any, ...],
) -> dict[str, Any] | None:
    with _CUA_DISCOVERY_CACHE_LOCK:
        entry = _CUA_HEALTH_STATUS_CACHE.get(cache_key)
        if entry is None:
            return None
        expires_at, status = entry
        if expires_at <= time.monotonic():
            _CUA_HEALTH_STATUS_CACHE.pop(cache_key, None)
            return None
        return copy.deepcopy(status)


def _store_cua_health_status(
    cache_key: tuple[Any, ...],
    status: Mapping[str, Any],
) -> None:
    with _CUA_DISCOVERY_CACHE_LOCK:
        _prune_cua_cache_locked(_CUA_HEALTH_STATUS_CACHE)
        _CUA_HEALTH_STATUS_CACHE[cache_key] = (
            time.monotonic() + _CUA_HEALTH_CACHE_TTL_SECONDS,
            copy.deepcopy(dict(status)),
        )


def _prune_cua_cache_locked(cache: dict[Any, Any]) -> None:
    now = time.monotonic()
    for key, entry in list(cache.items()):
        if isinstance(entry, tuple) and entry and float(entry[0]) <= now:
            cache.pop(key, None)
    while len(cache) >= _MAX_CUA_DISCOVERY_CACHE_ENTRIES:
        cache.pop(next(iter(cache)))


def _cua_health_report_arguments(
    remote_tool: Mapping[str, Any],
    *,
    skip_bundle_identity: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    properties = _cua_tool_schema_properties(remote_tool)
    arguments = {"prompt": False} if "prompt" in properties else {}
    if skip_bundle_identity and "skip" in properties:
        arguments["skip"] = ["bundle_identity"]
    missing = [
        name
        for name in _missing_cua_required_arguments(remote_tool, arguments)
        if name not in arguments
    ]
    return arguments, missing


def _cua_health_report_readiness(
    mcp_result: Mapping[str, Any],
) -> tuple[bool, list[str], dict[str, Any]]:
    report = _preferred_mcp_tool_result(mcp_result)
    blockers = _cua_health_report_blockers(report)
    ready_signal: bool | None = None
    overall = str(report.get("overall") or "").strip().lower().replace("-", "_")
    has_canonical_overall = bool(overall)
    if overall == "ok":
        ready_signal = True
    elif overall in {"degraded", "failed"}:
        ready_signal = False
    if not has_canonical_overall:
        for key in ("ready", "healthy", "available", "ok"):
            if isinstance(report.get(key), bool):
                ready_signal = bool(report[key])
                break
        status = str(report.get("status") or "").strip().lower().replace("-", "_")
        if status in {"healthy", "ok", "ready", "available"}:
            ready_signal = True
        elif status in {
            "blocked",
            "degraded",
            "error",
            "not_ready",
            "unavailable",
            "unhealthy",
        }:
            ready_signal = False
    permissions = report.get("permissions")
    if isinstance(permissions, Mapping):
        for name, value in permissions.items():
            granted = (
                value.get("granted")
                if isinstance(value, Mapping)
                else value
            )
            if granted is False:
                blockers.append(
                    "desktop_permission_"
                    + str(name).strip().lower().replace(" ", "_")
                    + "_required"
                )
    blockers.extend(_cua_health_check_blockers(report.get("checks")))
    blockers = _string_list(blockers)
    ready = ready_signal is True and not blockers
    if not ready and not blockers:
        blockers = ["desktop_execution_provider_not_ready"]
    return ready, blockers, report


def _cua_health_check_blockers(checks: Any) -> list[str]:
    items: list[tuple[str, Any]] = []
    if isinstance(checks, Mapping):
        items.extend((str(name), value) for name, value in checks.items())
    elif isinstance(checks, Sequence) and not isinstance(
        checks,
        (str, bytes, bytearray),
    ):
        for index, value in enumerate(checks):
            name = (
                str(value.get("name") or value.get("id") or index)
                if isinstance(value, Mapping)
                else str(index)
            )
            items.append((name, value))
    blockers: list[str] = []
    for fallback_name, value in items:
        if not isinstance(value, Mapping):
            continue
        status = str(value.get("status") or "").strip().lower().replace("-", "_")
        check_failed = value.get("ok") is False or status in {
            "error",
            "fail",
            "failed",
        }
        if not check_failed:
            continue
        name = str(value.get("name") or value.get("id") or fallback_name).strip()
        blockers.append(
            "cua_health_check_"
            + name.lower().replace(" ", "_")
            + "_failed"
        )
    return blockers


def _cua_health_report_blockers(report: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    for key in (
        "blocking_conditions",
        "blockers",
        "missing_permissions",
        "issues",
    ):
        value = report.get(key)
        if isinstance(value, str):
            blockers.extend(_string_list(value))
        elif isinstance(value, Sequence) and not isinstance(
            value,
            (str, bytes, bytearray),
        ):
            for item in value:
                if isinstance(item, Mapping):
                    clean = str(
                        item.get("code")
                        or item.get("name")
                        or item.get("message")
                        or ""
                    ).strip()
                else:
                    clean = str(item or "").strip()
                if clean:
                    blockers.append(clean)
    return blockers


def _cua_manifest_mcp_invocation(
    executable: str,
    *,
    environ: Mapping[str, str],
    run: Callable[..., Any],
) -> tuple[str, ...] | None:
    try:
        completed = run(
            [executable, "manifest"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3.0,
            env=_cua_subprocess_environ(environ),
        )
    except (OSError, subprocess.SubprocessError, TypeError, ValueError):
        return None
    if int(getattr(completed, "returncode", 0) or 0) != 0:
        return None
    stdout = getattr(completed, "stdout", "")
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    try:
        manifest = json.loads(str(stdout or ""))
    except (TypeError, ValueError):
        return None
    if not isinstance(manifest, Mapping):
        return None
    invocation = manifest.get("mcp_invocation")
    if invocation is None and isinstance(manifest.get("mcp"), Mapping):
        invocation = manifest["mcp"].get("invocation")
    return _parse_manifest_invocation(invocation, executable=executable)


def _parse_manifest_invocation(
    invocation: Any,
    *,
    executable: str,
) -> tuple[str, ...] | None:
    if isinstance(invocation, str):
        try:
            parts = tuple(shlex.split(invocation))
        except ValueError:
            return None
    elif isinstance(invocation, Sequence) and not isinstance(
        invocation, (str, bytes, bytearray)
    ):
        parts = tuple(str(part) for part in invocation)
    elif isinstance(invocation, Mapping):
        command = str(invocation.get("command") or "").strip()
        args = invocation.get("args")
        if not command or not isinstance(args, Sequence) or isinstance(
            args, (str, bytes, bytearray)
        ):
            return None
        parts = (command, *(str(arg) for arg in args))
    else:
        return None
    if not parts or not all(str(part).strip() for part in parts):
        return None
    first = str(parts[0])
    if first == "cua-driver":
        parts = (executable, *parts[1:])
    return tuple(parts)


def _cua_subprocess_environ(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environment = scrubbed_subprocess_env(
        {str(key): str(value) for key, value in (environ or {}).items()}
    )
    environment[CUA_TELEMETRY_ENV] = "0"
    return environment


def _preferred_mcp_tool_result(mcp_result: Mapping[str, Any]) -> dict[str, Any]:
    structured_content = mcp_result.get("structuredContent")
    if isinstance(structured_content, Mapping):
        return dict(structured_content)
    if structured_content is not None:
        return {"structured_content": structured_content}
    content = mcp_result.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, Mapping) or item.get("type") != "text":
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            try:
                decoded = json.loads(text)
            except (TypeError, ValueError):
                continue
            if isinstance(decoded, Mapping):
                return dict(decoded)
    return {"content": content} if content is not None else {}


def _mcp_result_message(result: Mapping[str, Any]) -> str:
    structured_content = result.get("structuredContent")
    if isinstance(structured_content, Mapping):
        for key in ("summary", "message", "error"):
            value = str(structured_content.get(key) or "").strip()
            if value:
                return value
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, Mapping) and item.get("type") == "text":
                value = str(item.get("text") or "").strip()
                if value:
                    return value
    return ""


def _cua_effect(result: Mapping[str, Any]) -> str:
    return str(result.get("effect") or "").strip().lower().replace("-", "_")


def _pending_window_materialization_recovery_allows(
    tool_name: str,
    payload: Mapping[str, Any],
    *,
    target: Mapping[str, Any],
) -> bool:
    target_pid = _positive_int(target.get("pid"))
    expires_at = target.get("_window_materialization_recovery_expires_at")
    if (
        target.get("agent_owned_target") is not True
        or target_pid is None
        or _positive_int(target.get("window_id")) is not None
        or not isinstance(expires_at, (int, float))
        or isinstance(expires_at, bool)
        or time.monotonic() > float(expires_at)
    ):
        return False
    phase = str(
        target.get("_window_materialization_recovery_phase") or ""
    ).strip()
    if phase == "delivery_dispatched":
        return tool_name in _CUA_TARGET_BOUND_OBSERVATION_TOOLS
    if phase != "window_not_ready" or tool_name != "desktop.safe_shortcut":
        return False
    action = (
        str(payload.get("action") or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )
    return action in _WINDOW_MATERIALIZATION_SHORTCUT_ACTIONS


def _pending_window_materialization_delivery(
    tool_name: str,
    payload: Mapping[str, Any],
    *,
    result: Mapping[str, Any],
    effect: str,
    target: Mapping[str, Any],
    arguments: Mapping[str, Any],
) -> bool:
    """Allow observation to finish a pid-bound first-window recovery.

    An acknowledged background Cmd-N-style delivery is not proof that a
    window exists.  It is only a safe intermediate receipt when launch has
    already established an agent-owned pid for the same private task scope and
    no window has been bound yet.
    """

    target_pid = _positive_int(target.get("pid"))
    return bool(
        _pending_window_materialization_recovery_allows(
            tool_name,
            payload,
            target=target,
        )
        and result.get("ok") is True
        and effect != "suspected_noop"
        and (effect == "unverifiable" or result.get("verified") is False)
        and target.get("agent_owned_target") is True
        and target_pid is not None
        and _positive_int(target.get("window_id")) is None
        and _positive_int(arguments.get("pid")) == target_pid
        and _positive_int(arguments.get("window_id")) is None
        and arguments.get("delivery_mode") == "background"
    )


_CUA_VOLATILE_SNAPSHOT_KEYS = {
    "captured_at",
    "capture_time",
    "duration_ms",
    "elapsed_ms",
    "timestamp",
}


def _cua_snapshot_digest(snapshot: Mapping[str, Any]) -> str:
    stable_snapshot = _stable_cua_snapshot_value(snapshot)
    encoded = json.dumps(
        stable_snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _stable_cua_snapshot_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _stable_cua_snapshot_value(item)
            for key, item in value.items()
            if str(key).strip().lower() not in _CUA_VOLATILE_SNAPSHOT_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_stable_cua_snapshot_value(item) for item in value]
    return value


def _cua_list_apps_records(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    records, _valid = _cua_list_apps_payload(result)
    return records


def _cua_list_windows_payload(
    result: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    structured = result.get("structuredContent")
    if isinstance(structured, list):
        return (
            [dict(item) for item in structured if isinstance(item, Mapping)],
            True,
        )
    if isinstance(structured, Mapping):
        for key in ("windows", "items", "data"):
            value = structured.get(key)
            if isinstance(value, list):
                return (
                    [dict(item) for item in value if isinstance(item, Mapping)],
                    True,
                )
            if isinstance(value, Mapping):
                nested_windows = value.get("windows")
                if isinstance(nested_windows, list):
                    return (
                        [
                            dict(item)
                            for item in nested_windows
                            if isinstance(item, Mapping)
                        ],
                        True,
                    )
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, Mapping) or item.get("type") != "text":
                continue
            try:
                decoded = json.loads(str(item.get("text") or ""))
            except (TypeError, ValueError):
                continue
            if isinstance(decoded, list):
                return (
                    [dict(value) for value in decoded if isinstance(value, Mapping)],
                    True,
                )
            if isinstance(decoded, Mapping):
                decoded_windows = decoded.get("windows")
                if isinstance(decoded_windows, list):
                    return (
                        [
                            dict(value)
                            for value in decoded_windows
                            if isinstance(value, Mapping)
                        ],
                        True,
                    )
    return [], False


def _cua_empty_offscreen_strip_scaffold(record: Mapping[str, Any]) -> bool:
    """Recognize only Cua's non-content WindowServer strip scaffolding.

    This deliberately requires every observed invariant.  In particular, an
    off-screen or untitled application window alone remains a viable target.
    """

    title = record.get("title")
    on_screen = record.get("is_on_screen", record.get("isOnScreen"))
    layer = record.get("layer")
    bounds = record.get("bounds")
    if title != "" or on_screen is not False:
        return False
    if isinstance(layer, bool) or not isinstance(layer, (int, float)) or layer != 0:
        return False
    if not isinstance(bounds, Mapping):
        return False
    width = _positive_dimension(bounds.get("width"))
    height = _positive_dimension(bounds.get("height"))
    return (
        width is not None
        and height is not None
        and width >= 1000
        and height <= 64
        and width >= height * 20
    )


def _cua_window_rejection_counts(
    records: Iterable[Mapping[str, Any]],
    pid: int,
) -> dict[str, int]:
    strip_count = sum(
        1
        for record in records
        if _positive_int(record.get("pid")) == pid
        and _cua_empty_offscreen_strip_scaffold(record)
    )
    return {"empty_offscreen_strip": strip_count} if strip_count else {}


def _cua_target_bound_snapshot_available(remote_tool: Any) -> bool:
    return isinstance(remote_tool, Mapping) and {"pid", "window_id"}.issubset(
        _cua_tool_schema_properties(remote_tool)
    )


def _cua_window_ax_evidence(
    snapshot: Mapping[str, Any] | None,
    *,
    pid: int,
    window_id: int,
) -> str:
    """Classify target-bound AX evidence without inferring from window metadata."""

    if (
        not isinstance(snapshot, Mapping)
        or _positive_int(snapshot.get("pid")) != pid
        or _positive_int(snapshot.get("window_id") or snapshot.get("windowId"))
        != window_id
    ):
        return "unproven"
    roles = _cua_snapshot_ax_roles(snapshot)
    if "axwindow" in roles:
        return "content"
    if "axmenubar" in roles:
        return "menu_bar_only"
    return "unproven"


def _cua_snapshot_ax_roles(snapshot: Mapping[str, Any]) -> set[str]:
    roots: list[Any] = []
    for key in ("roots", "elements"):
        value = snapshot.get(key)
        if isinstance(value, list):
            roots.extend(value)
        elif isinstance(value, Mapping):
            roots.append(value)
    accessibility_tree = snapshot.get("accessibility_tree")
    if isinstance(accessibility_tree, Mapping):
        for key in ("roots", "elements"):
            value = accessibility_tree.get(key)
            if isinstance(value, list):
                roots.extend(value)
            elif isinstance(value, Mapping):
                roots.append(value)
    roles: set[str] = set()
    pending = [item for item in roots if isinstance(item, Mapping)]
    while pending:
        element = pending.pop()
        role = str(element.get("role") or "").strip().lower()
        if role:
            roles.add(role)
        for key in ("children", "elements", "children_elements"):
            children = element.get(key)
            if isinstance(children, list):
                pending.extend(item for item in children if isinstance(item, Mapping))
    return roles


def _positive_dimension(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric_value = float(value)
    return numeric_value if numeric_value > 0 else None


def _cua_list_apps_payload(
    result: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    structured = result.get("structuredContent")
    if isinstance(structured, list):
        return (
            [dict(item) for item in structured if isinstance(item, Mapping)],
            True,
        )
    elif isinstance(structured, Mapping):
        for key in ("apps", "applications", "items", "data"):
            value = structured.get(key)
            if isinstance(value, list):
                return (
                    [dict(item) for item in value if isinstance(item, Mapping)],
                    True,
                )
            if isinstance(value, Mapping):
                nested_apps = value.get("apps")
                if isinstance(nested_apps, list):
                    return (
                        [
                            dict(item)
                            for item in nested_apps
                            if isinstance(item, Mapping)
                        ],
                        True,
                    )
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, Mapping) or item.get("type") != "text":
                continue
            try:
                decoded = json.loads(str(item.get("text") or ""))
            except (TypeError, ValueError):
                continue
            if isinstance(decoded, list):
                return (
                    [dict(value) for value in decoded if isinstance(value, Mapping)],
                    True,
                )
            if isinstance(decoded, Mapping):
                decoded_apps = decoded.get("apps")
                if isinstance(decoded_apps, list):
                    return (
                        [
                            dict(value)
                            for value in decoded_apps
                            if isinstance(value, Mapping)
                        ],
                        True,
                    )
    return [], False


def _cua_running_app_pids(result: Mapping[str, Any]) -> set[int] | None:
    records, valid = _cua_list_apps_payload(result)
    if not valid:
        return None
    pids: set[int] = set()
    for record in records:
        if record.get("running") is False:
            continue
        pid = _positive_int(record.get("pid"))
        if pid is not None:
            pids.add(pid)
    return pids


def _cua_launch_identity_from_list_apps(
    result: Mapping[str, Any],
    launch_request: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve one exact installed-app identity before crossing launch."""

    records, valid = _cua_list_apps_payload(result)
    if not valid:
        return {}
    requested_bundle_id = _normalized_bundle_id(
        launch_request.get("bundle_id")
    )
    requested_name = _normalized_app_name(
        launch_request.get("app_name") or launch_request.get("name")
    )
    if not requested_bundle_id and not requested_name:
        return {}

    matched_identities: list[tuple[str, set[str], set[int], set[int]]] = []
    for record in records:
        bundle_id = _normalized_bundle_id(
            record.get("bundle_id") or record.get("bundleIdentifier")
        )
        if not bundle_id:
            continue
        app_names = {
            normalized
            for value in (record.get("name"), record.get("display_name"))
            if (normalized := _normalized_app_name(value))
        }
        for path_key in (
            "launch_path",
            "path",
            "bundlePath",
            "executable_path",
        ):
            path_value = record.get(path_key)
            if isinstance(path_value, (Mapping, list, tuple, set)):
                continue
            path_name = str(path_value or "").strip().rstrip("/").rsplit("/", 1)[-1]
            normalized_path_name = _normalized_app_name(path_name)
            if normalized_path_name:
                app_names.add(normalized_path_name)
        if requested_bundle_id:
            matches = bundle_id == requested_bundle_id
        else:
            matches = requested_name in app_names
        if matches:
            pid = _positive_int(record.get("pid"))
            running_pids = (
                {pid}
                if pid is not None and record.get("running") is not False
                else set()
            )
            active_pids = (
                {pid}
                if pid is not None and record.get("active") is True
                else set()
            )
            matched_identities.append(
                (bundle_id, app_names, running_pids, active_pids)
            )

    bundle_ids = {
        bundle_id for bundle_id, _names, _running, _active in matched_identities
    }
    if len(bundle_ids) != 1:
        # An exact display-name collision is still ambiguous.  Never guess
        # which installed bundle Cua will launch.
        return {}
    bundle_id = next(iter(bundle_ids))
    app_names = sorted(
        {
            name
            for candidate_bundle_id, names, _running, _active in matched_identities
            if candidate_bundle_id == bundle_id
            for name in names
        }
    )
    running_pids = sorted(
        {
            pid
            for candidate_bundle_id, _names, running, _active in matched_identities
            if candidate_bundle_id == bundle_id
            for pid in running
        }
    )
    active_pids = sorted(
        {
            pid
            for candidate_bundle_id, _names, _running, active in matched_identities
            if candidate_bundle_id == bundle_id
            for pid in active
        }
    )
    if requested_name:
        app_names = _string_list((requested_name, *app_names))
    return {
        "bundle_id": bundle_id,
        "running_pids": running_pids,
        "active_pids": active_pids,
        **({"app_names": app_names} if app_names else {}),
    }


def _normalized_cua_target_bound_observation_result(
    tool_name: str,
    mcp_result: Mapping[str, Any],
    *,
    payload: Mapping[str, Any],
    target: Mapping[str, Any],
    tool_request: Mapping[str, Any],
    route: Mapping[str, Any],
    provider_kind: str,
    provider_id: str,
) -> dict[str, Any]:
    """Project one agent-owned Cua window into Oha's readonly tool contracts.

    A background snapshot is useful only when the response repeats the exact
    pid/window pair established by this run's launch receipt.  Missing or
    mismatched identity fails closed so a verifier can never fall through to,
    or be confused with, the user's foreground desktop.
    """

    raw = _preferred_mcp_tool_result(mcp_result)
    if raw.get("ok") is False:
        return raw
    raw_data = raw.get("data") if isinstance(raw.get("data"), Mapping) else raw
    target_pid = _positive_int(target.get("pid"))
    target_window_id = _positive_int(target.get("window_id"))
    observed_pid = _positive_int(raw_data.get("pid"))
    observed_window_id = _positive_int(
        raw_data.get("window_id") or raw_data.get("windowId")
    )
    target_owned = target.get("agent_owned_target") is True
    if (
        not target_owned
        or target_pid is None
        or target_window_id is None
        or observed_pid != target_pid
        or observed_window_id != target_window_id
    ):
        return {
            "ok": False,
            "status": "provider_result_invalid",
            "error": "cua_window_state_target_mismatch",
            "summary": (
                "Cua returned a window snapshot that was not bound to this "
                "run's agent-owned background target."
            ),
            "blocking_conditions": ["desktop_background_target_required"],
            "requires_user_handoff": True,
            "agent_owned_target": target_owned,
            "data": {
                "expected_pid": target_pid,
                "expected_window_id": target_window_id,
                "observed_pid": observed_pid,
                "observed_window_id": observed_window_id,
            },
        }

    target_names = _string_list(target.get("app_names"))
    observed_app_name = str(
        raw_data.get("app_name")
        or raw_data.get("application_name")
        or raw_data.get("name")
        or ""
    ).strip()
    trusted_app_name = observed_app_name or (
        target_names[0] if target_names else ""
    )
    app_name = str(
        observed_app_name
        or payload.get("app_name")
        or (target_names[0] if target_names else "")
    ).strip()
    title = str(
        raw_data.get("title")
        or raw_data.get("window_title")
        or raw_data.get("name")
        or ""
    ).strip()
    raw_elements = raw_data.get("elements")
    if not isinstance(raw_elements, list):
        accessibility = raw_data.get("accessibility_tree")
        raw_elements = (
            accessibility.get("elements")
            if isinstance(accessibility, Mapping)
            and isinstance(accessibility.get("elements"), list)
            else []
        )
    elements = [dict(item) for item in raw_elements if isinstance(item, Mapping)]
    role_filter = _normalized_cua_element_role(payload.get("role_filter"))
    if role_filter:
        elements = [
            item
            for item in elements
            if role_filter
            in _normalized_cua_element_role(
                item.get("role") or item.get("role_description")
            )
        ]
    requested_limit = _positive_int(payload.get("limit")) or 80
    elements = elements[: min(requested_limit, 200)]

    window = {
        "pid": target_pid,
        "window_id": target_window_id,
        "app_name": app_name,
        "title": title,
        "agent_owned_target": True,
        "background_target": True,
        "target_bound": True,
    }
    data: dict[str, Any] = {
        **window,
        "active_app_name": app_name,
        "frontmost": False,
        "foreground": False,
        "focus_verified": False,
        "active_window_scope": "agent_owned_background_target",
        "desktop_scope": "agent_owned_background",
        "observation_verified": True,
    }
    if tool_name in {"desktop.windows", "desktop.list_windows", "desktop.inspect_app"}:
        data["windows"] = [dict(window)]
        data["count"] = 1
    if tool_name in {"desktop.ui_elements", "desktop.read_ui", "desktop.inspect_app"}:
        data["elements"] = elements
        data["count"] = len(elements)
    postcondition_verified = False
    verification_contract_present = False
    verification_method = "target_bound_window_observation"
    trusted_verification_evidence: dict[str, Any] = {}
    if tool_name == "desktop.verify":
        (
            postcondition_verified,
            verification_contract_present,
            verification_method,
            trusted_verification_evidence,
        ) = _cua_window_postcondition_evaluation(
            payload,
            tool_request=tool_request,
            route=route,
            provider_kind=provider_kind,
            provider_id=provider_id,
            app_name=trusted_app_name,
            elements=elements,
            pid=target_pid,
            window_id=target_window_id,
        )
        data["verified"] = postcondition_verified
        data["postcondition_verified"] = postcondition_verified
        data["verification_method"] = verification_method
        if trusted_verification_evidence:
            data.update(trusted_verification_evidence)
        if not postcondition_verified:
            data["requires_postcondition_verification"] = True
            data["verification_inconclusive"] = not verification_contract_present

    summaries = {
        "desktop.active_window": "Observed the agent-owned background window.",
        "desktop.windows": "Observed the agent-owned background window list.",
        "desktop.list_windows": "Observed the agent-owned background window list.",
        "desktop.ui_elements": "Read UI elements from the agent-owned background window.",
        "desktop.read_ui": "Read the agent-owned background window.",
        "desktop.inspect_app": "Inspected the agent-owned background application.",
        "desktop.verify": (
            "Verified the requested state of the agent-owned background window."
            if postcondition_verified
            else "Observed the agent-owned background window; the requested postcondition was not verified."
        ),
    }
    return {
        "ok": True,
        "summary": summaries.get(
            tool_name,
            "Observed the agent-owned background window.",
        ),
        "data": data,
        "agent_owned_target": True,
        "target_bound": True,
        "observation_verified": True,
        **(
            {
                "postcondition_verified": postcondition_verified,
                "verification_method": verification_method,
                **trusted_verification_evidence,
                **(
                    {
                        "verification_failed": True,
                        "requires_postcondition_verification": True,
                        "verification_inconclusive": (
                            not verification_contract_present
                        ),
                    }
                    if not postcondition_verified
                    else {}
                ),
            }
            if tool_name == "desktop.verify"
            else {}
        ),
        "desktop_execution_provider_evidence": {
            "mcp_tool": "get_window_state",
            "desktop_scope": "agent_owned_background",
            "pid": target_pid,
            "window_id": target_window_id,
            "target_bound": True,
            "target_identity_source": "mcp_result",
        },
    }


def _cua_window_postcondition_evaluation(
    payload: Mapping[str, Any],
    *,
    tool_request: Mapping[str, Any],
    route: Mapping[str, Any],
    provider_kind: str,
    provider_id: str,
    app_name: str,
    elements: Sequence[Mapping[str, Any]],
    pid: int,
    window_id: int,
) -> tuple[bool, bool, str, dict[str, Any]]:
    """Evaluate one bounded predicate from an executor-authorized receipt.

    Public verifier input and public source ids can only invalidate a private
    context; they can never create authority.  Missing, serialized, or
    mismatched contexts leave ``desktop.verify`` observation-only.
    """

    del payload  # Public predicates are deliberately non-authoritative.
    context = tool_request.get(RUNTIME_PRIVATE_VERIFICATION_CONTEXT_KEY)
    if not isinstance(context, Mapping):
        return False, False, "target_bound_window_observation", {}
    if (
        context.get("version") != RUNTIME_PRIVATE_VERIFICATION_CONTEXT_VERSION
        or context.get("_authority") is not RUNTIME_PRIVATE_VERIFICATION_AUTHORITY
    ):
        return False, False, "target_bound_window_observation", {}

    execution_scope = tool_request.get(_RUNTIME_EXECUTION_SCOPE_KEY)
    run_id = str(context.get("run_id") or "").strip()
    if (
        not isinstance(execution_scope, Mapping)
        or not run_id
        or str(execution_scope.get("run_id") or "").strip() != run_id
    ):
        return False, False, "target_bound_window_observation", {}
    clean_provider_kind = str(provider_kind or "").strip()
    clean_provider_id = str(provider_id or "").strip()
    if (
        clean_provider_kind != CUA_BACKGROUND_PROVIDER_KIND
        or not clean_provider_id
        or str(context.get("provider_kind") or "").strip()
        != clean_provider_kind
        or str(context.get("provider_id") or "").strip() != clean_provider_id
        or str(route.get("selected_provider_kind") or "").strip()
        != clean_provider_kind
        or str(route.get("selected_provider_id") or "").strip()
        != clean_provider_id
    ):
        return False, False, "target_bound_window_observation", {}

    source_tool_call_id = str(
        context.get("source_tool_call_id") or ""
    ).strip()
    source_step_id = str(context.get("source_step_id") or "").strip()
    source_tool = str(context.get("source_tool") or "").strip()
    if (
        not source_tool_call_id
        or not source_step_id
        or not source_tool
        or str(tool_request.get("source_tool_call_id") or "").strip()
        != source_tool_call_id
        or str(tool_request.get("source_step_id") or "").strip()
        != source_step_id
    ):
        return False, False, "target_bound_window_observation", {}
    for key in ("plan_id", "tool_plan_id"):
        context_value = str(context.get(key) or "").strip()
        request_value = str(tool_request.get(key) or "").strip()
        if (context_value or request_value) and context_value != request_value:
            return False, False, "target_bound_window_observation", {}

    target = context.get("target")
    if (
        not isinstance(target, Mapping)
        or target.get("agent_owned_target") is not True
        or _positive_int(target.get("pid")) != pid
        or _positive_int(target.get("window_id")) != window_id
    ):
        return False, False, "target_bound_window_observation", {}
    clean_app_name = str(app_name or "").strip()
    target_app_name = str(target.get("app_name") or "").strip()
    if (
        not clean_app_name
        or (
            target_app_name
            and _normalized_app_name(target_app_name)
            != _normalized_app_name(clean_app_name)
        )
    ):
        return False, False, "target_bound_window_observation", {}

    predicate = context.get("predicate")
    if not isinstance(predicate, Mapping):
        return False, False, "target_bound_window_observation", {}
    predicate_kind = str(predicate.get("kind") or "").strip()
    verified = False
    observed_state = ""
    method = "target_bound_window_observation"
    if predicate_kind == APP_WINDOW_PRESENT_PREDICATE:
        expected_app_name = str(predicate.get("app_name") or "").strip()
        if (
            source_tool not in {"app.open", "desktop.open_app"}
            or not expected_app_name
        ):
            return False, False, method, {}
        method = "trusted_app_window_present_receipt"
        verified = bool(
            _normalized_app_name(expected_app_name)
            == _normalized_app_name(clean_app_name)
        )
        observed_state = "open"
    elif predicate_kind == EXACT_TYPED_CONTENT_PRESENT_PREDICATE:
        expected_text = predicate.get("expected_text")
        expected_digest = str(predicate.get("text_sha256") or "").strip()
        if (
            source_tool
            not in {
                "app.open_and_type_into_ui_element",
                "desktop.type_into_ui_element",
            }
            or not isinstance(expected_text, str)
            or not expected_text
            or len(expected_text) > 20000
            or not expected_digest
            or hashlib.sha256(expected_text.encode("utf-8")).hexdigest()
            != expected_digest
        ):
            return False, False, method, {}
        method = "trusted_exact_typed_content_receipt"
        verified = _cua_elements_contain_exact_text(elements, expected_text)
        observed_state = "typed"
    else:
        return False, False, method, {}

    if not verified:
        return False, True, method, {}
    observed_target = {
        "app_name": clean_app_name,
        "pid": pid,
        "window_id": window_id,
        "agent_owned_target": True,
    }
    evidence = {
        "verification_context_trusted": True,
        "verification_run_id": run_id,
        **(
            {"verification_plan_id": str(context.get("plan_id") or "").strip()}
            if str(context.get("plan_id") or "").strip()
            else {}
        ),
        **(
            {
                "verification_tool_plan_id": str(
                    context.get("tool_plan_id") or ""
                ).strip()
            }
            if str(context.get("tool_plan_id") or "").strip()
            else {}
        ),
        "source_tool_call_id": source_tool_call_id,
        "source_step_id": source_step_id,
        "source_tool": source_tool,
        "provider_kind": clean_provider_kind,
        "provider_id": clean_provider_id,
        "verification_predicate_kind": predicate_kind,
        "verified_observed_state": observed_state,
        "observed_target": observed_target,
    }
    return True, True, method, evidence


def _cua_elements_contain_exact_text(
    elements: Sequence[Mapping[str, Any]],
    expected_text: str,
) -> bool:
    for element in elements:
        if not isinstance(element, Mapping):
            continue
        for key in ("value", "text"):
            value = element.get(key)
            if isinstance(value, str) and value == expected_text:
                return True
    return False


def _normalized_cua_list_apps_result(
    mcp_result: Mapping[str, Any],
    *,
    query: Any,
    limit: Any,
) -> dict[str, Any]:
    records, valid = _cua_list_apps_payload(mcp_result)
    if not valid:
        return {
            "ok": False,
            "status": "provider_result_invalid",
            "error": "cua_list_apps_result_invalid",
            "summary": "Cua list_apps returned an unrecognized result shape.",
            "data": {
                "apps": [],
                "count": 0,
                "total_count": 0,
                "truncated": False,
            },
        }
    clean_query = " ".join(str(query or "").strip().casefold().split())
    filtered = [
        _normalized_cua_app_record(record)
        for record in records
        if not clean_query or _cua_app_record_matches(record, clean_query)
    ]
    clean_limit = _bounded_app_list_limit(limit)
    apps = filtered[:clean_limit]
    best_match: dict[str, Any] | None = None
    if apps and clean_query:
        best_match = next(
            (
                app
                for app in apps
                if _normalized_app_name(app.get("name")) == clean_query
                or _normalized_bundle_id(app.get("bundle_id")) == clean_query
            ),
            apps[0],
        )
    data: dict[str, Any] = {
        "apps": apps,
        "count": len(apps),
        "total_count": len(filtered),
        "truncated": len(filtered) > len(apps),
    }
    if best_match is not None:
        data["best_match"] = dict(best_match)
    return {
        "ok": True,
        "summary": (
            f"Found {len(filtered)} matching apps."
            if clean_query
            else f"Found {len(records)} apps."
        ),
        "data": data,
        "desktop_execution_provider_evidence": {
            "mcp_tool": "list_apps",
            "unfiltered_count": len(records),
            "filtered_locally": True,
        },
    }


def _normalized_cua_app_record(record: Mapping[str, Any]) -> dict[str, Any]:
    aliases = {
        "bundleIdentifier": "bundle_id",
        "bundlePath": "path",
        "display_name": "name",
        "executable_path": "path",
    }
    allowed = {
        "bundle_id",
        "icon_path",
        "name",
        "path",
        "pid",
        "running",
        "version",
    }
    normalized: dict[str, Any] = {}
    for source_key, value in record.items():
        key = aliases.get(str(source_key), str(source_key))
        if key in allowed and value not in (None, ""):
            normalized[key] = value
    return normalized


def _cua_app_record_matches(record: Mapping[str, Any], query: str) -> bool:
    searchable = (
        record.get("name"),
        record.get("display_name"),
        record.get("bundle_id"),
        record.get("bundleIdentifier"),
        record.get("path"),
        record.get("bundlePath"),
        record.get("executable_path"),
    )
    return any(query in str(value or "").casefold() for value in searchable)


def _bounded_app_list_limit(value: Any) -> int:
    parsed = _positive_int(value)
    return min(parsed or 200, 200)


def _launch_target_is_agent_owned(
    result: Mapping[str, Any],
    launch_arguments: Mapping[str, Any],
    preexisting_pids: set[int] | None,
    preflight_launch_identity: Mapping[str, Any],
) -> bool:
    pid = _positive_int(result.get("pid"))
    target_was_proven_stopped = bool(
        _normalized_bundle_id(preflight_launch_identity.get("bundle_id"))
        and preflight_launch_identity.get("running_pids") == []
    )
    return bool(
        pid is not None
        and (
            launch_arguments.get("creates_new_application_instance") is True
            or target_was_proven_stopped
        )
        and preexisting_pids is not None
        and pid not in preexisting_pids
    )


def _normalized_app_name(value: Any) -> str:
    if isinstance(value, (Mapping, list, tuple, set)):
        return ""
    name = " ".join(str(value or "").strip().split()).casefold()
    if name in _CUA_IDENTITY_PLACEHOLDERS:
        return ""
    return name[:-4].rstrip() if name.endswith(".app") else name


def _normalized_bundle_id(value: Any) -> str:
    if isinstance(value, (Mapping, list, tuple, set)):
        return ""
    bundle_id = str(value or "").strip().casefold()
    return "" if bundle_id in _CUA_IDENTITY_PLACEHOLDERS else bundle_id


def _same_cached_app_identity(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> bool:
    first_bundle = _normalized_bundle_id(first.get("bundle_id"))
    second_bundle = _normalized_bundle_id(second.get("bundle_id"))
    if first_bundle and second_bundle:
        return first_bundle == second_bundle
    first_names = {
        _normalized_app_name(value)
        for value in _string_list(first.get("app_names"))
        if _normalized_app_name(value)
    }
    second_names = {
        _normalized_app_name(value)
        for value in _string_list(second.get("app_names"))
        if _normalized_app_name(value)
    }
    return bool(first_names.intersection(second_names))


def _cached_target_matches_launch_request(
    target: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> bool:
    if (
        target.get("agent_owned_target") is not True
        or target.get("ambiguous") is True
        or _positive_int(target.get("pid")) is None
    ):
        return False
    requested_bundle = _normalized_bundle_id(payload.get("bundle_id"))
    cached_bundle = _normalized_bundle_id(target.get("bundle_id"))
    if requested_bundle:
        return bool(cached_bundle and requested_bundle == cached_bundle)
    requested_name = _normalized_app_name(
        payload.get("app_name") or payload.get("name")
    )
    cached_names = {
        _normalized_app_name(value)
        for value in _string_list(target.get("app_names"))
        if _normalized_app_name(value)
    }
    return bool(requested_name and requested_name in cached_names)


def _cua_tool_schema_properties(remote_tool: Mapping[str, Any]) -> dict[str, Any]:
    schema = remote_tool.get("inputSchema")
    if not isinstance(schema, Mapping):
        schema = remote_tool.get("input_schema")
    if not isinstance(schema, Mapping):
        return {}
    properties = schema.get("properties")
    return dict(properties) if isinstance(properties, Mapping) else {}


def _missing_cua_required_arguments(
    remote_tool: Mapping[str, Any],
    arguments: Mapping[str, Any],
) -> list[str]:
    schema = remote_tool.get("inputSchema")
    if not isinstance(schema, Mapping):
        schema = remote_tool.get("input_schema")
    if not isinstance(schema, Mapping):
        return []
    required = _string_list(schema.get("required"))
    missing: list[str] = []
    for name in required:
        if name not in arguments:
            missing.append(name)
            continue
        value = arguments.get(name)
        if value is None or value == "" or value == []:
            missing.append(name)
    return missing


def _canonical_cua_arguments(
    tool_name: str,
    cua_tool_name: str,
    payload: Mapping[str, Any],
    *,
    allowed_arguments: set[str],
) -> dict[str, Any]:
    known_arguments = _CUA_OFFICIAL_ARGUMENTS.get(cua_tool_name, frozenset())
    # ``session`` belongs to the runtime/provider lifecycle, and
    # ``delivery_mode`` is owned by this no-foreground adapter.  Neither may be
    # supplied by a model-authored tool payload.
    result = {
        key: payload.get(key)
        for key in known_arguments
        if key in payload and key not in {"session", "delivery_mode"}
    }
    if cua_tool_name == "launch_app":
        app_name = str(payload.get("app_name") or payload.get("name") or "").strip()
        if app_name:
            result["name"] = app_name
        if "creates_new_application_instance" in allowed_arguments:
            result["creates_new_application_instance"] = True
        return result

    action = (
        str(payload.get("action") or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )
    if tool_name == "desktop.safe_key":
        result.pop("key", None)
        result.pop("modifiers", None)
    elif tool_name == "desktop.safe_shortcut":
        result.pop("key", None)
        result.pop("keys", None)
        result.pop("modifiers", None)

    if cua_tool_name == "press_key" and action in _SAFE_KEY_ARGUMENTS:
        key, modifiers = _SAFE_KEY_ARGUMENTS[action]
        result["key"] = key
        if modifiers and "modifiers" in allowed_arguments:
            result["modifiers"] = list(modifiers)
    elif cua_tool_name == "hotkey" and action in _SAFE_SHORTCUT_KEYS:
        keys = _SAFE_SHORTCUT_KEYS[action]
        if "keys" in allowed_arguments:
            result["keys"] = list(keys)
            result.pop("key", None)
            result.pop("modifiers", None)
        elif "key" in allowed_arguments:
            result["key"] = keys[-1]
            if "modifiers" in allowed_arguments:
                result["modifiers"] = list(keys[:-1])
    elif cua_tool_name == "scroll":
        pages = _positive_int(payload.get("pages"))
        if pages is not None:
            result.setdefault("amount", pages)
            result.setdefault("by", "page")

    if tool_name in _CUA_GROUNDED_ELEMENT_ACTION_TOOLS:
        # Model-authored coordinates or element identifiers are never trusted.
        # Only the target-bound Cua snapshot may establish this selector.
        for key in ("element_index", "element_token", "x", "y"):
            result.pop(key, None)
    return result


def _grounded_element_action_tool(tool_name: str) -> str:
    if tool_name in _CUA_GROUNDED_ELEMENT_ACTION_TOOLS:
        return tool_name
    composite_action = _CUA_OPEN_COMPOSITE_TOOLS.get(tool_name, "")
    return (
        composite_action
        if composite_action in _CUA_GROUNDED_ELEMENT_ACTION_TOOLS
        else ""
    )


def _grounded_element_contract_supported(
    remote_action_tool: Mapping[str, Any] | None,
    remote_snapshot_tool: Mapping[str, Any] | None,
) -> bool:
    if remote_action_tool is None or remote_snapshot_tool is None:
        return False
    action_properties = _cua_tool_schema_properties(remote_action_tool)
    snapshot_properties = _cua_tool_schema_properties(remote_snapshot_tool)
    return bool(
        {"pid", "window_id"}.issubset(action_properties)
        and {"pid", "window_id"}.issubset(snapshot_properties)
        and {"element_index", "element_token"}.intersection(action_properties)
    )


def _normalized_cua_element_label(value: Any) -> str:
    if isinstance(value, (Mapping, list, tuple, set)):
        return ""
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(normalized.split()).casefold()


def _normalized_cua_element_role(value: Any) -> str:
    role = _normalized_cua_element_label(value)
    compact = "".join(character for character in role if character.isalnum())
    return compact[2:] if compact.startswith("ax") else compact


def _cua_element_labels(element: Mapping[str, Any]) -> set[str]:
    labels = {
        _normalized_cua_element_label(element.get(key))
        for key in ("label", "name", "title", "description", "value")
    }
    labels.discard("")
    return labels


def _collapse_equivalent_cua_element_matches(
    matches: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Collapse duplicate AX projections only when they describe one frame.

    Some drivers expose the same native control through both an app-root and a
    window-root traversal.  The element tokens differ, but label, role, frame,
    value and interaction state are identical.  Treating those projections as
    separate targets makes safe background input impossible; targets with a
    missing/different frame or any semantic difference remain ambiguous.
    """

    copied = [dict(item) for item in matches]
    if len(copied) <= 1:
        return copied
    signatures = [_cua_element_equivalence_signature(item) for item in copied]
    if any(signature is None for signature in signatures) or len(set(signatures)) != 1:
        return copied
    return [min(copied, key=_cua_element_stable_selector_order)]


def _cua_element_equivalence_signature(
    element: Mapping[str, Any],
) -> tuple[Any, ...] | None:
    frame = element.get("frame")
    if isinstance(frame, Mapping):
        try:
            normalized_frame = json.dumps(
                dict(frame),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        except (TypeError, ValueError):
            return None
    elif isinstance(frame, str):
        normalized_frame = "".join(frame.split())
    else:
        return None
    if not normalized_frame:
        return None
    return (
        tuple(sorted(_cua_element_labels(element))),
        _normalized_cua_element_role(element.get("role")),
        normalized_frame,
        tuple(
            (key, element.get(key))
            for key in ("enabled", "clickable", "actionable", "interactable")
        ),
    )


def _cua_element_stable_selector_order(element: Mapping[str, Any]) -> tuple[Any, ...]:
    element_index = _cua_element_index(element)
    return (
        element_index is None,
        element_index if element_index is not None else 0,
        _cua_element_token(element),
    )


def _cua_element_token(element: Mapping[str, Any]) -> str:
    value = element.get("element_token")
    if value in (None, ""):
        value = element.get("token")
    if isinstance(value, (Mapping, list, tuple, set, bool)):
        return ""
    token = str(value or "").strip()
    return token if 0 < len(token) <= 512 else ""


def _cua_element_index(element: Mapping[str, Any]) -> int | None:
    value = element.get("element_index")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _has_cua_pointer_target(arguments: Mapping[str, Any]) -> bool:
    has_window = _positive_int(arguments.get("window_id")) is not None
    element_index = arguments.get("element_index")
    has_element_index = (
        isinstance(element_index, int)
        and not isinstance(element_index, bool)
        and element_index >= 0
    )
    has_element_token = bool(str(arguments.get("element_token") or "").strip())
    if has_element_token or (has_window and has_element_index):
        return True
    return _number_argument(arguments.get("x")) and _number_argument(
        arguments.get("y")
    )


def _number_argument(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value.strip())
        except (TypeError, ValueError):
            return False
        return bool(value.strip())
    return False


def _trusted_task_scope_key(tool_request: Mapping[str, Any]) -> str:
    """Return only the executor-injected, parser-protected run scope."""

    runtime_scope = tool_request.get(_RUNTIME_EXECUTION_SCOPE_KEY)
    if not isinstance(runtime_scope, Mapping):
        return ""
    run_id = _stable_identifier(runtime_scope.get("run_id"))
    if not run_id:
        return ""
    parts = [f"run_id:{run_id}"]
    for key in _RUNTIME_SCOPE_CONTEXT_KEYS:
        value = _stable_identifier(runtime_scope.get(key))
        if value:
            parts.append(f"{key}:{value}")
    return "|".join(parts)


def _stable_identifier(value: Any) -> str:
    if isinstance(value, bool) or isinstance(value, (Mapping, list, tuple, set)):
        return ""
    return str(value or "").strip()


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        return int(value) if value.is_integer() and value > 0 else None
    if isinstance(value, str):
        clean_value = value.strip()
        if not clean_value or not clean_value.isdigit():
            return None
        parsed = int(clean_value)
        return parsed if parsed > 0 else None
    return None


def _bounded_repeat_count(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1 <= value <= 20 else None
    if isinstance(value, str):
        clean_value = value.strip()
        if clean_value.isdigit():
            parsed = int(clean_value)
            return parsed if 1 <= parsed <= 20 else None
    return None


def _provider_supported_tools(tool_request: Mapping[str, Any]) -> list[str]:
    for key in (
        "sandbox_provider",
        "sandbox_desktop_provider",
        "desktop_sandbox_provider",
    ):
        value = tool_request.get(key)
        if isinstance(value, Mapping):
            return _string_list(value.get("supported_tools"))
    metadata = tool_request.get("metadata")
    if isinstance(metadata, Mapping) and metadata is not tool_request:
        return _provider_supported_tools(metadata)
    return []


def _internal_composite_tool_request(
    tool_request: Mapping[str, Any],
    tool_name: str,
) -> dict[str, Any]:
    request = dict(tool_request)
    provider: dict[str, Any] = {}
    for key in (
        "sandbox_provider",
        "sandbox_desktop_provider",
        "desktop_sandbox_provider",
    ):
        value = tool_request.get(key)
        if isinstance(value, Mapping):
            provider = dict(value)
            break
    provider.setdefault("provider_id", CUA_BACKGROUND_PROVIDER_ID)
    provider.setdefault("provider_kind", CUA_BACKGROUND_PROVIDER_KIND)
    provider["supported_tools"] = [tool_name]
    request["sandbox_provider"] = provider
    request["tool"] = tool_name
    return request


def _compact_composite_step(
    tool_name: str,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "tool": tool_name,
        "ok": result.get("ok") is True,
    }
    for key in ("status", "error", "summary"):
        value = result.get(key)
        if value not in (None, ""):
            step[key] = value
    return step


def _composite_result(
    tool_name: str,
    step_result: Mapping[str, Any],
    *,
    steps: Sequence[Mapping[str, Any]],
    failed_step: str,
) -> dict[str, Any]:
    result = dict(step_result)
    result["tool"] = tool_name
    result["action"] = tool_name
    result["composite_steps"] = [dict(step) for step in steps]
    if failed_step:
        result["failed_step"] = failed_step
    else:
        result.pop("failed_step", None)
    return result


def _required_cua_tool_names(tool_name: str, cua_tool_name: str) -> set[str]:
    required = {str(cua_tool_name or "").strip()}
    if cua_tool_name == "launch_app":
        required.add("list_apps")
    if tool_name in _CUA_OPEN_COMPOSITE_TOOLS:
        required.add("launch_app")
    if cua_tool_name in _CUA_PID_TARGETED_TOOLS:
        required.add("list_apps")
    if (
        cua_tool_name in _CUA_SNAPSHOT_VERIFICATION_TOOLS
        or _grounded_element_action_tool(tool_name)
    ):
        required.add("get_window_state")
    required.discard("")
    return required


def _cua_logical_tool_contract_supported(
    tool_name: str,
    cua_tool_name: str,
    remote_tools: Mapping[str, Mapping[str, Any]],
) -> bool:
    """Validate executable capability from the live MCP schemas.

    A static logical-to-MCP name map describes intent, not capability.  In
    particular, calling a global observation tool without pid/window fields
    could inspect the user's foreground desktop before Oha has a chance to
    reject the response.  Advertise a logical tool only when every dependency
    and the target-binding arguments are present in the installed driver.
    """

    if not _required_cua_tool_names(tool_name, cua_tool_name).issubset(
        remote_tools
    ):
        return False
    if (
        cua_tool_name == "launch_app"
        or tool_name in _CUA_OPEN_COMPOSITE_TOOLS
    ) and not _background_launch_contract_supported(remote_tools.get("launch_app")):
        return False
    if tool_name in _CUA_TARGET_BOUND_OBSERVATION_TOOLS:
        observation_properties = _cua_tool_schema_properties(
            remote_tools.get(cua_tool_name) or {}
        )
        if not {"pid", "window_id"}.issubset(observation_properties):
            return False
    if cua_tool_name in _CUA_BACKGROUND_INPUT_TOOLS:
        action_properties = _cua_tool_schema_properties(
            remote_tools.get(cua_tool_name) or {}
        )
        if "pid" not in action_properties:
            return False
    grounded_action_tool = _grounded_element_action_tool(tool_name)
    if grounded_action_tool:
        return _grounded_element_contract_supported(
            remote_tools.get(cua_tool_name),
            remote_tools.get("get_window_state"),
        )
    return True


def _background_launch_contract_supported(
    remote_launch_tool: Mapping[str, Any] | None,
) -> bool:
    if remote_launch_tool is None:
        return False
    return "creates_new_application_instance" in _cua_tool_schema_properties(
        remote_launch_tool
    )


def _requests_foreground_takeover(
    payload: Mapping[str, Any],
    route: Mapping[str, Any],
) -> bool:
    if route.get("foreground_takeover_required") is True:
        return True
    return payload.get("bring_to_front") is True


def _is_foreground_only_tool(tool_name: str) -> bool:
    clean_name = str(tool_name or "").strip().lower().replace("-", "_")
    leaf_name = clean_name.rsplit(".", 1)[-1]
    return leaf_name in _FOREGROUND_ONLY_TOOL_NAMES


def _string_list(values: Iterable[Any] | Any | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = values.split(",")
    if isinstance(values, Mapping):
        values = values.keys()
    try:
        iterator = iter(values)
    except TypeError:
        iterator = iter((values,))
    result: list[str] = []
    for value in iterator:
        clean_value = str(value or "").strip()
        if clean_value and clean_value not in result:
            result.append(clean_value)
    return result


def _background_capabilities() -> list[str]:
    return [
        "background_input",
        "keyboard_mouse_capture",
        "no_foreground_takeover",
    ]


def _background_status_fields() -> dict[str, Any]:
    return {
        "foreground_mutation_supported": True,
        "keyboard_mouse_capture_supported": True,
        "requires_real_sandbox_for": [],
        "desktop_session_kind": "background_desktop",
        "desktop_session_isolated": False,
        "foreground_takeover_required": False,
        "desktop_backend_kind": "cua_driver",
        "desktop_backend_is_loopback": False,
        "desktop_backend_ready_for_public_release": False,
        "requires_real_virtual_desktop_backend": False,
    }


__all__ = [
    "CUA_BACKGROUND_PROVIDER_ID",
    "CUA_BACKGROUND_PROVIDER_KIND",
    "CUA_DRIVER_COMMAND_ENV",
    "CUA_DRIVER_PATH_ENV",
    "CUA_HOST_BUNDLE_ID_ENV",
    "CUA_MCP_BRIDGE_GENERATION_ENV",
    "CUA_MCP_BRIDGE_TOKEN_ENV",
    "CUA_MCP_BRIDGE_URL_ENV",
    "CUA_MCP_PROTOCOL_VERSION",
    "CUA_MCP_TRANSPORT_ENV",
    "CUA_TELEMETRY_ENV",
    "CuaBackgroundDesktopExecutionProviderAdapter",
    "CuaMcpClient",
    "CuaMcpError",
    "CuaMcpProtocolError",
    "CuaMcpRemoteError",
    "CuaMcpTimeoutError",
    "CuaMcpToolError",
    "CuaMcpTransportError",
    "DEFAULT_CUA_TOOL_NAME_MAP",
    "cua_background_provider_adapter_from_env",
    "cua_background_provider_status",
    "invalidate_cua_background_provider_caches",
    "resolve_cua_mcp_command",
]
