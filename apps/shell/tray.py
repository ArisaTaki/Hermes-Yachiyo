"""系统托盘管理

MVP 实现：使用 pystray 提供系统托盘图标。
后续可替换为其他桌面壳方案的原生托盘。

macOS 注意事项
--------------
pystray 的 darwin 后端在构造时即调用 AppKit.NSStatusBar 等对象，
这些 AppKit UI 对象必须在主线程创建。因此在 macOS 下不能在子线程调用
``pystray.Icon(...)``；应使用 ``create_tray_macos()`` 通过 GCD 调度。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

try:
    import pystray
    from PIL import Image

    _HAS_TRAY = True
except ImportError:
    _HAS_TRAY = False

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime

logger = logging.getLogger(__name__)

# 防止 GCD 回调被 Python GC 提前回收（ctypes CFUNCTYPE 需要手动保活）
_GCD_CALLBACKS: list = []


def _create_icon_image() -> "Image.Image":
    """生成一个简单的占位托盘图标"""
    img = Image.new("RGB", (64, 64), color=(100, 149, 237))
    return img


def create_tray(runtime: "HermesRuntime") -> None:
    """创建并运行系统托盘图标（非 macOS 平台）。

    此函数会阻塞调用线程（在 pystray 的 icon.run() 内循环），
    应在后台 daemon 线程中调用。
    """
    if not _HAS_TRAY:
        logger.warning("pystray 未安装，跳过系统托盘")
        return

    def on_status(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        status = runtime.get_status()
        logger.info("状态: %s", status)

    def on_quit(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("状态", on_status),
        pystray.MenuItem("退出", on_quit),
    )

    icon = pystray.Icon(
        name="hermes-yachiyo",
        icon=_create_icon_image(),
        title="Hermes-Yachiyo",
        menu=menu,
    )
    icon.run()


# ── macOS 专用：GCD 主线程调度 ────────────────────────────────────────────────

def _dispatch_to_main_queue(fn) -> None:
    """macOS: 将 fn 追加到 GCD 主队列，在主 run loop 下一次迭代时执行。

    可在主线程或子线程调用。若在 ``NSApp.run()`` 启动之前入队，
    回调会在 NSApp 运行后自动执行（GCD 主队列与主线程 run loop 绑定）。
    """
    import ctypes

    CFUNC = ctypes.CFUNCTYPE(None, ctypes.c_void_p)

    def _wrapper(_ctx: ctypes.c_void_p) -> None:
        try:
            fn()
        except Exception as exc:
            logger.error("GCD 主线程回调异常: %s", exc, exc_info=True)
        finally:
            # 回调执行完毕后移除保活引用
            try:
                _GCD_CALLBACKS.remove(_cb_ref[0])
            except ValueError:
                pass

    _cb = CFUNC(_wrapper)
    _cb_ref = [_cb]
    _GCD_CALLBACKS.append(_cb)  # 防止被 GC

    lib = ctypes.CDLL(None)  # RTLD_DEFAULT，macOS 下包含 libdispatch
    lib.dispatch_get_main_queue.restype = ctypes.c_void_p
    queue = lib.dispatch_get_main_queue()
    lib.dispatch_async_f.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
    ]
    lib.dispatch_async_f(ctypes.c_void_p(queue), None, _cb)


def create_tray_macos(runtime: "HermesRuntime") -> None:
    """macOS 专用：通过 GCD 将托盘创建调度到主 AppKit 事件循环中执行。

    调用时机：在 ``webview.start()``（即 ``NSApp.run()``）之前从主线程调用。
    GCD 主队列会在 NSApp 运行后处理入队的回调，保证 pystray.Icon() 在
    主线程上构造（满足 AppKit UI 对象的主线程要求）。

    pystray 0.19 darwin 后端的 ``_run_detached()`` 不启动独立的 NSApp
    事件循环，仅将图标挂载到 pywebview 已在主线程运行的 NSApp 事件循环上。
    """
    if not _HAS_TRAY:
        logger.warning("pystray 未安装，跳过系统托盘")
        return

    def _create_on_main() -> None:
        """GCD 回调：在主线程构造图标并以 run_detached 模式激活。"""
        try:
            _create_tray_main_thread(runtime)
        except Exception as exc:
            logger.error("macOS 托盘创建失败: %s", exc, exc_info=True)

    _dispatch_to_main_queue(_create_on_main)
    logger.info("系统托盘：GCD 调度已入队，将在 NSApp 启动后在主线程创建")


def _create_tray_main_thread(runtime: "HermesRuntime") -> None:
    """在主线程上构造 pystray 图标并以 run_detached 模式运行。

    ``icon.run_detached()`` 在 macOS darwin 后端只调用 ``_mark_ready()``，
    不会启动第二个 ``NSApp.run()``，图标事件由 pywebview 的 NSApp 负责分发。

    此函数必须从主线程调用（由 GCD 回调保证）。
    """
    def on_status(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        status = runtime.get_status()
        logger.info("状态: %s", status)

    def on_quit(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("状态", on_status),
        pystray.MenuItem("退出", on_quit),
    )

    icon = pystray.Icon(
        name="hermes-yachiyo",
        icon=_create_icon_image(),
        title="Hermes-Yachiyo",
        menu=menu,
    )
    # run_detached() 在 macOS darwin 后端：
    #   - 设置图标（NSStatusItem 已在 __init__ 中创建）
    #   - 调用 _run_detached() → _mark_ready()，不启动 NSApp 事件循环
    #   - 图标通过 pywebview 已运行的 NSApp 接收系统事件
    icon.run_detached()
    logger.info("系统托盘图标已创建（macOS run_detached 模式，挂载到 pywebview NSApp）")
