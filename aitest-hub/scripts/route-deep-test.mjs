#!/usr/bin/env node
/**
 * 32 路由深度集成测试（任务 1）
 *
 * Part A 访客守卫：未登录访问受保护路由应重定向 /auth?redirect=...
 * Part B 登录态 32 路由扫描：pathname/标题/壳结构/正文非空/无移植占位/无 JS 错误
 * Part C 深度交互：
 *   - /app 四分组全遍历（?tab= 同步 + active + 卡片）+ 卡片覆盖全部 27 工具
 *   - /prompts 侧栏 3 项 + 搜索 API 往返 + 分页 + 每页条数切换
 *   - 27 工具页：面包屑/页头/侧栏项数 = catalog tabs 数、?tab= 深链激活、侧栏点击切 tab
 *
 * 用法: node scripts/route-deep-test.mjs [--only /prompts,/t/tool-api-testing]
 * 依赖: vite @127.0.0.1:5173 + api @127.0.0.1:8000（需真实登录）
 */
import { createRequire } from 'node:module'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const { chromium } = require('/Users/snow-sakura/.npm-global/lib/node_modules/playwright')

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const API = process.env.API_URL || 'http://127.0.0.1:8000'
const OUT = path.join(ROOT, '.playwright-mcp', 'screens', 'deep')
const REPORT = path.join(ROOT, '.playwright-mcp', 'route-deep-test.json')
fs.mkdirSync(OUT, { recursive: true })

const args = process.argv.slice(2)
const oi = args.indexOf('--only')
const only = oi >= 0 && args[oi + 1] ? args[oi + 1].split(',').map((s) => s.trim()) : null

/* ---------- 路由清单（与 ui-pixel-diff 一致的 32 条） ---------- */
const catSrc = fs.readFileSync(path.join(ROOT, 'frontend/src/data/catalog.ts'), 'utf8')
const ki = catSrc.indexOf('TOOL_CATALOG')
const CATALOG = JSON.parse(catSrc.slice(catSrc.indexOf('[{', ki), catSrc.lastIndexOf(']') + 1))

const ROUTES = [
  { path: '/', type: 'home', title: 'AITest Hub — AI 驱动的测试与质量工具聚合平台' },
  { path: '/auth', type: 'auth', title: '登录 — AITest Hub' },
  { path: '/register', type: 'register', title: '注册 — AITest Hub' },
  { path: '/app', type: 'hub', title: '工具台首页 — AITest Hub' },
  { path: '/prompts', type: 'prompts', title: '提示词库 — AITest Hub' },
  ...CATALOG.map((t) => ({ path: '/t/' + t.slug, type: 'tool', title: t.title, def: t })),
]
if (ROUTES.length !== 32) {
  console.error('路由清单应为 32 条，实际', ROUTES.length)
  process.exit(2)
}
const targets = only ? ROUTES.filter((r) => only.some((o) => r.path.includes(o))) : ROUTES

/* ---------- 断言收集 ---------- */
const routeResults = []
let pass = 0
let fail = 0

function makeChecker(route) {
  const checks = []
  return {
    checks,
    chk(name, ok, detail = '') {
      if (ok) pass++
      else {
        fail++
        console.error(`  ✗ ${name}${detail ? ' — ' + detail : ''}`)
      }
      checks.push({ name, ok, detail })
      return ok
    },
  }
}

function tabText(label) {
  if (!label) return ''
  const cp = label.codePointAt(0)
  return label.slice(String.fromCodePoint(cp).length).trim()
}

