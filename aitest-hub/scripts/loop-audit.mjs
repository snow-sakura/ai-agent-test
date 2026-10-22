#!/usr/bin/env node
/**
 * Loop Engineering 巡检脚本
 * 遍历 5 门户路由 + 27 工具路由 × 多视口
 * 检查：横向溢出、内容裁切/滚动可达、console/pageerror
 * 每页自动截图到 .playwright-mcp/screens/loop/
 *
 * 用法:
 *   node scripts/loop-audit.mjs
 *   node scripts/loop-audit.mjs --layer portal|testmgmt|exec|ai|platform|all
 *   node scripts/loop-audit.mjs --vp 1920x1080
 *   node scripts/loop-audit.mjs --only /t/tool-ai-reports
 */
import { createRequire } from 'node:module'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const { chromium } = require('/Users/snow-sakura/.npm-global/lib/node_modules/playwright')

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const OUT = path.join(ROOT, '.playwright-mcp', 'screens', 'loop')
const REPORT = path.join(ROOT, '.playwright-mcp', 'loop-audit-report.json')

// ---- CLI ----
const args = process.argv.slice(2)
function flag(name, def) {
  const i = args.indexOf(`--${name}`)
  if (i >= 0 && args[i + 1] && !args[i + 1].startsWith('--')) return args[i + 1]
  return def
}
const layer = flag('layer', 'all')
const only = flag('only', null)
const vpArg = flag('vp', '1920x1080,1920x966,1440x900')
const VIEWPORTS = vpArg.split(',').map((s) => {
  const [w, h] = s.split('x').map(Number)
  return { w, h }
})

// ---- Route catalog (L1-L5 layers) ----
const LAYERS = {
  portal: [
    '/',
    '/auth',
    '/register',
    '/app',
    '/prompts',
  ],
  // L2 测试管理
  testmgmt: [
    '/t/tool-requirement-management',
    '/t/tool-case-management',
    '/t/tool-defect-management',
    '/t/tool-test-cases',
    '/t/tool-api-testing',
    '/t/tool-knowledge-base',
  ],
  // L3 测试执行
  exec: [
    '/t/tool-ui-automation',
    '/t/tool-app-automation',
    '/t/tool-performance-testing',
    '/t/tool-security-testing',
    '/t/tool-pentest-testing',
    '/t/tool-api-scenario-studio',
    '/t/tool-workflow-editor',
  ],
  // L4 AI 中心
  ai: [
    '/t/tool-agent-center',
    '/t/tool-ai-assistant',
    '/t/tool-ai-reports',
    '/t/tool-skills-center',
    '/t/tool-skill-library',
    '/t/tool-root-cause',
    '/t/tool-deai-flavor',
    '/t/tool-data-factory',
    '/t/tool-mcp-center',
  ],
  // L5 平台与数据
  platform: [
    '/t/tool-config-center',
    '/t/tool-log-center',
    '/t/tool-scheduler',
    '/t/tool-token-usage',
    '/t/tool-media-data-hub',
    '/t/tool-media-data-hub',
  ],
}

// dedupe platform (media listed twice above intentionally removed)
LAYERS.platform = [
  '/t/tool-config-center',
  '/t/tool-log-center',
  '/t/tool-scheduler',
  '/t/tool-token-usage',
  '/t/tool-media-data-hub',
]

function routesFor(layerName) {
  if (layerName === 'all') {
    return [...LAYERS.portal, ...LAYERS.testmgmt, ...LAYERS.exec, ...LAYERS.ai, ...LAYERS.platform]
  }
  return LAYERS[layerName] || []
}

const ROUTES = only ? [only] : routesFor(layer)

// ---- AUTH seed ----
const AUTH_KEYS = {
  aitesthub_token: process.env.AITEST_TOKEN || 'loop-audit-fake-token',
  aitesthub_auth: '1',
  aitesthub_user: 'admin',
}
// discover actual key names from http.ts at runtime via page after login attempt is heavier;
// we seed both known names + fallbacks after first page load by reading source constants.

const LOGIN = async (page) => {
  // try real login first (works when API up)
  try {
    const res = await page.request.post(`${BASE.replace('5173', '8000')}/api/auth/login`, {
      form: { username: 'admin', password: 'admin123' },
      failOnStatusCode: false,
    })
    if (res.ok()) {
      const data = await res.json()
      if (data?.access_token) return data.access_token
    }
  } catch {
    /* fall through */
  }
  return null
}

