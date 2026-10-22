#!/usr/bin/env node
/**
 * UI 设计稿 ↔ 线上页面 像素级 diff
 * 设计稿: file://.../UI/<name>.html
 * 线上:   http://127.0.0.1:5173/<route>
 *
 * 用法:
 *   node scripts/ui-pixel-diff.mjs
 *   node scripts/ui-pixel-diff.mjs --only prompts
 *   node scripts/ui-pixel-diff.mjs --vp 1440x900
 */
import { createRequire } from 'node:module'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const { chromium } = require('/Users/snow-sakura/.npm-global/lib/node_modules/playwright')

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const UI_DIR = path.join(ROOT, 'UI')
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const API = process.env.API_URL || 'http://127.0.0.1:8000'
const OUT = path.join(ROOT, '.playwright-mcp', 'screens', 'pixel-diff')
const REPORT = path.join(ROOT, '.playwright-mcp', 'pixel-diff-report.json')

const args = process.argv.slice(2)
function flag(name, def) {
  const i = args.indexOf(`--${name}`)
  if (i >= 0 && args[i + 1] && !args[i + 1].startsWith('--')) return args[i + 1]
  return def
}
const only = flag('only', null)
const vpArg = flag('vp', '1440x900')
const [VP_W, VP_H] = vpArg.split('x').map(Number)
// 高于该阈值输出 diff 图并标记 WARN
const WARN_PCT = Number(flag('warn', '8'))
const FAIL_PCT = Number(flag('fail', '25'))

/** UI html → 路由 映射 */
const PAIRS = [
  ['index.html', '/'],
  ['auth.html', '/auth'],
  ['register.html', '/register'],
  ['app.html', '/app'],
  ['prompts.html', '/prompts'],
  ['tool-requirement-management.html', '/t/tool-requirement-management'],
  ['tool-case-management.html', '/t/tool-case-management'],
  ['tool-defect-management.html', '/t/tool-defect-management'],
  ['tool-test-cases.html', '/t/tool-test-cases'],
  ['tool-api-testing.html', '/t/tool-api-testing'],
  ['tool-knowledge-base.html', '/t/tool-knowledge-base'],
  ['tool-ui-automation.html', '/t/tool-ui-automation'],
  ['tool-app-automation.html', '/t/tool-app-automation'],
  ['tool-performance-testing.html', '/t/tool-performance-testing'],
  ['tool-security-testing.html', '/t/tool-security-testing'],
  ['tool-pentest-testing.html', '/t/tool-pentest-testing'],
  ['tool-api-scenario-studio.html', '/t/tool-api-scenario-studio'],
  ['tool-workflow-editor.html', '/t/tool-workflow-editor'],
  ['tool-agent-center.html', '/t/tool-agent-center'],
  ['tool-ai-assistant.html', '/t/tool-ai-assistant'],
  ['tool-ai-reports.html', '/t/tool-ai-reports'],
  ['tool-skills-center.html', '/t/tool-skills-center'],
  ['tool-skill-library.html', '/t/tool-skill-library'],
  ['tool-root-cause.html', '/t/tool-root-cause'],
  ['tool-deai-flavor.html', '/t/tool-deai-flavor'],
  ['tool-data-factory.html', '/t/tool-data-factory'],
  ['tool-mcp-center.html', '/t/tool-mcp-center'],
  ['tool-config-center.html', '/t/tool-config-center'],
  ['tool-log-center.html', '/t/tool-log-center'],
  ['tool-scheduler.html', '/t/tool-scheduler'],
  ['tool-token-usage.html', '/t/tool-token-usage'],
  ['tool-media-data-hub.html', '/t/tool-media-data-hub'],
]

fs.mkdirSync(OUT, { recursive: true })

async function login() {
  const res = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: 'username=admin&password=admin123',
  })
  const data = await res.json()
  return data.access_token || ''
}

const token = await login()
let browser = null
let ctx = null
let shotPage = null