/* ---------- 真实登录（demo 账号，失败即退出：401 会导致守卫误判） ---------- */
async function login() {
  const body = new URLSearchParams({
    username: process.env.DEMO_ACCOUNT || 'demo_tester',
    phone: process.env.DEMO_ACCOUNT || 'demo_tester',
    password: process.env.DEMO_PASSWORD || 'Demo@2026',
  })
  try {
    const res = await fetch(API + '/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    })
    const data = await res.json()
    if (data.access_token) return data.access_token
    console.error('LOGIN_FAILED', JSON.stringify(data).slice(0, 200))
  } catch (e) {
    console.error('LOGIN_ERROR', String(e).slice(0, 200))
  }
  return null
}

/* ---------- 打开页面并收集错误 ---------- */
const RESOURCE_NOISE = /favicon|Failed to load resource|net::ERR|Reporting API|Download the React DevTools/i

async function openPage(ctx, url) {
  const page = await ctx.newPage()
  const pageErrors = []
  const jsErrs = []
  const resErrs = []
  page.on('pageerror', (e) => pageErrors.push(String(e).slice(0, 200)))
  page.on('console', (m) => {
    if (m.type() !== 'error') return
    const t = m.text()
    if (RESOURCE_NOISE.test(t)) resErrs.push(t.slice(0, 160))
    else jsErrs.push(t.slice(0, 200))
  })
  page.on('response', (r) => {
    try {
      if (r.url().includes('/api/') && r.status() >= 400) {
        resErrs.push(`HTTP ${r.status()} ${r.url().replace(BASE, '')}`)
      }
    } catch {
      /* ignore */
    }
  })
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 20000 })
  await page.waitForSelector('.topbar, .auth-wrap', { timeout: 10000 }).catch(() => {})
  await page.waitForTimeout(450)
  return { page, pageErrors, jsErrs, resErrs }
}

const shot = (page, name) =>
  page.screenshot({ path: path.join(OUT, name + '.png'), fullPage: false }).catch(() => {})

/* ================= 主流程 ================= */
const token = await login()
if (!token) {
  console.error('DEEP_TEST_ABORT: 无法登录，中止（避免 401 守卫干扰）')
  process.exit(2)
}

const browser = await chromium.launch({ headless: true })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
await ctx.addInitScript(
  ([t]) => {
    localStorage.setItem('aitesthub_token', t)
    localStorage.setItem('aitesthub_auth', '1')
    localStorage.setItem('aitesthub_login_user', 'admin')
  },
  [token],
)

/* ---------- Part A：访客守卫 ---------- */
console.log('== Part A 访客守卫 ==')
{
  const gctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const guard = makeChecker({ path: 'guest-guard' })

  for (const p of ['/app', '/prompts', '/t/tool-test-cases']) {
    const page = await gctx.newPage()
    await page.goto(BASE + p, { waitUntil: 'domcontentloaded', timeout: 20000 })
    const redirected = await page
      .waitForURL('**/auth*', { timeout: 6000 })
      .then(() => page.url())
      .catch(() => page.url())
    const hasRedirect = decodeURIComponent(redirected).includes('redirect=' + p)
    guard.chk(`守卫 ${p} → /auth?redirect=`, redirected.includes('/auth') && hasRedirect, redirected)
    await page.close()
  }
  for (const p of ['/', '/auth', '/register']) {
    const page = await gctx.newPage()
    await page.goto(BASE + p, { waitUntil: 'domcontentloaded', timeout: 20000 })
    await page.waitForTimeout(400)
    const pathName = new URL(page.url()).pathname
    guard.chk(`公开页 ${p} 不被重定向`, pathName === p, page.url())
    const wrap = await page.locator('.auth-wrap, .home-hero').count()
    if (p !== '/') guard.chk(`公开页 ${p} 有 auth-wrap`, wrap >= 1)
    else guard.chk('公开页 / 有 home-hero', wrap >= 1)
    await page.close()
  }
  routeResults.push({ route: 'guest-guard (Part A)', checks: guard.checks })
  await gctx.close()
}

