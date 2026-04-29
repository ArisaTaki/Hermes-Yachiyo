# Hermes-Yachiyo Knowledge Base

## Product definition

Hermes-Yachiyo is a desktop-first local personal agent application built around Hermes Agent.

It is not primarily a backend service.
Its primary product form should be a launchable local desktop app that can later be packaged and distributed.

## System split

- Hermes-Yachiyo App: local desktop application shell
- Hermes-Yachiyo Core: embedded runtime around Hermes Agent
- Hermes-Yachiyo Local Capabilities: screenshots, active-window, local machine integrations
- Hermes-Yachiyo Local Bridge/API: optional internal API for UI and AstrBot integration
- AstrBot plugin: QQ bridge
- Hapi: existing Codex execution backend
- QQ: remote communication channel

## Product expectations

When launched locally, Hermes-Yachiyo should eventually support:

- tray or window entry
- configurable display mode
- bubble mode
- Live2D mode with renderer-backed model loading when assets are available
- settings page or WebUI
- local runtime execution
- optional remote access through AstrBot bridge

## Three-mode product shape

Hermes-Yachiyo now treats the desktop product as three parallel shell modes instead of one main window plus attached utilities:

- **Window Mode**: control center, dashboard, mode switch entry, settings entry, recent session/message overview
- **Bubble Mode**: lightweight always-available floating chat shell with short input and recent reply summary
- **Live2D Mode**: character chat shell with recent reply bubble, quick input, renderer-backed model loading, and preview fallback
- **Chat Window**: shared full conversation space that all three modes can open

All four surfaces must use the same chat/session/task runtime and must not fork independent assistant state.

## Shell layering

- **shared core layer**: `apps/core` owns `ChatSession`, `ChatStore`, `TaskRunner`, `Executor`, Hermes runtime state
- **mode shell layer**: `apps/shell/modes/window.py`, `bubble.py`, `live2d.py`
- **mode settings layer**: `WindowModeConfig`, `BubbleModeConfig`, `Live2DModeConfig` under `apps/shell/config.py`, with shared update/serialization in `apps/shell/mode_settings.py`

Mode settings should stay grouped by mode instead of growing a single mixed settings object.

## Live2D asset packaging

- Large Live2D binaries are optional asset packs, not required source-tree assets.
- Default import location is `~/.hermes/yachiyo/assets/live2d/`.
- Program code assets under `apps/shell/assets/` should stay lightweight: avatar, fallback preview, placeholder docs.
- Live2D mode must remain usable as a shell even when no model asset pack has been imported yet.

## Hermes-Yachiyo responsibilities

- local app runtime
- local configuration UI
- status queries
- task list and task state
- screenshot
- active-window query
- local assistant behaviors
- risk tiers
- audit logs

## AstrBot responsibilities

- receive QQ messages
- route requests
- authz checks
- format responses

## Hapi responsibilities

- Codex CLI workflows
- coding/project writing execution chain
