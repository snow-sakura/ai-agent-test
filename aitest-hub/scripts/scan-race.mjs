/* 全路由冷启动竞态扫描：对 manifest 全部真实路由做"冷页面 + API 延迟"加载，
   收集 pageerror——复现 BUG-01 类"数据未就绪时 render"竞态。
   用法: node scripts/scan-race.mjs [--delay 600] [--wait 2200] */
import { createRequire } from 'node:module'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const { chromium } = require('/Users/snow-sakura/.npm-global/lib/node_modules/playwright')

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const API = process.env.API_URL || 'http://127.0.0.1:8000'
const arg = (k, d) => {
  const i = process.argv.indexOf(k)
  return i > -1 ? Number(process.argv[i + 1]) : d
}
const DELAY = arg('--delay', 600)
const WAIT = arg('--wait', 2200)

const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, '.playwright-mcp', 'features-manifest.json'), 'utf8'))
const routes = [...new Set(manifest.modules.map((m) => m.route))].filter(
  (r) => r && r !== '(shell)',
)

const login = await fetch(API + '/api/auth/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({
    username: process.env.DEMO_ACCOUNT || 'demo_tester',
    password: process.env.DEMO_PASSWORD || 'Demo@2026',
  }).toString(),
})
const token = (await login.json()).access_token

const browser = await chromium.launch({ headless: true })
const findings = []
const consoleIssues = []

for (const route of routes) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  await ctx.addInitScript((t) => {
    localStorage.setItem('aitesthub_token', t)
    localStorage.setItem('aitesthub_auth', '1')
    localStorage.setItem('aitesthub_login_user', 'admin')
  }, token)
  // 放大"数据未就绪"竞态窗口
  await ctx.route('**/api/**', async (route2) => {
    await new Promise((r) => setTimeout(r, DELAY))
    await route2.continue()
  })
  const page = await ctx.newPage()
  const errs = []
  const cons = []
  page.on('pageerror', (e) => errs.push(String(e).slice(0, 180)))
  /* console 盲区：验证器只收 pageerror，Vue warning / 未捕获的 console.error
     需在此收集；过滤静态资源 404 等噪音 */
  page.on('console', (msg) => {
    const t = msg.type()
    if (t !== 'error' && t !== 'warning') return
    const text = msg.text()
    if (/Failed to load resource|net::ERR|favicon|Download the Vue Devtools/i.test(text)) return
    cons.push(`[${t}] ${text.slice(0, 180)}`)
  })
  try {
    await page.goto(BASE + route, { waitUntil: 'domcontentloaded', timeout: 15000 })
    await page.waitForTimeout(WAIT)
    // 二次刺激：部分页面 tab 切换/滚动触发重渲染
    await page.mouse.wheel(0, 400).catch(() => {})
    await page.waitForTimeout(400)
  } catch (e) {
    errs.push('[goto] ' + String(e).slice(0, 120))
  }
  await ctx.close()
  const mark = errs.length ? '✗' : cons.length ? '!' : '✓'
  console.log(
    `${mark} ${route}${errs.length ? `  pageerror=${errs.length}` : ''}${cons.length ? `  console=${cons.length}` : ''}`,
  )
  for (const e of errs) {
    console.log(`    ${e}`)
    findings.push({ route, kind: 'pageerror', error: e })
  }
  for (const c of [...new Set(cons)]) {
    console.log(`    ${c}`)
    consoleIssues.push({ route, kind: 'console', error: c })
  }
}

await browser.close()
console.log('\n==== 扫描汇总 ====')
console.log(
  `路由 ${routes.length}，pageerror 路由 ${new Set(findings.map((f) => f.route)).size}（共 ${findings.length}），console 问题路由 ${new Set(consoleIssues.map((f) => f.route)).size}（共 ${consoleIssues.length}）`,
)
fs.writeFileSync(
  path.join(ROOT, '.playwright-mcp', 'race-scan-report.json'),
  JSON.stringify({ at: new Date().toISOString(), delay: DELAY, wait: WAIT, findings, consoleIssues }, null, 1),
)
process.exit(findings.length ? 1 : 0)
