"""NPS 隧道管理集成."""
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform

from .const import DOMAIN
from .coordinator import NpsDataUpdateCoordinator
from .api import NpsApiClient

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SWITCH, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """从配置入口设置 NPS 集成."""
    host = entry.data["host"]
    auth_key = entry.data["auth_key"]

    api_client = NpsApiClient(host, auth_key)
    coordinator = NpsDataUpdateCoordinator(hass, api_client)

    # 首次获取数据，验证连接是否正常
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "api_client": api_client,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载配置入口."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
