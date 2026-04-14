# Current State

## 已完成

### Milestone 0 — 仓库骨架（desktop-first）

- ✅ pyproject.toml（桌面应用依赖：pywebview, pystray, Pillow, fastapi, uvicorn）
- ✅ apps/shell/ — 桌面壳入口（app.py, tray.py, window.py, config.py, modes/）
- ✅ apps/core/ — Runtime + State 骨架（runtime.py, state.py），不暴露 HTTP
- ✅ apps/bridge/ — 内部 FastAPI 桥梁（server.py + routes/），非产品本体
- ✅ apps/locald/ — 截图 + 活动窗口适配器（macOS 实现）
- ✅ packages/protocol/ — 枚举、请求/响应模型、错误模型、审计事件
- ✅ packages/tasking/ — 占位
- ✅ packages/security/ — 占位
- ✅ integrations/astrbot-plugin/ — QQ 命令路由骨架

### Milestone 1 — Protocol Schema

- ✅ TaskStatus, TaskType, RiskLevel, ErrorCode, AuditAction 枚举
- ✅ StatusResponse, TaskCreateRequest, TaskInfo, TaskListResponse 等请求/响应模型
- ✅ ErrorResponse 错误模型
- ✅ AuditEvent 审计事件模型

### Milestone 2 — Hermes 安装引导层

- ✅ packages/protocol/install.py — Hermes 安装状态模型
- ✅ packages/protocol/enums.py — 新增 HermesInstallStatus, Platform 枚举
- ✅ apps/installer/ — Hermes Agent 安装引导层
  - hermes_check.py: 命令检测、版本检查、平台支持检测
  - hermes_install.py: 分平台安装指导（不含复杂自动安装）
  - hermes_setup.py: HERMES_HOME 规划与环境变量设置
- ✅ apps/core/runtime.py — 集成安装检测到启动流程
- ✅ apps/bridge/routes/hermes.py — Hermes 环境设置 API
- ✅ apps/bridge/routes/status.py — 暴露 Hermes 安装状态

## 架构边界确认

- apps/shell: 桌面壳（pywebview 仅为 MVP 原型，不影响长期边界）
- apps/core: runtime + state + task orchestration + Hermes 安装检测，不直接暴露 HTTP
- apps/bridge: FastAPI 内部通信桥梁，仅供 UI 和 AstrBot 调用
- apps/locald: 本地能力适配器
- apps/installer: Hermes Agent 视为外部运行时依赖，提供安装检测与引导
- integrations/astrbot-plugin: QQ 桥接，路由到 Hermes 或 Hapi
