from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.shell.agent.runtime.cua_background_provider import (
    CUA_DRIVER_COMMAND_ENV,
    CUA_DRIVER_PATH_ENV,
    CUA_HOST_BUNDLE_ID_ENV,
    resolve_cua_mcp_command,
)

ROOT = Path(__file__).resolve().parents[1]


def test_bundled_driver_path_is_authoritative_and_uses_embedded_mode() -> None:
    discovery_calls: list[str] = []
    bundled_path = (
        "/Applications/Oha-Yachiyo.app/Contents/Resources/computer-use/macos/"
        "OhaCuaDriver.app/Contents/MacOS/cua-driver"
    )

    def forbidden_run(*_args: Any, **_kwargs: Any) -> Any:
        discovery_calls.append("run")
        raise AssertionError("bundled driver resolution must not inspect a manifest")

    def forbidden_which(_name: str) -> str:
        discovery_calls.append("which")
        return "/usr/local/bin/cua-driver"

    command = resolve_cua_mcp_command(
        {
            CUA_DRIVER_PATH_ENV: bundled_path,
            CUA_DRIVER_COMMAND_ENV: "/tmp/override mcp",
            CUA_HOST_BUNDLE_ID_ENV: "io.github.arisataki.oha-yachiyo",
        },
        run=forbidden_run,
        which=forbidden_which,
        path_exists=lambda path: path == bundled_path,
    )

    assert command == (
        bundled_path,
        "mcp",
        "--embedded",
        "--host-bundle-id",
        "io.github.arisataki.oha-yachiyo",
    )
    assert discovery_calls == []


def test_missing_configured_bundled_path_fails_closed() -> None:
    discovery_calls: list[str] = []

    command = resolve_cua_mcp_command(
        {
            CUA_DRIVER_PATH_ENV: "/missing/resources/cua-driver",
            CUA_DRIVER_COMMAND_ENV: "/tmp/external-driver mcp",
        },
        run=lambda *_args, **_kwargs: discovery_calls.append("run"),
        which=lambda _name: discovery_calls.append("which") or "/usr/local/bin/cua-driver",
        path_exists=lambda _path: False,
    )

    assert command is None
    assert discovery_calls == []


def test_development_discovery_remains_available_without_bundled_path() -> None:
    command = resolve_cua_mcp_command(
        {CUA_DRIVER_COMMAND_ENV: "'/tmp/Cua Driver/cua-driver' mcp"},
        run=lambda *_args, **_kwargs: None,
        which=lambda _name: None,
        path_exists=lambda _path: False,
    )

    assert command == ("/tmp/Cua Driver/cua-driver", "mcp")


def test_electron_packaged_backend_uses_only_the_direct_host_bridge() -> None:
    source = (ROOT / "apps" / "frontend" / "electron" / "main.ts").read_text("utf-8")
    bridge_source = (
        ROOT / "apps" / "frontend" / "electron" / "cuaMcpBridge.ts"
    ).read_text("utf-8")

    for path_part in (
        "'computer-use'",
        "'macos'",
        "'OhaCuaDriver.app'",
        "'Contents'",
        "'MacOS'",
        "'cua-driver'",
    ):
        assert path_part in source
    assert "return app.isPackaged && process.platform === 'darwin'" in source
    assert "await startPackagedCuaMcpBridge()" in source
    assert (
        "backendEnvironment[CUA_MCP_TRANSPORT_ENV] = "
        "CUA_MCP_ELECTRON_BRIDGE_TRANSPORT"
    ) in source
    assert "backendEnvironment[CUA_MCP_BRIDGE_URL_ENV] = cuaMcpBridgeUrl" in source
    assert "backendEnvironment[CUA_MCP_BRIDGE_TOKEN_ENV] = cuaMcpBridgeToken" in source
    assert (
        "backendEnvironment[CUA_MCP_BRIDGE_GENERATION_ENV] = "
        "cuaMcpBridgeGeneration"
    ) in source
    assert "delete backendEnvironment[CUA_DRIVER_PATH_ENV]" in source
    assert "delete backendEnvironment[CUA_DRIVER_COMMAND_ENV]" in source
    assert "delete backendEnvironment[CUA_HOST_BUNDLE_ID_ENV]" in source
    assert "backendEnvironment[CUA_DRIVER_PATH_ENV] = packagedCuaDriverPath()" not in source
    for driver_arg in (
        "'mcp'",
        "'--embedded'",
        "'--host-bundle-id'",
        "this.#hostBundleId",
        "'--no-overlay'",
    ):
        assert driver_arg in bridge_source
    assert "shell: false" in bridge_source
    assert "let backendShutdownPromise: Promise<void> | null = null" in source
    assert "let backendTerminationPromise: Promise<void> | null = null" in source
    assert "if (backendShutdownPromise)" in source
    assert "backendProcess || backendTerminationPromise || cuaMcpBridge" in source
    assert "let appShutdownRequested = false" in source
    assert "appShutdownRequested = true" in source
    assert "const MAX_CONCURRENT_SESSIONS = 2" in bridge_source


