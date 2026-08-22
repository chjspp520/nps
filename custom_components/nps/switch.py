"""NPS 开关实体 - 隧道开关 + NPC 客户端开关."""
import asyncio
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .coordinator import NpsDataUpdateCoordinator
from .api import NpsApiClient

_LOGGER = logging.getLogger(__name__)

# turn_on/off 操作后延迟刷新的秒数
REFRESH_DELAY = 3

# NPS Mode 字段英文显示名映射（用于开关命名）
MODE_LABELS = {
    "tcp": "TCP",
    "udp": "UDP",
    "socks5": "Socks5",
    "httpProxy": "HTTPProxy",
    "secret": "Secret",
    "p2p": "P2P",
    "file": "File",
    "httpHostServer": "HostServer",
    "webServer": "WebServer",
}


def _format_flow(flow_bytes: float) -> str:
    """将字节数格式化为人类可读的动态单位.

    < 1MB → KB,  1MB~1GB → MB,  >= 1GB → GB,  >= 1024GB → TB
    """
    if flow_bytes <= 0:
        return "0 B"
    units = [
        (1024 ** 4, "TB"),
        (1024 ** 3, "GB"),
        (1024 ** 2, "MB"),
        (1024 ** 1, "KB"),
    ]
    for divisor, unit in units:
        if abs(flow_bytes) >= divisor:
            return f"{flow_bytes / divisor:.2f} {unit}"
    return f"{flow_bytes:.0f} B"


def _mask_password(pwd: str | None) -> str:
    """密码脱敏: 只显示前2位和后2位."""
    if not pwd or len(pwd) <= 4:
        return "****"
    return f"{pwd[:2]}{'*' * min(len(pwd) - 4, 8)}{pwd[-2:]}"


