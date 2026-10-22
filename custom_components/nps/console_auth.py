"""NPS 管理面板的链接签名与会话鉴权（做法与 ikuai 集成一致）.

为什么不用「HA 前端面板 + 登录态」
--------------------------------
HA 的侧边栏面板必须是已登录 HA 的前端 SPA，链接无法单独分享/在外部地址上
直接打开，页面里的 websocket 也会因为跨环境没有 token 而失败。

这里改成爱快集成那套：

1. 设备页「访问」= HA 官方 ``async_sign_path`` 签发的带 ``authSig`` 的地址
   （默认 24 小时有效），因此远程（外部地址）访问同样是 HA 自己签的名；
2. 第一次带签名打开 ``/nps/console`` 时校验 authSig，随后下发本集成自己的
   HttpOnly Cookie，之后页面里的所有 ``POST /nps/api/action`` 都靠它鉴权
   （绕开"HA 只对 GET/HEAD 接受 authSig"的限制）；
3. 页面是独立 HTML（不依赖 HA 前端），所以可以在卡片里以 iframe 悬浮窗打开，
   也可以直接在新标签页打开。

除签名链接外，还有一种更短的入口：**面板密钥**（``?key=``）。密钥口径与爱快
集成的 ``sensor.ikuai_api_key`` 一致：

* ``key = md5(集成盐 | 整点序号 | 主机地址 | 条目 id)[:16]``，盐随机生成、只存在
  内存里，所以别人知道主机地址也算不出密钥；
* **整点轮换**，一把密钥只在一个整点周期内有效；
* 旧密钥**再宽限一个周期**（正在使用的人跨整点不会被打断），宽限期过后失效。
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# 独立页面（带 authSig 打开）与页面调用的数据接口
CONSOLE_PATH = "/nps/console"
CONSOLE_API_PATH = "/nps/api/action"

# 本集成自己的会话 Cookie
CONSOLE_COOKIE_NAME = "nps_panel_sess"
CONSOLE_COOKIE_MAX_AGE = 12 * 3600
CONSOLE_SIGN_EXPIRY = timedelta(hours=24)

_SECRET_KEY = f"{DOMAIN}_console_secret"
_URL_CACHE_KEY = f"{DOMAIN}_console_urls"
_URL_CACHE_TTL = 3600  # 签名地址缓存 1 小时，到期重签

try:  # 官方签名工具（老版本可能没有）
    from homeassistant.auth import jwt_wrapper
    from homeassistant.components.http.auth import (
        DATA_SIGN_SECRET,
        SAFE_QUERY_PARAMS,
        SIGN_QUERY_PARAM,
        async_sign_path,
    )
except ImportError:  # pragma: no cover - 兼容老版本
    jwt_wrapper = None
    DATA_SIGN_SECRET = "http.auth.sign_secret"
    SAFE_QUERY_PARAMS = frozenset(("height", "width"))
    SIGN_QUERY_PARAM = "authSig"
    async_sign_path = None


# ----------------------------------------------------------------------
# 基地址
# ----------------------------------------------------------------------
def get_base_url(hass: HomeAssistant) -> str | None:
    """返回 HA 的绝对访问地址（internal_url / external_url / 云端地址）."""
    try:
        base = get_url(hass, allow_cloud=True)
    except NoURLAvailableError:
        _LOGGER.debug(
            "无法确定 Home Assistant 的访问地址（internal_url/external_url 均未配置）"
        )
        return None
    return base.rstrip("/")


def sign_console_url(hass: HomeAssistant, entry_id: str) -> str | None:
    """签发（并缓存）某个配置条目的管理面板地址."""
    cache = hass.data.setdefault(_URL_CACHE_KEY, {})
    now = time.time()
    cached = cache.get(entry_id)
    if cached and cached[0] > now:
        return cached[1]

    if async_sign_path is None:  # pragma: no cover
        _LOGGER.error("当前 Home Assistant 版本不支持签名链接，无法生成面板地址")
        return None

    base = get_base_url(hass)
    if not base:
        return None

    try:
        signed = async_sign_path(
            hass, f"{CONSOLE_PATH}?entry={entry_id}", CONSOLE_SIGN_EXPIRY
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("签发 NPS 管理面板地址失败: %s", err)
        return None

    url = f"{base}{signed}"
    cache[entry_id] = (now + _URL_CACHE_TTL, url)
    return url


def clear_signed_url(hass: HomeAssistant, entry_id: str) -> None:
    """丢弃缓存的签名地址（开关切换 / 卸载时用）."""
    cache = hass.data.get(_URL_CACHE_KEY)
    if isinstance(cache, dict):
        cache.pop(entry_id, None)


# ----------------------------------------------------------------------
# 面板密钥：加盐 + 整点轮换 + 旧密钥宽限一个周期（口径同 ikuai 集成）
# ----------------------------------------------------------------------
API_KEY_TTL = 3600  # 密钥轮换刻度：整点换新，有效期 1 小时
API_KEY_LEN = 16  # 密钥长度（md5 前 16 位）
_KEY_STORE_KEY = f"{DOMAIN}_panel_keys"


def _hour_index(now: float | None = None) -> int:
    """当前整点序号（UTC 整点，作为密钥轮换刻度）."""
    return int((now if now is not None else time.time()) // API_KEY_TTL)


def _key_store(hass: HomeAssistant) -> dict:
    """密钥状态存储：随机盐 + 各条目的当前/上一把密钥（全部只在内存里）."""
    store = hass.data.setdefault(_KEY_STORE_KEY, {})
    if not isinstance(store, dict):
        store = {}
        hass.data[_KEY_STORE_KEY] = store
    store.setdefault("salt", os.urandom(16).hex())
    store.setdefault("keys", {})
    return store


def _key_seed(hass: HomeAssistant, entry_id: str) -> str:
    """密钥的熵源：该配置条目的 NPS 主机地址.

    加盐是为了：别人即使知道你连的是哪台 NPS，也算不出密钥；
    末尾再带 entry_id，多实例时各台的密钥互不相同，拿密钥就能定位到条目。
    """
    entry = hass.config_entries.async_get_entry(entry_id)
    host = (entry.data or {}).get("host") if entry is not None else ""
    return str(host or entry_id)


def _make_key(hass: HomeAssistant, hour: int, seed: str, entry_id: str) -> str:
    """key = md5(集成盐 | 整点序号 | 主机地址 | 条目 id)，取前 API_KEY_LEN 位."""
    salt = _key_store(hass)["salt"]
    raw = f"{salt}|{hour}|{seed}|{entry_id}".encode()
    return hashlib.md5(raw).hexdigest()[:API_KEY_LEN]


def ensure_panel_key(hass: HomeAssistant, entry_id: str) -> dict:
    """保证当前整点有密钥，返回该条目的密钥状态（整点首次访问时自动换新）."""
    keys = _key_store(hass)["keys"]
    state = keys.get(entry_id) or {}
    hour = _hour_index()
    if state.get("hour") != hour:
        state = {
            "hour": hour,
            "key": _make_key(hass, hour, _key_seed(hass, entry_id), entry_id),
            "prev_key": state.get("key"),  # 上一把密钥再宽限一个周期
            "created": time.time(),
        }
        keys[entry_id] = state
    return state


def panel_key_matches(hass: HomeAssistant, entry_id: str, candidate: str | None) -> bool:
    """校验密钥：当前整点的、以及上一整点（宽限期内）的密钥都算有效."""
    candidate = str(candidate or "").strip()
    if not candidate:
        return False
    state = ensure_panel_key(hass, entry_id)
    return candidate in ({state.get("key"), state.get("prev_key")} - {None})


def resolve_entry_by_panel_key(hass: HomeAssistant, candidate: str | None) -> str | None:
    """按密钥反查配置条目（多实例时调用方可以只给 key）."""
    if not candidate:
        return None
    for entry in hass.config_entries.async_entries(DOMAIN):
        if panel_key_matches(hass, entry.entry_id, candidate):
            return entry.entry_id
    return None


def _human_duration(seconds: int) -> str:
    """秒数 → 中文可读时长（最多两级单位）."""
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days} 天 {hours} 小时" if hours else f"{days} 天"
    if hours:
        return f"{hours} 小时 {minutes} 分" if minutes else f"{hours} 小时"
    if minutes:
        return f"{minutes} 分"  # 分钟级不再显示秒
    return f"{secs} 秒"


def panel_key_info(hass: HomeAssistant, entry_id: str) -> dict | None:
    """密钥实体要展示的信息：密钥、剩余时长、可直开的访问地址.

    条目不存在时返回 None；访问地址需要 HA 能确定自己的基地址
    （``internal_url`` / ``external_url``），否则 URL 为 None。
    """
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        return None
    state = ensure_panel_key(hass, entry_id)
    expires_at = (state["hour"] + 1) * API_KEY_TTL
    remaining = max(0, int(expires_at - time.time()))
    base = get_base_url(hass)
    url = (
        f"{base}{CONSOLE_PATH}?entry={entry_id}&key={state['key']}"
        if base
        else None
    )
    return {
        "key": state["key"],
        "prev_key": state.get("prev_key"),
        "url": url,
        "expires_at": datetime.fromtimestamp(expires_at)
        .astimezone()
        .isoformat(timespec="seconds"),
        "expires_ts": expires_at,
        "remaining": remaining,
        # 与 ikuai 一致：不足 1 分钟按 1 分钟显示
        "remaining_minutes": max(1, (remaining + 59) // 60),
        "remaining_text": _human_duration(remaining),
    }


# ----------------------------------------------------------------------
# 会话 Cookie（HMAC 自签，不依赖 HA 登录态）
# ----------------------------------------------------------------------
def _hmac_secret(hass: HomeAssistant) -> bytes:
    secret = hass.data.get(DATA_SIGN_SECRET)
    if isinstance(secret, str):
        return secret.encode()
    if isinstance(secret, bytes):
        return secret
    fallback = hass.data.get(_SECRET_KEY)
    if not isinstance(fallback, bytes):
        fallback = os.urandom(32)
        hass.data[_SECRET_KEY] = fallback
    return fallback


def issue_cookie(hass: HomeAssistant, entry_id: str) -> str:
    """生成会话票据：entry_id.签发时间.HMAC."""
    issued = str(int(time.time()))
    signature = hmac.new(
        _hmac_secret(hass), f"{entry_id}.{issued}".encode(), hashlib.sha256
    ).hexdigest()
    return f"{entry_id}.{issued}.{signature}"


def verify_cookie(hass: HomeAssistant, value: str | None) -> str | None:
    """校验会话票据，返回 entry_id；无效返回 None."""
    if not value or value.count(".") != 2:
        return None
    entry_id, issued, signature = value.split(".")
    expected = hmac.new(
        _hmac_secret(hass), f"{entry_id}.{issued}".encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        if time.time() - int(issued) > CONSOLE_COOKIE_MAX_AGE:
            return None
    except ValueError:
        return None
    return entry_id


def cookie_header(hass: HomeAssistant, entry_id: str, secure: bool = False) -> str:
    """构造 Set-Cookie 头（Path 限定在 /nps/ 下）."""
    tail = "; Secure" if secure else ""
    return (
        f"{CONSOLE_COOKIE_NAME}={issue_cookie(hass, entry_id)}; "
        f"Path=/nps/; Max-Age={CONSOLE_COOKIE_MAX_AGE}; HttpOnly; SameSite=Lax{tail}"
    )


# ----------------------------------------------------------------------
# authSig 校验（GET/HEAD 用，规则与 HA 中间件一致）
# ----------------------------------------------------------------------
async def verify_signature(hass: HomeAssistant, request) -> bool:
    """校验请求里的 authSig：签名有效、路径/参数一致、refresh token 仍存在."""
    if async_sign_path is None or jwt_wrapper is None:  # pragma: no cover
        return False
    secret = hass.data.get(DATA_SIGN_SECRET)
    signature = request.query.get(SIGN_QUERY_PARAM)
    if not secret or not signature:
        return False
    try:
        claims = jwt_wrapper.verify_and_decode(
            signature, secret, algorithms=["HS256"], options={"verify_iss": False}
        )
    except Exception:  # noqa: BLE001 - 签名无效/过期
        return False
    if claims.get("path") != request.path:
        return False
    params = [
        [item[0], item[1]]
        for item in request.query.items()
        if item[0] not in SAFE_QUERY_PARAMS and item[0] != SIGN_QUERY_PARAM
    ]
    if claims.get("params") != params:
        return False
    if hass.auth.async_get_refresh_token(claims.get("iss")) is None:
        return False
    return True
