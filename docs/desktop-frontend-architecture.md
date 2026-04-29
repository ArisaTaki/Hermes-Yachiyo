# Desktop Frontend Architecture

Hermes-Yachiyo now uses a fixed desktop-first split. React is only the
renderer layer; the product runtime must be Electron, not a standalone browser
tab:

- Electron owns the desktop shell, native window, and renderer lifecycle.
- React/Vite/TypeScript owns user-facing screens under `apps/frontend/`.
- Python runs as a headless runtime process under `apps/desktop_backend/`.
- FastAPI Bridge exposes local HTTP routes for the frontend and integrations.
- pywebview is not part of the active UI path.

## Process Model

1. `hermes-yachiyo` runs `apps.desktop_launcher:main`.
2. The launcher prefers nvm Node `v20.19.0`, installs frontend dependencies
  when the required `node_modules/.bin` tools are missing, then starts
  `npm --prefix apps/frontend run dev`. It passes the current Python
  interpreter through `HERMES_YACHIYO_PYTHON`. Before starting the frontend it
  validates that the selected `node` is at least 20.19.0, so Vite engine
  mismatches fail with an actionable message.
3. Electron starts `python -m apps.desktop_backend.app` as a child process.
4. The backend starts `HermesRuntime`, injects it into Bridge dependencies, and
   runs FastAPI on the configured local host/port.
5. The renderer reads the Bridge URL from Electron preload IPC or the `bridge`
   query parameter, then calls `/ui/*` endpoints over HTTP.

The development renderer uses fixed port `5174` with Vite strict port mode.
When `hermes-yachiyo` finds an existing Vite dev server on that port, it reuses
the server and starts Electron directly. If no Vite server is running and the
port is occupied by something else, startup should fail visibly instead of
silently moving Electron and Vite to different URLs.

## Frontend Workspace

- `apps/frontend/electron/main.ts`: Electron main process and Python backend
  process manager.
- `apps/frontend/electron/preload.cts`: CommonJS preload that exposes the narrow
  IPC surface to renderer.
- `apps/frontend/src/lib/bridge.ts`: typed fetch helpers for local HTTP Bridge.
- `apps/frontend/src/lib/view.ts`: hash-route helpers shared by renderer views.
- `apps/frontend/src/views/`: React screens for dashboard, chat, installer,
  launcher modes, and settings.
- `apps/frontend/src/styles/app.css`: renderer presentation layer.

The React general settings view now edits the core settings fields directly:
display mode, assistant persona/address, Bridge enabled/host/port, and tray
entry. It compares the loaded `/ui/settings` payload with local form state,
sends only changed keys to `/ui/settings`, then refreshes from the backend after
save so renderer state stays aligned with Python config persistence.

The React mode settings view also edits Bubble and Live2D mode config directly
instead of showing a JSON preview. It reads `/ui/modes/{mode}/settings`, maps the
mode config payload into controlled fields, submits only changed keys through
`/ui/settings`, then reloads the mode settings payload after save. Client-side
validation mirrors the Python mode-settings boundary for ranges and enum values,
while Python remains the source of truth for persistence and effect summaries.

Live2D resource operations are split by responsibility. Electron preload/main
owns native dialogs and OS actions: selecting a model directory, selecting a ZIP
archive, opening the default import directory, and opening the Releases page.
The Bridge owns resource validation/import through `/ui/live2d/model-path/prepare`
and `/ui/live2d/archive/import`. Those routes return a `live2d_mode.model_path`
draft change for the React form; they do not persist config by themselves, so
the final save still flows through `/ui/settings`.

The frontend targets Node `>=20.19.0`. Use nvm Node 20.19+ for installs and
builds. The Python launcher prefers `~/.nvm/versions/node/v20.19.0/bin` when it
exists, so `hermes-yachiyo` uses the same fixed Node line from a normal shell.

## Python Boundary

- `apps/desktop_backend/app.py` owns runtime startup and Bridge lifecycle.
- `apps/bridge/routes/ui.py` provides UI-specific HTTP routes for dashboard,
  settings, chat, launcher state, and mode configuration.
- The frontend must not call Python objects directly and must not depend on
  `window.pywebview.api`.
- High-risk capabilities remain disabled by default and should stay mediated by
  Bridge/runtime policy.

## Routing And Window Semantics

React renderer navigation uses hash routes while keeping the Bridge URL in the
normal query string. The main routes are `#/`, `#/chat`, `#/settings`,
`#/settings/bubble`, `#/settings/live2d`, `#/bubble`, and `#/live2d`. The helper
still accepts the old `?view=` query shape so older Electron `rendererUrl()`
callers and browser fallback paths keep working during migration.

Electron owns window identity. The main window is for dashboard, settings, and
installer views. Chat uses a dedicated singleton BrowserWindow; every
`openView('chat')` request focuses or reloads that one chat window instead of
loading ChatView into the main window or a launcher window. The chat window's
"main dashboard" action calls desktop-aware `openView('main')`, so it focuses
the main window rather than converting the chat window into a dashboard.

Bubble and Live2D windows are launcher-only surfaces. Electron intercepts
navigation and `window.open` requests from those mode windows; if a launcher
tries to navigate to chat, settings, or dashboard, Electron redirects the target
to the correct main/chat window and keeps the mode window on its launcher route.
This preserves the old pywebview behavior where clicking Bubble or Live2D opens
the shared chat surface instead of rendering a full app page inside a tiny
transparent window.

