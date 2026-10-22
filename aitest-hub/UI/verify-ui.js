/* Playwright 全站 UI 验证脚本
 * 用法: NODE_PATH=$(npm root -g) node verify-ui.js [组名]
 * 组: flow | tools | misc | all
 */
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const BASE = "file://" + path.resolve(__dirname) + "/";
const ACC = process.env.DEMO_ACCOUNT || 'demo_tester', PWD = process.env.DEMO_PASSWORD || 'Demo@2026';
const issues = [];
function log(kind, page, msg) {
  const line = `[${kind}] ${page}: ${msg}`;
  (kind === "FAIL" ? issues : []).push(line);
  console.log(line);
}

/* ---------- 布局扫描：横向溢出 / 元素越界 ---------- */
async function scanLayout(page, name) {
  const r = await page.evaluate(() => {
    const out = { docOverflow: false, offenders: [] };
    const de = document.documentElement;
    if (de.scrollWidth > de.clientWidth + 2) out.docOverflow = true;
    const vw = de.clientWidth;
    const els = document.querySelectorAll("body *");
    for (const el of els) {
      if (el.closest(".modal-mask")) continue;           // 弹窗单独验
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden") continue;
      const b = el.getBoundingClientRect();
      if (b.width < 4 || b.height < 4) continue;
      // 明显超出视口右侧（滚动容器内部超出不算）
      if (b.right > vw + 6 && !el.closest("[data-scroll-x]") ) {
        const tag = el.tagName.toLowerCase() + (el.className && typeof el.className === "string" ? "." + el.className.split(" ").slice(0,2).join(".") : "");
        out.offenders.push(`${tag} right=${Math.round(b.right)}>vw=${vw}`);
        if (out.offenders.length >= 5) break;
      }
    }
    return out;
  });
  if (r.docOverflow) log("FAIL", name, "页面级横向溢出 (scrollWidth > clientWidth)");
  r.offenders.forEach(o => log("WARN", name, "元素越界: " + o));
}

/* ---------- 点击所有可见且可点的元素，检查 JS 报错 ---------- */
async function clickThrough(page, name) {
  const handles = await page.$$("button, a[href], .tab, .hub-tab, .side-item, .page-btn, [data-open-modal], [data-close-modal]");
  let clicked = 0;
  for (const h of handles) {
    try {
      if (!(await h.isVisible())) continue;
      if (await h.isDisabled()) continue;
      const cls = await h.getAttribute("class") || "";
      const txt = ((await h.textContent()) || "").trim().slice(0, 14);
      // 退出登录 / 删除确认等破坏性按钮只悬停不点
      if (/退出|logout|danger/i.test(cls) || /退出登录|删除/.test(txt)) continue;
      const href = await h.getAttribute("href");
      if (href && /^https?:/.test(href)) continue;        // 外链跳过
      const before = page.url();
      await h.click({ timeout: 1200 });
      clicked++;
      await page.waitForTimeout(120);
      // 若发生了导航则回到原页
      if (page.url() !== before && !page.url().includes("#")) {
        await page.goto(before, { waitUntil: "load" });
        await page.evaluate(() => localStorage.setItem("aitesthub_auth", "1"));
      }
      // 关闭被点开的弹窗
      const open = await page.$(".modal-mask.open");
      if (open) { await page.keyboard.press("Escape"); await page.waitForTimeout(80); }
    } catch (e) { /* 不可点元素忽略 */ }
  }
  return clicked;
}

async function checkPage(browser, file, opts = {}) {
  const ctx = await browser.newContext({ viewport: opts.viewport || { width: 1440, height: 820 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", e => errors.push(e.message.split("\n")[0]));
  page.on("console", m => { if (m.type() === "error") errors.push(m.text().split("\n")[0]); });
  try {
    await page.goto(BASE + file, { waitUntil: "load", timeout: 15000 });
    await page.evaluate(() => localStorage.setItem("aitesthub_auth", "1"));
    await page.reload({ waitUntil: "load" });
    await page.waitForTimeout(300);
    await scanLayout(page, file);
    if (!opts.noClick) {
      const n = await clickThrough(page, file);
      log("INFO", file, `交互点击 ${n} 个元素`);
    }
    errors.slice(0, 3).forEach(e => log("FAIL", file, "JS错误: " + e));
    if (!errors.length && !issues.filter(i => i.includes(file) && i.startsWith("[FAIL]")).length)
      log("PASS", file, "布局+交互+脚本 OK");
  } catch (e) {
    log("FAIL", file, "加载失败: " + e.message.split("\n")[0]);
  }
  await ctx.close();
}

/* ---------- 主流程 ---------- */
const TOOLS = fs.readdirSync(__dirname).filter(f => /^tool-.*\.html$/.test(f) || f === "prompts.html").sort();
const MISC = ["auth.html", "register.html", "index.html", "app.html"];

(async () => {
  const group = process.argv[2] || "all";
  const browser = await chromium.launch();
  if (group === "flow" || group === "all") {
    // 主流程: index → auth 登录 → index → app TAB → 卡片
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 820 } });
    const page = await ctx.newPage();
    const errs = [];
    page.on("pageerror", e => errs.push(e.message));
    await page.goto(BASE + "index.html", { waitUntil: "load" });
    await scanLayout(page, "flow:index");
    await page.click('a[href="auth.html"]');
    await page.waitForLoadState("load");
    await page.fill('#li-user, input[placeholder*="手机号"]', ACC).catch(() => {});
    await page.fill('input[type="password"]', PWD).catch(() => {});
    await page.click('button:has-text("登 录"), button:has-text("登录"), .btn-primary').catch(() => {});
    await page.waitForTimeout(600);
    log("INFO", "flow:auth", "登录后 URL = " + page.url().replace(BASE, ""));
    if (!page.url().includes("index.html")) log("FAIL", "flow:auth", "登录后未回官网首页");
    await page.goto(BASE + "app.html", { waitUntil: "load" });
    await page.waitForTimeout(300);
    for (const t of ["exec", "ai", "plat"]) {
      await page.click(`.hub-tabs .tab[data-tab="${t}"]`).catch(() => log("FAIL", "flow:app", "TAB " + t + " 不可点"));
      await page.waitForTimeout(150);
      const vis = await page.$$eval(".tab-pane.active .tool-card", els => els.length).catch(() => 0);
      log("INFO", "flow:app", `TAB ${t} 卡片数 ${vis}`);
    }
    await page.click('.tab-pane.active .tool-card .tc-enter').catch(() => log("FAIL", "flow:app", "卡片不可点"));
    await page.waitForLoadState("load");
    log("INFO", "flow:app", "点击卡片跳转到 " + page.url().replace(BASE, ""));
    errs.slice(0, 3).forEach(e => log("FAIL", "flow", "JS: " + e));
    await ctx.close();
  }
  if (group === "tools" || group === "all") {
    for (const f of TOOLS) await checkPage(browser, f);
  }
  if (group === "misc" || group === "all") {
    for (const f of MISC) await checkPage(browser, f, { noClick: f === "auth.html" || f === "register.html" });
  }
  await browser.close();
  console.log("\n======== 汇总 ========");
  console.log("FAIL:", issues.filter(i => i.startsWith("[FAIL]")).length, " WARN:", issues.filter(i => i.startsWith("[WARN]")).length);
  issues.filter(i => i.startsWith("[FAIL]")).forEach(i => console.log(i));
})().catch(e => { console.error("脚本异常:", e); process.exit(1); });
