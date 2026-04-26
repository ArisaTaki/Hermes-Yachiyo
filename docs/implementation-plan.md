# Hermes-Yachiyo Implementation Plan

## Milestone 0

- scaffold repo
- add docs
- add protocol package
- add empty core service
- add AstrBot plugin skeleton

## Milestone 1

- task enums
- request/response schemas
- error schemas
- audit event schemas

## Milestone 2

- GET /status
- GET /tasks
- POST /tasks
- POST /tasks/{task_id}/cancel

## Milestone 3

- screenshot adapter
- active window adapter

## Milestone 4

- AstrBot bridge skeleton
- /y status
- /y tasks
- /y screen
- /y window
- /y do
- /y codex -> Hapi

## Milestone 55

- mode-first shell architecture refactor
- add WindowModeConfig / BubbleModeConfig / Live2DModeConfig
- keep Chat Window as shared full conversation surface
- make Window Mode a dashboard/control center instead of a chat container
- upgrade Bubble to lightweight full mode with summary + quick input + open chat/settings
- upgrade Live2D to character chat shell with reply bubble + quick input + renderer placeholders
- centralize mode settings serialization/update logic

## Milestone 59

- decouple Live2D large asset packs from the source repository
- download Live2D asset packs from GitHub Releases instead of requiring bundled binaries
- prefer `~/.hermes/yachiyo/assets/live2d/` for default model discovery
- keep Live2D mode usable without imported resources
- add user-facing prompts in settings / Live2D mode / control center summaries

## Milestone 60

- close the Bubble / Live2D settings runtime loop so saved options are consumed by launcher views
- add shared assistant persona prompt configuration and wrap Hermes task descriptions before execution
- add optional TTS abstraction with `none` / `http` / `command` providers, disabled by default
- extract proactive desktop watching into a shared shell service for Bubble and Live2D
- add Bridge `POST /assistant/intent` as the low-risk natural language entry for AstrBot
- add AstrBot `/y ask` and `/y chat` commands while keeping existing `/y` command family compatible
- keep AstrBot as a thin QQ bridge; do not move local runtime or machine control into the plugin

## Milestone 61

- make Bubble and Live2D chat entry click-only; hover/pointerenter/focus must not open or toggle Chat Window
- normalize legacy `bubble_mode.expand_trigger=hover` to `click` and reject new hover writes from settings API
- clarify settings effect semantics: Bubble size/position/top/avatar and Live2D startup auto-open require current-mode restart
- expand Bubble launcher size range to `80-192` and make visual size / native hit-test scale with the configured window size
- add a settings-page “apply and restart app” fallback until a true mode-only restart primitive exists
- harden Chat Window singleton cleanup for closed/destroyed stale windows
- add Bridge `GET/PATCH /assistant/profile` for shared persona profile; keep `assistant.persona_prompt` canonical
- define future memory-sharing boundary: no default raw QQ chat sync, inject prompt as persona → relevant memory → current session → request
