"""NPS sensor entities - traffic stats, client info, etc."""
import logging
from datetime import timedelta

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.typing import StateType

from .console_auth import panel_key_info
from .const import DOMAIN
from .coordinator import NpsDataUpdateCoordinator
from .helpers import build_device_info, get_device_id, panel_access_enabled

# 「所有实体」传感器最多列出的实体数（避免单条状态属性超过 recorder 上限）
MAX_LISTED_ENTITIES = 200

# 隧道类型传感器属性里最多列出的隧道条数（同样为了避免属性过大）
MAX_LISTED_TUNNELS = 50

_LOGGER = logging.getLogger(__name__)


# 流量传感器：字节 → GB 的转换系数
BYTES_TO_GB = 1 / (1024 ** 3)


def _human_bytes(value) -> str:
    """字节数 → 可读文本（属性里展示用，B 取整、其余两位小数）."""
    try:
        num = float(value or 0)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024 or unit == "TB":
            text = f"{num:.0f}" if unit == "B" else f"{num:.2f}"
            return f"{text} {unit}"
        num /= 1024
    return "0 B"


def _tunnel_brief(tunnel: dict) -> dict:
    """单条隧道摘要（类型传感器属性用，字段精简且稳定）."""
    client = tunnel.get("Client") if isinstance(tunnel.get("Client"), dict) else {}
    target = tunnel.get("Target") if isinstance(tunnel.get("Target"), dict) else {}
    flow = tunnel.get("Flow") if isinstance(tunnel.get("Flow"), dict) else {}
    target_str = str(target.get("TargetStr") or "").split("\n")[0].strip()
    return {
        "tunnel_id": tunnel.get("Id"),
        "remark": tunnel.get("Remark") or None,
        "mode": tunnel.get("Mode") or tunnel.get("Type"),
        "port": tunnel.get("Port"),
        "target": target_str or None,
        "client_id": client.get("Id"),
        "client_online": client.get("IsConnect"),
        "running": bool(tunnel.get("RunStatus", False)),
        "enabled": tunnel.get("Status"),
        "inlet_flow": _human_bytes(flow.get("InletFlow")),
        "export_flow": _human_bytes(flow.get("ExportFlow")),
    }


class NpsDashboardSensor(SensorEntity):
    """NPS statistics sensor entity."""

    # 隧道明细不进 recorder：避免历史库膨胀，也避免触及状态属性大小上限
    _unrecorded_attributes = frozenset({"tunnels"})

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
        object_id: str | None = None,
        tunnel_mode: str | None = None,
    ) -> None:
        """Initialize NPS sensor.

        Args:
            divisor: 原始值的除数（如 1024**3 用于 B→GB 转换）
            object_id: 固定的 entity_id 后缀（中文名称 slugify 后为空，必须显式给定，
                并且沿用早期的英文名 slug，避免升级后实体 ID 漂移）
            tunnel_mode: 隧道类型实体的模式（"tcp"/"udp"/…/，`*` 表示全部），
                给了该值时状态属性里会附带这一类隧道的明细列表
        """
        self.coordinator = coordinator
        self.entry_id = entry_id
        self._sensor_key = sensor_key
        # None = 不做换算：计数值保持整数，避免 0 → 0.0
        self._divisor = divisor
        self._tunnel_mode = tunnel_mode.lower() if tunnel_mode else None
        self._attr_unique_id = f"{entry_id}_nps_{sensor_key}"
        self._attr_name = sensor_name
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._host = host
        self._object_id = object_id or sensor_key
        if state_class:
            self._attr_state_class = state_class
        if device_class:
            self._attr_device_class = device_class

    @property
    def suggested_object_id(self) -> str | None:
        """固定 entity_id，避免中文名称被 slugify 成空."""
        return self._object_id

    @property
    def device_info(self) -> DeviceInfo:
        """设备信息（configuration_url 指向 NPS 管理面板）."""
        return build_device_info(self.hass, self.entry_id, self._host)

    @property
    def native_value(self) -> StateType:
        dashboard = getattr(self.coordinator, "dashboard_data", {})
        raw_val = dashboard.get(self._sensor_key)
        if raw_val is None:
            return None
        # 字符串类型直接返回，不做数值转换（serverIps, bridgeTypes 等）
        if isinstance(raw_val, (str, bool)):
            return raw_val
        # 计数类：原样返回整数；只有配了 divisor 的才换算（流量 GB、速率 KB/s）
        if self._divisor is None:
            return raw_val
        return round(raw_val * self._divisor, 2)

    @property
    def extra_state_attributes(self) -> dict | None:
        """隧道类型实体附加该类型下每条隧道的明细（其它传感器不附加）."""
        if self._tunnel_mode is None:
            return None
        rows = self._type_tunnels()
        attrs: dict = {"tunnels": rows, "returned": len(rows)}
        if len(rows) >= MAX_LISTED_TUNNELS:
            attrs["truncated"] = True
        return attrs

    def _type_tunnels(self) -> list[dict]:
        """按类型（或 `*` = 全部）从 coordinator 的隧道列表里取摘要."""
        tunnels = getattr(self.coordinator, "data", None) or []
        wanted = self._tunnel_mode
        rows: list[dict] = []
        for tunnel in tunnels:
            if not isinstance(tunnel, dict):
                continue
            # NPS 不同版本里类型字段是 Mode，个别分支用 Type
            mode = str(tunnel.get("Mode") or tunnel.get("Type") or "").lower()
            if wanted != "*" and mode != wanted:
                continue
            rows.append(_tunnel_brief(tunnel))
            if len(rows) >= MAX_LISTED_TUNNELS:
                break
        return rows

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


