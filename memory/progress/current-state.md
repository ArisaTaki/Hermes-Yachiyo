# Current State

## 已完成

### Milestone 76 — 主动关怀截图链路、首启回退与发布自动化收口

- ✅ 主动关怀桌面观察的截图附件改为只作为内部附件传给对话链路，不再把“主动桌面观察”的系统指令文本写入用户消息；对话中仍可看到生成的桌面截图附件，方便用户确认本轮观察依据。
- ✅ 聊天附件读取改为 `inline` 响应，并移除图片查看器中的“打开原图”外部浏览器入口，避免主动关怀截图触发后自动弹出 Chrome/默认浏览器预览窗口，同时保持图片识别链路可继续读取本地附件。
- ✅ Hermes provider 推断补强：当配置为 `auto` 但 Base URL/模型指向 OpenRouter 时，Yachiyo 会按有效 provider 写入 `OPENROUTER_API_KEY` 并使用对应模型缓存判断图片原生输入能力，避免误报“API Key 无效”或错误回退到 vision 预分析。
- ✅ Electron 首启/激活流程继续加固：只要用户已经进入过主控台或安装信息显示 ready，Dock 图标激活就不会再用旧的 `lastInstallReady=false` 打回安装向导；进入主控台时会恢复配置中的 Bubble/Live2D 表现态，Live2D 无资源时自动回退 Bubble。
- ✅ Live2D 资源 gate 前后端双重兜底：设置页保存 `display_mode=live2d` 时如果没有有效资源，会返回 `redirect` 到 Live2D 设置页并保持 Bubble；Electron 表现态打开也会先检查资源状态，避免无资源透明窗口把用户困住。
- ✅ 主动关怀语音页新增 GPT-SoVITS 本地服务状态/安装/移除路由：可查看 API 是否可达、服务目录是否存在、LaunchAgent 是否安装/运行，并可把当前服务目录和命令写成当前用户的 macOS LaunchAgent；不会下载或改写 GPT-SoVITS 项目本体。
- ✅ Release workflow 改为自动生成带版本号的 stable/experimental release tag 与资产名：版本以 `pyproject.toml` 基础版本加 `GITHUB_RUN_NUMBER` 形成发布版本；DMG 和可选八千代 GPT-SoVITS ZIP 都会带上发布版本号。语音包可来自 `dist/release-assets/*.zip` 或仓库变量/密钥 `YACHIYO_TTS_VOICE_ASSET_URL`。
- ✅ 卸载“删除当前应用本体”改为 macOS Finder 删除优先、shell 删除兜底；仍属于 best-effort，因为运行中的 `.app` 删除受 Finder/权限/签名路径影响，失败时继续提示用户手动从 Applications 移除。
- ✅ 验证：`python -m pytest tests/test_ui_bridge_routes.py tests/test_tts.py tests/test_mode_settings.py tests/test_main_api_modes.py tests/test_proactive.py tests/test_hermes_capabilities.py tests/test_executor.py` → 181 passed；`npm --prefix apps/frontend run build` → passed（保留 Vite 大 chunk warning）；`ruby -e 'require "yaml"; YAML.load_file(".github/workflows/release-macos.yml")'` → passed；`git diff --check` → passed。

### Milestone 75 — DMG 首装流程、Live2D Gate 与 TTS 本地服务辅助

