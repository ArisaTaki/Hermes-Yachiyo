#!/usr/bin/env python3
"""Run the supervised desktop-control loopback provider."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.shell.agent.runtime.controlled_desktop_provider import main


if __name__ == "__main__":
    raise SystemExit(main())
