"""NPS 数据协调器 - 定期轮询隧道状态和仪表盘数据."""
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import NpsApiClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# 轮询间隔：30 秒
UPDATE_INTERVAL = timedelta(seconds=30)


class NpsDataUpdateCoordinator(DataUpdateCoordinator):
    """管理 NPS 数据更新的协调器.

    同时维护隧道列表和仪表盘数据：
    - self.data: 隧道列表（供 switch 实体使用）
    - self.dashboard_data: 仪表盘数据（供 sensor 实体使用）
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api_client: NpsApiClient,
    ) -> None:
        """初始化协调器.

        Args:
            hass: Home Assistant 实例
            api_client: NPS API 客户端实例
        """
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.api = api_client
        # 仪表盘数据（传感器用）
        self.dashboard_data: dict = {}
        # 客户端列表（客户端开关用）
        self.clients_data: list = []
        # Host 列表（域名映射，供未来 Host 实体使用）
        self.hosts_data: list = []
        # 服务器时间（用于检测时钟偏差）
        self.server_time: int = 0

    async def _async_update_data(self) -> list:
        """获取最新的隧道列表和客户端数据.

        Returns:
            隧道列表（每项包含 Id, Remark, RunStatus, Port, Mode 等）

        同时将聚合的仪表盘数据存入 self.dashboard_data 供传感器使用。
        数据来源：
        - 隧道列表 (/index/gettunnel 按类型查询)
        - 客户端列表 (/client/list)
        """
        _LOGGER.debug("开始更新 NPS 数据...")
        try:
            # 核心请求：隧道列表 + 客户端列表（必须成功）
            tunnels = await self.hass.async_add_executor_job(self.api.get_tunnels)
            clients = await self.hass.async_add_executor_job(self.api.get_clients)

            # 可选请求：Host 列表（部分版本不支持，失败不阻塞）
            hosts = []
            try:
                hosts = await self.hass.async_add_executor_job(
                    self.api.get_host_list
                )
            except Exception as err:
                _LOGGER.debug(
                    "获取 Host 列表失败（该接口可能在此 NPS 版本中不可用）: %s",
                    err,
                )

            # 可选请求：服务器时间（失败不阻塞）
            try:
                time_data = await self.hass.async_add_executor_job(
                    self.api.get_server_time
                )
                self.server_time = (
                    time_data.get("time", 0)
                    if isinstance(time_data, dict)
                    else 0
                )
            except Exception:
                self.server_time = 0

            # 从原始数据聚合出仪表盘统计信息
            self.dashboard_data = self._build_dashboard(tunnels, clients, hosts)
            # 保存客户端原始数据供客户端开关使用
            self.clients_data = clients if isinstance(clients, list) else []
            # 保存 Host 数据供未来 Host 实体使用
            self.hosts_data = hosts if isinstance(hosts, list) else []

            _LOGGER.info(
                "NPS 更新完成: %d 条隧道, %d 个客户端, %d 个Host",
                len(tunnels),
                len(clients) if isinstance(clients, list) else 0,
                len(hosts) if isinstance(hosts, list) else 0,
            )
            return tunnels
        except Exception as err:
            _LOGGER.error("更新 NPS 数据失败: %s", err)
            raise

    @staticmethod
    def _build_dashboard(tunnels: list, clients: list, hosts: list | None = None) -> dict:
        """从隧道、客户端和 Host 数据聚合出仪表盘统计数据.

        Args:
            tunnels: 隧道列表
            clients: 客户端列表
            hosts: Host（域名映射）列表

        Returns:
            聚合后的仪表盘字典，供 sensor 实体读取
        """
        # 客户端统计
        total_clients = len(clients) if isinstance(clients, list) else 0
        online_clients = 0
        total_inlet_flow = 0
        total_export_flow = 0
        total_conn = 0
        # 新增：实时速率汇总 + 桥接信息
        total_now_rate = 0
        bridge_types = set()
        server_ips = set()

        if isinstance(clients, list):
            for c in clients:
                if isinstance(c, dict):
                    if c.get("IsConnect"):
                        online_clients += 1
                    # 累加流量
                    flow = c.get("Flow")
                    if isinstance(flow, dict):
                        total_inlet_flow += flow.get("InletFlow", 0) or 0
                        total_export_flow += flow.get("ExportFlow", 0) or 0
                    total_conn += c.get("NowConn", 0) or 0
                    # 实时速率 (Rate.NowRate)
                    rate = c.get("Rate")
                    if isinstance(rate, dict):
                        total_now_rate += rate.get("NowRate", 0) or 0
                    # 桥接协议
                    bt = c.get("bridgeType")
                    if bt:
                        bridge_types.add(bt)
                    # 服务端 IP（NPS 公网 IP）
                    ip = c.get("ip") or c.get("Ip")
                    if ip:
                        server_ips.add(ip)

        # 按类型统计隧道数量
        type_counts = {}
        if isinstance(tunnels, list):
            for t in tunnels:
                if isinstance(t, dict):
                    mode = t.get("Mode", "unknown")
                    type_counts[mode] = type_counts.get(mode, 0) + 1

        dashboard = {
            "clientCount": total_clients,
            "clientOnlineCount": online_clients,
            "inletFlowCount": total_inlet_flow,
            "exportFlowCount": total_export_flow,
            "totalConnections": total_conn,
            # 各类型隧道计数
            "tcpC": type_counts.get("tcp", 0),
            "udpCount": type_counts.get("udp", 0),
            "socks5Count": type_counts.get("socks5", 0),
            "httpProxyCount": type_counts.get("httpProxy", 0),
            "secretCount": type_counts.get("secret", 0),
            "p2pCount": type_counts.get("p2p", 0),
            "fileCount": type_counts.get("file", 0),
            "tunnelTotal": len(tunnels) if isinstance(tunnels, list) else 0,
            # Host 映射计数
            "hostCount": len(hosts) if isinstance(hosts, list) else 0,
            # 从客户端数据聚合的新指标
            "nowRateBps": total_now_rate,
            "serverIps": ",".join(sorted(server_ips)),
            "bridgeTypes": ",".join(sorted(bridge_types)),
        }

        return dashboard
