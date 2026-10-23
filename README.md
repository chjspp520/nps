# NPS 隧道管理集成 - 项目说明文档

> 适用版本：`1.1.0`  
> 适用 Home Assistant：支持 Config Flow / `panel_custom` / 签名链接（`async_sign_path`）的版本（2024.x 及以上）  
> 依赖：`requests`（唯一第三方依赖）

---

## 一、项目概述

### 1.1 集成名称与定位

- **集成名称**：NPS 隧道管理（Home Assistant 集成域 `nps`）
- **对接对象**：[ehang-io/nps](https://github.com/ehang-io/nps) —— 一款轻量级、高性能、功能强大的内网穿透代理服务器。
- **集成目标**：把 NPS 服务端的运行数据完整映射为 HA 实体，并额外提供一个**可视化管理面板**（隧道 / 客户端 / 域名映射的增删改启停），面板可在侧边栏、设备页悬浮窗中打开。

### 1.2 功能特性

| 能力 | 说明 |
|---|---|
| 仪表盘统计 | 17 个中文名称的传感器：客户端总数/在线数、连接数、各类隧道数量、进出流量、实时速率等 |
| 隧道控制 | 每个 NPS 隧道生成一个 `switch` 实体，支持开启/停止 |
| 客户端控制 | 每个 NPC 客户端生成一个 `switch` 实体，支持启用/禁用（断开/恢复连接） |
| 域名映射统计 | 读取并展示 HTTP(S) 域名反向代理数量（部分旧版 NPS 无此接口，已做容错） |
| **管理面板** | 可视化界面（`panel/nps-panel.js`）：隧道 / 客户端 / 域名映射三个选项卡，支持搜索、类型筛选、新建、编辑、复制、启停、删除 |
| **设备页悬浮窗** | 设备页点「访问」不再整页跳转，而是弹出可拖动、可缩放的 iframe 悬浮窗（`panel/nps-embed.js`） |
| **访问密钥传感器** | 密钥加盐 + 整点轮换（旧密钥宽限 1 小时），状态 = 剩余分钟数，属性含密钥、剩余时长、可直接打开的访问地址 |
| **管理面板访问开关** | 一键禁用/启用面板访问（禁用后设备链接、面板页面、WS/HTTP 接口全部拒绝） |
| 服务器时间 | 每次轮询顺带读取 NPS 服务端时间（`/auth/get_time`）存到 `coordinator.server_time`，便于排查时钟偏差（服务端要求时间戳偏差 ≤ 20 秒） |
| 多实例 | 以 `unique_id = nps_{host}` 支持配置多个 NPS 服务端，面板内可切换实例 |
| 轮询间隔可调 | 选项流可设置 5~3600 秒（默认 30 秒），修改后自动重载 |

### 1.3 三种入口

| 入口 | 打开方式 | 说明 |
|---|---|---|
| 侧边栏「NPS 管理」 | `panel_custom` 面板（路径 `/nps`） | 整页加载，需 HA 管理员；模块 `nps-panel.js` 同时被注册为全局前端资源 |
| 设备页「访问」 | 设备 `configuration_url` = 签名地址 | 被 `nps-embed.js` 拦截，改为**同页悬浮窗** |
| 任意浏览器（含外部） | `http(s)://<HA>/nps/console?entry=<entry_id>&authSig=<jwt>`<br>`http(s)://<HA>/nps/console?entry=<entry_id>&key=<密钥>` | 签名地址 24 小时有效；密钥短链接整点轮换（旧密钥宽限 1 小时）。都可不登录 HA 直接打开 |

### 1.4 文件结构

```text
y:\custom_components\nps\
├── __init__.py          # 集成入口：注册面板、创建 client/coordinator、转发平台
├── api.py               # NpsApiClient：HTTP 请求 + MD5 签名鉴权 + 全部增删改启停接口
├── config_flow.py       # UI 配置流 + 选项流（scan_interval）
├── const.py             # 全局常量（DOMAIN / CONF_SCAN_INTERVAL / CONF_PANEL_ACCESS）
├── coordinator.py       # NpsDataUpdateCoordinator：周期轮询，聚合仪表盘数据
├── console_auth.py      # 签名地址签发、会话 Cookie、authSig 校验、面板密钥（加盐整点轮换）
├── helpers.py           # 设备信息、面板地址、访问开关读写
├── panel.py             # 管理面板后端：websocket 命令 + 独立页面 + HTTP 数据接口
├── sensor.py            # 19 个 sensor：17 个仪表盘 + 面板访问密钥 + 所有实体
├── switch.py            # NpsTunnelSwitch / NpsClientSwitch / NpsPanelAccessSwitch
├── panel/
│   ├── nps-panel.js     # 管理面板 webcomponent（nps-panel，侧边栏与悬浮窗共用）
│   └── nps-embed.js     # 设备页「访问」悬浮窗拦截模块（add_extra_js_url 注入）
├── manifest.json        # HA 集成元数据
├── strings.json         # HA 基准翻译文件（必须存在）
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
| `__init__.py` | `async_setup` 里注册面板（`async_setup_panel`）；`async_setup_entry` 创建 `NpsApiClient` + `NpsDataUpdateCoordinator`，存入 `hass.data[DOMAIN][entry_id]`，首次刷新验证连通性后转发 `[SWITCH, SENSOR]` 平台 |
| `config_flow.py` | 输入 `host`（`ip:port`）+ `auth_key`；`test_connection()` 验证；`unique_id = nps_{host}` 去重；选项流只含 `scan_interval`（`OptionsFlowWithReload`，改完自动重载） |
| `api.py` | 唯一网络层。`NpsApiClient` 用 MD5 签名 + POST form 调用 NPS 官方 API；**禁止 302 重定向**；同一路由支持多候选路径（尾部斜杠差异） |
| `coordinator.py` | 30 秒（可配）轮询；产出 `data`（隧道）、`clients_data`、`hosts_data`、`dashboard_data`、`server_time` |
| `sensor.py` | 按 `DASHBOARD_SENSORS` 字典表批量创建 17 个统计传感器；`NpsAccessKeySensor`（面板访问密钥）；`NpsAllEntitiesSensor`（所有实体汇总） |
| `switch.py` | 遍历 `coordinator.data` 建隧道开关、遍历 `clients_data` 建客户端开关（`NoDisplay` 跳过），末尾追加「管理面板访问」开关 |
| `console_auth.py` | 签发/缓存签名地址（24h，缓存 1h）、HMAC 会话票据（12h）、校验 `authSig`、生成/校验面板密钥（加盐整点轮换 + 一个周期宽限） |
| `helpers.py` | `build_device_info()` 统一设备信息与 `configuration_url`；`get_console_url()`（受开关门控）；`set_panel_access()` 持久化并同步设备链接 |
| `panel.py` | 后端命令分发 `_async_dispatch()`（18 种动作）、websocket 命令 `nps/action`、独立页面 `GET /nps/console`、HTTP 接口 `POST /nps/api/action`、静态资源与面板注册 |
| `panel/nps-panel.js` | 面板 UI（纯 Web Component + Shadow DOM）；`_call()` 支持 websocket / HTTP 双通道 |
| `panel/nps-embed.js` | 捕获阶段拦截设备页「访问」链接，弹可拖动/缩放的 iframe 悬浮窗 |

### 2.2 数据流图（轮询链路）

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
│  - _async_update_data()     │  默认 30s
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
│ 19 个    │   │ N 隧道   │
│          │   │ + M 客户 │
│          │   │ + 面板访问│
└──────────┘   └────┬─────┘
                    │ 用户操作 switch
                    ▼
              api.start_tunnel / stop_tunnel
              api.change_client_status
                    │ 睡眠 REFRESH_DELAY=3s
                    ▼
              coordinator.async_request_refresh()
```

### 2.3 管理面板链路（签名 → Cookie → 双通道）

```text
                    ┌──────────────────────────────┐
                    │ 设备页「访问」或侧边栏        │
                    └──────────┬───────────────────┘
                               │
        ┌──────────────────────┼─────────────────────────┐
        │ HA 前端内            │ 独立页面（iframe / 新标签）│
        ▼                      ▼
 websocket nps/action     GET /nps/console?entry=&authSig= （或 &key=）
 （require_admin）              │ 校验 authSig / 面板密钥
        │                      │ Set-Cookie: nps_panel_sess（12h）
        │                      ▼
        │                POST /nps/api/action（Cookie 鉴权）
        │                      │
        └──────────┬───────────┘
                   ▼
        _async_dispatch()  → api.* → NPS
                   │
        coordinator.async_refresh()
                   │
        返回最新快照（tunnels/clients/hosts/dashboard）
```

**面板前端双通道**：`nps-panel.js` 的 `_call(action, data)`：

- `_httpMode === true`（独立页面，`startHttp(entryId)` 设置）→ `fetch("/nps/api/action", {method:"POST", credentials:"same-origin", ...})`；
- 否则（HA 前端内）→ `hass.connection.sendMessagePromise({type:"nps/action", ...})`。

两者返回同一份快照结构，UI 代码无需区分。

### 2.4 NPS API 关键约束（与源码对齐）

| 约束 | 说明 |
|---|---|
| 签名算法 | `sign = md5(auth_key + timestamp).hexdigest()`，32 位小写 |
| 鉴权失败 | NPS 返回 `302 → /login/index`；必须 `allow_redirects=False`，否则会拿到 HTML 登录页 |
| 业务错误 | 响应 JSON `status == 0` 表示失败；`msg` 字段说明原因 |
| 隧道类型 | 支持 `tcp / udp / socks5 / httpProxy / secret / p2p / file` 共 7 种 |
| 获取隧道 | `/index/gettunnel` 必须按 `type` 逐个查询再合并去重（type="" 且 clientId=0 时会过滤掉所有真实隧道） |
| 路由斜杠 | 不同版本/分支的尾部斜杠不一致，`api.ROUTES` 为每个接口列了候选路径并按序回退 |
| 隧道启停 | `/index/start` 与 `/index/stop`，参数 `id` |
| 客户端启停 | `/client/change_status`，参数 `id` + `status`（字符串 `"true"` / `"false"`） |
| 服务器时间 | `/auth/get_time`（鉴权控制器中），用于诊断时钟漂移 |

---

## 三、安装与配置

### 3.1 前置条件

1. 已部署 [NPS 服务端](https://github.com/ehang-io/nps)，并能在浏览器访问 Web 控制台。
2. NPS 服务端的时间与 Home Assistant 主机时间偏差应 **≤ 20 秒**（超出后 MD5 签名会被服务端拒绝）。
3. 已知 NPS 服务端的 `ip:port` 和 `nps.conf` 中的 `auth_key`（**不是 Web 登录用户名/密码**）。
4. **HA 必须能确定自己的访问地址**（`internal_url` / `external_url`，或 Nabu Casa 云端地址）。否则无法签发面板签名链接，设备页不会出现「访问」按钮，密钥实体为 `unavailable`。

### 3.2 安装方式

将整个 `nps` 目录复制到 HA 配置目录的 `custom_components/nps/` 即可。重启 Home Assistant。

重启后会自动注册：

- 侧边栏面板 `/nps`（`panel_custom`，需要管理员）；
- 静态资源 `/nps_static/nps-panel.js`、`/nps_static/nps-embed.js`；
- 全局前端模块（`add_extra_js_url`）：设备页「访问」的悬浮窗拦截；
- 视图 `GET /nps/console`、`POST /nps/api/action`；
- websocket 命令 `nps/action`。

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

每个 NPS 服务端用 `host` 作为唯一标识（`unique_id = nps_{host}`），可重复添加多个不同 `host` 的实例。所有实例共用同一套面板/接口注册，面板顶部会自动出现实例下拉框，可切换查看不同服务端。

### 3.5 选项（Options）

**设置 → 设备与服务 → 集成 → NPS → 配置**

| 选项 | 范围 | 默认 | 说明 |
|---|---|---|---|
| `scan_interval` | 5 ~ 3600 秒 | 30 | 轮询间隔；基于 `OptionsFlowWithReload`，保存后自动重载集成 |

服务器地址与 `auth_key` 仍不可在选项里修改，如需变更请删除原集成后重新添加。

---

## 四、实体清单

所有实体归属于同一台虚拟设备 `NPS Server ({host})`，便于在 HA 设备页中统一查看。设备 `configuration_url` 指向管理面板的**签名地址**（受「管理面板访问」开关控制）。

### 4.1 Sensor 实体（19 个）

> `unique_id` 格式：`{entry_id}_nps_{key}`；`entity_id` 由固定的 `suggested_object_id` 决定（见 4.1.4）。

#### 4.1.1 仪表盘统计传感器（17 个）

| Key | 名称 | entity_id | 单位 | 图标 | StateClass | Divisor |
|---|---|---|---|---|---|---|
| `clientCount` | 客户端总数 | `sensor.client_total` | — | `mdi:account-group` | TOTAL | 1 |
| `clientOnlineCount` | 在线客户端 | `sensor.clients_online` | — | `mdi:account-check` | TOTAL | 1 |
| `totalConnections` | 连接总数 | `sensor.total_connections` | — | `mdi:connection` | MEASUREMENT | 1 |
| `inletFlowCount` | 入口流量 | `sensor.inlet_traffic` | GB | `mdi:download-network-outline` | TOTAL_INCREASING | 1/1024³ |
| `exportFlowCount` | 出口流量 | `sensor.export_traffic` | GB | `mdi:upload-network-outline` | TOTAL_INCREASING | 1/1024³ |
| `tunnelTotal` | 隧道总数 | `sensor.tunnel_total` | — | `mdi:tunnel-variant` | TOTAL | 1 |
| `tcpC` | TCP 隧道 | `sensor.tcp_tunnels` | — | `mdi:tunnel` | TOTAL | 1 |
| `udpCount` | UDP 隧道 | `sensor.udp_tunnels` | — | `mdi:tunnel` | TOTAL | 1 |
| `socks5Count` | SOCKS5 隧道 | `sensor.socks5_tunnels` | — | `mdi:tunnel` | TOTAL | 1 |
| `httpProxyCount` | HTTP 代理隧道 | `sensor.http_proxy_tunnels` | — | `mdi:tunnel` | TOTAL | 1 |
| `secretCount` | 秘密隧道 | `sensor.secret_tunnels` | — | `mdi:tunnel-lock` | TOTAL | 1 |
| `p2pCount` | P2P 隧道 | `sensor.p2p_tunnels` | — | `mdi:tunnel` | TOTAL | 1 |
| `fileCount` | 文件隧道 | `sensor.file_tunnels` | — | `mdi:file-document-outline` | TOTAL | 1 |
| `hostCount` | 域名映射 | `sensor.host_mappings` | — | `mdi:dns-outline` | TOTAL | 1 |
| `nowRateBps` | 实时速率 | `sensor.realtime_rate` | KB/s | `mdi:speedometer` | MEASUREMENT | 1/1024 |
| `serverIps` | 服务器 IP | `sensor.server_ips` | — | `mdi:server-network` | — | 1（字符串原样返回） |
| `bridgeTypes` | 网桥协议 | `sensor.bridge_protocols` | — | `mdi:swap-horizontal` | — | 1（字符串原样返回） |

> 备注：`serverIps` 与 `bridgeTypes` 是逗号连接的多值字符串，不会被 `divisor` 缩放（代码里 `if isinstance(raw_val, (str, bool)): return raw_val` 已特判）。

**隧道类传感器附带明细属性**：`隧道总数`、`TCP 隧道`、`UDP 隧道`、`SOCKS5 隧道`、`HTTP 代理隧道`、`秘密隧道`、`P2P 隧道`、`文件隧道` 这 8 个实体的状态属性里额外带该类型下每条隧道的信息（`隧道总数` 汇总全部类型）：

| 属性 | 内容 |
|---|---|
| `tunnels` | 隧道摘要列表，最多 `MAX_LISTED_TUNNELS = 50` 条 |
| `returned` | 本次列出的条数 |
| `truncated` | 仅当条数达到 50 时出现，值为 `true` |

`tunnels` 每项字段：

| 字段 | 含义 |
|---|---|
| `tunnel_id` | 隧道 ID |
| `remark` | 备注（没有则 `null`） |
| `mode` | 原始模式值（`tcp` / `udp` / `socks5` / `httpProxy` / `secret` / `p2p` / `file`；旧版 NPS 取 `Type`） |
| `port` | 服务端端口（0 = 自动分配） |
| `target` | 内网目标（`Target.TargetStr` 第一行） |
| `client_id` / `client_online` | 所属 NPC ID / 该 NPC 是否在线 |
| `running` | NPS `RunStatus`：隧道当前是否在运行 |
| `enabled` | NPS `Status`：是否在配置中启用 |
| `inlet_flow` / `export_flow` | 已格式化的流量（B / KB / MB / GB / TB） |

- `tunnels` 属性已声明 `_unrecorded_attributes`，**不写入 recorder**（避免历史库膨胀与属性大小上限）。
- 用法示例（列出正在运行的 TCP 隧道备注）：

  ```yaml
  {{ state_attr('sensor.tcp_tunnels', 'tunnels')
     | selectattr('running')
     | map(attribute='remark') | list }}
  ```

#### 4.1.2 面板访问密钥（新增）

| 项目 | 内容 |
|---|---|
| 名称 | **面板访问密钥** |
| entity_id | `sensor.panel_access_key` |
| unique_id | `{entry_id}_nps_access_key` |
| 图标 / 单位 | `mdi:key-variant` / `min`（`state_class: measurement`；**不声明** `device_class: duration`，否则 HA 会把分钟按规范单位换算回秒） |
| 状态值 | 当前密钥**剩余有效分钟数**（不足 1 分钟按 1 分钟），随 coordinator 刷新（默认 30 秒，可在选项中改 5~3600 秒） |

密钥口径与爱快集成的 `sensor.ikuai_api_key` 完全一致：

```text
key = md5(集成盐 | 整点序号 | 主机地址 | 条目 id)[:16]
```

- **加盐**：盐在集成启动时随机生成（`os.urandom(16).hex()`），只存在内存里，不落盘、不写进任何链接；即使知道你连的是哪台 NPS，也算不出密钥。
- **整点轮换**：以 UTC 整点为一个周期（`API_KEY_TTL = 3600` 秒），跨整点自动换新。
- **旧密钥宽限一个周期**：上一把密钥在下一个整点内仍然有效，正在使用的人跨整点不会被打断；再过一小时彻底失效。
- 多实例时密钥带条目 id，各台密钥互不相同，也可以只凭密钥反查是哪一台。

状态属性：

| 属性 | 含义 |
|---|---|
| `密钥` | 当前整点的密钥（16 位 hex） |
| `剩余时长` | 中文可读时长，分钟级只到分钟：`55 分` / `29 分`；只剩不到 1 分钟时显示 `42 秒` |
| `访问地址` | 可直接打开的面板地址：`http(s)://<HA>/nps/console?entry=<entry_id>&key=<密钥>` |
| `过期时间` | 本周期结束时刻（带时区的 ISO 时间） |
| `上一把密钥` | 上一个整点的密钥（宽限期内仍有效，首个周期为 `null`） |
| `算法` | 密钥算法说明 |

实体形态示例（状态是**整数分钟**，单位 `min`）：

```yaml
entity_id: sensor.nps_server_47_108_189_87_8080_panel_access_key
state: "37"                 # 37 分钟，最长 60
unit_of_measurement: min
attributes:
  密钥: ce0fa23a907c260f
  剩余时长: 36 分
  访问地址: http://<HA>:8123/nps/console?entry=<entry_id>&key=ce0fa23a907c260f
  过期时间: "2026-10-22T19:00:00+08:00"
  上一把密钥: null
  算法: md5(集成盐 | 整点序号 | 主机地址 | 条目id)[:16]，整点换新、旧密钥宽限 1 小时
```

行为说明：

- 状态单位就是 `min`：**不要**给它加 `device_class: duration`，否则 HA 会按 duration 的规范单位把分钟换算回秒（状态变成 `分钟 × 60` 的浮点数、单位显示 `s`）。
- 「访问地址」是一条**短链接**：不需要签名、不依赖 HA 登录态，有效期为"当前整点剩余时间 + 一个整点宽限"，打开后照常下发 12 小时会话 Cookie。
- 密钥相关属性已声明 `_unrecorded_attributes`，**不写入 recorder** 历史库。
- 「管理面板访问」开关关闭时，实体为 `unavailable`。
- 盐只在内存里，**HA 重启后密钥会重新生成**（即使还在同一整点）。
- 改过单位/设备类后必须**重载集成**（点"刷新"无效），页面再硬刷一次。

#### 4.1.3 所有实体（汇总）

| 项目 | 内容 |
|---|---|
| 名称 | **所有实体** |
| entity_id | `sensor.all_entities` |
| 状态值 | 该设备下实体注册表条目数量 |
| 属性 | `count`（数量）、`entities`（`entity_id` / `name` / `icon` / `state` 明细）、`truncated`（超过 200 条时置 `true`） |

刷新时机：每 60 秒 + 实体注册表变化事件 + 成员实体状态变化。

#### 4.1.4 命名与 entity_id 稳定性

- 传感器显示名全部为中文；中文名 slugify 后为空，会生成 `sensor.xxx_2` 之类的不稳定 ID，因此每个传感器都用 `suggested_object_id` **显式固定** entity_id。
- 固定的 object_id 沿用早期英文名的 slug（如 `Client Total` → `client_total`），**升级后已有 entity_id 不变**；`unique_id` 也未改动，重启后注册表会把显示名刷新为中文（用户手动改过名的保持用户设置）。

### 4.2 Switch 实体（动态数量 + 1）

#### 4.2.1 `NpsTunnelSwitch` —— 隧道开关

- **唯一 ID**：`{entry_id}_nps_tunnel_{tunnel_id}`
- **命名规则**：
  - 有备注时：`{client_id}_{remark}_{MODE_LABEL}_{target_first_line}`
  - 无备注时：`{client_id}_Tunnel{tunnel_id}_{MODE_LABEL}_{target_first_line}`
  - `MODE_LABEL` 取自 `MODE_LABELS`：`TCP` / `UDP` / `Socks5` / `HTTPProxy` / `Secret` / `P2P` / `File`（另有 `HostServer`、`WebServer`）；目标为空时后缀省略
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
  | `password` | `Password` | **脱敏**（前 2 + 中间最多 8 个 \* + 后 2）；隧道本身没密码时不输出该字段 |
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

#### 4.2.3 `NpsPanelAccessSwitch` —— 管理面板访问开关

- **名称 / entity_id**：`管理面板访问` / `switch.panel_access`
- **唯一 ID**：`{entry_id}_nps_panel_access`
- **图标**：`mdi:shield-lock`（开） / `mdi:shield-off-outline`（关）
- **属性**：`entry_id`、`panel_url`（开启时为签名面板地址，关闭时不输出）
- **持久化**：状态写在配置条目 `options.panel_access`，重启后保持
- **关闭后的效果**：
  - 设备页「访问」链接被移除（`configuration_url` 置空）；
  - 已打开的面板页面所有请求被拒（HTTP 403 `panel_disabled` / 401 `unauthorized`）；
  - HA 前端内 websocket 调用返回 `panel_disabled`；
  - 密钥传感器变为 `unavailable`。

---

## 五、管理面板

### 5.1 打开方式

1. **侧边栏**：设置 → 面板 → 「NPS 管理」；路径 `/nps`，需管理员。
2. **设备页「访问」**：点击设备信息里的「访问」按钮，弹**悬浮窗**（不再整页跳转）。
3. **链接直开**：`sensor.panel_access_key` 的 `访问地址`（密钥短链接，整点轮换 + 1 小时宽限）或设备实体的 `panel_url`（`authSig` 签名地址，24 小时），都可在任意浏览器（含外网）直接打开。

### 5.2 面板功能

顶部：标题、状态条（`N 条隧道 · 在线/总客户端 · N 个域名映射`）、**实例下拉框**（多实例时出现）。
工具栏：搜索框、隧道类型筛选（仅隧道页）、「新建…」、「刷新」。

三个选项卡：

| 选项卡 | 表格列 | 操作 |
|---|---|---|
| 隧道 | 运行、ID、类型、备注、客户端、服务端端口、内网目标、流量(入/出) | 启停、编辑、复制、删除 |
| 客户端 | 连接、ID、备注、地址、版本、连接数、流量(入/出)、实时速率 | 启用/禁用、编辑、删除 |
| 域名映射 | 状态、ID、域名、内网目标、备注、客户端、协议 | 启停、编辑、删除 |

新建/编辑使用原生 `<dialog>` 表单，字段与 NPS 官方后台一致：

- **隧道**：隧道类型（7 种）、所属客户端、备注、服务端端口（0=自动分配）、服务端绑定 IP、内网目标、隧道密码（仅 `secret`）、本地文件路径（仅 `file`）、去除 URL 前缀（仅 `httpProxy`）、转发到 NPS 服务器本地。带 `dependsOn` 的字段会随类型自动显隐。
- **客户端**：备注、唯一验证密钥、Basic 认证用户名/密码、压缩、加密、允许配置文件模式连接、带宽限制 (KB/s)、流量限制 (M)、最大连接数、最大隧道数、Web 登录用户名/密码、IP 白名单（开关/授权密码/列表）、黑名单 IP 列表、到期时间。编辑时留空的敏感字段（Basic 密码、Web 密码、白名单密码、各 IP 列表）不会被提交，避免把服务端已有值清空。
- **域名映射**：所属客户端、域名、协议（all/http/https）、URL 路由、内网目标、备注、改写请求 Host、自定义请求头、自动申请 HTTPS、HTTPS 私钥/证书、转发到 NPS 服务器本地。编辑时留空的私钥/证书同样不提交。

面板操作完成后，后端会立即 `coordinator.async_refresh()` 刷新一次，保证面板与 HA 实体同步：

- **新增**隧道/客户端 → 自动补建对应的 `switch` 实体；
- **删除**隧道/客户端 → 自动移除对应实体（含实体注册表条目）；
- **修改**备注/端口/目标等 → 实体状态属性与显示名就地更新。

以上都不需要重载集成；`switch.py` 的 `_sync_entities()` 挂在 coordinator 监听上做增量对齐。

### 5.3 设备页悬浮窗（`nps-embed.js`）

- 通过 `frontend.add_extra_js_url` 注入，在 `document` 捕获阶段拦截点击；用 `composedPath()` 穿透 `ha-button` 的 Shadow DOM。
- 命中条件：链接 pathname 为 `/nps/console` 且带 `authSig`。
- 命中后 `preventDefault + stopPropagation`，在 Shadow DOM 宿主里弹 iframe 窗口；`Ctrl/Cmd/Shift/Alt` 点击与中键仍走浏览器原生新标签。
- 同时把链接的 host 原地改写为**当前地址栏 origin**（`authSig` 只签 path+query 不签 host），带端口映射/反向代理时不会指向不可达的内部地址。
- 窗口能力：标题栏拖动、右下角缩放、`↻` 重载、`↗` 新标签打开、`✕` 关闭（关闭时 `src=about:blank` 释放页面连接）。
- 非模态：容器 `pointer-events: none`、窗口本体 `auto`，窗体外仍可正常操作 HA。
- 调试：F12 输入 `__npsFloatEmbed` 可确认模块已加载；`__npsFloatOpen(url)` / `__npsFloatClose()` 可手动控制。

### 5.4 鉴权与安全

| 环节 | 机制 |
|---|---|
| 面板地址 | HA 官方 `async_sign_path` 签发 `authSig`，默认 **24 小时**有效；地址缓存 1 小时，到期自动重签 |
| 面板密钥 | `?key=<16 位 hex>`，算法 `md5(盐 \| 整点序号 \| 主机地址 \| 条目 id)`；**整点轮换**、旧密钥**宽限一个周期**（详见 4.1.2 / 6.11） |
| 首次进入 | `GET /nps/console` 校验 `authSig`（或 `key`）后下发 HttpOnly Cookie |
| 会话 | `nps_panel_sess` = `entry_id.签发时间.HMAC-SHA256`，**12 小时**有效，`Path=/nps/`、`HttpOnly`、`SameSite=Lax`，HTTPS 下自动加 `Secure` |
| 数据接口 | 独立页面走 `POST /nps/api/action` + Cookie；HA 前端内走 websocket `nps/action`（`require_admin`） |
| 为什么不用 `authSig` 直接 POST | HA 只对 GET/HEAD 接受签名参数，所以页面第一次 GET 用 `authSig` 换 Cookie，后续 POST 靠 Cookie |
| 总开关 | 「管理面板访问」开关；关闭后签名地址不再签发、已打开页面请求被拒 |

### 5.5 后端接口

**websocket**：`{type: "nps/action", action, entry_id?, data?}`（管理员）

**HTTP - 页面**：`GET /nps/console?entry=<entry_id>`，鉴权二选一：`authSig=<jwt>`（签名链接，24h）或 `key=<面板密钥>`（整点轮换），校验通过后下发 Cookie 并返回面板 HTML。

**HTTP - 数据**：`POST /nps/api/action`，body `{action, entry_id?, data?, key?}`，鉴权三选一：会话 Cookie / `authSig` / 面板密钥（`?key=` 或 body 的 `key`）；未指定 `entry_id` 时取第一个已加载实例。

成功返回最新快照：

```json
{
  "success": true,
  "entry_id": "…",
  "entries": [{ "entry_id": "…", "title": "NPS (host)" }],
  "tunnels": [], "clients": [], "hosts": [],
  "dashboard": {}, "server_time": 0,
  "tunnel_types": ["tcp", "udp", "socks5", "httpProxy", "secret", "p2p", "file"],
  "host_schemes": ["all", "http", "https"]
}
```

失败返回 `{success: false, code, message}`，错误码：

| code | 触发条件 |
|---|---|
| `panel_disabled` | 「管理面板访问」开关关闭 |
| `invalid_format` | 请求体不是 JSON / 缺少 `action` / 参数校验不通过 |
| `nps_error` | NPS 连接失败、业务错误、未预期异常 |
| `unauthorized` | （HTTP）Cookie 无效、`authSig` 校验失败且面板密钥不匹配，401 |

`action = console_url` 特例：不拉数据，直接返回 `{success: true, url, entry_id}`。

---

## 六、关键实现细节

### 6.1 鉴权签名

```python
timestamp = str(int(time.time()))
sign = hashlib.md5((self._auth_key + timestamp).encode("utf-8")).hexdigest()
# 提交：auth_key=sign, timestamp=...
```

注意：HA 这边是用 `int(time.time())`（秒级），不是毫秒；签名输出 32 位小写 hex。

### 6.2 重定向拦截

NPS 源码 `base.go` 在鉴权失败时返回 `302 → /login/index`。若允许重定向，客户端会被重定向到登录页并得到 HTML 而非 JSON，导致后续 JSON 解析报错且错误信息误导。代码中强制 `allow_redirects=False`，遇到 302 时主动抛出 `HomeAssistantError`。

### 6.3 隧道查询策略

NPS `server.go` 的过滤逻辑：当 `type=""` 且 `clientId=0` 时，会跳过所有 `Client.Id != 0` 的真实隧道，因此不能用空 type 一次拉完。代码采用 7 次查询 + 合并去重：

```python
for tunnel_type in TUNNEL_TYPES:  # tcp/udp/socks5/httpProxy/secret/p2p/file
    rows = _post("/index/gettunnel", type=tunnel_type).get("rows", [])
    for t in rows:
        if t.get("Id") not in seen_ids:
            seen_ids.add(t["Id"])
            all_tunnels.append(t)
```

单次失败仅 `WARNING` 记录，不影响整体更新。

### 6.4 协调器容错

```text
- 核心请求（隧道/客户端）：失败时整体 raise，由 HA 标记 coordinator 为 unavailable
- 可选请求（Host / 服务器时间）：try/except 吞掉，debug 日志
```

`hostCount` 在旧版 NPS 中可能没有 `/index/hostlist/` 接口，失败后 sensor 显示 `None`（而非 unavailable）。

### 6.5 仪表盘聚合字段

`coordinator._build_dashboard(tunnels, clients, hosts)` 产出以下键：

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

### 6.6 开关反馈延迟

`REFRESH_DELAY = 3` 秒：用户在 UI 触发 `turn_on/off` 后，集成先调用 NPS API，再 `await asyncio.sleep(3)`，最后 `coordinator.async_request_refresh()` 强制拉取最新数据并广播给所有监听实体。不强制 sleep 直接刷新会拿到 NPS 内部状态尚未更新的旧值（按钮状态短暂错乱）。

### 6.7 流量单位

- 传感器：内部存原始字节，读取时 `round(raw * 1/1024^3, 2)` 输出 GB；计数类传感器不做换算，直接输出整数。
- Switch `extra_state_attributes`：`_format_flow(bytes)` 动态单位（`0` 显示 `0 B`，其余按 KB/MB/GB/TB 保留两位小数）。

### 6.8 密码脱敏

`_mask_password`：长度 ≤4 显示 `****`；否则 `前2 + 最多8个* + 后2`。客户端 `vkey` 仅显示前 16 字符。面板页面不回填密码、验证密钥、Web 密码、IP 白名单密码与证书内容，编辑时留空即保持服务端原值。

### 6.9 面板动作分发（`_async_dispatch`）

| action | api 方法 | NPS 端点 |
|---|---|---|
| `list` | —（只刷新） | — |
| `tunnel_add` / `tunnel_edit` | `add_tunnel` / `edit_tunnel` | `/index/add` / `/index/edit` |
| `tunnel_del` / `tunnel_copy` | `del_tunnel` / `copy_tunnel` | `/index/del` / `/index/copy` |
| `tunnel_start` / `tunnel_stop` | `start_tunnel` / `stop_tunnel` | `/index/start` / `/index/stop` |
| `host_add` / `host_edit` / `host_del` | `add_host` / `edit_host` / `del_host` | `/index/addhost` / `/index/edithost` / `/index/delhost` |
| `host_start` / `host_stop` | `start_host` / `stop_host` | `/index/hoststart` / `/index/hoststop` |
| `client_add` / `client_edit` / `client_del` | `add_client` / `edit_client` / `del_client` | `/client/add` / `/client/edit` / `/client/del` |
| `client_on` / `client_off` | `change_client_status` | `/client/change_status` |
| `console_url` | —（签发签名地址） | — |

每个动作执行后统一 `coordinator.async_refresh()` 并返回最新快照；刷新失败只记 `WARNING`，不把已成功的操作报成失败。

### 6.10 传感器中文名与 entity_id 稳定性

`DASHBOARD_SENSORS` 为字典列表（`key / name / object_id / unit / icon / state_class / divisor`）。`NpsDashboardSensor` 覆写 `suggested_object_id` 使用 `object_id`，原因：中文 `name` 经 HA slugify 后为空字符串，会退化成 `sensor.xxx_2` 这类不稳定 ID；固定为早期英文名 slug 可保证升级前后 `entity_id` 完全一致。

### 6.11 面板密钥：加盐 + 整点轮换 + 宽限

1. `_hour_index()` = `int(time.time() // API_KEY_TTL)`（`API_KEY_TTL = 3600`），即 UTC 整点序号；
2. 盐存在 `hass.data["nps_panel_keys"]["salt"]`，首次访问时 `os.urandom(16).hex()` 随机生成，**只在内存里**；
3. `_make_key()` = `md5(f"{盐}|{整点序号}|{host}|{entry_id}")[:16]`（`host` 取自配置条目的 `entry.data["host"]`）；
4. `ensure_panel_key()`：发现整点序号变化就换新，并把旧密钥挪到 `prev_key`；
5. `panel_key_matches()`：`{当前密钥, 上一把密钥}` 命中即通过 —— 这就是"跨整点宽限一个周期"，两小时前的密钥彻底失效；
6. `resolve_entry_by_panel_key()`：遍历所有配置条目按密钥反查，多实例时调用方可以只给 `key` 不给 `entry`；
7. 实体状态 = `remaining_minutes = max(1, (到期时刻 - now + 59) // 60)`，整数、单位 `min`、**不设 `device_class`**（设了 `duration` 会被 HA 换算成秒）；
8. `剩余时长` 属性由 `_human_duration()` 生成："N 天 M 小时" / "N 小时 M 分" / "N 分"，只有不足 1 分钟时才用 "N 秒"。

---

## 七、日志与故障排查

### 7.1 常用日志关键字

| 关键字 | 含义 |
|---|---|
| `NPS API 请求`（DEBUG） | 每次 POST 的 URL 和参数 keys |
| `NPS 返回重定向 [...] → ...`（ERROR） | 鉴权签名失败（auth_key 错，被 302 到登录页） |
| `NPS API 业务错误`（ERROR） | 服务端返回 status=0 + msg |
| `NPS API 请求失败`（ERROR） | 网络层失败（超时/连接拒绝等） |
| `NPS 返回内容无法解析为 JSON`（ERROR） | 收到了非 JSON 响应（HTML 登录页） |
| `NPS 更新完成`（INFO） | 每次拉取成功的条数汇总 |
| `正在开启/停止/启用/禁用 ...`（INFO） | 开关操作 |
| `NPS 管理面板已注册`（DEBUG） | 面板注册成功 |
| `NPS 管理面板前端脚本注册失败`（WARNING） | 面板前端模块未注入（功能降级，不影响实体） |
| `NPS 悬浮窗前端模块注册失败`（WARNING） | 「访问」仍会在新页面打开 |
| `NPS 操作已提交，但刷新数据失败`（WARNING） | 面板操作已生效，只是快照没刷新 |
| `启用/禁用 NPS 管理面板访问`（INFO/WARNING） | 访问开关切换 |

### 7.2 常见问题

| 现象 | 排查方向 |
|---|---|
| 添加集成提示 `connection_error` | 1) host:port 拼写 2) 防火墙 3) auth_key 是否为 nps.conf 的原始值 4) 时钟偏差 |
| 隧道开关操作后 5~10 秒无反馈 | 正常，`REFRESH_DELAY=3s` + coordinator 拉取 + 监听回调 |
| sensor 一直 `unavailable` | coordinator 首次刷新失败，看 ERROR 日志中的根因 |
| `hostCount` 一直为 None | NPS 版本没有 `/index/hostlist/` 接口，集成会安全忽略 |
| 重复添加相同 host 提示 already configured | 通过 host 去重的多实例保护，请到现有实例查看 |
| 设备页没有「访问」按钮 | 1) 未配置 `internal_url`/`external_url`（无法签发地址）2) 「管理面板访问」开关被关闭 3) 集成尚未加载完成 |
| 点「访问」仍在新页面打开 | 1) `nps-embed.js` 未加载（F12 输入 `__npsFloatEmbed` 验证）2) 浏览器缓存旧前端资源，强刷 3) Ctrl/中键点击本来就是新标签 |
| 点「访问」弹窗白屏 / 显示「链接或密钥无效/已过期」 | 签名已过期（>24h）或 Cookie 过期（>12h），重新点一次「访问」；或 HA 地址在浏览器不可达 |
| 侧边栏「NPS 管理」404 / 空白 | `/nps` 路径可能已被其他面板占用，看 ERROR 日志「NPS 管理面板注册失败」 |
| 面板提示「会话或密钥已过期，请重新打开管理面板」 | Cookie 失效；从设备页或侧边栏重新进入 |
| 改了 HA 的 `internal_url`/`external_url` 后「访问」链接还是旧的 | 设备链接在实体添加时写入设备注册表，**重载集成**才会重新签发 |
| 面板提示「管理面板已被「管理面板访问」开关禁用」 | 打开 `switch.panel_access` |
| 「面板访问密钥」为 `unavailable` | 上述开关关闭 |
| 密钥/访问地址整点后变了 | 正常：密钥**整点轮换**；上一把密钥还有一整个周期的宽限，手上的旧链接不会立刻失效 |
| 访问地址打开提示「链接或密钥无效/已过期」 | 已跨过两个整点（超出宽限），或 HA 重启过（盐重新生成）；从实体属性取新地址 |
| 外部脚本调 `/nps/api/action` 返回 401 | 把密钥放 `?key=<密钥>` 或 body 的 `key` 字段；`entry` 可省略（会按密钥反查实例），且密钥必须在有效期内 |
| 剩余时长总是 ≤ 60 分钟 | 设计如此：单位是分钟，密钥按整点轮换，每周期最长 60 分钟 |

