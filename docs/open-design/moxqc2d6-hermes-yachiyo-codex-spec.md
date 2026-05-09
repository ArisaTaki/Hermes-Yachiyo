# Hermes Yachiyo — Codex 实装规格书

> 基于 Fusion Direction v4 设计稿导出。Codex 读取本文档即可完成 UI 实装。
> 设计原型：`moxqc2d6-design-reference.html`（完整可交互，12 个路由，全部可点击）
> Logo 资源：`moxqc2db-logo.png`
> 背景参考图：`moxqc2d3-bg-reference.png`

---

## 1. 项目概述

Hermes Yachiyo 是一个 Electron + React + TypeScript 桌面应用，Python 后端。角色原型为动画电影《超时空辉夜姬》的月見八千代——8000 岁的 AI 歌姬，月夜见虚拟空间管理员。

**设计方向：** 月夜深蓝 × 金→蓝绿渐变 × 月光粒子
**角色融合（v4）：** 渐变发（银→粉）+ 渐变瞳（粉→青）融入 accent 色系，月球 motif、四角装饰框参考超かぐや姫官网风格

---

## 2. CSS Design Tokens（完整）

```css
:root {
  color-scheme: dark;

  /* ====== 月夜深蓝基底 ====== */
  --bg-deep:    oklch(10.5% 0.025 260);
  --bg:         oklch(14.5% 0.030 258);
  --surface:    oklch(18.0% 0.032 256);
  --surface-2:  oklch(21.5% 0.034 254);
  --surface-3:  oklch(25.5% 0.036 252);

  /* ====== 文字色阶 ====== */
  --fg:         oklch(94.5% 0.010 245);
  --muted:      oklch(75.0% 0.025 250);
  --subtle:     oklch(58.0% 0.030 252);
  --faint:      oklch(43.0% 0.028 254);

  /* ====== 边框 ====== */
  --border:      oklch(30.0% 0.035 255 / 0.72);
  --border-soft: oklch(35.0% 0.030 255 / 0.32);
  --line:        oklch(42.0% 0.030 255 / 0.14);

  /* ====== 八千代色系 ====== */
  --gold:    oklch(82% 0.135 76);
  --coral:   oklch(68% 0.165 30);
  --teal:    oklch(66% 0.120 188);
  --cyan:    oklch(75% 0.095 205);
  --violet:  oklch(64% 0.160 285);

  /* ====== 功能色 ====== */
  --success: oklch(68% 0.150 155);
  --warning: oklch(78% 0.145 76);
  --danger:  oklch(58% 0.190 24);

  /* ====== 柔化版本 ====== */
  --gold-soft:   oklch(82% 0.135 76 / 0.14);
  --teal-soft:   oklch(66% 0.120 188 / 0.14);
  --cyan-soft:   oklch(75% 0.095 205 / 0.16);
  --violet-soft: oklch(64% 0.160 285 / 0.12);

  /* ====== 角色渐变色系（v4 — 渐变发/瞳） ====== */
  --eye-pink: oklch(72% 0.140 350);
  --eye-cyan: oklch(75% 0.095 205);
  --silver:   oklch(85% 0.010 250);

  /* ====== 渐变 ====== */
  --gradient-yachiyo:  linear-gradient(135deg, var(--gold), var(--teal) 58%, var(--cyan));
  --gradient-shimmer:  linear-gradient(90deg, transparent, var(--gold), var(--teal), transparent);
  --gradient-hair:     linear-gradient(135deg, var(--silver), var(--eye-pink));
  --gradient-eye:      linear-gradient(135deg, var(--eye-pink), var(--eye-cyan));
  --gradient-cosmic:   linear-gradient(135deg, var(--eye-pink), var(--violet), var(--teal), var(--cyan));

  /* ====== 字体 ====== */
  --font-display: "SF Pro Display", "Inter Variable", "PingFang SC", "Hiragino Sans", system-ui, sans-serif;
  --font-body:    "SF Pro Text", "Inter Variable", "PingFang SC", "Hiragino Sans", system-ui, sans-serif;
  --font-mono:    "Berkeley Mono", "SF Mono", ui-monospace, Menlo, monospace;

  /* ====== 圆角 ====== */
  --radius-control: 6px;
  --radius-card:    8px;
  --radius-panel:   12px;
  --radius-window:  18px;

  /* ====== 动效 ====== */
  --dur-fast:   120ms;
  --dur-normal: 220ms;
  --dur-page:   420ms;
  --dur-breath: 2800ms;
  --ease-out:   cubic-bezier(0.16, 1, 0.3, 1);
  --ease-in-out: cubic-bezier(0.65, 0, 0.35, 1);
}
```

