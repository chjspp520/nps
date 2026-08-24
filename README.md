# NPS 隧道管理集成 - 项目说明文档

> 适用版本：`0.1.0`  
> 适用 Home Assistant：支持 Config Flow 的版本  
> 仓库路径：`y:\custom_components\nps\`  
> 依赖：`requests`（唯一第三方依赖）

---

## 一、项目概述

### 1.1 集成名称与定位

- **集成名称**：NPS 隧道管理（Home Assistant 集成域 `nps`）
- **对接对象**：[ehang-io/nps](https://github.com/ehang-io/nps) —— 一款轻量级、高性能、功能强大的内网穿透代理服务器。
- **集成目标**：在 Home Assistant 中可视化 NPS 服务端的所有运行数据，并允许通过开关（switch）实体远程控制隧道（tunnel）和 NPC 客户端的启停。

### 1.2 功能特性

| 能力 | 说明 |
|---|---|
| 仪表盘统计 | 客户端总数 / 在线数、连接数、各类隧道数量、流量、实时速率等 |
| 隧道控制 | 每一个 NPS 隧道生成一个 switch 实体，支持开启/停止 |
| 客户端控制 | 每一个 NPC 客户端生成一个 switch 实体，支持启用/禁用（断开/恢复连接） |
| Host 映射统计 | 读取并展示 HTTP(S) 域名反向代理数量（部分旧版 NPS 无此接口，已做容错） |
| 时钟检测 | 读取 NPS 服务端时间，可用于诊断本机与服务器时钟偏差（>20s 会导致签名失败） |
| 多实例 | 通过 `unique_id = nps_{host}` 支持配置多个 NPS 服务端 |

### 1.3 文件结构

```text
y:\custom_components\nps\
├── __init__.py          # 集成入口：注册平台、加载/卸载配置入口
├── api.py               # NpsApiClient：封装 HTTP 请求 + MD5 签名鉴权
├── config_flow.py       # UI 配置流（仅一个用户输入步骤）
├── const.py             # 全局常量 DOMAIN = "nps"
├── coordinator.py       # NpsDataUpdateCoordinator：30s 周期轮询，聚合仪表盘数据
├── sensor.py            # 16 个 sensor 实体：仪表盘统计
├── switch.py            # NpsTunnelSwitch + NpsClientSwitch 实体
├── manifest.json        # HA 集成元数据
├── strings.json         # 默认（英文）UI 文案
├── translations/
│   └── zh-Hans.json     # 简体中文 UI 文案
└── brand/
    └── icon.png         # 集成图标
```

---

## 二、架构与数据流

### 2.1 模块职责

| 文件 | 职责 |
|---|---|
| `__init__.py` | 注册 `[SWITCH, SENSOR]` 两个平台；创建 `NpsApiClient` 和 `NpsDataUpdateCoordinator` 实例并存入 `hass.data[DOMAIN][entry_id]`；启动时 `async_config_entry_first_refresh` 验证连通性 |
| `config_flow.py` | 接收用户在 UI 输入的 `host`（`ip:port`）和 `auth_key`；调用 `api_client.test_connection()` 验证；通过 `async_set_unique_id(f"nps_{host}")` 实现多实例去重 |
| `api.py` | 唯一的网络层。`NpsApiClient` 用 MD5 签名 + POST 形式调用 NPS 官方 API；**禁止 302 重定向**（防止被重定向到登录页拿到 HTML 响应） |
| `coordinator.py` | HA 标准 `DataUpdateCoordinator`，每 30 秒拉取一次；聚合 `tunnels / clients / hosts` 为 `dashboard_data` 字典 |
| `sensor.py` | 根据 `DASHBOARD_SENSORS` 元组表批量创建 16 个 sensor 实体 |
| `switch.py` | 在 `async_setup_entry` 时遍历 `coordinator.data` 创建隧道开关、遍历 `coordinator.clients_data` 创建客户端开关；为每个实体注册 coordinator 监听器 |

### 2.2 数据流图

```text
┌─────────────────────┐
│  NPS Server (nps)   │
│  HTTP API           │
└──────────┬──────────┘
           │ POST + form-data
           │ 鉴权: md5(auth_key + timestamp)
           ▼