- ✅ 基于 `develop` 当前 HEAD `67b7f74` 的 DMG 清机验证反馈，修复安装向导在 Hermes 终端安装完成后的衔接：重新检测到 `installed_needs_setup` / `setup_in_progress` / `installed_not_initialized` 后会滚动到模型配置向导，引导用户填写 Provider、模型、Base URL 和 API Key。
- ✅ 初始化 Yachiyo 工作空间前新增模型/API Key 完整性提示：如果当前 Provider、模型或所需 API Key 缺失，会提示“直接初始化可能导致首次对话不可用”，用户确认后仍可继续，取消则回到模型配置区。
- ✅ Hermes ready / 工作空间初始化成功后，桌面壳会进入主控台并主动打开 Bubble 表现态；macOS 点击 Dock 图标时会先刷新 `/hermes/install-info`，避免使用旧的 `lastInstallReady=false` 把已初始化用户拉回安装向导，同时恢复当前表现态。
- ✅ 通用设置中的 Live2D 模式切换新增资源 gate：若 `mode_settings.live2d.config.model_state` 不是 `path_valid` / `loaded`，不会切换到 Live2D，而是跳到 Live2D 资源配置页要求导入 ZIP 或选择有效模型目录；后端 `apply_settings_changes()` 同步拒绝无资源的 `display_mode=live2d`。
- ✅ Electron 表现态启动也新增 Live2D gate：显式打开 Live2D 且资源未就绪时进入设置页；默认打开表现态时如当前配置是 Live2D 但资源不可用，会回退到 Bubble，避免用户进入不可点击、找不到 Dock 图标的死路。
- ✅ Live2D 真模型渲染增加 Electron/WebGL 保护：加载 runtime 后配置 Pixi WebGL2 偏好并关闭 major performance caveat；遇到 `checkMaxIfStatementsInShader` / `invalid value of 0` 时保留静态预览并显示明确的 WebGL 回退说明，避免把资源导入成功误判成导入失败。
- ✅ 主动关怀 TTS 的 GPT-SoVITS 配置新增本地服务辅助字段：`tts.gsv_service_workdir` 与 `tts.gsv_service_command`；导入八千代语音包后会默认填入 `http://127.0.0.1:9880`、权重/参考音频路径和默认服务启动命令，服务目录可由语音包 manifest 提供或由用户手动填写。
- ✅ 主动关怀语音设置页新增“GPT-SoVITS 本地服务”区块：可填写服务目录与启动命令，并通过受控 `/ui/hermes/terminal-command` 打开终端启动本地服务；说明语音 ZIP 只包含权重/参考音频，本地 API 服务仍需单独运行。
- ✅ 卸载页新增“同时删除当前应用本体”选项：完成工作区/Hermes 数据卸载后，可由 Electron 启动受控 shell 删除当前 `.app` bundle 并退出；失败时会提示手动移除 Applications 中的应用。
- ✅ GitHub Actions DMG workflow 失败原因已定位为 CI 未安装 `pytest-asyncio`，`pyproject.toml` dev extras 已补 `pytest-asyncio>=0.23.0`，workflow 的 async smoke tests 可正常收集执行。
- ✅ 验证：`npm --prefix apps/frontend run build` → passed；`python -m pytest tests/test_main_api_modes.py tests/test_mode_settings.py tests/test_ui_bridge_routes.py tests/test_tts.py tests/test_uninstall.py` → 131 passed，1 known duplicate ZIP warning；workflow smoke suite `python -m pytest tests/test_screenshot.py tests/test_proactive.py tests/test_chat_session.py tests/test_chat_api.py tests/test_ui_bridge_routes.py tests/test_tts.py tests/test_mode_settings.py` → 112 passed；`python -m pytest tests/test_hermes_installer.py` → 10 passed；全量 `python -m pytest` → 421 passed，1 known duplicate ZIP warning；`git diff --check` → passed。

### Milestone 74 — Tool Center Doctor 分级与工具配置修复