/** 创建/重建浏览器与上下文（内存压力下 chromium 可能被系统击杀，崩溃后自动恢复） */
async function ensureBrowser() {
  const browserOk = !!browser && browser.isConnected()
  if (browserOk && ctx && shotPage && !shotPage.isClosed()) return
  if (!browserOk || !ctx) {
    await rebuildBrowser()
    return
  }
  if (!shotPage || shotPage.isClosed()) {
    try {
      // 复用单页截图，避免每对新建/销毁页面造成内存与渲染进程抖动
      shotPage = await ctx.newPage()
      shotPage.setDefaultTimeout(15000)
    } catch {
      // 上下文半死（createTarget 报错等）→ 整体重建
      await rebuildBrowser()
    }
  }
}

async function rebuildBrowser() {
  if (browser) await browser.close().catch(() => {})
  browser = await chromium.launch({ headless: true })
  ctx = await browser.newContext({
    viewport: { width: VP_W, height: VP_H },
    deviceScaleFactor: 1,
  })
  // 统一登录态
  await ctx.addInitScript(
    ({ t, u }) => {
      localStorage.setItem('aitesthub_token', t)
      localStorage.setItem('aitesthub_auth', '1')
      localStorage.setItem('aitesthub_login_user', u)
    },
    { t: token, u: 'wxh' }
  )
  shotPage = await ctx.newPage()
  shotPage.setDefaultTimeout(15000)
}

async function shoot(url, file) {
  await ensureBrowser()
  const errors = []
  const onErr = (e) => errors.push(String(e).split('\n')[0])
  shotPage.on('pageerror', onErr)
  try {
    try {
      await shotPage.goto(url, { waitUntil: 'networkidle', timeout: 15000 })
    } catch {
      await shotPage.goto(url, { waitUntil: 'load', timeout: 15000 }).catch(() => {})
    }
    await shotPage.waitForTimeout(600)
    // 关掉可能打开的 toast/modal
    await shotPage.keyboard.press('Escape').catch(() => {})
    await shotPage.waitForTimeout(150)
    const buf = await shotPage.screenshot({ path: path.join(OUT, file), fullPage: false })
    return { buf, errors }
  } finally {
    shotPage.off('pageerror', onErr)
  }
}

/** 硬超时兜底：单对卡死不拖垮整轮 */
function withTimeout(promise, ms, label) {
  let timer
  return Promise.race([
    promise.finally(() => clearTimeout(timer)),
    new Promise((_, rej) => {
      timer = setTimeout(() => rej(new Error(`${label} timeout ${ms}ms`)), ms)
    }),
  ])
}

/** 在浏览器里做像素 diff，返回 { pct, diffDataUrl, w, h } */
async function pixelDiff(pngA, pngB) {
  await ensureBrowser()
  const p = shotPage
  try {
    return await p.evaluate(
      async ({ a, b }) => {
        function load(dataUrl) {
          return new Promise((res, rej) => {
            const img = new Image()
            img.onload = () => res(img)
            img.onerror = rej
            img.src = dataUrl
          })
        }
        const ia = await load(a)
        const ib = await load(b)
        const w = Math.min(ia.width, ib.width)
        const h = Math.min(ia.height, ib.height)
        const c1 = document.createElement('canvas')
        const c2 = document.createElement('canvas')
        c1.width = c2.width = w
        c1.height = c2.height = h
        const x1 = c1.getContext('2d', { willReadFrequently: true })
        const x2 = c2.getContext('2d', { willReadFrequently: true })
        x1.drawImage(ia, 0, 0)
        x2.drawImage(ib, 0, 0)
        const d1 = x1.getImageData(0, 0, w, h)
        const d2 = x2.getImageData(0, 0, w, h)
        const out = x1.createImageData(w, h)
        let diff = 0
        const TH = 32 // 每通道阈值
        for (let i = 0; i < d1.data.length; i += 4) {
          const dr = Math.abs(d1.data[i] - d2.data[i])
          const dg = Math.abs(d1.data[i + 1] - d2.data[i + 1])
          const db = Math.abs(d1.data[i + 2] - d2.data[i + 2])
          if (dr > TH || dg > TH || db > TH) {
            diff++
            out.data[i] = 255
            out.data[i + 1] = 0
            out.data[i + 2] = 0
            out.data[i + 3] = 255
          } else {
            // 灰度底
            const g = (d1.data[i] * 0.3 + d1.data[i + 1] * 0.59 + d1.data[i + 2] * 0.11) * 0.35 + 60
            out.data[i] = out.data[i + 1] = out.data[i + 2] = g
            out.data[i + 3] = 255
          }
        }
        const total = w * h
        const pct = (diff / total) * 100
        const co = document.createElement('canvas')
        co.width = w
        co.height = h
        co.getContext('2d').putImageData(out, 0, 0)
        return { pct, w, h, diffDataUrl: co.toDataURL('image/png'), diffCount: diff, total }
      },
      { a: pngA, b: pngB }
    )
  } finally {
    // p 复用 shotPage，不在此关闭；失败时由 catch 重置
  }
}

