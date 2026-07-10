#!/usr/bin/env python3
"""Run the host-side SSH bridge for a macOS VM guest provider."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.shell.yachiyo_agent.virtual_desktop_ssh_bridge import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