---

## 3. 字体规则

- **全局 OpenType：** `font-feature-settings: 'cv01', 'ss03'`
- **标题字重：** 510（签名介于 regular 和 medium 之间）
- **强调字重：** 590
- **正文字重：** 400
- **最大字重：** 不超过 590（禁用 700/bold）
- **显示字号负字距：** 30px → -0.7px

| 角色 | 字号 | 字重 | 行高 | 字距 |
|------|------|------|------|------|
| Dashboard 标题 | 30px | 510 | 1.1 | -0.7px |
| 区块标题 | 18px | 590 | 1.33 | normal |
| 卡片标题 | 16px | 590 | 1.33 | normal |
| 正文 | 14px | 400 | 1.6 | normal |
| 小字/描述 | 12px | 400 | 1.4 | normal |
| 标签 | 11px | 510 | 1.4 | normal |
| 元数据 | 11px | 400 | 1.5 | normal |
| Mono | 12px | 400 | 1.5 | normal |

---

## 4. 页面结构（12 个路由）

```
sidebar (260px fixed)
├── logo + app name
├── character status (avatar + name + status dot)
├── nav groups
│   ├── 初始化: dashboard / installer / provider
│   ├── 日常桌面: chat / bubble / live2d
│   ├── 资源: resources / workspace
│   └── 维护: diagnostics / settings
└── footer buttons (检查更新 / 帮助)

main-content (flex, fills remaining)
├── page-dashboard
├── page-installer
├── page-provider
├── page-chat
├── page-bubble
├── page-live2d
├── page-resources
├── page-workspace
├── page-diagnostics
├── page-settings
├── page-tools-all        ← v4 新增
└── page-activity-all     ← v4 新增
```

### 4.1 Dashboard 主控台
- **KV Hero 区域（v4）：** 角色主题大区块，含 eyebrow 标签、标题（银→粉渐变文字）、描述、状态元数据。参考超かぐや姫官网 KV hero 风格
- **头部：** 30px 标题 + 副标题
- **状态网格：** 3 列 grid，每张卡片含 label + icon + value + description（四角装饰框 corner-frame）
  - Bridge 状态（监听中）
  - 模型连接（已连接）
  - 工作区（已初始化）
- **桌面工具网格：** 4 列 grid，点击跳转对应页面
  - 聊天窗口 / 气泡模式 / Live2D 模式 / GPT-SoVITS
  - "查看全部" → tools-all 路由
- **最近活动列表：** icon + text + time
  - "查看全部" → activity-all 路由

### 4.2 安装器 Installer
- **步骤指示器：** 4 步横排（欢迎→依赖检查→模型配置→完成）
- **配置卡片：** 表单（提供商下拉 + API Key 密码框 + 模型选择）
- **检查清单侧栏：** 安装检查项

### 4.3 模型配置 Provider
- **提供商区：** 提供商选择 / API Key / 模型选择 / 连接测试
- **TTS 区：** TTS 引擎 / API 地址 / 默认音色
- **RTX 4060 优化区：** GPU 加速开关 / 显存限制 / 精度

### 4.4 聊天窗口 Chat
- **双栏布局：** 左侧会话列表(280px) + 右侧聊天主区
- **消息气泡：** agent 左侧 / user 右侧，错位入场动画
- **输入区：** textarea + 发送按钮（渐变背景）

### 4.5 气泡模式 Bubble
- **演示区：** 320×480 模拟气泡窗口
- **浮动气泡：** 64px 渐变圆形，上下浮动动画
- **功能说明：** 4 个功能胶囊标签

### 4.6 Live2D 模式
- **舞台区：** 400×500 模型区域（四角装饰框）
- **导入按钮：** 渐变主按钮
- **功能说明：** 口型同步 / 表情动作 / 语音合成 / 月光舞台

### 4.7 资源管理 Resources
- **分类标签栏：** 全部 / 模型 / 语音 / 壁纸 / Live2D
- **统计卡片：** 3 列（总文件数 / 总大小 / Live2D 模型数）
- **文件列表：** icon + name + meta + status badge

### 4.8 工作区 Workspace
- **对话记录区：** 导出 / 导入 / 清空
- **路径配置区：** 工作区目录 / 资源目录 / 备份
- **文件浏览区：** 树状文件列表