def test_all_macos_packaging_paths_prepare_and_embed_the_driver() -> None:
    package = json.loads(
        (ROOT / "apps" / "frontend" / "package.json").read_text("utf-8")
    )
    scripts = package["scripts"]
    assert scripts["prepare:cua-driver"] == "python3 ../../scripts/prepare_cua_driver.py"
    for name in ("dist:mac", "pack:mac"):
        command = scripts[name]
        assert command.startswith("npm run prepare:cua-driver && ")
        assert command.index("prepare:cua-driver") < command.index("electron-builder")

    builder = (ROOT / "apps" / "frontend" / "electron-builder.yml").read_text("utf-8")
    assert "from: ../../dist/cua-driver/macos/cua-driver" in builder
    assert (
        "to: computer-use/macos/OhaCuaDriver.app/Contents/MacOS/cua-driver"
        in builder
    )
    assert "from: ../../packaging/cua-driver-background-helper.Info.plist" in builder
    assert "to: computer-use/macos/OhaCuaDriver.app/Contents/Info.plist" in builder
    assert "from: ../../dist/cua-driver/macos/LICENSE.md" in builder
    assert "from: ../../dist/cua-driver/macos/manifest.json" in builder

    helper_info = (
        ROOT / "packaging" / "cua-driver-background-helper.Info.plist"
    ).read_text("utf-8")
    assert "<key>LSBackgroundOnly</key>" in helper_info
    assert "<true/>" in helper_info

    build_script = (ROOT / "scripts" / "build_macos_self_signed_dmg.sh").read_text("utf-8")
    prepare = 'python3 "${ROOT}/scripts/prepare_cua_driver.py"'
    builder_command = "npx electron-builder --config electron-builder.yml --mac dir"
    assert prepare in build_script
    assert build_script.index(prepare) < build_script.index(builder_command)
    assert 'SIGNING_MODE="${2:-${MACOS_SIGNING_MODE:-}}"' in build_script
    assert "plistlib.loads(sys.stdin.buffer.read())" in build_script
    assert "plistlib.load(sys.stdin.buffer)" not in build_script
    assert "`codesign --deep --force` would recursively overwrite" in build_script
    assert "codesign_args=(\n  --deep" not in build_script

    bridge_source = (
        ROOT / "apps" / "frontend" / "electron" / "cuaMcpBridge.ts"
    ).read_text("utf-8")
    assert "'--no-overlay'" in bridge_source

    workflow = (ROOT / ".github" / "workflows" / "release-macos.yml").read_text(
        "utf-8"
    )
    assert "plistlib.loads(sys.stdin.buffer.read())" in workflow
    assert "plistlib.load(sys.stdin.buffer)" not in workflow
