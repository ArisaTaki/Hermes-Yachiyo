# Oha-Yachiyo Desktop Execution Baseline

Date: 2026-06-22
Branch: `phase-5/oha-yachiyo-runtime`

## Locked Invariants

- Keep Agent Studio, Groups, multi-agent runs, Workflow, Run Timeline, Approval, and Artifact behavior.
- Do not rewrite `NativeRunEngine` as part of the desktop execution migration.
- Do not change the database schema for the first execution-oriented phases.
- Do not break legacy `/agents` route response shapes.
- Keep high-risk actions behind the approval/policy gate.

## Current Baseline

- `apps/shell/yachiyo_agent/` already provides public Chat and Studio facades plus snapshots.
- `/yachiyo/tasks` and `/yachiyo/studio/*` routes are present while legacy Agent Studio routes remain.
- Chat readiness currently reports task/runnable readiness through the legacy runtime port.
- The runtime tool registry currently exposes workspace, terminal, memory, future task, skill, and artifact tools.

## Product Gap

- Chat is not yet a desktop execution surface by default.
- The tool registry does not yet contain `screen.*`, `desktop.*`, `app.*`, `media.*`, or `browser.*` tools.
- The main Chat default policy does not expose desktop execution tools.
- `terminal.run` and `workspace.write_patch` are approval-gated high-risk tools; this remains intentional.

## First Execution Direction

- Add stable desktop execution readiness contracts before implementing tool actions.
- Prefer structured desktop tools over relaxing raw terminal execution.
- Low/medium-risk desktop tools should eventually execute directly and remain observable in Run Timeline.
- High-risk actions such as destructive file writes, sending messages, payments, system settings, credentials, and raw shell remain approval-gated.
