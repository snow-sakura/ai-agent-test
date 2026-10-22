/* BUG-02 根因实证：冷加载直跳 notify tab + 延迟 notify API，复现 smtp→vnode 次生链 */
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const { chromium } = require('/Users/snow-sakura/.npm-global/lib/node_modules/playwright')

const BASE = 'http://127.0.0.1:5173'
const errs = []

// 1) 登录取 token
const login = await fetch(`${BASE.replace('5173', '8000')}/api/auth/login`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({
    username: process.env.DEMO_ACCOUNT || 'demo_tester',
    password: process.env.DEMO_PASSWORD || 'Demo@2026',
  }).toString(),
})
const token = (await login.json()).access_token

const browser = await chromium.launch({ headless: true })
const ctx = await browser.newContext()
await ctx.addInitScript((t) => {
  localStorage.setItem('aitesthub_token', t)
  localStorage.setItem('aitesthub_auth', '1')
  localStorage.setItem('aitesthub_login_user', 'admin')
}, token)

// 2) 延迟 notify 配置接口 800ms，放大 loadAll 未返回的竞态窗口
await ctx.route('**/api/config/notify**', async (route) => {
  await new Promise((r) => setTimeout(r, 800))
  await route.continue()
})

const page = await ctx.newPage()
page.on('pageerror', (e) => errs.push(String(e).slice(0, 160)))

// 3) 冷启动直跳 ?tab=notify（历史触发路径：scheduler 内「配置中心」链接）
await page.goto(`${BASE}/t/tool-config-center?tab=notify`, { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(1200) // render 已崩（smtp），loadAll 尚未返回

// 4) 刺激：数据到达后的多次更新 + 路由往返（模拟 run19 导航时机）
await page.waitForTimeout(1200) // loadAll（800ms 延迟）已返回 → notify 更新触发重渲染
try {
  await page.click('a[href*="tool-scheduler"], .side-item:has-text("定时任务")', { timeout: 2000 })
} catch {}
await page.waitForTimeout(800)
try {
  await page.click('a[href*="tool-config-center"], .side-item:has-text("配置中心")', { timeout: 2000 })
} catch {}
await page.waitForTimeout(1500)

console.log('pageerrors=', errs.length)
errs.forEach((e, i) => console.log(`  [${i}] ${e}`))
await browser.close()
process.exit(0)
