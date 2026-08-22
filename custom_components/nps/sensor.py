"""NPS sensor entities - traffic stats, client info, etc."""
import logging

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.typing import StateType

from .const import DOMAIN
from .coordinator import NpsDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


# 流量传感器：字节 → GB 的转换系数
BYTES_TO_GB = 1 / (1024 ** 3)


class NpsDashboardSensor(SensorEntity):
    """NPS statistics sensor entity."""

    def __init__(
        self,
        coordinator: NpsDataUpdateCoordinator,
        entry_id: str,
        host: str,
        sensor_key: str,
        sensor_name: str,
        unit: str | None = None,
        icon: str | None = None,
        state_class: SensorStateClass | None = None,
        device_class: str | None = None,
        divisor: float | None = None,
    ) -> None:
        """Initialize NPS sensor.

        Args:
            divisor: 原始值的除数（如 1024**3 用于 B→GB 转换）
        """
        self.coordinator = coordinator
        self.entry_id = entry_id
        self._sensor_key = sensor_key
        self._divisor = divisor or 1.0
        self._attr_unique_id = f"{entry_id}_nps_{sensor_key}"
        self._attr_name = sensor_name
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_nps_server")},
            name=f"NPS Server ({host})",
            manufacturer="NPS",
            model="Tunnel Server",
        )
        if state_class:
            self._attr_state_class = state_class
        if device_class:
            self._attr_device_class = device_class

    @property
    def native_value(self) -> StateType:
        dashboard = getattr(self.coordinator, "dashboard_data", {})
        raw_val = dashboard.get(self._sensor_key)
        if raw_val is not None:
            # 字符串类型直接返回，不做数值转换（serverIps, bridgeTypes 等）
            if isinstance(raw_val, (str, bool)):
                return raw_val
            return round(raw_val * self._divisor, 2)
        return raw_val

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


# (key, name, unit, icon, state_class, device_class, divisor)
DASHBOARD_SENSORS = [
    # 客户端统计
    ("clientCount", "Client Total", None, "mdi:account-group", SensorStateClass.TOTAL),
    ("clientOnlineCount", "Clients Online", None, "mdi:account-check", SensorStateClass.TOTAL),
    ("totalConnections", "Total Connections", None, "mdi:connection", SensorStateClass.MEASUREMENT),
    # 流量（字节→GB）
    ("inletFlowCount", "Inlet Traffic", "GB", "mdi:download-network-outline", SensorStateClass.TOTAL_INCREASING, None, BYTES_TO_GB),
    ("exportFlowCount", "Export Traffic", "GB", "mdi:upload-network-outline", SensorStateClass.TOTAL_INCREASING, None, BYTES_TO_GB),
    # 隧道统计
    ("tunnelTotal", "Tunnel Total", None, "mdi:tunnel-variant", SensorStateClass.TOTAL),
    ("tcpC", "TCP Tunnels", None, "mdi:tunnel", SensorStateClass.TOTAL),
    ("udpCount", "UDP Tunnels", None, "mdi:tunnel", SensorStateClass.TOTAL),
    ("socks5Count", "SOCKS5 Tunnels", None, "mdi:tunnel", SensorStateClass.TOTAL),
    ("httpProxyCount", "HTTP Proxy Tunnels", None, "mdi:tunnel", SensorStateClass.TOTAL),
    ("secretCount", "Secret Tunnels", None, "mdi:tunnel-lock", SensorStateClass.TOTAL),
    ("p2pCount", "P2P Tunnels", None, "mdi:tunnel", SensorStateClass.TOTAL),
    ("fileCount", "File Tunnels", None, "mdi:file-document-outline", SensorStateClass.TOTAL),
    # 域名映射
    ("hostCount", "Host Mappings", None, "mdi:dns-outline", SensorStateClass.TOTAL),
    # 从客户端数据聚合的额外指标
    ("nowRateBps", "Realtime Rate", "KB/s", "mdi:speedometer", SensorStateClass.MEASUREMENT, None, 1 / 1024),
    ("serverIps", "Server IPs", None, "mdi:server-network"),
    ("bridgeTypes", "Bridge Protocols", None, "mdi:swap-horizontal"),
]


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up NPS sensors from config entry."""
    entry_id = config_entry.entry_id
    data = hass.data[DOMAIN][entry_id]
    coordinator = data["coordinator"]
    host = config_entry.data["host"]

    entities = []
    for sensor_def in DASHBOARD_SENSORS:
        key = sensor_def[0]
        name = sensor_def[1]
        unit = sensor_def[2] if len(sensor_def) > 2 else None
        icon = sensor_def[3] if len(sensor_def) > 3 else None
        sc = sensor_def[4] if len(sensor_def) > 4 else None
        dc = sensor_def[5] if len(sensor_def) > 5 else None
        div = sensor_def[6] if len(sensor_def) > 6 else None
        entities.append(NpsDashboardSensor(
            coordinator=coordinator,
            entry_id=entry_id,
            host=host,
            sensor_key=key,
            sensor_name=name,
            unit=unit,
            icon=icon,
            state_class=sc,
            device_class=dc,
            divisor=div,
        ))

    _LOGGER.info("Created %d NPS sensors", len(entities))
    async_add_entities(entities)
