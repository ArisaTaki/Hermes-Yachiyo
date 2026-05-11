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
- Settings page: prototype-style settings-layout with 720px centered container, four grouped sections (通用/外观与表现态/模型与连接/关于与维护), settings-card/settings-item/settings-toggle hover indicator strip, and unified SpecificModeSettingsView header/card/control style while preserving all existing settings save, backup, update, bridge restart, and uninstall behavior.
- Settings backup strategy restore: backup_auto_cleanup_enabled toggle and backup_retention_count input restored in the 关于与维护 section, preserving existing 1-100 validation and payload fields.
- Tools-all page: back link to 主控台, 8 tool cards with 220px min grid, real navigation preserved.
- Activity-all page: back link to 主控台, activities grouped by 今天/昨天/更早 with activity-day-label, fallback copy when no data.
- Global QA pre-fix: activity grouping now uses raw timestamp instead of parsing display text; relative times (e.g. "2 分钟前") correctly bucket into "今天"; all new Settings/Tools/Activity styles migrated to --hy-* design tokens; removed unused SettingsSelect component; save buttons now use type="submit" instead of document.querySelector hack.
- Diagnostics timestamp fix: activity-all diagnostics rows now include raw timestamp field for proper day grouping.
- CSS scope fix: hover indicator strip and hover background now scoped to `.settings-page .settings-item` to avoid affecting Workspace page.
- Activity dayKey fix: `dayKey()` now returns computed `todayKey` instead of literal "today" for relative times and missing timestamps.
- Settings split: GeneralSettingsView split into ReferenceSettingsHome (prototype layout + real data mirror, no savebar) and SystemSettingsView (real functionality at mode=system); MainView backup button navigates to settings?mode=system.
- Settings real data: ReferenceSettingsHome loads /ui/settings and /ui/hermes/config; connection test calls POST /ui/hermes/connection-test; update check reuses checkAppUpdate() with proper error display.
- Settings data mapping: hermesConfig uses model.provider, provider_options[] with id/label/api_key_configured, api_key.configured/display; provider select falls back to OpenAI/Anthropic/本地模型 when config fails.
- Tools-all/Activity-all header fix: removed English eyebrow, back link now outside header div, matches prototype structure.
- Activity-all visual fix: activity rows now use lightweight activity-item style instead of hy-activity-row card style.
- Black frame fix (completed by user): 4-point fix chain — main.tsx pre-adds desktop-mode-root/desktop-mode-body + inline transparent; app.css transparent chain for html/body/#root/launcher/canvas; LauncherView.tsx Live2D PIXI transparent flags + canvas fallback; main.ts setBackgroundColor('#00000000'). Verified: git diff --check, npm run build.
- Black frame hardening (current QA): desktop mode windows now start hidden until ready-to-show, repaint transparent background with rgba alpha, invalidate macOS transparent-window artifacts after load/resize, and Live2D Pixi explicitly clears WebGL with alpha 0 while capping the ticker at 30fps. This is intended to remove persistent black rectangles without changing launcher behavior.
- Tools-all prototype: card order changed to Bubble/Live2D/GPT/Resources/Workspace/Diagnostics/Provider/Main Console; subtitle changed to "所有可用的桌面工具和交互模式".
- Activity-all prototype: subtitle changed to "所有系统和交互活动的完整记录".
- Launcher/chat UX fixes: ordinary desktop-mode clicks no longer pass `session_id` or reload an already-open chat route; `showChatWindow()` reuses the existing main window when it is on a non-chat route by switching the hash in place; existing standalone chat windows are focused without `loadURL` when the target session is unchanged; long chat loads pre-sync assistant render state, wait for message layout height to settle, keep the scroll pinned to the bottom, then release the loading state.
- Chat wide-window responsive pass: at >=1500px the session column auto-expands from 280px to 360px unless the user has manually dragged it smaller; message rows actively expand across the pane, assistant/system bubbles fill the expanded row, user bubbles align farther right, composer padding expands with the viewport, and inline markdown code can wrap long local paths without forcing chat-level horizontal scroll.

## Current Focus

- Black frame fixed, Tools-all/Activity-all prototype aligned, launcher-to-chat route consolidation is in place, and chat wide-window responsiveness has a first pass. Next: manual QA for desktop-mode clicks from dashboard/chat/bubble/live2d, long-session loading smoothness, and chat layout at normal/wide window sizes.

## Remaining Major Slices

- Global QA: desktop and narrow widths, no white flash, no unwanted horizontal scroll, loading behavior with and without Bridge.

## Global QA Parity Checklist

### Shell / Titlebar / Sidebar
- [ ] Dark Electron window background matches prototype
- [ ] Traffic lights (close/minimize/maximize) positioned correctly
- [ ] Sidebar width 260px, scrolls independently
- [ ] Sidebar nav items have hover/active states
- [ ] Moonlight background particles animate correctly
- [ ] Shimmer sweep animation on load