function toDataUrl(buf) {
  return `data:image/png;base64,${buf.toString('base64')}`
}

const pairs = PAIRS.filter(([f]) => !only || only.split(',').some((o) => f.includes(o)))
const results = []

for (const [file, route] of pairs) {
  const designPath = path.join(UI_DIR, file)
  if (!fs.existsSync(designPath)) {
    results.push({ file, route, status: 'SKIP', reason: 'design missing' })
    console.log('SKIP', file)
    continue
  }
  const slug = file.replace(/\.html$/, '')
  process.stdout.write(`DIFF ${slug} ... `)
  try {
    const design = await withTimeout(shoot('file://' + designPath, `design-${slug}.png`), 45000, 'design')
    const live = await withTimeout(shoot(BASE + route, `live-${slug}.png`), 45000, 'live')
    const r = await withTimeout(pixelDiff(toDataUrl(design.buf), toDataUrl(live.buf)), 45000, 'diff')
    let status = 'OK'
    if (r.pct >= FAIL_PCT) status = 'FAIL'
    else if (r.pct >= WARN_PCT) status = 'WARN'
    // 写 diff 图
    if (status !== 'OK') {
      const b64 = r.diffDataUrl.split(',')[1]
      fs.writeFileSync(path.join(OUT, `diff-${slug}.png`), Buffer.from(b64, 'base64'))
    }
    const row = {
      file,
      route,
      status,
      pct: Math.round(r.pct * 100) / 100,
      diffPx: r.diffCount,
      totalPx: r.total,
      designErrors: design.errors.slice(0, 2),
      liveErrors: live.errors.slice(0, 2),
    }
    results.push(row)
    console.log(`${status} ${row.pct}%`)
  } catch (e) {
    // 单对失败：丢弃可能卡死的复用页，ensureBrowser 会重建后继续
    try {
      if (shotPage && !shotPage.isClosed()) await shotPage.close({ timeout: 5000 })
    } catch {}
    shotPage = null
    results.push({ file, route, status: 'ERROR', pct: null, reason: String(e).slice(0, 160) })
    console.log(`ERROR ${String(e).slice(0, 120)}`)
  }
}

if (browser && browser.isConnected()) await browser.close().catch(() => {})

const summary = {
  vp: vpArg,
  warn: WARN_PCT,
  fail: FAIL_PCT,
  counts: results.reduce((m, r) => ((m[r.status] = (m[r.status] || 0) + 1), m), {}),
  worst: [...results].filter((r) => r.pct != null).sort((a, b) => b.pct - a.pct).slice(0, 15),
  results,
}
fs.writeFileSync(REPORT, JSON.stringify(summary, null, 2))

console.log('\n==== SUMMARY ====')
console.log(JSON.stringify(summary.counts))
console.log('Worst:')
for (const r of summary.worst) console.log(`  ${r.status.padEnd(4)} ${String(r.pct).padStart(6)}%  ${r.file}`)
console.log('Report:', REPORT)
console.log('Shots:', OUT)

const fails = results.filter((r) => r.status === 'FAIL' || r.status === 'ERROR').length
process.exit(fails ? 1 : 0)
