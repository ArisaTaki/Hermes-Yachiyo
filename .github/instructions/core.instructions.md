---
applyTo: "apps/**,packages/**,docs/**"
---

# Core and Desktop App Instructions

Hermes-Yachiyo is the main system.

## Architectural intent

Hermes-Yachiyo is a desktop-first local application.

It should be split into:

- app shell
- core runtime
- local capability layer
- optional local bridge/API

## Responsibilities

- app shell: window, tray, display mode, settings entry, local UX
- core runtime: Hermes integration, task orchestration, state, memory/tool coordination
- local capability layer: screenshots, active-window, local machine capabilities
- optional bridge/API: local communication for UI and AstrBot bridge

## Rules

- Do not design Hermes-Yachiyo as a pure FastAPI service.
- FastAPI or similar local APIs may exist only as internal bridge layers.
- Define product shape and module boundaries before deep implementation.
- Keep modules small and typed.
- Use explicit request/response models where APIs exist.
- Do not implement Codex CLI execution here.
- Do not expose unrestricted shell access.

## MVP order

1. app shell scaffold
2. core runtime scaffold
3. protocol/task schema
4. local capability adapters
5. local bridge/API
6. AstrBot integration support
