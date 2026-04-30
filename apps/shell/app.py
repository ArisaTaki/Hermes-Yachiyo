"""Compatibility import path for the Electron desktop launcher."""

from __future__ import annotations

def main() -> None:
    from apps.desktop_launcher import main as launch_electron

    launch_electron()


if __name__ == "__main__":
    main()
