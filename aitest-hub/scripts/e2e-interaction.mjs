#!/usr/bin/env node
/**
 * E2E 交互用例：
 *  1) 登录流：/auth 表单校验 → 成功登录 → 落地 /app 且写入 localStorage
 *  2) /app hub 分组 tab：点击切换 + ?tab= query 同步
 *  3) /prompts 侧栏注入导航：切换 tab（favs）
 *  4) /t/tool-api-testing 侧栏 tab：?tab=run 激活 + 点击切换
 *  5) 退出登录：清空 auth 回到访客态
 *
 * 用法: node scripts/e2e-interaction.mjs
 * 依赖: vite @127.0.0.1:5173 + api @127.0.0.1:8000
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
const OUT = path.join(ROOT, '.playwright-mcp', 'screens', 'e2e')
fs.mkdirSync(OUT, { recursive: true })

const results = []
let fail = 0

function assert(cond, msg) {
  if (!cond) {
    fail++
    console.error('ASSERT FAIL:', msg)
    results.push({ ok: false, msg })
  } else {
    results.push({ ok: true, msg })
  }
}

async function openTracked(ctx, url) {
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

// ========== 1) 登录流 ==========
{
  const { page, pageErrors, consoleErrors } = await openTracked(ctx, BASE + '/auth')
  await page.screenshot({ path: path.join(OUT, '01-auth-empty.png') })

  const submitBtn = () => page.locator('form button[type="submit"]').first()

  // 空表单提交 → 手机号校验
  await submitBtn().click()
  await page.waitForTimeout(300)
  const phoneErr = await page.locator('.field.has-err .err-msg:visible').count()
  assert(phoneErr >= 1, `登录空表单应显示字段校验错误，实际 ${phoneErr}`)
  await page.screenshot({ path: path.join(OUT, '02-auth-validation.png') })

  // 错误密码
  await page.fill('#account', process.env.DEMO_ACCOUNT || 'demo_tester')
  await page.fill('#password', 'wrong-password-xxx')
  await submitBtn().click()
  await page.waitForTimeout(800)
  const badPw =
    (await page
      .locator('#password')
      .locator('xpath=ancestor::div[contains(@class,"field")]//div[contains(@class,"err-msg")]')
      .first()
      .textContent()
      .catch(() => '')) || ''
  const toastText = (await page.locator('.toast').allTextContents().catch(() => [])).join('|')
  assert(
    badPw.includes('账号或密码') || toastText.length > 0,
    `错误密码应提示失败，field="${badPw}" toast="${toastText}"`,
  )
  assert(!page.url().includes('/app'), '错误密码不应跳转 /app')
  await page.screenshot({ path: path.join(OUT, '03-auth-bad-pw.png') })

  // 正确凭据（演示手机号）
  await page.fill('#account', process.env.DEMO_ACCOUNT || 'demo_tester')
  await page.fill('#password', process.env.DEMO_PASSWORD || 'Demo@2026')
  await submitBtn().click()
  await page.waitForURL('**/app', { timeout: 15000 }).catch(() => {})
  await page.waitForTimeout(500)
  const url = page.url()
  assert(url.includes('/app'), `登录成功应跳转 /app，实际 ${url}`)

  const ls = await page.evaluate(() => ({
    token: localStorage.getItem('aitesthub_token'),
    auth: localStorage.getItem('aitesthub_auth'),
    user: localStorage.getItem('aitesthub_login_user'),
  }))
  assert(!!ls.token && ls.token.split('.').length === 3, '登录后应写入 JWT token')
  assert(ls.auth === '1', "aitesthub_auth 必须为 '1'")
  assert(!!ls.user, '登录后应写入 login_user')

  const topbar = await page.locator('.topbar').count()
  const userChip = await page.locator('.user-chip').count()
  assert(topbar >= 1, '/app 登录态需有 topbar')
  assert(userChip >= 1, '/app 登录态需有 user-chip')
  assert(pageErrors.length === 0, `登录后无 pageerror: ${pageErrors.join(';')}`)
  await page.screenshot({ path: path.join(OUT, '04-app-after-login.png'), fullPage: false })
  await page.close()
}

// ========== 2) /app hub 分组 tab ==========
{
  const { page, pageErrors } = await openTracked(ctx, BASE + '/app')
  const tabs = await page.locator('.hub-tabs .tab, .tabs.hub-tabs .tab').count()
  assert(tabs >= 4, `/app 应有 4 个分组 tab，实际 ${tabs}`)

  const firstCards = await page.locator('.tool-card').count()
  assert(firstCards > 0, '/app 默认分组应有卡片')

  // 点击「测试执行」
  const execTab = page.locator('.hub-tabs .tab, .tabs.hub-tabs .tab').filter({ hasText: '测试执行' })
  await execTab.click()
  await page.waitForTimeout(300)
  const execUrl = page.url()
  assert(execUrl.includes('tab=exec'), `点击后 ?tab=exec，实际 ${execUrl}`)
  const execActive = await page.locator('.hub-tabs .tab.active, .tabs.hub-tabs .tab.active').textContent()
  assert((execActive || '').includes('执行'), 'exec tab 应为 active')
  const execCards = await page.locator('.tool-card').count()
  assert(execCards > 0 && execCards !== firstCards, '切 tab 后卡片集合应变化')

  // 直达 ?tab=ai
  await page.goto(BASE + '/app?tab=ai', { waitUntil: 'networkidle' })
  await page.waitForTimeout(300)
  const aiActive = await page.locator('.hub-tabs .tab.active, .tabs.hub-tabs .tab.active').textContent()
  assert((aiActive || '').includes('AI'), `?tab=ai 应激活 AI 中心，实际 ${aiActive}`)
  // 打开一张卡片进入工具页
  await page.locator('.tool-card').first().click()
  await page.waitForURL('**/t/**', { timeout: 8000 }).catch(() => {})
  assert(page.url().includes('/t/'), '点击卡片应进入 /t/ 工具页')
  assert(pageErrors.length === 0, `hub 无 pageerror: ${pageErrors.join(';')}`)
  await page.screenshot({ path: path.join(OUT, '05-hub-tab.png') })
  await page.close()
}

