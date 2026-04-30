from __future__ import annotations

from pathlib import Path

from apps import desktop_launcher


def _create_frontend_bins(frontend_dir: Path) -> None:
    bin_dir = frontend_dir / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    for name in desktop_launcher.REQUIRED_FRONTEND_BINS:
        (bin_dir / name).write_text("", encoding="utf-8")


def test_frontend_dependencies_ready_requires_expected_bins(tmp_path: Path) -> None:
    frontend_dir = tmp_path / "apps" / "frontend"

    assert not desktop_launcher._frontend_dependencies_ready(frontend_dir)

    _create_frontend_bins(frontend_dir)

    assert desktop_launcher._frontend_dependencies_ready(frontend_dir)


def test_parse_node_version_accepts_common_version_output() -> None:
    assert desktop_launcher._parse_node_version("v20.19.0") == (20, 19, 0)
    assert desktop_launcher._parse_node_version("20.19") == (20, 19, 0)
    assert desktop_launcher._parse_node_version("not-node") is None


def test_node_version_supported_requires_vite_minimum() -> None:
    assert desktop_launcher._node_version_supported((20, 19, 0))
    assert desktop_launcher._node_version_supported((22, 12, 0))
    assert not desktop_launcher._node_version_supported((20, 18, 9))


def test_ensure_node_version_reports_old_node(monkeypatch) -> None:
    monkeypatch.setattr(desktop_launcher, "_node_executable", lambda env: "/usr/bin/node")

    class Result:
        stdout = "v20.18.0\n"
        stderr = ""

    monkeypatch.setattr(desktop_launcher.subprocess, "run", lambda *args, **kwargs: Result())

    try:
        desktop_launcher._ensure_node_version({"PATH": "/usr/bin"})
    except SystemExit as exc:
        assert "Node.js 20.19+ is required" in str(exc)
    else:
        raise AssertionError("expected SystemExit")


def test_run_frontend_dev_converts_keyboard_interrupt(tmp_path: Path, monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(desktop_launcher.subprocess, "run", fake_run)

    try:
        desktop_launcher._run_frontend_dev(tmp_path, tmp_path / "apps" / "frontend", "/usr/bin/npm", {})
    except SystemExit as exc:
        assert exc.code == 130
    else:
        raise AssertionError("expected SystemExit")


def test_ensure_frontend_dependencies_runs_npm_ci_when_missing(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path
    frontend_dir = tmp_path / "apps" / "frontend"
    frontend_dir.mkdir(parents=True)
    (frontend_dir / "package-lock.json").write_text("{}", encoding="utf-8")
    calls = []

    monkeypatch.setattr(desktop_launcher, "_npm_executable", lambda env: "/usr/bin/npm")

    def fake_run(command, cwd, env, check):
        calls.append((command, cwd, env, check))

    monkeypatch.setattr(desktop_launcher.subprocess, "run", fake_run)

    env = {"PATH": "/usr/bin"}
    desktop_launcher._ensure_frontend_dependencies(project_root, frontend_dir, env)

    assert calls == [
        (["/usr/bin/npm", "--prefix", str(frontend_dir), "ci"], project_root, env, True)
    ]


def test_ensure_frontend_dependencies_skips_install_when_ready(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path
    frontend_dir = tmp_path / "apps" / "frontend"
    _create_frontend_bins(frontend_dir)

    monkeypatch.setattr(
        desktop_launcher.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected install")),
    )

    desktop_launcher._ensure_frontend_dependencies(project_root, frontend_dir, {"PATH": ""})


def test_run_electron_against_existing_vite_compiles_and_starts(
    tmp_path: Path, monkeypatch
) -> None:
    frontend_dir = tmp_path / "apps" / "frontend"
    _create_frontend_bins(frontend_dir)
    calls = []

    def fake_run(command, cwd, env, check):
        calls.append((command, cwd, env, check))

    monkeypatch.setattr(desktop_launcher.subprocess, "run", fake_run)

    env = {"PATH": "/usr/bin"}
    desktop_launcher._run_electron_against_existing_vite(tmp_path, frontend_dir, env)

    assert calls == [
        ([str(frontend_dir / "node_modules" / ".bin" / "tsc"), "-p", "tsconfig.electron.json"], frontend_dir, env, True),
        ([str(frontend_dir / "node_modules" / ".bin" / "electron"), "dist-electron/main.js"], frontend_dir, env, True),
    ]