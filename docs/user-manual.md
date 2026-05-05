# Hermes-Yachiyo 使用手册

适用对象：第一次安装并使用 Hermes-Yachiyo 的 macOS 用户。

适用版本：`/Applications/Hermes-Yachiyo.app` 发布包，实测 Hermes Agent `0.12.0`。

本文截图来自一次隔离 HOME 的真实首用流程。截图素材已放在 `docs/public/images/hermes-yachiyo/first-run/`，VitePress 中可直接使用 `/images/hermes-yachiyo/first-run/<文件名>.png` 引用。

## 1. 应用定位

Hermes-Yachiyo 是桌面优先的本地个人 Agent 应用。它把 Hermes Agent 包装成常驻桌面助手，并提供主控台、完整对话窗口、Bubble 悬浮入口、Live2D 角色入口、主动关怀、语音播报、资源导入、工具配置、诊断、备份和卸载管理。

应用本体不内置所有大资源：

- Hermes Agent 会在首次使用时安装或被自动检测。
- Live2D 模型资源需要导入 ZIP。
- GPT-SoVITS 八千代语音包需要导入 ZIP。
- GPT-SoVITS API 服务需要本机已有或由设置页配置启动。

## 2. 首次启动

1. 将 `Hermes-Yachiyo.app` 放入 `/Applications`。
2. 打开应用。
3. 首次启动会进入安装引导。
4. 点击“安装 Hermes Agent”，等待安装任务完成。
5. 安装完成后，点击“重新检测”或继续进入模型配置。

![首次启动安装页](/images/hermes-yachiyo/first-run/01-installer-first-launch.png)

安装过程中会显示实时进度。

![安装运行中](/images/hermes-yachiyo/first-run/02-installer-install-running.png)

如果安装阶段出现 `RPC failed`、`curl 18`、`early EOF` 或 `invalid index-pack output`，通常是 GitHub 克隆中断。可以重试，切换网络或代理后再安装。也可以手动安装 Hermes Agent，再回到应用点击“重新检测”。

![安装失败示例](/images/hermes-yachiyo/first-run/03-installer-install-result.png)

当应用检测到 Hermes Agent 后，会显示 Hermes 版本、命令路径、工作空间状态和模型配置表单。

![检测到 Hermes Agent](/images/hermes-yachiyo/first-run/04-installer-detected-hermes.png)

## 3. 配置模型

在“模型配置向导”填写 Provider、模型、Base URL 和 API Key。

实测配置：

- Provider：`Xiaomi MiMo`
- 模型：`mimo-v2.5-pro`
- Base URL：`https://token-plan-cn.xiaomimimo.com/v1`
- API Key：填写自己的密钥

API Key 输入框会以密码形式显示，截图中不会显示明文。

![模型配置填写完成](/images/hermes-yachiyo/first-run/05-model-config-filled.png)

点击“保存并测试连接”。测试过程中按钮会进入运行状态。

![模型连接测试中](/images/hermes-yachiyo/first-run/06-model-config-testing.png)

通过后页面会显示连接已验证。

![模型连接通过](/images/hermes-yachiyo/first-run/07-model-config-verified.png)

## 4. 初始化工作空间

模型配置通过后点击“初始化工作空间”。应用会创建：

```text
~/.hermes/yachiyo/
```

这里会保存聊天数据库、导入资源、附件缓存、日志、备份相关数据和 Yachiyo 工作空间配置。

![工作空间初始化完成](/images/hermes-yachiyo/first-run/08-workspace-initialized-dashboard.png)

初始化后会进入主控台。

![主控台就绪](/images/hermes-yachiyo/first-run/09-dashboard-ready.png)

## 5. 图片链路测试

如果要使用图片附件，需要在主控台点击“保存并测试图片链路”。对于 Xiaomi MiMo，Yachiyo 会使用 vision 预分析图片，再把文本结果交给主模型。

![图片链路测试中](/images/hermes-yachiyo/first-run/10-image-chain-testing.png)

测试通过后会显示图片链路可用。实测返回结果正确识别测试色块。

![图片链路测试通过](/images/hermes-yachiyo/first-run/11-image-chain-verified.png)

## 6. 对话窗口

点击“打开对话”进入完整 Chat Window。

支持：

- 文字对话。
- 新建或删除对话。
- 停止正在处理的任务。
- 图片附件。
- 粘贴图片。
- 查看历史会话。

![空对话窗口](/images/hermes-yachiyo/first-run/12-chat-window-empty.png)

输入文字后点击发送。

![输入文字消息](/images/hermes-yachiyo/first-run/13-chat-text-composed.png)

发送过程中会显示处理中状态。

![文字发送中](/images/hermes-yachiyo/first-run/14-chat-text-sending.png)

模型返回后消息进入完成状态。

