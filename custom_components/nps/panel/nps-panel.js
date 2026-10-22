/**
 * NPS 管理面板（panel_custom webcomponent）
 *
 * 通过 hass.connection 调用后端的 nps/action 命令完成：
 * 隧道（新建/编辑/启停/复制/删除）、客户端（新建/编辑/启停/删除）、
 * 域名映射（新建/编辑/启停/删除）。
 */

const TUNNEL_TYPE_LABELS = {
  tcp: "TCP",
  udp: "UDP",
  socks5: "SOCKS5",
  httpProxy: "HTTP 代理",
  secret: "秘密隧道",
  p2p: "P2P",
  file: "文件服务",
};

const SCHEME_LABELS = { all: "全部", http: "HTTP", https: "HTTPS" };

const STYLES = `
  :host { display: block; height: 100%; background: var(--primary-background-color, #fafafa); }
  * { box-sizing: border-box; }
  .panel {
    max-width: 1500px; margin: 0 auto; padding: 16px;
    color: var(--primary-text-color, #212121);
    font-family: var(--ha-font-family-body, "Roboto", "Helvetica Neue", Arial, sans-serif);
  }
  .head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
  .title { font-size: 20px; font-weight: 600; }
  .status { font-size: 12px; color: var(--secondary-text-color, #727272); }
  .bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
  .spacer { flex: 1; }
  .btn {
    border: 1px solid var(--divider-color, #e0e0e0);
    background: var(--card-background-color, #fff);
    color: var(--primary-text-color, #212121);
    border-radius: 8px; padding: 6px 12px; font-size: 13px; cursor: pointer;
    font-family: inherit; line-height: 1.4; white-space: nowrap;
  }
  .btn:hover { border-color: var(--primary-color, #03a9f4); color: var(--primary-color, #03a9f4); }
  .btn.primary { background: var(--primary-color, #03a9f4); border-color: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); }
  .btn.primary:hover { filter: brightness(0.92); color: var(--text-primary-color, #fff); }
  .btn.danger:hover { border-color: var(--error-color, #db4437); color: var(--error-color, #db4437); }
  .btn[disabled] { opacity: 0.5; cursor: not-allowed; }
  .btn.small { padding: 3px 8px; font-size: 12px; }
  .tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--divider-color, #e0e0e0); margin-bottom: 12px; flex-wrap: wrap; }
  .tab {
    background: none; border: none; border-bottom: 2px solid transparent;
    padding: 8px 14px; font-size: 14px; cursor: pointer; color: var(--secondary-text-color, #727272);
    font-family: inherit;
  }
  .tab.active { color: var(--primary-color, #03a9f4); border-bottom-color: var(--primary-color, #03a9f4); font-weight: 600; }
  .tab .count { font-size: 11px; opacity: 0.75; margin-left: 4px; }
  input[type="text"], input[type="search"], input[type="number"], input[type="password"], select, textarea {
    background: var(--card-background-color, #fff);
    color: var(--primary-text-color, #212121);
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: 8px; padding: 6px 10px; font-size: 13px; font-family: inherit;
    outline: none; min-width: 0;
  }
  input:focus, select:focus, textarea:focus { border-color: var(--primary-color, #03a9f4); }
  .card {
    background: var(--card-background-color, #fff);
    border-radius: var(--ha-card-border-radius, 12px);
    border: 1px solid var(--divider-color, #e0e0e0);
    overflow: hidden;
  }
  .scroll { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--divider-color, #eeeeee); white-space: nowrap; }
  th { font-size: 12px; font-weight: 600; color: var(--secondary-text-color, #727272); background: var(--secondary-background-color, #f5f5f5); position: sticky; top: 0; }
  tbody tr:hover { background: var(--secondary-background-color, #f5f5f5); }
  tbody tr:last-child td { border-bottom: none; }
  .mono { font-family: var(--ha-font-family-code, ui-monospace, Consolas, monospace); font-size: 12px; }
  .muted { color: var(--secondary-text-color, #727272); }
  .tag {
    display: inline-block; padding: 0 6px; border-radius: 6px; font-size: 11px;
    background: var(--secondary-background-color, #f0f0f0); color: var(--secondary-text-color, #616161);
    margin-left: 6px;
  }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; background: var(--disabled-text-color, #bdbdbd); }
  .dot.on { background: var(--success-color, #43a047); }
  .dot.off { background: var(--error-color, #db4437); }
  .switch { position: relative; display: inline-block; width: 38px; height: 22px; vertical-align: middle; }
  .switch input { opacity: 0; width: 0; height: 0; }
  .switch .track {
    position: absolute; inset: 0; background: var(--disabled-color, #cfcfcf);
    border-radius: 22px; transition: background 0.2s; cursor: pointer;
  }
  .switch .track::before {
    content: ""; position: absolute; width: 16px; height: 16px; left: 3px; top: 3px;
    background: #fff; border-radius: 50%; transition: transform 0.2s;
  }
  .switch input:checked + .track { background: var(--success-color, #43a047); }
  .switch input:checked + .track::before { transform: translateX(16px); }
  .ops { display: flex; gap: 6px; }
  .empty { padding: 40px 16px; text-align: center; color: var(--secondary-text-color, #727272); font-size: 13px; }
  .err { padding: 24px; color: var(--error-color, #db4437); font-size: 13px; }
  .toast {
    position: fixed; left: 50%; bottom: 28px; transform: translateX(-50%) translateY(20px);
    background: var(--primary-text-color, #333); color: var(--card-background-color, #fff);
    padding: 10px 18px; border-radius: 10px; font-size: 13px; opacity: 0;
    transition: opacity 0.2s, transform 0.2s; pointer-events: none; max-width: 80vw; z-index: 10;
  }
  .toast.show { opacity: 0.95; transform: translateX(-50%) translateY(0); }
  .toast.error { background: var(--error-color, #db4437); color: #fff; }
  .toast.success { background: var(--success-color, #43a047); color: #fff; }
  dialog {
    border: none; border-radius: 14px; padding: 0; width: min(560px, 92vw); max-height: 88vh;
    background: var(--card-background-color, #fff); color: var(--primary-text-color, #212121);
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.4); overflow: hidden;
    font-family: inherit;
  }
  dialog::backdrop { background: rgba(0, 0, 0, 0.5); }
  .dlg-head { display: flex; align-items: center; padding: 14px 16px; border-bottom: 1px solid var(--divider-color, #e0e0e0); }
  .dlg-title { font-size: 15px; font-weight: 600; flex: 1; }
  .dlg-close { background: none; border: none; cursor: pointer; color: var(--secondary-text-color, #727272); font-size: 18px; line-height: 1; padding: 4px; }
  .form { padding: 14px 16px; overflow-y: auto; max-height: 62vh; display: grid; gap: 12px; }
  .field { display: grid; gap: 4px; }
  .field > label { font-size: 12px; color: var(--secondary-text-color, #727272); }
  .field .hint { font-size: 11px; color: var(--secondary-text-color, #727272); }
  .field.check { grid-template-columns: auto 1fr; align-items: center; gap: 8px; }
  .field.check > label { font-size: 13px; color: var(--primary-text-color, #212121); }
  .dlg-foot {
    display: flex; justify-content: flex-end; gap: 8px; padding: 12px 16px;
    border-top: 1px solid var(--divider-color, #e0e0e0);
    position: sticky; bottom: -14px; margin: 14px -16px -14px;
    background: var(--card-background-color, #fff);
  }
  .hidden { display: none !important; }
  .busy { opacity: 0.6; pointer-events: none; }
  @media (max-width: 700px) {
    .panel { padding: 10px; }
    th, td { padding: 6px 8px; }
  }
`;

