"""设置页 HTML 生成器

为 live2d 等模式提供独立设置窗口，与主窗口内嵌设置面板保持相同信息结构。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)

_SETTINGS_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>Hermes-Yachiyo — 设置</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    font-family: -apple-system, "Helvetica Neue", "PingFang SC", sans-serif;
    background: #1a1a2e; color: #e0e0e0;
    padding: 20px; font-size: 14px; line-height: 1.5;
}}
h2 {{ color: #6495ed; font-size: 1.1em; margin-bottom: 16px; }}
.section {{
    background: #2d2d54; border-radius: 8px;
    padding: 14px 16px; margin-bottom: 14px;
}}
.section h4 {{ color: #6495ed; font-size: 0.9em; margin-bottom: 10px; }}
.row {{
    display: flex; justify-content: space-between;
    align-items: center; padding: 5px 0;
    border-bottom: 1px solid #3a3a6a; font-size: 0.88em;
}}
.row:last-child {{ border-bottom: none; }}
.label {{ color: #999; flex: 0 0 140px; }}
.value {{ color: #e0e0e0; text-align: right; }}
.value.ok {{ color: #90ee90; }}
.value.warn {{ color: #ffd700; }}
.value.dim {{ color: #666; font-style: italic; }}
.badge {{
    display: inline-block; background: #1a1a3e;
    border: 1px solid #6495ed33; color: #9988cc;
    padding: 1px 8px; border-radius: 10px; font-size: 0.8em;
}}
</style>
</head>
<body>
<h2>⚙️ 应用设置</h2>

<div class="section">
    <h4>显示模式</h4>
    <div class="row"><span class="label">当前模式</span>
        <span class="value">{display_mode}</span></div>
</div>

<div class="section">
    <h4>Live2D 模式配置 <span class="badge">骨架</span></h4>
    <div class="row"><span class="label">配置状态</span>
        <span class="value {model_state_class}">{model_state_label}</span></div>
    <div class="row"><span class="label">当前模型</span>
        <span class="value {model_name_class}">{model_name}</span></div>
    <div class="row"><span class="label">模型路径</span>
        <span class="value {model_path_class}" style="font-size:0.8em;word-break:break-all;">{model_path}</span></div>
    <div class="row"><span class="label">检测到 .model3.json</span>
        <span class="value {summary_json_class}" style="font-size:0.82em;">{summary_model3_json}</span></div>
    <div class="row"><span class="label">检测到 .moc3</span>
        <span class="value {summary_moc3_class}" style="font-size:0.82em;">{summary_moc3}</span></div>
    <div class="row"><span class="label">文件位置</span>
        <span class="value" style="font-size:0.82em;">{summary_file_loc}</span></div>
    <div class="row"><span class="label">待机动作组</span>
        <span class="value">{idle_motion_group}</span></div>
    <div class="row"><span class="label">表情系统</span>
        <span class="value {expr_class}">{enable_expressions}</span></div>
    <div class="row"><span class="label">物理模拟</span>
        <span class="value {phys_class}">{enable_physics}</span></div>
    <div class="row"><span class="label">窗口置顶</span>
        <span class="value">{window_on_top}</span></div>
    <div class="row" style="border-top:1px solid #4a3a4a; margin-top:6px; padding-top:8px;">
        <span class="label" style="color:#888;font-size:0.82em;">接入状态</span>
        <span class="value dim">渲染器未实现 · 等待 live2d_renderer.py</span>
    </div>
</div>

<div class="section">
    <h4>Bridge / 内部通信</h4>
    <div class="row"><span class="label">启用</span>
        <span class="value {bridge_class}">{bridge_enabled}</span></div>
    <div class="row"><span class="label">地址</span>
        <span class="value" style="font-size:0.85em;">{bridge_addr}</span></div>
</div>

<div class="section">
    <h4>AstrBot / QQ 集成</h4>
    <div class="row"><span class="label">连接状态</span>
        <span class="value dim">未接入 · 需配置 AstrBot 插件</span></div>
</div>
</body>
</html>
"""


def build_settings_html(config: "AppConfig") -> str:
    """生成设置页 HTML，供独立设置窗口使用。

    Args:
        config: 当前应用配置

    Returns:
        完整 HTML 字符串
    """
    l2d = config.live2d
    model_state = l2d.validate()
    summary = l2d.scan()

    _MODEL_STATE_LABELS = {
        "not_configured":  ("⚪ 未配置", ""),
        "path_invalid":    ("❌ 路径不存在", "warn"),
        "path_not_live2d": ("⚠️ 目录无模型文件（缺少 .moc3 / .model3.json）", "warn"),
        "path_valid":      ("✅ 模型目录就绪 · 渲染器待实现", "ok"),
        "loaded":          ("✅ 已加载", "ok"),
    }
    state_label, state_class = _MODEL_STATE_LABELS.get(model_state.value, (model_state.value, ""))

    # 摘要字段格式化
    if summary and not summary.is_empty():
        s_json    = summary.model3_json or "—"
        s_json_cls = "ok" if summary.model3_json else "dim"
        s_moc3    = summary.moc3_file or "—"
        if summary.extra_moc3_count > 0:
            s_moc3 += f" (+{summary.extra_moc3_count})"
        s_moc3_cls = "ok" if summary.moc3_file else "dim"
        s_loc     = f"子目录: {summary.subdir_name}" if summary.found_in_subdir else "根目录"
    else:
        s_json, s_json_cls = "—", "dim"
        s_moc3, s_moc3_cls = "—", "dim"
        s_loc = "—"

    return _SETTINGS_HTML.format(
        display_mode=config.display_mode,
        # Live2D 配置
        model_state_label=state_label,
        model_state_class=state_class,
        model_name=l2d.model_name if l2d.model_name else "（未设置）",
        model_name_class="" if l2d.model_name else "dim",
        model_path=l2d.model_path if l2d.model_path else "（未设置）",
        model_path_class="" if l2d.model_path else "dim",
        summary_model3_json=s_json,
        summary_json_class=s_json_cls,
        summary_moc3=s_moc3,
        summary_moc3_class=s_moc3_cls,
        summary_file_loc=s_loc,
        idle_motion_group=l2d.idle_motion_group or "Idle",
        enable_expressions="✅ 启用" if l2d.enable_expressions else "— 禁用",
        expr_class="ok" if l2d.enable_expressions else "",
        enable_physics="✅ 启用" if l2d.enable_physics else "— 禁用",
        phys_class="ok" if l2d.enable_physics else "",
        window_on_top="✅ 置顶" if l2d.window_on_top else "— 不置顶",
        # Bridge
        bridge_enabled="✅ 已启用" if config.bridge_enabled else "⛔ 已禁用",
        bridge_class="ok" if config.bridge_enabled else "",
        bridge_addr=f"http://{config.bridge_host}:{config.bridge_port}",
    )
