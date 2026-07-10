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