/* ---------- Part B/C：32 路由深度扫描 ---------- */
for (const r of targets) {
  const isTool = r.type === 'tool'
  const slug = r.path.replace(/^\//, '').replace(/\//g, '-') || 'home'
  console.log(`== ${r.path} ==`)
  const c = makeChecker(r)
  let page
  try {
    const opened = await openPage(ctx, BASE + r.path)
    page = opened.page
    const { pageErrors, jsErrs, resErrs } = opened

    // --- 通用：pathname（未被意外重定向，如 401→/auth） ---
    const pn = new URL(page.url()).pathname
    c.chk('pathname 保持', pn === r.path, `expect ${r.path} got ${pn}`)

    // --- 通用：标题 ---
    const title = await page.title()
    if (isTool) c.chk('title 含工具名', title.startsWith(r.title), title)
    else c.chk('title 精确匹配', title === r.title, title)

    // --- 通用：壳 ---
    if (r.type === 'auth' || r.type === 'register') {
      c.chk('auth-wrap 存在', (await page.locator('.auth-wrap').count()) >= 1)
      c.chk('表单输入 >= 2', (await page.locator('form input').count()) >= 2)
      c.chk('提交按钮存在', (await page.locator('form button[type="submit"]').count()) >= 1)
    } else {
      c.chk('.topbar 存在', (await page.locator('.topbar').count()) >= 1)
    }

    // --- 通用：正文非空 + 无移植占位 ---
    const bodyText = await page.evaluate(() => document.body.innerText)
    c.chk('正文 >= 100 字符', bodyText.replace(/\s+/g, '').length >= 100, `len=${bodyText.length}`)
    c.chk('无「移植中」占位', !bodyText.includes('移植中'))

    // --- 通用：无 JS 错误 ---
    c.chk('无 pageerror', pageErrors.length === 0, pageErrors.join(';'))
    c.chk('无 console JS 错误', jsErrs.length === 0, jsErrs.join(';'))

    // --- 类型专属 ---
    if (r.type === 'home') {
      c.chk('home-hero 存在', (await page.locator('.home-hero').count()) >= 1)
      c.chk('hero CTA 登录链接', (await page.locator('.hero-actions a[href="/auth"]').count()) >= 1)
      c.chk('登录态 user-chip', (await page.locator('.user-chip').count()) >= 1)
    }

    if (r.type === 'hub') {
      const tabSel = '.hub-tabs .tab, .tabs.hub-tabs .tab'
      const n = await page.locator(tabSel).count()
      c.chk('hub 分组 tab = 4', n === 4, `got ${n}`)
      const hrefs = new Set()
      for (let i = 0; i < n; i++) {
        const tab = page.locator(tabSel).nth(i)
        await tab.click()
        await page.waitForTimeout(300)
        const activeIdx = await page
          .locator(tabSel)
          .evaluateAll((els) => els.findIndex((e) => e.classList.contains('active')))
        c.chk(`分组[${i}] 点击后 active`, activeIdx === i, `activeIdx=${activeIdx}`)
        c.chk(`分组[${i}] ?tab= 同步`, /[?&]tab=/.test(page.url()), page.url().replace(BASE, ''))
        const cards = await page.locator('.tool-card').count()
        c.chk(`分组[${i}] 卡片 > 0`, cards > 0, `cards=${cards}`)
        const hs = await page.locator('.tc-enter').evaluateAll((els) =>
          els.map((e) => e.getAttribute('href')),
        )
        for (const h of hs) if (h && h.startsWith('/t/')) hrefs.add(h.slice(3))
      }
      const missing = CATALOG.map((t) => t.slug).filter((s) => !hrefs.has(s))
      c.chk('卡片覆盖全部 27 工具', missing.length === 0, 'missing: ' + missing.join(','))
    }

    if (r.type === 'prompts') {
      c.chk('侧栏 side-item = 3', (await page.locator('aside.sidebar .side-item').count()) === 3)
      c.chk('mod-back 返回入口', (await page.locator('aside.sidebar .mod-back').count()) >= 1)
      const tabsHidden = await page
        .locator('.prompts-view .tabs')
        .first()
        .evaluate((el) => getComputedStyle(el).display === 'none')
        .catch(() => false)
      c.chk('主区 .tabs 按设计隐藏', tabsHidden === true)
      c.chk('可见 pane 恰好 1', (await page.locator('.tab-pane:visible').count()) === 1)

      // 搜索：应触发 /api/prompts?q= 往返
      const respP = page
        .waitForResponse((x) => x.url().includes('/api/prompts?') && x.url().includes('q='), {
          timeout: 6000,
        })
        .catch(() => null)
      const cntBefore = await page.locator('.filter-bar .text-faint').first().textContent().catch(() => '')
      await page.fill('.prompts-pane .input.search, .input.search', '用例')
      const resp = await respP
      c.chk('搜索触发 GET /api/prompts?q=', !!resp && resp.status() === 200, resp ? 'HTTP ' + resp.status() : 'no response')
      await page.waitForTimeout(300)
      const cntAfter = await page.locator('.filter-bar .text-faint').first().textContent().catch(() => '')
      c.chk('搜索结果计数更新', !!cntAfter && cntAfter.includes('共'), `${cntBefore} → ${cntAfter}`)
      // 清空恢复
      const resp2P = page
        .waitForResponse((x) => x.url().includes('/api/prompts?'), { timeout: 6000 })
        .catch(() => null)
      await page.fill('.prompts-pane .input.search, .input.search', '')
      await resp2P
      await page.waitForTimeout(300)

      // 分页（数据足够时）
      const info = await page.locator('.prompts-pager .page-info').first().textContent().catch(() => '')
      const m = (info || '').match(/共\s*(\d+)\s*条\s*·\s*第\s*(\d+)\/(\d+)\s*页/)
      c.chk('分页信息可解析', !!m, info || '(empty)')
      if (m && Number(m[3]) >= 2) {
        await page.locator('.prompts-pager .page-btn').filter({ hasText: /^2$/ }).click()
        await page.waitForTimeout(300)
        const info2 = await page.locator('.prompts-pager .page-info').first().textContent().catch(() => '')
        c.chk('翻到第 2 页', (info2 || '').includes('第 2/'), info2)
        const rows = await page.locator('.prompt-card').count()
        c.chk('第 2 页卡片 > 0', rows > 0, `rows=${rows}`)
      } else if (m) {
        c.chk('数据单页（跳过翻页）', true, `pages=${m[3]}`)
      }
      // 每页条数切换（仅当总条数 > 6 时有意义）
      if (m && Number(m[1]) > 6) {
        await page.selectOption('.prompts-pager .pg-size-sel', '10')
        await page.waitForTimeout(300)
        const rows10 = await page.locator('.prompt-card').count()
        c.chk('每页 10 条生效', rows10 === 10 || rows10 === Math.min(10, Number(m[1])), `rows=${rows10}`)
        await page.selectOption('.prompts-pager .pg-size-sel', '6')
        await page.waitForTimeout(200)
      } else if (m) {
        c.chk('总条数 ≤ 6（跳过每页切换）', true, `total=${m[1]}`)
      }

      // 侧栏切 pane
      await page.locator('aside.sidebar .side-item').filter({ hasText: '收藏' }).click()
      await page.waitForTimeout(300)
      const activeTxt = (await page.locator('aside.sidebar .side-item.active .si-txt').first().textContent()) || ''
      c.chk('侧栏切到我的收藏', activeTxt.includes('收藏'), activeTxt)
      c.chk('切后可见 pane 恰好 1', (await page.locator('.tab-pane:visible').count()) === 1)
    }

    if (isTool) {
      const def = r.def
      const bc = (await page.locator('.main-area .breadcrumb').first().textContent().catch(() => '')) || ''
      c.chk('面包屑含工具名', bc.includes(def.title), bc.trim().slice(0, 60))
      const h1 = (await page.locator('.page-head h1').first().textContent().catch(() => '')) || ''
      c.chk('页头 h1 含工具名', h1.includes(def.title), h1.trim().slice(0, 60))
      c.chk('mod-back 返回入口', (await page.locator('.sidebar .mod-back').count()) >= 1)

      const sideN = await page.locator('.side-nav .side-item').count()
      const expectN = Math.max(1, def.tabs.length)
      c.chk(`侧栏项 = ${expectN}（tabs=${def.tabs.length}）`, sideN === expectN, `got ${sideN}`)

      const mainTxt = await page.locator('.main-area').innerText().catch(() => '')
      c.chk('内容区正文 >= 30 字', mainTxt.replace(/\s+/g, '').length >= 30, `len=${mainTxt.length}`)

      if (def.tabs.length >= 2) {
        const t2 = def.tabs[1]
        const t1 = def.tabs[0]
        // ?tab= 深链
        await page.goto(`${BASE}${r.path}?tab=${t2.key}`, {
          waitUntil: 'domcontentloaded',
          timeout: 20000,
        })
        await page.waitForSelector('.side-nav .side-item', { timeout: 8000 }).catch(() => {})
        await page.waitForTimeout(350)
        const act2 =
          (await page.locator('.side-item.active .si-txt').first().textContent().catch(() => '')) || ''
        const nAct = await page.locator('.side-item.active').count()
        c.chk(`?tab=${t2.key} 激活「${tabText(t2.label)}」`, nAct === 1 && act2 === tabText(t2.label), `active="${act2}" n=${nAct}`)
        // 侧栏点击切回第一个 tab
        await page.locator('.side-nav .side-item').first().click()
        await page.waitForTimeout(300)
        c.chk(`侧栏点击 → ?tab=${t1.key}`, page.url().includes(`tab=${t1.key}`), page.url().replace(BASE, ''))
        const act1 =
          (await page.locator('.side-item.active .si-txt').first().textContent().catch(() => '')) || ''
        c.chk(`点击后激活「${tabText(t1.label)}」`, act1 === tabText(t1.label), `active="${act1}"`)
        const main2 = await page.locator('.main-area').innerText().catch(() => '')
        c.chk('切 tab 后内容仍非空', main2.replace(/\s+/g, '').length >= 30, `len=${main2.length}`)
      } else {
        c.chk('单 tab（跳过深链切换）', true, `tabs=${def.tabs.length}`)
      }
    }

    // 资源/API 4xx（记录不判失败，最终报告展示）
    if (resErrs.length) console.log('  [api/resource]', resErrs.slice(0, 5).join(' | '))

    await shot(page, slug)
  } catch (e) {
    fail++
    c.checks.push({ name: 'route exception', ok: false, detail: String(e).slice(0, 200) })
    console.error('  ✗ EXCEPTION', String(e).slice(0, 200))
  } finally {
    if (page) await page.close().catch(() => {})
  }
  const bad = c.checks.filter((x) => !x.ok).length
  routeResults.push({ route: r.path, checks: c.checks, ok: bad === 0 })
  console.log(`  ${bad === 0 ? '✓' : '✗'} ${r.path}  ${c.checks.length - bad}/${c.checks.length}`)
}

await browser.close()

const report = {
  at: new Date().toISOString(),
  pass,
  fail,
  ok: fail === 0,
  routes: routeResults,
}
fs.writeFileSync(REPORT, JSON.stringify(report, null, 2))

console.log('\n==== DEEP TEST SUMMARY ====')
console.log(`checks: pass=${pass} fail=${fail}  routes=${routeResults.length}`)
for (const r of routeResults) {
  const bad = r.checks.filter((x) => !x.ok)
  if (bad.length) console.log(`  FAIL ${r.route}: ${bad.map((x) => x.name).join('; ')}`)
}
console.log('Report:', REPORT)
if (fail) {
  console.log('ROUTE_DEEP_TEST_FAIL count=' + fail)
  process.exit(1)
}
console.log('ROUTE_DEEP_TEST_OK', routeResults.length, 'routes')
