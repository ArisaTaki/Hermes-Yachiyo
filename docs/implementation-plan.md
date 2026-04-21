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
