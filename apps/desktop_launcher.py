"""Development launcher for the Electron desktop shell."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

NODE_VERSION = "v20.19.0"
MIN_NODE_VERSION = (20, 19, 0)
REQUIRED_FRONTEND_BINS = ("concurrently", "electron", "tsc", "vite")
FRONTEND_DEV_URL = "http://127.0.0.1:5174"
BRIDGE_SETTINGS_URL = "http://127.0.0.1:8420/ui/settings"


def _node_bin_dir() -> Path | None:
    nvm_root = Path(os.environ.get("NVM_DIR", Path.home() / ".nvm"))
    candidate = nvm_root / "versions" / "node" / NODE_VERSION / "bin"
    return candidate if (candidate / "npm").exists() else None


def _npm_executable(env: dict[str, str]) -> str:
    npm = shutil.which("npm", path=env.get("PATH"))
    if npm is None:
        raise SystemExit(
            "npm was not found. Install Node.js 20.19+ or run `nvm install 20.19.0`."
        )
    return npm


def _node_executable(env: dict[str, str]) -> str:
    node = shutil.which("node", path=env.get("PATH"))
    if node is None:
        raise SystemExit(
            "node was not found. Install Node.js 20.19+ or run `nvm install 20.19.0`."
        )
    return node


def _parse_node_version(value: str) -> tuple[int, int, int] | None:
    raw = value.strip().lstrip("v")
    parts = raw.split(".")
    if len(parts) < 2:
        return None
    try:
        major = int(parts[0])
        minor = int(parts[1])
        patch = int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        return None
    return major, minor, patch


def _node_version_supported(version: tuple[int, int, int]) -> bool:
    return version >= MIN_NODE_VERSION


def _ensure_node_version(env: dict[str, str]) -> None:
    node = _node_executable(env)
    result = subprocess.run(
        [node, "--version"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    version_text = (result.stdout or result.stderr).strip()
    version = _parse_node_version(version_text)
    if version is None or not _node_version_supported(version):
        raise SystemExit(
            "Node.js 20.19+ is required for the Electron frontend. "
            f"Current node version: {version_text or 'unknown'}. "
            "Run `source ~/.nvm/nvm.sh && nvm install 20.19.0 && nvm use 20.19.0`."
        )


def _has_frontend_bin(frontend_dir: Path, name: str) -> bool:
    bin_dir = frontend_dir / "node_modules" / ".bin"
    return (bin_dir / name).exists() or (bin_dir / f"{name}.cmd").exists()


def _frontend_dependencies_ready(frontend_dir: Path) -> bool:
    return all(_has_frontend_bin(frontend_dir, name) for name in REQUIRED_FRONTEND_BINS)


def _local_http_ready(url: str, *, timeout: float = 0.75) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError):
        return False


def _frontend_dev_server_ready() -> bool:
    return _local_http_ready(FRONTEND_DEV_URL)


def _bridge_server_ready() -> bool:
    return _local_http_ready(BRIDGE_SETTINGS_URL)


def _frontend_bin(frontend_dir: Path, name: str) -> Path:
    bin_dir = frontend_dir / "node_modules" / ".bin"
    if sys.platform.startswith("win"):
        candidate = bin_dir / f"{name}.cmd"
        if candidate.exists():
            return candidate
    return bin_dir / name


def _ensure_frontend_dependencies(project_root: Path, frontend_dir: Path, env: dict[str, str]) -> None:
    if _frontend_dependencies_ready(frontend_dir):
        return

    npm = _npm_executable(env)
    install_command = "ci" if (frontend_dir / "package-lock.json").exists() else "install"
    print(f"[desktop] Frontend dependencies missing; running npm {install_command}.")
    subprocess.run(
        [npm, "--prefix", str(frontend_dir), install_command],
        cwd=project_root,
        env=env,
        check=True,
    )


def _run_frontend_dev(project_root: Path, frontend_dir: Path, npm: str, env: dict[str, str]) -> None:
    try:
        subprocess.run(
            [npm, "--prefix", str(frontend_dir), "run", "dev"],
            cwd=project_root,
            env=env,
            check=True,
        )
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except subprocess.CalledProcessError as exc:
        if exc.returncode in {130, -2}:
            raise SystemExit(130) from None
        raise SystemExit(
            f"[desktop] Electron frontend exited with code {exc.returncode}. "
            "Check the logs above for the first failing process."
        ) from None


def _run_electron_against_existing_vite(
    project_root: Path,
    frontend_dir: Path,
    env: dict[str, str],
) -> None:
    try:
        subprocess.run(
            [str(_frontend_bin(frontend_dir, "tsc")), "-p", "tsconfig.electron.json"],
            cwd=frontend_dir,
            env=env,
            check=True,
        )
        subprocess.run(
            [str(_frontend_bin(frontend_dir, "electron")), "dist-electron/main.js"],
            cwd=frontend_dir,
            env=env,
            check=True,
        )
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except subprocess.CalledProcessError as exc:
        if exc.returncode in {130, -2}:
            raise SystemExit(130) from None
        raise SystemExit(
            f"[desktop] Electron app exited with code {exc.returncode}. "
            "Check the logs above for the first failing process."
        ) from None


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    frontend_dir = project_root / "apps" / "frontend"
    node_bin = _node_bin_dir()
    env = {**os.environ, "HERMES_YACHIYO_PYTHON": sys.executable}
    if node_bin is not None:
        env["PATH"] = f"{node_bin}{os.pathsep}{env.get('PATH', '')}"
    _ensure_node_version(env)
    npm = _npm_executable(env)
    _ensure_frontend_dependencies(project_root, frontend_dir, env)
    if _frontend_dev_server_ready():
        print(f"[desktop] Reusing existing frontend dev server at {FRONTEND_DEV_URL}.")
        if _bridge_server_ready():
            print("[desktop] Reusing existing Python Bridge at http://127.0.0.1:8420.")
            env["HERMES_YACHIYO_SKIP_BACKEND"] = "1"
        _run_electron_against_existing_vite(project_root, frontend_dir, env)
        return
    _run_frontend_dev(project_root, frontend_dir, npm, env)


if __name__ == "__main__":
    main()
