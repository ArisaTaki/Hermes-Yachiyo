"""PyInstaller entry point for the macOS virtual desktop guest provider."""

import sys

from apps.shell.agent.runtime.virtual_desktop_guest_provider import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