### 4.9 诊断工具 Diagnostics
- **检测网格：** 4 列，8 项系统检测
  - Python / Node.js / Bridge / 模型 / GPU / 工作区 / Live2D / TTS
  - 状态：passed（绿）/ warning（黄）/ error（红）
- **日志查看器：** 等宽字体，带时间戳和级别标签

### 4.10 设置 Settings
- **分组卡片：** 通用 / 外观 / 模型 / 关于
- **控件类型：** toggle 开关 / select 下拉 / button 按钮
- **hover 效果：** 左侧渐变指示条

---

## 5. 组件规范

### 5.1 按钮

**Primary（主按钮）**
```css
.btn--primary {
  background: var(--gradient-yachiyo);
  border: none;
  color: var(--bg-deep);
  padding: 8px 16px;
  border-radius: var(--radius-control);
  font-size: 13px;
  font-weight: 510;
}
.btn--primary:hover {
  transform: scale(1.02);
  box-shadow: 0 0 16px oklch(82% 0.135 76 / 0.3);
}
```

**Ghost（幽灵按钮）**
```css
.btn--ghost {
  background: oklch(255 0 0 / 0.03);
  border: 1px solid var(--border-soft);
  color: var(--muted);
  padding: 8px 16px;
  border-radius: var(--radius-control);
  font-size: 13px;
  font-weight: 510;
}
.btn--ghost:hover {
  background: oklch(75% 0.095 205 / 0.06);
  color: var(--fg);
  border-color: oklch(75% 0.095 205 / 0.2);
}
```

### 5.2 卡片

```css
.card {
  background: var(--surface);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-panel);
  padding: 20px;
  transition: all var(--dur-normal) var(--ease-out);
}
.card:hover {
  border-color: oklch(75% 0.095 205 / 0.2);
  transform: translateY(-1px);
}
/* 渐变光边（hover 时） */
.card::before {
  content: '';
  position: absolute;
  inset: -1px;
  border-radius: inherit;
  background: linear-gradient(135deg, oklch(82% 0.135 76 / 0), oklch(75% 0.095 205 / 0));
  z-index: -1;
  opacity: 0;
  transition: opacity var(--dur-normal) var(--ease-out);
}
.card:hover::before {
  opacity: 1;
  background: linear-gradient(135deg, oklch(82% 0.135 76 / 0.15), oklch(75% 0.095 205 / 0.15));
}
```

### 5.3 开关 Toggle

```css
.toggle {
  position: relative;
  width: 44px; height: 24px;
  background: var(--border);
  border-radius: 9999px;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out);
}
.toggle.active { background: var(--teal); }
.toggle::after {
  content: '';
  position: absolute;
  top: 2px; left: 2px;
  width: 20px; height: 20px;
  border-radius: 50%;
  background: var(--fg);
  transition: transform var(--dur-fast) var(--ease-out);
}
.toggle.active::after { transform: translateX(20px); }
```

### 5.4 选择器 Select

```css
.select {
  padding: 6px 12px;
  background: oklch(255 0 0 / 0.03);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-control);
  color: var(--fg);
  font-size: 13px;
  appearance: none;
  background-image: url("data:image/svg+xml,..."); /* 下拉箭头 */
  background-repeat: no-repeat;
  background-position: right 8px center;
  padding-right: 28px;
}
```

### 5.5 徽章 Badge

```css
.badge--success { background: oklch(68% 0.150 155 / 0.12); color: var(--success); }
.badge--warning { background: oklch(78% 0.145 76 / 0.12); color: var(--warning); }
.badge--error   { background: oklch(58% 0.190 24 / 0.12); color: var(--danger); }
.badge--info    { background: oklch(75% 0.095 205 / 0.12); color: var(--cyan); }
```

### 5.6 状态指示点

```css
.status-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--success);
  animation: pulse-dot 2s ease-in-out infinite;
}
@keyframes pulse-dot {
  0%, 100% { opacity: 1; box-shadow: 0 0 4px oklch(68% 0.150 155 / 0.4); }
  50% { opacity: 0.5; box-shadow: 0 0 10px oklch(68% 0.150 155 / 0.6); }
}
```

---

## 6. 动效系统

### 6.1 月光粒子背景
- 35 个微小光点（0.8-3.8px），三种轨迹交替：
  - 直线上升（moon-drift）
  - 闪烁漂移（moon-drift-flicker）
  - 弧线绕行（moon-drift-orbit）