┌─────────────────────┐
│   NpsApiClient      │  api.py
│  - get_tunnels      │  (同步, requests.Session)
│  - get_clients      │
│  - get_host_list    │
│  - start/stop/...   │
└──────────┬──────────┘
           │ 包装为 async_add_executor_job
           ▼
┌─────────────────────────────┐
│  NpsDataUpdateCoordinator   │  coordinator.py
│  - _async_update_data()     │  30s 周期
│  - data: 隧道列表           │
│  - dashboard_data: 聚合统计 │
│  - clients_data: 客户端     │
│  - hosts_data: Host 映射    │
└──────────┬──────────────────┘
           │ listener 通知
   ┌───────┴────────┐
   ▼                ▼
┌──────────┐   ┌──────────┐
│ sensors  │   │ switches │
│ 16 个    │   │ N 隧道   │
│ 仪表盘   │   │ + M 客户 │
└──────────┘   └────┬─────┘
                    │ 用户操作 switch
                    ▼
              api.start_tunnel / stop_tunnel
              api.change_client_status
                    │ 睡眠 REFRESH_DELAY=3s
                    ▼
              coordinator.async_request_refresh()
```

### 2.3 NPS API 关键约束（与源码对齐）

| 约束 | 说明 |
|---|---|
| 签名算法 | `sign = md5(auth_key + timestamp).hexdigest()`，32 位小写 |
| 鉴权失败 | NPS 返回 `302 → /login/index`；必须 `allow_redirects=False`，否则会拿到 HTML 登录页 |
| 业务错误 | 响应 JSON `status == 0` 表示失败；`msg` 字段说明原因 |
| 隧道类型 | 支持 `tcp / udp / socks5 / httpProxy / secret / p2p / file` 共 7 种 |
| 获取隧道 | `/index/gettunnel` 必须按 `type` 逐个查询再合并去重（type="" 且 clientId=0 时会过滤掉所有真实隧道） |
| 隧道启停 | `/index/start` 与 `/index/stop`，参数 `id` |
| 客户端启停 | `/client/change_status`，参数 `id` + `status`（字符串 `"true"` / `"false"`） |
| 服务器时间 | `/auth/get_time`（鉴权控制器中），用于诊断时钟漂移 |

---

## 三、安装与配置

### 3.1 前置条件

1. 已部署 [NPS 服务端](https://github.com/ehang-io/nps)，并能在浏览器访问 Web 控制台。
2. NPS 服务端的时间与 Home Assistant 主机时间偏差应 **≤ 20 秒**（超出后 MD5 签名会被服务端拒绝）。
3. 已知 NPS 服务端的 `ip:port` 和 `nps.conf` 中的 `auth_key`（**不是 Web 登录用户名/密码**）。

### 3.2 安装方式

将整个 `nps` 目录复制到 HA 配置目录的 `custom_components/nps/` 即可。重启 Home Assistant。

### 3.3 UI 配置

**设置 → 设备与服务 → 集成 → "+" 添加集成 → 搜索 "NPS 隧道管理"**

| 字段 | 示例 | 说明 |
|---|---|---|
| NPS 服务器地址（ip:port） | `192.168.1.100:8080` | 必填，需含冒号 |
| API 认证密钥（nps.conf 中的 auth_key） | `your_auth_key_here` | 必填，**原始值**，不是 Web 登录密码 |

提交后集成会立刻调用 `test_connection()` 拉取一条隧道进行验证：

- ✅ 成功 → 创建配置入口，跳转到设备详情页。
- ❌ 失败 → 提示 `connection_error`：
  1. 服务器地址和端口是否正确且可访问
  2. auth_key 是否为 nps.conf 中的原始值
  3. NPS 服务端时间与本地时间偏差是否超过 20 秒

### 3.4 多实例

每个 NPS 服务端用 `host` 作为唯一标识（`unique_id = nps_{host}`），可重复添加多个不同 `host` 的实例。

### 3.5 选项（Options）

当前 `NpsOptionsFlowHandler` 仅返回 `not_supported`，**没有可配置选项**。如需修改服务器或密钥，请删除原集成后重新添加。

---

## 四、实体清单

所有实体归属于同一台虚拟设备 `NPS Server ({host})`，便于在 HA 设备页中统一查看。

### 4.1 Sensor 实体（16 个）

> `entry_id` 占位为 `XXXX`；以下 `unique_id` 格式：`{entry_id}_nps_{key}`

| Key | 名称 | 单位 | 图标 | StateClass | Divisor |
|---|---|---|---|---|---|
| `clientCount` | Client Total | — | `mdi:account-group` | TOTAL | 1 |
| `clientOnlineCount` | Clients Online | — | `mdi:account-check` | TOTAL | 1 |
| `totalConnections` | Total Connections | — | `mdi:connection` | MEASUREMENT | 1 |
| `inletFlowCount` | Inlet Traffic | GB | `mdi:download-network-outline` | TOTAL_INCREASING | 1/1024³ |
| `exportFlowCount` | Export Traffic | GB | `mdi:upload-network-outline` | TOTAL_INCREASING | 1/1024³ |
| `tunnelTotal` | Tunnel Total | — | `mdi:tunnel-variant` | TOTAL | 1 |
| `tcpC` | TCP Tunnels | — | `mdi:tunnel` | TOTAL | 1 |
| `udpCount` | UDP Tunnels | — | `mdi:tunnel` | TOTAL | 1 |
| `socks5Count` | SOCKS5 Tunnels | — | `mdi:tunnel` | TOTAL | 1 |
| `httpProxyCount` | HTTP Proxy Tunnels | — | `mdi:tunnel` | TOTAL | 1 |
| `secretCount` | Secret Tunnels | — | `mdi:tunnel-lock` | TOTAL | 1 |
| `p2pCount` | P2P Tunnels | — | `mdi:tunnel` | TOTAL | 1 |
| `fileCount` | File Tunnels | — | `mdi:file-document-outline` | TOTAL | 1 |
| `hostCount` | Host Mappings | — | `mdi:dns-outline` | TOTAL | 1 |
| `nowRateBps` | Realtime Rate | KB/s | `mdi:speedometer` | MEASUREMENT | 1/1024 |
| `serverIps` | Server IPs | — | `mdi:server-network` | — | 1（字符串原样返回） |
| `bridgeTypes` | Bridge Protocols | — | `mdi:swap-horizontal` | — | 1（字符串原样返回） |

> 备注：表格中 `serverIps` 和 `bridgeTypes` 是字符串（逗号连接的多值），不会被 `divisor` 缩放，代码里 `if isinstance(raw_val, (str, bool)): return raw_val` 已做特判。

#### Sensor 设备类

所有 sensor 归属到设备 `NPS Server ({host})`（manufacturer=NPS, model=Tunnel Server），identifier = `(DOMAIN, f"{entry_id}_nps_server")`。

### 4.2 Switch 实体（动态数量）

#### 4.2.1 `NpsTunnelSwitch` —— 隧道开关

- **唯一 ID**：`{entry_id}_nps_tunnel_{tunnel_id}`
- **命名规则**：
  - 有备注时：`{client_id}_{remark}_{MODE_LABEL}_{target_first_line}`
  - 无备注时：`{client_id}_Tunnel{tunnel_id}_{MODE_LABEL}_{target_first_line}`
- **图标**：`mdi:lan-connect`（开） / `mdi:lan-disconnect`（关）
- **动作**：
  - 开启 → `POST /index/start id={tunnel_id}` → 等 3 秒 → 请求刷新
  - 关闭 → `POST /index/stop id={tunnel_id}` → 等 3 秒 → 请求刷新
- **extra_state_attributes**：

  | 字段 | 来源 | 备注 |
  |---|---|---|
  | `tunnel_id` | `Id` | 隧道 ID |
  | `port` | `Port` | 监听端口 |
  | `mode` | `Mode` | 原始枚举值 |
  | `target` | `Target.TargetStr` 第一行 | 目标地址 |
  | `status_enabled` | `Status` | 数据库启用标志 |
  | `server_ip` | `ServerIp` | 服务端 IP |
  | `ports` | `Ports` | 多端口 |
  | `target_addr` | `TargetAddr` | 顶层目标 |
  | `strip_pre` | `StripPre` | HTTP 前缀剥离 |
  | `inlet_flow` | `Flow.InletFlow` | 格式化（B/KB/MB/GB/TB） |
  | `export_flow` | `Flow.ExportFlow` | 格式化 |
  | `flow_limit` | `Flow.FlowLimit` | 格式化（>0 才输出） |
  | `password` | `Password` | **脱敏**（前 2 + 中间 8 个 \* + 后 2） |
  | `health_check_interval_s` | `HealthCheckInterval` | 顶层健康检查周期 |
  | `health_max_fail` | `HealthMaxFail` | 最大失败次数 |
  | `health_check_timeout_s` | `HealthCheckTimeout` | 健康检查超时 |
  | `client_id` | `Client.Id` | 所属 NPC ID |
  | `client_ip` | `Client.Addr` | 客户端 IP |
  | `client_online` | `Client.IsConnect` | 客户端在线状态 |
  | `server` | `api._base_url` | 当前 NPS 服务端地址 |

#### 4.2.2 `NpsClientSwitch` —— NPC 客户端开关

- **唯一 ID**：`{entry_id}_nps_client_{client_id}`
- **命名规则**：
  - 有备注时：`{client_id}_{remark}_{verify_key}`
  - 无备注时：`{client_id}_NPC_{verify_key or 'unknown'}`
- **图标**：`mdi:ethernet`（在线） / `mdi:ethernet-off`（离线）
- **动作**：
  - 开启（启用连接）→ `POST /client/change_status id={client_id} status=true` → 等 3 秒 → 刷新
  - 关闭（禁用连接 = 断开）→ `POST /client/change_status id={client_id} status=false` → 等 3 秒 → 刷新
- **过滤**：若客户端 `NoDisplay == True`，**不会**创建实体。
- **extra_state_attributes**：

  | 字段 | 来源 | 备注 |
  |---|---|---|
  | `client_id` | `Id` | NPC ID |
  | `ip` | `Addr` | 客户端 IP |
  | `online` | `IsConnect` | 在线状态 |
  | `connections` | `NowConn` | 当前连接数 |
  | `inlet_flow` / `export_flow` | `Flow.*` | 格式化 |
  | `version` | `Version` | NPC 版本 |
  | `vkey` | `VerifyKey` | 仅显示前 16 字符（脱敏） |
  | `rate_limit_kbps` | `RateLimit` | 速率限制 |
  | `max_tunnel_num` | `MaxTunnelNum` | 最大隧道数 |
  | `max_connections` | `MaxConn` | 最大连接数 |
  | `flow_limit` | `Flow.FlowLimit` | 流量上限 |
  | `config_allowed` | `ConfigConnAllow` | 是否允许配置连接 |
  | `web_username` | `WebUserName` | Web 鉴权用户名 |
  | `compression` | `Cnf.Compress` | 是否启用压缩 |
  | `encryption` | `Cnf.Crypt` | 是否启用加密 |
  | `realtime_rate` | `Rate.NowRate` | KB/s 字符串 |
  | `bridge_protocol` / `bridge_port` | `bridgeType` / `bridgePort` | 桥接信息 |
  | `nps_public_ip` | `ip` / `Ip` | NPS 公网 IP |

---

## 五、关键实现细节

### 5.1 鉴权签名

```python
timestamp = str(int(time.time()))
sign = hashlib.md5((self._auth_key + timestamp).encode("utf-8")).hexdigest()
# 提交：auth_key=sign, timestamp=...
```

注意：HA 这边是用 `int(time.time())`（秒级），不是毫秒；签名输出 32 位小写 hex。

### 5.2 重定向拦截

NPS 源码 `base.go` 在鉴权失败时返回 `302 → /login/index`。若允许重定向，客户端会被重定向到登录页并得到 HTML 而非 JSON，导致后续 JSON 解析报错且错误信息误导。

代码中强制 `allow_redirects=False`，遇到 302 时主动抛出 `HomeAssistantError`，明确提示用户"auth_key 错误"。

### 5.3 隧道查询策略

由于 NPS `server.go` 的过滤逻辑：当 `type=""` 且 `clientId=0` 时，会跳过所有 `Client.Id != 0` 的真实隧道，因此不能用空 type 一次拉完。

代码采用 7 次查询 + 合并去重：

```python
for tunnel_type in TUNNEL_TYPES:  # tcp/udp/socks5/httpProxy/secret/p2p/file
    rows = _post("/index/gettunnel", type=tunnel_type).get("rows", [])
    for t in rows:
        if t.get("Id") not in seen_ids:
            seen_ids.add(t["Id"])
            all_tunnels.append(t)