### Loading
- [ ] Loading overlay shows early while Bridge prepares
- [ ] Logo breathes, text pulses, bar fills
- [ ] Loading hides smoothly when ready

### Dashboard
- [ ] KV hero section with role copy
- [ ] 3 status cards in grid
- [ ] Tool cards with status rows
- [ ] Activity list with staggered entry
- [ ] Navigation badges update

### Provider
- [ ] Settings sections for provider, TTS, RTX/GPU
- [ ] Real save/test behavior preserved

### Installer
- [ ] Four-step horizontal indicator
- [ ] Step status (completed/active/pending)
- [ ] Install, setup terminal, backup, config actions

### Chat
- [ ] Two-column layout (sessions + chat)
- [ ] Session search/list
- [ ] Message avatars/bubbles
- [ ] Typing dots animation
- [ ] Circular composer controls

### Bubble
- [ ] 320x480 preview
- [ ] Floating bubble
- [ ] Right-side feature pills

### Live2D
- [ ] 400x500 stage
- [ ] Import placeholder
- [ ] Right-side feature pills

### Resources
- [ ] Header with segmented tabs
- [ ] Stat cards
- [ ] Resource rows with hover glow
- [ ] Local tab filtering

### Workspace
- [ ] Settings sections for conversation, paths, files
- [ ] Hover glow on items
- [ ] Backup action works

### Diagnostics
- [ ] System check grid
- [ ] Command results display

### Settings
- [ ] 720px centered container
- [ ] Four grouped sections
- [ ] Settings cards with items
- [ ] Toggle switches work
- [ ] Save bar with pending count
- [ ] Hover indicator strip (scoped to settings-page)

### Tools-all
- [ ] Back link to 主控台
- [ ] 8 tool cards with 220px min grid
- [ ] Navigation works

### Activity-all
- [ ] Back link to 主控台
- [ ] Activities grouped by 今天/昨天/更早
- [ ] Day labels display correctly
- [ ] Fallback copy when no data

### Cross-cutting
- [ ] No horizontal scroll at 1440x900
- [ ] No horizontal scroll at 390x844
- [ ] No white flash on route change
- [ ] Long text doesn't break layout
- [ ] Buttons don't overflow

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
- `npm run build` passes after the Settings page slice. Vite still emits only the known large chunk warning.
- `npm run build` passes after the Settings backup restore + tools-all/activity-all slices. Vite still emits only the known large chunk warning.
- `npm run build` passes after the Global QA pre-fix slice. Vite still emits only the known large chunk warning.
- `npm run build` passes after the Prototype Parity QA slice. Vite still emits only the known large chunk warning.
- `npm run build` passes after the Settings final 1:1 slice. Vite still emits only the known large chunk warning.
- `npm run build` passes after the Settings split slice. Vite still emits only the known large chunk warning.
- `npm run build` passes after the Settings real data slice. Vite still emits only the known large chunk warning.
- `npm run build` passes after the Settings data mapping fix slice. Vite still emits only the known large chunk warning.
- `npm --prefix apps/frontend run build` passes after the launcher/chat UX fix slice. Vite still emits only the known large chunk warning.
- `npm --prefix apps/frontend run build` passes after the chat wide-window responsive slice. Vite still emits only the known large chunk warning.
- `npm --prefix apps/frontend run build` passes after the Python capability backfill slice. Vite still emits only the known large chunk warning.

## Notes For Next Agent

- The branch is intentionally experimental and not ready to merge.
- Avoid reverting existing dirty files in `docs/open-design`; the new `moxqc2d6-*` files are the active references.
- Keep updates incremental. After each slice, update this file with completed items, caveats, and validation.
- Settings page strategy: default `#/settings` is prototype layout + real data mirror (no savebar); real save at `#/settings?mode=system`; provider save at `#/provider`.
- Default page controls: language/theme/fontSize/animations use local draft state; tray toggle navigates to mode=system; provider select shows real options but changes only local draft; assistant Prompt card now saves through `/assistant/profile`.
- Real data sources: `/ui/settings` for app.version/tray_enabled; `/assistant/profile` and `PATCH /assistant/profile` for assistant Prompt; `/ui/hermes/config` for text/Vision model config; `/ui/hermes/connection-test` and `/ui/hermes/image-connection-test` for connection tests; `checkAppUpdate()` for update check.
- Python capability backfill slice added visible entries for assistant Prompt, Vision config/testing, proactive observation settings/testing, runtime status, tasks, assistant intent, local probes, Hermes environment, and real Workspace/backup links. It intentionally does not add fake import/export/clear conversation actions because no Python API exists yet.
