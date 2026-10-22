"""NPS 管理面板（前端页面 + 后端命令）.

前端页面是一个 panel_custom 的 webcomponent，位于 panel/nps-panel.js，
可在侧边栏打开，也可以在设备页点「访问」直达。
"""
import json
import logging
import os
from functools import partial
from typing import Any

import voluptuous as vol
from aiohttp import web

from homeassistant.components import panel_custom, websocket_api
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .console_auth import (
    CONSOLE_API_PATH,
    CONSOLE_COOKIE_NAME,
    CONSOLE_PATH,
    cookie_header,
    panel_key_matches,
    resolve_entry_by_panel_key,
    sign_console_url,
    verify_cookie,
    verify_signature,
)
from .const import DOMAIN
from .helpers import PANEL_URL_PATH, panel_access_enabled

_LOGGER = logging.getLogger(__name__)

PANEL_STATIC_URL = "/nps_static"
PANEL_MODULE_URL = f"{PANEL_STATIC_URL}/nps-panel.js"
# 设备页「访问」的悬浮窗拦截模块（参照 esxi_control 的控制台悬浮窗）
PANEL_EMBED_URL = f"{PANEL_STATIC_URL}/nps-embed.js"
PANEL_TITLE = "NPS 管理"
PANEL_ICON = "mdi:tunnel"

# 记录面板是否已注册（重载集成时避免重复注册）
DATA_PANEL_REGISTERED = f"{DOMAIN}_panel_registered"

# 隧道类型 / 域名协议（与 NPS 服务端一致）
TUNNEL_TYPES = ("tcp", "udp", "socks5", "httpProxy", "secret", "p2p", "file")
HOST_SCHEMES = ("all", "http", "https")

PANEL_DISABLED_MESSAGE = (
    "管理面板已被「管理面板访问」开关禁用，"
    "请在 NPS 设备的实体里打开该开关后再试"
)


class PanelDisabledError(HomeAssistantError):
    """管理面板被「管理面板访问」开关禁用."""


