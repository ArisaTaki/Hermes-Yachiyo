"""Bundled shell assets."""

from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path
from typing import Callable, Iterator

SHELL_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SHELL_DIR.parents[1]
ASSETS_DIR = SHELL_DIR / "assets"
DEFAULT_BUBBLE_AVATAR_PATH = ASSETS_DIR / "avatars" / "yachiyo-default.jpg"
PROGRAM_LIVE2D_ASSETS_DIR = ASSETS_DIR / "live2d"
LEGACY_BUNDLED_LIVE2D_MODEL_DIR = PROGRAM_LIVE2D_ASSETS_DIR / "yachiyo"
DEFAULT_LIVE2D_MODEL_DIR = Path.home() / ".hermes" / "yachiyo" / "assets" / "live2d"
DEFAULT_LIVE2D_PREVIEW_PATH = DEFAULT_BUBBLE_AVATAR_PATH
LIVE2D_RELEASES_URL = "https://github.com/ArisaTaki/Hermes-Yachiyo/releases"
TTS_RELEASES_URL = f"{LIVE2D_RELEASES_URL}/tag/tts-assets-yachiyo-gpt-sovits-v4"


def get_hermes_home_dir() -> Path:
    """Return Hermes home directory, honoring HERMES_HOME when set."""
    hermes_home = os.getenv("HERMES_HOME")
    if hermes_home:
        return Path(hermes_home).expanduser()
    return Path.home() / ".hermes"


def get_yachiyo_workspace_dir() -> Path:
    """Return Yachiyo user workspace directory."""
    return get_hermes_home_dir() / "yachiyo"


def get_user_live2d_assets_dir() -> Path:
    """Return the default user-scoped Live2D asset import directory."""
    return get_yachiyo_workspace_dir() / "assets" / "live2d"


def get_user_tts_assets_dir() -> Path:
    """Return the default user-scoped TTS voice preset import directory."""
    return get_yachiyo_workspace_dir() / "assets" / "tts"


def iter_live2d_candidate_dirs(root: str | Path | None = None) -> Iterator[Path]:
    """Yield candidate directories under the user asset root for auto discovery."""
    resolved_root = Path(root or get_user_live2d_assets_dir()).expanduser()
    if not resolved_root.exists() or not resolved_root.is_dir():
        return

    yield resolved_root
    for child in sorted(path for path in resolved_root.iterdir() if path.is_dir()):
        yield child


def find_default_live2d_model_dir(
    is_valid_dir: Callable[[Path], bool],
    root: str | Path | None = None,
) -> Path | None:
    """Find the first valid Live2D model directory in the user asset root."""
    for candidate in iter_live2d_candidate_dirs(root):
        if is_valid_dir(candidate):
            return candidate.resolve()
    return None


def file_uri(path: str | Path) -> str:
    """Return a browser-safe file URI for a local asset path."""
    return Path(path).expanduser().resolve().as_uri()


def data_uri(path: str | Path) -> str:
    """Embed a local asset as a browser-safe data URI."""
    asset_path = Path(path).expanduser().resolve()
    mime_type = mimetypes.guess_type(asset_path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(asset_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def project_display_path(path: str | Path) -> str:
    """Return a compact path for settings UI, relative to the project when possible."""
    resolved = Path(path).expanduser().resolve()
    try:
        return str(resolved.relative_to(PROJECT_DIR))
    except ValueError:
        try:
            return f"~/{resolved.relative_to(Path.home().resolve())}"
        except ValueError:
            return str(resolved)


def is_project_asset(path: str | Path) -> bool:
    """Whether a path points into the bundled shell assets directory."""
    resolved = Path(path).expanduser().resolve()
    try:
        resolved.relative_to(ASSETS_DIR)
        return True
    except ValueError:
        return False


def find_live2d_preview_path(model_path: str | Path) -> Path:
    """Find a bundled/static preview image for a Live2D model directory."""
    if not model_path:
        return DEFAULT_LIVE2D_PREVIEW_PATH
    root = Path(model_path).expanduser()
    patterns = (
        "*头像*.png",
        "*avatar*.png",
        "*preview*.png",
        "*thumbnail*.png",
        "*.png",
        "*.jpg",
        "*.jpeg",
    )
    if root.exists() and root.is_dir():
        for pattern in patterns:
            matches = sorted(p for p in root.glob(pattern) if p.is_file())
            if matches:
                return matches[0]
    if DEFAULT_LIVE2D_PREVIEW_PATH.exists():
        return DEFAULT_LIVE2D_PREVIEW_PATH
    return DEFAULT_BUBBLE_AVATAR_PATH
