# Session Summary

## 本轮完成内容 — Milestone 55: 三模式统一架构重构

### 核心结果

Hermes-Yachiyo 现在不再是“主窗口 + 附属入口”的结构，而是：

- **Window Mode**：总控台 / 仪表盘 / 入口中心
- **Bubble Mode**：轻量常驻聊天模式
- **Live2D Mode**：角色聊天壳
- **Chat Window**：三模式共享的完整会话空间

四者围绕同一套聊天内核运行，没有分叉出独立聊天状态。

### 本轮主要变更

#### 1. 模式配置层重构

- `apps/shell/config.py`
  - 新增 `WindowModeConfig`
  - 新增 `BubbleModeConfig`
  - 新增 `Live2DModeConfig`
  - `AppConfig` 改为通用配置 + 按模式配置的结构
  - 兼容旧 `live2d` 配置块读取

- `apps/shell/mode_settings.py`
  - 集中模式设置读写、校验、序列化
  - 支持 `window_mode.*` / `bubble_mode.*` / `live2d_mode.*`
  - 兼容旧 `live2d.*` 更新键

- `apps/shell/settings.py`
  - 改为单模式设置窗口
  - Window / Bubble / Live2D 都能打开各自设置，不再塞进一个混合设置页

#### 2. 模式壳职责重构

- `apps/shell/window.py`
  - 主窗口改成 Window Mode 总控台
  - 只保留状态、模式入口、最近消息概览、最近会话概览、打开 Chat Window 入口
  - 新增 `open_main_window(runtime, config)`，供 Bubble / Live2D 打开 Window Mode

- `apps/shell/modes/bubble.py`
  - 重写为真正 Bubble 模式
  - 支持展开/收起
  - 支持最近 1~3 条摘要显示
  - 支持快捷输入并继续当前会话
  - 支持 processing / failed / ready 状态展示
  - 支持打开 Chat Window / Window Mode / Bubble 设置

- `apps/shell/modes/live2d.py`
  - 重写为角色聊天壳
  - 角色舞台 + 回复泡泡 + 最近摘要
  - 支持最小输入入口
  - 支持打开 Chat Window / Window Mode / Live2D 设置
  - 保留 renderer 接入位，但本轮不做真实渲染

#### 3. 共享聊天概览层增强

- `apps/shell/chat_bridge.py`
  - 新增 `get_recent_sessions()`
  - 新增 `get_conversation_overview()`
  - Window / Bubble / Live2D 统一通过它读取当前会话摘要和最近会话

- `apps/shell/main_api.py`
  - `get_dashboard_data()` 新增 `chat` + `modes`
  - `get_settings_data()` 改为返回 `mode_settings`
  - `update_settings()` 改为委托 `mode_settings.apply_settings_changes()`
  - 新增 `open_mode_settings(mode_id)`

### 当前产品职责关系

#### Window Mode

- 用途：总控台、仪表盘、模式切换入口、设置入口
- 展示：Hermes / workspace / bridge / integration / task 状态、最近消息、最近会话
- 不做：完整聊天消息区

#### Chat Window

- 用途：完整会话空间
- 展示：完整消息流、历史会话切换、会话清空/删除
- 关系：三模式都可打开它，它不是产品唯一入口

#### Bubble Mode

- 用途：轻量桌面聊天模式
- 已具备：
  - 展开/收起
  - 最近摘要
  - 快捷输入
  - 当前会话续聊
  - 状态标签
  - 打开完整聊天窗口
  - 打开 Bubble 设置

#### Live2D Mode

- 用途：角色聊天壳
- 已具备：
  - 角色舞台壳
  - 最近回复泡泡
  - 最近摘要
  - 最小输入入口
  - 当前会话状态感知
  - 打开完整聊天窗口
  - 打开 Live2D 设置
- 未做：
  - 真正 renderer / moc3 渲染
  - 动作 / 表情 / 口型驱动

### 统一聊天来源确认

仍然保持唯一来源：

```text
Window / Bubble / Live2D / Chat Window
        ↓
      ChatBridge / ChatAPI
        ↓
      ChatSession
        ↓
      ChatStore (SQLite)
```

没有新增任何独立消息状态容器。

### 测试覆盖

- `tests/test_mode_settings.py`
  - 模式配置模型分离
  - Bubble 配置读写
  - 旧 `live2d.*` 兼容更新
  - 新旧配置块加载/保存

- `tests/test_main_api_modes.py`
  - Window Mode 仪表盘包含 chat overview + modes
  - 设置数据返回 `mode_settings`

- `tests/test_chat_bridge.py`
  - 新增 conversation overview 覆盖
  - Bubble / Live2D HTML 仍保留统一轮询契约

- `tests/test_window_exit.py`
  - 验证 Window Mode 仍通过 Chat Window 承载完整会话

### 手工验证建议

1. 启动 `display_mode=window`，确认主窗口只显示总控信息和最近消息/会话概览。
2. 在 Window Mode 打开 Chat Window，确认完整消息流仍正常。
3. 切到 Bubble Mode，发送短消息，确认 Chat Window 中能看到同一会话。
4. 切到 Live2D Mode，观察回复泡泡和最近摘要是否跟随同一会话变化。
5. 分别打开 Window / Bubble / Live2D 设置，确认配置能保存到对应 mode config。

### 后续最合理的方向

1. 把 Bubble / Live2D 的窗口位置恢复、吸附和更细粒度未读态做成真正原生行为。
2. 为 Live2D 模式接入 renderer 占位实现（先 canvas / mock renderer，再接 moc3）。
3. 继续补 UI 层自动化或更细的 shell service 测试。
