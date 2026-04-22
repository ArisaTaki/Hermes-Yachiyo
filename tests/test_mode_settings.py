"""Mode settings model and update behavior tests."""

from __future__ import annotations

import json
import sys
import types
import zipfile
from pathlib import Path

import apps.shell.config as config_mod
import apps.shell.settings as settings_mod
from apps.shell.assets import (
    DEFAULT_BUBBLE_AVATAR_PATH,
    LEGACY_BUNDLED_LIVE2D_MODEL_DIR,
    LIVE2D_RELEASES_URL,
)
from apps.shell.config import AppConfig, ModelState, load_config, save_config
from apps.shell.mode_settings import (
    apply_settings_changes,
    serialize_mode_settings,
    serialize_mode_window_data,
)
from apps.shell.settings import ModeSettingsAPI, _SETTINGS_HTML, _import_live2d_archive, open_mode_settings_window


def _create_live2d_model_dir(root: Path, model_name: str = "demo") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{model_name}.model3.json").write_text("{}", encoding="utf-8")
    (root / f"{model_name}.moc3").write_text("stub", encoding="utf-8")
    return root


def _patch_no_live2d_assets(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config_mod, "find_default_live2d_model_dir", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(config_mod, "get_user_live2d_assets_dir", lambda: tmp_path / "assets" / "live2d")


class _DialogWindowStub:
    def __init__(self, selection: tuple[str, ...] | None) -> None:
        self.selection = selection
        self.show_calls = 0
        self.closed = False
        self.events = _WindowEventsStub()

    def create_file_dialog(self, *_args, **_kwargs):
        return self.selection

    def show(self):
        self.show_calls += 1


class _EventHookStub:
    def __init__(self) -> None:
        self.handler = None

    def __iadd__(self, handler):
        self.handler = handler
        return self


class _WindowEventsStub:
    def __init__(self) -> None:
        self.closed = _EventHookStub()


class _WebviewModuleStub:
    def __init__(self) -> None:
        self.create_calls = 0
        self.last_window: _DialogWindowStub | None = None
        self.on_create = None

    def create_window(self, **_kwargs):
        self.create_calls += 1
        if self.on_create is not None:
            self.on_create()
        self.last_window = _DialogWindowStub(None)
        return self.last_window


def test_app_config_has_separate_mode_models(monkeypatch, tmp_path):
    _patch_no_live2d_assets(monkeypatch, tmp_path)
    config = AppConfig()

    assert config.window_mode.width > 0
    assert config.bubble_mode.summary_count == 3
    assert config.bubble_mode.avatar_path == str(DEFAULT_BUBBLE_AVATAR_PATH)
    assert config.bubble_mode.proactive_enabled is False
    assert config.live2d_mode.idle_motion_group == "Idle"
    assert config.live2d_mode.scale == 1.0
    assert config.live2d_mode.show_on_all_spaces is True
    assert config.live2d_mode.model_name == ""
    assert config.live2d_mode.model_path == ""
    assert config.live2d_mode.validate() == ModelState.NOT_CONFIGURED
    assert config.live2d is config.live2d_mode


def test_live2d_auto_discovers_user_assets(monkeypatch, tmp_path):
    user_root = tmp_path / "user-assets" / "live2d"
    model_dir = _create_live2d_model_dir(user_root / "yachiyo")
    monkeypatch.setattr(config_mod, "get_user_live2d_assets_dir", lambda: user_root)
    monkeypatch.setattr(
        config_mod,
        "find_default_live2d_model_dir",
        lambda *_args, **_kwargs: user_root,
    )

    config = AppConfig()
    resource = config.live2d_mode.resource_info()

    assert resource.state == ModelState.PATH_VALID
    assert resource.source == "auto_discovered"
    assert resource.effective_model_path == str(model_dir)
    assert resource.default_assets_root_display.endswith("user-assets/live2d")


def test_apply_settings_changes_updates_bubble_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    config = AppConfig()

    result = apply_settings_changes(
        config,
        {
            "bubble_mode.summary_count": 2,
            "bubble_mode.default_display": "recent_reply",
            "bubble_mode.opacity": 0.8,
            "bubble_mode.proactive_enabled": True,
            "bubble_mode.proactive_desktop_watch_enabled": True,
            "bubble_mode.proactive_interval_seconds": 120,
        },
    )

    assert result["ok"] is True
    assert config.bubble_mode.summary_count == 2
    assert config.bubble_mode.default_display == "recent_reply"
    assert config.bubble_mode.opacity == 0.8
    assert config.bubble_mode.proactive_enabled is True
    assert config.bubble_mode.proactive_desktop_watch_enabled is True
    assert config.bubble_mode.proactive_interval_seconds == 120
    assert result["mode_settings"]["bubble"]["config"]["summary_count"] == 2


def test_apply_settings_changes_rejects_invalid_single_field(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    config = AppConfig()

    result = apply_settings_changes(config, {"bubble_mode.summary_count": 8})

    assert result["ok"] is False
    assert result["applied"] == {}
    assert config.bubble_mode.summary_count == 3
    assert "summary_count" in result["error"]


def test_apply_settings_changes_supports_legacy_live2d_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    config = AppConfig()

    result = apply_settings_changes(
        config,
        {
            "live2d.model_name": "hiyori",
            "live2d.window_on_top": False,
            "live2d.scale": 1.25,
        },
    )

    assert result["ok"] is True
    assert config.live2d_mode.model_name == "hiyori"
    assert config.live2d_mode.window_on_top is False
    assert config.live2d_mode.scale == 1.25


def test_serialize_mode_settings_returns_separate_sections(monkeypatch, tmp_path):
    _patch_no_live2d_assets(monkeypatch, tmp_path)
    config = AppConfig()

    payload = serialize_mode_settings(config)

    assert set(payload) == {"bubble", "live2d"}
    assert "摘要" in payload["bubble"]["summary"]
    assert "未导入资源" in payload["live2d"]["summary"]
    assert payload["bubble"]["config"]["avatar_path_display"].startswith(
        "apps/shell/assets/avatars/"
    )
    assert payload["live2d"]["config"]["model_path_display"] == ""
    assert payload["live2d"]["config"]["resource"]["releases_url"] == LIVE2D_RELEASES_URL
    assert payload["live2d"]["config"]["resource"]["state"] == "not_configured"


def test_serialize_mode_window_data_returns_mode_part_only(monkeypatch, tmp_path):
    _patch_no_live2d_assets(monkeypatch, tmp_path)
    config = AppConfig(display_mode="live2d")
    config.live2d_mode.scale = 1.2

    payload = serialize_mode_window_data(config, "live2d")

    assert "common" not in payload
    assert payload["mode"]["id"] == "live2d"
    assert payload["settings"]["config"]["scale"] == 1.2
    assert payload["settings"]["config"]["show_on_all_spaces"] is True


def test_mode_settings_window_does_not_render_common_settings():
    assert "Common" not in _SETTINGS_HTML
    assert "display_mode" not in _SETTINGS_HTML
    assert "bridge_host" not in _SETTINGS_HTML
    assert "function scaleRow" in _SETTINGS_HTML
    assert 'type="range"' in _SETTINGS_HTML
    assert "选择模型目录" in _SETTINGS_HTML
    assert "导入资源包 ZIP" in _SETTINGS_HTML
    assert "打开导入目录" in _SETTINGS_HTML
    assert "当前配置路径" in _SETTINGS_HTML
    assert "当前生效路径" in _SETTINGS_HTML
    assert "默认导入目录" in _SETTINGS_HTML
    assert "资源下载" in _SETTINGS_HTML
    assert "当前头像资源" in _SETTINGS_HTML
    assert "GitHub Releases" not in _SETTINGS_HTML  # URL 运行时填充


def test_load_config_reads_legacy_live2d_block(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    _patch_no_live2d_assets(monkeypatch, tmp_path)
    config_mod._CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_mod._CONFIG_FILE.write_text(
        json.dumps(
            {
                "display_mode": "bubble",
                "bubble_mode": {"summary_count": 1},
                "live2d": {
                    "model_name": "legacy-model",
                    "window_on_top": False,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    config = load_config()

    assert config.display_mode == "bubble"
    assert config.bubble_mode.summary_count == 1
    assert config.live2d_mode.model_name == "legacy-model"
    assert config.live2d_mode.model_path == ""
    assert config.live2d_mode.window_on_top is False


def test_load_config_migrates_legacy_window_display_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    _patch_no_live2d_assets(monkeypatch, tmp_path)
    config_mod._CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_mod._CONFIG_FILE.write_text(
        json.dumps({"display_mode": "window"}, ensure_ascii=False),
        encoding="utf-8",
    )

    config = load_config()

    assert config.display_mode == "bubble"
    assert config.live2d_mode.model_name == ""
    assert config.live2d_mode.model_path == ""


def test_load_config_clears_legacy_bundled_live2d_path(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    _patch_no_live2d_assets(monkeypatch, tmp_path)
    config_mod._CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_mod._CONFIG_FILE.write_text(
        json.dumps(
            {
                "live2d_mode": {
                    "model_name": "八千代辉夜姬",
                    "model_path": str(LEGACY_BUNDLED_LIVE2D_MODEL_DIR),
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    config = load_config()

    assert config.live2d_mode.model_name == ""
    assert config.live2d_mode.model_path == ""


def test_save_config_persists_mode_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    config = AppConfig()
    config.window_mode.recent_messages_limit = 5
    config.bubble_mode.summary_count = 2
    config.live2d_mode.model_name = "hiyori"
    config.live2d_mode.scale = 1.4
    config.live2d_mode.show_on_all_spaces = False

    save_config(config)
    data = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))

    assert data["window_mode"]["recent_messages_limit"] == 5
    assert data["bubble_mode"]["summary_count"] == 2
    assert data["live2d_mode"]["model_name"] == "hiyori"
    assert data["live2d_mode"]["scale"] == 1.4
    assert data["live2d_mode"]["show_on_all_spaces"] is False


def test_mode_settings_api_can_choose_live2d_model_path(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")

    model_dir = _create_live2d_model_dir(tmp_path / "picked" / "yachiyo")
    config = AppConfig(display_mode="live2d")
    api = ModeSettingsAPI(config, "live2d")
    api.bind_window(_DialogWindowStub((str(model_dir),)))

    result = api.choose_live2d_model_path()

    assert result["ok"] is True
    assert config.live2d_mode.model_path == str(model_dir)
    assert result["settings"]["settings"]["config"]["model_path"] == str(model_dir)


def test_import_live2d_archive_extracts_model_dir(tmp_path):
    source_root = tmp_path / "release" / "yachiyo"
    _create_live2d_model_dir(source_root, model_name="yachiyo")
    archive_path = tmp_path / "yachiyo-live2d.zip"

    with zipfile.ZipFile(archive_path, "w") as archive:
        for file in source_root.rglob("*"):
            archive.write(file, file.relative_to(source_root.parent))

    imported_path = _import_live2d_archive(archive_path, assets_root=tmp_path / "imported")

    assert imported_path.exists()
    assert imported_path.name == "yachiyo"
    assert (imported_path / "yachiyo.model3.json").exists()


def test_open_mode_settings_window_reuses_existing_mode_window(monkeypatch):
    webview_stub = _WebviewModuleStub()
    monkeypatch.setitem(sys.modules, "webview", webview_stub)
    monkeypatch.setattr(settings_mod, "_settings_windows", {})
    monkeypatch.setattr(settings_mod, "_settings_windows_creating", set())

    config = AppConfig(display_mode="live2d")

    assert open_mode_settings_window(config, "live2d") is True
    assert open_mode_settings_window(config, "live2d") is True
    assert webview_stub.create_calls == 1
    assert webview_stub.last_window is not None
    assert webview_stub.last_window.show_calls == 1


def test_open_mode_settings_window_recreates_after_close(monkeypatch):
    webview_stub = _WebviewModuleStub()
    monkeypatch.setitem(sys.modules, "webview", webview_stub)
    monkeypatch.setattr(settings_mod, "_settings_windows", {})
    monkeypatch.setattr(settings_mod, "_settings_windows_creating", set())

    config = AppConfig(display_mode="live2d")

    assert open_mode_settings_window(config, "live2d") is True
    assert webview_stub.last_window is not None
    assert webview_stub.last_window.events.closed.handler is not None
    webview_stub.last_window.events.closed.handler()

    assert open_mode_settings_window(config, "live2d") is True
    assert webview_stub.create_calls == 2


def test_open_mode_settings_window_does_not_reenter_while_creating(monkeypatch):
    webview_stub = _WebviewModuleStub()
    monkeypatch.setitem(sys.modules, "webview", webview_stub)
    monkeypatch.setattr(settings_mod, "_settings_windows", {})
    monkeypatch.setattr(settings_mod, "_settings_windows_creating", set())

    config = AppConfig(display_mode="live2d")
    reentered = False

    def _reenter() -> None:
        nonlocal reentered
        if reentered:
            return
        reentered = True
        assert open_mode_settings_window(config, "live2d") is True

    webview_stub.on_create = _reenter

    assert open_mode_settings_window(config, "live2d") is True
    assert reentered is True
    assert webview_stub.create_calls == 1


def test_open_mode_settings_window_ignores_stale_closed_window(monkeypatch):
    webview_stub = _WebviewModuleStub()
    monkeypatch.setitem(sys.modules, "webview", webview_stub)
    monkeypatch.setattr(settings_mod, "_settings_windows", {})
    monkeypatch.setattr(settings_mod, "_settings_windows_creating", set())

    config = AppConfig(display_mode="live2d")

    assert open_mode_settings_window(config, "live2d") is True
    assert webview_stub.last_window is not None
    webview_stub.last_window.closed = True

    assert open_mode_settings_window(config, "live2d") is True
    assert webview_stub.create_calls == 2
