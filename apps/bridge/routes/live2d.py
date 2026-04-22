"""GET /live2d/assets/{asset_path:path} — 受控提供当前 Live2D 模型资源。"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from apps.bridge.deps import get_runtime

router = APIRouter(tags=["Live2D"])


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


@router.get("/live2d/assets/{asset_path:path}")
async def get_live2d_asset(asset_path: str) -> FileResponse:
    asset = _resolve_live2d_asset(asset_path)
    media_type = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
    return FileResponse(asset, media_type=media_type)