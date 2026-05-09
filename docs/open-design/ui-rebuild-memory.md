# Hermes Yachiyo UI Rebuild Memory

> This file records the open-design UI reconstruction progress so work can continue from another machine.

## Ground Rules

- Source of truth: `docs/open-design/moxqc2d6-design-reference.html`.
- Supporting spec: `docs/open-design/moxqc2d6-hermes-yachiyo-codex-spec.md`.
- Visual assets: `docs/open-design/logo.png`, `docs/open-design/bg-reference.png`.
- Priority: one-to-one visual, motion, and interaction fidelity to the prototype HTML.
- Scope: frontend reconstruction only. Do not change backend behavior, Bridge API contracts, model configuration semantics, or desktop mode functionality.
- Existing functions must keep working. Prefer styling, layout, and wrapper changes over business logic changes.

## Completed Slices

- Open-design shell: dark Electron window background, titlebar, sidebar, moonlight background, particles, shimmer sweep, route shell.
- Startup loading: opens early while Bridge prepares, uses prototype-style splash, no longer completes early before Bridge is ready.
- Dashboard: prototype-style KV hero, role copy, status cards, tool cards with status rows, activity list, staggered entry.
- Bubble mode: prototype-style 320x480 bubble preview, floating bubble, right-side feature pills.
- Live2D mode: prototype-style 400x500 stage, import placeholder, right-side feature pills.
- Tweaks panel: accent swatches, particle density, moonlight intensity, animation speed, font size, particle toggle, glow toggle.
- Toasts: prototype-style temporary notifications for shell actions.
- Diagnostics: system check grid added and shell overflow fixed.
- Provider: prototype-style settings sections for provider, TTS, and RTX/GPU optimization while preserving real save/test behavior.
- Installer: prototype-style four-step horizontal indicator and more prototype-aligned initializer layout while preserving install, setup terminal, backup, config, and workspace actions.
- Chat page: prototype-style two-column layout, session search/list, chat header, message avatars/bubbles, typing dots, and circular composer controls while preserving existing sessions, send, stop, delete, copy, and image attachment behavior.
- Resources page: prototype-style header, segmented category tabs, stat cards, resource rows, hover glow, and local tab filtering while preserving existing Live2D/TTS resource data reads and navigation actions.
- Window sizing fix: chat windows opened from desktop presentation modes now use a main-window-sized layout and existing old small chat windows are expanded before showing, preventing open-design shell compression.
- Workspace page: prototype-style settings sections for conversation actions, workspace paths, project file rows, hover glow, and backup action while preserving existing workspace/open-path/backup endpoints. Export/import/clear are intentionally status-only placeholders because no safe existing frontend behavior was available for them in this slice.

## Current Focus

- Next slice: Settings page. Align grouped cards, toggles/selects, hover indicator strip, and status copy with the prototype while keeping current settings behavior intact.

## Remaining Major Slices

- Settings page: grouped cards, toggles/selects, hover indicator strip.
- Tools-all and activity-all: align full list spacing, icons, statuses, and activity day labels.
- Global QA: desktop and narrow widths, no white flash, no unwanted horizontal scroll, loading behavior with and without Bridge.

## Verification History

- `npm run build` passes as of the Dashboard/Bubble/Live2D/Tweaks slice. Vite emits only the known large chunk warning.
- Browser smoke test passed with a temporary mock Bridge for Dashboard, Bubble, Live2D, Tweaks, and loading-ready behavior.
- `npm run build` passes after the Installer/Provider slice. Vite still emits only the known large chunk warning.
- Browser smoke test passed with a temporary mock Bridge for Provider settings cards and Installer step/status/config panels.
- `npm run build` passes after the Chat page slice. Vite still emits only the known large chunk warning.
- Browser smoke test passed with a temporary mock Bridge for Chat: 3 sessions, 5 messages, search field, composer, send button enabled state, and no console errors.
- `npm run build` passes after the Resources page slice. Vite still emits only the known large chunk warning.
- Browser smoke test passed with a temporary mock Bridge for Resources: 5 tabs, 3 stat cards, Live2D tab filters to 2 rows, and no console errors.
- `npm run build` passes after the presentation-mode chat window sizing fix. Vite still emits only the known large chunk warning.
- `npm run build` passes after the Workspace page slice. Vite still emits only the known large chunk warning.
- Browser smoke test passed with a temporary mock Bridge for Workspace: 3 settings sections, 2 cards, 6 file rows, backup action refreshes the latest backup path, and no console errors.

## Notes For Next Agent

- The branch is intentionally experimental and not ready to merge.
- Avoid reverting existing dirty files in `docs/open-design`; the new `moxqc2d6-*` files are the active references.
- Keep updates incremental. After each slice, update this file with completed items, caveats, and validation.
