"""Bridge Server 测试。"""

import json

import pytest

from apps.bridge.routes import live2d as live2d_route
from apps.bridge.server import app, get_live2d_asset_token, regenerate_live2d_asset_token


def test_bridge_app_enables_local_webview_cors():
    middleware = getattr(app, "user_middleware", [])
    cors_entry = next(
        (item for item in middleware if getattr(getattr(item, "cls", None), "__name__", "") == "CORSMiddleware"),
        None,
    )

    assert cors_entry is not None
    assert cors_entry.options["allow_origins"] == []
    assert cors_entry.options["allow_origin_regex"] == r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$"
    assert cors_entry.options["allow_methods"] == ["*"]
    assert cors_entry.options["allow_headers"] == ["*"]


def test_live2d_asset_token_can_rotate():
    first = get_live2d_asset_token()
    second = regenerate_live2d_asset_token()

    assert second
    assert second != first


def test_rewrite_live2d_manifest_paths_appends_token():
    manifest = {
        "Version": 3,
        "FileReferences": {
            "Moc": "model.moc3",
            "Textures": ["textures/tex_00.png"],
            "Physics": "physics.json",
            "Motions": {
                "Idle": [{"File": "motions/idle.motion3.json", "Sound": "sounds/idle.wav"}],
            },
        },
    }

    rewritten = live2d_route._rewrite_live2d_manifest_paths(manifest, "token-123")
    refs = rewritten["FileReferences"]

    assert refs["Moc"].endswith("model.moc3?token=token-123")
    assert refs["Textures"][0].endswith("textures/tex_00.png?token=token-123")
    assert refs["Physics"].endswith("physics.json?token=token-123")
    assert refs["Motions"]["Idle"][0]["File"].endswith("motions/idle.motion3.json?token=token-123")
    assert refs["Motions"]["Idle"][0]["Sound"].endswith("sounds/idle.wav?token=token-123")


def test_resolve_live2d_asset_rejects_path_escape(tmp_path, monkeypatch):
    model_root = tmp_path / "models"
    model_root.mkdir()
    (model_root / "ok.txt").write_text("ok", encoding="utf-8")

    monkeypatch.setattr(live2d_route, "_get_live2d_model_root", lambda: model_root)

    with pytest.raises(live2d_route.HTTPException) as exc_info:
        live2d_route._resolve_live2d_asset("../secret.txt")

    assert exc_info.value.status_code == 403


def test_render_live2d_manifest_keeps_json_structure(tmp_path):
    manifest_path = tmp_path / "model.model3.json"
    manifest_path.write_text(
        '{"FileReferences":{"Moc":"model.moc3","Textures":["tex.png"]}}',
        encoding="utf-8",
    )

    payload = live2d_route._render_live2d_manifest(manifest_path, "token-xyz")
    decoded = json.loads(payload.decode("utf-8"))

    assert decoded["FileReferences"]["Moc"].endswith("model.moc3?token=token-xyz")
    assert decoded["FileReferences"]["Textures"][0].endswith("tex.png?token=token-xyz")
