"""Launcher notification tracker tests."""

from apps.shell.launcher_notifications import LauncherNotificationTracker, latest_notifiable_message


def _chat(message_id: str = "a1", content: str = "回复", status: str = "completed"):
    return {
        "messages": [
            {
                "id": message_id,
                "role": "assistant",
                "content": content,
                "status": status,
                "task_id": "t1",
            }
        ],
        "latest_notifiable_message": {
            "marker": message_id,
            "id": message_id,
            "content": content,
            "status": status,
        },
    }


def test_latest_notifiable_message_ignores_processing_and_empty_content():
    assert latest_notifiable_message(_chat(status="processing")) is None
    assert latest_notifiable_message(_chat(content="")) is None
    assert latest_notifiable_message(_chat())["marker"] == "a1"


def test_tracker_does_not_notify_existing_history_on_first_update():
    tracker = LauncherNotificationTracker()

    state = tracker.update(_chat("a1"))

    assert state["has_unread"] is False
    assert state["message_marker"] == "a1"


def test_tracker_notifies_only_when_new_assistant_result_arrives():
    tracker = LauncherNotificationTracker()
    tracker.update(_chat("a1"))

    same = tracker.update(_chat("a1"))
    newer = tracker.update(_chat("a2", "新回复"))

    assert same["has_unread"] is False
    assert newer["has_unread"] is True
    assert newer["source"] == "chat"
    assert newer["unread_marker"] == "a2"


def test_tracker_acknowledge_clears_unread_marker():
    tracker = LauncherNotificationTracker()
    tracker.update(_chat("a1"))
    tracker.update(_chat("a2"))

    tracker.acknowledge(_chat("a2"))
    state = tracker.update(_chat("a2"))

    assert state["has_unread"] is False


def test_tracker_reports_external_attention_without_chat_unread():
    tracker = LauncherNotificationTracker()
    tracker.update(_chat("a1"))

    state = tracker.update(_chat("a1"), external_attention=True)

    assert state["has_unread"] is True
    assert state["source"] == "proactive"
