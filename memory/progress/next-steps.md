# Next Steps

1. 手工验证 Hermes 首次请求冷启动日志：确认首事件、首 token、完成耗时能帮助区分冷启动与模型执行时间。
2. 继续手工验证 Electron 固定入口的剩余交互：默认 `hermes-yachiyo` 已确认能拉起 Vite/Electron/Python backend/Bridge 且 `/ui/dashboard`、`/ui/launcher?mode=bubble` 返回 200；已补 5174 已有 Vite 时复用 dev server 并直接启动 Electron 的路径。后续还需在清理 `apps/frontend/node_modules` 后验证自动 `npm ci`，并手工走完聊天发送、设置保存、表现态重开/退出。
3. 手工验证最新窗口/路由语义：点击 Bubble、点击 Live2D、从主控台打开对话、从设置页返回主控台，都应走 Electron `openView` 并保持 Chat Window 单例；Bubble/Live2D 表现态窗口只能保留 launcher route，不应再显示完整 ChatView 或设置页。
4. 继续手工验证 React 设置页真实编辑控件：通用设置页、Bubble/Live2D 模式设置页和 Live2D 资源操作入口已支持字段级控件、差异保存、自定义校验、Electron 原生目录/ZIP 选择、无 IPC 时内联路径导入、打开导入目录和打开 Releases；通用设置已补 Hermes/Workspace/Bridge/集成/备份/卸载等旧版内容。下一步需要在 Electron 窗口内走完文件对话框选择、保存更改、备份恢复、卸载预览和重开 Live2D 表现态链路。
5. 继续对照旧 pywebview Chat Window 做 React 体验补全：当前已恢复单例窗口、轮询流式/typewriter/Markdown/复制/会话切换；后续补更完整的快捷键、链接打开策略、错误边界、处理中取消入口和消息操作细节。
6. 继续补齐 Electron 下的 Bubble / Live2D 表现态能力：当前已迁移真实状态、未读、最近回复、右键菜单、Bubble 旧头像气泡/状态点/auto-hide/拖拽点击阈值、Live2D 预览 fallback/资源提示/默认打开行为/快捷输入、第一版 Pixi/Cubism 模型加载、Bubble 靠边吸附、位置/尺寸持久化和表现态导航保护；Live2D 透明穿透先降为实验开关，默认以可点击/可右键/可操作优先。下一步用真实 Live2D 资源做手工验证，并继续补全全局鼠标同步、动作/表情细节和 TTS 触发状态。
7. 新增 macOS App 打包路径：React 只是 renderer，产品运行态必须是 Electron `.app`；下一步应增加无新依赖的本地 `.app` 打包脚本或明确引入 electron-builder/electron-forge，确保用户可以直接启动 Hermes-Yachiyo.app，而不是长期依赖终端 dev server。
8. 制定旧 pywebview shell 退休清单：确认哪些测试、能力和窗口行为已由 Electron/Bridge 覆盖，再逐步删除 legacy 入口。
9. 手工验证备份/卸载：在设置页主动生成 ZIP 备份；确认备份内有 `manifest.json`、应用配置、完整 `yachiyo-workspace`、`chat.db`、缓存/日志/导入资源；验证备份生成期间目录内不会出现正式命名的半成品 ZIP，默认自动清理保留最近 10 份、覆盖最近一次备份、恢复最近备份、管理备份中的删除/打开位置/恢复此版本、损坏/超限 ZIP 导入会失败且不留下部分输出文件、卸载确认短语首尾空白容错、空 `.hermes`/`hermes` 目录会跳过，以及卸载前生成备份和安装引导导入最近备份。
10. 手工验证主动桌面观察：关闭状态、Hermes 未就绪 blocker、vision 受限 blocker、成功创建低风险截图任务、ack 清除提示、失败间隔后重试。
11. 手工验证 TTS：默认关闭无感、`http` endpoint 调用、`command` 本地命令调用、错误配置不影响聊天。
12. 手工验证 AstrBot `/y ask` / `/y chat`：allow-list 拒绝、状态/截图/窗口摘要、自然语言低风险任务创建。
13. 调研 Hermes 原生 memory API / CLI / 存储边界，决定 `HermesMemoryAdapter` 第一版能力。
14. 继续推进 AstrBot 宿主绑定：在 AstrBot 插件框架中注册 `/y` 命令监听并调用 `on_y_command()`。
15. 继续对接 Hapi `/codex` 真实端点，保持 Codex CLI 执行不进入 Hermes-Yachiyo。
16. 完善任务持久化与安全策略模块（packages/tasking / packages/security），并补跨平台本地能力适配。
