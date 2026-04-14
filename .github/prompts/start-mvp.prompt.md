请严格遵循以下仓库文件：

- .github/copilot-instructions.md
- docs/knowledge-base.md
- docs/implementation-plan.md
- memory/00-project-definition.md
- memory/01-system-architecture.md
- memory/02-routing-rules.md
- memory/progress/current-state.md

你当前在开发的项目是 Hermes-Yachiyo。

## 先纠正产品形态

Hermes-Yachiyo 的最终产品形态不是单纯的 FastAPI 本地服务，而是一个本地可运行、可打包的桌面应用。

它应当包含：
- 桌面应用壳
- 托盘或窗口入口
- 配置界面或 WebUI
- 可切换显示模式
- 气泡模式
- Live2D 模式或至少预留支持
- 内嵌 Hermes Agent runtime
- 必要时暴露本地 bridge/API 给 AstrBot 插件调用

## 正确分层

1. App Shell
   - 桌面应用壳
   - 托盘/窗口/悬浮层
   - 模式切换
   - 设置入口

2. Core Runtime
   - Hermes Agent 封装
   - 任务管理
   - 状态管理
   - 记忆与工具协调

3. Local Capability Layer
   - screenshot
   - active-window
   - 其他本地能力

4. Local Bridge/API
   - 仅作为内部通信和 AstrBot 远程调用桥
   - 不是最终产品本体

5. AstrBot Plugin
   - QQ bridge
   - 路由到 Hermes-Yachiyo 或 Hapi

## 严格禁止

- 不要把 Hermes-Yachiyo 设计成纯 FastAPI 服务
- 不要把 FastAPI 当成产品本体
- 不要把 Codex CLI 执行搬进 Hermes-Yachiyo
- 不要把 AstrBot 插件写成第二个 agent runtime
- 不要在 AstrBot 里实现本地机器控制
- 不要先做复杂 UI 视觉细节
- 不要绕过 schema 直接堆功能

## 本轮目标

请先做桌面应用优先的骨架，而不是后端服务优先的骨架。

### 本轮先做
- 重新输出 desktop-first 的架构理解
- 重新规划目录结构
- 创建 app shell / core runtime / local capability / bridge / AstrBot plugin 的基础骨架
- 只做最小配置入口和模块边界
- 不要先深挖具体后端实现

## 输出格式

请按下面顺序开始：
1. Product Shape Summary
2. Revised Architecture Summary
3. Revised File Plan
4. Desktop-first MVP Slice Plan
5. Step 1 Implementation

现在开始，不要先做纯后端服务骨架。