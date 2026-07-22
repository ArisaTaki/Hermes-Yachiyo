"""App build metadata preparation tests."""

from __future__ import annotations

import json

from scripts import prepare_app_build_metadata as metadata
from scripts.release_integrity import SourceTreeProvenance

SOURCE_TREE_FINGERPRINT = "sha256:" + "a" * 64


def test_build_metadata_derives_latest_url_and_short_commit():
    result = metadata.build_metadata(
        channel="stable",
        source_branch="main",
        version="1.2.3",
        commit="abcdef1234567890",
        build_number=42,
        run_number=42,
        repository="owner/repo",
        built_at="2026-06-12T00:00:00Z",
        dirty=False,
        source_tree_fingerprint=SOURCE_TREE_FINGERPRINT,
    )

    assert result == {
        "name": "Oha-Yachiyo",
        "channel": "stable",
        "branch": "main",
        "source_branch": "main",
        "version": "1.2.3",
        "base_version": "1.2.3",
        "commit": "abcdef1234567890",
        "short_commit": "abcdef1",
        "build_number": 42,
        "run_number": 42,
        "repository": "owner/repo",
        "latest_json_url": (
            "https://github.com/owner/repo/releases/download/"
            "main-latest/Oha-Yachiyo-main-latest.json"
        ),
        "built_at": "2026-06-12T00:00:00Z",
        "dirty": False,
        "source_tree_fingerprint": SOURCE_TREE_FINGERPRINT,
        "release_publishable": True,
    }


def test_build_metadata_uses_alpha_latest_branch():
    result = metadata.build_metadata(
        channel="alpha",
        source_branch="release/alpha-candidate",
        version="1.2.3",
        commit="1234567890abcdef",
        build_number=7,
        run_number=8,
        repository="owner/repo",
        built_at="2026-06-12T00:00:00Z",
        dirty=True,
        source_tree_fingerprint=SOURCE_TREE_FINGERPRINT,
    )

    assert result["branch"] == "alpha"
    assert result["dirty"] is True
    assert result["release_publishable"] is False
    assert result["latest_json_url"].endswith(
        "/alpha-latest/Oha-Yachiyo-alpha-latest.json"
    )


def test_main_writes_metadata_from_explicit_arguments(tmp_path, monkeypatch):
    output = tmp_path / "oha-yachiyo-build.json"
    monkeypatch.setattr(metadata, "read_product_version", lambda: "0.4.0")

    assert metadata.main(
        [
            "--output",
            str(output),
            "--channel",
            "experimental",
            "--source-branch",
            "phase-5/oha-yachiyo-runtime",
            "--commit",
            "b7c9cedd00000000000000000000000000000000",
            "--build-number",
            "0",
            "--run-number",
            "0",
            "--repository",
            "kuguya-AI-app-develop/Hermes-Yachiyo",
            "--built-at",
            "2026-06-12T08:00:00Z",
            "--source-tree-fingerprint",
            SOURCE_TREE_FINGERPRINT,
            "--source-dirty",
        ]
    ) == 0

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["channel"] == "experimental"
    assert result["branch"] == "oha-develop"
    assert result["source_branch"] == "phase-5/oha-yachiyo-runtime"
    assert result["version"] == "0.4.0"
    assert result["base_version"] == "0.4.0"
    assert result["commit"] == "b7c9cedd00000000000000000000000000000000"
    assert result["short_commit"] == "b7c9ced"
    assert result["dirty"] is True
    assert result["source_tree_fingerprint"] == SOURCE_TREE_FINGERPRINT
    assert result["release_publishable"] is False
    assert result["latest_json_url"].endswith(
        "/oha-develop-latest/Oha-Yachiyo-oha-develop-latest.json"
    )


def test_main_defaults_from_github_environment(tmp_path, monkeypatch):
    output = tmp_path / "oha-yachiyo-build.json"
    monkeypatch.setattr(metadata, "read_product_version", lambda: "0.4.0")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_SHA", "abc1234567890000000000000000000000000000")
    monkeypatch.setenv("GITHUB_RUN_NUMBER", "51")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")

    assert metadata.main(
        [
            "--output",
            str(output),
            "--built-at",
            "2026-06-12T09:00:00Z",
            "--source-tree-fingerprint",
            SOURCE_TREE_FINGERPRINT,
            "--source-clean",
        ]
    ) == 0

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["channel"] == "stable"
    assert result["branch"] == "main"
    assert result["source_branch"] == "main"
    assert result["build_number"] == 51
    assert result["run_number"] == 51
    assert result["repository"] == "owner/repo"


def test_main_captures_source_provenance_when_not_explicit(tmp_path, monkeypatch):
    output = tmp_path / "oha-yachiyo-build.json"
    commit = "f" * 40
    monkeypatch.setattr(metadata, "read_product_version", lambda: "0.4.0")
    monkeypatch.setenv("GITHUB_SHA", commit)
    monkeypatch.setattr(
        metadata,
        "capture_source_tree_provenance",
        lambda _root: SourceTreeProvenance(
            commit=commit,
            dirty=True,
            source_tree_fingerprint=SOURCE_TREE_FINGERPRINT,
        ),
    )

    assert metadata.main(["--output", str(output)]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["dirty"] is True
    assert result["source_tree_fingerprint"] == SOURCE_TREE_FINGERPRINT
    assert result["release_publishable"] is False
