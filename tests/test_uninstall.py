"""Hermes-Yachiyo 卸载功能测试。"""

from __future__ import annotations

from types import SimpleNamespace

import apps.shell.config as config_mod
from apps.installer import uninstall as uninstall_mod
from apps.installer.uninstall import (
    UNINSTALL_CONFIRM_PHRASE,
    UninstallScope,
    build_uninstall_plan,
    execute_uninstall,
    get_config_snapshot_status,
    import_config_snapshot,
)
from apps.shell.config import AppConfig
from apps.shell.installer_api import InstallerWebViewAPI
from apps.shell.main_api import MainWindowAPI


def _prepare_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    hermes_home = home / ".hermes"
    config_dir = home / ".hermes-yachiyo"

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", config_dir / "config.json")

    return home, hermes_home, config_dir


def test_yachiyo_only_plan_includes_config_and_workspace(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("{}", encoding="utf-8")
    workspace = hermes_home / "yachiyo"
    workspace.mkdir(parents=True)
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")

    plan = build_uninstall_plan(
        UninstallScope.YACHIYO_ONLY,
        keep_config_snapshot=True,
        backup_root=home / "backups",
    )

    target_ids = {target.id for target in plan.targets}
    assert target_ids == {"app_config_dir", "yachiyo_workspace"}
    assert "hermes_home" not in target_ids
    assert plan.backup.enabled is True
    assert plan.to_dict()["existing_count"] == 2
    assert plan.to_dict()["removable_count"] == 2


def test_execute_yachiyo_only_keeps_config_snapshot_and_removes_targets(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text('{"display_mode":"bubble"}', encoding="utf-8")

    workspace = hermes_home / "yachiyo"
    (workspace / "configs").mkdir(parents=True)
    (workspace / "configs" / "yachiyo.json").write_text("{}", encoding="utf-8")
    (workspace / "templates").mkdir()
    (workspace / "templates" / "default.json").write_text("{}", encoding="utf-8")
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")
    (workspace / "chat.db").write_text("chat", encoding="utf-8")

    result = execute_uninstall(
        UninstallScope.YACHIYO_ONLY,
        keep_config_snapshot=True,
        confirm_text=UNINSTALL_CONFIRM_PHRASE,
        backup_root=home / "backups",
    )

    assert result.ok is True
    assert not config_dir.exists()
    assert not workspace.exists()

    backup_path = home / "backups"
    snapshots = list(backup_path.iterdir())
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert (snapshot / "manifest.json").exists()
    assert (snapshot / "app-config" / "config.json").exists()
    assert (snapshot / "yachiyo-workspace" / "configs" / "yachiyo.json").exists()
    assert (snapshot / "yachiyo-workspace" / "templates" / "default.json").exists()
    assert not (snapshot / "yachiyo-workspace" / "chat.db").exists()


def test_import_config_snapshot_restores_config_and_workspace(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text('{"display_mode":"live2d"}', encoding="utf-8")

    workspace = hermes_home / "yachiyo"
    (workspace / "configs").mkdir(parents=True)
    (workspace / "configs" / "yachiyo.json").write_text("{}", encoding="utf-8")
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")

    backup_root = home / "backups"
    uninstall_result = execute_uninstall(
        UninstallScope.YACHIYO_ONLY,
        keep_config_snapshot=True,
        confirm_text=UNINSTALL_CONFIRM_PHRASE,
        backup_root=backup_root,
    )
    assert uninstall_result.ok is True

    status = get_config_snapshot_status(backup_root)
    assert status["has_snapshot"] is True

    import_result = import_config_snapshot(backup_root=backup_root)

    assert import_result.ok is True
    assert (config_dir / "config.json").read_text(encoding="utf-8") == '{"display_mode":"live2d"}'
    assert (workspace / ".yachiyo_init").exists()
    assert (workspace / "configs" / "yachiyo.json").exists()
    assert import_result.restored


def test_execute_requires_confirm_phrase(tmp_path, monkeypatch):
    _home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    workspace = hermes_home / "yachiyo"
    workspace.mkdir(parents=True)

    result = execute_uninstall(
        UninstallScope.YACHIYO_ONLY,
        keep_config_snapshot=False,
        confirm_text="",
    )

    assert result.ok is False
    assert config_dir.exists()
    assert workspace.exists()
    assert UNINSTALL_CONFIRM_PHRASE in result.errors[0]


def test_include_hermes_removes_hermes_home_and_safe_user_binary(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (hermes_home / "yachiyo").mkdir(parents=True)
    (hermes_home / "config.yaml").write_text("model: test", encoding="utf-8")
    (hermes_home / "bin").mkdir()
    nested_hermes_bin = hermes_home / "bin" / "hermes"
    nested_hermes_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    nested_hermes_bin.chmod(0o755)

    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    hermes_bin = bin_dir / "hermes"
    hermes_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    hermes_bin.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))

    result = execute_uninstall(
        UninstallScope.INCLUDE_HERMES,
        keep_config_snapshot=False,
        confirm_text=UNINSTALL_CONFIRM_PHRASE,
    )

    removed_paths = {item["path"] for item in result.removed}
    assert result.ok is True
    assert not config_dir.exists()
    assert not hermes_home.exists()
    assert not hermes_bin.exists()
    assert str(hermes_home) in removed_paths
    assert str(hermes_bin) in removed_paths
    assert result.failed == []
    assert any(item["path"] == str(nested_hermes_bin) for item in result.skipped)


def test_main_window_api_exposes_uninstall_preview(monkeypatch):
    class RuntimeStub:
        pass

    fake_plan = SimpleNamespace(to_dict=lambda: {"scope": "yachiyo_only", "targets": []})
    calls = []

    def fake_build(scope, keep_config_snapshot):
        calls.append((scope, keep_config_snapshot))
        return fake_plan

    monkeypatch.setattr(uninstall_mod, "build_uninstall_plan", fake_build)

    api = MainWindowAPI(RuntimeStub(), AppConfig())
    result = api.get_uninstall_preview("yachiyo_only", True)

    assert result == {"ok": True, "plan": {"scope": "yachiyo_only", "targets": []}}
    assert calls == [("yachiyo_only", True)]


def test_installer_api_exposes_config_snapshot_status(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("{}", encoding="utf-8")
    workspace = hermes_home / "yachiyo"
    workspace.mkdir(parents=True)
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")

    result = execute_uninstall(
        UninstallScope.YACHIYO_ONLY,
        keep_config_snapshot=True,
        confirm_text=UNINSTALL_CONFIRM_PHRASE,
        backup_root=home / "Hermes-Yachiyo-uninstall-backups",
    )
    assert result.ok is True

    status = InstallerWebViewAPI().get_config_snapshot_status()

    assert status["success"] is True
    assert status["has_snapshot"] is True
    assert status["latest"]["path"] == result.backup_path
