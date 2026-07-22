from __future__ import annotations

from pathlib import Path

import subprocess

from scripts import smoke_installed_apple_music_search as smoke


def _verified_primer() -> dict:
    return {
        "ok": True,
        "verified": True,
        "primer": "The Beatles",
        "query": "smoke query",
        "result_marker": True,
        "search_query_identity_verified": False,
        "query_match": True,
        "result_fingerprint": "primer-results",
    }


def _verified_response(*, changed_from_primer: bool = True) -> dict:
    return {
        "ok": True,
        "committed": True,
        "task_id": "task-music-smoke",
        "run_id": "run-music-smoke",
        "agent_task": {
            "status": "completed",
            "tool_calls": [
                {
                    "tool_name": "media.apple_music_play",
                    "status": "completed",
                    "output_preview": {
                        "ok": True,
                        "data": {
                            "search_opened": True,
                            "search_query_verified": True,
                            "search_query_identity_verified": True,
                            "search_baseline_result_marker": True,
                            "search_baseline_query_match": False,
                            "search_result_changed_from_nonmatching_baseline": (
                                changed_from_primer
                            ),
                            "search_baseline_fingerprint": "primer-results",
                            "search_result_fingerprint": (
                                "target-results"
                                if changed_from_primer
                                else "primer-results"
                            ),
                            "focus_strategy": "electron_native_bridge",
                            "focus_verified": True,
                            "focus_frontmost_app": "Music",
                            "electron_native_focus_verified": True,
                            "foreground_verified": True,
                        },
                        "fallback_result": {
                            "ok": True,
                            "data": {
                                "result_fingerprint": (
                                    "target-results"
                                    if changed_from_primer
                                    else "primer-results"
                                ),
                            },
                            "fallback_result": {
                                "baseline_evidence": {
                                    "ok": True,
                                    "data": {
                                        "result_marker": True,
                                        "query_match": False,
                                        "search_query_identity_value": "",
                                        "fingerprint": "primer-results",
                                    },
                                },
                                "focus": {
                                    "ok": True,
                                    "data": {
                                        "focus_strategy": "electron_native_bridge",
                                        "focus_verified": True,
                                        "frontmost_app": "Music",
                                    },
                                }
                            },
                        },
                    },
                }
            ],
        },
    }


def test_installed_music_smoke_requires_search_and_electron_focus_receipts() -> None:
    result = smoke.assess_search_response(
        _verified_response(),
        query="smoke query",
        primer_evidence=_verified_primer(),
    )

    assert result["ok"] is True
    assert all(result["checks"].values())
    assert result["evidence"]["focus_strategy"] == "electron_native_bridge"
    assert result["evidence"]["frontmost_app"] == "Music"


def test_installed_music_smoke_rejects_auth_status_only_evidence() -> None:
    result = smoke.assess_search_response(
        {"ok": True, "committed": True},
        query="smoke query",
        primer_evidence=_verified_primer(),
    )

    assert result["ok"] is False
    assert result["checks"]["music_tool_selected"] is False
    assert result["checks"]["search_fallback_verified"] is False
    assert result["checks"]["electron_native_focus_verified"] is False


def test_installed_music_smoke_rejects_stale_identity_without_primer_change() -> None:
    result = smoke.assess_search_response(
        _verified_response(changed_from_primer=False),
        query="smoke query",
        primer_evidence=_verified_primer(),
    )

    assert result["ok"] is False
    assert result["checks"]["causal_query_evidence_verified"] is False


def test_installed_music_smoke_accepts_dynamic_nonmatching_baseline_fingerprint() -> None:
    response = _verified_response()
    data = response["agent_task"]["tool_calls"][0]["output_preview"]["data"]
    data["search_baseline_fingerprint"] = "same-primer-page-after-dynamic-refresh"

    result = smoke.assess_search_response(
        response,
        query="smoke query",
        primer_evidence=_verified_primer(),
    )

    assert result["ok"] is True
    assert result["checks"]["runtime_baseline_matches_verified_primer"] is True
    assert result["checks"]["causal_query_evidence_verified"] is True


