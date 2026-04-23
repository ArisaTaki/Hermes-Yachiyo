"""GET /live2d/assets/{asset_path:path} — 受控提供当前 Live2D 模型资源。"""

from __future__ import annotations

import hmac
import json
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from apps.bridge.deps import get_runtime
from apps.bridge.server import get_live2d_asset_token

router = APIRouter(tags=["Live2D"])

_LIVE2D_MANIFEST_SUFFIXES = (".model3.json", ".model.json")
_LIVE2D_PATH_KEYS = {"Moc", "Physics", "Pose", "UserData", "DisplayInfo", "File", "Sound"}
_LIVE2D_PATH_LIST_KEYS = {"Textures"}


def _get_live2d_model_root() -> Path:
    resolved = get_runtime().config.live2d_mode.resolve_model_path()
    if resolved is None:
        raise HTTPException(status_code=404, detail="Live2D 模型目录不存在")
    root = resolved.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=404, detail="Live2D 模型目录不存在")
    return root


def _resolve_live2d_asset(asset_path: str) -> Path:
    root = _get_live2d_model_root()
    resolved = (root / asset_path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="禁止访问模型目录外文件") from exc
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"Live2D 资源不存在: {asset_path}")
    return resolved


def _validate_live2d_asset_token(token: str) -> None:
    if not token or not hmac.compare_digest(str(token), get_live2d_asset_token()):
        raise HTTPException(status_code=403, detail="Live2D 资源访问令牌无效")


def _live2d_asset_response_headers(request: Request) -> dict[str, str]:
    origin = (request.headers.get("origin") or "").strip().lower()
    if origin != "null":
        return {}
    return {
        "Access-Control-Allow-Origin": "null",
        "Vary": "Origin",
    }


def _tokenize_live2d_asset_path(path_value: str, token: str) -> str:
    text = str(path_value or "").strip()
    if not text:
        return text
    parts = urlsplit(text)
    if parts.scheme or parts.netloc or text.startswith("data:") or text.startswith("blob:"):
        return text

    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["token"] = token
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query, doseq=True),
            parts.fragment,
        )
    )


def _rewrite_live2d_manifest_paths(value: Any, token: str, *, key: str = "") -> Any:
    if isinstance(value, dict):
        return {
            item_key: _rewrite_live2d_manifest_paths(item_value, token, key=item_key)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        if key in _LIVE2D_PATH_LIST_KEYS:
            return [
                _tokenize_live2d_asset_path(item, token) if isinstance(item, str) else item
                for item in value
            ]
        return [_rewrite_live2d_manifest_paths(item, token, key=key) for item in value]
    if isinstance(value, str) and key in _LIVE2D_PATH_KEYS:
        return _tokenize_live2d_asset_path(value, token)
    return value


def _render_live2d_manifest(asset: Path, token: str) -> bytes:
    payload = json.loads(asset.read_text(encoding="utf-8"))
    rewritten = _rewrite_live2d_manifest_paths(payload, token)
    return json.dumps(rewritten, ensure_ascii=False).encode("utf-8")


@router.get("/live2d/assets/{asset_path:path}")
async def get_live2d_asset(asset_path: str, request: Request, token: str = "") -> Response:
    _validate_live2d_asset_token(token)
    asset = _resolve_live2d_asset(asset_path)
    headers = _live2d_asset_response_headers(request)

    if asset.name.endswith(_LIVE2D_MANIFEST_SUFFIXES):
        return Response(
            content=_render_live2d_manifest(asset, token),
            media_type="application/json",
            headers=headers,
        )

    media_type = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
    return FileResponse(asset, media_type=media_type, headers=headers)
