<div align="center">

# Oha-Yachiyo

Desktop-first local personal agent application

Built around the in-repository Native Agent runtime, with Yachiyo available as a desktop assistant, floating bubble, or Live2D character.

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-pytest%20suite-brightgreen.svg)](#testing)

**English** | **[中文](README.md)** | **[日本語](README.ja.md)**

</div>

---

## Start Here

Oha-Yachiyo is still source-first. It is not yet a normal packaged desktop installer for every platform.

Source runs require:

- Python 3.11 or newer
- Node.js 20.19 or newer
- npm
- Git

The `oha-yachiyo` command starts the Electron + React frontend and the Python backend. If frontend dependencies are missing, the launcher can install `apps/frontend/node_modules`; it does not install Node.js itself.

## What It Does

Oha-Yachiyo is a local desktop shell, not another hosted chat page:

- Dashboard: Native Agent readiness, Model Profiles, sessions, tools, settings, backup, and uninstall.
- Chat Window: full conversation surface backed by ChatSession and TaskRunner.
- Bubble mode: a lightweight desktop entry point that opens the shared chat window.
- Live2D mode: a character desktop entry point with local resource import.
- Local Bridge: loopback-only HTTP API for the frontend and optional AstrBot integration.

The execution path is:

```text
Chat UI / Bridge
-> AppRuntime / AppState
-> TaskRunner
-> NativeAgentExecutor
-> NativeRunEngine
-> Model Profiles / ToolBroker / PolicyGate / ApprovalCoordinator / RunEvent
```

Task remains the product-level task contract. Run is the Native Agent execution record. NativeAgentExecutor owns the Task-to-Run mapping.

## Quick Start

```bash
git clone <repo-url>
cd oha-yachiyo
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
```

For tests and development tools:

```bash
pip install -e ".[dev]"
```

Start the desktop app:

```bash
oha-yachiyo
```

Backend-only development:

```bash
oha-yachiyo-backend
```

## First Launch

On first launch, configure the local app and model path:

```text
Configure model source / default Chat model
  -> Initialize the Oha-Yachiyo workspace
  -> Import Live2D / TTS resources if needed
  -> Enter the dashboard
```

If no model is configured, Chat and Agent runs return structured `native_agent_not_ready / model_profile_required` errors. They do not require an external execution kernel.

Common checks:

- Model connection failed: verify Base URL, model name, and API key.
- Bridge unavailable: confirm the desktop backend is running and the local port is free.
- Screenshot unavailable on macOS: grant Screen Recording permission to Oha-Yachiyo.

## Local Data

Main user-scoped paths:

```text
~/.oha-yachiyo/
~/.oha-yachiyo-config/
```

Back up these paths before resetting local data.

## Live2D Resources

Live2D assets are optional and not stored in the main repository.

Download resource releases from:

<https://github.com/kuguya-AI-app-develop/oha-yachiyo/releases>

Recommended path:

```text
~/.oha-yachiyo/assets/live2d/
```

The dashboard can import a resource ZIP or select a model directory. See [docs/live2d-assets.md](docs/live2d-assets.md).

## Yachiyo GPT-SoVITS Voice Resources

The Yachiyo GPT-SoVITS voice package is published separately from the app DMG:

<https://github.com/kuguya-AI-app-develop/oha-yachiyo/releases/tag/tts-assets-yachiyo-gpt-sovits-v4>

Import `Oha-Yachiyo-yachiyo-gpt-sovits-v4.zip` from the proactive care / desktop observation page. The package contains voice weights and reference audio only; users still run their own local GPT-SoVITS API service. See [docs/tts-voice-assets.md](docs/tts-voice-assets.md).

## Optional QQ / AstrBot Bridge

The AstrBot plugin routes QQ commands to the local Bridge. It does not implement local machine control itself.

| Command | Description |
|---------|-------------|
| `/y status` | View status |
| `/y tasks` | List tasks |
| `/y do <description>` | Create a task |
| `/y check <id>` | Show task details |
| `/y cancel <id>` | Cancel a task |
| `/y screen` | Show screenshot info |
| `/y window` | Show active-window info |
| `/y help` | Show help |

## Project Structure

```text
apps/
  frontend/           Electron + React/Vite/TypeScript frontend
  desktop_backend/    Headless Python backend entry point
  desktop_launcher.py Source development launcher
  shell/              Config, Native runtime, desktop backend UI adapters
  core/               AppRuntime, task state, chat state
  bridge/             Local FastAPI Bridge
  locald/             Screenshot and active-window adapters
  installer/          Workspace initialization, backup, restore, uninstall
packages/
  protocol/           Cross-layer data models
integrations/
  astrbot-plugin/     QQ bridge plugin
tests/                pytest suite
docs/                 Architecture and resource documentation
```

## Development Commands

```bash
source .venv/bin/activate
source ~/.nvm/nvm.sh
nvm use 20.19.0

npm --prefix apps/frontend run build
pytest -q
oha-yachiyo
```

## Testing

```bash
pip install -e ".[dev]"
pytest -q
```

Focused areas include protocol models, AppState, TaskRunner, NativeAgentExecutor, NativeRunEngine, Chat API, Bridge routes, Model Profiles, approval flows, Workflow, release guards, and frontend feature-preservation contracts.

## Packaging Direction

Release packages should not depend on a globally installed Python, Node.js, or editable checkout. The macOS path builds the React renderer, freezes the Python backend into `oha-yachiyo-backend`, packages Electron, and scans release artifacts for product identity and security regressions.

## License

MIT
