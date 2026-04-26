"""ChatBridge 测试 — 统一摘要层与三模式共享验证"""

import sys

from apps.core.chat_session import ChatSession
from apps.core.chat_store import ChatStore
from apps.core.state import AppState
from apps.shell.chat_bridge import ChatBridge, _truncate
from apps.shell.config import AppConfig
from apps.shell.modes.bubble import BubbleWindowAPI, _BUBBLE_HTML, _BUBBLE_MENU_HTML, _render_bubble_html
import apps.shell.modes.live2d as _live2d_mod
from apps.shell.modes.live2d import Live2DWindowAPI, _LIVE2D_HTML, _render_live2d_html
from packages.protocol.enums import TaskStatus


class _RuntimeStub:
    """测试用运行时桩"""
    def __init__(self, store: ChatStore) -> None:
        self.state = AppState()
        self.chat_session = ChatSession(session_id="s1")
        self.chat_session.attach_store(store, load_existing=False)
        self.task_runner = None
        self.cancelled_runner_tasks: list[str] = []

    def cancel_task_runner_task(self, task_id: str) -> bool:
        self.cancelled_runner_tasks.append(task_id)
        return True

    def is_hermes_ready(self) -> bool:
        return True

    def get_status(self):
        return {"hermes": {"limited_tools": []}}


