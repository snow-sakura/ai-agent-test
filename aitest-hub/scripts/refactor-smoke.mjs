#!/usr/bin/env node
/** 门户/工具页重构冒烟：顶栏、布局壳、tab-pane、console/pageerror */
import { createRequire } from 'node:module'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const { chromium } = require('/Users/snow-sakura/.npm-global/lib/node_modules/playwright')

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const OUT = path.join(ROOT, '.playwright-mcp', 'screens', 'refactor')
fs.mkdirSync(OUT, { recursive: true })

const results = []

async function openPage(ctx, url) {
  const page = await ctx.newPage()
  const pageErrors = []
  const consoleErrors = []
  page.on('pageerror', (e) => pageErrors.push(String(e)))
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text())
  })
  await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 })
  return { page, pageErrors, consoleErrors }
}

const browser = await chromium.launch({ headless: true })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
await seedAuth(ctx)

// seed auth like loop-audit: AUTH_KEY 必须为 '1'，token 需真实 JWT 以免 API 401
async function seedAuth(ctx) {
  let token = 'refactor-smoke-fake-token'
  try {
    const res = await fetch('http://127.0.0.1:8000/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'username=admin&password=admin123',
    })
    if (res.ok) {
      const data = await res.json()
      if (data?.access_token) token = data.access_token
    }
  } catch {
    /* fallback fake */
  }
  await ctx.addInitScript(
    ([t]) => {
      localStorage.setItem('aitesthub_token', t)
      localStorage.setItem('aitesthub_auth', '1')
      localStorage.setItem('aitesthub_login_user', 'admin')
    },
    [token],
  )
  return token
}

// --- logged-in routes ---
{
  const { page, pageErrors, consoleErrors } = await openPage(ctx, BASE + '/')
  await page.screenshot({ path: path.join(OUT, '01-home-login.png'), fullPage: false })
  const topbar = await page.locator('header.topbar, .topbar').count()
  const brand = (await page.locator('.brand').first().textContent().catch(() => '')) || ''
  const tbActs = await page.locator('.tb-act').count()
  const userChip = await page.locator('.user-chip').count()
  results.push({ route: '/', topbar, brand: brand.trim().slice(0, 40), tbActs, userChip, pageErrors, consoleErrors })
  await page.close()
}

{
  const { page, pageErrors, consoleErrors } = await openPage(ctx, BASE + '/app')
  await page.screenshot({ path: path.join(OUT, '02-app.png'), fullPage: true })
  const topbar = await page.locator('header.topbar, .topbar').count()
  const hub = await page.locator('.hub, .container.page.hub').count()
  const cards = await page.locator('.tool-card').count()
  const tbActs = await page.locator('.tb-act').count()
  results.push({ route: '/app', topbar, hub, cards, tbActs, pageErrors, consoleErrors })
  await page.close()
}

{
  const { page, pageErrors, consoleErrors } = await openPage(ctx, BASE + '/prompts')
  await page.screenshot({ path: path.join(OUT, '03-prompts.png'), fullPage: true })
  const topbar = await page.locator('header.topbar, .topbar').count()
  const sidebar = await page.locator('aside.sidebar').count()
  const main = await page.locator('main.main-area').count()
  const tabs = await page.locator('.tabs .tab').count()
  const sideItems = await page.locator('aside.sidebar .side-item').count()
  const modBack = await page.locator('aside.sidebar .mod-back').count()
  const tabsHidden = await page.locator('.tabs').evaluate((el) => getComputedStyle(el).display === 'none')
  const panes = await page.locator('.tab-pane').count()
  const visiblePanes = await page.locator('.tab-pane:visible').count()
  const inlineDisplay = await page.evaluate(() =>
    [...document.querySelectorAll('.tab-pane')].map((el) => el.getAttribute('style') || ''),
  )
  // switch tab via injected sidebar (design hides main .tabs)
  await page.locator('aside.sidebar .side-item').nth(1).click()
  await page.waitForTimeout(200)
  const afterSwitch = await page.locator('.tab-pane:visible').count()
  const favBanner = await page.locator('.banner:visible').count()
  const activeSide = await page.locator('aside.sidebar .side-item.active .si-txt').textContent()
  await page.screenshot({ path: path.join(OUT, '03b-prompts-favs.png'), fullPage: false })
  results.push({
    route: '/prompts',
    topbar,
    sidebar,
    main,
    tabs,
    sideItems,
    modBack,
    tabsHidden,
    panes,
    visiblePanes,
    inlineDisplay,
    afterSwitch,
    favBanner,
    activeSide: (activeSide || '').trim(),
    pageErrors,
    consoleErrors,
  })
  await page.close()
}

{
  const { page, pageErrors, consoleErrors } = await openPage(ctx, BASE + '/t/tool-test-cases')
  await page.screenshot({ path: path.join(OUT, '04-tool.png'), fullPage: false })
  const topbar = await page.locator('header.topbar, .topbar').count()
  const sidebar = await page.locator('aside.sidebar').count()
  const breadcrumb = await page.locator('.breadcrumb').count()
  const pageHead = await page.locator('.page-head').count()
  const sideItems = await page.locator('.side-item').count()
  const modBack = await page.locator('.mod-back').count()
  results.push({
    route: '/t/tool-test-cases',
    topbar,
    sidebar,
    breadcrumb,
    pageHead,
    sideItems,
    modBack,
    pageErrors,
    consoleErrors,
  })
  await page.close()
}

