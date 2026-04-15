"""Integration Status 测试 — Bridge / AstrBot / Hapi 状态计算"""

from unittest.mock import patch

from apps.shell.integration_status import (
    AstrBotStatus,
    BridgeStatus,
    HapiStatus,
    IntegrationSnapshot,
    get_astrbot_status,
    get_bridge_status,
    get_hapi_status,
    get_integration_snapshot,
)


def _make_config(enabled: bool = True, host: str = "127.0.0.1", port: int = 8420):
    """创建最小 mock config"""
    class MockConfig:
        bridge_enabled = enabled
        bridge_host = host
        bridge_port = port
    return MockConfig()


def _boot(enabled: bool = True, host: str = "127.0.0.1", port: int = 8420) -> dict:
    return {"enabled": enabled, "host": host, "port": port}


class TestBridgeStatus:
    @patch("apps.shell.integration_status.get_bridge_state", return_value="running")
    def test_running(self, mock_state):
        config = _make_config(enabled=True)
        status = get_bridge_status(config, _boot())
        assert status.state == "running"
        assert status.config_dirty is False

    @patch("apps.shell.integration_status.get_bridge_state", return_value="not_started")
    def test_enabled_not_started(self, mock_state):
        config = _make_config(enabled=True)
        status = get_bridge_status(config, _boot())
        assert status.state == "enabled_not_started"

    @patch("apps.shell.integration_status.get_bridge_state", return_value="failed")
    def test_failed(self, mock_state):
        config = _make_config(enabled=True)
        status = get_bridge_status(config, _boot())
        assert status.state == "failed"

    @patch("apps.shell.integration_status.get_bridge_state", return_value="running")
    def test_disabled(self, mock_state):
        config = _make_config(enabled=False)
        status = get_bridge_status(config, _boot(enabled=False))
        assert status.state == "disabled"

    @patch("apps.shell.integration_status.get_bridge_state", return_value="running")
    def test_config_dirty_port_change(self, mock_state):
        config = _make_config(enabled=True, port=9000)
        status = get_bridge_status(config, _boot(port=8420))
        assert status.config_dirty is True
        assert any("端口" in d for d in status.drift_details)

    @patch("apps.shell.integration_status.get_bridge_state", return_value="running")
    def test_config_dirty_host_change(self, mock_state):
        config = _make_config(host="0.0.0.0")
        status = get_bridge_status(config, _boot(host="127.0.0.1"))
        assert status.config_dirty is True
        assert any("地址" in d for d in status.drift_details)

    @patch("apps.shell.integration_status.get_bridge_state", return_value="running")
    def test_no_drift(self, mock_state):
        config = _make_config()
        status = get_bridge_status(config, _boot())
        assert status.config_dirty is False
        assert status.drift_details == []

    def test_to_dict(self):
        status = BridgeStatus(
            state="running",
            saved_enabled=True, saved_host="127.0.0.1", saved_port=8420,
            boot_enabled=True, boot_host="127.0.0.1", boot_port=8420,
            config_dirty=False,
        )
        d = status.to_dict()
        assert d["state"] == "running"
        assert d["url"] == "http://127.0.0.1:8420"
        assert d["boot_config"]["url"] == "http://127.0.0.1:8420"

    def test_to_dashboard_dict_has_running_key(self):
        status = BridgeStatus(
            state="running",
            saved_enabled=True, saved_host="127.0.0.1", saved_port=8420,
            boot_enabled=True, boot_host="127.0.0.1", boot_port=8420,
            config_dirty=False,
        )
        d = status.to_dashboard_dict()
        assert d["running"] == "running"  # 向后兼容


class TestAstrBotStatus:
    def test_bridge_disabled(self):
        bridge = BridgeStatus(
            state="disabled",
            saved_enabled=False, saved_host="h", saved_port=1,
            boot_enabled=False, boot_host="h", boot_port=1,
            config_dirty=False,
        )
        ab = get_astrbot_status(bridge)
        assert ab.state == "not_configured"
        assert ab.bridge_ready is False
        assert any("未启用" in b for b in ab.blockers)

    def test_bridge_failed(self):
        bridge = BridgeStatus(
            state="failed",
            saved_enabled=True, saved_host="h", saved_port=1,
            boot_enabled=True, boot_host="h", boot_port=1,
            config_dirty=False,
        )
        ab = get_astrbot_status(bridge)
        assert ab.state == "configured_not_connected"
        assert any("异常" in b for b in ab.blockers)

    def test_bridge_running(self):
        bridge = BridgeStatus(
            state="running",
            saved_enabled=True, saved_host="h", saved_port=1,
            boot_enabled=True, boot_host="h", boot_port=1,
            config_dirty=False,
        )
        ab = get_astrbot_status(bridge)
        assert ab.state == "not_configured"
        assert ab.bridge_ready is True
        assert ab.blockers == []

    def test_bridge_running_but_dirty(self):
        """bridge running + config_dirty → 应有漂移警告 blocker"""
        bridge = BridgeStatus(
            state="running",
            saved_enabled=True, saved_host="h", saved_port=9000,
            boot_enabled=True, boot_host="h", boot_port=8420,
            config_dirty=True,
            drift_details=["端口: 8420 → 9000"],
        )
        ab = get_astrbot_status(bridge)
        assert ab.bridge_ready is True
        assert any("旧地址" in b for b in ab.blockers)


class TestHapiStatus:
    def test_placeholder(self):
        status = get_hapi_status()
        assert status.state == "not_configured"
        assert "未配置" in status.label


class TestIntegrationSnapshot:
    @patch("apps.shell.integration_status.get_bridge_state", return_value="running")
    def test_snapshot(self, mock_state):
        config = _make_config()
        snap = get_integration_snapshot(config, _boot())
        assert isinstance(snap, IntegrationSnapshot)
        assert snap.bridge.state == "running"
        assert snap.hapi.state == "not_configured"

    @patch("apps.shell.integration_status.get_bridge_state", return_value="running")
    def test_snapshot_to_dict(self, mock_state):
        config = _make_config()
        snap = get_integration_snapshot(config, _boot())
        d = snap.to_dict()
        assert "bridge" in d
        assert "astrbot" in d
        assert "hapi" in d
