# Session Summary

## 本轮完成内容

将 Bridge 状态接入主界面仪表盘和气泡模式，同时为 AstrBot / Hapi 预留集成占位。

### 主界面展示的 Bridge 信息

| 展示内容 | 位置 | 说明 |
|--------|------|------|
| Bridge 启用状态 | card3 “运行信息” | ✅ 已启用 / ❌ 已禁用 |
| Bridge 地址 | card3 “运行信息” | <http://host:port> |
| AstrBot / QQ | 新增全宽集成服务卡 | ⏳ 未接入（占位） |
| Hapi / Codex | 新增全宽集成服务卡 | ⏳ 未接入（占位） |

### bubble 模式展示的精简状态

| 行 | 内容 |
|----|------|
| Bridge | ✅ 127.0.0.1:8420 / ❌ 已禁用 |
| AstrBot | ⏳ 未接入（占位） |

气泡模式不展示 Hapi，保持轻量；完整集成信息通过“打开主窗口”入口查看。

### AstrBot / QQ 接入状态占位

- `get_dashboard_data()` 返回 `integrations.astrbot.status = "not_connected"`
- `get_dashboard_data()` 返回 `integrations.hapi.status = "not_connected"`
- `get_bubble_data()` 返回 `astrbot.status = "not_connected"`
- 主界面和气泡均显示 `⏳ 未接入`
- 状态字符串设计为可扩展：后续改为 `connected` / `error` 即可最新展示

## 修改的文件

| 文件 | 变更 |
|------|------|
| apps/shell/main_api.py | `get_dashboard_data()` 新增 bridge + integrations 字段 |
| apps/shell/window.py | card3 增 bridge 行，新增集成服务全宽卡 |
| apps/shell/modes/bubble.py | `get_bubble_data()` 增 bridge/astrbot，HTML/JS 增 2 行 |
| memory/progress/current-state.md | 更新 Milestone 7 |
| memory/handoff/session-summary.md | 更新本轮总结 |

## 下一步重点

**AstrBot 插件实现**：QQ 命令路由到 bridge API 或 Hapi Codex。

### bubble 模式新增能力

| 能力 | 说明 |
|------|------|
| 状态摘要 | 显示 Hermes Agent 就绪状态、工作空间初始化状态、运行时间 |
| 打开主窗口 | 在当前 pywebview 会话中创建第二个完整仪表盘窗口 |
| 刷新状态 | 手动刷新数据，15 秒自动刷新 |
| 关闭入口 | `close_bubble()` 销毁气泡窗口 |
| 常驻最前 | `on_top=True` 使气泡窗口保持在其他窗口上层 |

### bubble 与 window 模式的区别

| 对比项 | window 模式 | bubble 模式 |
|--------|-------------|-------------|
| 窗口尺寸 | 560×520，可调 | 320×280，固定 |
| 内容 | 完整仪表盘 + 可编辑设置面板 | 状态摘要 + 操作按钮 |
| API | MainWindowAPI（get_dashboard/settings/update） | BubbleWindowAPI（get_bubble_data/open_main/close） |
| on_top | 否 | 是（常驻最前） |
| 设置编辑 | ✅ 支持 | ❌ 不支持（通过「打开主窗口」进入完整设置） |

### open_main_window 实现说明

pywebview 支持在 API 回调中调用 `webview.create_window()`，新窗口会加入当前 `start()` 的事件循环。
当前实现：气泡窗口持有全局 `BubbleWindowAPI`（通过 `webview.start(api=api)`），主窗口以只读仪表盘形式创建，共享同一 webview 会话。

### main_api.py 同步变更

- `get_settings_data()` 中 bubble 的 `available` 改为 `True`
- 设置页可选模式下拉 bubble 选项对用户可见

### live2d 后续接入方式

live2d 保持占位实现不变。后续接入时只需修改 `apps/shell/modes/live2d.py`：

1. 替换 `_LIVE2D_HTML` 为嵌入 Live2D WebGL 渲染器的 HTML
2. 添加 `Live2DWindowAPI` 提供角色控制 / 互动接口
3. `main_api.py` 中 live2d 的 `available` 改为 `True`

## 修改的文件

| 文件 | 变更 |
|------|------|
| apps/shell/modes/bubble.py | 重写为最小可用实现（BubbleWindowAPI + 状态摘要 UI） |
| apps/shell/main_api.py | bubble available 改为 True |
| memory/progress/current-state.md | 更新 Milestone 6 |
| memory/handoff/session-summary.md | 更新本轮总结 |

