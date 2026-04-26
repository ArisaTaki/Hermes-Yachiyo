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
from typing import Any

logger = logging.getLogger(__name__)

PointerHitTest = Callable[[float, float, float, float], bool]
PointerObserver = Callable[[float, float, float, float, bool], None]

_MAIN_QUEUE_CALLBACKS: list[Any] = []
_pointer_passthrough_lock = threading.RLock()
_pointer_passthrough_stops: dict[str, threading.Event] = {}


def _dispatch_to_main_queue(fn: Callable[[], None]) -> None:
    """Schedule ``fn`` on the macOS main queue via GCD."""
    import ctypes

    CFUNC = ctypes.CFUNCTYPE(None, ctypes.c_void_p)

    def _wrapper(_ctx: ctypes.c_void_p) -> None:
        try:
            fn()
        except Exception as exc:
            logger.error("GCD 主线程回调异常: %s", exc, exc_info=True)
        finally:
            try:
                _MAIN_QUEUE_CALLBACKS.remove(_cb_ref[0])
            except ValueError:
                pass

    _cb = CFUNC(_wrapper)
    _cb_ref = [_cb]
    _MAIN_QUEUE_CALLBACKS.append(_cb)

    lib = ctypes.CDLL(None)
    main_q_obj = ctypes.c_void_p.in_dll(lib, "_dispatch_main_q")
    queue = ctypes.addressof(main_q_obj)

    lib.dispatch_async_f.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
    ]
    lib.dispatch_async_f(queue, None, _cb)


