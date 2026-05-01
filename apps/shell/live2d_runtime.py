"""Live2D web runtime dependency cache for the Electron launcher."""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.request import Request, urlopen

from apps.shell.assets import get_yachiyo_workspace_dir

logger = logging.getLogger(__name__)

_PIXI_JS_CDN = "https://cdn.jsdelivr.net/npm/pixi.js@6/dist/browser/pixi.min.js"
_LIVE2D_CUBISM_CORE_CDN = "https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js"
_PIXI_LIVE2D_DISPLAY_CDN = (
    "https://cdn.jsdelivr.net/npm/pixi-live2d-display@0.5.0-beta/dist/cubism4.min.js"
)
_LIVE2D_RUNTIME_DEPENDENCY_STATE: dict[str, object] = {
    "primed": False,
    "ready": False,
    "error": "",
}


def get_live2d_runtime_dependency_specs() -> dict[str, tuple[str, Path]]:
    cache_dir = get_yachiyo_workspace_dir() / "cache" / "live2d-web"
    return {
        "pixi_js": (_PIXI_JS_CDN, cache_dir / "pixi.min.js"),
        "live2d_cubism_core": (
            _LIVE2D_CUBISM_CORE_CDN,
            cache_dir / "live2dcubismcore.min.js",
        ),
        "pixi_live2d_display": (
            _PIXI_LIVE2D_DISPLAY_CDN,
            cache_dir / "pixi-live2d-display-cubism4.min.js",
        ),
    }


def runtime_dependency_files_ready() -> bool:
    specs = get_live2d_runtime_dependency_specs()
    return all(path.exists() and path.is_file() and path.stat().st_size > 0 for _, path in specs.values())


def _download_live2d_runtime_dependency(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "Hermes-Yachiyo/0.1"})
    with urlopen(request, timeout=20) as response:
        payload = response.read()
    if not payload:
        raise RuntimeError(f"下载 {target.name} 时收到空响应")

    temp_path = target.with_name(f".{target.name}.tmp")
    temp_path.write_bytes(payload)
    temp_path.replace(target)


def prime_live2d_runtime_dependencies(force: bool = False) -> tuple[bool, str]:
    if not force and _LIVE2D_RUNTIME_DEPENDENCY_STATE.get("primed"):
        return bool(_LIVE2D_RUNTIME_DEPENDENCY_STATE.get("ready")), str(
            _LIVE2D_RUNTIME_DEPENDENCY_STATE.get("error") or ""
        )

    specs = get_live2d_runtime_dependency_specs()
    error = ""
    ready = True
    try:
        for url, path in specs.values():
            if not force and path.exists() and path.stat().st_size > 0:
                continue
            _download_live2d_runtime_dependency(url, path)
        ready = runtime_dependency_files_ready()
    except Exception as exc:
        ready = False
        error = f"{exc}"
        logger.warning("准备 Live2D 渲染依赖失败: %s", exc)

    _LIVE2D_RUNTIME_DEPENDENCY_STATE["primed"] = True
    _LIVE2D_RUNTIME_DEPENDENCY_STATE["ready"] = ready
    _LIVE2D_RUNTIME_DEPENDENCY_STATE["error"] = error
    return ready, error
