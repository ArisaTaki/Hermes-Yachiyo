"""桌面原生窗口行为辅助。

pywebview 提供跨平台窗口外壳；少数 macOS 行为（例如跨 Spaces 浮动）
需要走 NSWindow best-effort 调整。该模块保持可选依赖：没有 PyObjC 时直接跳过。
"""

from __future__ import annotations

import logging
import platform
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

PointerHitTest = Callable[[float, float, float, float], bool]

_pointer_passthrough_lock = threading.RLock()
_pointer_passthrough_stops: dict[str, threading.Event] = {}


def schedule_macos_window_behavior(
    *,
    title: str,
    always_on_top: bool,
    show_on_all_spaces: bool,
    delay_seconds: float = 0.4,
) -> bool:
    """延迟应用 macOS NSWindow 行为。

    pywebview 的原生 NSWindow 需要等事件循环启动后才可被 AppKit 枚举到，
    因此使用一个很短的 daemon timer 做 best-effort 应用。
    """
    if platform.system() != "Darwin":
        return False

    timer = threading.Timer(
        delay_seconds,
        apply_macos_window_behavior,
        kwargs={
            "title": title,
            "always_on_top": always_on_top,
            "show_on_all_spaces": show_on_all_spaces,
        },
    )
    timer.daemon = True
    timer.start()
    return True


def apply_macos_window_behavior(
    *,
    title: str,
    always_on_top: bool,
    show_on_all_spaces: bool,
) -> bool:
    """按标题查找 NSWindow 并应用置顶 / Spaces 行为。"""
    if platform.system() != "Darwin":
        return False

    try:
        from AppKit import (  # type: ignore[import-untyped]
            NSApp,
            NSFloatingWindowLevel,
            NSNormalWindowLevel,
            NSColor,
        )
    except Exception as exc:
        logger.debug("PyObjC/AppKit 不可用，跳过 macOS 窗口层级设置: %s", exc)
        return False

    try:
        windows = list(NSApp.windows() or [])
    except Exception as exc:
        logger.debug("无法枚举 NSApp.windows(): %s", exc)
        return False

    target = None
    for ns_window in windows:
        try:
            if str(ns_window.title()) == title:
                target = ns_window
                break
        except Exception:
            continue

    if target is None:
        logger.debug("未找到标题为 %r 的 NSWindow，跳过原生窗口设置", title)
        return False

    try:
        level = NSFloatingWindowLevel if always_on_top else NSNormalWindowLevel
        target.setLevel_(level)
        target.setHidesOnDeactivate_(False)
        target.setOpaque_(False)
        target.setBackgroundColor_(NSColor.clearColor())

        behavior = int(target.collectionBehavior())
        can_join_spaces = _collection_behavior_constant(
            "NSWindowCollectionBehaviorCanJoinAllSpaces",
            fallback=1 << 0,
        )
        fullscreen_aux = _collection_behavior_constant(
            "NSWindowCollectionBehaviorFullScreenAuxiliary",
            fallback=1 << 8,
        )

        if show_on_all_spaces:
            behavior |= can_join_spaces | fullscreen_aux
        else:
            behavior &= ~can_join_spaces
            behavior &= ~fullscreen_aux

        target.setCollectionBehavior_(behavior)
        logger.info(
            "已应用 macOS 窗口行为: title=%s always_on_top=%s show_on_all_spaces=%s",
            title,
            always_on_top,
            show_on_all_spaces,
        )
        return True
    except Exception as exc:
        logger.debug("应用 macOS 窗口行为失败: %s", exc)
        return False


def focus_macos_window(*, title: str) -> bool:
    """按标题聚焦 macOS NSWindow，用于右键菜单立即接收键鼠焦点。"""
    if platform.system() != "Darwin":
        return False

    try:
        from AppKit import NSApp  # type: ignore[import-untyped]
    except Exception as exc:
        logger.debug("PyObjC/AppKit 不可用，跳过 macOS 窗口聚焦: %s", exc)
        return False

    try:
        windows = list(NSApp.windows() or [])
    except Exception as exc:
        logger.debug("无法枚举 NSApp.windows(): %s", exc)
        return False

    for ns_window in windows:
        try:
            if str(ns_window.title()) != title:
                continue
            ns_window.makeKeyAndOrderFront_(None)
            NSApp.activateIgnoringOtherApps_(True)
            logger.debug("已聚焦 macOS 窗口: title=%s", title)
            return True
        except Exception as exc:
            logger.debug("聚焦 macOS 窗口失败: %s", exc)
            return False
    return False


def bubble_visual_hit_test(width: float, height: float, x: float, y: float) -> bool:
    """Return whether a point is inside the visible circular Bubble launcher."""
    if width <= 0 or height <= 0:
        return False
    diameter = min(width * 0.84, height * 0.84, 108.0)
    radius = (diameter / 2.0) + 3.0
    center_x = width / 2.0
    center_y = height / 2.0
    return ((x - center_x) ** 2 + (y - center_y) ** 2) <= radius ** 2


