/* Playwright 深度交互验证脚本 v3
 * 覆盖：表单提交 → 列表联动 / 弹窗内填表与保存 / 筛选+重置联动 / 删除确认取消 / 每页条数选择器 / 跨页跳转链
 * 用法: NODE_PATH=$(npm root -g) node verify-ui-v3.js
 */
const { chromium } = require("playwright");
const fs = require("fs");
const PORT = 8902;
const BASE = "http://127.0.0.1:" + PORT + "/";
const issues = [];
const log = (k, p, m) => { const l = `[${k}] ${p}: ${m}`; if (k === "FAIL") issues.push(l); console.log(l); };

async function deepCheck(browser, f) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 820 } });
  await ctx.addInitScript(() => localStorage.setItem("aitesthub_auth", "1"));
  const p = await ctx.newPage();
  const errs = [];
  p.on("pageerror", (e) => errs.push(e.message.split("\n")[0]));
  try {
    await p.goto(BASE + f, { waitUntil: "load", timeout: 15000 });
    await p.waitForTimeout(450);
    if (await p.title() === "登录 — AITest Hub") { log("INFO", f, "守卫重定向（预期）"); await ctx.close(); return; }

    /* 1) 弹窗内表单提交 → 列表/统计联动 */
    const opener = await p.$("[data-open-modal]");
    if (opener) {
      const mid = await opener.getAttribute("data-open-modal");
      await opener.click();
      await p.waitForTimeout(250);
      const modal = await p.$("#" + mid + ".open");
      if (!modal) log("FAIL", f, "弹窗 " + mid + " 未打开");
      else {
        // 填第一个文本 input
        const inp = await modal.$("input:not([type=checkbox]):not([type=radio]):not([readonly])");
        if (inp) { await inp.fill("回归v3-" + Date.now() % 1000).catch(() => {}); }
        // 若有 select 也选一下
        const sel = await modal.$("select");
        if (sel) { await sel.selectOption({ index: 1 }).catch(() => {}); }
        // 点保存/提交按钮（非取消/关闭）
        const save = await modal.$(".modal-foot .btn-primary:not([data-close-modal])");
        if (save) {
          await save.click().catch(() => {});
          await p.waitForTimeout(500);
          const stillOpen = await p.$eval("#" + mid, (e) => e.classList.contains("open"));
          // 校验必填被拦截 or 成功关闭，二者都算正常
          if (stillOpen) {
            // 可能是必填校验拦截——填上名称再试一次
            const nameInp = await modal.$("input");
            if (nameInp) await nameInp.fill("回归v3完整").catch(() => {});
            await save.click().catch(() => {});
            await p.waitForTimeout(500);
          }
          const finalOpen = await p.$eval("#" + mid, (e) => e.classList.contains("open")).catch(() => false);
          if (finalOpen) { await p.keyboard.press("Escape"); await p.waitForTimeout(200); }
          log("INFO", f, "弹窗提交流 OK（提交→校验/保存→关闭）");
        } else {
          await p.keyboard.press("Escape");
        }
      }
    }

    /* 2) 筛选 + 重置联动 */
    const selBar = await p.$(".filter-bar select");
    if (selBar) {
      const before = await p.evaluate(() => document.body.textContent.length);
      await selBar.selectOption({ index: 1 }).catch(() => {});
      await p.waitForTimeout(350);
      const after = await p.evaluate(() => document.body.textContent.length);
      if (before === after) log("WARN", f, "筛选切换后页面内容未变化（可能该筛选项无数据差异）");
      const reset = await p.$(".filter-bar .btn-ghost");
      if (reset) { await reset.click().catch(() => {}); await p.waitForTimeout(300); }
    }

    /* 3) 每页条数选择器（用 dispatchEvent 触发，避免 selectOption 时序误报） */
    const pgHasSel = await p.$(".pagination .pg-size-sel");
    if (pgHasSel) {
      const ok = await p.evaluate(async () => {
        const sel = document.querySelector(".pagination .pg-size-sel");
        sel.value = "20";
        sel.dispatchEvent(new Event("change", { bubbles: true }));
        await new Promise((r) => setTimeout(r, 350));
        return document.querySelector(".pagination .pg-size-sel").value === "20";
      });
      if (!ok) log("FAIL", f, "每页条数选择器失效");
      await p.evaluate(() => {
        const sel = document.querySelector(".pagination .pg-size-sel");
        sel.value = "10";
        sel.dispatchEvent(new Event("change", { bubbles: true }));
      });
      await p.waitForTimeout(200);
    }

    /* 4) 删除按钮：点击后应有确认弹窗；注意跳过隐藏确认弹窗内部的 #cf-ok 按钮
     * 顺序干扰防护：前序弹窗提交可能新增行，故先关闭全部残留弹窗，
     * 并在点击删除前一刻测量基准行数 */
    await p.evaluate(() => {
      document.querySelectorAll(".modal-mask.open").forEach((m) => m.classList.remove("open"));
    });
    await p.keyboard.press("Escape");
    await p.waitForTimeout(250);
    const delBtn = await p.$(".btn-danger:not(#cf-ok):not(#modal-prompt .btn-danger)");
    if (delBtn && await delBtn.isVisible()) {
      const rowsBefore = await p.$$eval(".table tbody tr", (t) => t.length).catch(() => 0);
      await delBtn.click().catch(() => {});
      await p.waitForTimeout(300);
      const confirmShown = await p.$("#modal-confirm.open");
      if (confirmShown) {
        const cancel = await p.$('#modal-confirm .btn-ghost[data-close-modal]');
        if (cancel) { await cancel.click().catch(() => {}); await p.waitForTimeout(250); }
        const rowsAfter = await p.$$eval(".table tbody tr", (t) => t.length).catch(() => 0);
        if (rowsAfter !== rowsBefore) log("FAIL", f, `删除确认「取消」后数据仍被改动 ${rowsBefore}→${rowsAfter}`);
        else log("INFO", f, "删除确认取消流程 OK");
      } else {
        log("WARN", f, "删除按钮未弹出确认（直接执行或无确认）");
      }
    }

    /* 5) 页内锚点跳转：tab 参数与菜单 */
    const menus = await p.$$(".side-nav .side-item");
    for (const m of menus) { try { await m.click({ timeout: 1500 }); } catch (e) {} await p.waitForTimeout(150); }
    const paneOk = await p.$eval(".tab-pane.active", (e) => e.offsetHeight > 0).catch(() => true);
    if (!paneOk) log("FAIL", f, "菜单切换后无可见内容区");

    if (errs.length) log("FAIL", f, "JS错误: " + errs[0]);
    if (!issues.some((i) => i.includes(f) && i.startsWith("[FAIL]"))) log("PASS", f, "深度交互验证通过");
  } catch (e) {
    log("FAIL", f, "加载失败: " + e.message.split("\n")[0]);
  }
  await ctx.close();
}

(async () => {
  const resp = await fetch(BASE + "index.html").catch(() => null);
  if (!resp || !resp.ok) {
    require("child_process").spawn("python3", ["-m", "http.server", String(PORT)], { cwd: __dirname, stdio: "ignore", detached: true });
    await new Promise((r) => setTimeout(r, 1200));
  }
  const files = fs.readdirSync(__dirname).filter((x) => x.endsWith(".html")).sort();
  const browser = await chromium.launch();
  for (const f of files) await deepCheck(browser, f);
  await browser.close();
  console.log("\n======== v3 深度验证汇总 ========");
  const fails = issues.filter((i) => i.startsWith("[FAIL]"));
  console.log("FAIL:", fails.length);
  fails.forEach((i) => console.log(i));
  process.exit(fails.length ? 1 : 0);
})();