```

单次失败仅 `WARNING` 记录，不影响整体更新。

### 5.4 协调器容错

```python
- 核心请求（隧道/客户端）：失败时整体 raise，由 HA 标记 coordinator 为 unavailable
- 可选请求（Host/时间）：try/except 吞掉，debug 日志
```

`hostCount` 在旧版 NPS 中可能没有 `/index/hostlist/` 接口，失败后 sensor 显示 `None`（而非 unavailable）。

### 5.5 仪表盘聚合字段

`coordinator._build_dashboard(tunnels, clients, hosts)` 静态方法产出以下键：

| 字段 | 含义 |
|---|---|
| `clientCount` / `clientOnlineCount` | 客户端总数 / 在线数 |
| `inletFlowCount` / `exportFlowCount` | 所有客户端流量累计（字节） |
| `totalConnections` | 所有客户端 `NowConn` 累计 |
| `tcpC` / `udpCount` / `socks5Count` / `httpProxyCount` / `secretCount` / `p2pCount` / `fileCount` | 各类型隧道计数 |
| `tunnelTotal` | 隧道总数 |
| `hostCount` | Host 映射数量 |
| `nowRateBps` | 所有客户端 `Rate.NowRate` 累计（B/s） |
| `serverIps` | 全部 NPS 公网 IP，去重后逗号连接 |
| `bridgeTypes` | 全部 `bridgeType` 去重后逗号连接 |

### 5.6 开关反馈延迟

`REFRESH_DELAY = 3` 秒：用户在 UI 触发 `turn_on/off` 后，集成先调用 NPS API，再 `await asyncio.sleep(3)`，最后 `coordinator.async_request_refresh()` 强制拉取最新数据并广播给所有监听实体。

不强制 sleep 直接刷新会拿到 NPS 内部状态尚未更新的旧值（按钮状态短暂错乱）。

### 5.7 流量单位

- 传感器：内部存原始字节，读取时 `round(raw * 1/1024^3, 2)` 输出 GB。
- Switch extra_state_attributes：`_format_flow(bytes)` 动态单位（B / KB / MB / GB / TB），便于在卡片上直接展示。

### 5.8 密码脱敏

`_mask_password`：长度 ≤4 显示 `****`；否则 `前2 + 最多8个* + 后2`。

`vkey`：仅显示前 16 字符。

---

## 六、日志与故障排查

### 6.1 常用日志关键字

| 关键字 | 含义 |
|---|---|
| `NPS API 请求`（DEBUG） | 每次 POST 的 URL 和参数 keys |
| `NPS 返回 302 重定向`（ERROR） | 鉴权签名失败（auth_key 错） |
| `NPS API 业务错误`（ERROR） | 服务端返回 status=0 + msg |
| `NPS API 请求失败`（ERROR） | 网络层失败（超时/连接拒绝等） |
| `NPS 返回内容无法解析为 JSON`（ERROR） | 收到了非 JSON 响应（HTML 登录页） |
| `NPS 更新完成`（INFO） | 每次拉取成功的条数汇总 |
| `正在开启/停止/启用/禁用 ...`（INFO） | 开关操作 |

### 6.2 常见问题

| 现象 | 排查方向 |
|---|---|
| 添加集成提示 `connection_error` | 1) host:port 拼写 2) 防火墙 3) auth_key 是否为 nps.conf 的原始值 4) 时钟偏差 |
| 隧道开关操作后 5~10 秒无反馈 | 正常，`REFRESH_DELAY=3s` + coordinator 拉取 + 监听回调 |
| sensor 一直 `unavailable` | coordinator 首次刷新失败，看 ERROR 日志中的根因 |
| `hostCount` 一直为 None | NPS 版本没有 `/index/hostlist/` 接口，集成会安全忽略 |
| 重复添加相同 host 提示 already configured | 通过 host 去重的多实例保护，请到现有实例查看 |

---

## 七、扩展与开发

### 7.1 添加新 Sensor

1. 在 `coordinator._build_dashboard()` 中产出新键。
2. 在 `sensor.DASHBOARD_SENSORS` 元组列表中追加新条目：
   ```python
   ("myKey", "My Sensor Name", "unit", "mdi:icon", SensorStateClass.MEASUREMENT, "device_class", 1.0)
   ```
3. 重启 HA。

### 7.2 添加新 Switch

当前 `switch.py` 已在 `async_setup_entry` 内一次性建好所有实体。若要新增：
1. 在 `NpsApiClient` 增加对应控制方法（如 `delete_tunnel`）。
2. 在 `switch.py` 增加新实体类并追加到 `entities` 列表。

### 7.3 多实例 / 多服务器

无特殊改动；HA 通过 `unique_id` 自动隔离，每个实例有自己的 coordinator 和实体。

### 7.4 与卡片 / 自动化联动示例

```yaml
# 任意自动化：隧道掉线时推送通知
trigger:
  - platform: state
    entity_id: switch.1_myhost_ssh_tcp_192_168_1_10_22
    to: "off"
