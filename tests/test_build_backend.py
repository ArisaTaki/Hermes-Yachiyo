"""Packaged backend build command tests."""

from __future__ import annotations

from scripts import build_backend as build_backend_mod


def test_build_backend_collects_certifi_ca_bundle(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(build_backend_mod, "DIST_DIR", tmp_path / "dist")
    monkeypatch.setattr(build_backend_mod, "BUILD_DIR", tmp_path / "build")

    def fake_run(command, *, cwd, check):
        commands.append((command, cwd, check))
        output_name = (
            "hermes-yachiyo-backend.exe"
            if build_backend_mod.os.name == "nt"
            else "hermes-yachiyo-backend"
        )
        (build_backend_mod.DIST_DIR / output_name).write_text("", encoding="utf-8")

    monkeypatch.setattr(build_backend_mod.subprocess, "run", fake_run)

    output_path = build_backend_mod.build_backend()

    assert output_path.exists()
    command, cwd, check = commands[0]
    assert cwd == build_backend_mod.ROOT
    assert check is True
    collect_index = command.index("--collect-data")
    assert command[collect_index + 1] == "certifi"
