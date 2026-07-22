from __future__ import annotations

import pytest

from apps.shell.agent.tools import desktop as desktop_mod


_RECEIPT_SEPARATOR = "\x1f"


def _run_music_control(
    monkeypatch: pytest.MonkeyPatch,
    *,
    action: str,
    stdout: str,
) -> tuple[dict, str]:
    scripts: list[str] = []

    def fake_osascript(script: str, args=None) -> dict:
        scripts.append(script)
        return {"ok": True, "stdout": stdout, "stderr": ""}

    monkeypatch.setattr(desktop_mod, "_desktop_platform", lambda: "macos")
    monkeypatch.setattr(desktop_mod, "_run_osascript", fake_osascript)
    return desktop_mod.apple_music_control(action), scripts[0]


def test_apple_music_next_verifies_database_id_change(monkeypatch) -> None:
    result, script = _run_music_control(
        monkeypatch,
        action="next",
        stdout=_RECEIPT_SEPARATOR.join(
            (
                "controlled-v2",
                "next",
                "playing",
                "101",
                "202",
                "",
                "",
                "After",
                "Artist",
            )
        ),
    )

    assert result["ok"] is True
    assert result["data"] == {
        "control": "next",
        "player_state": "playing",
        "track": "After",
        "artist": "Artist",
        "track_changed": True,
        "track_change_verified": True,
        "track_identity_source": "music_database_id",
        "before_track_id": "101",
        "after_track_id": "202",
        "track_id": "202",
    }
    assert "database ID of current track" in script
    assert script.index("set beforeIdentity") < script.index("next track")


def test_apple_music_previous_uses_stable_persistent_id_fallback(monkeypatch) -> None:
    result, _script = _run_music_control(
        monkeypatch,
        action="previous",
        stdout=_RECEIPT_SEPARATOR.join(
            (
                "controlled-v2",
                "previous",
                "playing",
                "",
                "",
                "AAAA1111",
                "BBBB2222",
                "Before",
                "Artist",
            )
        ),
    )

    assert result["data"]["track_changed"] is True
    assert result["data"]["track_change_verified"] is True
    assert result["data"]["track_identity_source"] == "music_persistent_id"
    assert result["data"]["before_track_id"] == "AAAA1111"
    assert result["data"]["after_track_id"] == "BBBB2222"


@pytest.mark.parametrize(
    ("before_database_id", "after_database_id"),
    (("101", "101"), ("", "")),
)
def test_apple_music_track_navigation_never_verifies_unchanged_or_missing_identity(
    monkeypatch,
    before_database_id: str,
    after_database_id: str,
) -> None:
    result, _script = _run_music_control(
        monkeypatch,
        action="next",
        stdout=_RECEIPT_SEPARATOR.join(
            (
                "controlled-v2",
                "next",
                "playing",
                before_database_id,
                after_database_id,
                "",
                "",
                "Same",
                "Artist",
            )
        ),
    )

    assert result["data"]["track_changed"] is False
    assert result["data"]["track_change_verified"] is False


def test_apple_music_track_navigation_rejects_conflicting_stable_id_evidence(
    monkeypatch,
) -> None:
    result, _script = _run_music_control(
        monkeypatch,
        action="next",
        stdout=_RECEIPT_SEPARATOR.join(
            (
                "controlled-v2",
                "next",
                "playing",
                "101",
                "202",
                "SAME-ID",
                "SAME-ID",
                "After",
                "Artist",
            )
        ),
    )

    assert result["data"]["track_changed"] is False
    assert result["data"]["track_change_verified"] is False
    assert result["data"]["track_identity_conflict"] is True
    assert result["data"]["before_track_id"] == ""
    assert result["data"]["after_track_id"] == ""


def test_apple_music_play_preserves_legacy_output_shape(monkeypatch) -> None:
    result, _script = _run_music_control(
        monkeypatch,
        action="play",
        stdout="controlled|play|playing|Song|Artist",
    )

    assert result == {
        "ok": True,
        "action": "media.apple_music_control",
        "summary": "Apple Music play executed",
        "data": {
            "control": "play",
            "player_state": "playing",
            "track": "Song",
            "artist": "Artist",
        },
        "permission_error": False,
        "fallback_used": False,
    }