/** 在页面上下文中注入登录态 */
async function seedAuth(page) {
  const token = await LOGIN(page)
  await page.addInitScript(
    ([keys, tok]) => {
      localStorage.setItem(keys.token, tok)
      localStorage.setItem(keys.auth, '1')
      localStorage.setItem(keys.user, 'admin')
    },
    [
      {
        token: 'aitesthub_token',
        auth: 'aitesthub_auth_flag',
        user: 'aitesthub_user',
      },
      token || AUTH_KEYS.aitesthub_token,
    ],
  )
  // Also set AUTH_KEY - need exact name from source; patch after reading
}

/** 读取前端 AUTH_KEY / LOGIN_USER_KEY 常量名 */
async function readAuthKeys() {
  const p = path.join(ROOT, 'frontend', 'src', 'api', 'http.ts')
  const src = fs.readFileSync(p, 'utf8')
  const tok = src.match(/TOKEN_KEY\s*=\s*['"]([^'"]+)['"]/)
  const auth = src.match(/AUTH_KEY\s*=\s*['"]([^'"]+)['"]/)
  const user = src.match(/LOGIN_USER_KEY\s*=\s*['"]([^'"]+)['"]/)
  return {
    token: tok?.[1] || 'aitesthub_token',
    auth: auth?.[1] || 'aitesthub_auth',
    user: user?.[1] || 'aitesthub_user',
  }
}