---

## 八、扩展与开发

### 8.1 添加新 Sensor

1. 在 `coordinator._build_dashboard()` 中产出新键。
2. 在 `sensor.DASHBOARD_SENSORS` 追加字典：

   ```python
   {
       "key": "myKey",
       "name": "我的传感器",        # 中文显示名
       "object_id": "my_sensor",   # 固定 entity_id 后缀（必填，中文名 slugify 为空）
       "unit": "GB",               # 可选
       "icon": "mdi:chart-line",   # 可选
       "state_class": SensorStateClass.MEASUREMENT,  # 可选
       "device_class": None,       # 可选
       "divisor": 1 / (1024 ** 3), # 可选
   }
   ```

3. 重启 HA。

### 8.2 添加新 Switch

1. 在 `NpsApiClient` 增加对应控制方法（如 `delete_tunnel`）。
2. 在 `switch.py` 增加新实体类并追加到 `async_setup_entry` 的 `entities` 列表。

### 8.3 添加面板动作

1. `api.py` 增加方法（必要时补充 `ROUTES` 候选路径）。
2. `panel.py` 的 `_async_dispatch()` 增加分支。
3. `panel/nps-panel.js` 调用 `this._act("your_action", {...})`。
4. websocket 与 HTTP 两条通道会自动复用同一分发逻辑，无需分别改动。