The Electron main process also mirrors the remaining legacy shell startup
contracts: the main window reads `window_mode.width` / `height`, honors
`app.start_minimized` at launch, optionally opens the Chat Window through
`window_mode.open_chat_on_start`, and creates an Electron-native tray menu when
`app.tray_enabled` is enabled.

The UI Bridge exposes legacy settings operations through HTTP routes rather than
duplicating business logic in React. Dashboard/settings renderer actions that
restart Bridge, recheck Hermes, open Hermes terminal commands, create/restore
backups, or preview/run uninstall delegate to `MainWindowAPI` via `/ui/*`.

The installer view uses an embedded terminal for guided macOS prerequisites,
Hermes Agent installation, and `hermes setup`. React renders the terminal with
xterm.js, while Electron owns the actual PTY through `node-pty` and exposes only
predefined installer tasks through preload IPC. The older native-terminal Bridge
routes remain as a fallback for browser/dev environments that do not expose the
Electron terminal IPC.

## Launcher Modes

Electron creates transparent BrowserWindows for Bubble and Live2D. Their React
route reads `/ui/launcher?mode=bubble|live2d`, acknowledges attention through
`/ui/launcher/ack`, and sends Live2D quick input through
`/ui/launcher/quick-message`. Window position is persisted through
`/ui/launcher/position`; Bubble snaps to the nearest screen edge in Electron
main before the persisted percent position is written back, while Live2D stores
absolute position and current window size. The backend reuses `ChatBridge` and
`LauncherNotificationTracker` so unread state, processing state, and latest
reply summaries follow the same semantics as the legacy pywebview launchers.

Bubble deliberately mirrors the legacy pywebview launcher contract: the backend
resolves the avatar as a data URI, exposes status/proactive fields, and the
renderer keeps the old avatar bubble shape, status dot classes, auto-hide
opacity behavior, and drag-vs-click threshold. Live2D currently mirrors the
legacy static shell: preview fallback, resource hint, default open behavior,
reply bubble, quick input, and renderer payload are present. The React launcher
also loads the legacy Pixi/Cubism runtime scripts through `/live2d/runtime`,
uses the protected `renderer.model_url` to create a Pixi canvas model, and falls
back to the preview image on dependency or model-load failure. Transparent
pointer pass-through is mediated by a narrow Electron IPC, but it is currently
experimental and disabled by default because the desktop launcher must remain
clickable and context-menu friendly first. The Live2D stage, character, resource
hint, reply bubble, and quick input are explicitly marked as Electron `no-drag`
regions so normal clicks are not swallowed by the transparent drag window. Set
`HERMES_YACHIYO_LIVE2D_POINTER_PASSTHROUGH=1` to test the alpha-mask passthrough
path. Electron now supplies global cursor position to the renderer for
window-outside mouse-follow, and the React launcher uses model manifest metadata
to trigger idle motion and first available expression on new replies. The
remaining Live2D parity work is real-model manual validation across multiple
resource packages and deeper per-model motion/expression tuning.

Launcher context menus are Electron-native and exposed through the narrow
preload IPC surface. Renderer code should request the menu; it should not build
native menu behavior with Python or pywebview APIs.

## Development Commands

```bash
source ~/.nvm/nvm.sh
nvm use 20.19.0
npm --prefix apps/frontend run build
hermes-yachiyo
```

Manual `npm --prefix apps/frontend install` is optional for development. The
Python launcher runs `npm ci` automatically when the frontend dependency tools
are missing and a lockfile is present.

During manual validation, `hermes-yachiyo` should show Vite on
`127.0.0.1:5174`, then Electron should start the Python backend and Bridge on
`127.0.0.1:8420`. A terminal exit code of 130 means the run was interrupted
with Ctrl-C; normal frontend child-process failures are reported with a concise
launcher message and the detailed process logs above it.

If `hermes-yachiyo` still opens the old pywebview shell after changing the
entry point, the active virtualenv has a stale console script. Run
`pip install -e .` from the repository root to regenerate it. The legacy shell
is intentionally reachable only through `hermes-yachiyo-legacy-pywebview`.

Backend-only development can use:

```bash
hermes-yachiyo-backend
```

## Packaging Direction

Packaging should treat the user's machine as clean: the released desktop app
must not depend on a globally installed Python, Node.js, or editable checkout.
The macOS target should be the first supported package, then Windows and Linux
can follow the same split with platform-specific launch wrappers.

The intended macOS packaging path is:

1. Build the React renderer with Node 20.19+.
2. Build the Python project as an installable wheel from the repository root.
3. Create a clean build virtualenv with `uv`, install the wheel plus locked
   runtime dependencies into that environment, and run backend smoke tests from
   that venv.
4. Freeze `apps.desktop_backend.app` into a self-contained backend executable
   under the Electron app's `Resources` directory. PyInstaller is the pragmatic
   first option; keeping a bundled venv is an acceptable fallback if hidden
   imports or native dependencies make freezing too brittle.
5. Package Electron with the compiled renderer, preload/main scripts, and the
   backend executable. In packaged mode, Electron should spawn the bundled
   backend path; in development it should keep spawning
   `python -m apps.desktop_backend.app`.
6. Unpack native Electron dependencies for runtime use, especially
   `node-pty` and its `prebuilds/*/spawn-helper` binary. The main process
   defensively restores the helper executable bit in development, but the
   packaged app should still mark native modules as unpacked from asar.

This keeps Python dependency resolution out of end-user startup, while still
letting development use the local editable virtualenv.