class NpsTunnelSwitch(SwitchEntity):
    """表示一个 NPS 隧道的开关实体."""

    def __init__(
        self,
        coordinator: NpsDataUpdateCoordinator,
        api_client: NpsApiClient,
        entry_id: str,
        host: str,
        tunnel_info: dict,
    ) -> None:
        self.coordinator = coordinator
        self.api = api_client
        self.entry_id = entry_id

        tunnel_id = tunnel_info.get("Id")
        remark = tunnel_info.get("Remark") or ""
        mode = tunnel_info.get("Mode", "")
        mode_label = MODE_LABELS.get(mode, mode)

        # 获取客户端 ID
        client_obj = tunnel_info.get("Client")
        client_id = client_obj.get("Id") if isinstance(client_obj, dict) else "?"
        
        # 构建目标地址描述
        target_info = ""
        target_obj = tunnel_info.get("Target")
        if isinstance(target_obj, dict):
            target_str = target_obj.get("TargetStr", "")
            if target_str:
                first_target = target_str.split("\n")[0].strip()
                if first_target:
                    target_info = f"_{first_target}"
            elif target_obj.get("LocalProxy"):
                target_info = "_LocalProxy"
        elif not target_obj:
            top_target = tunnel_info.get("TargetAddr", "")
            if top_target:
                target_info = f"_{top_target}"

        # 格式: 客户端ID_备注_模式_目标(IP:端口)
        if remark:
            final_name = f"{client_id}_{remark}_{mode_label}{target_info}"
        else:
            final_name = f"{client_id}_Tunnel{tunnel_id}_{mode_label}{target_info}"

        self._attr_unique_id = f"{entry_id}_nps_tunnel_{tunnel_id}"
        self._attr_name = final_name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_nps_server")},
            name=f"NPS Server ({host})",
            manufacturer="NPS",
            model="Tunnel Server",
        )

        self._tunnel_id = tunnel_id
        self._attr_is_on = bool(tunnel_info.get("RunStatus", False))
        # 基础信息
        self._port = tunnel_info.get("Port")
        self._mode = tunnel_info.get("Mode")
        # 客户端信息
        client_obj = tunnel_info.get("Client")
        self._client_id = client_obj.get("Id") if isinstance(client_obj, dict) else None
        self._client_addr = client_obj.get("Addr") if isinstance(client_obj, dict) else None
        self._client_is_connect = (
            client_obj.get("IsConnect", False) if isinstance(client_obj, dict) else False
        )
        # 目标地址
        target_o = tunnel_info.get("Target")
        self._target_str = (
            target_o.get("TargetStr", "").split("\n")[0].strip()
            if isinstance(target_o, dict) else ""
        )
        # 额外增强字段
        self._status = tunnel_info.get("Status")  # 数据库启用状态
        self._server_ip = tunnel_info.get("ServerIp") or ""
        self._ports = tunnel_info.get("Ports") or ""
        self._password_raw = tunnel_info.get("Password") or ""
        self._target_addr = tunnel_info.get("TargetAddr") or ""
        self._strip_pre = tunnel_info.get("StripPre") or ""
        # 流量数据
        flow = tunnel_info.get("Flow") or {}
        self._inlet_flow = flow.get("InletFlow", 0) or 0
        self._export_flow = flow.get("ExportFlow", 0) or 0
        self._flow_limit = flow.get("FlowLimit", 0) or 0
        # 健康检查配置（顶层字段，非嵌套对象）
        self._health_interval = tunnel_info.get("HealthCheckInterval", 0) or 0
        self._health_max_fail = tunnel_info.get("HealthMaxFail", 0) or 0
        self._health_timeout = tunnel_info.get("HealthCheckTimeout", 0) or 0

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {
            "tunnel_id": self._tunnel_id,
            "port": self._port,
            "mode": self._mode,
            "target": self._target_str,
            "status_enabled": self._status,
            "server_ip": self._server_ip or None,
            "ports": self._ports or None,
            "target_addr": self._target_addr or None,
            "strip_pre": self._strip_pre or None,
            "inlet_flow": _format_flow(self._inlet_flow),
            "export_flow": _format_flow(self._export_flow),
            "flow_limit": _format_flow(self._flow_limit) if self._flow_limit else None,
        }
        if self._password_raw:
            attrs["password"] = _mask_password(self._password_raw)
        if self._health_interval or self._health_max_fail or self._health_timeout:
            attrs["health_check_interval_s"] = self._health_interval
            attrs["health_max_fail"] = self._health_max_fail
            attrs["health_check_timeout_s"] = self._health_timeout
        if self._client_id is not None:
            attrs["client_id"] = self._client_id
        if self._client_addr is not None:
            attrs["client_ip"] = self._client_addr
            attrs["client_online"] = self._client_is_connect
        attrs["server"] = self.api._base_url
        return attrs

    @property
    def icon(self) -> str:
        """根据开关状态返回不同图标."""
        return "mdi:lan-connect" if self._attr_is_on else "mdi:lan-disconnect"

    @callback
    def _handle_coordinator_update(self) -> None:
        if not self.coordinator.data:
            return
        for tunnel in self.coordinator.data:
            if tunnel.get("Id") == self._tunnel_id:
                self._attr_is_on = bool(tunnel.get("RunStatus", False))
                self._port = tunnel.get("Port")
                self._mode = tunnel.get("Mode")
                # 增强字段更新
                self._status = tunnel.get("Status")
                self._server_ip = tunnel.get("ServerIp") or ""
                self._ports = tunnel.get("Ports") or ""
                self._password_raw = tunnel.get("Password") or ""
                self._target_addr = tunnel.get("TargetAddr") or ""
                self._strip_pre = tunnel.get("StripPre") or ""
                target_obj = tunnel.get("Target")
                if isinstance(target_obj, dict):
                    self._target_str = target_obj.get("TargetStr", "").split("\n")[0].strip()
                client_obj = tunnel.get("Client")
                if isinstance(client_obj, dict):
                    self._client_id = client_obj.get("Id")
                    self._client_addr = client_obj.get("Addr")
                    self._client_is_connect = client_obj.get("IsConnect", False)
                flow = tunnel.get("Flow") or {}
                if isinstance(flow, dict):
                    self._inlet_flow = flow.get("InletFlow", 0) or 0
                    self._export_flow = flow.get("ExportFlow", 0) or 0
                    self._flow_limit = flow.get("FlowLimit", 0) or 0
                # 健康检查配置（顶层字段）
                self._health_interval = tunnel.get("HealthCheckInterval", 0) or 0
                self._health_max_fail = tunnel.get("HealthMaxFail", 0) or 0
                self._health_timeout = tunnel.get("HealthCheckTimeout", 0) or 0
                # 动态更新名称
                remark = tunnel.get("Remark", "")
                mode = tunnel.get("Mode", "")
                mode_label = MODE_LABELS.get(mode, mode)
                cid = self._client_id if self._client_id else "?"
                ti = f"_{self._target_str}" if self._target_str else ""
                if remark:
                    self._attr_name = f"{cid}_{remark}_{mode_label}{ti}"
                else:
                    self._attr_name = f"{cid}_Tunnel{self._tunnel_id}_{mode_label}{ti}"
                break
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        _LOGGER.info("开启隧道: %s (ID=%d)", self.name, self._tunnel_id)
        try:
            await self.hass.async_add_executor_job(self.api.start_tunnel, self._tunnel_id)
        except HomeAssistantError as err:
            raise
        except ConnectionError as err:
            raise HomeAssistantError(f"开启隧道失败: {err}") from err
        await asyncio.sleep(REFRESH_DELAY)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        _LOGGER.info("停止隧道: %s (ID=%d)", self.name, self._tunnel_id)
        try:
            await self.hass.async_add_executor_job(self.api.stop_tunnel, self._tunnel_id)
        except HomeAssistantError as err:
            raise
        except ConnectionError as err:
            raise HomeAssistantError(f"停止隧道失败: {err}") from err
        await asyncio.sleep(REFRESH_DELAY)
        await self.coordinator.async_request_refresh()