## 下一步重点

**AstrBot 插件实现**：QQ 命令路由到 bridge API 或 Hapi Codex。
3. `_start_normal_mode(config)` → `launch_mode(runtime, config)`
4. `launch_mode()` 根据 `config.display_mode` 分发到对应 runner

### app.py 变更

- 移除对 `create_main_window` 的直接导入
- `_start_normal_mode()` 末尾改为 `launch_mode(runtime, config)`
- 所有模式分支收敛到 `modes/`，`app.py` 无模式判断逻辑

## 修改的文件

| 文件 | 变更 |
|------|------|
| apps/shell/modes/**init**.py | 实现 launch_mode() 分发器 |
| apps/shell/modes/window.py | 新建，窗口模式 runner |
| apps/shell/modes/bubble.py | 实现气泡模式占位 runner |
| apps/shell/modes/live2d.py | 实现 Live2D 模式占位 runner |
| apps/shell/app.py | 改用 launch_mode()，去掉 create_main_window 导入 |
| memory/progress/current-state.md | 更新 Milestone 6 |
| memory/handoff/session-summary.md | 更新本轮总结 |

## 下一步重点

**AstrBot 插件实现**：QQ 命令路由到 bridge API 或 Hapi Codex。

### 可编辑配置项实现

| 配置项 | 控件类型 | 位置 |
|--------|----------|------|
| 显示模式 | select 下拉（window/bubble/live2d） | 显示模式分组 |
| Bridge 开关 | toggle 开关 | Bridge 分组 |
| Bridge 地址 | input 文本框 | Bridge 分组 |
| Bridge 端口 | input 数字框（1024-65535） | Bridge 分组 |
| 系统托盘开关 | toggle 开关 | 应用分组 |

### config.py 扩展

- 新增 `bridge_enabled: bool = True` — Bridge 启用开关
- 新增 `tray_enabled: bool = True` — 系统托盘启用开关
- load_config() / save_config() 自动覆盖新字段

### main_api.py 扩展

- `get_settings_data()` 返回 bridge.enabled 和 app.tray_enabled 新字段
- 新增 `update_settings(changes)` 方法：
  - 白名单校验：仅允许 display_mode, bridge_enabled, bridge_host, bridge_port, tray_enabled
  - 类型校验：int/str/bool 分别验证，JS float→int 自动转换
  - 值域校验：display_mode 只接受 window/bubble/live2d，bridge_port 限 1024-65535
  - 通过后 setattr 修改运行时配置 + save_config() 持久化
  - 返回 {ok, applied, errors} 结构

### window.py 设置面板改造

- 显示模式：`<select>` 替代纯文本
- Bridge 开关：toggle 滑块
- Bridge 地址/端口：`<input>` 替代纯文本
- 系统托盘：toggle 滑块
- 新增 CSS：.s-select / .s-input / .s-toggle / .save-hint
- 新增 JS `onSettingChange(key, value)`：调用 update_settings + 显示保存结果 + 3秒后自动清除
- 修改后自动调用 refreshSettings() 同步最新值

### app.py 启动逻辑改造

- Bridge 启动受 `config.bridge_enabled` 控制（False 时跳过启动）
- 系统托盘启动受 `config.tray_enabled` 控制（False 时跳过启动）
- 退出清理逻辑同步适配开关状态

## 架构边界保持

- shell 是产品入口，config 由 shell 管理
- core 不暴露 HTTP
- bridge 只是内部通信桥，受 shell 配置控制
- 配置修改通过 WebView API（MainWindowAPI），不走 bridge HTTP

## 修改的文件

| 文件 | 变更 |
|------|------|
| apps/shell/config.py | 新增 bridge_enabled、tray_enabled 字段 |
| apps/shell/main_api.py | 新增 update_settings()，settings data 增加新字段 |
| apps/shell/window.py | 设置面板改为可编辑控件，新增 CSS/JS |
| apps/shell/app.py | bridge/tray 启动受配置开关控制 |
| memory/progress/current-state.md | 更新 Milestone 5 |
| memory/handoff/session-summary.md | 更新本轮总结 |

## 下一步重点

实现 AstrBot 插件的 QQ 命令路由功能。
