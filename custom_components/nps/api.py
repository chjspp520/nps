"""NPS API 客户端 - 封装鉴权和请求逻辑."""
import hashlib
import time
import logging

import requests

from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)

# NPS 支持的所有隧道类型（来自 server.go NewMode 和 GetDashboardData）
TUNNEL_TYPES = [
    "tcp",
    "udp",
    "socks5",
    "httpProxy",
    "secret",
    "p2p",
    "file",
]

# 请求超时设置（秒）
REQUEST_TIMEOUT = 15

# 各接口的候选路径：不同 NPS 版本/分支的尾部斜杠不一致，
# 按顺序尝试，遇到 404/405 或非登录重定向就换下一个。
ROUTES = {
    "tunnel_list": ("/index/gettunnel", "/index/gettunnel/"),
    "tunnel_get": ("/index/getonetunnel/", "/index/getonetunnel"),
    "tunnel_add": ("/index/add/", "/index/add"),
    "tunnel_edit": ("/index/edit/", "/index/edit"),
    "tunnel_del": ("/index/del/", "/index/del"),
    "tunnel_copy": ("/index/copy/", "/index/copy"),
    "tunnel_start": ("/index/start", "/index/start/"),
    "tunnel_stop": ("/index/stop", "/index/stop/"),
    "host_list": ("/index/hostlist/", "/index/hostlist"),
    "host_add": ("/index/addhost/", "/index/addhost"),
    "host_edit": ("/index/edithost/", "/index/edithost"),
    "host_del": ("/index/delhost/", "/index/delhost"),
    "host_start": ("/index/hoststart/", "/index/hoststart"),
    "host_stop": ("/index/hoststop/", "/index/hoststop"),
    "client_list": ("/client/list", "/client/list/"),
    "client_add": ("/client/add/", "/client/add"),
    "client_edit": ("/client/edit/", "/client/edit"),
    "client_del": ("/client/del/", "/client/del"),
    "client_status": (
        "/client/change_status",
        "/client/changestatus/",
        "/client/change_status/",
        "/client/changestatus",
    ),
    "server_time": ("/auth/get_time", "/auth/get_time/"),
}


class _RouteMismatch(Exception):
    """内部使用：该路径形式不存在（用于切换到候选路径）."""


