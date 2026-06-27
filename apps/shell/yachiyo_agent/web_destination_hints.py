"""Compatibility web-destination hints for planner execution.

The planner should prefer browser discovery and direct URL handling when
available. This module keeps legacy known-site normalization behind a single
boundary until web destination resolution can be replaced by discovered or
model-planned browser targets.
"""

from __future__ import annotations

from apps.shell.agent.runtime.web_destinations import (
    known_web_destination_search_url,
    known_web_destination_url_hint,
)


def legacy_known_web_destination_url_hint(value: str) -> str:
    return known_web_destination_url_hint(value)


def legacy_known_web_destination_search_url(site_name: str, query: str) -> str:
    return known_web_destination_search_url(site_name, query)
