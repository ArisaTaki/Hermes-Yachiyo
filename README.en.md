<div align="center">

# 🌸 Hermes-Yachiyo

**Desktop-First Local Personal Agent Application**

An intelligent desktop assistant built on [Hermes Agent](https://github.com/NousResearch/hermes-agent)

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-105%20passed-brightgreen.svg)](#testing)

**English** | **[中文](README.md)** | **[日本語](README.ja.md)**

</div>

---

## ✨ Features

- 🖥️ **Desktop-First** — Runs locally as a desktop app with system tray, no server deployment needed
- 🔄 **Three Display Modes** — Window / Floating Bubble / Live2D Character
- 🤖 **Smart Task System** — Pluggable execution strategies with simulated and Hermes CLI execution
- 🎨 **Live2D Ready** — Full model configuration, directory scanning, and validation framework
- ⚙️ **Complete Settings System** — Instant / restart-required tiered feedback on save
- 🔌 **QQ Bridge** — Remote control via AstrBot plugin (`/y` command family)
- 🏗️ **Strict Layering** — Shell / Core / Bridge / Locald / Protocol with clear responsibilities

## 📸 Display Modes

| Window Mode | Bubble Mode | Live2D Mode |
|:---:|:---:|:---:|
| 560×520 full dashboard | 320×280 floating status | 380×560 character skeleton |
| Task stats · Settings panel | Auto-refresh · Quick expand | Motion placeholder · Config entry |

## 🏛️ Architecture

```
┌────────────────────────────────────────────────┐
│            Hermes-Yachiyo Desktop App           │
│                                                │
│  ┌── App Shell (apps/shell) ────────────────┐  │
│  │  Entry point · System tray · Window mgmt  │  │
│  │  Display modes: window / bubble / live2d  │  │
│  │  Settings · Effect policies · Integration │  │
│  └───────────────────────────────────────────┘  │
│                      │                         │
│  ┌── Core Runtime (apps/core) ───────────────┐  │
│  │  Hermes Agent wrapper · Task state mgmt   │  │
│  │  TaskRunner · Execution strategy · No HTTP│  │
│  └───────────────────────────────────────────┘  │
│                      │                         │
│  ┌── Local (apps/locald) ────────────────────┐  │
│  │  Screenshot · Active window · HW adapters │  │
│  └───────────────────────────────────────────┘  │
│                      │                         │
│  ┌── Bridge (apps/bridge) ───────────────────┐  │
│  │  Internal FastAPI · For UI & AstrBot only │  │
│  │  Restartable · Config drift · State machine│  │
│  └───────────────────────────────────────────┘  │
└────────────────────────────────────────────────┘
           ↑ HTTP (local, optional)
  ┌────────┴───────┐        ┌───────────┐
  │  AstrBot Plugin │  ───→  │   Hapi    │
  │  (QQ Bridge)    │        │  (Codex)  │
  └────────────────┘        └───────────┘
```

## 🚀 Quick Start

### Requirements

- Python 3.11+
- macOS / Linux / Windows (WSL2)
- [Hermes Agent](https://github.com/NousResearch/hermes-agent) (guided installation within the app)

### Installation & Launch

```bash
# Clone and install
git clone <repo-url>
cd Hermes-Yachiyo
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Launch the desktop app
hermes-yachiyo
# or
python -m apps.shell.app
```

### First Launch Flow

The app automatically detects Hermes Agent status and guides you through setup:

```
Hermes not installed → Installation guide UI (one-click install)
    ↓
Installed but not initialized → Workspace initialization wizard
    ↓
Ready → Enter normal mode → Current display mode
```

## ⚙️ Configuration

Config file located at `~/.hermes-yachiyo/config.json`, editable via the settings UI.

| Setting | Default | Effect Policy |
|---------|---------|--------------|
| `display_mode` | `window` | Requires mode restart |
| `bridge_enabled` | `true` | Requires Bridge restart |
| `bridge_host` | `127.0.0.1` | Requires Bridge restart |
| `bridge_port` | `8420` | Requires Bridge restart |
| `tray_enabled` | `true` | Requires app restart |
| `live2d.model_name` | — | Immediate |
| `live2d.model_path` | — | Immediate |
| `live2d.enable_expressions` | `false` | Immediate |
| `live2d.enable_physics` | `false` | Immediate |
| `live2d.window_on_top` | `false` | Requires mode restart |

After saving, the UI instantly shows effect status hints for each setting.

## 🤖 Task System

Task lifecycle: `PENDING → RUNNING → COMPLETED / CANCELLED / FAILED`

**Execution Strategies:**

- **SimulatedExecutor** — Mock execution for MVP testing
- **HermesExecutor** — Real `hermes run --prompt` calls with auto-detection

```bash
# Via Bridge API
curl http://127.0.0.1:8420/tasks -X POST \
  -H "Content-Type: application/json" \
  -d '{"description": "Analyze current directory structure"}'

# Via QQ
/y do Analyze current directory structure
/y check abc123
/y cancel abc123
```

## 🔌 QQ Bridge (AstrBot Plugin)

Integrates with QQ via AstrBot plugin. All commands start with `/y`:

| Command | Description |
|---------|-------------|
| `/y status` | View system status |
| `/y tasks` | Task list |
| `/y do <desc>` | Create task |
| `/y check <id>` | Query task details |
| `/y cancel <id>` | Cancel task |
| `/y screen` | Screenshot info |
| `/y window` | Current active window |
| `/y codex <desc>` | Codex execution (Hapi, coming soon) |
| `/y help` | Command help |

The plugin only handles command routing — no local logic. Error messages cover connection failures, timeouts, service unavailability, and more.

## 🎨 Live2D Support

The current phase provides a complete configuration and validation framework (renderer SDK not yet integrated):

- **Five-level validation**: Not configured → Invalid path → Not a model dir → Valid path → Loaded
- **Auto directory scan**: Detects `.moc3` / `.model3.json` files (Cubism 3/4 support)
- **Model summary extraction**: Primary candidate files, source directory, renderer entry point
- **Editable settings**: Model name, path, idle motion group, expression/physics toggles
- **Instant refresh**: Re-validates and updates display immediately after save

## 🔗 Bridge API

Internal FastAPI service for UI and AstrBot consumption:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/status` | GET | Runtime status & task statistics |
| `/tasks` | GET | Task list |
| `/tasks` | POST | Create task |
| `/tasks/{id}` | GET | Task details |
| `/tasks/{id}/cancel` | POST | Cancel task |
| `/screen/current` | GET | Screenshot (base64) |
| `/system/active-window` | GET | Active window info |
| `/hermes/status` | GET | Hermes installation status |

Bridge supports runtime restart, config drift detection, and state machine management (disabled / enabled_not_started / running / failed).

## 🧪 Testing

```bash
# Run all tests
.venv/bin/python -m pytest tests/ -v

# 105 tests, all passed
```

| Test Module | Count | Coverage |
|-------------|-------|----------|
| `test_protocol` | 14 | Enums, data models, request/response |
| `test_state` | 11 | Task lifecycle, terminal state protection |
| `test_executor` | 7 | Executor models, simulated execution |
| `test_effect_policy` | 9 | Settings effect policies |
| `test_integration_status` | 11 | Bridge/AstrBot/Hapi status |
| `test_astrbot_handlers` | 32 | All handler output & error formatting |
| `test_startup` | 6 | Startup decision tree |

## 📁 Project Structure

```
apps/
  shell/              # Desktop application shell
    app.py              # Main entry point
    startup.py          # Startup decision logic
    window.py           # Main window (pywebview)
    config.py           # Configuration management + Live2D validation
    effect_policy.py    # Settings effect policies
    integration_status.py  # Unified integration state source
    main_api.py         # Window API
    settings.py         # Settings page builder
    tray.py             # System tray
    modes/              # Display modes
      bubble.py           # Floating bubble mode
      live2d.py           # Live2D character mode
  core/               # Core runtime (no HTTP exposure)
    runtime.py          # Hermes runtime wrapper
    state.py            # Task state management
    executor.py         # Execution strategies (simulated / Hermes CLI)
    task_runner.py      # Task scheduling poller
  bridge/             # Internal communication bridge
    server.py           # FastAPI server (restartable)
    deps.py             # Dependency injection
    routes/             # API routes
  locald/             # Local capability adapters
    screenshot.py       # Screenshot (macOS)
    active_window.py    # Active window (macOS)
  installer/          # Hermes installation guide
    hermes_check.py     # Installation detection
    hermes_install.py   # Installation execution
    workspace_init.py   # Workspace initialization
packages/
  protocol/           # Cross-layer data definitions
    enums.py            # Enumerations
    schemas.py          # Request/response models
    install.py          # Installation models
integrations/
  astrbot-plugin/     # QQ bridge plugin
    main.py             # Entry point & ACL
    command_router.py   # Command routing
    api_client.py       # HTTP client
    handlers/           # Command handlers
tests/                # Test suite (105 tests)
```

## 🔧 Development Guide

### Strict Boundaries

| Module | Allowed | Forbidden |
|--------|---------|-----------|
| `apps/core` | Runtime, state, executors | Exposing HTTP |
| `apps/bridge` | Internal API, DI | Implementing business logic |
| `apps/shell` | Product entry, UI, config | Accessing state outside Bridge |
| `apps/locald` | Platform adapters | Business logic |
| `astrbot-plugin` | Command routing, formatting | Local machine control |

### Adding New Features

1. **New local capability** → Add adapter in `apps/locald/` → Expose endpoint in `apps/bridge/routes/`
2. **New task type** → Add enum in `packages/protocol/enums.py` → Handle in `apps/core/state.py`
3. **New display mode** → Implement in `apps/shell/modes/` → Integrate in `startup.py`

## 📋 Roadmap

- [ ] Live2D Cubism SDK renderer integration
- [ ] HermesExecutor real CLI testing
- [ ] Hapi Codex backend integration
- [ ] Task persistence (currently in-memory)
- [ ] Cross-platform support (Windows / Linux)
- [ ] AstrBot real QQ environment testing
- [ ] Bridge HTTPS + authentication
- [ ] Desktop shell technology upgrade (replace pywebview)

## 📄 License

MIT