def _make_bridge(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    return ChatBridge(runtime), runtime, store


# ── 截断函数 ──────────────────────────────────────────────────────────────────

def test_truncate_short_text():
    assert _truncate("hello", 80) == "hello"


def test_truncate_long_text():
    long = "x" * 100
    result = _truncate(long, 80)
    assert len(result) == 81  # 80 + "…"
    assert result.endswith("…")


# ── 摘要空状态 ────────────────────────────────────────────────────────────────

def test_empty_session_summary(tmp_path):
    bridge, runtime, store = _make_bridge(tmp_path)
    try:
        result = bridge.get_recent_summary(3)
        assert result["ok"] is True
        assert result["empty"] is True
        assert result["status_label"] == "暂无对话"
        assert result["messages"] == []
    finally:
        store.close()


def test_empty_session_status(tmp_path):
    bridge, runtime, store = _make_bridge(tmp_path)
    try:
        status = bridge.get_session_status()
        assert status["ok"] is True
        assert status["status_label"] == "暂无对话"
        assert status["message_count"] == 0
        assert status["is_processing"] is False
    finally:
        store.close()


def test_session_status_error_has_consistent_api_contract(tmp_path):
    bridge, runtime, store = _make_bridge(tmp_path)

    class BrokenChatAPI:
        def get_session_info(self):
            raise RuntimeError("boom")

    try:
        bridge._chat_api = BrokenChatAPI()  # type: ignore[assignment]

        status = bridge.get_session_status()

        assert status["ok"] is False
        assert status["error"] == "boom"
        assert status["status_label"] == "错误"
    finally:
        store.close()


# ── 快捷发送 ──────────────────────────────────────────────────────────────────

def test_send_quick_message(tmp_path):
    bridge, runtime, store = _make_bridge(tmp_path)
    try:
        result = bridge.send_quick_message("你好")
        assert result["ok"] is True
        assert "message_id" in result
        assert "task_id" in result
        # 消息应该进入统一 ChatSession
        assert runtime.chat_session.message_count() == 1
    finally:
        store.close()


def test_send_quick_message_empty(tmp_path):
    bridge, runtime, store = _make_bridge(tmp_path)
    try:
        result = bridge.send_quick_message("")
        assert result["ok"] is False
    finally:
        store.close()


# ── 摘要内容 ──────────────────────────────────────────────────────────────────

def test_summary_shows_recent_messages(tmp_path):
    bridge, runtime, store = _make_bridge(tmp_path)
    try:
        # 发 3 条消息，完成 2 条
        for i in range(3):
            r = bridge.send_quick_message(f"消息{i}")
            task_id = r["task_id"]
            if i < 2:
                runtime.state.update_task_status(task_id, TaskStatus.RUNNING)
                runtime.state.update_task_status(task_id, TaskStatus.COMPLETED, result=f"回复{i}")

        summary = bridge.get_recent_summary(3)
        assert summary["ok"] is True
        assert summary["is_processing"] is True  # 第三条还在 pending
        assert summary["status_label"] == "处理中…"
        # 应该能看到最近 3 条消息（从排序后的列表取末尾）
        assert len(summary["messages"]) == 3
    finally:
        store.close()


def test_summary_truncates_long_content(tmp_path):
    bridge, runtime, store = _make_bridge(tmp_path)
    try:
        long_text = "A" * 200
        bridge.send_quick_message(long_text)
        summary = bridge.get_recent_summary(1)
        assert summary["ok"] is True
        msg = summary["messages"][0]
        assert len(msg["content"]) <= 81  # 80 + "…"
    finally:
        store.close()


def test_conversation_overview_keeps_full_latest_reply_for_tts(tmp_path):
    bridge, runtime, store = _make_bridge(tmp_path)
    try:
        long_reply = "长回复" + "A" * 200
        result = bridge.send_quick_message("需要一段长回复")
        runtime.state.update_task_status(result["task_id"], TaskStatus.RUNNING)
        runtime.state.update_task_status(result["task_id"], TaskStatus.COMPLETED, result=long_reply)

        summary = bridge.get_recent_summary(3)
        overview = bridge.get_conversation_overview(summary_count=3, session_limit=3)

        assert summary["latest_reply_full"] == long_reply
        assert overview["latest_reply_full"] == long_reply
        assert overview["latest_reply"] == _truncate(long_reply)
        assert overview["latest_reply"] != overview["latest_reply_full"]
    finally:
        store.close()


def test_summary_count_zero_returns_no_messages(tmp_path):
    bridge, runtime, store = _make_bridge(tmp_path)
    try:
        bridge.send_quick_message("不会出现在摘要里")

        summary = bridge.get_recent_summary(0)

        assert summary["ok"] is True
        assert summary["empty"] is False
        assert summary["messages"] == []
    finally:
        store.close()


def test_summary_invalid_count_returns_no_messages(tmp_path):
    bridge, runtime, store = _make_bridge(tmp_path)
    try:
        bridge.send_quick_message("不会出现在摘要里")

        summary = bridge.get_recent_summary("bad")  # type: ignore[arg-type]

        assert summary["ok"] is True
        assert summary["messages"] == []
    finally:
        store.close()


# ── 处理中状态 ────────────────────────────────────────────────────────────────

def test_processing_status_label(tmp_path):
    bridge, runtime, store = _make_bridge(tmp_path)
    try:
        r = bridge.send_quick_message("测试")
        runtime.state.update_task_status(r["task_id"], TaskStatus.RUNNING)

        summary = bridge.get_recent_summary(3)
        assert summary["is_processing"] is True
        assert summary["status_label"] == "处理中…"
    finally:
        store.close()


def test_completed_status_label(tmp_path):
    bridge, runtime, store = _make_bridge(tmp_path)
    try:
        r = bridge.send_quick_message("测试")
        runtime.state.update_task_status(r["task_id"], TaskStatus.RUNNING)
        runtime.state.update_task_status(r["task_id"], TaskStatus.COMPLETED, result="ok")

        summary = bridge.get_recent_summary(3)
        assert summary["is_processing"] is False
        assert summary["status_label"] == "就绪"
    finally:
        store.close()


# ── 三模式共享状态验证 ────────────────────────────────────────────────────────

def test_three_modes_share_session(tmp_path):
    """验证 bubble/live2d/chat_window 共享同一个 ChatSession"""
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        # 模拟 bubble 的 ChatBridge
        bubble_bridge = ChatBridge(runtime)
        # 模拟 live2d 的 ChatBridge
        live2d_bridge = ChatBridge(runtime)

        # bubble 发消息
        r1 = bubble_bridge.send_quick_message("来自bubble")
        assert r1["ok"] is True

        # live2d 能看到
        summary = live2d_bridge.get_recent_summary(3)
        assert len(summary["messages"]) == 1
        assert summary["messages"][0]["content"] == "来自bubble"

        # live2d 也发消息
        r2 = live2d_bridge.send_quick_message("来自live2d")
        assert r2["ok"] is True

        # bubble 能看到两条
        summary2 = bubble_bridge.get_recent_summary(3)
        assert len(summary2["messages"]) == 2

        # 都在同一个 session
        assert summary["session_id"] == summary2["session_id"]
        assert runtime.chat_session.message_count() == 2
    finally:
        store.close()


def test_modes_do_not_create_independent_sessions(tmp_path):
    """确认 bridge 实例不会创建独立会话"""
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        b1 = ChatBridge(runtime)
        b2 = ChatBridge(runtime)

        s1 = b1.get_session_status()
        s2 = b2.get_session_status()
        assert s1["session_id"] == s2["session_id"]
    finally:
        store.close()


def test_conversation_overview_includes_recent_sessions(tmp_path):
    bridge, runtime, store = _make_bridge(tmp_path)
    try:
        bridge.send_quick_message("overview")

        overview = bridge.get_conversation_overview(summary_count=2, session_limit=3)

        assert overview["ok"] is True
        assert overview["messages"]
        assert overview["recent_sessions"]
        assert overview["recent_sessions"][0]["is_current"] is True
    finally:
        store.close()


# ── 失败状态 ──────────────────────────────────────────────────────────────────

def test_failed_task_in_summary(tmp_path):
    bridge, runtime, store = _make_bridge(tmp_path)
    try:
        r = bridge.send_quick_message("会失败")
        runtime.state.update_task_status(r["task_id"], TaskStatus.RUNNING)
        runtime.state.update_task_status(r["task_id"], TaskStatus.FAILED, error="boom")

        summary = bridge.get_recent_summary(3)
        assert summary["ok"] is True
        assert summary["is_processing"] is False
        # 应该有 user + assistant(failed) 两条
        assert len(summary["messages"]) == 2
    finally:
        store.close()


def test_bubble_html_keeps_idle_polling_for_cross_mode_updates():
    assert "const IDLE_POLL_INTERVAL_MS = 5000;" in _BUBBLE_HTML
    assert "function startIdlePolling()" in _BUBBLE_HTML
    assert "function startActivePolling()" in _BUBBLE_HTML
    assert "startIdlePolling();" in _BUBBLE_HTML
    assert "window.addEventListener('pywebviewready', bootstrap);" in _BUBBLE_HTML
    assert "openSettings()" in _BUBBLE_HTML
    assert "Yachiyo" in _BUBBLE_HTML
    assert "bubble-launcher" in _BUBBLE_HTML
    assert "toggle_chat" in _BUBBLE_HTML
    assert "set_dragging" in _BUBBLE_HTML
    assert "open_context_menu" in _BUBBLE_HTML
    assert "close_context_menu" in _BUBBLE_HTML
    assert "normalizedStatusLabel" in _BUBBLE_HTML
    assert "label === '就绪'" in _BUBBLE_HTML
    assert "onpointerenter" not in _BUBBLE_HTML
    assert "hoverOpening" not in _BUBBLE_HTML
    assert "getExpandTrigger" not in _BUBBLE_HTML
    assert "getExpandTrigger() !== 'click'" not in _BUBBLE_HTML


def test_bubble_status_dot_visible_states_are_explicit():
    assert "const hasUnread = showDot && !!bubble.has_attention;" in _BUBBLE_HTML
    assert "if (hasUnread)" in _BUBBLE_HTML
    assert "dotClass += ' visible attention';" in _BUBBLE_HTML
    assert "status === 'processing'" in _BUBBLE_HTML
    assert "dotClass += ' visible processing';" in _BUBBLE_HTML
    assert "status === 'failed'" in _BUBBLE_HTML
    assert "dotClass += ' visible failed';" in _BUBBLE_HTML
    assert "dotClass += ' ' + status;" in _BUBBLE_HTML


def test_bubble_context_menu_uses_separate_window_html():
    assert "context-menu" not in _BUBBLE_HTML
    assert "positionMenu(event)" not in _BUBBLE_HTML
    assert "打开对话" in _BUBBLE_MENU_HTML
    assert "主控台" in _BUBBLE_MENU_HTML
    assert "invokeAction('open_chat')" in _BUBBLE_MENU_HTML
    assert "window.addEventListener('blur'" in _BUBBLE_MENU_HTML


def test_bubble_context_menu_api_creates_separate_window(tmp_path, monkeypatch):
    class _EventHook:
        def __init__(self):
            self.handler = None

        def __iadd__(self, handler):
            self.handler = handler
            return self

    class _Events:
        def __init__(self):
            self.closed = _EventHook()

    class _Window:
        def __init__(self):
            self.events = _Events()
            self.destroyed = False
            self.destroy_calls = 0

        def destroy(self):
            self.destroyed = True
            self.destroy_calls += 1

    class _Webview:
        def __init__(self):
            self.calls = []
            self.window = _Window()

        def create_window(self, **kwargs):
            self.calls.append(kwargs)
            return self.window

    webview = _Webview()
    monkeypatch.setitem(sys.modules, "webview", webview)
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    api = BubbleWindowAPI(runtime, AppConfig())
    try:
        result = api.open_context_menu(120, 80)

        assert result == {"ok": True, "open": True}
        assert webview.calls[0]["title"] == "Hermes-Yachiyo Bubble Menu"
        assert webview.calls[0]["width"] > 112
        assert webview.calls[0]["height"] > 112
        assert webview.calls[0]["x"] == 120
        assert webview.calls[0]["y"] == 80
        assert api._context_menu_open is True

        assert api.close_context_menu()["ok"] is True
        assert webview.window.destroy_calls == 1
        assert api._context_menu_open is False
    finally:
        store.close()


def test_live2d_html_keeps_idle_polling_for_cross_mode_updates():
    assert "{{RUNTIME_ENV_SHIM}}" in _LIVE2D_HTML
    assert "const IDLE_POLL_INTERVAL_MS = 5000;" in _LIVE2D_HTML
    assert "function startIdlePolling()" in _LIVE2D_HTML
    assert "function startActivePolling()" in _LIVE2D_HTML
    assert "startIdlePolling();" in _LIVE2D_HTML
    assert "window.addEventListener('pywebviewready', bootstrap);" in _LIVE2D_HTML
    assert "window.addEventListener('error', function(event)" in _LIVE2D_HTML
    assert "window.addEventListener('unhandledrejection', function(event)" in _LIVE2D_HTML
    assert "openSettings()" in _LIVE2D_HTML
    assert "live2d-canvas" in _LIVE2D_HTML
    assert "live2d-fallback-preview" in _LIVE2D_HTML
    assert "ensureLive2DRenderer" in _LIVE2D_HTML
    assert "dismissResourceHint(event)" in _LIVE2D_HTML
    assert "live2d-resource-hint-close" in _LIVE2D_HTML
    assert "report_client_event" in _LIVE2D_HTML
    assert "set_dragging" in _LIVE2D_HTML
    assert "formatRendererDiagnostics" in _LIVE2D_HTML
    assert "getLive2DModelCtor" in _LIVE2D_HTML
    assert "hair-back" not in _LIVE2D_HTML
    assert "toggle_chat" in _LIVE2D_HTML
    assert "--live2d-preview-scale" in _LIVE2D_HTML
    assert "alpha_mask" in _LIVE2D_HTML
    assert "updateLive2DFocus(event, false)" in _LIVE2D_HTML
    assert "mouse_follow_enabled" in _LIVE2D_HTML
    assert "cursor: default;" in _LIVE2D_HTML
    assert "get_pointer_state" in _LIVE2D_HTML
    assert "startGlobalPointerPolling" in _LIVE2D_HTML
    assert "update_ui_regions" in _LIVE2D_HTML
    assert "reportUIRegions()" in _LIVE2D_HTML
    assert "@keyframes live2d-idle" not in _LIVE2D_HTML
    assert 'onpointerenter="focusLauncherWindow()"' not in _LIVE2D_HTML
    assert "notification.has_unread" in _LIVE2D_HTML
    assert "!!chat.latest_reply && !chat.is_processing" not in _LIVE2D_HTML


def test_launcher_modes_do_not_embed_inline_chat_inputs():
    assert "send_quick_message" not in _BUBBLE_HTML
    assert "msg-input" not in _BUBBLE_HTML
    assert "toggleChat(event)" in _BUBBLE_HTML
    assert "event.key === 'Escape'" in _BUBBLE_HTML
    assert "CLICK_DRAG_THRESHOLD_PX" in _BUBBLE_HTML
    assert "trackLauncherPointerDown(event)" in _BUBBLE_HTML
    assert "shouldIgnoreLauncherClick(event)" in _BUBBLE_HTML
    assert "window.pywebview.api.focus_window" in _BUBBLE_HTML
    for html in (_LIVE2D_HTML,):
        assert "msg-input" not in html
        assert "window.addEventListener('blur', hideMenu);" in html
        assert "event.key === 'Escape'" in html
        assert "CLICK_DRAG_THRESHOLD_PX" in html
        assert "trackLauncherPointerDown(event)" in html
        assert "shouldIgnoreLauncherClick(event)" in html
        assert "positionMenu(event)" in html
        assert "window.pywebview.api.focus_window" in html
        assert "set_context_menu_open" in html
    assert "handleStageClick(event)" in _LIVE2D_HTML
    assert "send_quick_message" in _LIVE2D_HTML
    assert "quick-input" in _LIVE2D_HTML
    assert "reply-bubble" in _LIVE2D_HTML
    assert "update_hit_region" in _LIVE2D_HTML
    assert "reportLive2DModelHitRegion" in _LIVE2D_HTML
    assert "status-dot" not in _LIVE2D_HTML
    assert "live2d-message-glow" in _LIVE2D_HTML


def test_launcher_html_avoids_invalid_alpha_hex_background():
    for html in (_BUBBLE_HTML, _LIVE2D_HTML):
        assert "#00000000" not in html


def test_bubble_avatar_is_embedded_as_data_uri():
    html = _render_bubble_html(AppConfig())

    assert "{{AVATAR_URL}}" not in html
    assert "background-image: url(\"data:image/" in html


def test_live2d_preview_is_embedded_as_data_uri():
    html = _render_live2d_html(AppConfig())

    assert "{{PREVIEW_URL}}" not in html
    assert '<img class="live2d-preview-fallback hidden"' in html
    assert 'src="data:image/' in html


def test_live2d_html_includes_renderer_cdns(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _live2d_mod,
        "_get_live2d_runtime_cache_dir",
        lambda: tmp_path / "empty-live2d-web-cache",
    )
    _live2d_mod._LIVE2D_RUNTIME_DEPENDENCY_STATE.update(
        {"primed": False, "ready": False, "error": ""}
    )
    html = _render_live2d_html(AppConfig())

    assert "cdn.jsdelivr.net/npm/pixi.js@6" in html
    assert "cdn.jsdelivr.net/npm/pixi-live2d-display@0.5.0-beta" in html
    assert "cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js" in html


def test_live2d_html_prefers_cached_runtime_scripts(tmp_path, monkeypatch):
    cache_dir = tmp_path / "live2d-web-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    pixi = cache_dir / "pixi.min.js"
    cubism = cache_dir / "live2dcubismcore.min.js"
    display = cache_dir / "pixi-live2d-display-cubism4.min.js"
    pixi.write_text("window.PIXI = {};", encoding="utf-8")
    cubism.write_text("window.Live2DCubismCore = {};", encoding="utf-8")
    display.write_text("window.PIXI = window.PIXI || {};", encoding="utf-8")

    monkeypatch.setattr(_live2d_mod, "_get_live2d_runtime_cache_dir", lambda: cache_dir)
    _live2d_mod._LIVE2D_RUNTIME_DEPENDENCY_STATE.update(
        {"primed": False, "ready": False, "error": ""}
    )

    html = _render_live2d_html(AppConfig())

    assert "process.env.NODE_ENV = 'production'" in html
    assert "window.PIXI = {};" in html
    assert "window.Live2DCubismCore = {};" in html
    assert "cdn.jsdelivr.net/npm/pixi.js@6" not in html
    assert "cdn.jsdelivr.net/npm/pixi-live2d-display@0.5.0-beta" not in html
    assert "cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js" not in html


def test_live2d_view_exposes_renderer_payload(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    config = AppConfig(display_mode="live2d")
    model_dir = tmp_path / "models" / "yachiyo"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "yachiyo.model3.json").write_text("{}", encoding="utf-8")
    (model_dir / "yachiyo.moc3").write_text("stub", encoding="utf-8")
    config.live2d_mode.model_path = str(model_dir)
    try:
        _live2d_mod._LIVE2D_RUNTIME_DEPENDENCY_STATE.update(
            {"primed": False, "ready": False, "error": ""}
        )
        monkeypatch.setattr(
            _live2d_mod,
            "_get_bridge_state",
            lambda: "running",
        )
        monkeypatch.setattr(
            _live2d_mod,
            "_get_bridge_running_config",
            lambda _config: {"host": "127.0.0.1", "port": 8420},
        )
        monkeypatch.setattr("apps.bridge.server.get_live2d_asset_token", lambda: "token-123")

        view = Live2DWindowAPI(runtime, config).get_live2d_view()
        renderer = view["live2d"]["renderer"]

        assert renderer["enabled"] is True
        assert renderer["model_url"].startswith("http://127.0.0.1:8420/live2d/assets/")
        assert ".model3.json?token=token-123" in renderer["model_url"]
        assert renderer["mouse_follow_enabled"] is True
        assert view["live2d"]["click_action"] == "open_chat"
        assert view["live2d"]["show_reply_bubble"] is True
        assert view["live2d"]["enable_quick_input"] is True
        assert view["live2d"]["default_open_behavior"] == "reply_bubble"
    finally:
        store.close()


def test_live2d_view_reports_dependency_prepare_failure(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    config = AppConfig(display_mode="live2d")
    model_dir = tmp_path / "models" / "yachiyo"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "yachiyo.model3.json").write_text("{}", encoding="utf-8")
    (model_dir / "yachiyo.moc3").write_text("stub", encoding="utf-8")
    config.live2d_mode.model_path = str(model_dir)
    try:
        monkeypatch.setattr(_live2d_mod, "_get_bridge_state", lambda: "running")
        monkeypatch.setattr(
            _live2d_mod,
            "_get_bridge_running_config",
            lambda _config: {"host": "127.0.0.1", "port": 8420},
        )
        monkeypatch.setattr(_live2d_mod, "_runtime_dependency_files_ready", lambda: False)
        _live2d_mod._LIVE2D_RUNTIME_DEPENDENCY_STATE.update(
            {"primed": True, "ready": False, "error": "network blocked"}
        )

        view = Live2DWindowAPI(runtime, config).get_live2d_view()
        renderer = view["live2d"]["renderer"]

        assert renderer["enabled"] is False
        assert "network blocked" in renderer["reason"]
    finally:
        store.close()


def test_live2d_api_accepts_client_events(tmp_path, caplog):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    api = Live2DWindowAPI(runtime, AppConfig(display_mode="live2d"))
    try:
        with caplog.at_level("ERROR"):
            result = api.report_client_event(
                "error",
                "renderer.model_load_failed",
                "TypeError: Cannot read properties of undefined (reading 'from')",
            )

        assert result == {"ok": True}
        assert api._last_client_event["event"] == "renderer.model_load_failed"
        assert "Cannot read properties of undefined" in caplog.text
    finally:
        store.close()


def test_live2d_api_keeps_pointer_interactive_while_dragging(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    api = Live2DWindowAPI(runtime, AppConfig(display_mode="live2d"))
    try:
        api.update_hit_region({"kind": "live2d", "x": 0.3, "y": 0.2, "width": 0.4, "height": 0.6})
        assert api.is_pointer_interactive(400, 600, 8, 8) is False

        api.set_dragging(True)
        assert api.is_pointer_interactive(400, 600, 8, 8) is True

        api.set_dragging(False)
        assert api.is_pointer_interactive(400, 600, 8, 8) is False
    finally:
        store.close()


def test_live2d_api_keeps_ui_regions_clickable(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    api = Live2DWindowAPI(runtime, AppConfig(display_mode="live2d"))
    try:
        api.update_hit_region({"kind": "alpha_mask", "x": 0.3, "y": 0.3, "width": 0.2, "height": 0.3, "cols": 2, "rows": 2, "mask": "1111"})
        api.update_ui_regions([{"kind": "rect", "x": 0.6, "y": 0.08, "width": 0.08, "height": 0.08}])

        assert api.is_pointer_interactive(420, 680, 270, 70) is True
        assert api.is_pointer_interactive(420, 680, 24, 24) is False
    finally:
        store.close()


def test_live2d_api_exposes_cached_global_pointer_state(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    api = Live2DWindowAPI(runtime, AppConfig(display_mode="live2d"))
    try:
        api.observe_pointer(420, 680, 128.4, 256.8, True)
        state = api.get_pointer_state()

        assert state["ok"] is True
        assert state["x"] == 128.4
        assert state["y"] == 256.8
        assert state["inside"] is True
    finally:
        store.close()


def test_bubble_api_keeps_pointer_interactive_while_dragging(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    api = BubbleWindowAPI(runtime, AppConfig())
    try:
        assert api.is_pointer_interactive(112, 112, 0, 0) is False

        api.set_dragging(True)
        assert api.is_pointer_interactive(112, 112, 0, 0) is True

        api.set_dragging(False)
        assert api.is_pointer_interactive(112, 112, 0, 0) is False
    finally:
        store.close()


def test_live2d_view_reports_missing_resource_guidance(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    config = AppConfig(display_mode="live2d")
    try:
        _live2d_mod._LIVE2D_RUNTIME_DEPENDENCY_STATE.update(
            {"primed": False, "ready": False, "error": ""}
        )
        original_resolve = config.live2d_mode.resolve_model_path
        config.live2d_mode.resolve_model_path = lambda: None  # type: ignore[method-assign]
        view = Live2DWindowAPI(runtime, config).get_live2d_view()

        resource = view["live2d"]["resource"]
        assert resource["state"] == "not_configured"
        assert "GitHub Releases" in resource["help_text"]
        assert resource["default_assets_root_display"].endswith(".hermes/yachiyo/assets/live2d")
    finally:
        config.live2d_mode.resolve_model_path = original_resolve  # type: ignore[method-assign]
        store.close()


def test_bubble_launcher_avoids_heavy_frame_and_blur():
    assert "drop-shadow" not in _BUBBLE_HTML
    assert "background: radial-gradient" not in _BUBBLE_HTML
    assert "#151515" not in _BUBBLE_HTML
    assert "backdrop-filter: none;" in _BUBBLE_HTML
    assert "-webkit-appearance: none;" in _BUBBLE_HTML
    assert "box-shadow: none;" in _BUBBLE_HTML


def test_bubble_red_attention_is_reserved_for_proactive_messages(tmp_path):
    _, runtime, store = _make_bridge(tmp_path)
    try:
        runtime.chat_session.add_assistant_message("普通对话回复")
        api = BubbleWindowAPI(runtime, AppConfig())

        view = api.get_bubble_view()

        assert view["bubble"]["has_attention"] is False
        assert view["proactive"]["status"] == "disabled"
    finally:
        store.close()


def test_bubble_view_consumes_runtime_display_settings(tmp_path):
    _, runtime, store = _make_bridge(tmp_path)
    try:
        config = AppConfig()
        config.bubble_mode.show_unread_dot = False
        config.bubble_mode.default_display = "recent_reply"
        config.bubble_mode.opacity = 0.66
        config.bubble_mode.expand_trigger = "hover"
        config.bubble_mode.auto_hide = True
        api = BubbleWindowAPI(runtime, config)

        view = api.get_bubble_view()

        assert view["bubble"]["show_unread_dot"] is False
        assert view["bubble"]["default_display"] == "recent_reply"
        assert view["bubble"]["opacity"] == 0.66
        assert view["bubble"]["expand_trigger"] == "click"
        assert view["bubble"]["auto_hide"] is True
    finally:
        store.close()


def test_bubble_view_marks_only_new_assistant_reply_as_unread(tmp_path):
    _, runtime, store = _make_bridge(tmp_path)
    try:
        runtime.chat_session.add_assistant_message("历史回复")
        api = BubbleWindowAPI(runtime, AppConfig())

        initial = api.get_bubble_view()
        runtime.chat_session.add_assistant_message("新回复")
        updated = api.get_bubble_view()

        assert initial["notification"]["has_unread"] is False
        assert initial["bubble"]["has_attention"] is False
        assert updated["notification"]["has_unread"] is True
        assert updated["bubble"]["has_attention"] is True

        api._clear_proactive_attention()
        acknowledged = api.get_bubble_view()
        assert acknowledged["notification"]["has_unread"] is False
        assert acknowledged["bubble"]["has_attention"] is False
    finally:
        store.close()


def test_live2d_view_consumes_interaction_settings(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    config = AppConfig(display_mode="live2d")
    config.live2d_mode.click_action = "toggle_reply"
    config.live2d_mode.show_reply_bubble = False
    config.live2d_mode.enable_quick_input = False
    config.live2d_mode.default_open_behavior = "chat_input"
    try:
        view = Live2DWindowAPI(runtime, config).get_live2d_view()

        assert view["live2d"]["click_action"] == "toggle_reply"
        assert view["live2d"]["show_reply_bubble"] is False
        assert view["live2d"]["enable_quick_input"] is False
        assert view["live2d"]["default_open_behavior"] == "chat_input"
        assert view["proactive"]["status"] == "disabled"
        assert view["notification"]["has_unread"] is False
        assert view["tts"]["enabled"] is False
    finally:
        store.close()


def test_bubble_proactive_desktop_watch_reports_executor_blocker(tmp_path):
    _, runtime, store = _make_bridge(tmp_path)
    try:
        config = AppConfig()
        config.bubble_mode.proactive_enabled = True
        config.bubble_mode.proactive_desktop_watch_enabled = True
        api = BubbleWindowAPI(runtime, config)

        view = api.get_bubble_view()

        assert view["bubble"]["has_attention"] is False
        assert view["proactive"]["status"] == "blocked"
        assert "任务执行器" in view["proactive"]["error"]
    finally:
        store.close()
