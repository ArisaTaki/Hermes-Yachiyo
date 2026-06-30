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
import zlib
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
                "请在系统设置的“隐私与安全性 / 屏幕与系统音频录制”中允许启动 Oha-Yachiyo 的 Electron、Python 或终端进程，"
                "然后重启 Oha-Yachiyo 或 Bridge。"
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
        **_image_visibility_metadata(target),
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


def _image_visibility_metadata(path: Path) -> dict[str, object]:
    png_metadata = _png_visibility_metadata(path)
    if png_metadata:
        return png_metadata
    try:
        from PIL import Image

        with Image.open(path) as image:
            sample = image.convert("RGB")
            sample.thumbnail((64, 64))
            pixels = list(sample.getdata())
    except Exception:
        return {}
    if not pixels:
        return {}
    luminances = [
        (0.2126 * red) + (0.7152 * green) + (0.0722 * blue)
        for red, green, blue in pixels
    ]
    mean_luminance = sum(luminances) / len(luminances)
    non_black_pixels = sum(1 for red, green, blue in pixels if max(red, green, blue) > 8)
    non_black_ratio = non_black_pixels / len(pixels)
    max_channel = max(max(red, green, blue) for red, green, blue in pixels)
    return _visibility_stats(
        mean_luminance=mean_luminance,
        non_black_ratio=non_black_ratio,
        max_channel=max_channel,
    )


def _png_visibility_metadata(path: Path) -> dict[str, object]:
    try:
        data = Path(path).read_bytes()
    except OSError:
        return {}
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return {}
    width = 0
    height = 0
    bit_depth = 0
    color_type = -1
    idat_parts: list[bytes] = []
    position = 8
    while position + 8 <= len(data):
        length = int.from_bytes(data[position : position + 4], "big")
        chunk_type = data[position + 4 : position + 8]
        chunk = data[position + 8 : position + 8 + length]
        position += 12 + length
        if chunk_type == b"IHDR" and len(chunk) >= 13:
            width = int.from_bytes(chunk[0:4], "big")
            height = int.from_bytes(chunk[4:8], "big")
            bit_depth = int(chunk[8])
            color_type = int(chunk[9])
        elif chunk_type == b"IDAT":
            idat_parts.append(chunk)
        elif chunk_type == b"IEND":
            break
    if width <= 0 or height <= 0 or bit_depth != 8 or color_type not in {0, 2, 4, 6}:
        return {}
    channels_by_type = {0: 1, 2: 3, 4: 2, 6: 4}
    channels = channels_by_type[color_type]
    stride = width * channels
    try:
        raw = zlib.decompress(b"".join(idat_parts))
    except Exception:
        return {}
    expected_min = height * (stride + 1)
    if len(raw) < expected_min:
        return {}
    previous = bytearray(stride)
    offset = 0
    sample_x_step = max(1, width // 128)
    sample_y_step = max(1, height // 128)
    total_samples = 0
    luminance_sum = 0.0
    non_black_pixels = 0
    max_channel = 0
    for y in range(height):
        filter_type = raw[offset]
        offset += 1
        scanline = bytearray(raw[offset : offset + stride])
        offset += stride
        _png_unfilter_scanline(scanline, previous, channels, filter_type)
        if y % sample_y_step == 0:
            for x in range(0, width, sample_x_step):
                index = x * channels
                red, green, blue = _png_rgb_at(scanline, index, color_type)
                luminance_sum += (0.2126 * red) + (0.7152 * green) + (0.0722 * blue)
                pixel_max = max(red, green, blue)
                max_channel = max(max_channel, pixel_max)
                if pixel_max > 8:
                    non_black_pixels += 1
                total_samples += 1
        previous = scanline
    if total_samples <= 0:
        return {}
    return _visibility_stats(
        mean_luminance=luminance_sum / total_samples,
        non_black_ratio=non_black_pixels / total_samples,
        max_channel=max_channel,
    )


def _png_unfilter_scanline(
    scanline: bytearray,
    previous: bytearray,
    bytes_per_pixel: int,
    filter_type: int,
) -> None:
    if filter_type == 0:
        return
    for index, value in enumerate(scanline):
        left = scanline[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
        up = previous[index] if index < len(previous) else 0
        up_left = (
            previous[index - bytes_per_pixel]
            if index >= bytes_per_pixel and index - bytes_per_pixel < len(previous)
            else 0
        )
        if filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = up
        elif filter_type == 3:
            predictor = (left + up) // 2
        elif filter_type == 4:
            predictor = _paeth_predictor(left, up, up_left)
        else:
            return
        scanline[index] = (value + predictor) & 0xFF


def _png_rgb_at(scanline: bytearray, index: int, color_type: int) -> tuple[int, int, int]:
    if color_type == 0:
        value = scanline[index]
        return value, value, value
    if color_type == 4:
        value = scanline[index]
        return value, value, value
    return scanline[index], scanline[index + 1], scanline[index + 2]


def _paeth_predictor(left: int, up: int, up_left: int) -> int:
    estimate = left + up - up_left
    distance_left = abs(estimate - left)
    distance_up = abs(estimate - up)
    distance_up_left = abs(estimate - up_left)
    if distance_left <= distance_up and distance_left <= distance_up_left:
        return left
    if distance_up <= distance_up_left:
        return up
    return up_left


def _visibility_stats(
    *,
    mean_luminance: float,
    non_black_ratio: float,
    max_channel: int,
) -> dict[str, object]:
    blank_frame = mean_luminance <= 2.0 and max_channel <= 8 and non_black_ratio <= 0.001
    low_light_frame = (
        not blank_frame
        and mean_luminance <= 6.0
        and max_channel <= 24
        and non_black_ratio <= 0.02
    )
    return {
        "visibility_status": (
            "blank_black"
            if blank_frame
            else "low_light"
            if low_light_frame
            else "visible"
        ),
        "blank_frame": blank_frame,
        "low_light_frame": low_light_frame,
        "mean_luminance": round(mean_luminance, 2),
        "non_black_pixel_ratio": round(non_black_ratio, 4),
        "max_channel": int(max_channel),
    }


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
