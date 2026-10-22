/* ============================================================
   AITest Hub — 全站共享脚本
   登录态 / 导航注入 / Modal / Toast / 分页 / 工具函数
   ============================================================ */
(function () {
  "use strict";

  /* ---------- 登录态 ---------- */
  var AUTH_KEY = "aitesthub_auth";
  /* 演示账号不在前端内置：向后端索取（后端由 DEMO_ACCOUNT / DEMO_PASSWORD 决定）。
     静态原型脱离后端打开时取不到，填充按钮会提示不可用。 */
  var demoCredsPromise = null;
  function demoCreds() {
    if (!demoCredsPromise) {
      demoCredsPromise = fetch("/api/config/demo-account")
        .then(function (r) { if (!r.ok) throw 0; return r.json(); })
        .catch(function () { return null; });
    }
    return demoCredsPromise;
  }

  window.Auth = {
    isLogin: function () { return localStorage.getItem(AUTH_KEY) === "1"; },
    login: function () { localStorage.setItem(AUTH_KEY, "1"); },
    logout: function () { localStorage.removeItem(AUTH_KEY); location.href = "index.html"; },
    demoCreds: demoCreds,
    /** 未登录则跳转登录页（带来源），登录后回跳 */
    requireLogin: function () {
      if (!Auth.isLogin()) {
        location.href = "auth.html?redirect=" + encodeURIComponent(location.pathname.split("/").pop() + location.search);
        return false;
      }
      return true;
    }
  };

  /* ---------- v5 前后端联调：真实 JWT 登录 + 统一鉴权请求 ---------- */
  window.API_BASE = window.API_BASE || "";
  var TOKEN_KEY = "aitesthub_token";
  var LOGIN_USER_KEY = "aitesthub_login_user";
  Auth.token = function () { return localStorage.getItem(TOKEN_KEY) || ""; };
  Auth.loginAPI = function (account, password) {
    return fetch(window.API_BASE + "/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ username: account, phone: account, password: password })
    }).then(function (resp) {
      return resp.json().catch(function () { return {}; }).then(function (data) {
        if (!resp.ok) { var d = data && data.detail; throw new Error(typeof d === "string" ? d : ("登录失败(" + resp.status + ")")); }
        localStorage.setItem(TOKEN_KEY, data.access_token);
        Auth.login();
        localStorage.setItem(LOGIN_USER_KEY, account);
        return data;
      });
    });
  };
  Auth.registerAPI = function (payload) {
    return fetch(window.API_BASE + "/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(payload)
    }).then(function (resp) {
      return resp.json().catch(function () { return {}; }).then(function (data) {
        if (!resp.ok) { var d = data && data.detail; throw new Error(typeof d === "string" ? d : ("注册失败(" + resp.status + ")")); }
        return data;
      });
    });
  };
  Auth.api = function (path, opts) {
    opts = opts || {};
    var h = {}; var src = opts.headers || {}; for (var k in src) { h[k] = src[k]; }
    var tk = Auth.token();
    if (tk) h["Authorization"] = "Bearer " + tk;
    opts.headers = h;
    if (opts.json !== undefined) { opts.method = opts.method || "POST"; h["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.json); delete opts.json; }
    return fetch(window.API_BASE + path, opts).then(function (r) {
      if (r.status === 401) { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(AUTH_KEY); }
      return r;
    });
  };
  var _origLogout = Auth.logout;
  Auth.logout = function () {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(LOGIN_USER_KEY);
    return _origLogout.apply(Auth, arguments);
  };

  /* ---------- Toast ---------- */
  function toastBox() {
    var box = document.getElementById("toast-box");
    if (!box) {
      box = document.createElement("div");
      box.id = "toast-box";
      document.body.appendChild(box);
    }
    return box;
  }
  window.toast = function (msg, type, timeout) {
    type = type || "success";
    var icons = { success: "✅", error: "❌", warn: "⚠️", info: "ℹ️" };
    var el = document.createElement("div");
    el.className = "toast toast-" + type;
    el.innerHTML = '<span class="t-icon">' + (icons[type] || "ℹ️") + '</span><span>' + msg + "</span>";
    toastBox().appendChild(el);
    setTimeout(function () {
      el.classList.add("out");
      setTimeout(function () { el.remove(); }, 260);
    }, timeout || 2600);
  };

  /* ---------- Modal ---------- */
  window.openModal = function (id) {
    var m = document.getElementById(id);
    if (!m) return;
    m.classList.add("open");
    var first = m.querySelector("input, textarea, select");
    if (first) setTimeout(function () { first.focus(); }, 60);
  };
  window.closeModal = function (id) {
    var m = typeof id === "string" ? document.getElementById(id) : id;
    if (m) m.classList.remove("open");
  };
  document.addEventListener("click", function (e) {
    if (e.target.classList && e.target.classList.contains("modal-mask")) e.target.classList.remove("open");
    var c = e.target.closest("[data-close-modal]");
    if (c) { var m = c.closest(".modal-mask"); if (m) m.classList.remove("open"); }
    var o = e.target.closest("[data-open-modal]");
    if (o) {
      var t = document.getElementById(o.getAttribute("data-open-modal"));
      if (t) t.classList.add("open");
    }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      document.querySelectorAll(".modal-mask.open").forEach(function (m) { m.classList.remove("open"); });
      document.querySelectorAll(".dropdown-menu.open").forEach(function (d) { d.classList.remove("open"); });
    }
  });

  /* ---------- 确认弹窗 ---------- */
  window.confirmAction = function (opt) {
    var mask = document.getElementById("modal-confirm");
    if (!mask) {
      mask = document.createElement("div");
      mask.id = "modal-confirm";
      mask.className = "modal-mask";
      mask.innerHTML =
        '<div class="modal modal-sm">' +
        '  <div class="modal-head"><h3 id="cf-title">确认操作</h3><button class="modal-close" data-close-modal>✕</button></div>' +
        '  <div class="modal-body"><p id="cf-msg" class="text-dim" style="font-size:13.5px"></p></div>' +
        '  <div class="modal-foot"><button class="btn btn-ghost" data-close-modal>取消</button>' +
        '  <button class="btn btn-danger" id="cf-ok">确认</button></div></div>';
      document.body.appendChild(mask);
    }
    mask.querySelector("#cf-title").textContent = opt.title || "确认操作";
    mask.querySelector("#cf-msg").textContent = opt.message || "确定要执行该操作吗？";
    var ok = mask.querySelector("#cf-ok");
    ok.textContent = opt.okText || "确认";
    ok.className = "btn " + (opt.danger === false ? "btn-primary" : "btn-danger");
    var handler = function () {
      mask.classList.remove("open");
      ok.removeEventListener("click", handler);
      if (opt.onOk) opt.onOk();
    };
    ok.removeEventListener("click", handler);
    ok.addEventListener("click", handler);
    mask.classList.add("open");
  };

  /* ---------- 输入弹窗（替代原生 prompt，风格与 confirmAction 一致） ---------- */
  window.promptModal = function (opt) {
    var mask = document.getElementById("modal-prompt");
    if (!mask) {
      mask = document.createElement("div");
      mask.id = "modal-prompt";
      mask.className = "modal-mask";
      mask.innerHTML =
        '<div class="modal modal-sm">' +
        '  <div class="modal-head"><h3 id="pm-title">输入内容</h3><button class="modal-close" data-close-modal>✕</button></div>' +
        '  <div class="modal-body"><div class="field"><label for="pm-input" id="pm-label">内容</label>' +
        '  <input class="input" id="pm-input" type="text"></div></div>' +
        '  <div class="modal-foot"><button class="btn btn-ghost" data-close-modal>取消</button>' +
        '  <button class="btn btn-primary" id="pm-ok">确定</button></div></div>';
      document.body.appendChild(mask);
    }
    mask.querySelector("#pm-title").textContent = opt.title || "输入内容";
    mask.querySelector("#pm-label").textContent = opt.label || "内容";
    var input = mask.querySelector("#pm-input");
    input.value = opt.defaultValue || "";
    var ok = mask.querySelector("#pm-ok");
    var handler = function () {
      mask.classList.remove("open");
      ok.removeEventListener("click", handler);
      if (opt.onOk) opt.onOk(input.value);
    };
    ok.removeEventListener("click", handler);
    ok.addEventListener("click", handler);
    mask.classList.add("open");
    setTimeout(function () { input.focus(); input.select(); }, 60);
  };

  /* ---------- Tabs ---------- */
  window.initTabs = function (root) {
    (root || document).querySelectorAll(".tabs").forEach(function (tabs) {
      tabs.querySelectorAll(".tab").forEach(function (tab) {
        tab.addEventListener("click", function () {
          var scope = tabs.dataset.scope ? document.getElementById(tabs.dataset.scope) || document : document;
          tabs.querySelectorAll(".tab").forEach(function (t) { t.classList.remove("active"); });
          tab.classList.add("active");
          var name = tab.dataset.tab;
          scope.querySelectorAll(":scope > .tab-pane, :scope .tab-panes > .tab-pane").forEach(function (p) {
            p.classList.toggle("active", p.dataset.pane === name);
          });
          if (typeof tab.dataset.onchange !== "undefined" && window._tabChange) window._tabChange(name);
        });
      });
    });
  };

  /* ---------- URL Query 工具 ---------- */
  window.qs = function (key) { return new URLSearchParams(location.search).get(key); };
  window.setQs = function (key, val) {
    var p = new URLSearchParams(location.search);
    if (val === null || val === "") p.delete(key); else p.set(key, val);
    history.replaceState(null, "", location.pathname + "?" + p.toString());
  };

  /* ---------- 防抖 ---------- */
  window.debounce = function (fn, wait) {
    var t;
    return function () {
      var args = arguments, ctx = this;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(ctx, args); }, wait || 250);
    };
  };

  /* ---------- 复制 ---------- */
  window.copyText = function (text, tip) {
    (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject())
      .then(function () { toast(tip || "已复制到剪贴板", "success"); })
      .catch(function () {
        var ta = document.createElement("textarea");
        ta.value = text; document.body.appendChild(ta);
        ta.select(); document.execCommand("copy"); ta.remove();
        toast(tip || "已复制到剪贴板", "success");
      });
  };

  /* ---------- 顶栏 & 模块侧栏注入 ---------- */
  /* 模块页可在加载 common.js 前定义：
     window.MODULE_META = { name, icon, back, items:[tab值子集(可选,默认全部)] }
     未定义则自动取页面主 TAB 组生成子功能菜单；无 TAB 页显示单项概览。 */

  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  function buildTopbar() {
    /* 顶栏注入规则：
       1) body[data-noinject-topbar] 的页面（登录/注册）不注入；
       2) 页面自带 .topbar（含 data-noinject 标记）时不重复注入；
       3) 其余页面在 <body> 顶部自动注入统一顶栏。 */
    if (document.body.hasAttribute("data-noinject-topbar")) return;
    var bar = document.querySelector(".topbar[data-noinject]");
    if (bar || document.querySelector(".topbar")) return;
    /* 顶栏只保留品牌与用户操作，模块导航由侧栏承担，不再重复出现 */
    var logged = Auth.isLogin();
    var right = logged
      ? '<div class="tb-actions">' +
        '<a class="tb-act" href="app.html"><span class="ta-ico">' + String.fromCodePoint(0x1F5C2) + '</span>\u5361\u7247\u5217\u8868</a>' +
        '<a class="tb-act" href="index.html"><span class="ta-ico">' + String.fromCodePoint(0x1F310) + '</span>\u5b98\u7f51\u9996\u9875</a>' +
        '<button class="tb-act" onclick="toast(\'\u6f14\u793a\u73af\u5883\uff1a\u4e2a\u4eba\u8bbe\u7f6e\u672a\u5f00\u653e\',\'info\')"><span class="ta-ico">\u2699\ufe0f</span>\u4e2a\u4eba\u8bbe\u7f6e</button>' +
        '<button class="tb-act danger" onclick="Auth.logout()"><span class="ta-ico">' + String.fromCodePoint(0x1F6AA) + '</span>\u9000\u51fa\u767b\u5f55</button>' +
        '</div>' +
        '<span class="user-chip static"><span class="avatar">W</span><span class="uc-name">wxh \u00b7 \u6d4b\u8bd5\u5de5\u7a0b\u5e08</span></span>'
      : '<a class="btn btn-ghost btn-sm" href="auth.html">\u767b\u5f55</a><a class="btn btn-primary btn-sm" href="register.html">\u6ce8\u518c</a>';
    var backBtn = (logged || document.querySelector(".sidebar")) ? "" :
      '<a class="btn btn-ghost btn-sm" href="app.html">' + String.fromCodePoint(0x1F5C2) + ' \u5361\u7247\u5217\u8868</a>';
    var bar2 = document.createElement("div");
    bar2.className = "topbar";
    bar2.innerHTML =
      '<a class="brand" href="index.html"><span class="logo">AT</span>AITest Hub</a>' +
      '<div class="topbar-right">' + backBtn + right + "</div>";
    var first = document.body.firstChild;
    document.body.insertBefore(bar2, first);
  }

  function buildSidebar() {
    var sb = document.querySelector(".sidebar[data-noinject]");
    if (sb || !document.querySelector(".sidebar")) return;
    var meta = window.MODULE_META || {};
    var sidebar = document.querySelector(".sidebar");
    /* 页面主 TAB 组 = 模块子功能菜单数据源 */
    var tabsBar = null, tabBtns = [];
    var cand = document.querySelectorAll(".workspace .tabs, .main-area .tabs, .tabs");
    for (var i = 0; i < cand.length; i++) {
      var btnIn = cand[i].querySelectorAll(":scope > .tab[data-tab]");
      if (btnIn.length) { tabsBar = cand[i]; tabBtns = [].slice.call(btnIn); break; }
    }
    var chosen = tabBtns;
    if (meta.items && meta.items.length) {
      var picked = [];
      meta.items.forEach(function (v) {
        tabBtns.forEach(function (b) { if (b.getAttribute("data-tab") === v) picked.push(b); });
      });
      if (picked.length) chosen = picked;
    }
    var title = meta.name || (document.title || "").split(" —")[0];
    var html = '<div class="mod-head">' +
      '<a class="mod-back" href="' + (meta.back || "app.html") + '">&#8592; \u8fd4\u56de\u5361\u7247\u5217\u8868</a>' +
      '<div class="mod-title"><span class="mt-ico">' + (meta.icon || "\u{1F9E9}") + '</span>' + title + "</div></div>";
    html += '<div class="side-nav">';
    if (chosen.length) {
      chosen.forEach(function (b) {
        var full = (b.textContent || "").trim();
        var icon = String.fromCodePoint(full.codePointAt(0));
        var rest = full.slice(icon.length).trim();
        html += '<a class="side-item" data-mtab="' + b.getAttribute("data-tab") + '"><span class="si-ico">' + icon + '</span><span class="si-txt">' + rest + '</span></a>';
      });
    } else {
      html += '<a class="side-item active"><span class="si-ico">\u{1F3E0}</span><span class="si-txt">\u603B\u89C8</span></a>';
    }
    html += '</div>';
    sidebar.innerHTML = html;
    var items = sidebar.querySelectorAll(".side-item[data-mtab]");
    function syncMenu() {
      [].forEach.call(items, function (it) {
        var b = tabBtns.filter(function (x) { return x.getAttribute("data-tab") === it.getAttribute("data-mtab"); })[0];
        it.classList.toggle("active", !!(b && b.classList.contains("active")));
      });
    }
    [].forEach.call(items, function (it) {
      it.addEventListener("click", function (ev) {
        ev.preventDefault();
        var b = tabBtns.filter(function (x) { return x.getAttribute("data-tab") === it.getAttribute("data-mtab"); })[0];
        if (b) { b.click(); if (window.setQs) setQs("tab", it.getAttribute("data-mtab")); }
        syncMenu();
      });
    });
    if (tabsBar && chosen.length) tabsBar.style.display = "none";
    document.addEventListener("click", function (e) {
      if (e.target.closest && e.target.closest(".tabs .tab")) setTimeout(syncMenu, 0);
    });
    syncMenu();
  }

  /* ---------- 通用表格渲染 + 分页 ---------- */
  window.PagedTable = function (opt) {
    this.data = opt.data || [];
    this.pageSize = opt.pageSize || 10;
    this.page = 1;
    this.filters = {};
    this.opt = opt;
    this.container = document.querySelector(opt.el);
    this.render();
  };
  PagedTable.prototype = {
    getFiltered: function () {
      var f = this.filters, d = this.data;
      if (this.opt.filterFn) d = d.filter(function (row) { return this.opt.filterFn(row, f); }, this);
      return d;
    },
    setPage: function (p) { this.page = p; this.render(); },
    setFilters: function (f) { this.filters = f; this.page = 1; this.render(); },
    refresh: function () { this.render(); },
    render: function () {
      var self = this, all = this.getFiltered();
      var total = all.length;
      var pages = Math.max(1, Math.ceil(total / this.pageSize));
      if (this.page > pages) this.page = pages;
      var rows = all.slice((this.page - 1) * this.pageSize, this.page * this.pageSize);
      var html = '<div class="table-wrap"><table class="table"><thead><tr>';
      this.opt.columns.forEach(function (c) { html += "<th>" + c.title + "</th>"; });
      html += "</tr></thead><tbody>";
      if (!rows.length) {
        html += '<tr><td colspan="' + this.opt.columns.length + '"><div class="empty"><div class="e-icon">🔍</div><div class="e-text">暂无匹配数据，试试调整筛选条件</div></div></td></tr>';
      } else {
        rows.forEach(function (row, i) {
          html += "<tr>";
          self.opt.columns.forEach(function (c) {
            html += "<td>" + c.render(row, (self.page - 1) * self.pageSize + i) + "</td>";
          });
          html += "</tr>";
        });
      }
      html += "</tbody></table></div>";
      // 分页条
      html += '<div class="pagination"><span class="page-info">共 ' + total + " 条 · 第 " + this.page + "/" + pages + " 页</span>";
      html += '<label class="pg-size">每页 <select class="pg-size-sel">' + [10, 20, 50, 100].map(function (n) { return '<option value="' + n + '"' + (n === self.pageSize ? " selected" : "") + ">" + n + "</option>"; }).join("") + "</select> 条</label>";
      html += '<button class="page-btn txt" data-p="1">首页</button><button class="page-btn txt" data-p="' + (this.page - 1) + '" ' + (this.page <= 1 ? "disabled" : "") + ">上一页</button>";
      var start = Math.max(1, this.page - 2), end = Math.min(pages, start + 4);
      for (var p = start; p <= end; p++) {
        html += '<button class="page-btn' + (p === this.page ? " active" : "") + '" data-p="' + p + '">' + p + "</button>";
      }
      html += '<button class="page-btn txt" data-p="' + (this.page + 1) + '" ' + (this.page >= pages ? "disabled" : "") + ">下一页</button>";
      html += '<button class="page-btn txt" data-p="' + pages + '">末页</button></div>';
      this.container.innerHTML = html;
      var self2 = this;
      this.container.querySelectorAll(".page-btn[data-p]").forEach(function (b) {
        b.addEventListener("click", function () {
          var p = parseInt(b.dataset.p, 10);
          if (p >= 1 && p <= pages) self2.setPage(p);
        });
      });
      var psel = this.container.querySelector(".pg-size-sel");
      if (psel) psel.addEventListener("change", function () {
        self2.pageSize = parseInt(psel.value, 10);
        self2.setPage(1);
      });
      if (this.opt.onRendered) this.opt.onRendered(rows, this);
    }
  };

  /* ---------- 表格列表自动中文分页（全站零侵入注入） ---------- */
  var PG_SIZE = 10;
  function visibleRows(tbody) {
    return [].slice.call(tbody.children).filter(function (tr) {
      return tr.tagName === "TR" && !tr.hasAttribute("data-empty");
    });
  }
  function applyAuto(tbody, host) {
    if (!host.__pg) host.__pg = { page: 1, size: 10 };
    var st = host.__pg;
    function apply() {
      var rs = visibleRows(tbody);
      var ps = Math.max(1, Math.ceil(rs.length / st.size));
      if (st.page > ps) st.page = ps;
      if (st.page < 1) st.page = 1;
      rs.forEach(function (tr, i) {
        tr.style.display = (i >= (st.page - 1) * st.size && i < st.page * st.size) ? "" : "none";
      });
      var bar = host.parentNode && host.parentNode.querySelector(":scope > .pagination.auto-pg");
      if (host.querySelector(".pagination:not(.auto-pg)") || host.parentNode.querySelector(":scope > .pagination:not(.auto-pg)") || host.closest("[data-pt]") || host.closest("[data-nopager]")) {
        if (bar) bar.remove();
        rs.forEach(function (tr) { tr.style.display = ""; });
        if (tbody.__pgObs) { tbody.__pgObs.disconnect(); tbody.__pgObs = null; }
        host.__pgApply = null;
        return;
      }
      if (rs.length === 0) return;
      if (!bar) {
        bar = document.createElement("div");
        bar.className = "pagination auto-pg";
        host.insertAdjacentElement("afterend", bar);
      }
      var h = '<span class="page-info">\u5171 ' + rs.length + ' \u6761 \u00b7 \u7b2c ' + st.page + '/' + ps + ' \u9875</span>';
      h += '<label class="pg-size">每页 <select class="pg-size-sel" data-ps="10,20,50,100">' + [10, 20, 50, 100].map(function (n) { return '<option value="' + n + '"' + (n === st.size ? " selected" : "") + '>' + n + "</option>"; }).join("") + '</select> 条</label>';
      h += '<button class="page-btn txt" data-p="1"' + (st.page <= 1 ? " disabled" : "") + '>\u9996\u9875</button>';
      h += '<button class="page-btn txt" data-p="' + (st.page - 1) + '"' + (st.page <= 1 ? " disabled" : "") + '>\u4e0a\u4e00\u9875</button>';
      var start = Math.max(1, st.page - 2), end = Math.min(ps, start + 4);
      start = Math.max(1, end - 4);
      for (var p = start; p <= end; p++) {
        h += '<button class="page-btn' + (p === st.page ? " active" : "") + '" data-p="' + p + '">' + p + '</button>';
      }
      h += '<button class="page-btn txt" data-p="' + (st.page + 1) + '"' + (st.page >= ps ? " disabled" : "") + '>\u4e0b\u4e00\u9875</button>';
      h += '<button class="page-btn txt" data-p="' + ps + '"' + (st.page >= ps ? " disabled" : "") + '>\u672b\u9875</button>';
      bar.innerHTML = h;
      [].forEach.call(bar.querySelectorAll(".page-btn[data-p]"), function (b) {
        b.addEventListener("click", function () {
          if (b.disabled) return;
          st.page = parseInt(b.getAttribute("data-p"), 10);
          apply();
        });
      });
      var sel = bar.querySelector(".pg-size-sel");
      if (sel && !sel.__bound) {
        sel.__bound = true;
        sel.addEventListener("change", function () {
          st.size = parseInt(sel.value, 10);
          st.page = 1;
          apply();
        });
      }
    }
    apply();
    host.__pgApply = apply;
    if (!tbody.__pgObs && typeof MutationObserver !== "undefined") {
      tbody.__pgObs = new MutationObserver(function () {
        if (host.__pgApply) host.__pgApply();
      });
      tbody.__pgObs.observe(tbody, { childList: true });
    }
  }
  window.autoPaginate = function (root) {
    (root || document).querySelectorAll(".table").forEach(function (tb) {
      /* v4：弹窗内的表格同样参与分页（默认 10 条/页） */
      if (tb.closest("[data-pt]") || tb.closest("[data-nopager]")) return;
      var tbody = tb.tBodies && tb.tBodies[0] ? tb.tBodies[0] : tb.querySelector("tbody");
      if (!tbody || !tbody.children.length) return;
      var host = tb.closest(".table-wrap") || tb.parentNode;
      if (!host || !host.parentNode) return;
      if (host.querySelector(".pagination")) return;
      if (host.parentNode.querySelector(":scope > .pagination:not(.auto-pg)")) return;
      applyAuto(tbody, host);
    });
  };

  /* ---------- v4 一屏收纳：内容封顶 + 「更多内容」弹窗（默认每页 10 条） ----------
     规则：页面正文中的长内容区（.code-block / .chat-box / [data-cap]）自动限高，
     超出部分不再撑破一屏，尾部渐隐并在下方给出「更多内容」按钮；
     点击弹出统一弹窗展示全部内容，列表/消息/日志行按 10 条一页分页。 */
  var MORE_SIZE = 10;
  var CAP_H_MAP = [[".chat-box", 330], [".code-block", 240]];

  function capHeightOf(el) {
    var h = el.getAttribute("data-cap-h");
    if (h && parseInt(h, 10) > 0) return parseInt(h, 10);
    for (var i = 0; i < CAP_H_MAP.length; i++) {
      if (el.matches(CAP_H_MAP[i][0])) return CAP_H_MAP[i][1];
    }
    return 240;
  }
  function capTitleOf(el) {
    var t = el.getAttribute("data-cap-title");
    if (t) return t;
    var f = el.closest(".field");
    if (f && f.querySelector("label")) return f.querySelector("label").textContent.trim();
    var card = el.closest(".card");
    if (card && card.querySelector(".card-title")) return card.querySelector(".card-title").textContent.trim().slice(0, 26);
    return (document.title || "内容").split(" —")[0] + " · 详细内容";
  }

  /* 通用分页条（页脚按钮组） */
  function renderPager(bar, st, total) {
    var size = st.size || MORE_SIZE;
    var ps = Math.max(1, Math.ceil(total / size));
    if (st.page > ps) st.page = ps;
    if (st.page < 1) st.page = 1;
    var h = '<span class="page-info">共 ' + total + " 条 · 第 " + st.page + "/" + ps + " 页</span>";
    h += '<label class="pg-size">每页 <select class="pg-size-sel">' + [10, 20, 50, 100].map(function (n) { return '<option value="' + n + '"' + (n === size ? " selected" : "") + ">" + n + "</option>"; }).join("") + "</select> 条</label>";
    h += '<button class="page-btn txt" data-p="1"' + (st.page <= 1 ? " disabled" : "") + ">首页</button>";
    h += '<button class="page-btn txt" data-p="' + (st.page - 1) + '"' + (st.page <= 1 ? " disabled" : "") + ">上一页</button>";
    var start = Math.max(1, st.page - 2), end = Math.min(ps, start + 4);
    start = Math.max(1, end - 4);
    for (var p = start; p <= end; p++) {
      h += '<button class="page-btn' + (p === st.page ? " active" : "") + '" data-p="' + p + '">' + p + "</button>";
    }
    h += '<button class="page-btn txt" data-p="' + (st.page + 1) + '"' + (st.page >= ps ? " disabled" : "") + ">下一页</button>";
    h += '<button class="page-btn txt" data-p="' + ps + '"' + (st.page >= ps ? " disabled" : "") + ">末页</button>";
    bar.innerHTML = h;
    [].forEach.call(bar.querySelectorAll(".page-btn[data-p]"), function (b) {
      b.addEventListener("click", function () {
        if (b.disabled) return;
        st.page = parseInt(b.getAttribute("data-p"), 10);
        bar.__go();
      });
    });
    var msel = bar.querySelector(".pg-size-sel");
    if (msel) msel.addEventListener("change", function () {
      st.size = parseInt(msel.value, 10);
      st.page = 1;
      bar.__go();
    });
  }

  function ensureMoreModal() {
    var m = document.getElementById("modal-more");
    if (!m) {
      m = document.createElement("div");
      m.id = "modal-more";
      m.className = "modal-mask";
      m.setAttribute("data-nopager", "1");
      m.innerHTML =
        '<div class="modal modal-xl">' +
        '<div class="modal-head"><h3 id="mm-title">详细内容</h3><button class="modal-close" data-close-modal>✕</button></div>' +
        '<div class="modal-body" id="mm-body"></div>' +
        '<div class="modal-foot"><button class="btn btn-ghost" data-close-modal>关闭</button></div></div>';
      document.body.appendChild(m);
    }
    return m;
  }

  window.openMoreModal = function (el) {
    var mask = ensureMoreModal();
    var body = mask.querySelector("#mm-body");
    mask.querySelector("#mm-title").textContent = capTitleOf(el);
    body.innerHTML = "";
    var clone = el.cloneNode(true);
    clone.classList.remove("cap-box", "cap-clip", "cap-open");
    clone.removeAttribute("style");
    body.appendChild(clone);

    var bar = document.createElement("div");
    bar.className = "pagination";
    bar.style.display = "none";

    /* 三种内容形态统一按 10 条/页：消息/子元素列表 / 文本行 */
    var nodes = null, lines = null;
    if (clone.matches(".chat-box, ul, ol")) nodes = [].slice.call(clone.children);
    else {
      var txt = clone.textContent;
      lines = txt.split("\n");
    }
    var st = { page: 1, size: MORE_SIZE };
    function go() {
      var size = st.size || MORE_SIZE;
      if (nodes) {
        nodes.forEach(function (n, i) {
          n.style.display = (i >= (st.page - 1) * size && i < st.page * size) ? "" : "none";
        });
        renderPager(bar, st, nodes.length);
      } else {
        var chunk = lines.slice((st.page - 1) * size, st.page * size);
        clone.textContent = chunk.join("\n");
        renderPager(bar, st, lines.length);
      }
    }
    bar.__go = go;

    var total = nodes ? nodes.length : lines.length;
    if (total > (st.size || MORE_SIZE)) {
      body.appendChild(bar);
      bar.style.display = "";
      go();
    }
    mask.classList.add("open");
  };

  function applyCaps() {
    var els = document.querySelectorAll(".code-block, .chat-box, [data-cap]");
    [].forEach.call(els, function (el) {
      if (el.closest(".modal-mask") || el.closest(".dropdown") || el.closest(".popconfirm")) return;
      if (el.hasAttribute("data-cap-off")) return;
      var capH = capHeightOf(el);
      var over = el.scrollHeight > capH + 12;
      var row = el.__capRow && el.__capRow.isConnected ? el.__capRow : null;
      if (over) {
        el.classList.add("cap-box");
        el.style.setProperty("--cap-h", capH + "px");
        el.classList.add("cap-clip");
        if (!row) {
          row = document.createElement("div");
          row.className = "cap-more-row";
          row.innerHTML = '<button class="btn btn-ghost btn-sm btn-more" type="button">⌄ 查看更多内容</button>';
          row.querySelector(".btn-more").addEventListener("click", function () { window.openMoreModal(el); });
          el.insertAdjacentElement("afterend", row);
          el.__capRow = row;
        }
      } else {
        el.classList.remove("cap-box", "cap-clip", "cap-open");
        if (row) { row.remove(); el.__capRow = null; }
      }
    });
  }
  window.applyCaps = applyCaps;

  /* ---------- URL ?tab= 状态恢复（与侧栏写入的 setQs("tab") 对应，刷新/分享链接后保持子页） ---------- */
  function restoreTabFromUrl() {
    var want = qs("tab");
    if (!want) return;
    var bars = document.querySelectorAll(".tabs");
    for (var i = 0; i < bars.length; i++) {
      var t = null;
      try { t = bars[i].querySelector(':scope > .tab[data-tab="' + (window.CSS && CSS.escape ? CSS.escape(want) : want) + '"]'); } catch (e) { t = null; }
      if (t) { if (!t.classList.contains("active")) t.click(); return; }
    }
  }

  /* ---------- 启动 ---------- */
  document.addEventListener("DOMContentLoaded", function () {
    buildTopbar();
    buildSidebar();
    initTabs();
    restoreTabFromUrl();
    autoPaginate(document);
    applyCaps();
    /* 内容动态变化（日志流入/渲染/切换 TAB 显示）时自动重新封顶与分页 */
    var reflow = debounce(function () { autoPaginate(document); applyCaps(); }, 420);
    if (typeof MutationObserver !== "undefined") {
      new MutationObserver(function (ms) {
        for (var i = 0; i < ms.length; i++) {
          if (ms[i].target.closest && ms[i].target.closest("#modal-more")) return;
        }
        reflow();
      }).observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["class", "style", "hidden"] });
    }
    // 页面守卫：声明 data-require-login 的页面未登录跳登录页
    if (document.body.hasAttribute("data-require-login")) Auth.requireLogin();
    // 演示提示
    if (!localStorage.getItem("aitesthub_welcomed")) {
      localStorage.setItem("aitesthub_welcomed", "1");
    }
  });
})();
