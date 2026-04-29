# Next Steps

1. 手工验证 Hermes 首次请求冷启动日志：确认首事件、首 token、完成耗时能帮助区分冷启动与模型执行时间。
2. 手工验证备份/卸载：在设置页主动生成 ZIP 备份；确认备份内有 `manifest.json`、应用配置、完整 `yachiyo-workspace`、`chat.db`、缓存/日志/导入资源；验证默认自动清理保留最近 10 份、覆盖最近一次备份、恢复最近备份、管理备份中的删除/打开位置/恢复此版本、卸载确认短语首尾空白容错、空 `.hermes`/`hermes` 目录会跳过，以及卸载前生成备份和安装引导导入最近备份。
3. 手工验证 Control Center 共通设置：修改助手称呼、人设、Bridge 地址/端口后按钮启用；改回当前值后 pending 自动消失。
4. 手工验证工作空间创建时间：仪表盘与设置页均显示本地可读格式，而不是原始 ISO 字符串。
5. 手工验证 Chat Window：消息文本可选择；复制图标可点击，成功后变对勾；重复点击 Bubble/Live2D 仅置前当前 `_chat_window.native` 对应窗口，不再把同标题白屏残留壳置前；创建中连续点击也不会重复创建；关闭后立即重开应创建真实聊天 UI。
6. 手工验证 Bubble 设置：尺寸 `80-192` 的视觉变化、默认位置百分比、右下角默认启动、拖动释放后靠边吸附、位置/置顶/头像重启后生效。
7. 手工验证 Bubble 呼吸灯：处理中为黄色；Chat Window 关闭后完成/失败分别转绿色/红色；Chat Window 打开时不显示状态点；点击查看后清除未读。
8. 手工验证 Live2D 启动策略：`default_open_behavior` 只影响回复泡泡/快捷输入，`auto_open_chat_window` 仅在模式启动时打开一次且需重启当前模式。
9. 手工验证主动桌面观察：关闭状态、Hermes 未就绪 blocker、vision 受限 blocker、成功创建低风险截图任务、ack 清除提示、失败间隔后重试。
10. 手工验证 TTS：默认关闭无感、`http` endpoint 调用、`command` 本地命令调用、错误配置不影响聊天。
11. 手工验证 AstrBot `/y ask` / `/y chat`：allow-list 拒绝、状态/截图/窗口摘要、自然语言低风险任务创建。
12. 调研 Hermes 原生 memory API / CLI / 存储边界，决定 `HermesMemoryAdapter` 第一版能力。
13. 继续推进 AstrBot 宿主绑定：在 AstrBot 插件框架中注册 `/y` 命令监听并调用 `on_y_command()`。
14. 继续对接 Hapi `/codex` 真实端点，保持 Codex CLI 执行不进入 Hermes-Yachiyo。
15. 后续再推进真实 Live2D renderer / moc3 动作和更精细的角色动作/表情表现。
16. 完善任务持久化与安全策略模块（packages/tasking / packages/security），并补跨平台本地能力适配。