# ----------------------------------------------------------------------
# 参数校验与表单组装
# ----------------------------------------------------------------------
TUNNEL_SCHEMA = vol.Schema(
    {
        vol.Optional("client_id", default=0): vol.Coerce(int),
        vol.Optional("type", default="tcp"): vol.In(TUNNEL_TYPES),
        vol.Optional("remark", default=""): cv.string,
        vol.Optional("port", default=0): vol.Coerce(int),
        vol.Optional("server_ip", default=""): cv.string,
        vol.Optional("target", default=""): cv.string,
        vol.Optional("local_proxy", default=False): cv.boolean,
        vol.Optional("password", default=""): cv.string,
        vol.Optional("local_path", default=""): cv.string,
        vol.Optional("strip_pre", default=""): cv.string,
        vol.Optional("proto_version", default=""): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)

HOST_SCHEMA = vol.Schema(
    {
        vol.Optional("client_id", default=0): vol.Coerce(int),
        vol.Optional("remark", default=""): cv.string,
        vol.Optional("host", default=""): cv.string,
        vol.Optional("scheme", default="all"): vol.In(HOST_SCHEMES),
        vol.Optional("location", default=""): cv.string,
        vol.Optional("target", default=""): cv.string,
        vol.Optional("local_proxy", default=False): cv.boolean,
        vol.Optional("header", default=""): cv.string,
        vol.Optional("hostchange", default=""): cv.string,
        vol.Optional("key_file_path", default=""): cv.string,
        vol.Optional("cert_file_path", default=""): cv.string,
        vol.Optional("auto_https", default=False): cv.boolean,
    },
    extra=vol.ALLOW_EXTRA,
)

CLIENT_SCHEMA = vol.Schema(
    {
        vol.Optional("remark", default=""): cv.string,
        vol.Optional("vkey", default=""): cv.string,
        vol.Optional("u", default=""): cv.string,
        vol.Optional("p", default=""): cv.string,
        vol.Optional("compress", default=True): cv.boolean,
        vol.Optional("crypt", default=True): cv.boolean,
        vol.Optional("config_conn_allow", default=True): cv.boolean,
        vol.Optional("rate_limit", default=""): cv.string,
        vol.Optional("flow_limit", default=""): cv.string,
        vol.Optional("max_conn", default=""): cv.string,
        vol.Optional("max_tunnel", default=""): cv.string,
        vol.Optional("web_username", default=""): cv.string,
        vol.Optional("web_password", default=""): cv.string,
        vol.Optional("blackiplist", default=""): cv.string,
        vol.Optional("ipwhite", default=False): cv.boolean,
        vol.Optional("ipwhitepass", default=""): cv.string,
        vol.Optional("ipwhitelist", default=""): cv.string,
        vol.Optional("expire_time", default=""): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)


def _bool_str(value: Any) -> str:
    """布尔值转 NPS 需要的 true/false 字符串."""
    return "true" if value else "false"


def _tunnel_form(payload: dict, tunnel_id: int | None = None) -> dict:
    """把面板提交的数据转换为 /index/add|edit 的表单参数."""
    data = TUNNEL_SCHEMA(payload)
    # 不同版本的表单字段名不一致（type / mode），两个都发，多余的字段服务端会忽略
    mode = data["type"]
    form = {
        "client_id": data["client_id"],
        "type": mode,
        "mode": mode,
        "remark": data["remark"],
        "port": data["port"],
        "server_ip": data["server_ip"],
        "target": data["target"],
        "local_proxy": _bool_str(data["local_proxy"]),
        "password": data["password"],
        "local_path": data["local_path"],
        "strip_pre": data["strip_pre"],
        "proto_version": data["proto_version"],
    }
    if tunnel_id is not None:
        form["id"] = tunnel_id
    return form


def _host_form(payload: dict, host_id: int | None = None) -> dict:
    """把面板提交的数据转换为 /index/addhost|edithost 的表单参数."""
    data = HOST_SCHEMA(payload)
    form = {
        "client_id": data["client_id"],
        "remark": data["remark"],
        "host": data["host"],
        "scheme": data["scheme"],
        "location": data["location"],
        "target": data["target"],
        "local_proxy": _bool_str(data["local_proxy"]),
        "header": data["header"],
        "hostchange": data["hostchange"],
        "key_file_path": data["key_file_path"],
        "cert_file_path": data["cert_file_path"],
        # 文档中该字段名为 AutoHttps，另附 snake_case 以兼容不同版本
        "AutoHttps": _bool_str(data["auto_https"]),
        "auto_https": _bool_str(data["auto_https"]),
    }
    if host_id is not None:
        form["id"] = host_id
        # 面板不回填证书内容，编辑时留空不应把已有证书清掉
        for key in ("key_file_path", "cert_file_path"):
            if not form[key]:
                form.pop(key)
    return form


def _client_form(payload: dict, client_id: int | None = None) -> dict:
    """把面板提交的数据转换为 /client/add|edit 的表单参数."""
    data = CLIENT_SCHEMA(payload)
    form = {
        "remark": data["remark"],
        "vkey": data["vkey"],
        "u": data["u"],
        "p": data["p"],
        "compress": _bool_str(data["compress"]),
        "crypt": _bool_str(data["crypt"]),
        "config_conn_allow": _bool_str(data["config_conn_allow"]),
        "rate_limit": data["rate_limit"],
        "flow_limit": data["flow_limit"],
        "max_conn": data["max_conn"],
        "max_tunnel": data["max_tunnel"],
        "web_username": data["web_username"],
        "web_password": data["web_password"],
        "blackiplist": data["blackiplist"],
        "ipwhite": _bool_str(data["ipwhite"]),
        "ipwhitepass": data["ipwhitepass"],
        "ipwhitelist": data["ipwhitelist"],
        "expire_time": data["expire_time"],
    }
    if client_id is not None:
        form["id"] = client_id
        # 面板不回填这些敏感字段，编辑时留空不应把服务器上已有值清空
        for key in ("vkey", "u", "p", "web_password", "ipwhitepass"):
            if not form[key]:
                form.pop(key)
    return form


def _require_id(payload: dict, name: str = "id") -> int:
    """从 payload 中取必填的整数 ID."""
    try:
        value = int(payload.get(name) or 0)
    except (TypeError, ValueError) as err:
        raise vol.Invalid(f"{name} 必须是整数") from err
    if value <= 0:
        raise vol.Invalid(f"缺少有效的 {name}")
    return value


# ----------------------------------------------------------------------
# 数据快照 / 命令分发
# ----------------------------------------------------------------------
def _snapshot(hass: HomeAssistant, entry_id: str, coordinator) -> dict:
    """返回面板渲染所需的完整数据."""
    return {
        "entry_id": entry_id,
        "entries": [
            {"entry_id": entry.entry_id, "title": entry.title}
            for entry in hass.config_entries.async_entries(DOMAIN)
        ],
        "tunnels": coordinator.data or [],
        "clients": getattr(coordinator, "clients_data", []) or [],
        "hosts": getattr(coordinator, "hosts_data", []) or [],
        "dashboard": getattr(coordinator, "dashboard_data", {}) or {},
        "server_time": getattr(coordinator, "server_time", 0),
        "tunnel_types": list(TUNNEL_TYPES),
        "host_schemes": list(HOST_SCHEMES),
    }


def _get_entry_data(hass: HomeAssistant, entry_id: str | None) -> tuple[str, dict]:
    """按 entry_id 取集成运行时数据；未指定时取第一个已加载的条目."""
    store = hass.data.get(DOMAIN, {})
    if entry_id:
        item = store.get(entry_id)
        if isinstance(item, dict) and "coordinator" in item:
            return entry_id, item
    for key, item in store.items():
        if isinstance(item, dict) and "coordinator" in item:
            return key, item
    raise HomeAssistantError("NPS 集成尚未加载完成，请稍后重试")


async def _async_dispatch(
    hass: HomeAssistant,
    entry_id: str,
    data: dict,
    action: str,
    payload: dict,
) -> dict:
    """执行面板操作，完成后刷新数据并返回最新快照."""
    api = data["api_client"]
    coordinator = data["coordinator"]

    async def call(func, **kwargs):
        """在线程池里调用同步的 requests 客户端."""
        return await hass.async_add_executor_job(partial(func, **kwargs))

    if action == "tunnel_add":
        await call(api.add_tunnel, **_tunnel_form(payload))
    elif action == "tunnel_edit":
        tunnel_id = _require_id(payload)
        await call(api.edit_tunnel, **_tunnel_form(payload, tunnel_id))
    elif action == "tunnel_del":
        await call(api.del_tunnel, tunnel_id=_require_id(payload))
    elif action == "tunnel_copy":
        await call(api.copy_tunnel, tunnel_id=_require_id(payload))
    elif action == "tunnel_start":
        await call(api.start_tunnel, tunnel_id=_require_id(payload))
    elif action == "tunnel_stop":
        await call(api.stop_tunnel, tunnel_id=_require_id(payload))
    elif action == "host_add":
        await call(api.add_host, **_host_form(payload))
    elif action == "host_edit":
        host_id = _require_id(payload)
        await call(api.edit_host, **_host_form(payload, host_id))
    elif action == "host_del":
        await call(api.del_host, host_id=_require_id(payload))
    elif action == "host_start":
        await call(api.start_host, host_id=_require_id(payload))
    elif action == "host_stop":
        await call(api.stop_host, host_id=_require_id(payload))
    elif action == "client_add":
        await call(api.add_client, **_client_form(payload))
    elif action == "client_edit":
        client_id = _require_id(payload)
        await call(api.edit_client, **_client_form(payload, client_id))
    elif action == "client_del":
        await call(api.del_client, client_id=_require_id(payload))
    elif action in ("client_on", "client_off"):
        await call(
            api.change_client_status,
            client_id=_require_id(payload),
            enable=action == "client_on",
        )
    elif action != "list":
        raise vol.Invalid(f"不支持的操作: {action}")

    # 操作后立即拉取一次最新数据，让面板与 HA 实体保持一致
    try:
        await coordinator.async_refresh()
    except Exception as err:  # noqa: BLE001 - 操作可能已成功，刷新失败不应报操作失败
        _LOGGER.warning("NPS 操作已提交，但刷新数据失败: %s", err)

    return _snapshot(hass, entry_id, coordinator)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "nps/action",
        vol.Required("action"): cv.string,
        vol.Optional("entry_id"): cv.string,
        vol.Optional("data", default=dict): dict,
    }
)
# 注意装饰器顺序：require_admin 是同步 wrapper（内部不会 await、也不返回协程结果），
# 必须包在 async_response（负责把协程调度成后台任务）之外。
@websocket_api.require_admin
@websocket_api.async_response
async def async_handle_nps_action(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """处理管理面板的所有请求（需管理员权限）."""
    try:
        entry_id, data = _get_entry_data(hass, msg.get("entry_id"))
        if not panel_access_enabled(hass, entry_id):
            raise PanelDisabledError(PANEL_DISABLED_MESSAGE)
        if msg["action"] == "console_url":
            url = sign_console_url(hass, entry_id)
            if not url:
                raise HomeAssistantError(
                    "无法签发面板地址（请检查 HA 的 internal_url / external_url 配置）"
                )
            connection.send_result(
                msg["id"], {"success": True, "url": url, "entry_id": entry_id}
            )
            return
        result = await _async_dispatch(
            hass, entry_id, data, msg["action"], msg.get("data") or {}
        )
    except PanelDisabledError as err:
        connection.send_error(msg["id"], "panel_disabled", str(err))
        return
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    except (HomeAssistantError, ConnectionError) as err:
        connection.send_error(msg["id"], "nps_error", str(err))
        return
    except Exception as err:  # noqa: BLE001 - 面板需要把任何异常回显给用户
        _LOGGER.exception("NPS 管理面板操作失败: %s", msg.get("action"))
        connection.send_error(msg["id"], "nps_error", str(err))
        return

    connection.send_result(msg["id"], result)


# ----------------------------------------------------------------------
# 独立页面 + 会话鉴权（做法同 ikuai 集成）
# ----------------------------------------------------------------------
_CONSOLE_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NPS 隧道管理</title>
<style>
  :root {
    color-scheme: light dark;
    --primary-background-color: #fafafa;
    --card-background-color: #ffffff;
    --primary-text-color: #212121;
    --secondary-text-color: #727272;
    --divider-color: #e0e0e0;
    --secondary-background-color: #f5f5f5;
    --primary-color: #03a9f4;
    --text-primary-color: #ffffff;
    --success-color: #43a047;
    --error-color: #db4437;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --primary-background-color: #111111;
      --card-background-color: #1c1c1c;
      --primary-text-color: #e1e1e1;
      --secondary-text-color: #a3a3a3;
      --divider-color: #2e2e2e;
      --secondary-background-color: #232323;
    }
  }
  html, body { margin: 0; height: 100%; background: var(--primary-background-color); }
  body { font-family: "Roboto", "Helvetica Neue", Arial, sans-serif; color: var(--primary-text-color); }
  #root { height: 100%; }
  #boot { padding: 28px; font-size: 14px; color: var(--secondary-text-color); }
