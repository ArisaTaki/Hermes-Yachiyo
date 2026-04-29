# UI Resource Architecture

Hermes-Yachiyo remains a desktop-first local application. The UI runs inside
pywebview windows, while Python owns runtime orchestration, native window
management, settings persistence, and local APIs.

## Current Boundary

- Python modules create pywebview windows and expose `js_api` objects.
- UI presentation assets live under `apps/shell/ui/`.
- CSS is loaded through `apps.shell.assets.inject_css()` and injected into the
  existing HTML constants at import time.
- Existing exported HTML constants such as `_CHAT_HTML`, `_SETTINGS_HTML`,
  `_BUBBLE_HTML`, and `_LIVE2D_HTML` are kept for compatibility with tests and
  current window creation code.
- `pyproject.toml` includes `apps.shell.ui` package data so bundled CSS is
  available in editable installs and packaged wheels.

## Recommended Next Phase

Move full HTML/JS pages into `apps/shell/ui/templates/` one window at a time:

1. Keep the existing Python constant names as compatibility aliases.
2. Load template text from `apps/shell/ui/templates/*.html`.
3. Keep runtime substitutions explicit, for example `{{HOST}}`, `{{PORT}}`,
   `{{AVATAR_URL}}`, and Live2D runtime script placeholders.
4. Keep pywebview `js_api` methods in Python; do not move runtime logic into
   browser-side code.
5. Update tests to assert rendered templates rather than Python inline strings
   once the compatibility layer is stable.

This gives the project a front-end/back-end style boundary without turning the
desktop app into a backend-first service.