// ========== 3) /prompts 侧栏切换 ==========
{
  const { page, pageErrors } = await openTracked(ctx, BASE + '/prompts')
  const sideItems = await page.locator('aside.sidebar .side-item').count()
  assert(sideItems >= 3, `/prompts 侧栏项 >= 3，实际 ${sideItems}`)

  const tabsHidden = await page
    .locator('.tabs')
    .evaluate((el) => getComputedStyle(el).display === 'none')
    .catch(() => false)
  assert(tabsHidden === true, '/prompts 主区 .tabs 应隐藏')

  await page.locator('aside.sidebar .side-item').filter({ hasText: '我的收藏' }).click()
  await page.waitForTimeout(300)
  const activeSide = await page.locator('aside.sidebar .side-item.active .si-txt').textContent()
  assert((activeSide || '').includes('收藏'), '侧栏点击应激活我的收藏')
  const visiblePanes = await page.locator('.tab-pane:visible').count()
  assert(visiblePanes === 1, `切换后应恰好 1 个可见 pane，实际 ${visiblePanes}`)

  // 投稿管理
  await page.locator('aside.sidebar .side-item').filter({ hasText: '投稿' }).click()
  await page.waitForTimeout(300)
  const active2 = await page.locator('aside.sidebar .side-item.active .si-txt').textContent()
  assert((active2 || '').includes('投稿'), '侧栏点击应激活投稿管理')
  assert(pageErrors.length === 0, `prompts 无 pageerror: ${pageErrors.join(';')}`)
  await page.screenshot({ path: path.join(OUT, '06-prompts-side.png') })
  await page.close()
}

// ========== 4) 工具页 tab（tool-api-testing） ==========
{
  const { page, pageErrors } = await openTracked(ctx, BASE + '/t/tool-api-testing?tab=run')
  await page.waitForTimeout(300)
  const activeSide = await page.locator('.side-item.active .si-txt').first().textContent().catch(() => '')
  assert(!!activeSide, '?tab=run 应有 active 侧栏项')
  assert(
    (activeSide || '').includes('执行') || (await page.locator('.side-item.active').count()) === 1,
    'tab=run 应激活用例执行',
  )

  // 点击「接口集合」切 tab
  const apis = page.locator('.side-item').filter({ hasText: '集合' }).first()
  if ((await apis.count()) > 0) {
    await apis.click()
    await page.waitForTimeout(300)
    assert(page.url().includes('tab='), `侧栏切换后 URL 应带 tab，实际 ${page.url()}`)
    const activeAfter = await page.locator('.side-item.active .si-txt').first().textContent().catch(() => '')
    assert(!!activeAfter && activeAfter !== activeSide, '侧栏点击应切换 active')
  } else {
    // 兜底：点击任意其他 side-item
    const items = page.locator('.side-item:not(.active)')
    if ((await items.count()) > 0) {
      const before = await page.locator('.side-item.active .si-txt').first().textContent().catch(() => '')
      await items.first().click()
      await page.waitForTimeout(300)
      const after = await page.locator('.side-item.active .si-txt').first().textContent().catch(() => '')
      assert(after !== before, '侧栏点击应切换 active')
    }
  }
  assert(pageErrors.length === 0, `tool 无 pageerror: ${pageErrors.join(';')}`)
  await page.screenshot({ path: path.join(OUT, '07-tool-tab.png') })
  await page.close()
}

// ========== 5) 退出登录 ==========
{
  // 通过清空 localStorage + reload 模拟登出后守卫/访客态
  const page = await ctx.newPage()
  await page.goto(BASE + '/app', { waitUntil: 'networkidle' })
  await page.evaluate(() => {
    localStorage.removeItem('aitesthub_token')
    localStorage.removeItem('aitesthub_auth')
    localStorage.removeItem('aitesthub_login_user')
  })
  await page.goto(BASE + '/auth', { waitUntil: 'networkidle' })
  const authWrap = await page.locator('.auth-wrap').count()
  assert(authWrap >= 1, '登出后可访问 /auth')
  // 访客首页 CTA
  await page.goto(BASE + '/', { waitUntil: 'networkidle' })
  const ctaLogin = await page.locator('a[href="/auth"]').count()
  assert(ctaLogin >= 1, '访客首页应有登录 CTA')
  await page.screenshot({ path: path.join(OUT, '08-guest.png') })
  await page.close()
}

await browser.close()

const report = { at: new Date().toISOString(), pass: fail === 0, fail, results }
const reportPath = path.join(ROOT, '.playwright-mcp', 'e2e-interaction.json')
fs.writeFileSync(reportPath, JSON.stringify(report, null, 2))
console.log(JSON.stringify({ fail, total: results.length, reportPath }, null, 2))
if (fail) {
  console.error('E2E_INTERACTION_FAIL count=' + fail)
  process.exit(1)
}
console.log('E2E_INTERACTION_OK', reportPath)