### 8.4 多实例 / 多服务器

无特殊改动；HA 通过 `unique_id` 自动隔离，每个实例有自己的 coordinator 和实体。面板/接口注册是全局单例（`hass.data` 标记），面板内通过 `entry_id` 切换实例。



---

## 九、附录

### 9.1 关键常量

| 来源 | 常量 | 值 | 说明 |
|---|---|---|---|
| `api.py` | `TUNNEL_TYPES` | `[tcp, udp, socks5, httpProxy, secret, p2p, file]` | 7 种隧道类型 |
| `api.py` | `REQUEST_TIMEOUT` | `15` 秒 | HTTP 超时 |
| `coordinator.py` | `UPDATE_INTERVAL` | `30` 秒 | 默认轮询周期（可被选项覆盖） |
| `switch.py` | `REFRESH_DELAY` | `3` 秒 | 操作后等待服务端状态同步 |
| `sensor.py` | `BYTES_TO_GB` | `1 / 1024**3` | 流量转换系数 |
| `sensor.py` | `MAX_LISTED_ENTITIES` | `200` | 「所有实体」传感器最多列出的条目 |
| `helpers.py` | `PANEL_URL_PATH` | `nps` | 侧边栏面板路径 |
| `panel.py` | `PANEL_STATIC_URL` | `/nps_static` | 前端静态资源前缀 |
| `panel.py` | `PANEL_MODULE_URL` / `PANEL_EMBED_URL` | `/nps_static/nps-panel.js` / `/nps_static/nps-embed.js` | 面板与悬浮窗模块 |
| `console_auth.py` | `CONSOLE_PATH` | `/nps/console` | 独立面板页（签名入口） |
| `console_auth.py` | `CONSOLE_API_PATH` | `/nps/api/action` | 面板数据接口 |
| `console_auth.py` | `CONSOLE_COOKIE_NAME` | `nps_panel_sess` | 会话 Cookie 名 |
| `console_auth.py` | `CONSOLE_COOKIE_MAX_AGE` | `12` 小时 | Cookie 有效期 |
| `console_auth.py` | `CONSOLE_SIGN_EXPIRY` | `24` 小时 | 签名地址有效期 |
| `console_auth.py` | `_URL_CACHE_TTL` | `1` 小时 | 签名地址内存缓存 |
| `console_auth.py` | `API_KEY_TTL` | `3600` 秒 | 面板密钥轮换刻度（整点换新，旧密钥再宽限一个周期） |
| `console_auth.py` | `API_KEY_LEN` | `16` | 面板密钥长度（md5 前 16 位） |
| `const.py` | `CONF_SCAN_INTERVAL` / `DEFAULT_SCAN_INTERVAL` | `scan_interval` / `30` | 轮询间隔选项 |
| `const.py` | `CONF_PANEL_ACCESS` | `panel_access` | 面板访问开关的持久化键 |

