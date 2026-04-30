# UI Resource Architecture

This document records the legacy pywebview resource split. The active frontend
architecture is now documented in `docs/desktop-frontend-architecture.md`.

## Legacy Boundary

- The old `apps/shell/` path creates pywebview windows and exposes `js_api`
  objects.
- Legacy presentation assets live under `apps/shell/ui/` and are injected with
  `apps.shell.assets.inject_css()`.
- Existing exported HTML constants such as `_CHAT_HTML`, `_SETTINGS_HTML`,
  `_BUBBLE_HTML`, and `_LIVE2D_HTML` are retained only for compatibility while
  the Electron frontend takes over.

## Migration Direction

- Do not add new first-class UI surfaces to pywebview.
- New desktop UI work belongs in `apps/frontend/`.
- New Python-facing UI data belongs behind HTTP routes in `apps/bridge/routes/`.
- Keep `apps/shell/` as a legacy compatibility layer until its behavior has
  been replaced or deliberately retired.