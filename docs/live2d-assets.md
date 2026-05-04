# Live2D 资源包说明

Hermes-Yachiyo 的 Live2D 模型资源包是可选内容。

程序本体不会再把大型 Live2D 二进制文件作为主仓库默认依赖。要使用自己的 Live2D 模型，请先下载资源包，再导入到本机用户目录。

## 去哪里下载

请从 GitHub Releases 下载 Live2D 资源包：

- <https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo/releases>

下载后，解压到下面的目录：

```text
~/.hermes/yachiyo/assets/live2d/
```

## 默认导入路径

推荐目录：

```text
~/.hermes/yachiyo/assets/live2d/
```

如果你没有在设置里手动填写模型路径，Hermes-Yachiyo 会默认在这个目录中自动查找可用的 Live2D 模型。

如果你把资源包放在别的位置，也可以在 Live2D 设置中手动指定模型路径。设置页支持直接“选择模型目录”以及“导入资源包 ZIP”，不需要用户自己手动查找完整路径。

## 解压后的目录结构示例

```text
~/.hermes/yachiyo/assets/live2d/
└── yachiyo/
    ├── yachiyo.model3.json
    ├── yachiyo.moc3
    ├── yachiyo.physics3.json
    ├── expressions/
    │   └── smile.exp3.json
    └── textures/
        ├── texture_00.png
        └── texture_01.png
```

有效模型目录至少需要下面任意一种文件：

- `.model3.json`
- `.moc3`

如果只有占位目录、说明文件或错误的解压层级，程序不会把它误判为有效模型。

## 如何在设置里启用

1. 启动 Hermes-Yachiyo。
2. 打开 Control Center。
3. 点击“Live2D 设置”。
4. 如果你下载的是 Releases 资源包，直接点击“导入资源包 ZIP”。
5. 如果模型已经在本地目录中，点击“选择模型目录”。
6. 如果资源包已经解压到默认目录，也可以把“模型路径”留空。
7. 设置页会立即刷新模型状态和当前生效路径。

## 未导入资源时的表现

未导入资源包时，程序仍然可以正常使用：

- Hermes-Yachiyo 正常启动
- Bubble / Chat Window / Control Center 不受影响
- Live2D 模式仍然作为角色聊天壳 / 桌面入口存在
- 设置页会提示你去 Releases 下载资源包
- Live2D 模式会明确提示“未检测到有效 Live2D 模型资源”

## 已导入资源后如何识别

资源包放到默认目录后：

- 设置页会显示“已在默认导入目录中检测到 Live2D 模型资源”
- 会显示当前生效路径、模型入口和资源来源
- Live2D 模式会从本地用户目录读取模型资源

如果你改成了自定义路径：

- 设置页会显示“用户配置路径”
- Live2D 模式优先使用你手动填写的目录

## 最小手工测试

### 1. 未导入资源

1. 确保 `~/.hermes/yachiyo/assets/live2d/` 目录为空，或暂时把资源移走。
2. 启动 Hermes-Yachiyo 并切到 Live2D 模式。
3. 预期结果：
   - 应用正常运行
   - Live2D 模式不崩溃
   - 设置页和 Live2D 模式都提示去 Releases 下载资源包

### 2. 导入资源到默认目录

1. 把资源包解压到 `~/.hermes/yachiyo/assets/live2d/`。
2. 不填写“模型路径”，直接打开 Live2D 设置。
3. 预期结果：
   - 设置页显示资源已就绪
   - 显示当前生效路径
   - Live2D 模式可识别该模型资源

### 3. 改为自定义模型路径

1. 在 Live2D 设置里填写新的模型目录。
2. 确认该目录里有 `.model3.json` 或 `.moc3`。
3. 预期结果：
   - 设置页状态切换为“用户配置路径”
   - Live2D 模式使用新的路径
   - 如果路径错误，会显示明确的错误提示