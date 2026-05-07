"""截图适配器

macOS 使用 screencapture，后续可扩展跨平台支持。
"""

from __future__ import annotations

import base64
import logging
import os
import platform
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from packages.protocol.schemas import ScreenshotResponse

logger = logging.getLogger(__name__)


class ScreenCapturePermissionError(RuntimeError):
    """Raised when macOS denies screen recording to the current backend process."""


def check_screen_capture_permission(*, open_settings: bool = False) -> dict[str, object]:
    """Try a real screenshot capture and optionally open macOS Screen Recording settings."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        capture_screenshot_to_file(tmp_path)
        return {"ok": True, "allowed": True, "message": "屏幕录制权限可用"}
    except ScreenCapturePermissionError as exc:
        if open_settings:
            open_screen_recording_settings()
        return {
            "ok": False,
            "allowed": False,
            "permission_denied": True,
            "settings_opened": bool(open_settings and platform.system() == "Darwin"),
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "ok": False,
            "allowed": False,
            "permission_denied": False,
            "settings_opened": False,
            "error": str(exc),
        }
    finally:
        tmp_path.unlink(missing_ok=True)


def open_screen_recording_settings() -> bool:
    """Open the macOS privacy pane for Screen Recording when available."""
    if platform.system() != "Darwin":
        return False
    urls = (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
        "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenRecording",
    )
    opened = False
    for url in urls:
        try:
            subprocess.run(["open", url], timeout=5, check=False)
            opened = True
            break
        except Exception:
            logger.debug("打开屏幕录制权限设置失败: %s", url, exc_info=True)
    return opened


def capture_screenshot_to_file(target_path: Path) -> dict[str, object]:
    """Capture the current screen to ``target_path`` and return attachment metadata."""
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["screencapture", "-x", str(target)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    output = "\n".join(
        part.strip()
        for part in (result.stderr, result.stdout)
        if isinstance(part, str) and part.strip()
    )
    if result.returncode != 0:
        detail = f"：{output}" if output else ""
        if _looks_like_screen_permission_error(output):
            raise ScreenCapturePermissionError(
                "当前后端进程没有 macOS 屏幕录制权限，无法读取桌面截图。"
                "请在系统设置的“隐私与安全性 / 屏幕与系统音频录制”中允许启动 Hermes-Yachiyo 的 Electron、Python 或终端进程，"
                "然后重启 Hermes-Yachiyo 或 Bridge。"
                f"{_screen_permission_process_hint()}"
                f"原始信息{detail}"
            )
        raise RuntimeError(f"screencapture 退出码 {result.returncode}{detail}")
    size = target.stat().st_size if target.exists() else 0
    if size <= 0:
        detail = f"：{output}" if output else ""
        raise RuntimeError(f"screencapture 未生成有效图片{detail}")
    width, height = _image_size(target)
    if width <= 0 or height <= 0:
        raise RuntimeError("screencapture 生成的文件不是有效图片")
    return {
        "path": str(target),
        "mime_type": "image/png",
        "format": "png",
        "width": width,
        "height": height,
        "size": size,
    }


async def capture_screenshot() -> ScreenshotResponse:
    """捕获当前屏幕截图"""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        capture_screenshot_to_file(tmp_path)
        image_data = tmp_path.read_bytes()
        image_b64 = base64.b64encode(image_data).decode("ascii")

        width, height = _image_size(tmp_path)

        return ScreenshotResponse(
            image_base64=image_b64,
            format="png",
            width=width,
            height=height,
            captured_at=datetime.now(timezone.utc),
        )
    finally:
        tmp_path.unlink(missing_ok=True)


def _image_size(path: Path) -> tuple[int, int]:
    png_size = _png_image_size(path)
    if png_size != (0, 0):
        return png_size
    try:
        from PIL import Image

        with Image.open(path) as img:
            return img.size
    except Exception:
        return 0, 0


def _png_image_size(path: Path) -> tuple[int, int]:
    try:
        with Path(path).open("rb") as file:
            header = file.read(24)
    except OSError:
        return 0, 0
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return 0, 0
    width = int.from_bytes(header[16:20], "big")
    height = int.from_bytes(header[20:24], "big")
    return (width, height) if width > 0 and height > 0 else (0, 0)


def _looks_like_screen_permission_error(output: str) -> bool:
    normalized = str(output or "").lower()
    return any(
        marker in normalized
        for marker in (
            "could not create image from display",
            "not authorized",
            "screen recording",
            "recording permission",
            "tcc",
        )
    )


def _screen_permission_process_hint() -> str:
    parts = [f"当前 Python: {sys.executable}", f"pid={os.getpid()}"]
    parent_pid = os.getppid()
    if parent_pid:
        parent_command = _process_command(parent_pid)
        parts.append(f"父进程 pid={parent_pid}{f' ({parent_command})' if parent_command else ''}")
    electron_app = Path("apps/frontend/node_modules/electron/dist/Electron.app").resolve()
    if electron_app.exists():
        parts.append(f"开发模式通常需要允许 Electron: {electron_app}")
    return "权限目标提示：" + "；".join(parts) + "。"


def _process_command(pid: int) -> str:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return " ".join((result.stdout or "").split())