- 颜色（v4）：金色 / 青色 / 粉色 / 银色 四色交替
- 位置：fixed，全屏覆盖，pointer-events: none

### 6.2 页面切换（交叉淡入淡出）
```css
/* 退出 */
.route-page.exiting {
  animation: page-exit 300ms var(--ease-out) both;
}
@keyframes page-exit {
  from { opacity: 1; transform: translateY(0); }
  to { opacity: 0; transform: translateY(-8px); }
}

/* 进入 */
.route-page.entering {
  animation: page-enter 500ms var(--ease-out) both;
}
@keyframes page-enter {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}
```

### 6.3 流光扫过过渡
```css
.shimmer-sweep {
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: var(--gradient-shimmer);
  background-size: 200% 100%;
}
.shimmer-sweep.active {
  animation: shimmer-sweep 1.8s var(--ease-out) forwards;
}
@keyframes shimmer-sweep {
  0% { background-position: -200% 0; opacity: 1; }
  30% { opacity: 1; filter: blur(1px); }
  100% { background-position: 200% 0; opacity: 0; }
}
```

### 6.4 Section 错位入场
```css
.stagger-in {
  opacity: 0;
  transform: translateY(16px);
  animation: stagger-fade-up 450ms var(--ease-out) both;
}
.stagger-in:nth-child(1) { animation-delay: 60ms; }
.stagger-in:nth-child(2) { animation-delay: 120ms; }
.stagger-in:nth-child(3) { animation-delay: 180ms; }
/* ...每项递增 60ms */
```

### 6.5 四角装饰框（电影官网风格）
```css
.corner-frame::before { /* 左上角 */
  top: -1px; left: -1px;
  border-width: 1px 0 0 1px;
  border-color: oklch(75% 0.095 205 / 0.25);
}
.corner-frame::after { /* 右下角 */
  bottom: -1px; right: -1px;
  border-width: 0 1px 1px 0;
}
.corner-frame:hover::before,
.corner-frame:hover::after {
  border-color: oklch(82% 0.135 76 / 0.4); /* hover 变金色 */
}
/* inner 伪元素处理右上和左下角 */
```

### 6.6 Loading 遮罩
- 深色底 + 中心微弱青色光晕
- Logo 圆形 + 柔光文字 + 渐变进度条
- 2 秒后自动消失（fade out 0.6s）

### 6.7 Reduced Motion
```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 1ms !important;
    transition-duration: 1ms !important;
  }
  .moon-particle { display: none; }
  .loading-overlay { display: none; }
}
```

---

## 7. 布局尺寸

| 区域 | 宽度 | 备注 |
|------|------|------|
| 标题栏 | 100%, h=52px | 固定顶部，毛玻璃 |
| 侧边栏 | 260px, full height | 固定左侧 |
| 主内容区 | flex-1 | left:260px, top:52px |
| 安装器内容 | max 800px | 居中 |
| 设置/配置/工作区 | max 720px | 居中 |
| 诊断工具 | max 900px | 居中 |
| 资源管理 | max 800px | 居中 |
| 聊天侧栏 | 280px | 聊天页面内 |
| Bubble 演示 | 320×480 | 居中展示 |
| Live2D 舞台 | 400×500 | 居中展示 |

---

## 8. 资源文件

| 文件名 | 用途 | 位置 |
|--------|------|------|
| `moxqc2db-logo.png` | 产品 logo（八千代头像） | 侧边栏、标题栏、Loading、头像环 |
| `moxqc2d3-bg-reference.png` | 背景参考图（电影官网风格） | 仅供参考，不直接使用 |
| `moxqc2d6-design-reference.html` | 完整设计原型（v4） | Codex 参考用 |

### Logo 使用尺寸
- Loading 屏幕：72×72px，圆形，发光
- 侧边栏 logo：36×36px，圆形
- 标题栏：20×20px，圆形
- 头像环内：40×40px，圆形

---

## 9. 路由映射

