# TTS 音色资源包说明

Oha-Yachiyo 的八千代 GPT-SoVITS 音色包是可选资源，和应用 DMG 分开发布。

这个 ZIP 是已经调配好的八千代音色资源，不需要随着 `develop` / `main` 的应用构建重复生成。应用 release 只发布 DMG；音色包放在独立的资源 release 中，用户需要时在“主动关怀与桌面观察”页面导入。

## 去哪里下载

请从 GitHub Releases 的独立资源页下载：

- <https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo/releases/tag/tts-assets-yachiyo-gpt-sovits-v4>

资源文件名：

```text
Oha-Yachiyo-yachiyo-gpt-sovits-v4.zip
```

## 如何导入

1. 启动 Oha-Yachiyo。
2. 打开主控台。
3. 打开侧栏“主动关怀”，进入“主动关怀与桌面观察”页面。
4. 选择 `GPT-SoVITS 本地服务`。
5. 点击“下载音色包”下载 ZIP。
6. 点击“导入音色包 ZIP”导入。
7. 保存语音设置。

导入后，Yachiyo 会把 GPT 权重、SoVITS 权重和参考音频路径填入主动关怀 TTS 设置。

## 本地服务说明

音色包只包含八千代音色权重和参考音频，不包含 GPT-SoVITS 服务本体、基础预训练模型或运行时。

如果要真正播放主动关怀语音，还需要在本机运行 GPT-SoVITS API 服务。“主动关怀与桌面观察”页面提供：

- GPT-SoVITS 服务目录
- 服务启动命令
- 部署运行时/基础模型
- 打开调试终端
- 安装/移除当前用户的 macOS LaunchAgent
- 刷新服务状态

“部署运行时/基础模型”会在 GPT-SoVITS 服务目录中准备 Python 环境和基础预训练模型。LaunchAgent 只负责启动用户已经配置好的本地服务。

模型配置页的 `文字转语音` tab 只负责登记 TTS 来源和 voice/profile id。`GSV TTS(Local)` 会跳转到“主动关怀与桌面观察”页面，完整的 GPT-SoVITS 服务目录、启动命令、参考音频、权重和测试参数仍在该页面维护。

## 发布方式

语音资源 release 由 `Publish TTS Voice Assets` workflow 手动触发。

该 workflow 只接收一个已经存在的 ZIP URL，并把它上传到独立 release；它不会从仓库重新打包音色，也不会在应用 DMG 构建时重复生成音色包。