![文字回复完成](/images/hermes-yachiyo/first-run/15-chat-text-replied.png)

图片附件可以通过附件按钮添加。建议使用正常尺寸图片，避免 1x1 之类极小图片被上游多模态服务判定为无法处理。

![图片已附加](/images/hermes-yachiyo/first-run/16-chat-image-attached.png)

发送图片后，Yachiyo 会先进行视觉预分析。

![图片发送中](/images/hermes-yachiyo/first-run/17-chat-image-sending.png)

实测标准 PNG 色块图能被正确描述。

![图片回复完成](/images/hermes-yachiyo/first-run/18-chat-image-replied.png)

## 7. 应用设置

应用设置包含通用配置、备份策略、Bubble、Live2D、Bridge、用户称呼和人格提示词。

![通用设置](/images/hermes-yachiyo/first-run/19-settings-general.png)

部分设置即时生效；涉及 Bridge 端口、应用启动行为、表现态窗口大小的设置会提示需要重启 Bridge、重启表现态或重启应用。

## 8. Bubble 模式

Bubble 是轻量悬浮入口。它可以显示摘要、未读状态、处理中状态和最近回复，点击后可打开完整对话窗口。

Bubble 设置支持：

- 宽高。
- 透明度。
- 常驻置顶。
- 边缘吸附。
- 默认显示内容。
- 摘要条数。
- 头像。
- 主动关怀开关。

![Bubble 设置](/images/hermes-yachiyo/first-run/20-settings-bubble.png)

保存后会显示设置已同步。

![Bubble 设置保存](/images/hermes-yachiyo/first-run/21-settings-bubble-saved.png)

打开 Bubble 表现态后会出现小窗。

![Bubble 窗口](/images/hermes-yachiyo/first-run/26-bubble-window-ready.png)

通过 Bubble 快捷消息发送内容后，回复会进入同一个对话系统并更新气泡状态。

![Bubble 快捷消息回复](/images/hermes-yachiyo/first-run/27-bubble-quick-message-replied.png)

## 9. Live2D 模式

Live2D 是角色桌面入口。首次使用需要导入 Live2D ZIP。

导入步骤：

1. 打开“应用设置”。
2. 选择 Live2D 设置。
3. 点击“导入资源包 ZIP”。
4. 选择 Live2D 资源包。
5. 等待资源识别完成。
6. 保存设置。
7. 重新打开 Live2D 表现态。

导入前页面会提示资源未配置。

![Live2D 导入前](/images/hermes-yachiyo/first-run/22-settings-live2d-before-import.png)

导入成功后，设置页会显示资源已就绪、有效模型路径、表达式和模型信息。

![Live2D 导入成功](/images/hermes-yachiyo/first-run/23-settings-live2d-imported.png)

保存详细设置后可启用回复气泡、快捷输入、鼠标跟随、表达式和物理。

![Live2D 设置保存](/images/hermes-yachiyo/first-run/24-settings-live2d-saved.png)

打开 Live2D 表现态后应能看到角色画布。实测画布非空，模型、表情和本地资源路径均被正确加载。

![Live2D 渲染完成](/images/hermes-yachiyo/first-run/25-live2d-window-rendered.png)

主动关怀触发后，Live2D 窗口会展示关怀消息。

![Live2D 主动关怀](/images/hermes-yachiyo/first-run/34-proactive-live2d-attention.png)

## 10. 主动关怀

主动关怀会按间隔读取桌面截图，通过视觉模型判断是否需要提醒用户，然后生成适合桌面入口展示的消息。

使用步骤：

1. 在主控台或表现态设置中启用主动桌面观察。
2. 设置观察间隔，最低为 300 秒。
3. 设置触发概率。
4. 如果需要语音，先配置主动关怀语音。
5. 保存后可点击测试触发。

macOS 可能会要求屏幕录制权限。请到“系统设置 -> 隐私与安全性 -> 屏幕录制”允许 Hermes-Yachiyo。

![完整配置后主控台](/images/hermes-yachiyo/first-run/32-dashboard-after-full-config.png)

## 11. 主动关怀语音

打开“主动关怀语音”页面后，可以选择：

- 不启用语音。
- HTTP TTS。
- 本地命令 TTS。
- GPT-SoVITS 本地服务。

八千代 GPT-SoVITS 语音包导入步骤：

1. 选择 `GPT-SoVITS 本地服务`。
2. 点击“导入语音包 ZIP”。
3. 选择语音包 ZIP。
4. 确认 GPT 权重、SoVITS 权重、参考音频路径已自动填入。
5. 保存设置。
6. 点击测试语音。

![TTS 导入前](/images/hermes-yachiyo/first-run/28-tts-settings-before-import.png)

导入成功后，页面会自动填入权重、参考音频、语言、切分方式和 API 地址。