def test_installed_music_smoke_rejects_runtime_baseline_matching_target() -> None:
    response = _verified_response()
    data = response["agent_task"]["tool_calls"][0]["output_preview"]["data"]
    data["search_baseline_query_match"] = True

    result = smoke.assess_search_response(
        response,
        query="smoke query",
        primer_evidence=_verified_primer(),
    )

    assert result["ok"] is False
    assert result["checks"]["runtime_baseline_matches_verified_primer"] is False
    assert result["checks"]["causal_query_evidence_verified"] is False


def test_installed_music_smoke_verifies_nonmatching_primer_before_target(
    monkeypatch,
) -> None:
    now = 0.0
    evidence_calls: list[tuple[str, float]] = []
    observations = iter(
        [
            {
                "ok": True,
                "data": {
                    "result_marker": True,
                    "query_match": False,
                    "search_query_identity_verified": False,
                    "fingerprint": "old-results",
                },
            },
            {
                "ok": True,
                "data": {
                    "result_marker": True,
                    "query_match": True,
                    "search_query_identity_verified": False,
                    "fingerprint": "primer-results",
                },
            },
        ]
    )

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    def evidence(query: str, *, timeout_seconds: float) -> dict:
        evidence_calls.append((query, timeout_seconds))
        return next(observations)

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, "", ""),
    )
    monkeypatch.setattr(smoke.time, "monotonic", monotonic)
    monkeypatch.setattr(smoke.time, "sleep", sleep)
    monkeypatch.setattr(smoke, "_music_search_evidence", evidence, raising=False)

    result = smoke._prime_nonmatching_music_search("smoke query")

    assert result["verified"] is True
    assert result["search_query_identity_verified"] is False
    assert result["query_match"] is True
    assert result["result_fingerprint"] == "primer-results"
    assert [query for query, _timeout in evidence_calls] == [
        "The Beatles",
        "The Beatles",
    ]
    assert 8.0 <= evidence_calls[0][1] <= 10.0
    assert evidence_calls[1][1] <= evidence_calls[0][1]


def test_installed_music_smoke_launches_app_with_private_bridge_session(
    monkeypatch,
    tmp_path,
) -> None:
    app_path = tmp_path / "Oha-Yachiyo.app"
    executable = app_path / "Contents" / "MacOS" / "Oha-Yachiyo"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    executable.chmod(0o755)
    popen_calls: list[dict] = []
    request_calls: list[dict] = []

    class FakeProcess:
        pid = 32123

        def poll(self):
            return None

    def fake_popen(command, **kwargs):
        popen_calls.append({"command": command, **kwargs})
        return FakeProcess()

    def fake_request(bridge_url, route, **kwargs):
        request_calls.append({"bridge_url": bridge_url, "route": route, **kwargs})
        return _verified_response()

    monkeypatch.setattr(smoke.sys, "platform", "darwin")
    monkeypatch.setattr(smoke, "_allocate_loopback_port", lambda: 49321)
    monkeypatch.setattr(smoke.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        smoke,
        "_wait_for_status",
        lambda *_args, **_kwargs: {
            "service": "oha-yachiyo",
            "build_metadata": {"version": "0.4.0"},
        },
    )
    monkeypatch.setattr(
        smoke,
        "_prime_nonmatching_music_search",
        lambda query: {**_verified_primer(), "query": query},
    )
    monkeypatch.setattr(smoke, "_request_json", fake_request)
    monkeypatch.setattr(smoke, "_terminate_process", lambda _process: None)

    result = smoke.run_smoke(app_path=Path(app_path), query="smoke query")

    assert result["ok"] is True
    assert popen_calls[0]["command"] == [str(executable.resolve())]
    env = popen_calls[0]["env"]
    assert env["OHA_YACHIYO_BRIDGE_URL"] == "http://127.0.0.1:49321"
    assert env["OHA_YACHIYO_BRIDGE_TOKEN"]
    assert env["OHA_YACHIYO_BRIDGE_TOKEN"] not in str(result)
    assert request_calls[0]["route"] == "/ui/chat/messages"
    assert request_calls[0]["token"] == env["OHA_YACHIYO_BRIDGE_TOKEN"]
