"""NPS 通用辅助函数."""
import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo

from .console_auth import get_base_url, sign_console_url
from .const import CONF_PANEL_ACCESS, DOMAIN

_LOGGER = logging.getLogger(__name__)

# 侧边栏面板的 URL 路径（panel_custom 注册的 frontend_url_path）
PANEL_URL_PATH = "nps"


def get_panel_url(hass: HomeAssistant) -> str | None:
    """侧边栏面板地址（需要已登录 HA 的前端）."""
    base = get_base_url(hass)
    return f"{base}/{PANEL_URL_PATH}" if base else None


def panel_access_enabled(hass: HomeAssistant, entry_id: str) -> bool:
    """管理面板是否允许访问（由「管理面板访问」开关控制，默认允许）."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        return True
    return bool(entry.options.get(CONF_PANEL_ACCESS, True))


def get_console_url(hass: HomeAssistant, entry_id: str) -> str | None:
    """管理面板的签名地址（authSig，默认 24 小时有效）；被禁用时返回 None."""
    if not panel_access_enabled(hass, entry_id):
        return None
    return sign_console_url(hass, entry_id)


def _nps_device_identifier(entry_id: str) -> tuple[str, str]:
    """NPS 设备在设备注册表里的唯一标识."""
    return (DOMAIN, f"{entry_id}_nps_server")


def _async_get_nps_device(
    registry: dr.DeviceRegistry, entry_id: str
) -> dr.DeviceEntry | None:
    """按 identifier 取设备（适配新版 device_registry API）.

    HA 2025.12 起 ``async_get_device`` 被弃用（identifier/connection 不再跨
    配置条目唯一），2027.8 将移除；这里优先用 ``async_get_device_by_identifier``，
    旧版本没有该 API 时回退到老接口。
    """
    identifier = _nps_device_identifier(entry_id)
    get_by_identifier = getattr(registry, "async_get_device_by_identifier", None)
    if get_by_identifier is not None:
        # 新 API 两个参数都是必需的：identifier 不再跨配置条目唯一，
        # 必须同时指定 config_entry_id 才能定位到本条目创建的那台设备
        return get_by_identifier(identifier, config_entry_id=entry_id)
    return registry.async_get_device(identifiers={identifier})  # HA 旧版回退


def get_device_id(hass: HomeAssistant, entry_id: str) -> str | None:
    """返回该配置条目对应的 NPS 设备 id."""
    device = _async_get_nps_device(dr.async_get(hass), entry_id)
    return device.id if device is not None else None


@callback
def set_panel_access(hass: HomeAssistant, entry_id: str, enabled: bool) -> None:
    """开关切换时更新持久化选项，并同步设备页的「访问」链接."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is not None:
        options = dict(entry.options)
        options[CONF_PANEL_ACCESS] = enabled
        hass.config_entries.async_update_entry(entry, options=options)

    registry = dr.async_get(hass)
    device = _async_get_nps_device(registry, entry_id)
    if device is not None:
        # 禁用时移除「访问」链接，启用时补回（带签名的面板地址）
        registry.async_update_device(
            device.id,
            configuration_url=get_console_url(hass, entry_id) if enabled else None,
        )
    _LOGGER.debug("NPS 管理面板访问已%s", "启用" if enabled else "禁用")


def build_device_info(
    hass: HomeAssistant, entry_id: str, host: str
) -> DeviceInfo:
    """构建设备信息（隧道/传感器/开关共用同一个设备）."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}_nps_server")},
        name=f"NPS Server ({host})",
        manufacturer="NPS",
        model="Tunnel Server",
        configuration_url=get_console_url(hass, entry_id),
    )