![TTS 导入并保存](/images/hermes-yachiyo/first-run/29-tts-settings-imported-saved.png)

点击测试后会显示运行状态。

![TTS 测试中](/images/hermes-yachiyo/first-run/30-tts-test-running.png)

测试成功后会显示 `TTS 测试已完成`。首次加载权重可能较慢，建议给第一次测试留出更长等待时间。

![TTS 测试成功](/images/hermes-yachiyo/first-run/31-tts-test-success.png)

主动关怀语音配置完成后可在该页复查开关、触发概率和 GPT-SoVITS 状态。

![主动关怀语音配置](/images/hermes-yachiyo/first-run/33-proactive-tts-enabled.png)

## 12. 工具中心

工具中心用于查看 Hermes 工具组和外部工具配置状态。

常见状态：

- `available`：工具已可用。
- `limited`：工具存在但缺少依赖或 API Key。
- `missing API Key`：需要在工具中心填写对应密钥。
- `system dependency not met`：需要安装浏览器、CDP、外部服务或系统依赖。

![工具中心概览](/images/hermes-yachiyo/first-run/35-tools-overview.png)

Web 工具需要 Firecrawl、Exa、Parallel 或 Tavily 等外部配置。未配置时测试会清楚列出缺失项。

![Web 工具测试](/images/hermes-yachiyo/first-run/36-tools-web-test-result.png)

Browser CDP 工具需要可连接的 Chrome CDP 端点。

![Browser CDP 工具测试](/images/hermes-yachiyo/first-run/37-tools-browser-cdp-test-result.png)

Image Generation 工具需要对应图片服务 Key。实测默认 FAL 配置在未填 Key 时会失败并提示缺失字段。

![Image Gen 工具测试](/images/hermes-yachiyo/first-run/38-tools-image-gen-test-result.png)

工具中心也提供 Hermes 更新检查入口。

![Hermes 更新检查](/images/hermes-yachiyo/first-run/39-tools-update-check.png)

## 13. 诊断

诊断页可以直接运行受控命令，包括：

- `hermes config check`
- `hermes doctor`
- `hermes auth list`

配置检查会列出必需与可选配置项。

![配置检查](/images/hermes-yachiyo/first-run/40-diagnostics-config-check.png)

Doctor 会检查 Python、依赖、目录结构、命令安装和外部工具。

![Hermes Doctor](/images/hermes-yachiyo/first-run/41-diagnostics-doctor.png)

## 14. 备份与恢复

应用维护页可以立即生成备份。备份默认保存在：

```text
~/Hermes-Yachiyo-backups/
```

备份包含：

- Yachiyo 应用配置。
- Yachiyo 工作空间。
- 聊天数据库。
- 导入资源。
- 附件缓存和日志。

实测在导入 Live2D 与 GPT-SoVITS 资源后，完整备份大小为 `465.3 MB`。

![备份生成后](/images/hermes-yachiyo/first-run/42-settings-general-backup-created.png)

恢复备份会把备份内容导回本地配置和工作空间。恢复前建议先确认当前数据是否需要另存。

## 15. 卸载

卸载页会先生成可删除清单，并要求输入确认短语 `UNINSTALL`。测试中只验证了预览清单，没有执行真实卸载。

支持的范围包括：

- 仅删除 Hermes-Yachiyo 配置和工作空间。
- 是否保留配置快照。
- 是否同时卸载 GPT-SoVITS LaunchAgent。

![卸载预览](/images/hermes-yachiyo/first-run/43-settings-uninstall-preview.png)

## 16. 常见问题

### Hermes Agent 安装失败

如果看到 `RPC failed`、`early EOF`、`invalid index-pack output`，通常是 GitHub 网络传输中断。请重试、切换网络或代理，或手动安装 Hermes Agent 后回到应用点击“重新检测”。

### 模型连接失败

检查 Provider、模型、Base URL 和 API Key。保存配置后重新点击“保存并测试连接”。

### 图片不可用

先点击“保存并测试图片链路”。请避免使用极小图片，建议使用正常尺寸截图或图片。

### Live2D 没有显示角色

确认资源包已导入，并且设置页显示 `资源已就绪`。保存模型路径后需要重新打开 Live2D 表现态。

### TTS 没声音

确认语音 Provider 已启用。GPT-SoVITS 语音包导入成功只代表音色路径就绪，还需要本地 API 服务可达。首次加载权重可能需要几十秒。

如果 GPT-SoVITS 返回 HTTP 400，请检查参考音频路径、文本语言、参考音频语言、切分方式、媒体类型，以及本地 GPT-SoVITS API 版本是否与 Hermes-Yachiyo 的请求格式兼容。

### 主动关怀不触发

确认主动桌面观察已开启，触发概率不是 0，macOS 屏幕录制权限已授权，并等待至少一个观察间隔。
