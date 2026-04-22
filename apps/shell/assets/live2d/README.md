# Live2D 资源占位目录

此目录仅保留轻量占位说明，不再作为大型 Live2D 二进制资源的默认存放位置。

## 请不要做的事

- 不要把 `.moc3`、`.model3.json`、大纹理 PNG 等大型 Live2D 资源继续直接提交到主仓库。

## 正确做法

- 将 Live2D 资源包发布到 GitHub Releases。
- 用户下载后，解压到本机目录：

```text
~/.hermes/yachiyo/assets/live2d/
```

- 程序运行时会优先从用户目录中自动检测模型资源。

发布说明见：

- https://github.com/ArisaTaki/Hermes-Yachiyo/releases