# Next Steps

## 当前优先项

### Phase 4 模型 / Agent / TTS 后续

1. 把 `apps/shell/provider_catalog_sync.py` 接入每日或低频后台更新机制，更新 `~/.hermes/yachiyo/provider-capabilities.json`；刷新失败不能阻塞应用启动。
2. 继续扩展 provider adapter：为 Xiaomi MiMo、OpenRouter、Gemini、DashScope、DeepSeek、MiniMax 等常用源沉淀 `/models` 路径、鉴权 header、模型 ID 规范、chat payload、vision payload 和错误归因。
3. 手工验证真实 provider：至少覆盖 Xiaomi MiMo `mimo-v2.5` / `mimo-v2-omni`、OpenRouter 视觉模型、Gemini、DashScope 和 DeepSeek；确认文本模型不能误保存为 vision Profile。
4. 完成 TTS 真实测试语义：HTTP TTS / Command TTS / API TTS 需要能配置 endpoint、voice、timeout、test text 并进行可证实测试；GPT-SoVITS 完整参数继续放在“主动关怀与桌面观察”页。
5. 为 `yachiyo_profile` 补第一版 ToolBroker：优先 OpenAI tool_calls，非 tool_calls 模型用 JSON fallback；不要默认宣称其能力等同 Hermes Agent。
6. 更新用户手册和截图索引中的旧命名：将“主动关怀语音”逐步统一为“主动关怀与桌面观察”，同时说明 GPT-SoVITS 是该页内的本地 TTS 服务模块。

1. 推送后验证 `Build macOS DMG`：`develop-latest` / `main-latest` 的 latest JSON 应包含 `changelog.generated_from=git`、`sections`、`commits` 和 `compare_url`；GitHub versioned release notes 与 rolling latest release notes 都应展示同一份“更新日志”。
2. 用下一版 develop DMG 验证应用更新页：检查更新后应显示“更新内容”，下载时有进度，下载完成后按钮切换为“安装并重启”；退出页面或重启后仍能识别已下载但未安装的更高版本 DMG。
3. 验证更新安装后的首次重开体验：Bridge/backend 尚未就绪时安装向导应显示“正在启动本地 Bridge”并自动重试，而不是直接红色报错；Bridge 可用后应自动恢复主控台或安装状态。
4. 验证自签名免费分发链路：latest DMG 可挂载；首次打开 `.app` 仍应是未知开发者/Gatekeeper 允许打开流程，而不是“移到废纸篓”的 DMG 挂载前拒绝。
5. 验证 Hermes Agent 脏安装修复：删掉损坏的 `~/.local/bin/hermes` 或保留旧 `~/.hermes/hermes-agent` 时，Yachiyo 应给出可修复状态；修复后图片链路测试不应再报 Hermes Python 环境缺失或 `env: ... Permission denied`。

1. 基于本轮新增的 `docs/user-manual.md`、`docs/screenshot-index.md`、`docs/experience-report-2026-05-05.md` 和 `docs/public/images/hermes-yachiyo/first-run/` 创建 VitePress 文档站点结构，并按安装、模型配置、桌面表现态、资源导入、工具中心、维护排障拆页。
2. VitePress 接入后检查所有 `/images/hermes-yachiyo/first-run/*.png` 引用是否能在站点中正确加载，并确认截图中 API Key 仍保持遮蔽。
3. 发布说明中补充本轮首用真实发现：GitHub 克隆中断时的手动安装 fallback、GPT-SoVITS 首次加载可能较慢、导入资源会显著增加备份体积、工具中心外部 Key 缺失属于预期受限状态。
4. 下一轮 DMG 复测时重点确认：主动关怀语音页能展示最近一次自动 TTS 错误；工具中心 `tts` 卡片能跳到主动关怀语音；备份页大资源提示可见；1x1/极小图片附件会被前端拦截。

