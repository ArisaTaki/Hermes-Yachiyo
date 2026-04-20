"""ChatBridge 测试 — 统一摘要层与三模式共享验证"""

from apps.core.chat_session import ChatSession
from apps.core.chat_store import ChatStore
from apps.core.state import AppState
from apps.shell.chat_bridge import ChatBridge, _truncate
from apps.shell.modes.bubble import _BUBBLE_HTML
from apps.shell.modes.live2d import _LIVE2D_HTML
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


def test_live2d_html_keeps_idle_polling_for_cross_mode_updates():
    assert "const IDLE_POLL_INTERVAL_MS = 5000;" in _LIVE2D_HTML
    assert "function startIdlePolling()" in _LIVE2D_HTML
    assert "function startActivePolling()" in _LIVE2D_HTML
    assert "startIdlePolling();" in _LIVE2D_HTML
    assert "window.addEventListener('pywebviewready', bootstrap);" in _LIVE2D_HTML


def test_thinking_dots_use_real_elements_not_content_animation():
    for html in (_BUBBLE_HTML, _LIVE2D_HTML):
        assert "@keyframes thinking-dot" in html
        assert "@keyframes thinking-dots" not in html
        assert "content: '.'" not in html
        assert '<span class="dot" aria-hidden="true">.</span>' in html
        assert '<span class="label">正在思考</span>' not in html
