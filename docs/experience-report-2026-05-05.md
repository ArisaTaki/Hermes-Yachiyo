# Hermes-Yachiyo 首用体验报告（2026-05-05）

测试目标：模拟完全第一次使用的 macOS 用户，从 `/Applications/Hermes-Yachiyo.app` 启动发布包，完成模型配置、Live2D 导入、GPT-SoVITS 导入，并覆盖主控台、对话、图片、Bubble、Live2D、主动关怀、工具中心、诊断、备份和卸载预览。

测试方式：使用隔离 HOME、独立 Bridge 端口和独立 Electron profile，避免污染当前用户真实环境。测试结束前未执行真实卸载。

## 环境摘要

- 应用：`/Applications/Hermes-Yachiyo.app`
- Hermes Agent：`0.12.0`
- 测试 Bridge：`http://127.0.0.1:18420`
- 模型 Provider：Xiaomi MiMo
- 模型：`mimo-v2.5-pro`
- Base URL：`https://token-plan-cn.xiaomimimo.com/v1`
- Live2D 资源包：`【雪熊企划】八千代辉夜姬.zip`
- GPT-SoVITS 资源包：`Hermes-Yachiyo-yachiyo-gpt-sovits-v4.zip`
- 截图素材：`docs/public/images/hermes-yachiyo/first-run/`

## 总体结论

Hermes-Yachiyo 的第一个 DMG 包已经能完成核心首用闭环。模型配置、工作空间初始化、文本对话、图片链路、Live2D 导入渲染、Bubble 快捷消息、TTS 手动测试、工具中心、诊断、备份和卸载预览都跑通了。

真实首用的主要摩擦点集中在外部依赖：GitHub 网络导致 GUI 安装 Hermes Agent 失败一次，未配置外部工具 Key 时工具中心显示受限，主动关怀自动 TTS 路径出现一次 GPT-SoVITS HTTP 400。这些问题没有阻断主体流程，但适合写进首版文档和发布说明。

## 已通过功能

| 功能 | 结果 | 证据截图 |
|---|---|---|
| 首次启动安装页 | 通过 | `/images/hermes-yachiyo/first-run/01-installer-first-launch.png` |
| Hermes Agent 检测 | 通过 | `/images/hermes-yachiyo/first-run/04-installer-detected-hermes.png` |
| Xiaomi MiMo 配置保存 | 通过 | `/images/hermes-yachiyo/first-run/05-model-config-filled.png` |
| 模型连接测试 | 通过 | `/images/hermes-yachiyo/first-run/07-model-config-verified.png` |
| Yachiyo 工作空间初始化 | 通过 | `/images/hermes-yachiyo/first-run/08-workspace-initialized-dashboard.png` |
| 主控台就绪 | 通过 | `/images/hermes-yachiyo/first-run/09-dashboard-ready.png` |
| 图片链路测试 | 通过 | `/images/hermes-yachiyo/first-run/11-image-chain-verified.png` |
| 文本对话 | 通过 | `/images/hermes-yachiyo/first-run/15-chat-text-replied.png` |
| 图片附件识别 | 通过 | `/images/hermes-yachiyo/first-run/18-chat-image-replied.png` |
| Bubble 窗口 | 通过 | `/images/hermes-yachiyo/first-run/26-bubble-window-ready.png` |
| Bubble 快捷消息 | 通过 | `/images/hermes-yachiyo/first-run/27-bubble-quick-message-replied.png` |
| Live2D 资源导入 | 通过 | `/images/hermes-yachiyo/first-run/23-settings-live2d-imported.png` |
| Live2D 桌面渲染 | 通过 | `/images/hermes-yachiyo/first-run/25-live2d-window-rendered.png` |
| GPT-SoVITS 资源导入 | 通过 | `/images/hermes-yachiyo/first-run/29-tts-settings-imported-saved.png` |
| GPT-SoVITS 手动测试 | 通过 | `/images/hermes-yachiyo/first-run/31-tts-test-success.png` |
| 主动关怀文本生成 | 通过 | `/images/hermes-yachiyo/first-run/34-proactive-live2d-attention.png` |
| 工具中心概览 | 通过 | `/images/hermes-yachiyo/first-run/35-tools-overview.png` |
| 诊断命令 | 通过 | `/images/hermes-yachiyo/first-run/40-diagnostics-config-check.png`、`/images/hermes-yachiyo/first-run/41-diagnostics-doctor.png` |
| Hermes 更新检查 | 通过 | `/images/hermes-yachiyo/first-run/39-tools-update-check.png` |
| 备份创建 | 通过 | `/images/hermes-yachiyo/first-run/42-settings-general-backup-created.png` |
| 卸载预览 | 通过，未执行卸载 | `/images/hermes-yachiyo/first-run/43-settings-uninstall-preview.png` |

## 详细体验记录

### 1. 安装阶段

首次启动体验清晰，用户能直接看到 Hermes Agent 未安装和下一步操作。GUI 安装任务有实时状态，但这次真实运行遇到了 GitHub 传输中断：