class NpsApiClient:
    """NPS 官方 API 客户端.

    使用动态签名鉴权（非 Session 模式），
    签名公式：sign = md5(auth_key + timestamp)
    """

    def __init__(self, host: str, auth_key: str) -> None:
        """初始化 API 客户端.

        Args:
            host: NPS 服务器地址，格式 ip:port
            auth_key: nps.conf 中配置的原始密钥（不是 web 登录密码）
        """
        self._base_url = f"http://{host}"
        self._auth_key = auth_key
        self._session = requests.Session()

    def _get_auth_params(self) -> dict:
        """生成签名鉴权参数.

        Returns:
            包含 auth_key (签名) 和 timestamp 的字典
        """
        timestamp = str(int(time.time()))
        # NPS 签名公式：md5(key + timestamp)，输出32位小写十六进制
        sign = hashlib.md5(
            (self._auth_key + timestamp).encode("utf-8")
        ).hexdigest()
        return {
            "auth_key": sign,
            "timestamp": timestamp,
        }

    def _post(
        self,
        endpoints: str | tuple[str, ...] | list[str],
        **extra_params,
    ) -> dict:
        """按候选路径顺序请求 API，返回第一个成功的 JSON 结果.

        Args:
            endpoints: 单个路径或候选路径列表（兼容尾部斜杠差异）
            **extra_params: 额外的 POST 参数

        Returns:
            API 返回的 JSON 数据
        """
        candidates = (
            (endpoints,) if isinstance(endpoints, str) else tuple(endpoints)
        )
        last_error: Exception | None = None
        for endpoint in candidates:
            try:
                return self._post_once(endpoint, **extra_params)
            except _RouteMismatch as err:
                last_error = err
                continue
        raise ConnectionError(
            f"未找到可用的 NPS 接口（已尝试 {list(candidates)}）: {last_error}"
        )

    def _post_once(self, endpoint: str, **extra_params) -> dict:
        """向单个路径发送 POST 请求.

        Args:
            endpoint: API 路径（如 /index/gettunnel）
            **extra_params: 额外的 POST 参数

        Returns:
            API 返回的 JSON 数据

        Raises:
            HomeAssistantError: API 返回业务错误时
            ConnectionError: 网络连接失败时
            _RouteMismatch: 该路径不存在时（内部使用）
        """
        url = f"{self._base_url}{endpoint}"
        payload = {**self._get_auth_params(), **extra_params}

        _LOGGER.debug("NPS API 请求: %s, 参数: %s", url, list(payload.keys()))

        try:
            # 关键：禁止跟随重定向！
            # NPS 源码 base.go: 鉴权失败时返回 302 重定向到 /login/index
            # 如果允许重定向，requests 会拿到登录页 HTML 而非 API 响应
            response = self._session.post(
                url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
            )
        except requests.exceptions.RequestException as err:
            _LOGGER.error("NPS API 请求失败 [%s]: %s", endpoint, err)
            raise ConnectionError(f"无法连接 NPS 服务器: {err}") from err

        # 重定向：到登录页 = 鉴权失败；其他 = 路由形式不匹配（如缺/多尾部斜杠）
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location", "")
            if "login" in location.lower():
                _LOGGER.error(
                    "NPS 返回重定向 [%s] → %s，说明 auth_key 鉴权签名不正确",
                    endpoint,
                    location,
                )
                raise HomeAssistantError(
                    "NPS API 鉴权失败（auth_key 不正确）。"
                    "请确认填入的是 nps.conf 中 auth_key 的原始值，"
                    "而非 Web 登录密码。"
                )
            raise _RouteMismatch(
                f"{endpoint} → HTTP {response.status_code} {location}"
            )

        # 路径不存在：交给候选路径重试
        if response.status_code in (404, 405):
            raise _RouteMismatch(f"{endpoint} → HTTP {response.status_code}")

        response.raise_for_status()

        # 尝试解析 JSON 响应
        try:
            data = response.json()
        except ValueError as err:
            text_preview = response.text[:200].replace("\n", " ").strip()
            _LOGGER.error(
                "NPS 返回内容无法解析为 JSON [%s], HTTP %s, Content-Type: %s, 内容预览: %s",
                endpoint,
                response.status_code,
                response.headers.get("Content-Type", ""),
                text_preview,
            )
            raise ConnectionError(
                f"NPS 服务器返回了非预期数据 (HTTP {response.status_code}): {text_preview}"
            ) from err

        # 检查业务状态码：status=0 表示错误（签名错误或 ID 不存在）
        if isinstance(data, dict) and data.get("status") == 0:
            msg = data.get("msg", "未知错误")
            _LOGGER.error("NPS API 业务错误 [%s]: %s", endpoint, msg)
            raise HomeAssistantError(f"NPS API 错误: {msg}")

        return data

    def get_tunnels(self, offset: int = 0, limit: int = 100) -> list:
        """获取隧道列表.

        NPS 源码 server.go GetTunnel 的过滤逻辑：
          当 type="" 且 clientId=0 时，会跳过所有 Client.Id != 0 的隧道
        
        因此需要按每种 tunnel type 分别查询，再合并去重。

        Returns:
            隧道列表，每个元素包含 Id, Remark, RunStatus, Port, Mode,
            Target.TargetStr(目标地址), Client.Addr(IP), Client.IsConnect 等
        """
        all_tunnels = []
        seen_ids = set()

        for tunnel_type in TUNNEL_TYPES:
            try:
                data = self._post(
                    ROUTES["tunnel_list"],
                    offset=offset,
                    limit=limit,
                    type=tunnel_type,
                )
                rows = data.get("rows", [])
                _LOGGER.debug(
                    "gettunnel [type=%s] 返回 %d 条记录",
                    tunnel_type,
                    len(rows),
                )
                for t in rows:
                    tid = t.get("Id")
                    if tid is not None and tid not in seen_ids:
                        seen_ids.add(tid)
                        all_tunnels.append(t)
            except Exception as err:
                _LOGGER.warning(
                    "获取类型 [%s] 的隧道失败，跳过: %s",
                    tunnel_type,
                    err,
                )

        _LOGGER.info("共获取到 %d 条唯一隧道记录", len(all_tunnels))
        return all_tunnels

    def get_clients(self, offset: int = 0, limit: int = 100) -> list:
        """获取客户端列表.

        Returns:
            客户端列表，每个元素包含 Id, VerifyKey(vkey), Addr(IP),
            Remark, IsConnect(在线), Version, NowConn(连接数), Flow 等
        """
        data = self._post(
            ROUTES["client_list"],
            offset=offset,
            limit=limit,
        )
        rows = data.get("rows", [])
        _LOGGER.info("获取到 %d 条客户端记录", len(rows))
        return rows

    def get_host_list(self, offset: int = 0, limit: int = 100) -> list:
        """获取 Host（域名映射）列表.

        对应官方文档：POST /index/hostlist/
        Host 用于 HTTP(S) 域名反向代理配置。

        Returns:
            Host 列表，每项包含 Id, Host(域名), Target,
            Remark, Client.Id, Status, Location 等
        """
        data = self._post(
            ROUTES["host_list"],
            offset=offset,
            limit=limit,
        )
        rows = data.get("rows", [])
        _LOGGER.info("获取到 %d 条 Host 映射记录", len(rows))
        return rows

    def get_server_time(self) -> dict:
        """获取服务器当前时间（验证连通性和检测时钟偏差）.

        对应 NPS 源码 AuthController.GetTime()：POST /auth/get_time

        Returns:
            {"time": unix_timestamp}
        """
        return self._post(ROUTES["server_time"])

    def change_client_status(self, client_id: int, enable: bool) -> dict:
        """开启或关闭客户端连接.

        对应 NPS 源码 ClientController.ChangeStatus()：
          POST /client/change_status, 参数 id + status(bool)
        
        Args:
            client_id: 客户端 ID
            enable: True=允许连接/启用, False=断开连接/禁用

        Returns:
            API 返回结果 {"status": 1, "msg": "modified success"}
        """
        action = "启用" if enable else "禁用"
        _LOGGER.info("正在%s客户端 [ID=%d]", action, client_id)
        result = self._post(
            ROUTES["client_status"], id=client_id, status=str(enable).lower()
        )
        _LOGGER.info("客户端 [ID=%d] 已%s", client_id, action)
        return result

    def start_tunnel(self, tunnel_id: int) -> dict:
        """开启指定隧道.

        Args:
            tunnel_id: 隧道 ID

        Returns:
            API 返回结果 {"status": 1, "msg": "ok"}
        """
        _LOGGER.info("正在开启隧道 [ID=%d]", tunnel_id)
        return self._post(ROUTES["tunnel_start"], id=tunnel_id)

    def stop_tunnel(self, tunnel_id: int) -> dict:
        """停止指定隧道.

        Args:
            tunnel_id: 隧道 ID

        Returns:
            API 返回结果 {"status": 1, "msg": "ok"}
        """
        _LOGGER.info("正在停止隧道 [ID=%d]", tunnel_id)
        return self._post(ROUTES["tunnel_stop"], id=tunnel_id)

    # ------------------------------------------------------------------
    # 隧道的增删改查（管理面板使用）
    # ------------------------------------------------------------------

    def get_tunnel(self, tunnel_id: int) -> dict:
        """获取单条隧道详情（返回 data 字段）."""
        data = self._post(ROUTES["tunnel_get"], id=tunnel_id)
        return data.get("data") or {}

    def add_tunnel(self, **params) -> dict:
        """新增隧道.

        参数见 NPS Web API 文档 /index/add/：
        client_id, type, remark, port, server_ip, target,
        local_proxy, password, local_path, strip_pre, proto_version
        """
        _LOGGER.info("新增隧道: %s", params)
        return self._post(ROUTES["tunnel_add"], **params)

    def edit_tunnel(self, **params) -> dict:
        """修改隧道（params 中必须含 id）."""
        _LOGGER.info("修改隧道: %s", params)
        return self._post(ROUTES["tunnel_edit"], **params)

    def del_tunnel(self, tunnel_id: int) -> dict:
        """删除隧道."""
        _LOGGER.info("删除隧道 [ID=%d]", tunnel_id)
        return self._post(ROUTES["tunnel_del"], id=tunnel_id)

    def copy_tunnel(self, tunnel_id: int) -> dict:
        """复制隧道（服务端自动分配新端口和 ID）."""
        _LOGGER.info("复制隧道 [ID=%d]", tunnel_id)
        return self._post(ROUTES["tunnel_copy"], id=tunnel_id)

    # ------------------------------------------------------------------
    # 域名映射（Host）的增删改查
    # ------------------------------------------------------------------

    def add_host(self, **params) -> dict:
        """新增域名映射."""
        _LOGGER.info("新增域名映射: %s", params)
        return self._post(ROUTES["host_add"], **params)

    def edit_host(self, **params) -> dict:
        """修改域名映射（params 中必须含 id）."""
        _LOGGER.info("修改域名映射: %s", params)
        return self._post(ROUTES["host_edit"], **params)

    def del_host(self, host_id: int) -> dict:
        """删除域名映射."""
        _LOGGER.info("删除域名映射 [ID=%d]", host_id)
        return self._post(ROUTES["host_del"], id=host_id)

    def start_host(self, host_id: int) -> dict:
        """启用域名映射."""
        return self._post(ROUTES["host_start"], id=host_id)

    def stop_host(self, host_id: int) -> dict:
        """停用域名映射."""
        return self._post(ROUTES["host_stop"], id=host_id)

    # ------------------------------------------------------------------
    # 客户端（NPC）的增删改
    # ------------------------------------------------------------------

    def add_client(self, **params) -> dict:
        """新增客户端."""
        _LOGGER.info("新增客户端: %s", params)
        return self._post(ROUTES["client_add"], **params)

    def edit_client(self, **params) -> dict:
        """修改客户端（params 中必须含 id）."""
        _LOGGER.info("修改客户端: %s", params)
        return self._post(ROUTES["client_edit"], **params)

    def del_client(self, client_id: int) -> dict:
        """删除客户端."""
        _LOGGER.info("删除客户端 [ID=%d]", client_id)
        return self._post(ROUTES["client_del"], id=client_id)

    def test_connection(self) -> bool:
        """测试 API 连接和鉴权是否正常.

        Returns:
            True 表示连接成功
        """
        try:
            self.get_tunnels(limit=1)
            return True
        except (ConnectionError, HomeAssistantError):
            return False
