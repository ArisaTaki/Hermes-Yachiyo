# Session Summary

## 本轮完成内容 — Milestone 37 增强: Setup 进程检测与防重复

### 问题

上一轮已将 `hermes setup` 阶段纳入状态流，但缺少：
1. `setup_in_progress` 状态 — 无法区分"需要 setup"和"setup 正在运行"
2. 进程检测 — 无法检测 `hermes setup` 是否已在终端运行
3. 防重复启动 — 用户可能重复点击"开始配置"打开多个终端

### 解决方案

将状态流从四级扩展为五级：

```
NOT_INSTALLED → INSTALLED_NEEDS_SETUP → SETUP_IN_PROGRESS → INSTALLED_NOT_INITIALIZED → READY
     安装引导        Setup 配置引导       Setup 进行中         工作空间初始化         正常模式
```

### 修改文件

| 文件 | 变更 |
|------|------|
| packages/protocol/enums.py | 新增 `SETUP_IN_PROGRESS` 枚举值 |
| apps/installer/hermes_check.py | 新增 `is_hermes_setup_running()` 进程检测 + 检测链集成 |
| apps/installer/hermes_install.py | 新增 `SETUP_IN_PROGRESS` 安装指导分支 |
| apps/shell/startup.py | 映射 `SETUP_IN_PROGRESS → INSTALLER` |
| apps/shell/installer_api.py | `open_hermes_setup_terminal()` 防重复 + 新增 `check_setup_process()` |
| apps/shell/window.py | Setup UI 增强：进程状态提示 + 轮询 + 防重复按钮 |
| tests/test_startup.py | 新增 `test_setup_in_progress_to_installer` |

### Setup 引导 UI

- 窗口标题：「Hermes-Yachiyo - 配置 Hermes Agent」
- 状态栏：蓝色 info 样式，显示「Hermes Agent 已安装，需要完成初始配置」
- 操作区：
  - 「开始配置 Hermes」按钮 → 打开 Terminal.app 执行 `hermes setup`
  - 「我已完成配置，重新检测」按钮 → recheck_status() → 按结果跳转

### macOS Terminal 拉起实现

使用 osascript AppleScript：

```applescript
tell application "Terminal"
    activate
    do script "hermes setup"
end tell
```

### 用户流程闭环

1. 安装完成 → recheck 检测到 `installed_needs_setup` → 自动重启进入 setup 引导
2. 用户点击「开始配置 Hermes」→ Terminal.app 打开并执行 `hermes setup`
3. 用户在终端完成交互式配置
4. 用户回到应用点击「重新检测」
5. 检测通过 → 进入工作空间初始化 → 完成 → 正常模式

### 如何接手

| test_protocol.py | 14 | Enum、TaskInfo、Request/Response 模型 |
| test_state.py | 11 | 任务创建/取消/状态推进/终态保护 |
| test_executor.py | 7 | HermesCallError、SimulatedExecutor |
| test_effect_policy.py | 9 | 设置生效策略查询和混合效果 |
| test_integration_status.py | 11 | Bridge/AstrBot/Hapi 状态 + config_dirty |
| test_astrbot_handlers.py | 32 | 全 handler 输出、ACL、错误格式化 |
| test_startup.py | 6 | startup 决策树全路径 |

### 关键技术决策

- **astrbot-plugin 连字符目录**：使用 `importlib.util.spec_from_file_location` 注册为 `astrbot_plugin` 包解决导入问题
- **Bridge mock 注入**：conftest 在测试加载前注入 fake uvicorn/fastapi modules，避免真实服务依赖
- **pytest-asyncio strict mode**：所有异步 handler 测试使用 `@pytest.mark.asyncio` 标注

### 如何接手

```bash
# 运行全部测试
cd /path/to/Hermes-Yachiyo
.venv/bin/python -m pytest tests/ -v

# 运行桌面应用
.venv/bin/python -m apps.shell.app

# 测试依赖
pip install pytest pytest-asyncio httpx
```

### 下一步建议

1. **Task 系统真实 CLI 联调** — 当前 HermesExecutor 有 CLI 调用骨架但未经真机测试
2. **AstrBot 真实 QQ 联调** — handler 输出已覆盖测试，可尝试真实 AstrBot 环境接入
3. **Live2D 渲染器** — 配置/校验/摘要层已完备，可开始 moc3 渲染实现
4. **Bridge HTTPS/认证** — 当前 bridge 无认证，生产使用需增加