const h = (tag, props = {}, children = []) => {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === "value") el.value = value;
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return el;
};

const fmtBytes = (bytes) => {
  const value = Number(bytes) || 0;
  if (value <= 0) return "0 B";
  const units = ["TB", "GB", "MB", "KB"];
  const divisors = [1024 ** 4, 1024 ** 3, 1024 ** 2, 1024];
  for (let i = 0; i < units.length; i += 1) {
    if (Math.abs(value) >= divisors[i]) return `${(value / divisors[i]).toFixed(2)} ${units[i]}`;
  }
  return `${Math.round(value)} B`;
};

const targetStr = (row) => {
  const target = row && row.Target;
  if (target && typeof target === "object") {
    const str = (target.TargetStr || "").split("\n")[0].trim();
    if (str) return str;
  }
  return row && row.TargetAddr ? String(row.TargetAddr) : "";
};

const clientInfo = (row) => {
  const client = row && row.Client;
  if (!client || typeof client !== "object") return null;
  return client;
};

class NpsPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._httpMode = false;
    this._booted = false;
    this._data = null;
    this._tab = "tunnel";
    this._entryId = null;
    this._search = "";
    this._typeFilter = "all";
    this._busy = false;
    this._error = null;
    this._toastTimer = null;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._booted) {
      this._booted = true;
      this._buildShell();
      this._load();
    }
  }

  get hass() {
    return this._hass;
  }

  set entryId(value) {
    if (!value || value === this._entryId) return;
    this._entryId = value;
    if (this._booted) this._load();
  }

  /**
   * 独立页面模式：不依赖 HA 前端（没有 hass 对象），
   * 所有请求走 /nps/api/action + 本集成自己的会话 Cookie。
   */
  startHttp(entryId) {
    this._httpMode = true;
    if (entryId) this._entryId = entryId;
    if (!this._booted) {
      this._booted = true;
      this._buildShell();
    }
    this._load();
  }

  // ------------------------------------------------------------------
  // 骨架
  // ------------------------------------------------------------------
  _buildShell() {
    this._tabsEl = h("div", { class: "tabs" });
    this._barEl = h("div", { class: "bar" });
    this._bodyEl = h("div", { class: "content" });
    this._statusEl = h("div", { class: "status" });
    this._toastEl = h("div", { class: "toast" });

    const root = h("div", { class: "panel" }, [
      h("div", { class: "head" }, [h("div", { class: "title", text: "NPS 隧道管理" }), this._statusEl]),
      this._tabsEl,
      this._barEl,
      this._bodyEl,
    ]);

    this.shadowRoot.replaceChildren(h("style", { text: STYLES }), root, this._toastEl);
  }

  _toast(message, kind = "") {
    this._toastEl.textContent = message;
    this._toastEl.className = `toast show ${kind}`.trim();
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => {
      this._toastEl.className = "toast";
    }, 3200);
  }

  _setBusy(busy) {
    this._busy = busy;
    const panel = this.shadowRoot.querySelector(".panel");
    if (panel) panel.classList.toggle("busy", busy);
    if (busy) return;
    this._renderBar();
  }

  // ------------------------------------------------------------------
  // 数据
  // ------------------------------------------------------------------
  async _call(action, data = {}) {
    if (this._httpMode) {
      const response = await fetch("/nps/api/action", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action,
          entry_id: this._entryId || null,
          data,
        }),
      });
      let payload = null;
      try {
        payload = await response.json();
      } catch (err) {
        payload = null;
      }
      if (!response.ok || !payload || payload.success === false) {
        const error = new Error(
          (payload && payload.message) || `HTTP ${response.status}`
        );
        error.code = payload && payload.code;
        throw error;
      }
      return payload;
    }

    return this._hass.connection.sendMessagePromise({
      type: "nps/action",
      action,
      entry_id: this._entryId || undefined,
      data,
    });
  }

  _applySnapshot(snapshot) {
    this._data = snapshot;
    this._error = null;
    if (!this._entryId && snapshot.entry_id) this._entryId = snapshot.entry_id;
    this._statusEl.textContent = this._statusText();
    this._render();
  }

  _statusText() {
    const dashboard = (this._data && this._data.dashboard) || {};
    const parts = [];
    if (dashboard.tunnelTotal !== undefined) parts.push(`${dashboard.tunnelTotal} 条隧道`);
    if (dashboard.clientCount !== undefined) {
      parts.push(`${dashboard.clientOnlineCount || 0}/${dashboard.clientCount} 客户端在线`);
    }
    if (dashboard.hostCount !== undefined) parts.push(`${dashboard.hostCount} 个域名映射`);
    return parts.join(" · ");
  }

  async _load() {
    this._setBusy(true);
    try {
      this._applySnapshot(await this._call("list"));
    } catch (err) {
      this._error = err && (err.message || err.code || String(err));
      this._render();
      this._toast(`加载失败：${this._error}`, "error");
    } finally {
      this._setBusy(false);
    }
  }

  async _act(action, data, okText) {
    this._setBusy(true);
    try {
      this._applySnapshot(await this._call(action, data));
      this._toast(okText || "操作成功", "success");
      return true;
    } catch (err) {
      this._toast(`操作失败：${err && (err.message || err.code || err)}`, "error");
      return false;
    } finally {
      this._setBusy(false);
      this._renderBar();
    }
  }

  // ------------------------------------------------------------------
  // 渲染
  // ------------------------------------------------------------------
  _render() {
    this._renderTabs();
    this._renderBar();
    this._renderBody();
  }

  _rows() {
    const data = this._data || {};
    return {
      tunnels: data.tunnels || [],
      clients: data.clients || [],
      hosts: data.hosts || [],
    };
  }

  _renderTabs() {
    const { tunnels, clients, hosts } = this._rows();
    const defs = [
      ["tunnel", "隧道", tunnels.length],
      ["client", "客户端", clients.length],
      ["host", "域名映射", hosts.length],
    ];
    this._tabsEl.replaceChildren(
      ...defs.map(([key, label, count]) =>
        h(
          "button",
          {
            class: `tab${this._tab === key ? " active" : ""}`,
            onclick: () => {
              if (this._tab === key) return;
              this._tab = key;
              this._search = "";
              this._render();
            },
          },
          [label, h("span", { class: "count", text: String(count) })]
        )
      )
    );
  }

  _renderBar() {
    // 面板访问被禁用等加载失败场景：只留「重新加载」，避免点了必然报错的操作
    if (this._error) {
      this._barEl.replaceChildren(
        h("div", { class: "spacer" }),
        h("button", { class: "btn", text: "重新加载", onclick: () => this._load() })
      );
      return;
    }

    const entries = (this._data && this._data.entries) || [];
    const children = [];

    if (entries.length > 1) {
      const select = h("select", {
        title: "选择 NPS 实例",
        onchange: (event) => {
          this._entryId = event.target.value;
          this._load();
        },
      });
      for (const entry of entries) {
        select.append(h("option", { value: entry.entry_id, text: entry.title }));
      }
      select.value = this._entryId || (entries[0] && entries[0].entry_id) || "";
      children.push(select);
    }

    children.push(
      h("input", {
        type: "search",
        placeholder: "搜索备注 / 目标 / ID",
        value: this._search,
        oninput: (event) => {
          this._search = event.target.value;
          this._renderBody();
        },
      })
    );

    if (this._tab === "tunnel") {
      const types = (this._data && this._data.tunnel_types) || Object.keys(TUNNEL_TYPE_LABELS);
      const select = h("select", {
        title: "按类型筛选",
        onchange: (event) => {
          this._typeFilter = event.target.value;
          this._renderBody();
        },
      });
      select.append(h("option", { value: "all", text: "全部类型" }));
      for (const type of types) {
        select.append(h("option", { value: type, text: TUNNEL_TYPE_LABELS[type] || type }));
      }
      select.value = this._typeFilter;
      children.push(select);
    }

    children.push(h("div", { class: "spacer" }));

    const labels = { tunnel: "新建隧道", client: "新建客户端", host: "新建域名映射" };
    children.push(
      h("button", {
        class: "btn primary",
        text: labels[this._tab],
        onclick: () => this._openCreate(),
      }),
      h("button", {
        class: "btn",
        text: "刷新",
        onclick: () => this._load(),
      })
    );

    this._barEl.replaceChildren(...children);
  }

  _renderBody() {
    if (this._error) {
      this._bodyEl.replaceChildren(
        h("div", { class: "card" }, [
          h("div", { class: "err", text: `加载失败：${this._error}` }),
          h("div", { class: "empty" }, [
            h("button", { class: "btn", text: "重新加载", onclick: () => this._load() }),
          ]),
        ])
      );
      return;
    }
    if (!this._data) {
      this._bodyEl.replaceChildren(h("div", { class: "card" }, [h("div", { class: "empty", text: "加载中…" })]));
      return;
    }
    if (this._tab === "client") this._bodyEl.replaceChildren(this._renderClients());
    else if (this._tab === "host") this._bodyEl.replaceChildren(this._renderHosts());
    else this._bodyEl.replaceChildren(this._renderTunnels());
  }

  _matches(...values) {
    const keyword = this._search.trim().toLowerCase();
    if (!keyword) return true;
    return values.some((value) => String(value === undefined || value === null ? "" : value).toLowerCase().includes(keyword));
  }

  _switch(checked, handler, title) {
    const input = h("input", { type: "checkbox", title: title || "" });
    input.checked = !!checked;
    input.addEventListener("change", (event) => handler(event.target.checked));
    return h("label", { class: "switch" }, [input, h("span", { class: "track" })]);
  }

  _table(headers, rows, emptyText) {
    if (!rows.length) {
      return h("div", { class: "card" }, [h("div", { class: "empty", text: emptyText })]);
    }
    return h("div", { class: "card" }, [
      h("div", { class: "scroll" }, [
        h("table", {}, [
          h("thead", {}, [h("tr", {}, headers.map((text) => h("th", { text })))]),
          h("tbody", {}, rows),
        ]),
      ]),
    ]);
  }

  _renderTunnels() {
    const tunnels = this._rows().tunnels.filter((tunnel) => {
      const mode = tunnel.Mode || tunnel.Type || "";
      if (this._typeFilter !== "all" && mode !== this._typeFilter) return false;
      const client = clientInfo(tunnel);
      return this._matches(tunnel.Remark, tunnel.Id, mode, targetStr(tunnel), client && client.Id, client && client.Addr);
    });

    const rows = tunnels.map((tunnel) => {
      const mode = tunnel.Mode || tunnel.Type || "";
      const client = clientInfo(tunnel);
      const running = !!tunnel.RunStatus;
      const flow = tunnel.Flow || {};
      const remarkChildren = [tunnel.Remark || "—"];
      if (tunnel.Password) remarkChildren.push(h("span", { class: "tag", text: "密码" }));
      if (tunnel.LocalPath) remarkChildren.push(h("span", { class: "tag", text: "文件" }));
      return h("tr", {}, [
        h("td", {}, [
          this._switch(running, (checked) =>
            this._act(checked ? "tunnel_start" : "tunnel_stop", { id: tunnel.Id },
              `${checked ? "已启动" : "已停止"}隧道 #${tunnel.Id}`),
            running ? "运行中，点击停止" : "已停止，点击启动"),
        ]),
        h("td", { class: "mono", text: String(tunnel.Id) }),
        h("td", {}, [
          h("span", { class: `dot ${running ? "on" : "off"}` }),
          TUNNEL_TYPE_LABELS[mode] || mode || "—",
        ]),
        h("td", {}, remarkChildren),
        h("td", {}, [
          client
            ? `#${client.Id}${client.Remark ? ` ${client.Remark}` : ""}`
            : "—",
          client && client.IsConnect ? h("span", { class: "tag", text: "在线" }) : null,
        ]),
        h("td", { class: "mono", text: tunnel.Port ? String(tunnel.Port) : "自动" }),
        h("td", { class: "mono", text: targetStr(tunnel) || "—" }),
        h("td", { class: "mono muted", text: `${fmtBytes(flow.InletFlow)} / ${fmtBytes(flow.ExportFlow)}` }),
        h("td", {}, [
          h("div", { class: "ops" }, [
            h("button", { class: "btn small", text: "编辑", onclick: () => this._openTunnelForm(tunnel) }),
            h("button", {
              class: "btn small",
              text: "复制",
              onclick: () => this._act("tunnel_copy", { id: tunnel.Id }, `已复制隧道 #${tunnel.Id}`),
            }),
            h("button", {
              class: "btn small danger",
              text: "删除",
              onclick: () => {
                if (!window.confirm(`确定删除隧道 #${tunnel.Id} ${tunnel.Remark || ""}？`)) return;
                this._act("tunnel_del", { id: tunnel.Id }, `已删除隧道 #${tunnel.Id}`);
              },
            }),
          ]),
        ]),
      ]);
    });

    return this._table(
      ["运行", "ID", "类型", "备注", "客户端", "服务端端口", "内网目标", "流量(入/出)", "操作"],
      rows,
      "暂无隧道，点击右上角「新建隧道」创建"
    );
  }

  _renderClients() {
    const clients = this._rows().clients.filter((client) =>
      this._matches(client.Remark, client.Id, client.Addr, client.VerifyKey, client.Version)
    );

    const rows = clients.map((client) => {
      const online = !!client.IsConnect;
      const flow = client.Flow || {};
      const rate = client.Rate || {};
      return h("tr", {}, [
        h("td", {}, [
          this._switch(online, (checked) =>
            this._act(checked ? "client_on" : "client_off", { id: client.Id },
              `客户端 #${client.Id} 已${checked ? "启用" : "禁用"}`),
            online ? "在线，点击禁用" : "离线，点击启用"),
        ]),
        h("td", { class: "mono", text: String(client.Id) }),
        h("td", {}, [client.Remark || "—"]),
        h("td", {}, [
          h("span", { class: `dot ${online ? "on" : "off"}` }),
          client.Addr || "—",
        ]),
        h("td", { class: "mono muted", text: client.Version || "—" }),
        h("td", { class: "mono", text: String(client.NowConn || 0) }),
        h("td", { class: "mono muted", text: `${fmtBytes(flow.InletFlow)} / ${fmtBytes(flow.ExportFlow)}` }),
        h("td", { class: "mono muted", text: rate.NowRate ? `${(rate.NowRate / 1024).toFixed(1)} KB/s` : "—" }),
        h("td", {}, [
          h("div", { class: "ops" }, [
            h("button", { class: "btn small", text: "编辑", onclick: () => this._openClientForm(client) }),
            h("button", {
              class: "btn small danger",
              text: "删除",
              onclick: () => {
                if (!window.confirm(`确定删除客户端 #${client.Id} ${client.Remark || ""}？`)) return;
                this._act("client_del", { id: client.Id }, `已删除客户端 #${client.Id}`);
              },
            }),
          ]),
        ]),
      ]);
    });

    return this._table(
      ["连接", "ID", "备注", "地址", "版本", "连接数", "流量(入/出)", "实时速率", "操作"],
      rows,
      "暂无客户端，点击右上角「新建客户端」创建"
    );
  }

  _renderHosts() {
    const hosts = this._rows().hosts.filter((host) => {
      const client = clientInfo(host);
      return this._matches(host.Host, host.Remark, host.Id, targetStr(host), client && client.Id);
    });

    const rows = hosts.map((host) => {
      const client = clientInfo(host);
      const active = host.Status === undefined || host.Status === null ? true : !!host.Status;
      return h("tr", {}, [
        h("td", {}, [
          this._switch(active, (checked) =>
            this._act(checked ? "host_start" : "host_stop", { id: host.Id },
              `域名映射 #${host.Id} 已${checked ? "启用" : "停用"}`),
            active ? "已启用，点击停用" : "已停用，点击启用"),
        ]),
        h("td", { class: "mono", text: String(host.Id) }),
        h("td", {}, [
          h("span", { class: `dot ${active ? "on" : "off"}` }),
          host.Host || "—",
          host.Location ? h("span", { class: "tag", text: host.Location }) : null,
        ]),
        h("td", { class: "mono", text: targetStr(host) || "—" }),
        h("td", {}, [host.Remark || "—"]),
        h("td", {}, [client ? `#${client.Id}${client.Remark ? ` ${client.Remark}` : ""}` : "—"]),
        h("td", { text: SCHEME_LABELS[host.Scheme] || host.Scheme || "—" }),
        h("td", {}, [
          h("div", { class: "ops" }, [
            h("button", { class: "btn small", text: "编辑", onclick: () => this._openHostForm(host) }),
            h("button", {
              class: "btn small danger",
              text: "删除",
              onclick: () => {
                if (!window.confirm(`确定删除域名映射 #${host.Id} ${host.Host || ""}？`)) return;
                this._act("host_del", { id: host.Id }, `已删除域名映射 #${host.Id}`);
              },
            }),
          ]),
        ]),
      ]);
    });

    return this._table(
      ["状态", "ID", "域名", "内网目标", "备注", "客户端", "协议", "操作"],
      rows,
      "暂无域名映射，点击右上角「新建域名映射」创建"
    );
  }

  // ------------------------------------------------------------------
  // 表单
  // ------------------------------------------------------------------
  _openCreate() {
    if (this._tab === "client") this._openClientForm(null);
    else if (this._tab === "host") this._openHostForm(null);
    else this._openTunnelForm(null);
  }

  _clientOptions(currentId) {
    const clients = this._rows().clients;
    const options = clients.map((client) => [
      String(client.Id),
      `#${client.Id} ${client.Remark || ""} ${client.IsConnect ? "（在线）" : "（离线）"}`.trim(),
    ]);
    // 当前值不在列表里（例如客户端列表获取失败）时补一个选项，避免编辑时被改成别的客户端
    const current = currentId === undefined || currentId === null ? "" : String(currentId);
    if (current && !options.some(([value]) => value === current)) {
      options.unshift([current, `#${current}`]);
    }
    return options;
  }

  _openTunnelForm(tunnel) {
    const isEdit = !!tunnel;
    const mode = tunnel ? tunnel.Mode || tunnel.Type || "tcp" : "tcp";
    const clientId = tunnel && clientInfo(tunnel) ? String(clientInfo(tunnel).Id) : (this._rows().clients[0] ? String(this._rows().clients[0].Id) : "0");
    this._openForm({
      title: isEdit ? `编辑隧道 #${tunnel.Id}` : "新建隧道",
      fields: [
        { key: "type", label: "隧道类型", type: "select", value: mode, options: Object.entries(TUNNEL_TYPE_LABELS) },
        { key: "client_id", label: "所属客户端", type: "select", value: clientId, options: this._clientOptions(clientId) },
        { key: "remark", label: "备注", type: "text", value: tunnel ? tunnel.Remark || "" : "", placeholder: "例如 群晖 NAS" },
        {
          key: "port",
          label: "服务端端口",
          type: "number",
          numeric: true,
          value: tunnel ? tunnel.Port || 0 : 0,
          hint: "填 0 表示由服务端自动分配",
        },
        { key: "server_ip", label: "服务端绑定 IP", type: "text", value: tunnel && tunnel.ServerIp ? tunnel.ServerIp : "", placeholder: "留空表示监听全部地址" },
        {
          key: "target",
          label: "内网目标（IP:端口）",
          type: "text",
          value: tunnel ? targetStr(tunnel) : "",
          placeholder: "127.0.0.1:8080",
        },
        {
          key: "password",
          label: "隧道密码",
          type: "text",
          value: tunnel && tunnel.Password ? tunnel.Password : "",
          dependsOn: { key: "type", values: ["secret"] },
          hint: "仅「秘密隧道」需要",
        },
        {
          key: "local_path",
          label: "本地文件路径",
          type: "text",
          value: tunnel && tunnel.LocalPath ? tunnel.LocalPath : "",
          dependsOn: { key: "type", values: ["file"] },
          hint: "仅「文件服务」需要",
        },
        {
          key: "strip_pre",
          label: "去除 URL 前缀",
          type: "text",
          value: tunnel && tunnel.StripPre ? tunnel.StripPre : "",
          dependsOn: { key: "type", values: ["httpProxy"] },
        },
        { key: "local_proxy", label: "转发到 NPS 服务器本地", type: "checkbox", value: tunnel ? !!tunnel.LocalProxy : false },
      ],
      submitText: isEdit ? "保存" : "创建",
      onSubmit: (values) => {
        const payload = { ...values };
        payload.client_id = Number(values.client_id) || 0;
        payload.port = Number(values.port) || 0;
        if (isEdit) {
          payload.id = tunnel.Id;
          return this._act("tunnel_edit", payload, `隧道 #${tunnel.Id} 已更新`);
        }
        return this._act("tunnel_add", payload, "隧道已创建");
      },
    });
  }

  _openClientForm(client) {
    const isEdit = !!client;
    this._openForm({
      title: isEdit ? `编辑客户端 #${client.Id}` : "新建客户端",
      fields: [
        { key: "remark", label: "备注", type: "text", value: client ? client.Remark || "" : "" },
        { key: "vkey", label: "唯一验证密钥", type: "text", value: client ? client.VerifyKey || "" : "", hint: "留空由服务端自动生成" },
        { key: "u", label: "Basic 认证用户名", type: "text", value: "", hint: isEdit ? "留空表示不修改" : "" },
        { key: "p", label: "Basic 认证密码", type: "text", value: "", hint: isEdit ? "留空表示不修改" : "" },
        { key: "compress", label: "启用压缩", type: "checkbox", value: true },
        { key: "crypt", label: "启用加密", type: "checkbox", value: true },
        { key: "config_conn_allow", label: "允许配置文件模式连接", type: "checkbox", value: true },
        { key: "rate_limit", label: "带宽限制 (KB/s)", type: "text", value: client && client.RateLimit ? String(client.RateLimit) : "", hint: "留空表示不限制" },
        { key: "flow_limit", label: "流量限制 (M)", type: "text", value: client ? String((client.Flow && client.Flow.FlowLimit) || client.FlowLimit || "") : "", hint: "留空表示不限制" },
        { key: "max_conn", label: "最大连接数", type: "text", value: client && client.MaxConn ? String(client.MaxConn) : "" },
        { key: "max_tunnel", label: "最大隧道数", type: "text", value: client && client.MaxTunnelNum ? String(client.MaxTunnelNum) : "" },
        { key: "web_username", label: "Web 登录用户名", type: "text", value: client && client.WebUserName ? client.WebUserName : "" },
        { key: "web_password", label: "Web 登录密码", type: "text", value: "" },
        { key: "ipwhite", label: "启用 IP 白名单", type: "checkbox", value: client ? !!client.IpWhite : false },
        { key: "ipwhitepass", label: "白名单授权密码", type: "text", value: "" },
        { key: "ipwhitelist", label: "白名单 IP 列表", type: "textarea", value: "", hint: "每行一个 IP" },
        { key: "blackiplist", label: "黑名单 IP 列表", type: "textarea", value: "", hint: "每行一个 IP" },
        { key: "expire_time", label: "到期时间", type: "text", value: client && client.ExpireTime ? client.ExpireTime : "", placeholder: "如 2027-01-01 00:00:00，留空永不过期" },
      ],
      submitText: isEdit ? "保存" : "创建",
      onSubmit: (values) => {
        if (isEdit) {
          values.id = client.Id;
          return this._act("client_edit", values, `客户端 #${client.Id} 已更新`);
        }
        return this._act("client_add", values, "客户端已创建");
      },
    });
  }

  _openHostForm(host) {
    const isEdit = !!host;
    const clientId = host && clientInfo(host) ? String(clientInfo(host).Id) : (this._rows().clients[0] ? String(this._rows().clients[0].Id) : "0");
    this._openForm({
      title: isEdit ? `编辑域名映射 #${host.Id}` : "新建域名映射",
      fields: [
        { key: "client_id", label: "所属客户端", type: "select", value: clientId, options: this._clientOptions(clientId) },
        { key: "host", label: "域名", type: "text", value: host ? host.Host || "" : "", placeholder: "nas.example.com" },
        { key: "scheme", label: "协议", type: "select", value: host ? host.Scheme || "all" : "all", options: Object.entries(SCHEME_LABELS) },
        { key: "location", label: "URL 路由", type: "text", value: host && host.Location ? host.Location : "", placeholder: "留空表示不限制" },
        { key: "target", label: "内网目标（IP:端口）", type: "text", value: host ? targetStr(host) : "", placeholder: "127.0.0.1:5000" },
        { key: "remark", label: "备注", type: "text", value: host ? host.Remark || "" : "" },
        { key: "hostchange", label: "改写请求 Host", type: "text", value: host && host.HostChange ? host.HostChange : "", hint: "可留空" },
        { key: "header", label: "自定义请求头", type: "textarea", value: host && host.Header ? host.Header : "", hint: "每行一个，如 X-Auth: 1" },
        { key: "auto_https", label: "自动申请 HTTPS 证书", type: "checkbox", value: host ? !!host.AutoHttps : false },
        { key: "key_file_path", label: "HTTPS 私钥", type: "textarea", value: "", hint: "可填文件路径或私钥内容" },
        { key: "cert_file_path", label: "HTTPS 证书", type: "textarea", value: "", hint: "可填文件路径或证书内容" },
        { key: "local_proxy", label: "转发到 NPS 服务器本地", type: "checkbox", value: host ? !!host.LocalProxy : false },
      ],
      submitText: isEdit ? "保存" : "创建",
      onSubmit: (values) => {
        values.client_id = Number(values.client_id) || 0;
        if (isEdit) {
          values.id = host.Id;
          return this._act("host_edit", values, `域名映射 #${host.Id} 已更新`);
        }
        return this._act("host_add", values, "域名映射已创建");
      },
    });
  }

  _openForm({ title, fields, submitText, onSubmit }) {
    const inputs = new Map();
    const wraps = [];
    const form = h("form", { class: "form" });

    const refreshVisibility = () => {
      for (const item of wraps) {
        if (!item.field.dependsOn) continue;
        const source = inputs.get(item.field.dependsOn.key);
        const current = source ? source.value : "";
        item.wrap.classList.toggle("hidden", !item.field.dependsOn.values.includes(current));
      }
    };

    for (const field of fields) {
      let input;
      if (field.type === "select") {
        input = h("select", { onchange: refreshVisibility });
        const options = field.options && field.options.length ? field.options : [["", "—"]];
        for (const [value, label] of options) input.append(h("option", { value, text: String(label) }));
        input.value = field.value === undefined || field.value === null ? "" : String(field.value);
        if (!input.value && options.length) input.value = options[0][0];
      } else if (field.type === "checkbox") {
        input = h("input", { type: "checkbox" });
        input.checked = !!field.value;
      } else if (field.type === "textarea") {
        input = h("textarea", { rows: 3 });
        input.value = field.value || "";
      } else {
        input = h("input", {
          type: field.type === "number" ? "number" : "text",
          placeholder: field.placeholder || "",
        });
        input.value = field.value === undefined || field.value === null ? "" : String(field.value);
      }
      inputs.set(field.key, input);

      if (field.type === "checkbox") {
        const wrap = h("div", { class: "field check" }, [input, h("label", { text: field.label })]);
        wraps.push({ field, wrap });
        form.append(wrap);
      } else {
        const wrap = h("div", { class: "field" }, [h("label", { text: field.label }), input]);
        if (field.hint) wrap.append(h("div", { class: "hint", text: field.hint }));
        wraps.push({ field, wrap });
        form.append(wrap);
      }
    }

    const dialog = h("dialog", {});
    const close = () => {
      dialog.close();
      dialog.remove();
    };

    const submitButton = h("button", { class: "btn primary", type: "submit", text: submitText || "保存" });
    const foot = h("div", { class: "dlg-foot" }, [
      h("button", { class: "btn", type: "button", text: "取消", onclick: close }),
      submitButton,
    ]);

    form.append(foot);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const values = {};
      for (const [key, input] of inputs) {
        values[key] = input.type === "checkbox" ? input.checked : input.value;
      }
      submitButton.disabled = true;
      try {
        const ok = await onSubmit(values);
        if (ok) close();
      } finally {
        submitButton.disabled = false;
      }
    });

    dialog.append(
      h("div", { class: "dlg-head" }, [
        h("div", { class: "dlg-title", text: title }),
        h("button", { class: "dlg-close", type: "button", text: "✕", onclick: close }),
      ]),
      form
    );

    dialog.addEventListener("cancel", () => dialog.remove());
    this.shadowRoot.append(dialog);
    refreshVisibility();
    dialog.showModal();
  }
}

