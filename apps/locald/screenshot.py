"""截图适配器

macOS 使用 screencapture，后续可扩展跨平台支持。
"""

from __future__ import annotations

import base64
import logging
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from packages.protocol.schemas import ScreenshotResponse

logger = logging.getLogger(__name__)


async def capture_screenshot() -> ScreenshotResponse:
    """捕获当前屏幕截图"""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        # macOS screencapture
        subprocess.run(
            ["screencapture", "-x", str(tmp_path)],
            check=True,
            capture_output=True,
            timeout=10,
        )
        image_data = tmp_path.read_bytes()
        image_b64 = base64.b64encode(image_data).decode("ascii")

        # 使用 Pillow 获取尺寸（可选依赖）
        try:
            from PIL import Image

            with Image.open(tmp_path) as img:
                width, height = img.size
        except ImportError:
            width, height = 0, 0

        return ScreenshotResponse(
            image_base64=image_b64,
            format="png",
            width=width,
            height=height,
            captured_at=datetime.now(timezone.utc),
        )
    finally:
        tmp_path.unlink(missing_ok=True)
