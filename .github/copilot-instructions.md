# GitHub Copilot Instructions for Hermes-Yachiyo

You are working on Hermes-Yachiyo.

Hermes-Yachiyo is a **desktop-first local agent application** built around Hermes Agent.
It is not a backend-first service product.

AstrBot is not the system core. AstrBot is only a QQ bridge plugin host.
Hapi remains the existing Codex execution backend and should not be reimplemented inside Hermes-Yachiyo.

## Product shape

Hermes-Yachiyo should ultimately be a packaged local desktop app that can be launched directly by the user.

The app should provide:
- a local desktop shell
- tray or window entry
- configurable display mode
- bubble mode
- Live2D mode as a future-capable mode or placeholder
- settings UI or WebUI
- embedded Hermes runtime
- optional local bridge/API for AstrBot integration

## Architecture rules

- Hermes-Yachiyo must run locally without QQ.
- Hermes-Yachiyo must be designed as a desktop app first.
- Internal APIs may exist, but they are not the product itself.
- AstrBot must remain a thin bridge that forwards QQ requests.
- Do not move machine-local control logic into AstrBot.
- Do not move Codex CLI execution into Hermes-Yachiyo.
- Do not create a second agent brain inside the AstrBot plugin.

## Delivery order

1. Define desktop-first architecture and repo layout.
2. Scaffold app shell and configuration surface.
3. Define protocol and task schemas.
4. Build embedded core runtime.
5. Build local capability adapters.
6. Add local bridge/API for internal and AstrBot use.
7. Add AstrBot bridge plugin.
8. Add richer UI modes later.

## MVP focus

The first runnable milestone should be:
- a launchable local desktop app shell
- a settings/config surface
- a core runtime boundary
- screenshot and active-window capability hooks
- optional local bridge/API
- AstrBot bridge prepared but still thin

## Safety

- low: status, task lists, screenshots, summaries
- medium: bounded reads, workspace scans, safe local queries
- high: arbitrary shell, destructive file ops, git push, keyboard/mouse automation

High-risk actions must never be enabled by default.