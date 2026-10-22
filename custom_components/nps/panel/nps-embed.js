/*!
 * NPS 隧道管理 —— Home Assistant 前端悬浮窗模块
 *
 * 通过 homeassistant.components.frontend.add_extra_js_url 注入到 HA 前端。
 *
 * 作用：设备页「访问」（configuration_url = 带 authSig 的 /nps/console）本来是
 * 整页跳转/新标签页打开，这里拦截点击，改为在 HA 界面内弹出**可拖动、可缩放**
 * 的 iframe 悬浮窗，窗口内的页面与独立页面完全一致（同一份 nps-panel.js，
 * startHttp 模式 + 本集成自己的会话 Cookie）。
 *
 * 纯原生 JS + Shadow DOM，不依赖 HA 前端内部实现，升级风险最小。
 */
(() => {
  "use strict";

  const CONSOLE_PATH = "/nps/console";
  const HOST_ID = "nps-float-host";
  const TITLE = "NPS 隧道管理";
  const WIDTH = "min(1180px, 95vw)";
  const HEIGHT = "min(860px, 90vh)";

  const CSS = `
    .nps-window {
      position: fixed;
      z-index: 1;
      display: none;
      flex-direction: column;
      min-width: 360px;
      min-height: 260px;
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color, #212121);
      border: 1px solid var(--divider-color, #e0e0e0);
      border-radius: 14px;
      box-shadow: 0 18px 56px rgba(0, 0, 0, .45);
      overflow: hidden;
      resize: both;
      pointer-events: auto;
    }
    .nps-window.show { display: flex; }
    .nps-window.nps-flash { animation: nps-pop .32s ease; }
    @keyframes nps-pop {
      0% { transform: scale(.97); }
      60% { transform: scale(1.012); }
      100% { transform: scale(1); }
    }
    .nps-head {
      display: flex;
      align-items: center;
      gap: 8px;
      height: 44px;
      padding: 0 10px;
      background: var(--secondary-background-color, #f5f5f5);
      border-bottom: 1px solid var(--divider-color, #e0e0e0);
      cursor: move;
      touch-action: none;
      flex: 0 0 auto;
    }
    .nps-ico { color: var(--primary-color, #03a9f4); font-size: 18px; line-height: 1; }
    .nps-title {
      font-size: 13.5px;
      font-weight: 600;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      font-family: var(--ha-font-family-body, "Roboto", Arial, sans-serif);
    }
    .nps-spacer { flex: 1; }
    .nps-btn {
      appearance: none;
      border: 1px solid var(--divider-color, #e0e0e0);
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color, #212121);
      border-radius: 8px;
      width: 30px;
      height: 28px;
      font-size: 15px;
      line-height: 1;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      text-decoration: none;
      padding: 0;
      font-family: inherit;
    }
    .nps-btn:hover {
      border-color: var(--primary-color, #03a9f4);
      color: var(--primary-color, #03a9f4);
    }
    .nps-x:hover {
      border-color: var(--error-color, #db4437);
      color: var(--error-color, #db4437);
      background: rgba(219, 68, 55, .1);
    }
    .nps-body { flex: 1 1 auto; position: relative; background: var(--card-background-color, #fff); }
    .nps-body iframe {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      border: 0;
      background: var(--primary-background-color, #fafafa);
    }
  `;

  // HA 设备页的「访问」渲染为 <ha-button href>，内部 <a> 位于 ha-button 的
  // Shadow DOM 中；普通 closest("a") 穿不过 shadow 边界，必须走
  // composedPath() 拿到事件穿过的全部节点。
  function matchConsoleLink(e) {
    let path = null;
    try { path = typeof e.composedPath === "function" ? e.composedPath() : null; }
    catch (_) { path = null; }
    if (!path || !path.length) {
      path = [];
      let n = e.target;
      while (n) {
        path.push(n);
        const root = n.getRootNode ? n.getRootNode() : null;
        n = n.parentNode || (root && root.host) || null;
      }
    }
    for (const node of path) {
      if (!node || node.nodeType !== 1) { continue; }  // 只看 Element
      let href = null;
      if (node.tagName === "A") { href = node.href; }
      if (!href && typeof node.getAttribute === "function") {
        href = node.getAttribute("href");  // ha-button 的 href 属性
      }
      if (!href) { continue; }
      let u;
      try { u = new URL(href, location.href); } catch (_) { continue; }
      if (u.pathname !== CONSOLE_PATH) { continue; }
      // 只拦截带签名的面板地址（静态资源 API 路径一律放行）
      if (!u.searchParams.has("authSig")) { continue; }
      // 关键：主机地址以**浏览器当前地址栏**为准，而不是设备链接里存的
      // HA 自探测地址（端口映射/反代/换过访问 IP 后那个地址往往不可达）。
      // authSig 只签 path+query 不签 host，换 host 后签名依然有效。
      try { u = new URL(u.pathname + u.search, window.location.origin); }
      catch (_) { /* 解析失败就用原链接 */ }
      return { url: u, node };
    }
    return null;
  }

  // 把命中的链接原地改写为地址栏主机地址：连 Ctrl/中键的原生新标签、
  //   ha-button 内部可能触发的 window.open 也一并覆盖到（不拦截默认行为）。
  function rewriteLink(match) {
    if (!match) { return; }
    try {
      if (match.node.getAttribute && match.node.getAttribute("href")) {
        match.node.setAttribute("href", match.url.href);
      }
    } catch (_) { /* 只读 DOM 改不动时静默，悬浮窗路径仍可用 */ }
  }

  function ensureHost() {
    let host = document.getElementById(HOST_ID);
    if (host) { return host; }
    host = document.createElement("div");
    host.id = HOST_ID;
    // 容器本身不挡鼠标，只有悬浮窗本体接收事件 —— 非模态，
    // 窗体外仍可正常操作 Home Assistant
    host.style.cssText =
      "position:fixed;inset:0;z-index:999999;pointer-events:none";
    const shadow = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = CSS;
    shadow.appendChild(style);
    document.body.appendChild(host);
    return host;
  }

  function centerWindow(win) {
    const w = win.offsetWidth || Math.min(1180, window.innerWidth * 0.95);
    const h = win.offsetHeight || Math.min(860, window.innerHeight * 0.9);
    win.style.left = Math.max(8, (window.innerWidth - w) / 2) + "px";
    win.style.top = Math.max(8, (window.innerHeight - h) / 2 - 8) + "px";
  }

  function enableDrag(win, head) {
    head.addEventListener("pointerdown", (e) => {
      if (e.target.closest(".nps-btn")) { return; }
      e.preventDefault();
      const offX = e.clientX - win.offsetLeft;
      const offY = e.clientY - win.offsetTop;
      const move = (ev) => {
        const x = Math.max(-win.offsetWidth + 120,
          Math.min(window.innerWidth - 60, ev.clientX - offX));
        const y = Math.max(0,
          Math.min(window.innerHeight - 40, ev.clientY - offY));
        win.style.left = x + "px";
        win.style.top = y + "px";
      };
      const up = () => {
        document.removeEventListener("pointermove", move);
        document.removeEventListener("pointerup", up);
      };
      document.addEventListener("pointermove", move);
      document.addEventListener("pointerup", up);
    });
  }

  function buildWindow(root) {
    const win = document.createElement("div");
    win.className = "nps-window";
    win.style.width = WIDTH;
    win.style.height = HEIGHT;
    win.innerHTML = `
      <div class="nps-head">
        <span class="nps-ico">⠿</span>
        <span class="nps-title">${TITLE}</span>
        <span class="nps-spacer"></span>
        <button type="button" class="nps-btn" data-act="reload" title="重新加载">↻</button>
        <a class="nps-btn nps-link" target="_blank" rel="noopener" title="在新标签页打开">↗</a>
        <button type="button" class="nps-btn nps-x" data-act="close" title="关闭">✕</button>
      </div>
      <div class="nps-body"><iframe
          allow="clipboard-read; clipboard-write"
          allowfullscreen></iframe></div>`;
    root.appendChild(win);

    const frame = win.querySelector("iframe");
    centerWindow(win);
    enableDrag(win, win.querySelector(".nps-head"));

    win.querySelector('[data-act="reload"]').addEventListener("click", () => {
      // 签名链接会被缓存，重载只重新拉页面（重新申请会话 Cookie）
      if (frame.dataset.url) { frame.src = frame.dataset.url; }
    });
    win.querySelector('[data-act="close"]').addEventListener("click", () => {
      // 先换地址，释放页面里的轮询/连接
      frame.src = "about:blank";
      frame.dataset.url = "";
      win.classList.remove("show");
    });
    return win;
  }

  function openFloat(url) {
    let target = url;
    if (typeof target === "string") {
      try { target = new URL(target, window.location.origin); } catch (_) { return; }
    }
    if (!target || target.pathname !== CONSOLE_PATH) { return; }

    const host = ensureHost();
    const root = host.shadowRoot;
    let win = root.querySelector(".nps-window");
    if (!win) { win = buildWindow(root); }

    const frame = win.querySelector("iframe");
    if (frame.dataset.url !== target.href) {
      frame.dataset.url = target.href;
      frame.src = target.href;
      win.querySelector(".nps-link").href = target.href;
    }
    win.classList.add("show");
    win.classList.remove("nps-flash");
    // 强制 reflow 以重放动画
    void win.offsetWidth;
    win.classList.add("nps-flash");
    win.style.zIndex = "10";
  }

  function closeFloat() {
    const host = document.getElementById(HOST_ID);
    const win = host && host.shadowRoot && host.shadowRoot.querySelector(".nps-window");
    if (!win) { return; }
    const frame = win.querySelector("iframe");
    frame.src = "about:blank";
    frame.dataset.url = "";
    win.classList.remove("show");
  }

  // 捕获阶段拦截（document 早于 shadow 内部的目标元素收到事件）：
  //   preventDefault 阻止 <a> 默认导航/开新标签；
  //   stopPropagation 阻止事件继续进入 shadow 到达 ha-button 自身的
  //   @click 处理器（_deviceActionClicked，可能 window.open）。
  //   Ctrl/Cmd/Shift/Alt 点击及中键仍走浏览器原生"新标签打开"。
  function onClick(e) {
    const match = matchConsoleLink(e);
    if (!match) { return; }
    rewriteLink(match);
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) {
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    openFloat(match.url);
  }

  document.addEventListener("click", onClick, true);

  // 供 Lovelace 卡片 / 自定义脚本复用：__npsFloatOpen(urlOrString)
  window.__npsFloatOpen = openFloat;
  window.__npsFloatClose = closeFloat;
  // 加载标记：F12 Console 输入 __npsFloatEmbed 可确认模块是否生效
  window.__npsFloatEmbed = "1.0.0";
})();
