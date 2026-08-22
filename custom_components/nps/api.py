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

    def _post(self, endpoint: str, **extra_params) -> dict:
        """发送 POST 请求到 NPS API.

        Args:
            endpoint: API 路径（如 /index/gettunnel）
            **extra_params: 额外的 POST 参数

        Returns:
            API 返回的 JSON 数据

        Raises:
            HomeAssistantError: API 返回业务错误时
            ConnectionError: 网络连接失败时
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

        # 检测 302 重定向 = 鉴权签名验证失败
        if response.status_code == 302:
            location = response.headers.get("Location", "")
            _LOGGER.error(
                "NPS 返回 302 重定向 [%s] → %s，说明 auth_key 鉴权签名不正确",
                endpoint,
                location,
            )
            raise HomeAssistantError(
                "NPS API 鉴权失败（auth_key 不正确）。"
                "请确认填入的是 nps.conf 中 auth_key 的原始值，"
                "而非 Web 登录密码。"
            )

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
                    "/index/gettunnel",
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
            "/client/list",
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
            "/index/hostlist/",
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
        return self._post("/auth/get_time")

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
        result = self._post("/client/change_status", id=client_id, status=str(enable).lower())
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
        return self._post("/index/start", id=tunnel_id)

    def stop_tunnel(self, tunnel_id: int) -> dict:
        """停止指定隧道.

        Args:
            tunnel_id: 隧道 ID

        Returns:
            API 返回结果 {"status": 1, "msg": "ok"}
        """
        _LOGGER.info("正在停止隧道 [ID=%d]", tunnel_id)
        return self._post("/index/stop", id=tunnel_id)

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
