#!/usr/bin/env python3
"""Run the authenticated desktop provider inside a macOS VM guest."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.shell.agent.runtime.virtual_desktop_guest_provider import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
