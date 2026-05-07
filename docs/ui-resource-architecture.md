# UI Resource Architecture

The desktop UI is now owned by Electron + React. `apps/shell/` remains as the
Python-side configuration, installer, resource, and UI data adapter layer; it
does not create desktop windows.

## Active Boundary

- New desktop UI work belongs in `apps/frontend/`.
- New Python-facing UI data belongs behind HTTP routes in `apps/bridge/routes/`.
- Shared local assets for backend data, avatars, and Live2D discovery remain in
  `apps/shell/assets.py` and `apps/shell/assets/`.
- Electron-native icons and packaging assets live under the repository-level
  `assets/` directory.
