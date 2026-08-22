"""NPS 配置流 - 用户在 UI 中配置服务器地址和密钥."""
import logging
from typing import Any

import voluptuous as vol
import requests

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .api import NpsApiClient

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("host"): str,
        vol.Required("auth_key"): str,
    }
)


class NpsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """NPS 集成的配置流."""

    VERSION = 1

    def __init__(self) -> None:
        """初始化配置流."""
        self._host: str | None = None
        self._auth_key: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """处理用户配置步骤.

        引导用户输入 NPS 服务器地址和认证密钥。
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            self._host = user_input["host"].strip()
            self._auth_key = user_input["auth_key"].strip()

            # 验证 host 格式
            if ":" not in self._host:
                errors["host"] = "格式错误，请填写 ip:port"
            elif not self._auth_key:
                errors["auth_key"] = "不能为空"

            if not errors:
                # 测试连接是否可用
                info = await self._async_test_connection()
                if info is None:
                    errors["base"] = "connection_error"
                else:
                    # 设置唯一标识符（基于 host 以支持多实例）
                    await self.async_set_unique_id(f"nps_{self._host}")
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=f"NPS ({self._host})",
                        data={
                            "host": self._host,
                            "auth_key": self._auth_key,
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={"host_example": "192.168.1.100:8080"},
        )

    async def _async_test_connection(self) -> bool | None:
        """异步测试 NPS 连接和鉴权.

        Returns:
            True 测试成功，None 失败
        """
        api_client = NpsApiClient(self._host, auth_key=self._auth_key)
        try:
            result = await self.hass.async_add_executor_job(api_client.test_connection)
            return result
        except requests.exceptions.RequestException:
            _LOGGER.warning("连接 NPS 服务器失败: %s", self._host)
            return None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """返回选项配置流（暂不支持修改配置）."""
        return NpsOptionsFlowHandler(config_entry)


class NpsOptionsFlowHandler(config_entries.OptionsFlow):
    """NPS 配置选项流（预留接口）."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """初始化选项流."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """管理选项步骤."""
        return self.async_abort(reason="not_supported")