```javascript
const ROUTES = {
  dashboard:     { label: '主控台',     icon: '📊', group: '初始化' },
  installer:     { label: '安装器',     icon: '📦', group: '初始化' },
  provider:      { label: '模型配置',   icon: '🔗', group: '初始化' },
  chat:          { label: '聊天窗口',   icon: '💬', group: '日常桌面' },
  bubble:        { label: '气泡模式',   icon: '💭', group: '日常桌面' },
  live2d:        { label: 'Live2D 模式', icon: '🎭', group: '日常桌面' },
  resources:     { label: '资源管理',   icon: '📁', group: '资源' },
  workspace:     { label: '工作区',     icon: '📂', group: '资源' },
  diagnostics:   { label: '诊断工具',   icon: '🔍', group: '维护' },
  settings:      { label: '设置',       icon: '⚙️', group: '维护' },
  'tools-all':   { label: '桌面工具',   icon: '🧰', group: '内部' },
  'activity-all':{ label: '活动日志',   icon: '📋', group: '内部' }
};
```

---

## 10. 实装注意事项

1. **Electron 兼容：** 标题栏使用 `pointer-events: none` + 子元素 `pointer-events: auto`，避免 `-webkit-app-region: drag` 阻止点击
2. **路由切换防抖：** `isTransitioning` 标志位防止连续点击，退出动画 250ms 后再进入
3. **粒子性能：** 纯 CSS animation + transform，35 个粒子，避免 JS 重绘
4. **Logo 图片：** 使用 `<img>` 标签引用 `moxqc2db-logo.png`，不使用 emoji
5. **字体渲染：** `-webkit-font-smoothing: antialiased`
6. **滚动条样式：** 6px 宽，透明轨道，圆角 thumb

---

## 11. Tweaks 调试面板（v4）

标题栏 ⚙ 按钮点击展开浮动面板，包含以下实时可控项：

| 控件 | 类型 | 范围 | 作用 |
|------|------|------|------|
| 主题色调 | 5 色板 | 八千代粉/月光金/星蓝/青瓷/紫藤 | 切换 `--accent` CSS 变量 |
| 粒子密度 | range | 0–80 | 实时重建月光粒子数量 |
| 月光强度 | range | 0%–200% | 控制背景月光 opacity |
| 动画速度 | range | 0.5×–3× | 全局 `--dur-*` 动画速度 |
| 字体大小 | range | 11–17px | 全局 `--font-size-base` |
| 粒子动画 | toggle | on/off | 暂停/恢复所有月光粒子 |
| 呼吸光效 | toggle | on/off | 暂停/恢复所有呼吸发光动画 |

---

## 12. Toast 通知系统（v4）

所有按钮操作后弹出 Toast 通知（底部右侧，自动消失 2.5s）：
- 成功（绿色）、信息（青色）、警告（金色）、错误（红色）四种类型
- 所有可点击元素统一调用 `showToast(message, type)` 反馈

---

## 13. 完整可点击链路（v4）

### 侧边栏（11 项 + 2 footer）
主控台 · 安装器 · 模型配置 · 聊天窗口 · 气泡模式 · Live2D · 资源管理 · 工作区 · 诊断工具 · 设置 · ⚙ Tweaks 按钮 + 检查更新 · 帮助

### Dashboard
- 状态卡片 × 3（hover 交互）
- 工具卡片 × 4（聊天窗口 → chat、气泡模式 → bubble、Live2D → live2d、GPT-SoVITS → toast）
- 查看全部 × 2 → tools-all / activity-all

### 聊天页面
- 发送按钮（输入文字后激活，Enter 发送，自动回复）
- 侧边栏会话切换（3 个会话）
- 操作按钮（语音 / 图片 / 更多）

### 资源管理
- 标签切换（全部 / 模型 / 语音 / 壁纸 / Live2D）
- 3 个「切换」按钮

### 设置页面
- API Key · 测试连接 · 检查更新 · 打开项目主页

### 安装器
- 上一步 / 下一步

### 模型配置
- 重新配置 · 测试连接

### 工作区
- 导出 · 导入 · 清空 · 更改 × 2 · 立即备份

### 诊断工具
- 重新检测

### Live2D
- 导入模型

---

## 14. 与线上版本的功能对齐

根据 https://www.hermes-yachiyo.dev/ 文档，所有功能页面已覆盖：

| 功能 | 路由 | 状态 |
|------|------|------|
| 主控台 | dashboard | ✅ |
| 安装器 | installer | ✅ |
| 模型配置 | provider | ✅ |
| 聊天窗口 | chat | ✅ |
| 气泡模式 | bubble | ✅ |
| Live2D 模式 | live2d | ✅ |
| 资源管理 | resources | ✅ |
| 工作区 | workspace | ✅ |
| 诊断工具 | diagnostics | ✅ |
| 设置 | settings | ✅ |
| 桌面工具全部 | tools-all | ✅ |
| 活动日志全部 | activity-all | ✅ |
