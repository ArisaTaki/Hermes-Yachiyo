"""桌面原生窗口行为辅助。

pywebview 提供跨平台窗口外壳；少数 macOS 行为（例如跨 Spaces 浮动）
需要走 NSWindow best-effort 调整。该模块保持可选依赖：没有 PyObjC 时直接跳过。
"""

from __future__ import annotations

import logging
import platform
import threading

logger = logging.getLogger(__name__)


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


def _collection_behavior_constant(name: str, *, fallback: int) -> int:
    try:
        import AppKit  # type: ignore[import-untyped]

        return int(getattr(AppKit, name))
    except Exception:
        return fallback