# 名称全部使用中文；object_id 固定为早期英文名 slug，保证升级后 entity_id 不变
DASHBOARD_SENSORS = [
    # 客户端统计
    {
        "key": "clientCount",
        "name": "客户端总数",
        "object_id": "client_total",
        "icon": "mdi:account-group",
        "state_class": SensorStateClass.TOTAL,
    },
    {
        "key": "clientOnlineCount",
        "name": "在线客户端",
        "object_id": "clients_online",
        "icon": "mdi:account-check",
        "state_class": SensorStateClass.TOTAL,
    },
    {
        "key": "totalConnections",
        "name": "连接总数",
        "object_id": "total_connections",
        "icon": "mdi:connection",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    # 流量（字节→GB）
    {
        "key": "inletFlowCount",
        "name": "入口流量",
        "object_id": "inlet_traffic",
        "unit": "GB",
        "icon": "mdi:download-network-outline",
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "divisor": BYTES_TO_GB,
    },
    {
        "key": "exportFlowCount",
        "name": "出口流量",
        "object_id": "export_traffic",
        "unit": "GB",
        "icon": "mdi:upload-network-outline",
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "divisor": BYTES_TO_GB,
    },
    # 隧道统计
    {
        "key": "tunnelTotal",
        "name": "隧道总数",
        "object_id": "tunnel_total",
        "icon": "mdi:tunnel-variant",
        "state_class": SensorStateClass.TOTAL,
        "tunnel_mode": "*",
    },
    {
        "key": "tcpC",
        "name": "TCP 隧道",
        "object_id": "tcp_tunnels",
        "icon": "mdi:tunnel",
        "state_class": SensorStateClass.TOTAL,
        "tunnel_mode": "tcp",
    },
    {
        "key": "udpCount",
        "name": "UDP 隧道",
        "object_id": "udp_tunnels",
        "icon": "mdi:tunnel",
        "state_class": SensorStateClass.TOTAL,
        "tunnel_mode": "udp",
    },
    {
        "key": "socks5Count",
        "name": "SOCKS5 隧道",
        "object_id": "socks5_tunnels",
        "icon": "mdi:tunnel",
        "state_class": SensorStateClass.TOTAL,
        "tunnel_mode": "socks5",
    },
    {
        "key": "httpProxyCount",
        "name": "HTTP 代理隧道",
        "object_id": "http_proxy_tunnels",
        "icon": "mdi:tunnel",
        "state_class": SensorStateClass.TOTAL,
        "tunnel_mode": "httpproxy",
    },
    {
        "key": "secretCount",
        "name": "秘密隧道",
        "object_id": "secret_tunnels",
        "icon": "mdi:tunnel-lock",
        "state_class": SensorStateClass.TOTAL,
        "tunnel_mode": "secret",
    },
    {
        "key": "p2pCount",
        "name": "P2P 隧道",
        "object_id": "p2p_tunnels",
        "icon": "mdi:tunnel",
        "state_class": SensorStateClass.TOTAL,
        "tunnel_mode": "p2p",
    },
    {
        "key": "fileCount",
        "name": "文件隧道",
        "object_id": "file_tunnels",
        "icon": "mdi:file-document-outline",
        "state_class": SensorStateClass.TOTAL,
        "tunnel_mode": "file",
    },
    # 域名映射
    {
        "key": "hostCount",
        "name": "域名映射",
        "object_id": "host_mappings",
        "icon": "mdi:dns-outline",
        "state_class": SensorStateClass.TOTAL,
    },
    # 从客户端数据聚合的额外指标
    {
        "key": "nowRateBps",
        "name": "实时速率",
        "object_id": "realtime_rate",
        "unit": "KB/s",
        "icon": "mdi:speedometer",
        "state_class": SensorStateClass.MEASUREMENT,
        "divisor": 1 / 1024,
    },
    {
        "key": "serverIps",
        "name": "服务器 IP",
        "object_id": "server_ips",
        "icon": "mdi:server-network",
    },
    {
        "key": "bridgeTypes",
        "name": "网桥协议",
        "object_id": "bridge_protocols",
        "icon": "mdi:swap-horizontal",
    },
]


class NpsAllEntitiesSensor(SensorEntity):
    """把该设备所有实体的 entity_id / name / icon / state 汇总到属性里.

    状态值 = 实体数量，属性 entities 为明细列表；实体状态变化时自动更新。
    """

    _attr_should_poll = False
    _attr_icon = "mdi:format-list-bulleted"

    def __init__(
        self,
        coordinator: NpsDataUpdateCoordinator,
        entry_id: str,
        host: str,
    ) -> None:
        self.coordinator = coordinator
        self.entry_id = entry_id
        self._host = host
        self._attr_unique_id = f"{entry_id}_nps_all_entities"
        self._attr_name = "所有实体"
        self._items: list[dict] = []
        self._tracked: list[str] = []
        self._unsub_states = None

    @property
    def suggested_object_id(self) -> str | None:
        """固定 entity_id，避免中文名称被 slugify 成空."""
        return "all_entities"

    @property
    def device_info(self) -> DeviceInfo:
        """设备信息（configuration_url 指向 NPS 管理面板）."""
        return build_device_info(self.hass, self.entry_id, self._host)

    @property
    def native_value(self) -> StateType:
        """该设备下的实体数量."""
        return len(self._items)

    @property
    def extra_state_attributes(self) -> dict:
        attributes = {
            "count": len(self._items),
            "entities": self._items,
        }
        if len(self._items) >= MAX_LISTED_ENTITIES:
            attributes["truncated"] = True
        return attributes

    async def async_added_to_hass(self) -> None:
        self._refresh_items()
        self._ensure_tracking()
        # 兜底：新增/删除实体（如新增隧道）时也能刷新清单
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._handle_interval, timedelta(seconds=60)
            )
        )
        self.async_on_remove(
            self.hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._handle_registry_update
            )
        )
        self.async_on_remove(self._stop_tracking)

    @callback
    def _handle_interval(self, now) -> None:
        self._ensure_tracking()
        self._refresh_items()
        self.async_write_ha_state()

    @callback
    def _handle_state_change(self, event) -> None:
        self._refresh_items()
        self.async_write_ha_state()

    @callback
    def _handle_registry_update(self, event) -> None:
        if event.data.get("device_id") != get_device_id(self.hass, self.entry_id):
            return
        self._ensure_tracking()
        self._refresh_items()
        self.async_write_ha_state()

    def _registry_entries(self) -> list:
        """返回该设备（含禁用）的实体注册表条目."""
        device_id = get_device_id(self.hass, self.entry_id)
        if device_id is None:
            return []
        return er.async_entries_for_device(
            er.async_get(self.hass), device_id, include_disabled_entities=True
        )

    def _refresh_items(self) -> None:
        items: list[dict] = []
        for entry in sorted(
            self._registry_entries(), key=lambda item: item.entity_id
        ):
            if len(items) >= MAX_LISTED_ENTITIES:
                break
            state = self.hass.states.get(entry.entity_id)
            items.append(
                {
                    "entity_id": entry.entity_id,
                    "name": entry.name
                    or entry.original_name
                    or (state.name if state is not None else entry.entity_id),
                    "icon": entry.icon
                    or entry.original_icon
                    or (
                        state.attributes.get("icon")
                        if state is not None
                        else None
                    ),
                    "state": state.state if state is not None else "unavailable",
                }
            )
        self._items = items

    def _ensure_tracking(self) -> None:
        """跟随所有成员实体的状态变化（排除自身，避免自触发循环）."""
        ids = [
            item["entity_id"]
            for item in self._items
            if item["entity_id"] != self.entity_id
        ]
        if ids == self._tracked:
            return
        self._stop_tracking()
        self._tracked = ids
        if ids:
            self._unsub_states = async_track_state_change_event(
                self.hass, ids, self._handle_state_change
            )

    def _stop_tracking(self) -> None:
        if self._unsub_states is not None:
            self._unsub_states()
            self._unsub_states = None