- ✅ 基于当前 `phase-2/feature/repair-tools` 的提交树补齐进度记录：`7307fd3` 合入了 2026-05-01 至 2026-05-02 的 Electron 固定前端、配置诊断、图片附件/vision 路由、图片链路校验缓存和窗口身份持久化等工作；其前序关键提交包括 `1ddba0a`、`41126f9`、`28c23ff`、`eac0dcb`、`0d0aee0`、`254ce91`、`9f55c9f`。
- ✅ `hermes doctor` 输出解析已从只看受限项扩展为同时解析 `available_tools`、`limited_tools`、受限原因和 issue count；旧的三元返回值仍保留兼容安装器调用。
- ✅ Runtime、Dashboard、Settings 和 Tool Center 已透传 Doctor 新字段，工具中心不再只依赖 `hermes.ready` 推断状态。
- ✅ Tool Center 已拆分基础 `browser` 和高级 `browser-cdp`：基础浏览器自动化可按 `browser` 可用状态显示，CDP 端口缺失只影响 `browser-cdp`。
- ✅ 新增工具配置安全接口 `/ui/hermes/tools/config`：按工具返回不同配置项，只展示 env 名和配置状态，不回传任何 token/key 明文；保存统一走 `hermes config set`。
- ✅ 第一批配置目录已覆盖 `web`、`browser`、`browser-cdp`、`image_gen`、Discord、Home Assistant、MoA、RL；Spotify、腾讯元宝和 messaging 先提供 Hermes 原生向导入口；Tool Center 现会读取 `hermes tools list`，只展示当前 Hermes 暴露的工具组。
- ✅ `image_gen` 配置已收敛为当前 Hermes 已知 provider：内置 FAL 与已装 OpenAI/OpenAI Codex/xAI 插件提供模型建议，不再主动列出 Hermes 未暴露的生图后端。
- ✅ 工具配置页新增“保存并测试 / 测试配置”：保存后会做必需配置静态检查，并运行 `hermes doctor` 对应工具状态，不会默认触发发消息、生图、RL 训练等有副作用/成本的真实调用。
- ✅ 新增 Hermes 更新检查与更新入口：Tool Center 可检查 `hermes version` / `hermes update --check`，更新通道跟随 Hermes 官方 updater 的当前 checkout `origin/main`；默认执行 `hermes update --gateway --yes --no-backup`，可勾选完整备份后改走 `--backup`，更新完成会自动刷新 `hermes tools list`、工具配置、Dashboard 与 Doctor 缓存，并展示工具清单变化。
- ✅ `image_gen` provider 列表改为从当前 Hermes `plugins/image_gen/*/plugin.yaml` 读取，确保已安装的 OpenAI、OpenAI Codex、xAI 插件不会被前端压成只剩 FAL。
- ✅ 新增 `/ui/hermes/tools/browser-cdp/launch`：可尝试启动或连接本机 Chrome `9222` 调试端口，成功后写入 `browser.cdp_url=http://127.0.0.1:9222`，失败时返回 Hermes 生成的手动命令。
- ✅ Tool Center React 视图新增 `#/tools/:toolId` 独立配置页，受限/可配置卡片会进入对应配置页而不是在长列表顶部展开；配置页顶部和底部都有保存入口，未保存切换时会弹出“保存并继续 / 弃置更改 / 继续编辑”确认。
- ✅ 诊断缓存指纹已纳入工具配置安全快照，工具配置或 env 配置状态变化后会让旧 Doctor 缓存标记为过期。
- ✅ 验证：`python -m pytest tests/test_hermes_installer.py tests/test_main_api_modes.py tests/test_ui_bridge_routes.py tests/test_hermes_capabilities.py` → 49 passed；`npm --prefix apps/frontend run build` → passed（保留 Vite 大 chunk warning）；`git diff --check` → passed。

### Milestone 73 — 一键安装错误捕获 hotfix

- ✅ `run_hermes_install()` 不再丢弃带 ANSI 颜色控制序列的安装脚本输出；会清洗控制码并保留可读错误文本，避免 UI 只显示 `exit=1` 而隐藏真正失败原因。
- ✅ 安装脚本非零退出后，兜底检测改为复用 `locate_hermes_binary()`，可识别 Hermes 已落盘但当前 GUI 进程 PATH 尚未刷新的场景。
- ✅ 通过备用路径找到 Hermes 且 `hermes --version` 成功时，将结果视为安装成功，并提示当前应用 PATH 已修复、仍需完成 `hermes setup`。
- ✅ 安装脚本真实失败时，失败文案提示用户查看上方安装日志中的错误详情。
- ✅ 修复 `apps/installer/hermes_install.py` 中已有 `Dict[str, any]` 类型标注问题，相关文件 diagnostics 清零。
- ✅ 新增回归测试覆盖 ANSI 错误日志保留、`exit=1` 后通过备用路径识别已安装 Hermes。
- ✅ 相关测试：`python -m pytest tests/test_hermes_installer.py` → 8 passed。
- ✅ 全量测试：`python -m pytest` → 425 passed，1 warning（已有重复 ZIP entry 警告）。
- ✅ `git diff --check` → passed。

### Milestone 72 — 备份清理与导入源安全收敛