// ----------------------------------------------------------------------
// Lovelace 卡片：以悬浮窗方式打开管理面板
// ----------------------------------------------------------------------
const CARD_STYLES = `
  :host { display: block; }
  .card {
    display: flex; align-items: center; gap: 12px; cursor: pointer;
    padding: 14px 16px;
    background: var(--ha-card-background, var(--card-background-color, #fff));
    border: 1px solid var(--ha-card-border-color, var(--divider-color, #e0e0e0));
    border-radius: var(--ha-card-border-radius, 12px);
    color: var(--primary-text-color, #212121);
    font-family: var(--ha-font-family-body, "Roboto", Arial, sans-serif);
    transition: box-shadow 0.2s;
  }
  .card:hover { box-shadow: 0 2px 10px rgba(0, 0, 0, 0.18); }
  .card:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: 2px; }
  .card .ico { color: var(--primary-color, #03a9f4); --mdc-icon-size: 26px; }
  .card .text { flex: 1; min-width: 0; }
  .card .title { font-size: 15px; font-weight: 600; }
  .card .sub { font-size: 12px; color: var(--secondary-text-color, #727272); margin-top: 2px; }
  .card .chevron { color: var(--secondary-text-color, #727272); }
  .inline {
    background: var(--ha-card-background, var(--card-background-color, #fff));
    border: 1px solid var(--ha-card-border-color, var(--divider-color, #e0e0e0));
    border-radius: var(--ha-card-border-radius, 12px);
    overflow: hidden;
    position: relative;
  }
  .frame { border: 0; width: 100%; height: 100%; display: block; }
  .boot { padding: 20px; font-size: 13px; color: var(--secondary-text-color, #727272); }
  .err { padding: 20px; font-size: 13px; color: var(--error-color, #db4437); }
`;

