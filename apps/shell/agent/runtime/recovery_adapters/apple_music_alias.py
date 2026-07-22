"""Compatibility exports for the application-agnostic entity-alias adapter."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from apps.shell.agent.runtime.recovery_adapters.entity_alias import (
    EntityAliasRecoveryAdapter,
    _entity_alias_evidence,
    _entity_alias_identity_url,
    _entity_alias_is_supported_by_evidence,
    _entity_alias_recovery_prompt,
    _entity_alias_search_page_is_expected,
)

# Keep the historical class import as a true alias. Registering both names can
# therefore never create two competing adapters for the same recovery action.
AppleMusicAliasRecoveryAdapter = EntityAliasRecoveryAdapter


def _legacy_search_query(original_query: str) -> str:
    return f"{str(original_query or '').strip()} Apple Music English title"


def _apple_music_alias_search_page_is_expected(
    page_url: Any,
    *,
    original_query: str,
) -> bool:
    return _entity_alias_search_page_is_expected(
        page_url,
        expected_search_query=_legacy_search_query(original_query),
    )


def _apple_music_alias_identity_url(value: Any) -> str:
    return _entity_alias_identity_url(value)


def _apple_music_alias_evidence(
    result: Mapping[str, Any],
    *,
    original_query: str,
) -> tuple[str, list[dict[str, str]]]:
    return _entity_alias_evidence(
        result,
        original_query=original_query,
        expected_search_query=_legacy_search_query(original_query),
    )


def _apple_music_alias_recovery_prompt(
    original_query: str,
    evidence_text: str,
) -> str:
    return _entity_alias_recovery_prompt(original_query, evidence_text)


def _apple_music_alias_is_supported_by_evidence(
    alias: str,
    *,
    original_query: str,
    trusted_records: Iterable[Mapping[str, Any]],
) -> bool:
    return _entity_alias_is_supported_by_evidence(
        alias,
        original_query=original_query,
        trusted_records=trusted_records,
    )


__all__ = [
    "AppleMusicAliasRecoveryAdapter",
    "_apple_music_alias_evidence",
    "_apple_music_alias_identity_url",
    "_apple_music_alias_is_supported_by_evidence",
]