</style>
</head>
<body>
<div id="root"><div id="boot">正在加载 NPS 管理面板…</div></div>
<script type="module" src="__MODULE__"></script>
<script type="module">
  customElements.whenDefined("nps-panel").then(() => {
    const root = document.getElementById("root");
    const el = document.createElement("nps-panel");
    el.startHttp(__ENTRY__);
    root.replaceChildren(el);
  });
</script>
</body>
</html>
"""


def _console_html(entry_id: str) -> str:
    """独立面板页（不依赖 HA 前端 SPA，可在 iframe 里跑）."""
    return _CONSOLE_PAGE_TEMPLATE.replace("__MODULE__", PANEL_MODULE_URL).replace(
        "__ENTRY__", json.dumps(entry_id)
    )


def _plain(text: str, status: int) -> web.Response:
    return web.Response(status=status, text=text, content_type="text/plain")


class NpsConsolePageView(HomeAssistantView):
    """签名链接入口：校验 authSig → 下发会话 Cookie → 返回独立面板页."""

    requires_auth = False
    url = CONSOLE_PATH
    name = "nps:console"

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        entry_id = request.query.get("entry") or ""

        authorized = await verify_signature(hass, request)
        if not authorized:
            # 第二入口：面板密钥（加盐、整点轮换、旧密钥宽限一个周期）
            key = request.query.get("key")
            if key:
                if not entry_id:
                    entry_id = resolve_entry_by_panel_key(hass, key) or ""
                authorized = bool(entry_id) and panel_key_matches(
                    hass, entry_id, key
                )
        if not authorized:
            return _plain(
                "NPS 管理面板：链接或密钥无效/已过期，请从设备页重新打开。",
                401,
            )

        entry = hass.config_entries.async_get_entry(entry_id) if entry_id else None
        if entry is None or entry.domain != DOMAIN:
            return _plain("NPS 管理面板：配置条目不存在。", 404)
        if not isinstance(hass.data.get(DOMAIN, {}).get(entry_id), dict):
            return _plain("NPS 集成尚未加载完成，请稍后刷新。", 409)
        if not panel_access_enabled(hass, entry_id):
            return _plain(PANEL_DISABLED_MESSAGE, 403)

        return web.Response(
            text=_console_html(entry_id),
            content_type="text/html",
            headers={
                "Set-Cookie": cookie_header(
                    hass, entry_id, request.scheme == "https"
                ),
                "Cache-Control": "no-store",
            },
        )


class NpsConsoleApiView(HomeAssistantView):
    """面板数据接口：会话 Cookie / authSig / 面板密钥（?key= 或 body.key）."""

    requires_auth = False
    url = CONSOLE_API_PATH
    name = "nps:console_api"

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]

        try:
            body = await request.json()
        except ValueError:
            return web.json_response(
                {"success": False, "code": "invalid_format", "message": "请求体必须是 JSON"}
            )

        # 鉴权三条路：会话 Cookie → authSig（页面首次带签名直连）→ 面板密钥
        # （?key= 或 body.key，加盐、整点轮换、旧密钥宽限一个周期）
        entry_id = verify_cookie(hass, request.cookies.get(CONSOLE_COOKIE_NAME))
        if entry_id is None:
            key = request.query.get("key") or (
                body.get("key") if isinstance(body, dict) else None
            )
            if await verify_signature(hass, request):
                entry_id = request.query.get("entry") or ""
            else:
                entry_id = (
                    request.query.get("entry")
                    or resolve_entry_by_panel_key(hass, key)
                    or ""
                )
                if not entry_id or not panel_key_matches(hass, entry_id, key):
                    return web.json_response(
                        {
                            "success": False,
                            "code": "unauthorized",
                            "message": "会话或密钥已过期，请重新打开管理面板",
                        },
                        status=401,
                    )

        action = body.get("action") if isinstance(body, dict) else None
        payload = (body.get("data") if isinstance(body, dict) else None) or {}
        if not isinstance(action, str):
            return web.json_response(
                {"success": False, "code": "invalid_format", "message": "缺少 action"}
            )

        try:
            if not panel_access_enabled(hass, entry_id):
                raise PanelDisabledError(PANEL_DISABLED_MESSAGE)
            if action == "console_url":
                url = sign_console_url(hass, entry_id)
                if not url:
                    raise HomeAssistantError(
                        "无法签发面板地址（请检查 HA 的 internal_url / external_url 配置）"
                    )
                return web.json_response(
                    {"success": True, "url": url, "entry_id": entry_id}
                )
            _, data = _get_entry_data(hass, entry_id)
            snapshot = await _async_dispatch(hass, entry_id, data, action, payload)
        except PanelDisabledError as err:
            return web.json_response(
                {"success": False, "code": "panel_disabled", "message": str(err)}
            )
        except vol.Invalid as err:
            return web.json_response(
                {"success": False, "code": "invalid_format", "message": str(err)}
            )
        except (HomeAssistantError, ConnectionError) as err:
            return web.json_response(
                {"success": False, "code": "nps_error", "message": str(err)}
            )
        except Exception as err:  # noqa: BLE001 - 全部回显给页面
            _LOGGER.exception("NPS 面板接口异常: %s", action)
            return web.json_response(
                {"success": False, "code": "nps_error", "message": str(err)}
            )

        return web.json_response({"success": True, **snapshot})


# ----------------------------------------------------------------------
# 面板注册
# ----------------------------------------------------------------------
async def async_setup_panel(hass: HomeAssistant) -> None:
    """注册侧边栏面板、静态资源与 websocket 命令（只注册一次）.

    面板注册失败不应影响隧道/客户端实体本身，因此各步骤单独兜底。
    """
    if hass.data.get(DATA_PANEL_REGISTERED):
        return
    hass.data[DATA_PANEL_REGISTERED] = True

    try:
        websocket_api.async_register_command(hass, async_handle_nps_action)
    except ValueError as err:
        _LOGGER.debug("NPS websocket 命令已注册: %s", err)

    # 独立页面与数据接口：签名链接入口 + 会话 Cookie 鉴权（全局只注册一次）
    views_key = f"{DOMAIN}_console_views"
    if not hass.data.get(views_key):
        hass.http.register_view(NpsConsolePageView)
        hass.http.register_view(NpsConsoleApiView)
        hass.data[views_key] = True

    static_dir = os.path.join(os.path.dirname(__file__), "panel")
    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(PANEL_STATIC_URL, static_dir, cache_headers=False)]
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("NPS 面板静态资源注册失败: %s", err)

    # 同时把模块作为全局前端资源加载，提供 Lovelace 卡片
    # （type: custom:nps-panel-card），点击后在当前页面弹悬浮窗，不新开标签页
    try:
        add_extra_js_url(hass, PANEL_MODULE_URL)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("NPS 管理面板前端脚本注册失败（悬浮窗卡片不可用）: %s", err)

    # 再注入「控制台悬浮窗」模块：设备页点「访问」时不再整页跳转，
    #   而是在 HA 界面内弹出可拖动/缩放、可调整大小的 iframe 悬浮窗
    #   （与 esxi_control 的控制台悬浮窗同一套做法，纯前端拦截，无需改后端）。
    try:
        add_extra_js_url(hass, PANEL_EMBED_URL)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("NPS 悬浮窗前端模块注册失败（「访问」仍在新页面打开）: %s", err)

    try:
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_URL_PATH,
            webcomponent_name="nps-panel",
            sidebar_title=PANEL_TITLE,
            sidebar_icon=PANEL_ICON,
            module_url=PANEL_MODULE_URL,
            require_admin=True,
            config={"domain": DOMAIN},
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.error(
            "NPS 管理面板注册失败（路径 /%s 可能已被占用）: %s", PANEL_URL_PATH, err
        )
        return

    _LOGGER.debug("NPS 管理面板已注册: /%s", PANEL_URL_PATH)