- ✅ `find_backups()` 只纳入严格匹配托管命名规则的 `hermes-yachiyo-backup-YYYYMMDD-HHMMSS[-N].zip`，不再把 `*-draft.zip` / `*-external.zip` 等前缀相似文件纳入管理列表。
- ✅ `cleanup_old_backups()` 删除旧备份时若遇到 `ValueError`，会记录 warning 并跳过该文件，避免自动清理导致 `create_backup(auto_cleanup=True)` 中断。
- ✅ `import_backup()` 恢复 `app-config` 前强制确认备份源是非 symlink 目录；若备份里是文件或非目录形态，会跳过并给出原因，不会替换目标配置目录。
- ✅ `import_backup()` 恢复 `yachiyo-workspace` 前同样强制确认备份源是非 symlink 目录，再检查初始化标识和目标安全性，避免文件替换目标工作空间目录。
- ✅ 新增回归测试覆盖不可管理删除错误跳过、非规范命名 ZIP 不进入 `find_backups()`、文件形态 app-config/workspace 源不会被恢复。
- ✅ 相关测试：`python -m pytest tests/test_uninstall.py` → 45 passed。
- ✅ 全量测试：`python -m pytest` → 423 passed。

### Milestone 71 — 受保护路径集合缓存

- ✅ `protected_paths()` 改为复用按当前 home 路径缓存的受保护路径集合，避免备份导入/卸载安全检查中反复执行多组 `exists()` / `resolve()`。
- ✅ `is_protected_path()` 直接查询缓存的 `frozenset`，不再为每次判断重新构造受保护路径集合。
- ✅ 移除 `protected_paths()` 中不可达且引用未定义 `home` 的旧 return，避免静态检查与后续维护误判。

### Milestone 70 — 备份 ZIP 解压实际写入限流

- ✅ `_extract_zip_safely()` 不再只依赖 `ZipInfo.file_size` 头部声明；解压成员改为分块读写，并按实际写入字节数校验单条目和总解压体积限制。
- ✅ 解压过程中一旦实际写入量超出单条目或总量限制，会中止并删除当前部分输出文件，避免恶意 ZIP 通过虚假 header 触发磁盘填充风险。

### Milestone 72 — Electron 固定前端与 Python Headless 后端

