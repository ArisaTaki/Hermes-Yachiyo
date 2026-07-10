"""Desktop app discovery matching regressions."""

from __future__ import annotations

from pathlib import Path

from apps.shell.agent.tools import desktop as desktop_tools


def test_installed_app_match_score_uses_localized_metadata_names() -> None:
    score = desktop_tools._installed_app_match_score(
        "音乐",
        "Music",
        {"display_names": ["Music", "音乐"], "names": {"music", "音乐"}},
    )

    assert score == 100
    match = desktop_tools._installed_app_name_match(
        "音乐",
        "Music",
        {"display_names": ["Music", "音乐"], "names": {"music", "音乐"}},
    )
    assert match == {
        "score": 100,
        "matched_name": "音乐",
        "matched_name_source": "bundle_metadata",
    }


def test_installed_app_match_score_uses_executable_metadata_names() -> None:
    score = desktop_tools._installed_app_match_score(
        "PixelForge",
        "Vendor Launcher",
        {
            "display_names": ["Vendor Launcher", "PixelForge"],
            "names": {"pixelforge", "vendor launcher helper"},
        },
    )

    assert score == 100


def test_installed_app_match_candidates_expose_match_evidence(monkeypatch) -> None:
    bundle_path = Path("/Applications/Music.app")

    monkeypatch.setattr(
        desktop_tools,
        "_iter_installed_app_bundles",
        lambda: [bundle_path],
    )
    monkeypatch.setattr(
        desktop_tools,
        "_app_bundle_metadata",
        lambda bundle: {
            "bundle_id": "com.apple.Music",
            "display_names": ["Music", "音乐"],
            "names": {"music", "音乐"},
            "schemes": {"music"},
            "documents": {"public.audio"},
        },
    )

    candidates = desktop_tools._installed_app_match_candidates("音乐")

    assert candidates[0]["name"] == "Music"
    assert candidates[0]["match_score"] == 100
    assert candidates[0]["matched_name"] == "音乐"
    assert candidates[0]["matched_name_source"] == "bundle_metadata"
    resolution = desktop_tools._app_discovery_resolution("音乐", candidates[0])
    assert resolution["app_resolution_matched_name"] == "音乐"
    assert resolution["app_resolution_matched_name_source"] == "bundle_metadata"


def test_installed_app_match_candidates_expand_low_confidence_aliases(monkeypatch) -> None:
    bundles = [
        Path("/System/Applications/Messages.app"),
        Path("/Applications/WeChat.app"),
        Path("/Applications/企业微信.app"),
    ]
    monkeypatch.setattr(desktop_tools, "_iter_installed_app_bundles", lambda: bundles)
    monkeypatch.setattr(desktop_tools, "_app_bundle_metadata", lambda _bundle: {})

    messages = desktop_tools._installed_app_match_candidates("短信")
    wechat = desktop_tools._installed_app_match_candidates("微信")

    assert messages[0]["name"] == "Messages"
    assert messages[0]["matched_query"] == "Messages"
    assert messages[0]["matched_query_source"] == "app_alias"
    assert wechat[0]["name"] == "WeChat"
    assert wechat[0]["match_score"] == 100


def test_installed_app_match_candidates_keep_high_confidence_original_name(monkeypatch) -> None:
    bundles = [
        Path("/Applications/WeChat.app"),
        Path("/Applications/企业微信.app"),
    ]
    monkeypatch.setattr(desktop_tools, "_iter_installed_app_bundles", lambda: bundles)
    monkeypatch.setattr(desktop_tools, "_app_bundle_metadata", lambda _bundle: {})

    candidates = desktop_tools._installed_app_match_candidates("企业微信")

    assert candidates[0]["name"] == "企业微信"
    assert candidates[0]["match_score"] == 100
    assert "matched_query_source" not in candidates[0]
