"""Hermes-Yachiyo 卸载功能测试。"""

from __future__ import annotations

import json
import os
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

import apps.shell.config as config_mod
import apps.shell.main_api as main_api_mod
import apps.shell.window as window_mod
from apps.installer import backup as backup_mod
from apps.installer import uninstall as uninstall_mod
from apps.installer.backup import create_backup, get_backup_status, import_backup
from apps.installer.uninstall import (
    UNINSTALL_CONFIRM_PHRASE,
    BackupPlan,
    UninstallScope,
    build_uninstall_plan,
    create_uninstall_backup,
    execute_uninstall,
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


def _write_importable_backup_archive(archive_path: Path, files: dict[str, bytes]) -> None:
    manifest = {
        "schema_version": backup_mod.BACKUP_SCHEMA_VERSION,
        "kind": "hermes-yachiyo-backup",
        "format": "zip",
        "created_at": "2026-04-28T00:00:00+00:00",
        "entries": [{"id": "app_config", "label": "Hermes-Yachiyo 应用配置"}],
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, payload in files.items():
            archive.writestr(name, payload)


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
    assert BackupPlan.__doc__ == "卸载前资料备份计划。"
    assert "tempfile._get_candidate_names" not in Path(backup_mod.__file__).read_text(encoding="utf-8")


def test_execute_yachiyo_only_creates_backup_and_removes_targets(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text('{"display_mode":"bubble"}', encoding="utf-8")

    workspace = hermes_home / "yachiyo"
    (workspace / "configs").mkdir(parents=True)
    (workspace / "configs" / "yachiyo.json").write_text("{}", encoding="utf-8")
    (workspace / "templates").mkdir()
    (workspace / "templates" / "default.json").write_text("{}", encoding="utf-8")
    (workspace / "cache").mkdir()
    (workspace / "cache" / "state.json").write_text("{}", encoding="utf-8")
    (workspace / "logs").mkdir()
    (workspace / "logs" / "app.log").write_text("log", encoding="utf-8")
    (workspace / "assets" / "live2d").mkdir(parents=True)
    (workspace / "assets" / "live2d" / "model.model3.json").write_text("{}", encoding="utf-8")
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
    backups = list(backup_path.glob("*.zip"))
    assert len(backups) == 1
    backup = backups[0]
    assert result.backup_path == str(backup.resolve())
    with zipfile.ZipFile(backup) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

    assert "manifest.json" in names
    assert "entries" in manifest
    assert "copied" not in manifest
    assert "source_app_config_dir" not in manifest
    assert "source_hermes_home" not in manifest
    assert "source_yachiyo_workspace" not in manifest
    assert all("source" not in entry for entry in manifest["entries"])
    assert "app-config/config.json" in names
    assert "yachiyo-workspace/configs/yachiyo.json" in names
    assert "yachiyo-workspace/templates/default.json" in names
    assert "yachiyo-workspace/cache/state.json" in names
    assert "yachiyo-workspace/logs/app.log" in names
    assert "yachiyo-workspace/assets/live2d/model.model3.json" in names
    assert "yachiyo-workspace/chat.db" in names


def test_create_uninstall_backup_uses_plan_backup_root_by_default(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("{}", encoding="utf-8")
    workspace = hermes_home / "yachiyo"
    workspace.mkdir(parents=True)
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")

    backup_root = home / "planned-backups"
    override_root = home / "override-backups"
    plan = build_uninstall_plan(
        UninstallScope.YACHIYO_ONLY,
        keep_config_snapshot=True,
        backup_root=backup_root,
    )

    planned_backup = create_uninstall_backup(plan)
    override_backup = create_uninstall_backup(plan, backup_root=override_root)

    assert planned_backup.parent == backup_root.resolve()
    assert override_backup.parent == override_root.resolve()


def test_create_backup_is_available_without_uninstall(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text('{"display_mode":"bubble"}', encoding="utf-8")

    workspace = hermes_home / "yachiyo"
    (workspace / "projects").mkdir(parents=True)
    (workspace / "projects" / "demo.json").write_text("{}", encoding="utf-8")
    (workspace / "chat.db").write_text("chat", encoding="utf-8")

    backup = create_backup(backup_root=home / "backups")

    assert backup.valid is True
    assert backup.format == "zip"
    assert config_dir.exists()
    assert workspace.exists()
    with zipfile.ZipFile(backup.path) as archive:
        names = set(archive.namelist())
    assert "app-config/config.json" in names
    assert "yachiyo-workspace/projects/demo.json" in names
    assert "yachiyo-workspace/chat.db" in names


def test_create_backup_skips_top_level_and_nested_symlinks(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    real_config_dir = home / "real-config"
    real_config_dir.mkdir(parents=True)
    (real_config_dir / "config.json").write_text('{"from":"symlink"}', encoding="utf-8")
    config_dir.symlink_to(real_config_dir, target_is_directory=True)

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "secret.txt"
    outside_file.write_text("secret", encoding="utf-8")
    (outside_dir / "nested-secret.txt").write_text("nested", encoding="utf-8")

    workspace = hermes_home / "yachiyo"
    workspace.mkdir(parents=True)
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")
    (workspace / "linked-secret.txt").symlink_to(outside_file)
    (workspace / "linked-dir").symlink_to(outside_dir, target_is_directory=True)
    (workspace / "normal.txt").write_text("normal", encoding="utf-8")

    backup = create_backup(backup_root=home / "backups")

    with zipfile.ZipFile(backup.path) as archive:
        names = set(archive.namelist())
        payload = b"\n".join(
            archive.read(name)
            for name in names
            if not name.endswith("/") and name != "manifest.json"
        )

    assert "app-config/config.json" not in names
    assert "yachiyo-workspace/linked-secret.txt" not in names
    assert not any(name.startswith("yachiyo-workspace/linked-dir") for name in names)
    assert "yachiyo-workspace/normal.txt" in names
    assert b"secret" not in payload
    assert b"nested" not in payload


def test_create_backup_cleans_up_old_backups_by_count(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("{}", encoding="utf-8")
    workspace = hermes_home / "yachiyo"
    workspace.mkdir(parents=True)
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")

    backup_root = home / "backups"
    created_paths = []
    for index in range(4):
        (workspace / "counter.txt").write_text(str(index), encoding="utf-8")
        backup = create_backup(backup_root=backup_root, retention_count=2)
        created_paths.append(backup.path)

    remaining = sorted(path.name for path in backup_root.glob("*.zip"))
    assert len(remaining) == 2
    assert not Path(created_paths[0]).exists()
    assert not Path(created_paths[1]).exists()


def test_create_backup_cleans_partial_temp_archive_when_zip_write_fails(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("{}", encoding="utf-8")
    workspace = hermes_home / "yachiyo"
    workspace.mkdir(parents=True)
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")

    backup_root = home / "backups"
    temp_archives = []

    def fail_zip_write(_source_dir, archive_path):
        temp_archives.append(archive_path)
        archive_path.write_bytes(b"partial zip")
        raise RuntimeError("zip failed")

    monkeypatch.setattr(backup_mod, "_write_zip_from_dir", fail_zip_write)

    with pytest.raises(RuntimeError, match="zip failed"):
        create_backup(backup_root=backup_root)

    assert temp_archives
    assert all(not path.exists() for path in temp_archives)
    assert list(backup_root.glob("*.zip")) == []
    assert backup_mod.find_backups(backup_root) == []


def test_create_backup_removes_published_archive_when_cleanup_fails(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("{}", encoding="utf-8")
    workspace = hermes_home / "yachiyo"
    workspace.mkdir(parents=True)
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")

    backup_root = home / "backups"

    def fail_cleanup(*, backup_root=None, keep_count=10):
        raise RuntimeError("cleanup failed")

    monkeypatch.setattr(backup_mod, "cleanup_old_backups", fail_cleanup)

    with pytest.raises(RuntimeError, match="cleanup failed"):
        create_backup(backup_root=backup_root)

    assert list(backup_root.glob("*.zip")) == []
    assert backup_mod.find_backups(backup_root) == []


def test_cleanup_old_backups_counts_invalid_managed_backups(tmp_path):
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    names = [
        "hermes-yachiyo-backup-20260428-101500.zip",
        "hermes-yachiyo-backup-20260428-101501.zip",
        "hermes-yachiyo-backup-20260428-101502.zip",
    ]
    for index, name in enumerate(names):
        path = backup_root / name
        path.write_bytes(b"not a zip")
        timestamp = 1_900_000_000 + index
        os.utime(path, (timestamp, timestamp))

    deleted = backup_mod.cleanup_old_backups(backup_root=backup_root, keep_count=2)

    remaining = sorted(path.name for path in backup_root.glob("*.zip"))
    assert remaining == names[1:]
    assert [Path(item.path).name for item in deleted] == [names[0]]
    assert deleted[0].valid is False


def test_cleanup_old_backups_skips_unmanageable_delete_errors(tmp_path, monkeypatch):
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    names = [
        "hermes-yachiyo-backup-20260428-101500.zip",
        "hermes-yachiyo-backup-20260428-101501.zip",
        "hermes-yachiyo-backup-20260428-101502.zip",
    ]
    for index, name in enumerate(names):
        path = backup_root / name
        path.write_bytes(b"not a zip")
        timestamp = 1_900_000_000 + index
        os.utime(path, (timestamp, timestamp))

    calls = []
    original_delete = backup_mod.delete_backup

    def flaky_delete(path, *, backup_root=None):
        calls.append(Path(path).name)
        if Path(path).name == names[0]:
            raise ValueError("not managed")
        return original_delete(path, backup_root=backup_root)

    monkeypatch.setattr(backup_mod, "delete_backup", flaky_delete)

    deleted = backup_mod.cleanup_old_backups(backup_root=backup_root, keep_count=1)

    assert calls == [names[1], names[0]]
    assert [Path(item.path).name for item in deleted] == [names[1]]
    assert (backup_root / names[0]).exists()
    assert not (backup_root / names[1]).exists()
    assert (backup_root / names[2]).exists()


def test_find_backups_ignores_noncanonical_prefixed_zip_names(tmp_path):
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    canonical = backup_root / "hermes-yachiyo-backup-20260428-101500.zip"
    noncanonical = backup_root / "hermes-yachiyo-backup-20260428-101500-draft.zip"
    canonical.write_bytes(b"not a zip")
    noncanonical.write_bytes(b"not a zip")

    backups = backup_mod.find_backups(backup_root)

    assert [Path(item.path).name for item in backups] == [canonical.name]


def test_backup_filename_order_parses_only_extra_numeric_suffix(tmp_path):
    assert (
        backup_mod._filename_order(
            tmp_path / "hermes-yachiyo-backup-20260428-101531.zip"
        )
        == 1
    )
    assert (
        backup_mod._filename_order(
            tmp_path / "hermes-yachiyo-backup-20260428-101531-2.zip"
        )
        == 2
    )
    assert backup_mod._filename_order(tmp_path / "hermes-yachiyo-backup-20260428.zip") == 0


def test_unique_backup_archive_uses_dash_two_for_same_second(tmp_path, monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 4, 28, 10, 15, 31, tzinfo=tz)

    monkeypatch.setattr(backup_mod, "datetime", FixedDateTime)
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    base = backup_root / "hermes-yachiyo-backup-20260428-101531.zip"
    base.write_text("base", encoding="utf-8")

    candidate = backup_mod._unique_backup_archive(backup_root)

    assert candidate.name == "hermes-yachiyo-backup-20260428-101531-2.zip"


def test_unique_backup_archive_ignores_invalid_same_second_matches(tmp_path, monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 4, 28, 10, 15, 31, tzinfo=tz)

    monkeypatch.setattr(backup_mod, "datetime", FixedDateTime)
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    invalid = backup_root / "hermes-yachiyo-backup-20260428-101531-draft.zip"
    invalid.write_text("invalid", encoding="utf-8")

    candidate = backup_mod._unique_backup_archive(backup_root)

    assert candidate.name == "hermes-yachiyo-backup-20260428-101531.zip"
    assert not candidate.name.endswith("-1.zip")


def test_create_backup_can_overwrite_latest_backup(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("{}", encoding="utf-8")
    workspace = hermes_home / "yachiyo"
    workspace.mkdir(parents=True)
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")

    backup_root = home / "backups"
    first = create_backup(backup_root=backup_root, auto_cleanup=False)
    second = create_backup(
        backup_root=backup_root,
        auto_cleanup=False,
        overwrite_latest=True,
    )

    assert not Path(first.path).exists()
    assert Path(second.path).exists()
    assert len(list(backup_root.glob("*.zip"))) == 1


def test_import_backup_restores_config_and_workspace(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text('{"display_mode":"live2d"}', encoding="utf-8")

    workspace = hermes_home / "yachiyo"
    (workspace / "configs").mkdir(parents=True)
    (workspace / "configs" / "yachiyo.json").write_text("{}", encoding="utf-8")
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")
    (workspace / "chat.db").write_text("chat", encoding="utf-8")

    backup_root = home / "backups"
    uninstall_result = execute_uninstall(
        UninstallScope.YACHIYO_ONLY,
        keep_config_snapshot=True,
        confirm_text=UNINSTALL_CONFIRM_PHRASE,
        backup_root=backup_root,
    )
    assert uninstall_result.ok is True

    status = get_backup_status(backup_root)
    assert status["has_backup"] is True

    import_result = import_backup(backup_root=backup_root)

    assert import_result.ok is True
    assert (config_dir / "config.json").read_text(encoding="utf-8") == '{"display_mode":"live2d"}'
    assert (workspace / ".yachiyo_init").exists()
    assert (workspace / "configs" / "yachiyo.json").exists()
    assert (workspace / "chat.db").exists()
    assert import_result.restored


def test_import_backup_rejects_zip_entry_over_size_limit(tmp_path, monkeypatch):
    home, _hermes_home, _config_dir = _prepare_home(tmp_path, monkeypatch)
    archive_path = home / "hermes-yachiyo-backup-20260428-101531.zip"
    _write_importable_backup_archive(archive_path, {"app-config/config.json": b"x" * 300})
    monkeypatch.setattr(backup_mod, "MAX_BACKUP_IMPORT_ENTRY_BYTES", 256)
    monkeypatch.setattr(backup_mod, "MAX_BACKUP_IMPORT_TOTAL_BYTES", 1024)

    with pytest.raises(ValueError, match="单个条目"):
        import_backup(archive_path)


def test_import_backup_rejects_zip_total_uncompressed_size_limit(tmp_path, monkeypatch):
    home, _hermes_home, _config_dir = _prepare_home(tmp_path, monkeypatch)
    archive_path = home / "hermes-yachiyo-backup-20260428-101531.zip"
    _write_importable_backup_archive(
        archive_path,
        {
            "app-config/config.json": b"x" * 80,
            "app-config/extra.json": b"y" * 80,
        },
    )
    monkeypatch.setattr(backup_mod, "MAX_BACKUP_IMPORT_ENTRY_BYTES", 1024)
    monkeypatch.setattr(backup_mod, "MAX_BACKUP_IMPORT_TOTAL_BYTES", 300)

    with pytest.raises(ValueError, match="解压后体积"):
        import_backup(archive_path)


def test_extract_zip_safely_limits_actual_written_entry_bytes(tmp_path, monkeypatch):
    class FakeMember:
        filename = "app-config/config.json"
        file_size = 1

        def is_dir(self):
            return False

    class FakeArchive:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def infolist(self):
            return [FakeMember()]

        def open(self, _member, _mode="r"):
            return BytesIO(b"x" * 12)

    monkeypatch.setattr(
        backup_mod.zipfile,
        "ZipFile",
        lambda *_args, **_kwargs: FakeArchive(),
    )
    monkeypatch.setattr(backup_mod, "MAX_BACKUP_IMPORT_ENTRY_BYTES", 8)
    monkeypatch.setattr(backup_mod, "MAX_BACKUP_IMPORT_TOTAL_BYTES", 1024)
    monkeypatch.setattr(backup_mod, "_ZIP_COPY_CHUNK_BYTES", 4)

    target_dir = tmp_path / "payload"
    target_dir.mkdir()

    with pytest.raises(ValueError, match="单个条目"):
        backup_mod._extract_zip_safely(tmp_path / "fake.zip", target_dir)

    assert not (target_dir / "app-config" / "config.json").exists()


def test_extract_zip_safely_limits_actual_written_total_bytes(tmp_path, monkeypatch):
    class FakeMember:
        file_size = 1

        def __init__(self, filename: str) -> None:
            self.filename = filename

        def is_dir(self):
            return False

    members = [
        FakeMember("app-config/one.json"),
        FakeMember("app-config/two.json"),
    ]

    class FakeArchive:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def infolist(self):
            return members

        def open(self, _member, _mode="r"):
            return BytesIO(b"x" * 4)

    monkeypatch.setattr(
        backup_mod.zipfile,
        "ZipFile",
        lambda *_args, **_kwargs: FakeArchive(),
    )
    monkeypatch.setattr(backup_mod, "MAX_BACKUP_IMPORT_ENTRY_BYTES", 1024)
    monkeypatch.setattr(backup_mod, "MAX_BACKUP_IMPORT_TOTAL_BYTES", 6)
    monkeypatch.setattr(backup_mod, "_ZIP_COPY_CHUNK_BYTES", 4)

    target_dir = tmp_path / "payload"
    target_dir.mkdir()

    with pytest.raises(ValueError, match="解压后体积"):
        backup_mod._extract_zip_safely(tmp_path / "fake.zip", target_dir)

    assert (target_dir / "app-config" / "one.json").read_bytes() == b"x" * 4
    assert not (target_dir / "app-config" / "two.json").exists()


def test_import_backup_rejects_duplicate_zip_entries(tmp_path, monkeypatch):
    home, _hermes_home, _config_dir = _prepare_home(tmp_path, monkeypatch)
    archive_path = home / "hermes-yachiyo-backup-20260428-101531.zip"
    manifest = {
        "schema_version": backup_mod.BACKUP_SCHEMA_VERSION,
        "kind": "hermes-yachiyo-backup",
        "format": "zip",
        "created_at": "2026-04-28T00:00:00+00:00",
        "entries": [{"id": "app_config", "label": "Hermes-Yachiyo 应用配置"}],
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("app-config/config.json", b'{"a":1}')
        archive.writestr("app-config/config.json", b'{"a":2}')

    with pytest.raises(ValueError, match="重复条目"):
        import_backup(archive_path)


def test_import_backup_skips_file_app_config_source(tmp_path, monkeypatch):
    home, _hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text('{"display_mode":"bubble"}', encoding="utf-8")
    archive_path = home / "hermes-yachiyo-backup-20260428-101531.zip"
    manifest = {
        "schema_version": backup_mod.BACKUP_SCHEMA_VERSION,
        "kind": "hermes-yachiyo-backup",
        "format": "zip",
        "created_at": "2026-04-28T00:00:00+00:00",
        "entries": [{"id": "app_config", "label": "Hermes-Yachiyo 应用配置"}],
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("app-config", b"not a directory")

    result = import_backup(archive_path)

    assert result.ok is True
    assert config_dir.is_dir()
    assert (
        (config_dir / "config.json").read_text(encoding="utf-8")
        == '{"display_mode":"bubble"}'
    )
    assert any("应用配置不是目录" in item["reason"] for item in result.skipped)


def test_import_backup_skips_file_workspace_source(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    workspace = hermes_home / "yachiyo"
    workspace.mkdir(parents=True)
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")
    archive_path = home / "hermes-yachiyo-backup-20260428-101531.zip"
    manifest = {
        "schema_version": backup_mod.BACKUP_SCHEMA_VERSION,
        "kind": "hermes-yachiyo-backup",
        "format": "zip",
        "created_at": "2026-04-28T00:00:00+00:00",
        "entries": [{"id": "yachiyo_workspace", "label": "Yachiyo 工作空间"}],
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("yachiyo-workspace", b"not a directory")

    result = import_backup(archive_path)

    assert result.ok is True
    assert workspace.is_dir()
    assert (workspace / ".yachiyo_init").exists()
    assert any("工作空间不是目录" in item["reason"] for item in result.skipped)


def test_replace_path_rolls_back_when_move_to_target_fails(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.write_text("new", encoding="utf-8")
    target = tmp_path / "target"
    target.write_text("old", encoding="utf-8")

    real_move = backup_mod.shutil.move
    call_count = {"count": 0}

    def flaky_move(src, dst):
        call_count["count"] += 1
        if call_count["count"] == 2:
            raise OSError("simulated move failure")
        return real_move(src, dst)

    monkeypatch.setattr(backup_mod.shutil, "move", flaky_move)

    with pytest.raises(OSError, match="simulated move failure"):
        backup_mod._replace_path(source, target)

    assert target.read_text(encoding="utf-8") == "old"


def test_import_backup_skips_workspace_restore_outside_home(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text('{"display_mode":"live2d"}', encoding="utf-8")

    workspace = hermes_home / "yachiyo"
    workspace.mkdir(parents=True)
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")
    (workspace / "state.json").write_text('{"safe":true}', encoding="utf-8")

    backup = create_backup(backup_root=home / "backups")
    outside_hermes_home = tmp_path / "outside-hermes"
    monkeypatch.setenv("HERMES_HOME", str(outside_hermes_home))

    result = import_backup(backup.path)

    assert result.ok is True
    assert not (outside_hermes_home / "yachiyo").exists()
    assert any("不在当前用户目录" in item["reason"] for item in result.skipped)


def test_yachiyo_workspace_outside_home_is_not_removable(tmp_path, monkeypatch):
    home, _hermes_home, _config_dir = _prepare_home(tmp_path, monkeypatch)
    outside_hermes_home = tmp_path / "outside-hermes"
    workspace = outside_hermes_home / "yachiyo"
    workspace.mkdir(parents=True)
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(outside_hermes_home))

    plan = build_uninstall_plan(
        UninstallScope.YACHIYO_ONLY,
        keep_config_snapshot=False,
        backup_root=home / "backups",
    )

    target = next(item for item in plan.targets if item.id == "yachiyo_workspace")
    assert target.exists is True
    assert target.removable is False
    assert "不在当前用户目录" in target.reason


def test_yachiyo_workspace_without_marker_is_not_removable(tmp_path, monkeypatch):
    home, hermes_home, _config_dir = _prepare_home(tmp_path, monkeypatch)
    workspace = hermes_home / "yachiyo"
    workspace.mkdir(parents=True)
    (workspace / "state.json").write_text("{}", encoding="utf-8")

    plan = build_uninstall_plan(
        UninstallScope.YACHIYO_ONLY,
        keep_config_snapshot=False,
        backup_root=home / "backups",
    )

    target = next(item for item in plan.targets if item.id == "yachiyo_workspace")
    assert target.exists is True
    assert target.removable is False
    assert "初始化标识" in target.reason


def test_public_path_safety_helpers_preserve_strict_rules(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    assert backup_mod.protected_paths()
    assert backup_mod.is_protected_path(home) is True

    config_dir.mkdir(parents=True)
    safe, reason = backup_mod.is_safe_app_config_dir(config_dir)
    assert safe is True
    assert reason == ""

    wrong_config = home / "not-hermes-yachiyo"
    wrong_config.mkdir()
    safe, reason = backup_mod.is_safe_app_config_dir(wrong_config)
    assert safe is False
    assert "配置目录名称" in reason

    workspace = hermes_home / "yachiyo"
    workspace.mkdir(parents=True)

    safe, reason = backup_mod.is_safe_yachiyo_workspace(workspace)
    assert safe is False
    assert "初始化标识" in reason

    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")
    safe, reason = backup_mod.is_safe_yachiyo_workspace(workspace)
    assert safe is True
    assert reason == ""


def test_protected_paths_cache_is_scoped_by_home(tmp_path, monkeypatch):
    backup_mod._protected_paths_for_home.cache_clear()

    home_one = tmp_path / "home-one"
    home_two = tmp_path / "home-two"
    home_one.mkdir()
    home_two.mkdir()

    monkeypatch.setenv("HOME", str(home_one))
    first = backup_mod.protected_paths()
    second = backup_mod.protected_paths()
    first_cache_info = backup_mod._protected_paths_for_home.cache_info()

    monkeypatch.setenv("HOME", str(home_two))
    third = backup_mod.protected_paths()
    second_cache_info = backup_mod._protected_paths_for_home.cache_info()

    assert first == second
    assert home_one.resolve() in first
    assert home_two.resolve() in third
    assert home_one.resolve() not in third
    assert first_cache_info.hits >= 1
    assert second_cache_info.misses == first_cache_info.misses + 1
    assert "return set(_protected_paths_for_home(home))" not in Path(
        backup_mod.__file__
    ).read_text(encoding="utf-8")


def test_public_path_safety_helpers_allow_symlink_paths_under_home(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)

    real_config_dir = home / "real-config"
    real_config_dir.mkdir(parents=True)
    config_dir.symlink_to(real_config_dir, target_is_directory=True)

    workspace_target = tmp_path / "workspace-target"
    workspace_target.mkdir(parents=True)
    workspace = hermes_home / "yachiyo"
    workspace.parent.mkdir(parents=True, exist_ok=True)
    workspace.symlink_to(workspace_target, target_is_directory=True)

    safe, reason = backup_mod.is_safe_app_config_dir(config_dir)
    assert safe is True
    assert reason == ""

    safe, reason = backup_mod.is_safe_yachiyo_workspace(workspace)
    assert safe is True
    assert reason == ""


def test_backup_import_and_uninstall_use_public_path_safety_helpers(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("{}", encoding="utf-8")
    workspace = hermes_home / "yachiyo"
    workspace.mkdir(parents=True)
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")
    backup = create_backup(backup_root=home / "backups")

    calls: list[str] = []
    original_app_config = backup_mod.is_safe_app_config_dir
    original_workspace = backup_mod.is_safe_yachiyo_workspace

    def track_app_config(path):
        calls.append("app_config")
        return original_app_config(path)

    def track_workspace(path):
        calls.append("workspace")
        return original_workspace(path)

    monkeypatch.setattr(backup_mod, "is_safe_app_config_dir", track_app_config)
    monkeypatch.setattr(backup_mod, "is_safe_yachiyo_workspace", track_workspace)

    import_result = import_backup(backup.path)
    assert import_result.ok is True

    plan = build_uninstall_plan(
        UninstallScope.YACHIYO_ONLY,
        keep_config_snapshot=False,
        backup_root=home / "backups",
    )

    assert any(target.id == "app_config_dir" and target.removable for target in plan.targets)
    assert any(target.id == "yachiyo_workspace" and target.removable for target in plan.targets)
    assert calls.count("app_config") >= 2
    assert calls.count("workspace") >= 2


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


def test_execute_accepts_confirm_phrase_with_outer_whitespace(tmp_path, monkeypatch):
    _home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    workspace = hermes_home / "yachiyo"
    workspace.mkdir(parents=True)
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")

    result = execute_uninstall(
        UninstallScope.YACHIYO_ONLY,
        keep_config_snapshot=False,
        confirm_text=f"  {UNINSTALL_CONFIRM_PHRASE}\n",
    )

    assert result.ok is True
    assert not config_dir.exists()
    assert not workspace.exists()


def test_include_hermes_named_home_without_markers_is_not_removable(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    hermes_home.mkdir(parents=True)

    plan = build_uninstall_plan(
        UninstallScope.INCLUDE_HERMES,
        keep_config_snapshot=False,
        backup_root=home / "backups",
    )

    target = next(item for item in plan.targets if item.id == "hermes_home")
    assert target.exists is True
    assert target.removable is False
    assert "不像 Hermes Home" in target.reason


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


def test_main_window_api_creates_backup_without_uninstall(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("{}", encoding="utf-8")
    workspace = hermes_home / "yachiyo"
    workspace.mkdir(parents=True)
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")

    api = MainWindowAPI(SimpleNamespace(), AppConfig())
    result = api.create_backup()

    assert result["ok"] is True
    assert result["backup_path"].endswith(".zip")
    assert (home / "Hermes-Yachiyo-backups").exists()
    assert config_dir.exists()
    assert workspace.exists()


def test_main_window_api_update_backup_settings_uses_common_settings_path(tmp_path, monkeypatch):
    _home, _hermes_home, _config_dir = _prepare_home(tmp_path, monkeypatch)
    config = AppConfig()
    calls = []
    original_apply = main_api_mod.apply_settings_changes

    def track_apply(config_obj, changes, *, persist=True):
        calls.append((changes.copy(), persist))
        return original_apply(config_obj, changes, persist=persist)

    monkeypatch.setattr(main_api_mod, "apply_settings_changes", track_apply)

    api = MainWindowAPI(SimpleNamespace(), config)
    result = api.update_backup_settings(False, 3)

    assert result["ok"] is True
    assert result["backup"] == {"auto_cleanup_enabled": False, "retention_count": 3}
    assert calls == [
        ({"backup.auto_cleanup_enabled": False, "backup.retention_count": 3}, False),
        ({"backup.auto_cleanup_enabled": False, "backup.retention_count": 3}, True),
    ]


def test_main_window_api_update_backup_settings_rejects_invalid_count_without_partial_save(
    tmp_path,
    monkeypatch,
):
    _home, _hermes_home, _config_dir = _prepare_home(tmp_path, monkeypatch)
    config = AppConfig()
    config.backup.auto_cleanup_enabled = True
    config.backup.retention_count = 5

    api = MainWindowAPI(SimpleNamespace(), config)
    result = api.update_backup_settings(False, 101)

    assert result["ok"] is False
    assert "1-100" in result["error"]
    assert config.backup.auto_cleanup_enabled is True
    assert config.backup.retention_count == 5


def test_main_window_api_overwrites_and_deletes_backup(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("{}", encoding="utf-8")
    workspace = hermes_home / "yachiyo"
    workspace.mkdir(parents=True)
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")

    api = MainWindowAPI(SimpleNamespace(), AppConfig())
    first = api.create_backup()
    second = api.create_backup(True)
    assert first["ok"] is True
    assert second["ok"] is True
    assert len(list((home / "Hermes-Yachiyo-backups").glob("*.zip"))) == 1

    deleted = api.delete_backup(second["backup_path"])
    assert deleted["ok"] is True
    assert deleted["status"]["has_backup"] is False


def test_main_window_api_restores_backup(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text('{"display_mode":"live2d"}', encoding="utf-8")
    workspace = hermes_home / "yachiyo"
    workspace.mkdir(parents=True)
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")

    backup = create_backup()
    (config_dir / "config.json").write_text('{"display_mode":"bubble"}', encoding="utf-8")
    restart_calls = []
    monkeypatch.setattr(window_mod, "request_app_restart", lambda: restart_calls.append(True))

    api = MainWindowAPI(SimpleNamespace(), AppConfig())
    result = api.restore_backup(backup.path)

    assert result["ok"] is True
    assert result["restart_scheduled"] is True
    assert restart_calls == [True]
    assert (config_dir / "config.json").read_text(encoding="utf-8") == '{"display_mode":"live2d"}'


def test_main_window_api_open_backup_location_allows_only_managed_backups(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("{}", encoding="utf-8")
    workspace = hermes_home / "yachiyo"
    workspace.mkdir(parents=True)
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")

    calls = []

    def fake_popen(command, stdout=None, stderr=None):
        calls.append(command)
        return SimpleNamespace()

    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("subprocess.Popen", fake_popen)

    api = MainWindowAPI(SimpleNamespace(), AppConfig())
    root_result = api.open_backup_location("")
    assert root_result["ok"] is True
    assert calls[-1] == ["open", str(home / "Hermes-Yachiyo-backups")]

    backup = create_backup()
    backup_result = api.open_backup_location(backup.path)
    assert backup_result["ok"] is True
    assert calls[-1] == ["open", "-R", backup.path]

    external_backup = home / "hermes-yachiyo-backup-external.zip"
    external_backup.write_text("not managed", encoding="utf-8")
    call_count = len(calls)
    rejected = api.open_backup_location(str(external_backup))
    assert rejected["ok"] is False
    assert len(calls) == call_count


def test_resolve_managed_backup_path_rejects_noncanonical_name_in_backup_root(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("{}", encoding="utf-8")
    workspace = hermes_home / "yachiyo"
    workspace.mkdir(parents=True)
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")

    backup_root = home / "Hermes-Yachiyo-backups"
    backup_root.mkdir(parents=True)
    fake_backup = backup_root / "hermes-yachiyo-backup-manual.zip"
    fake_backup.write_text("manual", encoding="utf-8")

    with pytest.raises(ValueError, match="名称不符合预期"):
        backup_mod.resolve_managed_backup_path(fake_backup)


def test_main_window_api_open_backup_location_supports_windows(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("{}", encoding="utf-8")
    workspace = hermes_home / "yachiyo"
    workspace.mkdir(parents=True)
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")

    calls = []
    startfile_calls = []

    def fake_popen(command, stdout=None, stderr=None):
        calls.append(command)
        return SimpleNamespace()

    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr("os.startfile", lambda path: startfile_calls.append(path), raising=False)

    api = MainWindowAPI(SimpleNamespace(), AppConfig())
    root_result = api.open_backup_location("")
    assert root_result["ok"] is True
    assert startfile_calls == [str(home / "Hermes-Yachiyo-backups")]

    backup = create_backup()
    backup_result = api.open_backup_location(backup.path)
    assert backup_result["ok"] is True
    assert calls[-1] == ["explorer.exe", "/select,", backup.path]


def test_installer_api_exposes_backup_status_and_import(tmp_path, monkeypatch):
    home, hermes_home, config_dir = _prepare_home(tmp_path, monkeypatch)
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text('{"display_mode":"live2d"}', encoding="utf-8")
    workspace = hermes_home / "yachiyo"
    workspace.mkdir(parents=True)
    (workspace / ".yachiyo_init").write_text("{}", encoding="utf-8")

    backup = create_backup()
    (config_dir / "config.json").unlink()

    api = InstallerWebViewAPI()
    status = api.get_backup_status()

    assert status["success"] is True
    assert status["has_backup"] is True
    assert status["latest"]["path"] == backup.path

    result = api.import_backup()
    assert result["ok"] is True
    assert (config_dir / "config.json").read_text(encoding="utf-8") == '{"display_mode":"live2d"}'