def live2d_visual_hit_test(
    width: float,
    height: float,
    x: float,
    y: float,
    region: dict[str, object] | None = None,
) -> bool:
    """Return whether a point is in the Live2D model's visual hit area.

    Coordinates are in window-local points from the top-left corner. The
    frontend-reported model bounds are treated as an outer frame for a tighter
    character silhouette, so blank transparent space inside the pywebview
    rectangle remains click-through.
    """
    if width <= 0 or height <= 0:
        return False
    if region is not None:
        region_hit = _region_hit_test(width, height, x, y, region)
        if region_hit is True:
            return True

    return _default_live2d_hit_test(width, height, x, y)


def schedule_macos_pointer_passthrough(
    *,
    title: str,
    hit_test: PointerHitTest,
    delay_seconds: float = 0.45,
    interval_seconds: float = 0.05,
    focus_on_hover: bool = False,
) -> bool:
    """Dynamically ignore mouse events outside a transparent window's visual shape.

    pywebview transparent windows are still rectangular at the native window
    level. On macOS we can poll the global cursor and toggle
    ``NSWindow.ignoresMouseEvents`` so clicks in transparent corners pass
    through to windows below, while visible Bubble/Live2D pixels remain
    interactive.
    """
    if platform.system() != "Darwin":
        return False

    stop = threading.Event()
    with _pointer_passthrough_lock:
        previous = _pointer_passthrough_stops.pop(title, None)
        if previous is not None:
            previous.set()
        _pointer_passthrough_stops[title] = stop

    thread = threading.Thread(
        target=_poll_macos_pointer_passthrough,
        kwargs={
            "title": title,
            "hit_test": hit_test,
            "stop": stop,
            "delay_seconds": delay_seconds,
            "interval_seconds": interval_seconds,
            "focus_on_hover": focus_on_hover,
        },
        name=f"hermes-pointer-passthrough:{title}",
        daemon=True,
    )
    thread.start()
    return True


def _poll_macos_pointer_passthrough(
    *,
    title: str,
    hit_test: PointerHitTest,
    stop: threading.Event,
    delay_seconds: float,
    interval_seconds: float,
    focus_on_hover: bool,
) -> None:
    time.sleep(max(0.0, delay_seconds))
    if stop.is_set():
        _discard_pointer_passthrough_stop(title, stop)
        return
    try:
        from AppKit import NSApp, NSEvent  # type: ignore[import-untyped]
    except Exception as exc:
        logger.debug("PyObjC/AppKit 不可用，跳过 macOS 鼠标穿透设置: %s", exc)
        _discard_pointer_passthrough_stop(title, stop)
        return

    target = None
    target_seen = False
    missing_after_seen = 0
    last_ignoring: bool | None = None
    last_interactive: bool | None = None

    try:
        while not stop.is_set():
            target = _find_macos_window(title=title)
            if target is None:
                if target_seen:
                    missing_after_seen += 1
                    if missing_after_seen >= 20:
                        break
                time.sleep(max(0.02, interval_seconds))
                continue

            target_seen = True
            missing_after_seen = 0
            frame = target.frame()
            width = float(frame.size.width)
            height = float(frame.size.height)
            mouse = NSEvent.mouseLocation()
            local_x = float(mouse.x - frame.origin.x)
            local_y_from_bottom = float(mouse.y - frame.origin.y)
            inside = 0 <= local_x <= width and 0 <= local_y_from_bottom <= height
            local_y = height - local_y_from_bottom

            interactive = False
            if inside:
                try:
                    interactive = bool(hit_test(width, height, local_x, local_y))
                except Exception as exc:
                    logger.debug("窗口命中测试失败: title=%s error=%s", title, exc)
                    interactive = True

            should_ignore = not interactive
            if should_ignore != last_ignoring:
                target.setIgnoresMouseEvents_(should_ignore)
                last_ignoring = should_ignore

            if focus_on_hover and interactive and last_interactive is not True:
                try:
                    target.setIgnoresMouseEvents_(False)
                    last_ignoring = False
                    target.makeKeyAndOrderFront_(None)
                    NSApp.activateIgnoringOtherApps_(True)
                except Exception as exc:
                    logger.debug("hover 聚焦 macOS 窗口失败: title=%s error=%s", title, exc)
            last_interactive = interactive

            time.sleep(max(0.02, interval_seconds))
    except Exception as exc:
        logger.debug("macOS 鼠标穿透轮询失败: title=%s error=%s", title, exc)
    finally:
        _discard_pointer_passthrough_stop(title, stop)
        try:
            if target is not None:
                target.setIgnoresMouseEvents_(False)
        except Exception:
            pass


def _discard_pointer_passthrough_stop(title: str, stop: threading.Event) -> None:
    with _pointer_passthrough_lock:
        if _pointer_passthrough_stops.get(title) is stop:
            _pointer_passthrough_stops.pop(title, None)


