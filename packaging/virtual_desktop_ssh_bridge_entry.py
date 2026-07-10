"""PyInstaller entry point for the host-side virtual desktop SSH bridge."""

import sys

from apps.shell.yachiyo_agent.virtual_desktop_ssh_bridge import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
