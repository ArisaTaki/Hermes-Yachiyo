"""Public navigation helpers shared by Yachiyo Agent surfaces."""

from __future__ import annotations

from urllib.parse import quote


def studio_run_url(run_id: str | None, *, group_run_id: str | None = None) -> str | None:
    """Return the Agent Studio route for a runtime run."""
    clean_run_id = str(run_id or "").strip()
    if not clean_run_id:
        return None
    clean_group_run_id = str(group_run_id or "").strip()
    url = f"#/agents?run_id={quote(clean_run_id, safe='')}"
    if clean_group_run_id:
        url += f"&group_run={quote(clean_group_run_id, safe='')}"
    return url