// ---- 测量逻辑（单页单视口） ----
const MEASURE = () => {
  const doc = document
  const html = doc.documentElement
  const body = doc.body
  const vw = window.innerWidth
  const vh = window.innerHeight

  const issues = []
  const detail = {}

  // 1. 横向溢出
  const hOverflow = Math.max(html.scrollWidth, body.scrollWidth) - vw
  detail.hOverflow = hOverflow
  if (hOverflow > 2) {
    issues.push({ type: 'h-overflow', delta: hOverflow })
  }

  // 2. 找滚动容器：优先 main-area / workspace / .main，否则 html/body
  const scrollers = []
  const candidates = doc.querySelectorAll(
    '.main-area, .workspace, .detail-shell, main, .hub, .container, #app, .page',
  )
  candidates.forEach((el) => {
    const st = getComputedStyle(el)
    const oy = st.overflowY
    if ((oy === 'auto' || oy === 'scroll') && el.scrollHeight > el.clientHeight + 4) {
      scrollers.push(el)
    }
  })
  // html/body 也检查
  if (html.scrollHeight > html.clientHeight + 4 && getComputedStyle(html).overflowY !== 'visible') {
    scrollers.push(html)
  }

  // 3. 内容裁切检测：视口内可见区域中，被 overflow:hidden/auto 裁掉底部/右侧的元素
  const clipped = []
  const all = doc.querySelectorAll('body *')
  const visLimit = Math.min(all.length, 2500) // 性能上限
  for (let i = 0; i < visLimit; i++) {
    const el = all[i]
    if (el.tagName === 'SCRIPT' || el.tagName === 'STYLE') continue
    const st = getComputedStyle(el)
    if (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0') continue
    if (st.position === 'fixed' || st.position === 'absolute') {
      // fixed 绝对定位也查，但放宽
    }
    const r = el.getBoundingClientRect()
    if (r.width < 4 || r.height < 4) continue
    // 元素右缘超出视口（水平裁切）
    if (r.right > vw + 2 && st.overflow !== 'visible') {
      // only if parent clips
      const p = el.parentElement
      if (p) {
        const pr = p.getBoundingClientRect()
        const pst = getComputedStyle(p)
        if (
          (pst.overflow === 'hidden' || pst.overflowX === 'hidden' || pst.overflowX === 'auto' || pst.overflowX === 'scroll') &&
          r.right > pr.right + 2
        ) {
          clipped.push({
            sel: el.className && typeof el.className === 'string' ? `.${el.className.split(/\s+/).slice(0, 3).join('.')}` : el.tagName,
            kind: 'right',
            overflowBy: Math.round(r.right - pr.right),
          })
        }
      }
    }
    // 元素底缘超出最近滚动祖先（垂直裁切）且该祖先 overflow hidden
    if (r.bottom > vh + 4) {
      const p = el.parentElement
      if (p) {
        const pst = getComputedStyle(p)
        if (pst.overflow === 'hidden' || pst.overflowY === 'hidden') {
          const pr = p.getBoundingClientRect()
          if (r.bottom > pr.bottom + 4 && r.top < pr.bottom) {
            clipped.push({
              sel: el.className && typeof el.className === 'string' ? `.${el.className.split(/\s+/).slice(0, 3).join('.')}` : el.tagName,
              kind: 'bottom-clip-hidden',
              overflowBy: Math.round(r.bottom - pr.bottom),
            })
          }
        }
      }
    }
  }

  // 4. 滚动可达性：对每个 scroller，滚到底后检查最底可见内容是否仍有被裁切的
  const scrollInfo = scrollers.map((el, idx) => {
    const tag = el === html ? 'html' : el.tagName.toLowerCase()
    const cls = typeof el.className === 'string' && el.className ? `.${el.className.split(/\s+/).slice(0, 3).join('.')}` : ''
    return {
      idx,
      sel: `${tag}${cls}`,
      scrollH: el.scrollHeight,
      clientH: el.clientHeight,
      overflowY: el.scrollHeight - el.clientHeight,
      canScroll: el.scrollHeight - el.clientHeight > 4,
      scrollTop: el.scrollTop,
    }
  })

  // 5. 页面级：是否有元素被裁在某个 overflow:hidden 容器里且不可滚
  detail.scrollers = scrollInfo
  detail.clippedCount = clipped.length
  detail.clipped = clipped.slice(0, 20)

  if (clipped.length > 0) {
    issues.push({ type: 'clipped', count: clipped.length, samples: clipped.slice(0, 5) })
  }

  // 6. 空白/异常：body 无内容
  if (!body.innerText || body.innerText.trim().length < 10) {
    issues.push({ type: 'empty-page' })
  }

  return {
    vw,
    vh,
    hOverflow,
    bodyH: body.scrollHeight,
    textLen: (body.innerText || '').length,
    scrollerCount: scrollers.length,
    scrollInfo,
    clipped,
    issues,
    detail,
  }
}

/** 滚动到最底并截图（展示“下方布局”是否可达） */
async function scrollAllScrollersToEnd(page) {
  await page.evaluate(() => {
    const html = document.documentElement
    const els = [html, document.body, ...document.querySelectorAll('.main-area, .workspace, .detail-shell, main, .hub')]
    for (const el of els) {
      if (!el) continue
      const st = getComputedStyle(el)
      const oy = st.overflowY
      if (oy === 'auto' || oy === 'scroll' || el === html) {
        try {
          el.scrollTop = el.scrollHeight
        } catch {
          /* ignore */
        }
      }
    }
    // window 滚动
    window.scrollTo(0, document.documentElement.scrollHeight)
  })
  await page.waitForTimeout(200)
}

async function measureAfterScroll(page) {
  return page.evaluate(() => {
    const html = document.documentElement
    const scrollers = []
    const candidates = document.querySelectorAll('.main-area, .workspace, .detail-shell, main, .hub, #app')
    candidates.forEach((el) => {
      const st = getComputedStyle(el)
      if (st.overflowY === 'auto' || st.overflowY === 'scroll') {
        scrollers.push({
          sel: (typeof el.className === 'string' && el.className ? `.${el.className.split(/\s+/).slice(0, 3).join('.')}` : el.tagName),
          scrollTop: el.scrollTop,
          remaining: el.scrollHeight - el.clientHeight - el.scrollTop,
        })
      }
    })
    scrollers.push({
      sel: 'window',
      scrollTop: window.scrollY,
      remaining: html.scrollHeight - html.clientHeight - window.scrollY,
    })
    return scrollers
  })
}

// ---- MAIN ----
async function main() {
  fs.mkdirSync(OUT, { recursive: true })
  const keys = await readAuthKeys()
  console.log('[loop-audit] auth keys:', keys)
  console.log('[loop-audit] routes:', ROUTES.length, ROUTES.join(', '))
  console.log('[loop-audit] viewports:', VIEWPORTS.map((v) => `${v.w}x${v.h}`).join(', '))

  const browser = await chromium.launch({ headless: true })
  const report = { startedAt: new Date().toISOString(), base: BASE, keys, results: [], summary: {} }

  let totalIssues = 0
  let totalPages = 0

  for (const vp of VIEWPORTS) {
    const context = await browser.newContext({
      viewport: { width: vp.w, height: vp.h },
      deviceScaleFactor: 1,
    })
    const page = await context.newPage()

    const consoleErrors = []
    const pageErrors = []
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text().slice(0, 300))
    })
    page.on('pageerror', (err) => pageErrors.push(String(err).slice(0, 300)))

    // seed auth
    let apiToken = null
    try {
      const res = await page.request.post('http://127.0.0.1:8000/api/auth/login', {
        form: { username: 'admin', password: 'admin123' },
        failOnStatusCode: false,
      })
      if (res.ok()) {
        const data = await res.json()
        apiToken = data.access_token
      }
    } catch (e) {
      console.warn('[loop-audit] login failed', e.message)
    }

    await page.addInitScript(
      ([k, tok]) => {
        if (tok) {
          localStorage.setItem(k.token, tok)
          localStorage.setItem(k.auth, '1')
          localStorage.setItem(k.user, 'admin')
        }
      },
      [keys, apiToken || 'loop-audit-fake-token'],
    )

    for (const route of ROUTES) {
      totalPages++
      const slug = route.replace(/[^\w]+/g, '_').replace(/^_|_$/g, '') || 'root'
      const vpTag = `${vp.w}x${vp.h}`
      const errorsBefore = consoleErrors.length
      const pageErrBefore = pageErrors.length

      try {
        await page.goto(BASE + route, { waitUntil: 'networkidle', timeout: 15000 })
      } catch (e) {
        // SPA nav fallback
        try {
          await page.goto(BASE + route, { waitUntil: 'domcontentloaded', timeout: 10000 })
        } catch (e2) {
          report.results.push({
            route,
            viewport: vpTag,
            ok: false,
            error: String(e2),
          })
          totalIssues++
          continue
        }
      }
      await page.waitForTimeout(400)

      const m = await page.evaluate(MEASURE)

      // 截图：初始
      const shotInit = path.join(OUT, `${vpTag}__${slug}__init.png`)
      await page.screenshot({ path: shotInit, fullPage: false })

      // 滚到底 + 再测 + 截图
      await scrollAllScrollersToEnd(page)
      const after = await measureAfterScroll(page)
      const stillBlocked = after.filter((s) => s.remaining > 8)
      const shotEnd = path.join(OUT, `${vpTag}__${slug}__end.png`)
      await page.screenshot({ path: shotEnd, fullPage: false })

      // fullPage 截图（看整体布局是否完整）
      const shotFull = path.join(OUT, `${vpTag}__${slug}__full.png`)
      await page.screenshot({ path: shotFull, fullPage: true })

      // 回到顶部
      await page.evaluate(() => {
        window.scrollTo(0, 0)
        document.querySelectorAll('.main-area, .workspace').forEach((el) => {
          el.scrollTop = 0
        })
      })

      const consErrs = consoleErrors.slice(errorsBefore)
      const pErrs = pageErrors.slice(pageErrBefore)

      const issues = [...m.issues]
      if (stillBlocked.length) {
        issues.push({ type: 'scroll-blocked', scrollers: stillBlocked })
      }
      if (consErrs.length) {
        issues.push({ type: 'console-error', msgs: consErrs.slice(0, 5) })
      }
      if (pErrs.length) {
        issues.push({ type: 'page-error', msgs: pErrs.slice(0, 5) })
      }

      const ok = issues.length === 0
      if (!ok) totalIssues++

      const row = {
        route,
        viewport: vpTag,
        ok,
        hOverflow: m.hOverflow,
        textLen: m.textLen,
        scrollers: m.scrollInfo,
        afterScroll: after,
        clipped: m.clipped.slice(0, 8),
        consoleErrors: consErrs,
        pageErrors: pErrs,
        issues,
        shots: { init: shotInit, end: shotEnd, full: shotFull },
      }
      report.results.push(row)

      const mark = ok ? 'OK ' : 'NG '
      console.log(
        `${mark} [${vpTag}] ${route}` +
          (m.hOverflow > 2 ? ` hOv=${m.hOverflow}` : '') +
          (m.clipped.length ? ` clip=${m.clipped.length}` : '') +
          (consErrs.length ? ` consErr=${consErrs.length}` : '') +
          (pErrs.length ? ` pageErr=${pErrs.length}` : '') +
          (stillBlocked.length ? ` scrollBlocked=${stillBlocked.length}` : ''),
      )
      if (!ok) {
        for (const iss of issues) {
          console.log('     -', JSON.stringify(iss).slice(0, 240))
        }
      }
    }

    await context.close()
  }

  await browser.close()

  report.summary = {
    totalPages,
    totalIssues,
    failed: report.results.filter((r) => !r.ok).length,
    passed: report.results.filter((r) => r.ok).length,
    finishedAt: new Date().toISOString(),
  }
  fs.writeFileSync(REPORT, JSON.stringify(report, null, 2))
  console.log('\n==== SUMMARY ====')
  console.log(`pages=${totalPages} pass=${report.summary.passed} fail=${report.summary.failed}`)
  console.log(`report: ${REPORT}`)
  console.log(`shots:  ${OUT}`)
  if (report.summary.failed > 0) {
    console.log('\nFailed list:')
    for (const r of report.results.filter((x) => !x.ok)) {
      console.log(`  ${r.viewport} ${r.route} :: ${r.issues.map((i) => i.type).join(',')}`)
    }
    process.exitCode = 1
  } else {
    console.log('ALL PASS')
  }
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