```text
RPC failed; curl 18 transfer closed with outstanding read data remaining
early EOF
invalid index-pack output
```

这类错误属于网络层中断。手动使用 GitHub codeload tarball 安装 Hermes Agent 后，应用重新检测成功，后续流程可以继续。

体验建议：

- 安装失败页可以增加“重试”、“切换网络后重试”、“手动安装后重新检测”的明确分支。
- 文档中需要保留这类 GitHub 传输失败的排障说明。

### 2. 模型与工作空间

Xiaomi MiMo 配置流程顺畅。Provider、模型、Base URL、API Key 的字段明确，连接测试结果能直接反馈。API Key 截图不会显示明文。

工作空间初始化完成后，主控台能正确展示 Hermes ready、Workspace ready、Bridge running。这个状态很适合放在“安装完成”文档页，用户看了就知道已经可以开始使用。

### 3. 对话与图片

文本对话成功返回。图片附件使用标准 PNG 红绿测试图，vision 链路正确描述左侧红色、右侧绿色，说明图片预分析和主模型整合链路可用。

边界记录：

- 极小图片可能被上游多模态服务判定为不可处理。
- 文档应建议用户使用正常尺寸截图或照片。

### 4. Bubble

Bubble 设置保存后能打开桌面小窗。快捷消息接口真实返回“收到~”，说明 Bubble 到 ChatBridge 的链路可用。

体验建议：

- 快捷输入成功后，Bubble 内可考虑给一个更明确的发送中或完成反馈。
- 对普通用户，Bubble 可以作为“轻量常驻入口”单独做一页说明。

### 5. Live2D

Live2D ZIP 导入后，设置页识别出模型、路径和表达式。保存配置后，Live2D 窗口真实渲染，画布非空。主动关怀消息也能显示在 Live2D 窗口。

体验建议：

- 导入成功页的信息很完整，适合在文档中截图解释。
- 如果 Live2D 渲染依赖下载失败，应在 UI 中给出更直接的可操作提示，例如重试下载、查看资源目录、查看日志。

### 6. GPT-SoVITS 与主动关怀语音

语音包导入成功，权重、参考音频和 API 地址能自动填入。手动“保存并测试”返回 `audio/wav`，UI 显示 `TTS 测试已完成`。

主动关怀文本生成成功，能根据桌面状态生成提醒。最后一次自动触发的 GPT-SoVITS `/tts` 请求返回 HTTP 400，同时状态里显示 `audio_ready: true`。错误提示指向参考音频、语言、切分方式、媒体格式或 GPT-SoVITS API 版本。

体验建议：

- 手动 TTS 测试成功和主动关怀自动播报应分开记录状态。
- 自动播报失败时，Live2D 或 TTS 页最好展示最近一次 TTS 错误。
- 文档应提示首次加载权重可能较慢。

### 7. 工具中心

工具中心能读取 22 个 Hermes toolsets 和多个配置卡片。未配置 Web、Browser CDP、Image Gen 外部依赖时，测试结果能清楚显示缺失项：

- Web：缺少 Firecrawl 或其他 Web Provider Key。
- Browser CDP：缺少 CDP Endpoint。
- Image Gen：缺少 FAL Key。
- TTS：当前 Hermes 工具配置中心返回未知配置项，Yachiyo 的主动关怀 TTS 应以“主动关怀语音”页为准。

体验建议：

- 文档里要说明“工具中心受限”不等于 Yachiyo 主功能不可用。
- `tts` 在工具中心返回未知配置项容易让用户困惑，建议 UI 文案提示它不同于 Yachiyo 主动关怀语音。

### 8. 诊断、更新、备份、卸载

`hermes config check` 和 `hermes doctor` 都能在 UI 内运行并展示输出。Hermes 更新检查返回当前已是最新。

备份在导入 Live2D 与 GPT-SoVITS 后成功生成，大小 `465.3 MB`。这说明大资源也进入了备份范围，符合“可恢复首用成果”的预期。

卸载预览显示将删除 Hermes-Yachiyo 应用配置和工作空间，GPT-SoVITS LaunchAgent 不存在时会标记跳过。测试没有执行真实卸载。

体验建议：

- 备份页需要强调导入资源越大，备份越大。
- 卸载页的“预览清单”很适合写进文档，降低用户误删焦虑。

## 文档素材建议

- 快速安装页：01、03、04、07、08、09。
- 日常使用页：12、15、16、18。
- 桌面表现态页：20、21、25、26、27、34。
- 资源导入页：22、23、24、28、29、31。
- 高级配置页：35、36、37、38、39、40、41。
- 维护页：42、43。

## 发布前建议

1. 在首用安装页增加网络失败排障文案。
2. 在图片上传说明中提醒使用正常尺寸图片。
3. 在 GPT-SoVITS 页面提示首次加载权重可能较慢。
4. 将主动关怀自动播报的最近错误同步显示到 TTS 设置页。
5. 在工具中心把 Hermes 工具 TTS 与 Yachiyo 主动关怀 TTS 的差异说清楚。
6. 在备份页提醒导入资源会显著增加备份体积。
