# Oha-Yachiyo Knowledge Base

## Product Definition

Oha-Yachiyo is a desktop-first local personal agent application built around the native execution stack in this repository.

It is not primarily a backend service. Its primary product form is a launchable local desktop app that can be packaged, started without external execution-kernel installation, and used through the same product task and chat contracts across all surfaces.

## System Split

- Oha-Yachiyo App: local Electron desktop shell.
- Oha-Yachiyo Core: AppState, TaskRunner, Task API, ChatSession, ChatStore, and ActivityStore.
- Native Agent Runtime: NativeAgentExecutor, NativeRunEngine, ModelProfileService, ToolBroker, approval coordination, RunRepository, and RunEvent replay.
- Local Capabilities: screenshots, active-window context, local files within workspace policy, manual TTS, proactive TTS, and Live2D shell behavior.
- Local Bridge/API: loopback-only desktop bridge for renderer and desktop surfaces.
- AstrBot plugin: optional QQ bridge integration.
- Hapi: existing external automation backend outside the Oha-Yachiyo runtime boundary.
- QQ: optional remote communication channel.

## Product Expectations

When launched locally, Oha-Yachiyo should support:

- window, bubble, and Live2D desktop surfaces
- configurable display mode
- shared chat/session/task state across surfaces
- model profiles for chat, image input, and voice-related integrations
- NativeRunEngine-backed task execution
- Agent Studio, Workflow, Run Detail, and approval UI
- proactive care, local screenshots, manual TTS, proactive TTS, Live2D, and notifications
- optional remote access through AstrBot bridge

## Three-Mode Product Shape

Oha-Yachiyo treats the desktop product as three parallel shell modes instead of one main window plus attached utilities:

- **Window Mode**: control center, dashboard, mode switch entry, settings entry, recent session/message overview.
- **Bubble Mode**: lightweight always-available floating chat shell with short input and recent reply summary.
- **Live2D Mode**: character chat shell with recent reply bubble, quick input, renderer-backed model loading, and preview fallback.
- **Chat Window**: shared full conversation space that all three modes can open.

All four surfaces must use the same ChatSession, TaskRunner, Task API, and NativeRunEngine-backed execution path. They must not fork independent assistant state.

## Runtime Layering

- **Product contract layer**: `apps/core` owns AppState, TaskRunner, Task API, ChatSession, ChatStore, and ActivityStore.
- **Execution boundary**: `apps/core/executor.py` maps product Tasks to NativeAgentExecutor.
- **Native execution layer**: `apps/shell/agent_runtime.py` owns NativeRunEngine, RunRepository, RunEvent, ToolBroker, approval handling, Workflow, Agent Studio, and TaskRunLink projections.
- **Mode shell layer**: desktop surfaces load Bubble, Live2D, and window modes from the same bridge payloads.
- **Mode settings layer**: `WindowModeConfig`, `BubbleModeConfig`, and `Live2DModeConfig` stay grouped by mode under `apps/shell/config.py`, with shared update/serialization in `apps/shell/mode_settings.py`.

Mode settings should stay grouped by mode instead of growing a single mixed settings object.

## Live2D Asset Packaging

- Large Live2D binaries are optional asset packs, not required source-tree assets.
- Default import location is `~/.oha-yachiyo/assets/live2d/`.
- Program code assets under `apps/shell/assets/` should stay lightweight: avatar, fallback preview, placeholder docs.
- Live2D mode must remain usable as a shell even when no model asset pack has been imported yet.

## Oha-Yachiyo Responsibilities

- local app runtime
- local configuration UI
- task list and task state
- Task to Run mapping
- chat/session persistence
- screenshots and active-window context
- local assistant behaviors
- controlled tool execution and approval UI
- risk tiers and workspace policy
- RunEvent replay and audit logs

## External Integration Responsibilities

AstrBot responsibilities:

- receive QQ messages
- route requests into the local bridge when enabled
- authz checks
- format responses for remote chat surfaces

Hapi responsibilities:

- external automation workflows outside the Oha-Yachiyo core
- project execution chains owned by their own service boundary
