"""Release guard for Electron's single desktop-runtime ownership contract."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ELECTRON_MAIN = ROOT / "apps" / "frontend" / "electron" / "main.ts"


def test_electron_acquires_single_instance_lock_before_runtime_startup() -> None:
    source = ELECTRON_MAIN.read_text(encoding="utf-8")

    lock_index = source.index("app.requestSingleInstanceLock()")
    ready_index = source.index("app.whenReady().then(")
    backend_index = source.index("startBackend();", ready_index)
    secondary_index = source.index("recordElectronProcessSmoke('secondary');", lock_index)
    quit_index = source.index("app.quit();", secondary_index)
    primary_branch_index = source.index("} else {", quit_index)

    assert lock_index < ready_index < backend_index
    assert lock_index < secondary_index < quit_index < primary_branch_index < ready_index


def test_second_electron_launch_focuses_the_existing_assistant() -> None:
    source = ELECTRON_MAIN.read_text(encoding="utf-8")

    assert "app.on('second-instance', () => {" in source
    assert "showMainWindowAtLastRoute({ restore: 'last' });" in source
    assert "app.focus({ steal: true });" in source


def test_initial_settings_refresh_preserves_an_early_renderer_route() -> None:
    source = ELECTRON_MAIN.read_text(encoding="utf-8")

    ready_index = source.index("app.whenReady().then(")
    create_index = source.index(
        "createMainWindow({ view: 'main' }, lastUiSettings, { focusOnReady: false });",
        ready_index,
    )
    settings_index = source.index("const settings = await waitForUiSettings();", create_index)
    preserve_index = source.index("if (!focusMainWindowWithoutNavigation(", settings_index)
    preserve_end_index = source.index(")) {", preserve_index)
    mode_index = source.index("await openConfiguredDesktopMode(undefined, settings);", settings_index)

    assert create_index < settings_index < preserve_index < mode_index
    preserve_call = source[preserve_index:preserve_end_index]
    assert "routeForWindow(mainWindow)" in preserve_call
    assert "{ focusOnReady: false }" in preserve_call
    assert "showMainWindow({}, settings, { focusOnReady: false });" not in source[
        settings_index:mode_index
    ]


def test_electron_process_smoke_isolated_paths_are_configured_before_lock() -> None:
    source = ELECTRON_MAIN.read_text(encoding="utf-8")

    configure_index = source.index("configureElectronProcessSmoke();")
    lock_index = source.index("app.requestSingleInstanceLock()")

    assert configure_index < lock_index
    assert "process.env[DESKTOP_SMOKE_MODE_ENV] !== '1'" in source
    assert "app.setPath('userData', smokeUserDataPath);" in source
    assert "OHA_YACHIYO_ELECTRON_SMOKE_ROOT" in source


def test_electron_process_smoke_records_runtime_ownership_lifecycle() -> None:
    source = ELECTRON_MAIN.read_text(encoding="utf-8")

    for event in (
        "primary",
        "secondary",
        "backend.spawn",
        "second-instance",
        "window.focus",
        "backend.exit",
    ):
        assert f"recordElectronProcessSmoke('{event}'" in source

    assert "[ELECTRON_PARENT_PID_ENV]: String(process.pid)" in source
    assert "[ELECTRON_PARENT_TOKEN_ENV]: backendParentToken" in source


def test_electron_process_smoke_rejects_symlinks_and_appends_without_following() -> None:
    source = ELECTRON_MAIN.read_text(encoding="utf-8")

    assert "fs.lstatSync(configuredRoot)" in source
    assert "smokeRootStat.isSymbolicLink()" in source
    assert "smokeUserDataStat.isSymbolicLink()" in source
    assert "fs.constants.O_NOFOLLOW" in source
    assert "fs.fstatSync(descriptor).isFile()" in source


def test_invalid_electron_process_smoke_configuration_exits_immediately() -> None:
    source = ELECTRON_MAIN.read_text(encoding="utf-8")

    configure_index = source.index("configureElectronProcessSmoke();")
    rejection_index = source.index(
        "console.error('[electron-process-smoke] configuration rejected');",
        configure_index,
    )
    app_exit_index = source.index("app.exit(1);", rejection_index)
    process_exit_index = source.index("process.exit(1);", app_exit_index)
    dock_index = source.index("showMacDockIcon();", process_exit_index)

    assert configure_index < rejection_index < app_exit_index < process_exit_index < dock_index
