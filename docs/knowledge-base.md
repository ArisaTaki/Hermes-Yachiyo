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
- Live2D mode or reserved support for it
- settings page or WebUI
- local runtime execution
- optional remote access through AstrBot bridge

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
