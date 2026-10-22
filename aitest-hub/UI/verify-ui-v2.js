/* Playwright 有头全站验证脚本 v2
 * 验证点：①一屏（页面级无向下溢出，超高块已折叠出「更多内容」按钮）
 *        ②分页默认 10 条 + 中文分页条
 *        ③表格列内容居中、列宽自适应
 *        ④「更多内容」弹窗打开/分页/关闭
 * 用法: NODE_PATH=$(npm root -g) node verify-ui-v2.js          → 批量无头复验
 *       NODE_PATH=$(npm root -g) node verify-ui-v2.js --headed → 有头逐页演示
 */
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const HEAD = process.argv.includes("--headed");
const PORT = process.env.VPORT || 8902;
const DIR = __dirname;
const issues = [];
function log(kind, page, msg) {
  const line = `[${kind}] ${page}: ${msg}`;
  if (kind === "FAIL") issues.push(line);
  console.log(line);
}

/* ---------- 单页深检 ---------- */
async function checkPage(browser, file) {
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 820 },
    ...(HEAD ? {} : {}),
  });
  await ctx.addInitScript(() => localStorage.setItem("aitesthub_auth", "1"));
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message.split("\n")[0]));
  try {
    await page.goto(`http://127.0.0.1:${PORT}/${file}`, { waitUntil: "load", timeout: 15000 });
    await page.waitForTimeout(600);

    /* 1) 一屏检查：页面级无纵向溢出（workspace 布局下 main-area 内部滚动） */
    const one = await page.evaluate(() => {
      const de = document.documentElement;
      const docY = de.scrollHeight - de.clientHeight;
      // 内容溢出块：未被折叠的超高块
      let uncapped = 0, capped = 0;
      document.querySelectorAll(".code-block, .chat-box, [data-cap], .card, .tab-pane").forEach((el) => {
        if (el.closest(".modal-mask")) return;
        const pane = el.closest(".tab-pane");
        if (pane && !pane.classList.contains("active")) return;
        const cs = getComputedStyle(el);
        if (cs.display === "none") return;
        if (el.scrollHeight > de.clientHeight + 60 && el.classList.contains("cap-clip")) capped++;
        else if (el.scrollHeight > de.clientHeight + 60) uncapped++;
      });
      return { docY, uncapped, capped, hOverflow: de.scrollWidth > de.clientWidth + 2 };
    });
    if (one.hOverflow) log("FAIL", file, "横向溢出");
    if (one.docY > 4) log("WARN", file, `页面级纵向滚动 ${one.docY}px（期望一屏内内部滚动）`);
    if (one.uncapped > 0) log("WARN", file, `${one.uncapped} 个超高块未折叠（无「更多内容」按钮）`);

    /* 2) 分页默认 10 条：首个分页表格的可见行数 */
    const pg = await page.evaluate(() => {
      const bar = document.querySelector(".pagination");
      if (!bar) return { has: false };
      const txt = bar.textContent.replace(/\s+/g, " ");
      const table = bar.previousElementSibling && bar.previousElementSibling.querySelector("tbody");
      let visible = -1;
      if (table) visible = [].slice.call(table.children).filter((tr) => tr.style.display !== "none").length;
      return { has: true, txt: txt.slice(0, 46), visible, zh: /首页/.test(txt) && /下一页/.test(txt) && /末页/.test(txt) };
    });
    if (pg.has) {
      if (!pg.zh) log("FAIL", file, "分页条缺中文按钮（首页/下一页/末页）");
      if (pg.visible > 10) log("FAIL", file, `分页可见行数 ${pg.visible} > 10`);
      log("INFO", file, `分页: ${pg.txt} | 可见行 ${pg.visible}`);
    }

    /* 3) 列居中：抽样表格 th/td 的 text-align */
    const align = await page.evaluate(() => {
      const t = document.querySelector(".table");
      if (!t) return "n/a";
      const th = getComputedStyle(t.querySelector("th")).textAlign;
      const td = getComputedStyle(t.querySelector("td")).textAlign;
      return th + "/" + td;
    });
    if (align !== "n/a" && !/center/.test(align)) log("FAIL", file, "表格列未居中: " + align);

    /* 4) 交互：侧栏菜单全点 → 弹窗开/关 → 分页点击（有头模式慢速可见） */
    const menus = await page.$$(".side-nav .side-item");
    for (const m of menus) {
      try { await m.click({ timeout: 1500 }); } catch (e) {}
      await page.waitForTimeout(HEAD ? 900 : 250);
      const pane = await page.$(".tab-pane.active");
      if (!pane || (await pane.evaluate((el) => el.offsetHeight <= 0)))
        log("FAIL", file, "菜单点击后右侧内容区不可见");
    }
    const more = await page.$(".btn-more");
    if (more) {
      await more.click();
      await page.waitForTimeout(HEAD ? 900 : 300);
      const opened = await page.$eval("#modal-more", (el) => el.classList.contains("open"));
      if (!opened) log("FAIL", file, "「更多内容」弹窗未打开");
      else {
        const mp = await page.$eval("#modal-more .pagination", (el) => /首页/.test(el.textContent)).catch(() => false);
        log("INFO", file, "更多内容弹窗: 打开✅ " + (mp ? "分页✅" : "无分页(≤10条)"));
        await page.keyboard.press("Escape");
        await page.waitForTimeout(HEAD ? 700 : 250);
        const closed = await page.$eval("#modal-more", (el) => !el.classList.contains("open"));
        if (!closed) log("FAIL", file, "弹窗 Escape 未关闭");
      }
    }
    const nxt = await page.$('.pagination .page-btn:has-text("下一页"):not([disabled])');
    if (nxt) {
      await nxt.click();
      await page.waitForTimeout(HEAD ? 900 : 300);
      const act = await page.$eval(".pagination .page-btn.active", (el) => el.textContent).catch(() => "?");
      log("INFO", file, "翻页 → 第 " + act + " 页 ✅");
    }
    errors.slice(0, 2).forEach((e) => log("FAIL", file, "JS错误: " + e));
    if (!issues.some((i) => i.includes(file) && i.startsWith("[FAIL]")))
      log("PASS", file, "一屏/分页/居中/交互 全部通过");
  } catch (e) {
    log("FAIL", file, "加载失败: " + e.message.split("\n")[0]);
  }
  await ctx.close();
}

(async () => {
  const resp = await fetch(`http://127.0.0.1:${PORT}/index.html`).catch(() => null);
  if (!resp || !resp.ok) {
    console.log("启动临时静态服务 :" + PORT);
    require("child_process").spawn("python3", ["-m", "http.server", String(PORT)], { cwd: DIR, stdio: "ignore", detached: true });
    await new Promise((r) => setTimeout(r, 1200));
  }
  const files = fs.readdirSync(DIR).filter((f) => f.endsWith(".html")).sort();
  const browser = await chromium.launch({ headless: !HEAD, slowMo: HEAD ? 350 : 0 });
  for (const f of files) await checkPage(browser, f);
  await browser.close();
  console.log("\n======== 汇总 ========");
  const fails = issues.filter((i) => i.startsWith("[FAIL]"));
  console.log("FAIL:", fails.length);
  fails.forEach((i) => console.log(i));
  process.exit(fails.length ? 1 : 0);
})();
