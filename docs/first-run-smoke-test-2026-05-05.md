# 首次用户功能走查记录（2026-05-05）

测试目标：模拟第一次使用用户，从 `/Applications/Hermes-Yachiyo.app` 启动发布包，配置 Hermes Agent、模型、Live2D、TTS，并覆盖主控台、对话、Bubble、Live2D、主动关怀、工具中心、备份和卸载预览。

测试环境：

- 应用：`/Applications/Hermes-Yachiyo.app`
- Hermes-Yachiyo：`0.1.0`
- Hermes Agent：`0.12.0`
- 测试 HOME：`/tmp/hermes-yachiyo-doc-run-home`
- 测试 Bridge：`http://127.0.0.1:18420`
- 模型 Provider：Xiaomi MiMo
- 模型：`mimo-v2.5-pro`
- Base URL：`https://token-plan-cn.xiaomimimo.com/v1`

## 通过项

- 首次启动进入 `#/installer`，显示未安装状态和安装引导。
- GUI 模型配置向导可读取 Provider 列表。
- Xiaomi MiMo 配置保存成功，连接测试通过。
- Yachiyo 工作空间初始化成功。
- 主控台显示 Hermes ready、Workspace 已初始化、Bridge running。
- 图片链路测试通过，Yachiyo vision 能实际识别测试图。
- Chat Window 打开成功，文字对话成功返回。
- 图片附件保存成功；标准 PNG 图片完成 vision 预分析并返回正确颜色描述。
- Bubble 表现态打开成功，launcher 状态可读，ack 成功，快捷消息返回“收到~”。
- Live2D 资源 ZIP 导入成功，设置显示 `path_valid`，Live2D renderer enabled，画布非空。
- GPT-SoVITS 语音包导入成功，26 项 TTS 配置写入成功。
- GPT-SoVITS TTS 测试成功返回 `audio/wav`。
- 主动关怀手动触发成功，生成桌面观察消息；最后一次自动播报的 GPT-SoVITS `/tts` 请求返回 HTTP 400，但文本关怀和 Live2D 展示成功。
- 工具中心读取 22 个 Hermes toolsets 和 11 个配置卡片。
- 工具配置测试能正确提示缺少外部 API Key 或系统依赖。
- 诊断命令 `hermes config check` 和 `hermes doctor` 通过。
- Hermes 更新检查通过，显示 already up to date。
- 备份创建成功，生成约 465.3 MB ZIP。
- 卸载预览成功，生成目标清单和确认短语 `UNINSTALL`；未执行真实卸载。

## 发现的问题与边界

1. GUI 安装 Hermes Agent 时，GitHub 克隆出现 `RPC failed / curl 18 / early EOF / invalid index-pack output` 后安装退出。手动浅克隆 Hermes Agent 后，应用重新检测可继续流程。
2. 1x1 PNG 图片附件会被上游多模态 API 返回 `Multimodal data is corrupted or cannot be processed`；标准尺寸 PNG 正常。
3. 首次 GPT-SoVITS TTS 调用可能较慢；手动测试最终成功返回 `audio/wav`，推测首轮权重加载需要更长等待时间。
4. Live2D renderer 成功渲染，但日志中出现过一次 Live2D 渲染依赖下载证书校验告警：`CERTIFICATE_VERIFY_FAILED`。当前测试资源仍可显示，建议确认离线依赖缓存或证书链处理。
5. 手动主动关怀测试成功生成文本并展示到 Live2D；退出前一次自动主动关怀触发的 TTS 请求返回 HTTP 400，错误指向参考音频、语言、切分方式、媒体类型或 GPT-SoVITS API 版本。建议对自动触发路径增加更明确的错误提示。
6. 工具中心中 web、browser-cdp、image_gen 等外部工具在未配置对应 API Key 或系统依赖时会失败，提示清晰，属于预期受限状态。

## 建议写入发布说明

- 首次安装失败时建议用户重试或切换网络，并补充手动安装 Hermes Agent 的备用步骤。
- 图片附件建议使用正常尺寸截图或图片，不建议使用极小测试图。
- GPT-SoVITS 首次测试可能较慢，界面文案可提示“首次加载模型可能需要几十秒”。
- GPT-SoVITS 自动播报失败时，界面可展示参考音频、语言、切分方式、API 版本等排查项。
- Live2D 渲染依赖建议随包、随资源缓存，或在证书校验失败时给出可操作提示。
- 卸载操作前应强调自动备份路径。