- ✅ 固定桌面壳改为 Electron + React/Vite/TypeScript，前端工作区落在 `apps/frontend/`，不再通过 pywebview 承载新 UI。
- ✅ 新增 `apps/desktop_backend/app.py`，Python 侧只负责 `HermesRuntime`、Bridge lifecycle 与本地能力边界，不创建桌面窗口。
- ✅ 新增 `apps/bridge/routes/ui.py`，提供 `/ui/dashboard`、`/ui/settings`、`/ui/chat/*`、`/ui/modes/{mode}/settings` 给 React renderer 调用。
- ✅ `hermes-yachiyo` 入口改为启动 Electron 前端；`hermes-yachiyo-backend` 可单独启动后端；旧 pywebview 入口保留为 `hermes-yachiyo-legacy-pywebview`。
- ✅ 前端移除 `window.pywebview.api` 调用，改用 HTTP bridge client；新增通用设置、模式设置、聊天和主控台 React 视图。
- ✅ Node 使用 `nvm install/use 20.19.0`，并用 Node 20.19 刷新 latest 前端依赖与 `apps/frontend/package-lock.json`；`npm audit` 当前为 0 vulnerabilities。
- ✅ Electron dev server 固定为 `127.0.0.1:5174` strict port，避免 5173 被占用时 Vite 自动漂移导致 Electron 加载错误端口。
- ✅ `hermes-yachiyo` 默认入口会优先使用 nvm Node 20.19；缺少前端 `node_modules/.bin` 工具时自动执行一次 `npm ci`，然后打开 Electron 前端并拉起 Python backend。
- ✅ `apps/desktop_launcher.py` 已补 Node 20.19+ 版本预检、前端子进程失败提示和 Ctrl-C/验证中断的无 traceback 退出；启动失败时会优先显示可操作原因，而不是裸 Python traceback。
- ✅ 已排查用户运行后仍像旧窗口的问题：当前 venv 的 `hermes-yachiyo` console script 曾残留为 `apps.shell.app:main`；重新 `pip install -e .` 后已刷新为 `apps.desktop_launcher:main`，旧入口仅在 `hermes-yachiyo-legacy-pywebview`。
- ✅ 已修复 React 主控台 `Failed to fetch` 红条成功后不清除的问题，并把网络失败文案改为“无法连接本地 Bridge”。Bridge 卡片兼容 `state/status/running` 字段。
- ✅ Electron main 新增按当前 `display_mode` 自动打开 Bubble/Live2D 透明表现态窗口；React LauncherView 新增第一版 Bubble/Live2D 表现态 UI 与打开对话/设置入口。完整旧 pywebview 表现态能力仍需继续迁移。
- ✅ Bubble/Live2D Electron 表现态已接入真实 Bridge 状态：新增 `/ui/launcher`、`/ui/launcher/ack`、`/ui/launcher/quick-message`，复用 `ChatBridge` 与 `LauncherNotificationTracker` 提供未读、处理中、最近回复和快捷输入；Electron 右键菜单已接入打开对话/主控台/设置/重开表现态/关闭表现态/退出应用。
- ✅ Electron 表现态窗口已支持位置持久化：新增 `/ui/launcher/position`，Electron 在 Bubble/Live2D 移动或缩放后防抖写回配置；Bubble 会按旧 pywebview 逻辑吸附最近屏幕边缘，Live2D 会保存位置和窗口尺寸。
- ✅ `/ui/launcher` 已补 Live2D 资源状态摘要，React 表现态可根据资源是否就绪调整 stage 视觉状态，为后续接入真实 Live2D renderer 准备数据边界。
- ✅ React ChatView 已对照旧 pywebview Chat Window 补回核心体验：500ms 处理中轮询、typewriter 渐进显示、Markdown 渲染、复制按钮、会话下拉、新对话/删除、executor badge，并通过 `/ui/chat/*` HTTP Bridge 接入。
- ✅ Electron Chat Window 已恢复旧 pywebview 单例语义：主控台、Bubble、Live2D 和任意 `openView('chat')` 都打开/置前同一个独立 Chat BrowserWindow，不再把 ChatView 装进主窗口或表现态小窗口；Chat 窗口内的“主控台”按钮会回到主窗口。
- ✅ React renderer 已加入 hash route 层：`#/`、`#/chat`、`#/settings`、`#/settings/bubble`、`#/settings/live2d`、`#/bubble`、`#/live2d` 等路由可在同一窗口内切换，并保留旧 `?view=` 兼容。
- ✅ Bubble/Live2D mode window 已加入 Electron 导航保护：表现态窗口只承载 launcher route，非 launcher 导航会被 Electron 转发到主窗口或 Chat 单例，避免 112×112 气泡里显示完整 ChatView。
- ✅ React 主控台已对照旧 pywebview Control Center 补回 Hermes、Workspace、Runtime/Bridge、Tasks、Integrations、会话摘要和模式入口等主要信息。
- ✅ React 通用设置页已补回旧 pywebview 主要内容：Hermes 诊断、Workspace 详情、显示模式、助手资料、Bridge 状态/漂移/重启、集成状态、应用设置、备份管理和卸载预览/执行入口。
- ✅ UI Bridge 已补旧 MainWindowAPI 操作路由：Hermes terminal/recheck、Bridge restart、backup status/create/restore/delete/open-location、uninstall preview/run，React 只调用 HTTP route，不复制业务逻辑。
- ✅ React 通用设置页已从只读状态页推进为字段级编辑表单：可编辑显示模式、助手称呼、助手人设、Bridge 启用/host/port、托盘入口；只提交与当前配置不同的字段到 `/ui/settings`，保存后重新拉取后端状态。浏览器实机检查确认真实 Bridge 数据能填充表单、待保存状态能正确启用按钮、非法端口会显示自定义错误且修正后自动清除。
- ✅ React Bubble/Live2D 模式设置页已从 JSON 预览推进为字段级编辑表单：Bubble 支持窗口尺寸、默认位置百分比、置顶、吸附、启动展开、头像路径、默认展示、摘要条数、未读灯、自动淡出、透明度和主动观察；Live2D 支持模型/路径、窗口位置尺寸、缩放、置顶/Spaces、回复气泡、启动表现、点击行为、快捷输入、鼠标跟随、动作/表情/物理开关、主动观察和 Live2D TTS。表单只提交差异字段到 `/ui/settings`，保存后重新读取 `/ui/modes/{mode}/settings`。
- ✅ React Live2D 模式设置页已恢复旧 pywebview 的资源操作入口：`选择模型目录` 和 `导入资源包 ZIP` 由 Electron 原生文件选择器选取路径，Bridge 负责验证/导入并返回 `live2d_mode.model_path` 草稿；`打开导入目录` 走 Electron `shell.openPath`，`打开 Releases` 走 Electron `shell.openExternal`。选择/导入不会直接保存配置，仍需用户点击 `保存更改`。
- ✅ 已修复无桌面 preload/IPC 场景的两处回归：Live2D 资源区在没有 Electron 文件选择器时会显示内联“模型目录路径 / 资源包 ZIP 路径”输入框，按钮改为按路径检查/导入；Bubble 点击在无 `openView` IPC 时不再把 ChatView 塞进 112×112 表现态窗口，而是打开新的 `view=chat` 窗口/标签。
- ✅ 已收紧“React renderer ≠ 产品运行态”的边界：产品态必须通过 Electron 桌面壳运行，浏览器/Vite 只作为开发 fallback；`hermes-yachiyo` 在发现 `127.0.0.1:5174` 已有 Vite dev server 时会复用它并直接启动 Electron，不再因为 strict port 占用退出。Live2D 透明 pointer passthrough 改为实验能力，默认关闭，以“表现态可点击/可右键/可操作”优先；Live2D 舞台、角色、资源提示、回复气泡和快捷输入已从 Electron drag 区域中排除，避免 div 点击被窗口拖拽吞掉；需要测试透明穿透时显式设置 `HERMES_YACHIYO_LIVE2D_POINTER_PASSTHROUGH=1`。
- ✅ 已用 Downloads 中真实资源包 `hermes-yachiyo-live2d-yachiyo-20260423.zip` 做模拟导入验证：临时目录导入识别到 1 个 `.model3.json` 和 1 个 `.moc3`，草稿预览 `model_state=path_valid`，`renderer_entry` 指向 `八千代辉夜姬.model3.json`；直接调用 `/ui/live2d/archive/import` 路由函数并将导入根目录替换为临时目录后同样返回成功，真实 `config.live2d_mode.model_path` 保持为空，未持久化用户配置。
- ✅ Electron Bubble 已对照旧 pywebview 表现恢复头像气泡结构：Bridge 返回头像 data URI、`expand_trigger`、`suppress_status_dot`、主动桌面观察状态；React 恢复旧 `.bubble-launcher` / `.portrait` / `.status-dot` 视觉、未读/处理中/失败状态点、auto-hide 透明度公式、title 提示和 6px 拖拽点击阈值。
- ✅ Electron Live2D 已完成第一步旧表现还原：Bridge 返回 preview data URI、resource 状态和 renderer scaffold；React 恢复预览图 fallback、资源提示条、默认打开行为、回复气泡、快捷输入和处理中/有消息发光状态。真实 Pixi/Cubism 模型渲染、鼠标跟随和透明命中区域仍是下一步。
- ✅ Electron Live2D 已接入第一版真模型渲染路径：Bridge 新增 `/live2d/runtime` 与 `/live2d/runtime/{dependency_id}`，复用旧 pywebview 的 Pixi/Cubism 依赖缓存；React 按顺序加载 runtime scripts，使用 `renderer.model_url` 创建 Pixi Application 与 Live2DModel，模型加载成功后淡出 preview，失败时保留静态预览并显示错误；已补窗口内鼠标跟随 focus。透明命中区域、全局鼠标同步、动作/表情细节仍待迁移和实机验证。
- ✅ Electron Live2D 已接入第一版透明命中区域：Electron main 新增 `setLauncherPointerInteractive` 窄 IPC 并用 `BrowserWindow.setIgnoreMouseEvents(..., { forward: true })` 切换空白区域穿透；React 从 preview/canvas 生成 alpha mask，并把资源提示、回复气泡、快捷输入作为 UI 命中区域参与判定。仍需真实模型实机验证穿透、拖拽和全局鼠标同步边界。
- ✅ 文档新增 `docs/desktop-frontend-architecture.md`，`docs/ui-resource-architecture.md` 改为 legacy 记录。
- ✅ 手工启动基线：`hermes-yachiyo` 已确认走当前 venv 的 `apps.desktop_launcher:main`，启动后拉起 Vite `127.0.0.1:5174`、Electron、Python backend 与 Bridge `127.0.0.1:8420`；日志中 `/ui/dashboard` 与 `/ui/launcher?mode=bubble` 返回 200。验证结束时的 exit 130 来自手动中断，不是应用主动崩溃。
- ✅ 验证：`npm --prefix apps/frontend run build` 通过；设置页浏览器实机检查通过，包括通用设置、Bubble 模式设置和 Live2D 模式设置的真实数据填充、待保存状态、非法数值提示与恢复原值同步状态；新增 Live2D 资源入口后再次 `npm --prefix apps/frontend run build` 通过；真实 Downloads Live2D ZIP 临时导入和 Bridge 路由模拟导入通过；无桌面 IPC 浏览器场景验证通过：资源区显示内联 ZIP 路径输入且空路径提示正常，Bubble 点击保持 `view=bubble` 并通过 `window.open(...view=chat)` 打开对话；Electron 运行态短启动验证确认 Vite + Electron 进程能拉起；最新 `npm --prefix apps/frontend run build` → 通过，`dist/assets/index-BB_YwRRT.css` / `dist/assets/index-DklLRZW3.js`；最新 `pytest tests/test_desktop_launcher.py tests/test_ui_bridge_routes.py` → 18 passed；`pytest tests/test_ui_bridge_routes.py tests/test_mode_settings.py tests/test_desktop_launcher.py` → 45 passed；`pytest tests/test_ui_bridge_routes.py tests/test_main_api_modes.py tests/test_mode_settings.py tests/test_desktop_launcher.py` → 48 passed；`pytest tests/test_bridge_server.py tests/test_ui_bridge_routes.py tests/test_chat_bridge.py tests/test_mode_settings.py tests/test_chat_api.py tests/test_desktop_launcher.py` → 119 passed；相关 VS Code diagnostics 无错误。此前 `pytest tests/test_ui_bridge_routes.py tests/test_bridge_server.py tests/test_chat_api.py tests/test_mode_settings.py tests/test_runtime.py` → 57 passed；`npm --prefix apps/frontend run dev` 已拉起 Electron、Python backend，并看到 renderer 请求 `/ui/dashboard` 200。
- ✅ 最新追加验证：`npm --prefix apps/frontend run build` 通过；`/Users/cxldefontaine/个人项目/Hermes-Yachiyo/.venv/bin/python -m pytest tests/test_desktop_launcher.py tests/test_ui_bridge_routes.py` → 19 passed；VS Code diagnostics 对最新改动文件无错误。

