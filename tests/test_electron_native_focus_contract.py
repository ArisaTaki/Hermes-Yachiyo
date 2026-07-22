"""Regression guards for the packaged Electron foreground-focus bridge."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
ELECTRON_MAIN = ROOT / "apps" / "frontend" / "electron" / "main.ts"
DESKTOP_TOOLS = ROOT / "apps" / "shell" / "agent" / "tools" / "desktop.py"


def _function_source(source: str, name: str, next_name: str) -> str:
    return source.split(f"function {name}", 1)[1].split(f"function {next_name}", 1)[0]


def test_system_events_stale_true_flag_cannot_override_final_frontmost_app() -> None:
    source = ELECTRON_MAIN.read_text(encoding="utf-8")
    parser = _function_source(
        source,
        "parseNativeFocusSnapshot",
        "parseNativeAppKitFocusSnapshot",
    )

    # focused|Music|true|ChatGPT must fail: the flag is diagnostic only.
    assert "system_events_reported_frontmost" in parser
    assert "frontmostText.toLocaleLowerCase() === 'true'\n    ||" not in parser
    assert (
        "Boolean(appName && frontmostApp "
        "&& compactAppName(appName) === compactAppName(frontmostApp))"
    ) in parser


def test_appkit_stale_active_flag_cannot_override_final_frontmost_app() -> None:
    source = ELECTRON_MAIN.read_text(encoding="utf-8")
    parser = _function_source(
        source,
        "parseNativeAppKitFocusSnapshot",
        "nativeFocusToolResult",
    )

    # appkit|Music|true|true|ChatGPT must fail for the same reason.
    assert "appkit_reported_active" in parser
    assert "activeText.toLocaleLowerCase() === 'true'\n    ||" not in parser
    assert (
        "Boolean(appName && frontmostApp "
        "&& compactAppName(appName) === compactAppName(frontmostApp))"
    ) in parser


def test_native_focus_continues_to_appkit_after_system_events_error() -> None:
    source = ELECTRON_MAIN.read_text(encoding="utf-8")
    focus = _function_source(
        source,
        "electronNativeFocusApp",
        "handleNativeRuntimeRequest",
    )

    system_events_index = focus.index("electron_system_events_verify")
    appkit_index = focus.index("electron_appkit_nsrunningapplication")
    between = focus[system_events_index:appkit_index]

    assert system_events_index < appkit_index
    assert "if (verifyResult.exitCode !== 0) {\n    return" not in between


def test_native_focus_server_budget_fits_inside_python_client_timeout() -> None:
    electron_source = ELECTRON_MAIN.read_text(encoding="utf-8")
    desktop_source = DESKTOP_TOOLS.read_text(encoding="utf-8")
    timeout_values = {
        name: int(value)
        for name, value in re.findall(
            r"const (NATIVE_FOCUS_[A-Z_]+_TIMEOUT_MS) = (\d+);",
            electron_source,
        )
    }

    required = {
        "NATIVE_FOCUS_OPEN_TIMEOUT_MS",
        "NATIVE_FOCUS_SYSTEM_EVENTS_TIMEOUT_MS",
        "NATIVE_FOCUS_APPKIT_TIMEOUT_MS",
    }
    assert required <= timeout_values.keys()
    worst_case_server_ms = (
        timeout_values["NATIVE_FOCUS_OPEN_TIMEOUT_MS"] * 2
        + timeout_values["NATIVE_FOCUS_SYSTEM_EVENTS_TIMEOUT_MS"] * 2
        + timeout_values["NATIVE_FOCUS_APPKIT_TIMEOUT_MS"]
    )
    client_match = re.search(
        r"def _electron_native_focus_app\(.*?"
        r"timeout_seconds: float = ([0-9.]+),.*?"
        r"urlopen\(request, timeout=timeout_seconds\)",
        desktop_source,
        re.DOTALL,
    )
    assert client_match is not None
    client_timeout_ms = float(client_match.group(1)) * 1000

    assert worst_case_server_ms < client_timeout_ms <= 8000
