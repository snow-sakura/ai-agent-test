#!/usr/bin/env node
/** 设计稿 ↔ 线上 /prompts 关键元素几何 + 容器宽度对比（1440×900） */
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const { chromium } = require('/Users/snow-sakura/.npm-global/lib/node_modules/playwright')

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const DESIGN = 'file://' + path.join(ROOT, 'UI', 'prompts.html')
const LIVE = 'http://127.0.0.1:5173/prompts'
const API = 'http://127.0.0.1:8000'

async function login() {
  const res = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: 'username=admin&password=admin123',
  })
  return (await res.json()).access_token || ''
}
const token = await login()

const browser = await chromium.launch({ headless: true })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
await ctx.addInitScript(
  ({ t, u }) => {
    localStorage.setItem('aitesthub_token', t)
    localStorage.setItem('aitesthub_auth', '1')
    localStorage.setItem('aitesthub_login_user', u)
  },
  { t: token, u: 'wxh' }
)

async function shot(url, fn, arg) {
  const page = await ctx.newPage()
  try {
    try { await page.goto(url, { waitUntil: 'networkidle', timeout: 20000 }) }
    catch { await page.goto(url, { waitUntil: 'load', timeout: 20000 }) }
    await page.waitForTimeout(700)
    return await page.evaluate(fn, arg)
  } finally { await page.close() }
}

const geomFn = (sels) => {
  const out = {}
  for (const [name, sel] of Object.entries(sels)) {
    const el = document.querySelector(sel)
    if (!el) { out[name] = null; continue }
    const b = el.getBoundingClientRect()
    const cs = getComputedStyle(el)
    out[name] = {
      rect: [b.x, b.y, b.width, b.height].map(v => Math.round(v * 10) / 10),
      fs: cs.fontSize, lh: cs.lineHeight, mt: cs.marginTop, mb: cs.marginBottom,
      pad: cs.padding, fw: cs.fontWeight, display: cs.display,
      text: (el.textContent || '').trim().slice(0, 26),
    }
  }
  const card = document.querySelector(sels.__card)
  if (card) {
    const cb = card.getBoundingClientRect()
    const parts = {}
    for (const [k, s] of Object.entries({ tag: sels.__tag, title: sels.__title, meta: sels.__meta, preview: sels.__preview, foot: sels.__foot })) {
      const e = card.querySelector(s)
      if (!e) { parts[k] = null; continue }
      const b = e.getBoundingClientRect()
      const cs = getComputedStyle(e)
      parts[k] = {
        relY: Math.round((b.y - cb.y) * 10) / 10, h: Math.round(b.height * 10) / 10,
        fs: cs.fontSize, lh: cs.lineHeight, mt: cs.marginTop, mb: cs.marginBottom, pad: cs.padding,
      }
    }
    out.__cardParts = parts
    out.__cardRect = [Math.round(cb.y * 10) / 10, Math.round(cb.height * 10) / 10]
  }
  out.__tabs = document.querySelector('.tabs') ? getComputedStyle(document.querySelector('.tabs')).display : 'n/a'
  return out
}

const contFn = (sels) => {
  const o = {}
  for (const [k, s] of Object.entries(sels)) {
    const el = document.querySelector(s)
    if (!el) { o[k] = null; continue }
    const b = el.getBoundingClientRect()
    const cs = getComputedStyle(el)
    o[k] = {
      x: Math.round(b.x * 10) / 10, right: Math.round((b.x + b.width) * 10) / 10,
      w: Math.round(b.width * 10) / 10, pad: cs.padding, mar: cs.margin, box: cs.boxSizing,
      clientW: el.clientWidth, scrollW: el.scrollWidth,
      overflowY: cs.overflowY, scrollable: el.scrollHeight > el.clientHeight + 2,
      sbGap: el.offsetWidth - el.clientWidth,
    }
  }
  o.__doc = { clientW: document.documentElement.clientWidth, innerW: window.innerWidth, scrollH: document.documentElement.scrollHeight }
  return o
}

const design = await shot(DESIGN, geomFn, {
  headerBtn: '.page-head .btn-primary', filterBar: '.filter-bar', count: '#result-count',
  card: '.grid.grid-3 > .card', pagination: '.pagination', userChip: '.user-chip',
  sub: '.page-head .sub', h1: '.page-head h1',
  __card: '.grid.grid-3 > .card', __tag: '.tag', __title: 'h3',
  __meta: '.text-faint', __preview: '.code-block', __foot: '.flex-between.mt-8',
})
const live = await shot(LIVE, geomFn, {
  headerBtn: '.page-head .btn', headerBtn2: '.page-head .flex .btn.btn-primary',
  filterBar: '.filter-bar', count: '.filter-bar .text-faint',
  card: '.prompt-card', pagination: '.prompts-pager .pagination', userChip: '.user-chip',
  sub: '.page-head .sub', h1: '.page-head h1',
  __card: '.prompt-card', __tag: '.pc-top .tag', __title: '.pc-title',
  __meta: '.pc-meta', __preview: '.pc-preview', __foot: '.pc-foot',
})

console.log('=== 关键元素 rect [x,y,w,h] ===')
for (const k of ['h1', 'sub', 'headerBtn', 'headerBtn2', 'filterBar', 'count', 'card', 'pagination', 'userChip']) {
  const d = design[k]?.rect, l = live[k]?.rect
  console.log(k.padEnd(12), 'D:', JSON.stringify(d), ' L:', JSON.stringify(l),
    d && l ? ` Δ=[${(l[0] - d[0]).toFixed(1)},${(l[1] - d[1]).toFixed(1)},${(l[2] - d[2]).toFixed(1)},${(l[3] - d[3]).toFixed(1)}]` : '')
}
console.log('\n=== 卡片内部 ===')
console.log('card  D:', JSON.stringify(design.__cardRect), ' L:', JSON.stringify(live.__cardRect))
for (const k of ['tag', 'title', 'meta', 'preview', 'foot']) {
  const d = design.__cardParts?.[k], l = live.__cardParts?.[k]
  console.log(k.padEnd(8),
    d ? `D y=${d.relY} h=${d.h} fs=${d.fs} lh=${d.lh} mt=${d.mt} mb=${d.mb} pad=${d.pad}` : 'D=null', '|',
    l ? `L y=${l.relY} h=${l.h} fs=${l.fs} lh=${l.lh} mt=${l.mt} mb=${l.mb} pad=${l.pad}` : 'L=null')
}
console.log('\ntabs  D:', design.__tabs, ' L:', live.__tabs)
console.log('count D:', JSON.stringify(design.count?.text), ' L:', JSON.stringify(live.count?.text))

const dc = await shot(DESIGN, contFn, {
  main: '.main-area', scroll: '.tab-pane.active', pager: '.pagination',
  filter: '.filter-bar', grid: '.grid.grid-3', pageHead: '.page-head', codeBlock: '.code-block',
  workspace: '.workspace',
})
const lc = await shot(LIVE, contFn, {
  main: '.main-area', scroll: '.prompts-scroll', pager: '.prompts-pager',
  filter: '.filter-bar', grid: '.grid.grid-3', pageHead: '.page-head', preview: '.pc-preview',
  view: '.prompts-panes', workspace: '.workspace-shell, .workspace',
})
console.log('\n=== 容器 D ==='); console.log(JSON.stringify(dc, null, 1))
console.log('\n=== 容器 L ==='); console.log(JSON.stringify(lc, null, 1))

await browser.close()
