"""Chat-entry regression coverage for capability-level media alias recovery."""

from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import quote_plus

from apps.core.task_runner import TaskStatus
from tests.test_chat_api import (
    _make_agent_runtime_service,
    _make_api,
    _native_postcondition_result,
    _send_foreground_message,
)


def test_named_media_miss_recovers_without_chat_profile(
    tmp_path,
    monkeypatch,
) -> None:
    api, runtime, store = _make_api(tmp_path)
    service = _make_agent_runtime_service(tmp_path)
    runtime.agent_runtime_service = service
    play_calls: list[str] = []
    opened_urls: list[str] = []
    expected_search_query = (
        "超时空辉夜姬 official title alternate title romanization"
    )
    expected_search_url = (
        "https://www.google.com/search?q=" + quote_plus(expected_search_query)
    )

    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(
                KeyError(profile_id)
            ),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("deterministic alias recovery must not call a model")
        ),
    )

    def fake_apple_music_play(query: str) -> dict:
        play_calls.append(query)
        if len(play_calls) == 1:
            return {
                "ok": True,
                "action": "media.apple_music_play",
                "summary": f"No exact media match for {query}",
                "data": {
                    "query": query,
                    "status": "not_found",
                    "outcome": "partial",
                    "background_safe": True,
                    "library_search_completed": True,
                    "foreground_action_taken": False,
                    "playback_started": False,
                    "search_opened": False,
                    "user_action_required": False,
                },
                "permission_error": False,
                "fallback_used": False,
            }
        return _native_postcondition_result(
            {
                "ok": True,
                "action": "media.apple_music_play",
                "summary": f"Playing {query}",
                "data": {
                    "query": query,
                    "status": "played",
                    "track": query,
                    "artist": "Various Artists",
                    "track_identity_verified": True,
                    "catalog_match_verified": True,
                    "player_state": "playing",
                    "playback_started": True,
                    "background_safe": True,
                    "foreground_action_taken": False,
                },
                "permission_error": False,
                "fallback_used": False,
            }
        )

    def fake_browser_open_url(url: str, **_kwargs) -> dict:
        opened_urls.append(url)
        return {
            "ok": True,
            "action": "browser.open_url",
            "data": {
                "url": url,
                "target_id": "run-owned-media-alias",
                "target_websocket_available": True,
            },
            "fallback_used": False,
        }

    def fake_browser_extract_text(_selector: str = "") -> dict:
        return {
            "ok": True,
            "action": "browser.extract_text",
            "data": {
                "page_url": expected_search_url,
                "page_url_truncated": False,
                "link_contexts": [
                    {
                        "href": "https://zh.wikipedia.org/wiki/超时空辉夜姬",
                        "text": "超时空辉夜姬 · 英文名称: Cho Kaguya Hime",
                    }
                ],
            },
            "fallback_used": False,
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.apple_music_play",
        fake_apple_music_play,
    )
    monkeypatch.setattr(
        "apps.shell.agent.tools.browser.open_url",
        fake_browser_open_url,
    )
    monkeypatch.setattr(
        "apps.shell.agent.tools.browser.extract_text",
        fake_browser_extract_text,
    )
    monkeypatch.setattr(
        "apps.shell.agent.tools.browser.close_target",
        lambda target_id: {
            "ok": True,
            "action": "browser.close_target",
            "data": {"target_id": target_id},
        },
    )

    try:
        result = _send_foreground_message(
            api,
            "Apple Music 播放超时空辉夜姬",
        )
        task = runtime.state.get_task(result["task_id"])
        run = service.get_run(result["run_id"])
        events = service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"]
        event_types = [event["event_type"] for event in events]

        assert result["ok"] is True
        assert result["status"] == "completed"
        assert task is not None and task.status is TaskStatus.COMPLETED
        assert play_calls == ["超时空辉夜姬", "Cho Kaguya Hime"]
        assert opened_urls == [expected_search_url]
        assert "Cho Kaguya Hime" in result["agent_task"]["summary"]
        assert "Chat Profile" not in result["agent_task"]["summary"]
        assert "agent.recovery.planned" in event_types
        assert "agent.recovery.completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.request.failed" not in event_types
    finally:
        service.close()
        store.close()