1. 用最新 develop DMG 再做一次清机首装复测：安装 Hermes 后应滚动到模型配置区；不填 API Key 初始化会提示风险；初始化完成后进入主控台并默认打开 Bubble；再次点击 Dock 图标不能回到安装向导，也不能让 Bubble 消失。
2. 手工复测主动关怀截图链路：授权屏幕录制后触发主动桌面观察，应能把桌面截图作为会话附件传入图片识别；点击附件只在应用内查看，不应自动弹出 Chrome/默认浏览器预览。
3. 手工复测模型配置为 `auto + OpenRouter Base URL` 的图片输入：只有 `AUTO_API_KEY` 旧配置时也应被识别为 OpenRouter key 可用；主动关怀/手动发图不应再误报 API Key 无效；若模型确实不支持图片，应给出真实能力说明。
4. 手工复测 Live2D 资源 gate 与导入：清空 `~/.hermes/yachiyo/assets/live2d` 与 `live2d_mode.model_path` 后选择 Live2D，应跳到配置页且不启动 Live2D；导入中文/日文文件名 ZIP 后状态栏不应乱码，保存后真模型应能加载或至少静态预览可点击。
5. 手工复测主动关怀 TTS 本地服务链路：导入八千代 GPT-SoVITS 语音包后确认权重/参考音频路径和默认启动命令自动填充；测试“部署本地服务”“打开服务终端”“安装开机自启”“刷新状态”“保存并测试”，并确认 TTS 开启时主动消息不会早于音频附件出现。
6. 推送后确认 GitHub Actions `Build macOS DMG`：release tag/DMG 名称应带自动发布版本号；应用 release 不应再包含八千代 GPT-SoVITS 语音 ZIP；重跑同一个 workflow run 时应覆盖同名 DMG asset，不再因 `ReleaseAsset.name already exists` 失败。
7. 如需更新八千代 GPT-SoVITS 语音资源，手动触发 `Publish TTS Voice Assets` workflow，并提供已经调配好的 ZIP URL；确认它更新独立的 `tts-assets-yachiyo-gpt-sovits-v4` release。
8. 手工复测卸载：分别验证仅卸载资料、卸载前备份、包含 Hermes Agent、以及“同时删除当前应用本体”四条路径；删除 `.app` 是 macOS best-effort，失败时应提示用户手动移除 Applications 中的应用。
9. 后续打包前补一次真实 macOS 权限验收：主动关怀开启时是否能触发系统屏幕录制权限提示；未授权时是否回退关闭并显示原因；授权后主动桌面观察截图应真实附加到会话，而不是只生成文本 fallback。

10. 手工验证 Tool Center 修复：运行 `hermes doctor` 后确认 Doctor 已确认可用的工具不再显示“待检测”；确认 `browser` 与 `browser-cdp` 分开显示，CDP 受限不再误伤基础浏览器自动化。
11. 手工验证工具配置入口：在 Tool Center 分别打开 `web`、`image_gen`、`browser-cdp`、Home Assistant、MoA、RL 等当前 `hermes tools list` 暴露的配置，确认 env 字段只显示变量名和已配置状态，不显示密钥明文；保存后可点击“保存并测试 / 测试配置”查看静态配置检查与 Doctor 对应状态。
12. 联网与网页读取的真实启用仍需要用户提供 Firecrawl / Exa / Parallel / Tavily / Nous Gateway 之一；配置后应分别验证 `hermes doctor` 状态、`web` 工具调用和网页读取结果。
13. 图片生成的真实启用仍需要当前 Hermes 已知 provider 的密钥或 image_gen plugin；配置页先只列 Hermes 已暴露/已安装的 provider，后续若 Hermes 新增 provider，再由 tools/plugin manifest 驱动 UI 扩展。
14. 手工验证 Hermes 更新入口：点击“检查更新”确认能显示当前版本/落后 commits；确认默认 `--no-backup` 更新不会停在 stash 恢复确认，勾选完整备份时能清楚提示耗时风险，完成后自动刷新 tools list、Doctor 缓存和 Tool Center provider 列表。
15. 手工验证 Browser CDP 修补：点击“启动/连接本机 Chrome”后确认能写入 `browser.cdp_url=http://127.0.0.1:9222`；若自动启动失败，复制页面返回的手动命令执行后再次运行 Doctor。
16. 继续对照旧 pywebview Chat Window 做 React 体验补全：当前已恢复单例窗口、轮询流式/typewriter/Markdown/复制/会话切换、外链打开策略、基础快捷键和处理中取消入口；后续补更完整的错误边界和消息操作细节。
17. TODO：制定旧 pywebview shell 退休清单。等 Electron 前端稳定覆盖聊天、主控台、设置、Bubble、Live2D、安装引导、备份/卸载和打包启动链路后，直接删除所有 pywebview UI 代码与 legacy 入口，只保留 Electron + Bridge 路径。
18. 手工验证 AstrBot `/y ask` / `/y chat`：allow-list 拒绝、状态/截图/窗口摘要、自然语言低风险任务创建。
19. 调研 Hermes 原生 memory API / CLI / 存储边界，决定 `HermesMemoryAdapter` 第一版能力。
20. 继续推进 AstrBot 宿主绑定：在 AstrBot 插件框架中注册 `/y` 命令监听并调用 `on_y_command()`。
21. 继续对接 Hapi `/codex` 真实端点，保持 Codex CLI 执行不进入 Hermes-Yachiyo。
22. 完善任务持久化与安全策略模块（packages/tasking / packages/security），并补跨平台本地能力适配。
