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
- Chat readiness reports task/runnable readiness plus desktop execution capability snapshots through the legacy runtime port.
- Public readiness already models `desktop_execution`, `screen_capture`, `active_window`, `app_control`, `media_control`, `foreground_input`, and `browser_control`.
- The runtime tool registry already exposes structured desktop/browser tools:
  - `screen.capture`
  - `desktop.active_window`
  - `app.open`
  - `app.focus`
  - `media.apple_music_play`
  - `desktop.hotkey`
  - `desktop.type_text`
  - `browser.open_url`
  - `browser.current_page`
  - `browser.click`
  - `browser.type_text`
  - `browser.extract_text`
  - `browser.screenshot`
- The main Chat runtime config is wired with daily desktop/browser tool names.
- Agent Studio has a Tool Catalog entrypoint and the Agent Editor can preview tool policy, missing permissions, risk, and approval requirements.
- Permission probing exists for Screen Recording, Automation/Accessibility, Music.app availability, and Chrome CDP reachability.

## Product Gap

- Chat is not yet proven as a desktop execution surface end to end for real user intents such as "play this song", "capture the screen", or "open this app".
- The main Chat prompt encourages structured desktop/browser tools, but the product still needs smoke coverage proving that common desktop intents select those tools instead of falling back to explanatory text.
- Permission diagnostics are available as readiness data, but Chat still needs clearer user-facing recovery cards and direct links when permissions are missing.
- Studio Tool Catalog and Agent Editor policy preview exist, but Tool Inspector dry-run/test and desktop-specific timeline styling remain incomplete.
- Groups and Workflow still need explicit group-level/workflow-node desktop execution policy and foreground-action locking surfaced in the public snapshots.
- `terminal.run` and `workspace.write_patch` are approval-gated high-risk tools; this remains intentional.

## First Execution Direction

- Treat stable desktop execution readiness contracts as present and continue extending them compatibly.
- Prefer structured desktop tools over relaxing raw terminal execution.
- Low/medium-risk desktop tools should eventually execute directly and remain observable in Run Timeline.
- High-risk actions such as destructive file writes, sending messages, payments, system settings, credentials, and raw shell remain approval-gated.

## Next Engineering Checkpoints

- Add focused smoke tests for daily Chat intent routing to `media.apple_music_play`, `screen.capture`, and `desktop.active_window`.
- Verify desktop tool call started/completed events and artifacts are projected into `RunTimelineSnapshot` and compact Chat task summaries.
- Add Chat-facing permission recovery copy for `screen_recording`, `automation_or_accessibility`, `accessibility`, `music_app`, and `chrome_cdp`.
- Add Studio tool dry-run/test UX after the current Tool Catalog and policy preview are stable.
- Keep every desktop tool behind the existing ToolBroker, schema validation, policy gate, and RunEvent projection.
