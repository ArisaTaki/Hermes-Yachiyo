---
applyTo: "integrations/astrbot-plugin/**"
---

# AstrBot Bridge Plugin Instructions

The plugin is a QQ bridge, not the main runtime.

## Responsibilities
- parse QQ commands
- validate sender and permissions
- call Hermes-Yachiyo HTTP APIs
- route /y codex to Hapi
- return formatted responses to QQ

## Non-responsibilities
- do not implement local machine control directly
- do not implement a second task system
- do not implement a second memory layer
- do not become the main planner

## Commands
- /y status
- /y tasks
- /y screen
- /y window
- /y do <task text>
- /y codex <task text>