def _find_macos_window(*, title: str):
    try:
        from AppKit import NSApp  # type: ignore[import-untyped]

        windows = list(NSApp.windows() or [])
    except Exception:
        return None

    for ns_window in windows:
        try:
            if str(ns_window.title()) == title:
                return ns_window
        except Exception:
            continue
    return None


def _region_hit_test(
    width: float,
    height: float,
    x: float,
    y: float,
    region: dict[str, object] | None,
) -> bool | None:
    if not region:
        return None

    try:
        kind = str(region.get("kind") or "ellipse")
        left = float(region.get("x", 0.0)) * width
        top = float(region.get("y", 0.0)) * height
        region_width = float(region.get("width", 0.0)) * width
        region_height = float(region.get("height", 0.0)) * height
    except (TypeError, ValueError):
        return None

    if region_width <= 0 or region_height <= 0:
        return None

    if kind in {"live2d", "model"}:
        if region_width > width * 0.86 or (region_height > height * 0.90 and top < height * 0.08):
            return None
        return _live2d_region_hit_test(left, top, region_width, region_height, x, y)

    padding = max(4.0, min(width, height) * 0.015)
    left -= padding
    top -= padding
    region_width += padding * 2.0
    region_height += padding * 2.0

    if kind == "rect":
        return left <= x <= left + region_width and top <= y <= top + region_height

    center_x = left + region_width / 2.0
    center_y = top + region_height / 2.0
    radius_x = region_width / 2.0
    radius_y = region_height / 2.0
    if radius_x <= 0 or radius_y <= 0:
        return None
    return ((x - center_x) / radius_x) ** 2 + ((y - center_y) / radius_y) ** 2 <= 1.0


def _default_live2d_hit_test(width: float, height: float, x: float, y: float) -> bool:
    region_height = height * 0.72
    region_width = min(width * 0.48, region_height * 0.58)
    left = (width - region_width) / 2.0
    top = min(height * 0.28, height * 0.98 - region_height)
    return bool(_live2d_region_hit_test(left, top, region_width, region_height, x, y))


def _live2d_region_hit_test(
    left: float,
    top: float,
    region_width: float,
    region_height: float,
    x: float,
    y: float,
) -> bool | None:
    if region_width <= 0 or region_height <= 0:
        return None

    u = (x - left) / region_width
    v = (y - top) / region_height
    if u < -0.03 or u > 1.03 or v < -0.03 or v > 1.03:
        return False

    return (
        _ellipse_unit_hit(u, v, 0.34, 0.08, 0.12, 0.09)
        or _ellipse_unit_hit(u, v, 0.66, 0.08, 0.12, 0.09)
        or _ellipse_unit_hit(u, v, 0.50, 0.17, 0.25, 0.17)
        or _ellipse_unit_hit(u, v, 0.50, 0.30, 0.34, 0.18)
        or _ellipse_unit_hit(u, v, 0.50, 0.48, 0.28, 0.22)
        or _ellipse_unit_hit(u, v, 0.28, 0.54, 0.14, 0.19)
        or _ellipse_unit_hit(u, v, 0.72, 0.54, 0.14, 0.19)
        or _ellipse_unit_hit(u, v, 0.50, 0.66, 0.42, 0.20)
        or _capsule_unit_hit(u, v, 0.43, 0.70, 0.96, 0.055)
        or _capsule_unit_hit(u, v, 0.57, 0.70, 0.96, 0.055)
        or _ellipse_unit_hit(u, v, 0.50, 0.92, 0.23, 0.08)
    )


def _ellipse_unit_hit(
    x: float,
    y: float,
    center_x: float,
    center_y: float,
    radius_x: float,
    radius_y: float,
) -> bool:
    if radius_x <= 0 or radius_y <= 0:
        return False
    return ((x - center_x) / radius_x) ** 2 + ((y - center_y) / radius_y) ** 2 <= 1.0


def _capsule_unit_hit(
    x: float,
    y: float,
    center_x: float,
    top: float,
    bottom: float,
    radius: float,
) -> bool:
    return _vertical_capsule_hit_test(center_x, top, bottom, radius, x, y)


def _vertical_capsule_hit_test(
    center_x: float,
    top: float,
    bottom: float,
    radius: float,
    x: float,
    y: float,
) -> bool:
    if radius <= 0 or bottom <= top:
        return False
    inner_top = top + radius
    inner_bottom = bottom - radius
    if inner_top <= y <= inner_bottom:
        return abs(x - center_x) <= radius

    cap_y = inner_top if y < inner_top else inner_bottom
    return (x - center_x) ** 2 + (y - cap_y) ** 2 <= radius ** 2


def _collection_behavior_constant(name: str, *, fallback: int) -> int:
    try:
        import AppKit  # type: ignore[import-untyped]

        return int(getattr(AppKit, name))
    except Exception:
        return fallback