### 9.2 NPS API 端点表

| 方法 | 端点 | 参数 | 用途 |
|---|---|---|---|
| POST | `/auth/get_time` | `auth_key, timestamp` | 服务器时间（调试用） |
| POST | `/index/gettunnel` | `+ type, offset, limit` | 隧道列表 |
| POST | `/index/getonetunnel` | `+ id` | 单条隧道 |
| POST | `/index/add` / `/index/edit` / `/index/del` / `/index/copy` | 表单字段 / `id` | 隧道增改删复制 |
| POST | `/index/hostlist/` | `offset, limit` | 域名映射列表 |
| POST | `/index/addhost` / `/index/edithost` / `/index/delhost` | 表单字段 / `id` | 域名映射增改删 |
| POST | `/index/hoststart` / `/index/hoststop` | `+ id` | 域名映射启停 |
| POST | `/client/list` | `offset, limit` | 客户端列表 |
| POST | `/client/add` / `/client/edit` / `/client/del` | 表单字段 / `id` | 客户端增改删 |
| POST | `/client/change_status` | `+ id, status` | 客户端启停 |
| POST | `/index/start` | `+ id` | 开启隧道 |
| POST | `/index/stop` | `+ id` | 停止隧道 |

> 上述路径均有「带/不带尾部斜杠」两种候选形式，由 `api.ROUTES` 依次尝试。

