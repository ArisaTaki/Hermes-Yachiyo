"""Effect Policy 测试"""

from apps.shell.effect_policy import (
    EffectType,
    build_effects_summary,
    get_effect,
)


class TestGetEffect:
    def test_known_field(self):
        etype, msg = get_effect("bridge_host")
        assert etype == EffectType.REQUIRES_BRIDGE_RESTART
        assert "Bridge" in msg

    def test_immediate_field(self):
        etype, msg = get_effect("live2d.model_name")
        assert etype == EffectType.IMMEDIATE

    def test_live2d_scale_is_immediate(self):
        etype, msg = get_effect("live2d_mode.scale")
        assert etype == EffectType.IMMEDIATE
        assert "缩放" in msg

    def test_live2d_model_path_requires_mode_restart(self):
        etype, msg = get_effect("live2d_mode.model_path")
        assert etype == EffectType.REQUIRES_MODE_RESTART
        assert "重新加载资源" in msg

    def test_app_restart_field(self):
        etype, msg = get_effect("tray_enabled")
        assert etype == EffectType.REQUIRES_APP_RESTART

    def test_display_mode_restarts_app(self):
        etype, msg = get_effect("display_mode")
        assert etype == EffectType.REQUIRES_APP_RESTART
        assert "重启" in msg

    def test_unknown_field_defaults_to_immediate(self):
        etype, msg = get_effect("unknown_field_xyz")
        assert etype == EffectType.IMMEDIATE
        assert msg == "已更新"


class TestBuildEffectsSummary:
    def test_single_immediate(self):
        summary = build_effects_summary(["live2d.model_name"])
        assert summary["has_immediate"] is True
        assert summary["has_restart_bridge"] is False
        assert summary["hint"] == "已即时生效"

    def test_bridge_restart(self):
        summary = build_effects_summary(["bridge_host", "bridge_port"])
        assert summary["has_restart_bridge"] is True
        assert len(summary["effects"]) == 2
        assert "Bridge" in summary["hint"]

    def test_mixed_effects(self):
        summary = build_effects_summary([
            "live2d.model_name",
            "bridge_host",
            "tray_enabled",
        ])
        assert summary["has_immediate"] is True
        assert summary["has_restart_bridge"] is True
        assert summary["has_restart_app"] is True
        assert "部分配置需" in summary["hint"]

    def test_empty_applied(self):
        summary = build_effects_summary([])
        assert len(summary["effects"]) == 0
        assert summary["hint"] == "已即时生效"

    def test_effects_list_structure(self):
        summary = build_effects_summary(["display_mode"])
        effect = summary["effects"][0]
        assert "key" in effect
        assert "effect" in effect
        assert "message" in effect
        assert effect["key"] == "display_mode"
        assert effect["effect"] == "requires_app_restart"