action:
  - service: notify.mobile_app
    data:
      title: "NPS 隧道断开"
      message: "{{ trigger.entity_id }} 状态变为 {{ trigger.to_state.state }}"
```

---

## 八、附录

### 8.1 关键常量

| 来源 | 常量 | 值 | 说明 |
|---|---|---|---|
| `api.py` | `TUNNEL_TYPES` | `[tcp, udp, socks5, httpProxy, secret, p2p, file]` | 7 种隧道类型 |
| `api.py` | `REQUEST_TIMEOUT` | `15` 秒 | HTTP 超时 |
| `coordinator.py` | `UPDATE_INTERVAL` | `30` 秒 | 轮询周期 |
| `switch.py` | `REFRESH_DELAY` | `3` 秒 | 操作后等待服务端状态同步 |
| `sensor.py` | `BYTES_TO_GB` | `1 / 1024**3` | 流量转换系数 |

### 8.2 NPS API 端点表

| 方法 | 端点 | 参数 | 用途 |
|---|---|---|---|
| POST | `/auth/get_time` | `auth_key, timestamp` | 服务器时间（调试用） |
| POST | `/index/gettunnel` | `+ type, offset, limit` | 隧道列表 |
| POST | `/index/hostlist/` | `offset, limit` | 域名映射 |
| POST | `/client/list` | `offset, limit` | 客户端列表 |
| POST | `/client/change_status` | `+ id, status` | 客户端启停 |
| POST | `/index/start` | `+ id` | 开启隧道 |
| POST | `/index/stop` | `+ id` | 停止隧道 |

### 8.3 版本演进

| 版本 | 日期 | 变更 |
|---|---|---|
| 0.1.0 | 2026-08-22 | 初版：隧道/客户端开关 + 16 个 sensor |

---