{
  const { page, pageErrors, consoleErrors } = await openPage(ctx, BASE + '/t/tool-api-testing?tab=run')
  await page.screenshot({ path: path.join(OUT, '05-tool-tab.png'), fullPage: false })
  const activeSide = await page
    .locator('.side-item.active .si-txt')
    .first()
    .textContent()
    .catch(() => null)
  const activeCount = await page.locator('.side-item.active').count()
  results.push({ route: '/t/tool-api-testing?tab=run', activeSide, activeCount, pageErrors, consoleErrors })
  await page.close()
}

{
  const { page, pageErrors, consoleErrors } = await openPage(ctx, BASE + '/t/tool-requirement-management')
  await page.screenshot({ path: path.join(OUT, '06-tool-req.png'), fullPage: false })
  const topbar = await page.locator('header.topbar').count()
  const sideItems = await page.locator('.side-item').count()
  results.push({ route: '/t/tool-requirement-management', topbar, sideItems, pageErrors, consoleErrors })
  await page.close()
}

// --- logged-out pages (separate context) ---
const ctx2 = await browser.newContext({ viewport: { width: 1440, height: 900 } })
{
  const { page, pageErrors, consoleErrors } = await openPage(ctx2, BASE + '/auth')
  await page.screenshot({ path: path.join(OUT, '07-auth.png'), fullPage: false })
  const authWrap = await page.locator('.auth-wrap').count()
  const topbar = await page.locator('header.topbar, .topbar').count()
  results.push({ route: '/auth', authWrap, topbar, pageErrors, consoleErrors })
  await page.close()
}
{
  const { page, pageErrors, consoleErrors } = await openPage(ctx2, BASE + '/register')
  await page.screenshot({ path: path.join(OUT, '08-register.png'), fullPage: false })
  const authWrap = await page.locator('.auth-wrap').count()
  const topbar = await page.locator('header.topbar, .topbar').count()
  results.push({ route: '/register', authWrap, topbar, pageErrors, consoleErrors })
  await page.close()
}
{
  const { page, pageErrors, consoleErrors } = await openPage(ctx2, BASE + '/')
  await page.screenshot({ path: path.join(OUT, '09-home-guest.png'), fullPage: false })
  const topbar = await page.locator('header.topbar').count()
  const ctaLogin = await page.locator('a[href="/auth"]').count()
  const ctaRegister = await page.locator('a[href="/register"]').count()
  results.push({ route: '/ (guest)', topbar, ctaLogin, ctaRegister, pageErrors, consoleErrors })
  await page.close()
}

await browser.close()

const report = { at: new Date().toISOString(), results }
const reportPath = path.join(ROOT, '.playwright-mcp', 'refactor-smoke.json')
fs.writeFileSync(reportPath, JSON.stringify(report, null, 2))
console.log(JSON.stringify(results, null, 2))

let fail = 0
for (const r of results) {
  const errs = (r.pageErrors || []).length + (r.consoleErrors || []).filter((c) => !c.includes('favicon')).length
  if (errs) {
    fail++
    console.error('FAIL', r.route, r.pageErrors, r.consoleErrors)
  }
}

// structural assertions
function assert(cond, msg) {
  if (!cond) {
    fail++
    console.error('ASSERT', msg)
  }
}
const by = Object.fromEntries(results.map((r) => [r.route, r]))
assert(by['/']?.topbar >= 1, '/ needs topbar')
assert(by['/ (guest)']?.topbar >= 1, '/ guest needs topbar')
assert(by['/ (guest)']?.ctaLogin >= 1, '/ guest needs login CTA')
assert(by['/app']?.topbar >= 1, '/app needs topbar')
assert(by['/app']?.cards > 0, '/app needs cards')
assert(by['/prompts']?.topbar >= 1, '/prompts needs topbar')
assert(by['/prompts']?.sidebar >= 1, '/prompts needs sidebar')
assert(by['/prompts']?.sideItems >= 3, '/prompts needs injected side nav')
assert(by['/prompts']?.modBack >= 1, '/prompts needs mod-back')
assert(by['/prompts']?.tabsHidden === true, '/prompts main tabs hidden when sidebar injected')
assert(by['/prompts']?.main >= 1, '/prompts needs main')
assert(by['/prompts']?.inlineDisplay?.every((s) => !s.includes('display:block')), '/prompts tab-pane no inline display:block')
assert(by['/prompts']?.afterSwitch === 1, '/prompts exactly one pane after switch')
assert(by['/prompts']?.favBanner >= 1, '/prompts favs banner after switch')
assert(
  (by['/prompts']?.activeSide || '').includes('收藏'),
  '/prompts sidebar click should activate 我的收藏',
)
assert(by['/t/tool-test-cases']?.topbar >= 1, 'tool needs topbar')
assert(by['/t/tool-test-cases']?.sidebar >= 1, 'tool needs sidebar')
assert(by['/t/tool-test-cases']?.sideItems > 0, 'tool needs side items')
assert(by['/t/tool-test-cases']?.breadcrumb >= 1, 'tool needs breadcrumb')
assert(by['/t/tool-api-testing?tab=run']?.activeSide, 'tool tab query needs active side item')
assert(
  (by['/t/tool-api-testing?tab=run']?.activeSide || '').includes('用例') ||
    (by['/t/tool-api-testing?tab=run']?.activeCount || 0) === 1,
  'tool tab=run should activate 用例执行',
)
assert(by['/auth']?.authWrap >= 1, '/auth needs auth-wrap')
assert(by['/auth']?.topbar === 0, '/auth must not have topbar')
assert(by['/register']?.authWrap >= 1, '/register needs auth-wrap')
assert(by['/register']?.topbar === 0, '/register must not have topbar')

if (fail) {
  console.error('REFactor smoke FAIL count=' + fail)
  process.exit(1)
}
console.log('REFACTOR_SMOKE_OK', reportPath)