class NpsAccessKeySensor(SensorEntity):
    """管理面板访问密钥（加盐、整点轮换、旧密钥宽限一个周期）.

    状态 = 剩余有效分钟数；属性给出密钥本身、可读剩余时长和可直接打开的访问
    地址，便于在自动化 / 卡片里取用（例如拼到二维码或通知里）。

    密钥口径与爱快集成的 ``sensor.ikuai_api_key`` 一致：
    ``key = md5(集成盐 | 整点序号 | 主机地址 | 条目 id)[:16]``；
    盐随机生成、只存在内存里，整点自动换新，上一把密钥再宽限一小时。
    """

    _attr_should_poll = False
    _attr_icon = "mdi:key-variant"
    # 注意：这里**不能**声明 device_class=DURATION —— HA 对 duration 有单位规范化，
    # 会把 native 的 min 再换算回规范单位 s（状态值变成 分钟×60 的浮点数）。
    _attr_native_unit_of_measurement = "min"
    _attr_state_class = SensorStateClass.MEASUREMENT
    # 密钥与地址不写 recorder（历史库不塞敏感值，也省体积）
    _unrecorded_attributes = frozenset(
        {"密钥", "剩余时长", "访问地址", "过期时间", "上一把密钥", "算法"}
    )

    def __init__(
        self,
        coordinator: NpsDataUpdateCoordinator,
        entry_id: str,
        host: str,
    ) -> None:
        self.coordinator = coordinator
        self.entry_id = entry_id
        self._host = host
        self._attr_unique_id = f"{entry_id}_nps_access_key"
        self._attr_name = "面板访问密钥"

    @property
    def suggested_object_id(self) -> str | None:
        """固定 entity_id，避免中文名称被 slugify 成空."""
        return "panel_access_key"

    @property
    def device_info(self) -> DeviceInfo:
        """设备信息（configuration_url 指向 NPS 管理面板）."""
        return build_device_info(self.hass, self.entry_id, self._host)

    @property
    def available(self) -> bool:
        """「管理面板访问」开关关闭时不再提供密钥."""
        return panel_access_enabled(self.hass, self.entry_id)

    @property
    def native_value(self) -> StateType:
        """密钥剩余有效时长（分钟，不足 1 分钟按 1 分钟）."""
        info = self._key_info()
        if not info:
            return None
        return info["remaining_minutes"]

    @property
    def extra_state_attributes(self) -> dict:
        info = self._key_info() or {}
        return {
            "密钥": info.get("key"),
            "剩余时长": info.get("remaining_text"),
            "访问地址": info.get("url"),
            "过期时间": info.get("expires_at"),
            "上一把密钥": info.get("prev_key"),
            "算法": (
                "md5(集成盐 | 整点序号 | 主机地址 | 条目id)[:16]，"
                "整点换新、旧密钥宽限 1 小时"
            ),
        }

    def _key_info(self) -> dict | None:
        """当前整点的密钥信息（整点首次读取时自动换新）."""
        return panel_key_info(self.hass, self.entry_id)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up NPS sensors from config entry."""
    entry_id = config_entry.entry_id
    data = hass.data[DOMAIN][entry_id]
    coordinator = data["coordinator"]
    host = config_entry.data["host"]

    entities = []
    for sensor_def in DASHBOARD_SENSORS:
        entities.append(NpsDashboardSensor(
            coordinator=coordinator,
            entry_id=entry_id,
            host=host,
            sensor_key=sensor_def["key"],
            sensor_name=sensor_def["name"],
            unit=sensor_def.get("unit"),
            icon=sensor_def.get("icon"),
            state_class=sensor_def.get("state_class"),
            device_class=sensor_def.get("device_class"),
            divisor=sensor_def.get("divisor"),
            object_id=sensor_def.get("object_id"),
            tunnel_mode=sensor_def.get("tunnel_mode"),
        ))

    # 管理面板访问密钥（剩余有效时长 / 密钥 / 访问地址）
    entities.append(
        NpsAccessKeySensor(coordinator=coordinator, entry_id=entry_id, host=host)
    )

    # 「所有实体」汇总传感器放在最后创建，确保前面的实体已进注册表
    entities.append(
        NpsAllEntitiesSensor(coordinator=coordinator, entry_id=entry_id, host=host)
    )

    _LOGGER.info("Created %d NPS sensors", len(entities))
    async_add_entities(entities)
