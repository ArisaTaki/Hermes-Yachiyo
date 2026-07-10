from __future__ import annotations

from scripts import build_virtual_desktop_guest as builder


def test_build_virtual_desktop_guest_uses_isolated_pyinstaller_output(
    monkeypatch,
    tmp_path,
) -> None:
    commands = []
    monkeypatch.setattr(builder, "DIST_DIR", tmp_path / "dist")
    monkeypatch.setattr(builder, "BUILD_DIR", tmp_path / "build")

    def fake_run(command, *, cwd, check):
        commands.append((command, cwd, check))
        output = builder.DIST_DIR / builder.OUTPUT_NAME
        output.write_text("provider", encoding="utf-8")

    monkeypatch.setattr(builder.subprocess, "run", fake_run)

    output = builder.build_virtual_desktop_guest(clean=True)

    assert output == builder.DIST_DIR / builder.OUTPUT_NAME
    assert output.exists()
    command, cwd, check = commands[0]
    assert cwd == builder.ROOT
    assert check is True
    assert "--onefile" in command
    assert "oha-yachiyo-desktop-provider" in command
    assert str(builder.ENTRYPOINT) == command[-1]
    assert "fastapi" in command
    assert "uvicorn" in command


def test_build_virtual_desktop_bridge_uses_independent_entrypoint(
    monkeypatch,
    tmp_path,
) -> None:
    commands = []
    monkeypatch.setattr(builder, "DIST_DIR", tmp_path / "dist")
    monkeypatch.setattr(builder, "BRIDGE_BUILD_DIR", tmp_path / "bridge-build")

    def fake_run(command, *, cwd, check):
        commands.append((command, cwd, check))
        output = builder.DIST_DIR / builder.BRIDGE_OUTPUT_NAME
        output.write_text("bridge", encoding="utf-8")

    monkeypatch.setattr(builder.subprocess, "run", fake_run)

    output = builder.build_virtual_desktop_ssh_bridge(clean=True)

    assert output == builder.DIST_DIR / builder.BRIDGE_OUTPUT_NAME
    command, cwd, check = commands[0]
    assert cwd == builder.ROOT
    assert check is True
    assert "oha-yachiyo-virtual-desktop-bridge" in command
    assert str(builder.BRIDGE_ENTRYPOINT) == command[-1]