class NpsClientSwitch(SwitchEntity):
    """表示一个 NPC 客户端的开关实体（控制连接/断开）."""

    def __init__(
        self,
        coordinator: NpsDataUpdateCoordinator,
        api_client: NpsApiClient,
        entry_id: str,
        host: str,
        client_info: dict,
    ) -> None:
        self.coordinator = coordinator
        self.api = api_client
        self.entry_id = entry_id

        client_id = client_info.get("Id")
        remark = client_info.get("Remark") or ""
        verify_key = client_info.get("VerifyKey", "")

        # 格式: ID_备注_唯一验证密钥
        if remark:
            final_name = f"{client_id}_{remark}_{verify_key}"
        else:
            final_name = f"{client_id}_NPC_{verify_key or 'unknown'}"

        self._attr_unique_id = f"{entry_id}_nps_client_{client_id}"
        self._attr_name = final_name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_nps_server")},
            name=f"NPS Server ({host})",
            manufacturer="NPS",
            model="Tunnel Server",
        )
        # 客户端图标通过动态 property 返回（根据在线状态切换）

        self._client_id = client_id
        self._attr_is_on = bool(client_info.get("IsConnect", False))
        self._addr = client_info.get("Addr")
        self._version = client_info.get("Version")
        self._now_conn = client_info.get("NowConn", 0)
        self._vkey = client_info.get("VerifyKey", "")
        # 增强字段
        self._rate_limit = client_info.get("RateLimit", 0) or 0
        self._max_tunnel_num = client_info.get("MaxTunnelNum", 0) or 0
        self._max_conn = client_info.get("MaxConn", 0) or 0
        self._config_conn_allow = client_info.get("ConfigConnAllow")
        self._web_username = client_info.get("WebUserName") or ""
        flow = client_info.get("Flow", {})
        if isinstance(flow, dict):
            self._inlet_flow = flow.get("InletFlow", 0) or 0
            self._export_flow = flow.get("ExportFlow", 0) or 0
            self._flow_limit = flow.get("FlowLimit", 0) or 0
        else:
            self._inlet_flow = 0
            self._export_flow = 0
            self._flow_limit = 0
        cnf = client_info.get("Cnf")
        if isinstance(cnf, dict):
            self._compress = cnf.get("Compress")
            self._crypt = cnf.get("Crypt")
        # 实时速率
        rate = client_info.get("Rate", {})
        if isinstance(rate, dict):
            self._now_rate = rate.get("NowRate", 0) or 0
        else:
            self._now_rate = 0
        # 桥接信息
        self._bridge_type = client_info.get("bridgeType") or ""
        self._bridge_port = client_info.get("bridgePort") or 0
        # 服务端 IP
        self._server_ip_raw = client_info.get("ip") or client_info.get("Ip") or ""

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {
            "client_id": self._client_id,
            "ip": self._addr,
            "online": self._attr_is_on,
            "connections": self._now_conn,
            "inlet_flow": _format_flow(self._inlet_flow),
            "export_flow": _format_flow(self._export_flow),
        }
        if self._version:
            attrs["version"] = self._version
        if self._vkey:
            attrs["vkey"] = self._vkey[:16]
        if self._rate_limit:
            attrs["rate_limit_kbps"] = self._rate_limit
        if self._max_tunnel_num:
            attrs["max_tunnel_num"] = self._max_tunnel_num
        if self._max_conn:
            attrs["max_connections"] = self._max_conn
        if self._flow_limit:
            attrs["flow_limit"] = _format_flow(self._flow_limit)
        if self._config_conn_allow is not None:
            attrs["config_allowed"] = self._config_conn_allow
        if self._web_username:
            attrs["web_username"] = self._web_username
        if hasattr(self, "_compress") and self._compress is not None:
            attrs["compression"] = self._compress
        if hasattr(self, "_crypt") and self._crypt is not None:
            attrs["encryption"] = self._crypt
        # 实时速率
        if hasattr(self, "_now_rate") and self._now_rate:
            attrs["realtime_rate"] = f"{self._now_rate / 1024:.1f} KB/s"
        # 桥接信息
        if hasattr(self, "_bridge_type") and self._bridge_type:
            attrs["bridge_protocol"] = self._bridge_type
            attrs["bridge_port"] = self._bridge_port
        if hasattr(self, "_server_ip_raw") and self._server_ip_raw:
            attrs["nps_public_ip"] = self._server_ip_raw
        return attrs

    @property
    def icon(self) -> str:
        """根据开关状态返回不同图标."""
        return "mdi:ethernet" if self._attr_is_on else "mdi:ethernet-off"

    @callback
    def _handle_coordinator_update(self) -> None:
        clients = getattr(self.coordinator, "clients_data", [])
        if isinstance(clients, list):
            for c in clients:
                if c.get("Id") == self._client_id:
                    self._attr_is_on = bool(c.get("IsConnect", False))
                    self._addr = c.get("Addr")
                    self._version = c.get("Version")
                    self._now_conn = c.get("NowConn", 0)
                    # 增强字段更新
                    self._rate_limit = c.get("RateLimit", 0) or 0
                    self._max_tunnel_num = c.get("MaxTunnelNum", 0) or 0
                    self._max_conn = c.get("MaxConn", 0) or 0
                    self._config_conn_allow = c.get("ConfigConnAllow")
                    self._web_username = c.get("WebUserName") or ""
                    flow = c.get("Flow", {})
                    if isinstance(flow, dict):
                        self._inlet_flow = flow.get("InletFlow", 0) or 0
                        self._export_flow = flow.get("ExportFlow", 0) or 0
                        self._flow_limit = flow.get("FlowLimit", 0) or 0
                    cnf = c.get("Cnf")
                    if isinstance(cnf, dict):
                        self._compress = cnf.get("Compress")
                        self._crypt = cnf.get("Crypt")
                    # 实时速率 + 桥接信息
                    rate = c.get("Rate", {})
                    if isinstance(rate, dict):
                        self._now_rate = rate.get("NowRate", 0) or 0
                    else:
                        self._now_rate = 0
                    self._bridge_type = c.get("bridgeType") or ""
                    self._bridge_port = c.get("bridgePort") or 0
                    self._server_ip_raw = c.get("ip") or c.get("Ip") or ""
                    break
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        _LOGGER.info("启用客户端: %s (ID=%d)", self.name, self._client_id)
        try:
            await self.hass.async_add_executor_job(
                self.api.change_client_status, self._client_id, True
            )
        except HomeAssistantError as err:
            raise
        except ConnectionError as err:
            raise HomeAssistantError(f"启用客户端失败: {err}") from err
        await asyncio.sleep(REFRESH_DELAY)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        _LOGGER.info("禁用客户端(断开连接): %s (ID=%d)", self.name, self._client_id)
        try:
            await self.hass.async_add_executor_job(
                self.api.change_client_status, self._client_id, False
            )
        except HomeAssistantError as err:
            raise
        except ConnectionError as err:
            raise HomeAssistantError(f"禁用客户端失败: {err}") from err
        await asyncio.sleep(REFRESH_DELAY)
        await self.coordinator.async_request_refresh()