const MODAL_STYLES = `
  :host { display: block; }
  .overlay {
    position: fixed; inset: 0; z-index: 10000;
    display: flex; align-items: center; justify-content: center;
    padding: 16px; background: rgba(0, 0, 0, 0.55);
    backdrop-filter: blur(3px);
    animation: fade 0.15s ease-out;
  }
  .window {
    width: min(1280px, 96vw); height: min(90vh, 1100px);
    display: flex; flex-direction: column; overflow: hidden;
    background: var(--primary-background-color, #fafafa);
    color: var(--primary-text-color, #212121);
    border-radius: 16px; box-shadow: 0 18px 50px rgba(0, 0, 0, 0.5);
    font-family: var(--ha-font-family-body, "Roboto", Arial, sans-serif);
    animation: rise 0.18s ease-out;
  }
  .head {
    display: flex; align-items: center; gap: 10px; padding: 10px 14px;
    background: var(--card-background-color, #fff);
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
  }
  .head .title { flex: 1; font-size: 15px; font-weight: 600; }
  .head .ico { color: var(--primary-color, #03a9f4); --mdc-icon-size: 24px; }
  .head .close {
    border: none; background: none; cursor: pointer; font-size: 18px; line-height: 1;
    padding: 6px 8px; border-radius: 8px; color: var(--secondary-text-color, #727272);
  }
  .head .close:hover { background: var(--secondary-background-color, #f0f0f0); }
  .body { flex: 1; min-height: 0; overflow: hidden; display: flex; flex-direction: column; }
  .frame { border: 0; width: 100%; height: 100%; display: block; flex: 1; }
  .boot { padding: 20px; font-size: 13px; color: var(--secondary-text-color, #727272); }
  .err { padding: 20px; font-size: 13px; color: var(--error-color, #db4437); }
  @keyframes fade { from { opacity: 0; } to { opacity: 1; } }
  @keyframes rise { from { transform: translateY(12px); opacity: 0.6; } to { transform: none; opacity: 1; } }
  @media (max-width: 700px) {
    .overlay { padding: 0; }
    .window { width: 100vw; height: 100vh; border-radius: 0; }
  }
`;

class NpsPanelCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = null;
    this._panel = null;
    this._modalHost = null;
    this._keyHandler = null;
    this._prevOverflow = undefined;
  }

  static getStubConfig() {
    return { title: "NPS 管理", mode: "button" };
  }

  setConfig(config) {
    this._config = {
      mode: "button",
      title: "NPS 管理",
      icon: "mdi:tunnel",
      height: "72vh",
      ...(config || {}),
    };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
  }

  get hass() {
    return this._hass;
  }

  getCardSize() {
    return this._config && this._config.mode === "inline" ? 10 : 1;
  }

  disconnectedCallback() {
    this._closeModal();
  }

  _render() {
    if (!this._config) return;
    if (this._config.mode === "inline") {
      const holder = h("div", {
        class: "inline",
        style: `height:${this._config.height || "72vh"}`,
      });
      this.shadowRoot.replaceChildren(h("style", { text: CARD_STYLES }), holder);
      this._mountIframe(holder);
      return;
    }

    this.shadowRoot.replaceChildren(h("style", { text: CARD_STYLES }), this._renderButton());
  }

  /** 向后台申请带 authSig 的面板地址（签名链接，24 小时有效） */
  async _consoleUrl() {
    const result = await this._hass.connection.sendMessagePromise({
      type: "nps/action",
      action: "console_url",
      entry_id: this._config.entry_id || undefined,
    });
    if (!result || !result.url) {
      throw new Error("未获取到面板地址");
    }
    return result.url;
  }

  /** 把签名面板页以 iframe 方式挂到容器里（同源、自带鉴权） */
  async _mountIframe(container) {
    container.replaceChildren(h("div", { class: "boot", text: "正在打开 NPS 管理面板…" }));
    try {
      const url = await this._consoleUrl();
      if (!container.isConnected) return;
      container.replaceChildren(
        h("iframe", {
          class: "frame",
          src: url,
          title: this._config.title || "NPS 管理",
          allow: "clipboard-write",
        })
      );
    } catch (err) {
      container.replaceChildren(
        h("div", {
          class: "err",
          text: `打开失败：${(err && (err.message || err.code)) || err}`,
        })
      );
    }
  }

  _renderButton() {
    const open = () => this._openModal();
    return h(
      "div",
      {
        class: "card",
        role: "button",
        tabindex: "0",
        onclick: open,
        onkeydown: (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            open();
          }
        },
      },
      [
        h("ha-icon", { class: "ico", icon: this._config.icon || "mdi:tunnel" }),
        h("div", { class: "text" }, [
          h("div", { class: "title", text: this._config.title || "NPS 管理" }),
          h("div", { class: "sub", text: "点击在本页弹出管理面板" }),
        ]),
        h("ha-icon", { class: "chevron", icon: "mdi:chevron-right" }),
      ]
    );
  }

  _openModal() {
    if (this._modalHost || !this._hass) return;

    const body = h("div", { class: "body" });
    const overlay = h("div", {
      class: "overlay",
      onclick: (event) => {
        if (event.target === overlay) this._closeModal();
      },
    }, [
      h("div", { class: "window" }, [
        h("div", { class: "head" }, [
          h("ha-icon", { class: "ico", icon: this._config.icon || "mdi:tunnel" }),
          h("div", { class: "title", text: this._config.title || "NPS 管理" }),
          h("button", { class: "close", type: "button", text: "✕", title: "关闭", onclick: () => this._closeModal() }),
        ]),
        body,
      ]),
    ]);

    const host = document.createElement("div");
    const root = host.attachShadow({ mode: "open" });
    root.append(h("style", { text: MODAL_STYLES }), overlay);
    document.body.append(host);

    this._keyHandler = (event) => {
      if (event.key === "Escape") this._closeModal();
    };
    document.addEventListener("keydown", this._keyHandler);
    this._modalHost = host;
    // 悬浮窗打开时锁住背景滚动，关闭时还原
    this._prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    this._mountIframe(body);
  }

  _closeModal() {
    if (this._keyHandler) {
      document.removeEventListener("keydown", this._keyHandler);
      this._keyHandler = null;
    }
    if (this._modalHost) {
      this._modalHost.remove();
      this._modalHost = null;
    }
    if (this._prevOverflow !== undefined) {
      document.body.style.overflow = this._prevOverflow || "";
      this._prevOverflow = undefined;
    }
  }
}

if (!customElements.get("nps-panel")) {
  customElements.define("nps-panel", NpsPanel);
}
if (!customElements.get("nps-panel-card")) {
  customElements.define("nps-panel-card", NpsPanelCard);
}

// 让卡片出现在仪表盘的卡片选择器里
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "nps-panel-card")) {
  window.customCards.push({
    type: "nps-panel-card",
    name: "NPS 管理面板",
    description: "点击后在当前页面以悬浮窗打开 NPS 隧道管理界面",
    preview: false,
  });
}