### UI 资源分离第一阶段

- ✅ 新增 `apps/shell/ui/styles/` 作为 pywebview 前端视觉资源目录，主控台、安装页、聊天窗、模式设置、Bubble、Live2D 的视觉覆盖样式已从 Python 字符串迁出。
- ✅ 新增 `read_ui_asset()` / `inject_css()`，Python 只保留窗口创建、JS API 绑定和占位符替换，视觉层通过外部 CSS 注入。
- ✅ `pyproject.toml` 已加入 `apps.shell.ui` package-data，确保 editable / wheel 安装时 CSS 资源随包分发。
- ✅ 清理前期 UI 探索生成的一次性 patch 脚本，仓库只保留正式源码与资源文件。
- ✅ 相关验证：`/usr/local/bin/python3 -m pytest tests/test_chat_window.py tests/test_chat_bridge.py tests/test_mode_settings.py` → 89 passed。
- ✅ 资源加载验证：`read_ui_asset("styles/elegant.css")`、`_CHAT_HTML`、`_BUBBLE_HTML` 均确认能读取/注入外部 CSS。

### UI / Visual Overhaul (Gemini Aesthetic Pass)

- ✅ Refactored the UI across all modules (chat_window, window, settings, mode_settings, bubble, live2d) focusing strictly on visual representation without altering underlying Python execution logic or string injection markers.
- ✅ Replaced the rigid, high-contrast Tsukuyomi cyberpunk design with an elegant macOS-inspired "Glassmorphism" deep dark theme (`--bg-main: #0B0E14`).
- ✅ Implemented radial lighting, smooth transition animations, and subpixel-antialiased typography using `SF Pro Text` / system fonts.
- ✅ Successfully restored broken mode setting configurations (like bubble size and opacity configurations mapping in `settings.py`) by isolating CSS block injection instead of full string replacement.