def _run_on_macos_main_thread(fn: Callable[[], Any], *, timeout_seconds: float = 0.6) -> Any:
    """Run ``fn`` on the macOS main thread and return its result."""
    if platform.system() != "Darwin" or threading.current_thread() is threading.main_thread():
        return fn()

    done = threading.Event()
    result: dict[str, Any] = {}

    def _runner() -> None:
        try:
            result["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - propagate original failure
            result["error"] = exc
        finally:
            done.set()

    _dispatch_to_main_queue(_runner)
    if not done.wait(max(0.05, timeout_seconds)):
        raise TimeoutError("等待 macOS 主线程执行超时")
    if "error" in result:
        raise result["error"]
    return result.get("value")


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

    def _apply() -> bool:
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

    try:
        return bool(_run_on_macos_main_thread(_apply))
    except Exception as exc:
        logger.debug("调度 macOS 窗口行为到主线程失败: %s", exc)
        return False


def focus_macos_window(*, title: str) -> bool:
    """按标题聚焦 macOS NSWindow，用于右键菜单立即接收键鼠焦点。"""
    if platform.system() != "Darwin":
        return False

    def _focus() -> bool:
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

    try:
        return bool(_run_on_macos_main_thread(_focus))
    except Exception as exc:
        logger.debug("调度 macOS 窗口聚焦到主线程失败: %s", exc)
        return False


def bubble_visual_hit_test(width: float, height: float, x: float, y: float) -> bool:
    """Return whether a point is inside the visible circular Bubble launcher."""
    if width <= 0 or height <= 0:
        return False
    diameter = max(0.0, min(width, height) - 8.0)
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
        if region_hit is not None:
            return region_hit

    return _default_live2d_hit_test(width, height, x, y)


def schedule_macos_pointer_passthrough(
    *,
    title: str,
    hit_test: PointerHitTest,
    pointer_observer: PointerObserver | None = None,
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
            "pointer_observer": pointer_observer,
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
    pointer_observer: PointerObserver | None,
    stop: threading.Event,
    delay_seconds: float,
    interval_seconds: float,
    focus_on_hover: bool,
) -> None:
    time.sleep(max(0.0, delay_seconds))
    if stop.is_set():
        _discard_pointer_passthrough_stop(title, stop)
        return

    state: dict[str, Any] = {
        "target_seen": False,
        "missing_after_seen": 0,
        "last_ignoring": None,
        "last_interactive": None,
    }

    try:
        while not stop.is_set():
            try:
                keep_running = bool(
                    _run_on_macos_main_thread(
                        lambda: _pointer_passthrough_tick_on_main(
                            title=title,
                            hit_test=hit_test,
                            pointer_observer=pointer_observer,
                            focus_on_hover=focus_on_hover,
                            state=state,
                        ),
                        timeout_seconds=max(0.15, interval_seconds * 6.0),
                    )
                )
            except TimeoutError:
                time.sleep(max(0.02, interval_seconds))
                continue
            if not keep_running:
                break
            time.sleep(max(0.02, interval_seconds))
    except Exception as exc:
        logger.debug("macOS 鼠标穿透轮询失败: title=%s error=%s", title, exc)
    finally:
        _discard_pointer_passthrough_stop(title, stop)
        try:
            _run_on_macos_main_thread(lambda: _reset_window_mouse_events(title), timeout_seconds=0.2)
        except Exception:
            pass


def _pointer_passthrough_tick_on_main(
    *,
    title: str,
    hit_test: PointerHitTest,
    pointer_observer: PointerObserver | None,
    focus_on_hover: bool,
    state: dict[str, Any],
) -> bool:
    try:
        from AppKit import NSApp, NSEvent  # type: ignore[import-untyped]
    except Exception as exc:
        logger.debug("PyObjC/AppKit 不可用，跳过 macOS 鼠标穿透设置: %s", exc)
        return False

    target = _find_macos_window(title=title)
    if target is None:
        if state.get("target_seen"):
            missing_after_seen = int(state.get("missing_after_seen", 0)) + 1
            state["missing_after_seen"] = missing_after_seen
            return missing_after_seen < 20
        return True

    state["target_seen"] = True
    state["missing_after_seen"] = 0
    frame = target.frame()
    width = float(frame.size.width)
    height = float(frame.size.height)
    mouse = NSEvent.mouseLocation()
    local_x = float(mouse.x - frame.origin.x)
    local_y_from_bottom = float(mouse.y - frame.origin.y)
    inside = 0 <= local_x <= width and 0 <= local_y_from_bottom <= height
    local_y = height - local_y_from_bottom

    if pointer_observer is not None:
        try:
            pointer_observer(width, height, local_x, local_y, inside)
        except Exception as exc:
            logger.debug("窗口指针观察回调失败: title=%s error=%s", title, exc)

    interactive = False
    if inside:
        try:
            interactive = bool(hit_test(width, height, local_x, local_y))
        except Exception as exc:
            logger.debug("窗口命中测试失败: title=%s error=%s", title, exc)
            interactive = True

    last_ignoring = state.get("last_ignoring")
    should_ignore = not interactive
    if should_ignore != last_ignoring:
        target.setIgnoresMouseEvents_(should_ignore)
        state["last_ignoring"] = should_ignore

    last_interactive = state.get("last_interactive")
    if focus_on_hover and interactive and last_interactive is not True:
        try:
            target.setIgnoresMouseEvents_(False)
            state["last_ignoring"] = False
            target.makeKeyAndOrderFront_(None)
            NSApp.activateIgnoringOtherApps_(True)
        except Exception as exc:
            logger.debug("hover 聚焦 macOS 窗口失败: title=%s error=%s", title, exc)

    state["last_interactive"] = interactive
    return True


def _reset_window_mouse_events(title: str) -> None:
    target = _find_macos_window(title=title)
    if target is not None:
        target.setIgnoresMouseEvents_(False)


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

    if kind == "alpha_mask":
        return _alpha_mask_hit_test(left, top, region_width, region_height, x, y, region)

    if kind in {"live2d", "model"}:
        # Reject obviously oversized regions to avoid regressing to near-rectangular hit boxes.
        if region_width > width * 0.76 or region_height > height * 0.88:
            return None
        # Live2D stage anchors at bottom; model head should not start too close to top edge.
        if top < height * 0.10:
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
    region_height = height * 0.70
    region_width = min(width * 0.44, region_height * 0.54)
    left = (width - region_width) / 2.0
    top = min(height * 0.30, height * 0.98 - region_height)
    return bool(_live2d_region_hit_test(left, top, region_width, region_height, x, y))


def _alpha_mask_hit_test(
    left: float,
    top: float,
    region_width: float,
    region_height: float,
    x: float,
    y: float,
    region: dict[str, object],
) -> bool | None:
    try:
        cols = int(region.get("cols", 0))
        rows = int(region.get("rows", 0))
        mask = str(region.get("mask") or "")
    except (TypeError, ValueError):
        return None

    if cols <= 0 or rows <= 0 or len(mask) < cols * rows:
        return None
    if x < left or x > left + region_width or y < top or y > top + region_height:
        return False

    rel_x = 0.0 if region_width <= 0 else (x - left) / region_width
    rel_y = 0.0 if region_height <= 0 else (y - top) / region_height
    col = min(cols - 1, max(0, int(rel_x * cols)))
    row = min(rows - 1, max(0, int(rel_y * rows)))
    return mask[(row * cols) + col] == "1"


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
    if u < -0.015 or u > 1.015 or v < -0.015 or v > 1.015:
        return False

    return (
        _ellipse_unit_hit(u, v, 0.36, 0.08, 0.10, 0.08)
        or _ellipse_unit_hit(u, v, 0.64, 0.08, 0.10, 0.08)
        or _ellipse_unit_hit(u, v, 0.50, 0.17, 0.22, 0.15)
        or _ellipse_unit_hit(u, v, 0.50, 0.30, 0.30, 0.16)
        or _ellipse_unit_hit(u, v, 0.50, 0.48, 0.24, 0.20)
        or _ellipse_unit_hit(u, v, 0.30, 0.54, 0.12, 0.17)
        or _ellipse_unit_hit(u, v, 0.70, 0.54, 0.12, 0.17)
        or _ellipse_unit_hit(u, v, 0.50, 0.66, 0.36, 0.18)
        or _capsule_unit_hit(u, v, 0.44, 0.72, 0.95, 0.048)
        or _capsule_unit_hit(u, v, 0.56, 0.72, 0.95, 0.048)
        or _ellipse_unit_hit(u, v, 0.50, 0.91, 0.19, 0.07)
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