async def async_setup_entry(hass, config_entry, async_add_entities):
    """为所有隧道和客户端创建 SwitchEntity.

    在 async_setup_entry 中被 HA 的 Switch 平台自动调用。
    """
    entry_id = config_entry.entry_id
    data = hass.data[DOMAIN][entry_id]
    coordinator = data["coordinator"]
    api_client = data["api_client"]
    host = config_entry.data["host"]

    entities = []

    # --- 创建隧道开关 ---
    if coordinator.data:
        for tunnel_info in coordinator.data:
            entities.append(
                NpsTunnelSwitch(coordinator, api_client, entry_id, host, tunnel_info)
            )

    # --- 创建客户端开关 ---
    clients = getattr(coordinator, "clients_data", [])
    if isinstance(clients, list):
        for c in clients:
            if c.get("NoDisplay"):
                continue
            entities.append(NpsClientSwitch(coordinator, api_client, entry_id, host, c))

    _LOGGER.info("共创建 %d 个开关实体 (%d 隧道 + %d 客户端)",
                 len(entities),
                 len([e for e in entities if isinstance(e, NpsTunnelSwitch)]),
                 len([e for e in entities if isinstance(e, NpsClientSwitch)]))

    async_add_entities(entities)

    for entity in entities:
        entity.async_on_remove(
            coordinator.async_add_listener(entity._handle_coordinator_update)
        )
