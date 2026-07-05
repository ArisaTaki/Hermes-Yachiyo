"""Desktop app discovery matching regressions."""

from __future__ import annotations

from apps.shell.agent.tools import desktop as desktop_tools


def test_installed_app_match_score_uses_localized_metadata_names() -> None:
    score = desktop_tools._installed_app_match_score(
        "音乐",
        "Music",
        {"names": {"music", "音乐", "Music"}},
    )

    assert score == 100


def test_installed_app_match_score_uses_executable_metadata_names() -> None:
    score = desktop_tools._installed_app_match_score(
        "PixelForge",
        "Vendor Launcher",
        {"names": {"PixelForge", "Vendor Launcher Helper"}},
    )

    assert score == 100
