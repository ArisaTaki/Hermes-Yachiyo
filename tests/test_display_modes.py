"""Display mode normalization tests."""

from apps.shell.config import AppConfig
from apps.shell.modes import DisplayMode, resolve_display_mode


def test_legacy_window_display_mode_resolves_to_bubble():
    config = AppConfig()
    config.display_mode = "window"  # type: ignore[assignment]

    assert resolve_display_mode(config) == DisplayMode.BUBBLE