### 9.3 集成内部端点

| 方法 | 路径 | 鉴权 | 用途 |
|---|---|---|---|
| WS | `nps/action` | HA 登录 + 管理员 | 面板所有操作与 `console_url` |
| GET | `/nps/console?entry=<id>&authSig=<jwt>` | HA 签名（24h） | 返回独立面板 HTML，并下发会话 Cookie |
| GET | `/nps/console?entry=<id>&key=<密钥>` | 面板密钥（整点轮换 + 1 周期宽限） | 同上，短链接入口 |
| POST | `/nps/api/action` | 会话 Cookie / `authSig` / `?key=` 或 body.key | 面板数据接口 |
| GET | `/nps_static/nps-panel.js` | 公开静态资源 | 面板 webcomponent（侧边栏 / 悬浮窗共用） |
| GET | `/nps_static/nps-embed.js` | 公开静态资源 | 设备页「访问」悬浮窗 |

### 9.4 版本演进

| 版本 | 日期 | 变更 |
|---|---|---|
| 0.1.0 | 2026-08-22 | 初版：隧道/客户端开关 + 16 个 sensor |
| 1.0.0 | 2026-10-22 | 1) 首发可视化管理面板（隧道/客户端/域名映射的增删改启停）<br>2) 签名链接 + 会话 Cookie 鉴权与独立页面 `/nps/console`、面板密钥（加盐、整点轮换）<br>3) 侧边栏面板、设备页「访问」悬浮窗 `nps-embed.js`<br>4) 「管理面板访问」开关与面板访问密钥传感器<br>5) 传感器全部中文化并固定 entity_id，条目扩充到 19 个（含「所有实体」）<br>6) 选项流：轮询间隔可配（5~3600 秒） |
| 1.1.0 | 2026-10-22 | 1) 隧道类传感器新增 `tunnels` 明细属性（备注/端口/目标/客户端/运行状态/流量）<br>2) 面板增删隧道、客户端后自动补建/移除对应实体，无需重载集成<br>3) 删除后彻底清除实体与注册表条目，并自动清理历史残留的「不可用」实体<br>4) 适配新版 `device_registry` API，消除弃用警告<br>5) 修复计数类传感器显示 `0.0`、以及「所有实体」传感器在部分版本下添加失败 |

---

> 文档版本：2.0  
> 维护者：@chjspp520  （https://github.com/chjspp520/nps）  
