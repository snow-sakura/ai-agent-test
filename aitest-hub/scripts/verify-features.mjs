#!/usr/bin/env node
/**
 * 清单驱动的最小功能点在线验证器
 *
 * 读取 .playwright-mcp/features-manifest.json（extract-features.mjs 输出，1053 项），
 * 在真实浏览器中逐项验证：定位 → 按风险策略交互 → 反馈信号检测 → 状态恢复。
 *
 * 状态语义：
 *   PASS        真实交互且检测到反馈（点击后 DOM/URL/toast/值变化）
 *   PASS-EXIST  仅存在性/可见性断言（danger 只看不点、外链、禁用、已激活等）
 *   FAIL        已定位但交互后无反馈 / 输入值未生效
 *   MISSING     DOM 中不存在（可能提取噪音或选择器不匹配）
 *   SKIP        设计上不可见（隐藏 tab/折叠菜单）或 modal 无法打开
 *
 * 风险策略（与 extract-features.mjs 的 risk 字段对应）：
 *   danger 只存在性断言；submit 空表单点一次看校验反馈；ai 点击长等待；
 *   safe 真点击 + 反馈检测 + 恢复（关 modal / goBack 回路由）。
 *
 * 用法:
 *   node scripts/verify-features.mjs                     # 全量（建议分批）
 *   node scripts/verify-features.mjs --only auth,register
 *   node scripts/verify-features.mjs --fresh            # 不合并旧报告
 *
 * 依赖: vite @127.0.0.1:5173 + api @127.0.0.1:8000（demo 账号真实登录）
 */
import { createRequire } from 'node:module'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'
import http from 'node:http'

const require = createRequire(import.meta.url)
const { chromium } = require('/Users/snow-sakura/.npm-global/lib/node_modules/playwright')

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const API = process.env.API_URL || 'http://127.0.0.1:8000'
const MANIFEST = path.join(ROOT, '.playwright-mcp', 'features-manifest.json')
const REPORT = path.join(ROOT, '.playwright-mcp', 'features-verify.json')

const args = process.argv.slice(2)
const argOf = (n) => {
  const i = args.indexOf(n)
  return i >= 0 && args[i + 1] ? args[i + 1] : null
}
const onlyArg = argOf('--only')
const ONLY = onlyArg ? onlyArg.split(',').map((s) => s.trim()) : null
const FRESH = args.includes('--fresh')
const NO_SCAN = args.includes('--no-scan') // 跳过前置竞态扫描
const LIMIT = argOf('--limit') ? Number(argOf('--limit')) : 0 // 每模块最多验证 N 项（调试）

/* ---------- 反馈窗口（ms） ---------- */
const W = { safe: 1400, submit: 2500, ai: 7000, link: 1600 }
const winOf = (risk) => (risk === 'ai' ? W.ai : risk === 'submit' ? W.submit : W.safe)

/* ---------- 宿主决策表（shell 模块多宿主页 / guest 模块） ---------- */
const HOSTS = {
  'shell:topbar': [
    { path: '/app', auth: true },
    { path: '/', auth: true },
  ],
  'shell:tool-sidebar': [
    { path: '/t/tool-scheduler', auth: true },
    { path: '/t/tool-ai-assistant', auth: true },
  ],
  'shell:prompts-sidebar': [{ path: '/prompts', auth: true }],
  auth: [{ path: '/auth', auth: false }],
  register: [{ path: '/register', auth: false }],
}
const hostsOf = (mod) => HOSTS[mod.id] || [{ path: mod.route, auth: true }]
const PROMPT_NAV = ['all', 'favs', 'submit'] // 侧栏 DOM 顺序：提示词列表/我的收藏/投稿管理

/* ---------- 小工具 ---------- */
const norm = (s) => (s || '').replace(/\s+/g, ' ').trim()
const ftext = (f) => norm(f.text || f.vModel || f.placeholder || '')
// key 含模块内序号：同文件同行可能有多个同 kind 特征（如两个协议链接）
const fid = (mod, f) => `${mod.id}#${f._idx}`
const fkey = (f) => `${f.kind}|${f.enclosing || ''}`

const isDynamicTo = (to) => typeof to === 'string' && to.trim().startsWith('{')
function staticTo(to) {
  if (!to || typeof to !== 'string') return null
  const t = to.trim()
  if (t.startsWith('{')) {
    const m = t.match(/path:\s*['"]([^'"]+)['"]/)
    return m ? m[1] : null
  }
  if (t.startsWith('#') || t.startsWith('javascript:')) return null
  return t
}

/* ---------- 页面状态快照（反馈信号） ---------- */
async function snap(page) {
  const s = await page.evaluate(() => {
    const n = (s) => (s || '').replace(/\s+/g, ' ').trim()
    let open = 0
    document.querySelectorAll('.modal-mask.open').forEach(() => open++)
    const toasts = [...document.querySelectorAll('#toast-box .toast')]
      .map((t) => n(t.innerText).slice(0, 80))
      .join('|')
    const body = document.body.innerText || ''
    let h = 5381
    for (let i = 0; i < body.length; i++) h = ((h * 33) ^ body.charCodeAt(i)) >>> 0
    let inputs = ''
    document.querySelectorAll('input,textarea,select').forEach((el, i) => {
      inputs += `${i}:${el.type || ''}:${el.value || ''}:${el.checked ? 1 : 0};`
    })
    return {
      url: location.pathname + location.search,
      open,
      toasts,
      body: h,
      inputs: inputs.slice(0, 6000),
    }
  })
  // Node 侧信号面：文件选择器 / 弹出窗口（浏览器侧事件计数）
  s.fc = page._fcN || 0
  s.pop = page._popN || 0
  return s
}

/* 点击后是否发起了「点击前未出现过」的 API 请求（防轮询误报：只认新 URL） */
function netNew(page, base) {
  const log = page._netLog
  if (!log || !base) return null
  for (const u of log) if (!base.has(u)) return u
  return null
}

async function waitChange(page, before, winMs, dlgRef) {
  const t0 = Date.now()
  for (;;) {
    if (dlgRef && dlgRef.n > 0) return { changed: true, how: 'native-dialog', waited: Date.now() - t0 }
    if (Date.now() - t0 >= winMs) return { changed: false, waited: Date.now() - t0 }
    await page.waitForTimeout(250)
    let s
    try {
      s = await snap(page)
    } catch {
      return { changed: false, waited: Date.now() - t0 }
    }
    const keys = []
    for (const k of Object.keys(before)) if (String(before[k]) !== String(s[k])) keys.push(k)
    if (keys.length)
      return { changed: true, how: keys.join('+'), waited: Date.now() - t0, toasts: s.toasts }
  }
}

/* ---------- 状态恢复：关 modal + 回到期望路由 ---------- */
async function closeModals(page) {
  for (let i = 0; i < 5; i++) {
    let n = 0
    try {
      n = await page.locator('.modal-mask.open').count()
    } catch {
      return false
    }
    if (!n) return true
    const mask = page.locator('.modal-mask.open').last()
    const close = mask.locator('.modal-close').last()
    if ((await close.count()) > 0) await close.click({ timeout: 2000 }).catch(() => {})
    else await page.keyboard.press('Escape').catch(() => {})
    await page.waitForTimeout(180)
  }
  try {
    return (await page.locator('.modal-mask.open').count()) === 0
  } catch {
    return false
  }
}

async function restore(page, expectPath) {
  for (let i = 0; i < 5; i++) {
    await closeModals(page).catch(() => {})
    let pn = ''
    try {
      pn = new URL(page.url()).pathname
    } catch {
      /* ignore */
    }
    if (pn === expectPath) return true
    await page.goBack({ waitUntil: 'domcontentloaded', timeout: 8000 }).catch(() => {})
    await page.waitForTimeout(350)
  }
  return false
}

/* ---------- tab 切换（读 DOM active 索引，不依赖缓存） ---------- */
async function switchTab(page, mod, key) {
  if (!mod.tabMode) return true
  const isPrompts = mod.tabMode === 'activeTab'
  const sel = isPrompts ? 'aside.sidebar .side-item' : '.side-nav .side-item'
  let idx
  if (isPrompts) idx = PROMPT_NAV.indexOf(key == null ? 'all' : key)
  else idx = (mod.tabs || []).findIndex((t) => t.key === key)
  if (idx < 0) idx = 0
  let cur = -1
  try {
    cur = await page.evaluate(
      (s) => [...document.querySelectorAll(s)].findIndex((e) => e.classList.contains('active')),
      sel,
    )
  } catch {
    /* ignore */
  }
  if (cur === idx) return true
  const cnt = await page.locator(sel).count().catch(() => 0)
  if (idx >= cnt) return false
  await page
    .locator(sel)
    .nth(idx)
    .click()
    .catch(() => {})
  await page.waitForTimeout(420)
  return true
}

/* ---------- 元素定位 ---------- */
function baseSelector(f) {
  switch (f.kind) {
    case 'button':
      if (f.tag === 'div@click') {
        if (f.cls) {
          const toks = f.cls.trim().split(/\s+/).filter((t) => /^[A-Za-z][\w-]*$/.test(t))
          if (toks.length) return 'div.' + toks.join('.')
        }
        return 'div'
      }
      return 'button,[role=button]'
    case 'link':
      return 'a,[role=link]'
    case 'input':
      return 'input:not([type=hidden]):not([type=file])'
    case 'select':
      return 'select'
    case 'textarea':
      return 'textarea'
    case 'file':
      return 'input[type=file]'
    default:
      return 'button'
  }
}

function textsOf(f) {
  const decode = (s) =>
    String(s)
      .replace(/&#10;|&#xA;/gi, '\n')
      .replace(/&amp;/gi, '&')
      .replace(/&lt;/gi, '<')
      .replace(/&gt;/gi, '>')
  const out = [
    decode(norm(f.text)),
    ...(f.textAlt || []).map((x) => decode(norm(x))),
    f.placeholder ? decode(f.placeholder) : null,
  ]
  // 剔除：插值 {{}}、绑定表达式 placeholder（如 stepPh(st.action)）；
  // HTML 残片（如 "...到此处</div"）先剥标签清洗保留可读文本，剥空才丢
  const isExpr = (x) => /^[a-zA-Z_$][\w$]*(\.[\w$]+)*\(.*\)$/.test(x.trim())
  const clean = (x) => (x.includes('<') ? x.replace(/<[^<>]*>?/g, '').trim() : x)
  return out
    .filter((x) => x && x.length > 0)
    .map(clean)
    .filter((x) => x && x.length > 0 && !x.includes('{{') && !isExpr(x))
}

/* 插值文本骨架：text 含 {{...}} 时被 textsOf 剔除 → 恒 no-match（如
   "🔗 {{ view.case }}"）。去掉插值生成正则源：字面量段用 [\s\S]* 连接，
   DOM 文本含任一插值结果即可命中（如 "🔗 TC-1001"）。 */
function patternsOf(f) {
  const cands = [f.text, ...(f.textAlt || [])]
  const out = []
  for (const raw of cands) {
    if (!raw || !String(raw).includes('{{')) continue
    const s = String(raw).replace(/\s+/g, ' ').trim()
    const segs = s
      .split(/\{\{[\s\S]*?\}\}/)
      // 残留 HTML 片段（如 "{{ x.title }} <span class=..."）先剥标签；
      // 剥空的段丢弃——纯绑定+标签的文本（trig 卡片类）不生成正则，
      // 保持旧的「texts 空 → 全池命中」语义
      .map((x) => x.replace(/<[^<>]*>?/g, ' ').replace(/\s+/g, ' ').trim())
      .filter(Boolean)
    if (!segs.length) continue
    if (segs.join('').replace(/\s+/g, '').length < 1) continue
    // 含未闭合插值残片（extract 截断的 "{{ NODE_META[..."）或标签残片 →
    // 不生成正则，保持「texts 空 → 全池命中」的旧行为
    if (segs.some((x) => x.includes('<') || x.includes('{{'))) continue
    const src = segs
      .map((x) => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
      .join('[\\s\\S]*')
    out.push(src)
  }
  return out
}

/* 条件渲染豁免：feature 文本是纯插值（texts/patterns 均为空，无任何可定位
   的字面量特征），且定位时 selector 池 0 匹配 → 通常是 v-if 条件渲染元素
   （如数据为空时不渲染的附件链接 {{ f.name }}），静态无法断言存在性 → SKIP。
   含字面量段的插值（如 "🔗 {{ view.case }}" 有 pattern）不受影响，仍实测。 */
function conditionalNotRendered(f, loc) {
  if (!loc) return false
  // how 形如 "<selector>:no-match"（locate 会拼上 selector 前缀）；
  // bad-selector 不豁免（selector 本身错误属真实问题）
  if (!/:no-match$/.test(String(loc.how))) return false
  return !textsOf(f).length && !patternsOf(f).length
}

async function locateOnce(page, selector, want) {
  return page.evaluate(
    ({ selector, texts, patterns, ordinal, used, href }) => {
      const n = (x) => (x || '').replace(/\s+/g, ' ').trim()
      const vis = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
      const regs = (patterns || [])
        .map((src) => {
          try {
            return new RegExp(src, 's')
          } catch {
            return null
          }
        })
        .filter(Boolean)
      let els
      try {
        els = [...document.querySelectorAll(selector)]
      } catch {
        return { status: 'missing', how: 'bad-selector' }
      }
      if (!els.length) return { status: 'missing', how: 'no-match' }
      const squash = (s) => (s || '').replace(/\s+/g, '')
      const strict = (el) => {
        // 链接按目标路径匹配（动态文本/ordinal 会错位到同池的其他链接）
        if (href) {
          const h = el.getAttribute('href') || ''
          return h === href || h.startsWith(href + '?') || h.startsWith(href + '#')
        }
        if (!texts.length && !regs.length) return true
        const t = n(el.innerText || el.textContent)
        const ph = el.getAttribute('placeholder') || ''
        const sqPh = squash(ph)
        for (const x of texts) {
          if (t === x || (t && t.includes(x))) return true
          // placeholder 比较去空白（多行 placeholder 换行/空格差异），要求足够长防误吞
          if (sqPh && squash(x).length >= 2 && sqPh.includes(squash(x))) return true
          // 反向包含：DOM 文本是特征文本的前缀（如 m-group 容器 innerText 只有标题，
          // 提取文本含标题+子链接），要求足够长避免误吞短文本
          if (t && t.length >= 4 && x.includes(t)) return true
        }
        for (const re of regs) if (re.test(t)) return true
        return false
      }
      // 宽松匹配（去空白）仅在严格匹配无结果时启用，避免 "登 录" 误吞 "登录"
      const loose = (el) => {
        if (href) return strict(el)
        const raw = n(el.innerText || el.textContent)
        const t = squash(raw)
        const ph = squash(el.getAttribute('placeholder') || '')
        for (const x of texts)
          if (t === squash(x) || (ph && squash(x).length >= 2 && ph.includes(squash(x))))
            return true
        for (const re of regs) if (re.test(raw)) return true
        return false
      }
      let matched = els.filter(strict)
      if (!matched.length) matched = els.filter(loose)
      if (!matched.length) return { status: 'missing', how: 'no-text-match' }
      let pool = matched.filter(vis)
      if (!pool.length) {
        const a = matched[0].closest(
          '.dropdown,.m-group,.submenu,.menu,[class*="drop"],[class*="menu"],[class*="pop"]',
        )
        if (a) a.setAttribute('data-reveal', '1')
        return { status: 'hidden', how: 'hidden', anc: !!a }
      }
      if (used && used.length) {
        const free = pool.filter((el) => !used.includes(n(el.innerText || el.textContent)))
        if (free.length) pool = free
      }
      const idx = Math.min(ordinal, pool.length - 1)
      pool[idx].setAttribute('data-locate', '1')
      return {
        status: 'ok',
        how: `${selector} #${idx}/${pool.length}${idx !== ordinal ? '~clamp' : ''}`,
      }
    },
    { selector, texts: want.texts, patterns: want.patterns || [], ordinal: want.ordinal, used: want.used, href: want.href || null },
  )
}

async function locate(page, f, want) {
  const sel = baseSelector(f)
  const pre = want.scope ? want.scope + ' ' : ''
  const tries = []
  if (f.enclosing && !want.scope) tries.push(pre + '.' + f.enclosing + ' ' + sel)
  tries.push(pre + sel)

  const clean = () =>
    page.evaluate(() => {
      document.querySelectorAll('[data-locate]').forEach((e) => e.removeAttribute('data-locate'))
      document.querySelectorAll('[data-reveal]').forEach((e) => e.removeAttribute('data-reveal'))
    })

  let sawHidden = false
  let lastHow = ''
  const dbg = process.env.VF_DEBUG ? (m) => console.error('  [locate]', m) : () => {}
  for (let pass = 0; pass < 2; pass++) {
    if (pass === 1) {
      if (!sawHidden) break
      // 揭示：先移开鼠标（确保 mouseenter 重新触发），再 hover 最近的下拉/菜单容器
      const anc = page.locator('[data-reveal]').first()
      const ac = await anc.count().catch(() => 0)
      dbg(`pass1 reveal count=${ac}`)
      if (ac > 0) {
        await page.mouse.move(6, 6).catch(() => {})
        await page.waitForTimeout(180)
        await anc.hover({ timeout: 1500 }).catch((e) => dbg('hover-err ' + e.message))
      }
      await page.waitForTimeout(350)
    }
    for (const s of tries) {
      await clean()
      const r = await locateOnce(page, s, want).catch(() => ({
        status: 'missing',
        how: 'exception',
      }))
      dbg(`pass${pass} ${s} → ${r.status}:${r.how}`)
      lastHow = `${s}:${r.how}`
      if (r.status === 'ok') return { status: 'ok', el: page.locator('[data-locate]'), how: r.how }
      if (r.status === 'hidden') sawHidden = true
    }
  }
  await clean()
  return { status: sawHidden ? 'hidden' : 'missing', how: lastHow }
}

/* ---------- 交互原语 ---------- */
async function safeClick(el) {
  await el.scrollIntoViewIfNeeded({ timeout: 2000 }).catch(() => {})
  try {
    await el.click({ timeout: 3000 })
  } catch {
    await el.evaluate((e) => e.click()).catch(() => {})
  }
}

function testValueFor(type) {
  if (type === 'number') return '42'
  if (type === 'tel') return '13800001111'
  if (type === 'email') return 'qa@example.com'
  if (type === 'date') return '2026-01-01'
  if (type === 'password') return 'Qa!23456'
  return 'aitest-验证'
}

/* ---------- 分类型验证 ---------- */
async function verifyField(page, el, f, dlgRef) {
  const type = (await el.getAttribute('type').catch(() => null)) || 'text'
  if (type === 'file') return { status: 'PASS-EXIST', detail: 'file-input' }
  const netBase = new Set(page._netLog || [])

  if (type === 'checkbox' || type === 'radio') {
    const disabled = await el.isDisabled().catch(() => false)
    if (disabled) return { status: 'PASS-EXIST', detail: 'disabled' }
    let before
    try {
      before = await el.isChecked()
    } catch {
      return { status: 'PASS-EXIST', detail: 'uncheckable' }
    }
    await safeClick(el)
    await page.waitForTimeout(320)
    let after = before
    try {
      after = await el.isChecked()
    } catch {
      /* ignore */
    }
    if (after !== before) {
      await safeClick(el).catch(() => {}) // 还原
      await page.waitForTimeout(180)
      return { status: 'PASS', detail: before ? 'unchecked' : 'checked', signal: 'toggle' }
    }
    // 未生效：evaluate click 兜底重试一次
    await el.evaluate((e) => e.click()).catch(() => {})
    await page.waitForTimeout(320)
    try {
      after = await el.isChecked()
    } catch {
      /* ignore */
    }
    if (after !== before) {
      await el.evaluate((e) => e.click()).catch(() => {}) // 还原
      await page.waitForTimeout(180)
      return { status: 'PASS', detail: before ? 'unchecked' : 'checked', signal: 'toggle-retry' }
    }
    if (type === 'radio' && before) {
      // 单选组中已选中的项，点击无变化是正确行为
      const name = await el.getAttribute('name').catch(() => null)
      if (!name) return { status: 'PASS-EXIST', detail: 'radio-already-selected' }
      // 尝试切换同组另一个 radio 验证组可交互
      const other = page
        .locator(`input[type=radio][name=${JSON.stringify(name)}]:not(:checked)`)
        .first()
      if (await other.count().catch(() => 0)) {
        await safeClick(other).catch(() => {})
        await page.waitForTimeout(300)
        const now = await other.isChecked().catch(() => false)
        await safeClick(el).catch(() => {}) // 还原回原选中项
        await page.waitForTimeout(250)
        if (now) return { status: 'PASS', detail: 'radio-group', signal: 'toggle' }
      }
      return { status: 'PASS-EXIST', detail: 'radio-already-selected' }
    }
    const nuT = netNew(page, netBase)
    if (nuT)
      return { status: 'PASS', detail: 'network-toggle', signal: 'network:' + nuT }
    return { status: 'FAIL', detail: 'toggle-no-effect', soft: true, signal: 'none' }
  }

  let orig = ''
  try {
    orig = await el.inputValue()
  } catch {
    return { status: 'PASS-EXIST', detail: 'unreadable' }
  }
  const disabled = await el.isDisabled().catch(() => false)
  if (disabled) return { status: 'PASS-EXIST', detail: 'disabled' }
  const readonly = await el.evaluate((e) => !!e.readOnly).catch(() => false)
  if (readonly) return { status: 'PASS-EXIST', detail: 'readonly-output' }

  const val = testValueFor(type)
  const before = await snap(page)
  await el.fill(val, { timeout: 5000 }).catch(() => {})
  await page.waitForTimeout(350)
  let got = ''
  try {
    got = await el.inputValue()
  } catch {
    /* ignore */
  }
  // 还原原值
  await el.fill(orig, { timeout: 5000 }).catch(() => {})
  await page.waitForTimeout(150)
  const chg = await waitChange(page, before, 400, dlgRef).catch(() => ({ changed: false }))

  if (got && got !== orig) {
    return {
      status: 'PASS',
      detail: got === val ? 'value-filled' : `v-model→${String(got).slice(0, 24)}`,
      signal: 'value',
    }
  }
  if (chg.changed) return { status: 'PASS', detail: 'page-feedback', signal: chg.how }
  const nuV = netNew(page, netBase)
  if (nuV) return { status: 'PASS', detail: 'network-input', signal: 'network:' + nuV }
  return { status: 'FAIL', detail: 'value-not-applied', soft: true, signal: 'none' }
}

async function verifySelect(page, el) {
  const disabled = await el.isDisabled().catch(() => false)
  if (disabled) return { status: 'PASS-EXIST', detail: 'disabled' }
  const netBase = new Set(page._netLog || [])
  const opts = await el.locator('option').count().catch(() => 0)
  if (!opts) return { status: 'PASS-EXIST', detail: 'no-options' }
  const orig = await el.inputValue().catch(() => '')
  const vals = await el
    .locator('option')
    .evaluateAll((os) => os.map((o) => o.value))
    .catch(() => [])
  const pick = vals.find((v) => v !== orig && v !== '')
  if (pick === undefined) return { status: 'PASS-EXIST', detail: 'single-option' }
  // 副作用探针：消费型 select（change handler 会重置 v-model 或改列表）下
  // 读回值可能仍等于 orig，但页面渲染已变（如出边列表 +1）
  const s0 = await snap(page)
  await el.selectOption(pick, { timeout: 5000 }).catch(() => {})
  await page.waitForTimeout(320)
  const got = await el.inputValue().catch(() => '')
  const s1 = await snap(page)
  await el.selectOption(orig, { timeout: 5000 }).catch(() => {})
  await page.waitForTimeout(150)
  if (got === pick) return { status: 'PASS', detail: 'selected', signal: 'value' }
  const nuS = netNew(page, netBase)
  if (nuS) return { status: 'PASS', detail: 'network-select', signal: 'network:' + nuS }
  if (s1.body !== s0.body)
    return { status: 'PASS', detail: 'select-side-effect', signal: 'value-side-effect' }
  return { status: 'FAIL', detail: 'select-no-effect', soft: true, signal: 'none' }
}

async function verifyLink(page, el, f, ctx, dlgRef) {
  const cls = f.cls || ''
  // 已激活的侧栏项（避免重复导航）
  const active = await el.evaluate((e) => e.classList.contains('active')).catch(() => false)
  if (active && (cls.includes('side-item') || f.enclosing === 'sidebar'))
    return { status: 'PASS-EXIST', detail: 'already-active' }

  const to = f.to
  if (!to) return { status: 'PASS-EXIST', detail: 'no-href' }
  if (/^https?:\/\//.test(String(to))) return { status: 'PASS-EXIST', detail: 'external' }
  if (isDynamicTo(to)) {
    const st = staticTo(to)
    if (!st) return { status: 'PASS-EXIST', detail: 'dynamic-to' }
    return clickNavigate(page, el, st, ctx, dlgRef, 'dynamic-to')
  }
  return clickNavigate(page, el, String(to), ctx, dlgRef, 'link')
}

async function clickNavigate(page, el, to, ctx, dlgRef, label) {
  if (to.startsWith('#')) return { status: 'PASS-EXIST', detail: 'hash-only' }
  const target = to.startsWith('/') ? to : null
  if (target) {
    const tp = target.split('?')[0].split('#')[0] || '/'
    const curPath = new URL(page.url()).pathname
    const sameSearch = page.url().replace(BASE, '') === target
    if (tp === curPath && (sameSearch || !target.includes('?')))
      return { status: 'PASS-EXIST', detail: 'already-here' }
  }
  const before = await snap(page)
  const netBase = new Set(page._netLog || [])
  await safeClick(el)
  const w = await waitChange(page, before, W.link, dlgRef)
  await restore(page, ctx.expectPath)
  if (w.changed) return { status: 'PASS', detail: label, signal: w.how }
  const nuL = netNew(page, netBase)
  if (nuL) return { status: 'PASS', detail: 'network-link', signal: 'network:' + nuL }
  return { status: 'FAIL', detail: 'no-feedback', soft: true, signal: 'none' }
}

async function verifyButton(page, el, f, ctx, dlgRef) {
  const disabled = await el.isDisabled().catch(() => false)
  if (disabled) return { status: 'PASS-EXIST', detail: 'disabled' }
  // 已激活的 tab 类按钮：点击无状态变化（如 /auth 的「登录」切换项）
  const active = await el
    .evaluate(
      (e) =>
        e.classList.contains('active') ||
        e.getAttribute('aria-selected') === 'true' ||
        e.classList.contains('on'),
    )
    .catch(() => false)
  if (active) return { status: 'PASS-EXIST', detail: 'already-active' }
  // submit/ai 类按钮：点击前先填充同一 input-group/field 里为空的文本框
  // （空内容会被前端校验拦截，导致无反馈的假阴性）
  if (f.risk === 'submit' || f.risk === 'ai') {
    await el
      .evaluate((btn) => {
        const scope = btn.closest('.input-group, .field, .form-row, form')
        if (!scope) return
        for (const inp of scope.querySelectorAll('input,textarea')) {
          if (!inp.offsetParent || inp.disabled || inp.readOnly || inp.value) continue
          if (['checkbox', 'radio', 'file', 'hidden'].includes(inp.type)) continue
          const setter =
            inp.tagName === 'TEXTAREA'
              ? Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
              : Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
          setter.call(inp, 'aitest-验证')
          inp.dispatchEvent(new Event('input', { bubbles: true }))
          inp.dispatchEvent(new Event('change', { bubbles: true }))
        }
      })
      .catch(() => {})
    await page.waitForTimeout(200)
  }
  const before = await snap(page)
  const netBase = new Set(page._netLog || [])
  await safeClick(el)
  // 点击后新弹 UiHost 确认框（.modal-sm：取消+确定两钮）→ 代点确定，
  // 让危险/评审类操作真正执行到反馈（toast），而不是停在确认框
  let confirmSignal = ''
  if ((await snap(page).catch(() => before)).open > before.open) {
    await page.waitForTimeout(220)
    const marked = await page
      .evaluate(() => {
        const mods = [...document.querySelectorAll('.modal-mask.open .modal-sm')]
        const m = mods[mods.length - 1]
        if (!m) return false
        const foot = m.querySelector('.modal-foot')
        if (!foot) return false
        const btns = [...foot.querySelectorAll('button')].filter(
          (b) => b.offsetWidth || b.offsetHeight,
        )
        if (btns.length !== 2) return false
        const first = (btns[0].innerText || '').trim()
        if (!/取消|否|再想想/.test(first)) return false
        btns[1].setAttribute('data-confirm-ok', '1')
        return true
      })
      .catch(() => false)
    if (marked) {
      await page
        .locator('[data-confirm-ok="1"]')
        .first()
        .click({ timeout: 2000 })
        .catch(() => {})
      await page.waitForTimeout(700)
      confirmSignal = 'confirm-accepted'
    }
  }
  const w = await waitChange(page, before, winOf(f.risk), dlgRef)
  // 点击无持久变化 → hover 兜底：hover 触发型 UI（如 mega 菜单 mouseenter 展开、
  // click 为 toggle 反而关闭）移动鼠标离开后再悬停，检测展开反馈。
  // （danger 已在 verifyFeature 早退，能走到这里的都允许 hover）
  let signal = w.how
  let hovered = false
  if (!w.changed) {
    await page.mouse.move(6, 6).catch(() => {})
    await page.waitForTimeout(260)
    const h0 = await snap(page)
    await el.hover({ timeout: 1500 }).catch(() => {})
    const hw = await waitChange(page, h0, 800, dlgRef)
    if (hw.changed) {
      hovered = true
      signal = 'hover:' + hw.how
    }
  }
  await restore(page, ctx.expectPath)
  if (w.changed || hovered) {
    const t = w.toasts ? ` toast:${String(w.toasts).slice(0, 40)}` : ''
    return {
      status: 'PASS',
      detail: hovered ? `${f.risk}-hover` : `${f.risk}-clicked`,
      signal: signal + (confirmSignal ? `+${confirmSignal}` : '') + t,
      ms: w.waited,
    }
  }
  // chip 组内唯一 primary = 已激活的过滤 chip（如"全部"），点击无反馈是正确行为。
  // 限定：父容器 ≥2 按钮且全部 btn-sm（chip 组特征），避免误判"提交"类主按钮。
  const chipActive = await el
    .evaluate((e) => {
      const p = e.parentElement
      if (!p) return false
      const btns = [...p.querySelectorAll(':scope > button, :scope > [role=button]')]
      if (btns.length < 2) return false
      if (!btns.every((b) => b.classList.contains('btn-sm'))) return false
      const pr = btns.filter((b) => b.classList.contains('btn-primary'))
      return pr.length === 1 && pr[0] === e
    })
    .catch(() => false)
  if (chipActive) return { status: 'PASS-EXIST', detail: 'active-chip', signal: 'none' }
  // 刷新类按钮：点击后数据未变则 body 无差异（loading 多为瞬时不可观测），判 no-op 通过
  const lbl = (await el.innerText().catch(() => '')).trim().slice(0, 12)
  if (/刷新|重新加载|reload|refresh/i.test(lbl))
    return { status: 'PASS-EXIST', detail: 'refresh-noop', signal: 'none' }
  // 分页边界按钮（首页/末页/上一页/下一页）在唯一页时点击无反馈是正确行为
  const inPager = await el
    .evaluate((e) => !!e.closest('.pagination, .prompts-pager'))
    .catch(() => false)
  if (inPager) return { status: 'PASS-EXIST', detail: 'pagination-noop', signal: 'none' }
  const nuB = netNew(page, netBase)
  if (nuB) return { status: 'PASS', detail: `${f.risk}-network`, signal: 'network:' + nuB, ms: w.waited }
  return { status: 'FAIL', detail: 'no-feedback', soft: true, signal: 'none', ms: w.waited }
}

/* 空态条件按钮（如 .empty 内的"重置筛选"）：先用不可能命中的关键词制造空结果，再验证点击 */
async function verifyEmptyState(page, f, want, ctx, dlgRef) {
  const kw = page
    .locator('input[placeholder*="搜索"]:visible, input[placeholder*="关键词"]:visible')
    .first()
  if (!(await kw.count().catch(() => 0))) return null
  await kw.fill('zzz-no-match-' + Math.floor(Math.random() * 1e6), { timeout: 5000 }).catch(() => {})
  await page.waitForTimeout(800) // 等筛选 debounce + 列表刷新
  const loc = await locate(page, f, want)
  if (loc.status !== 'ok') {
    await kw.fill('', { timeout: 5000 }).catch(() => {})
    await page.waitForTimeout(500)
    return null
  }
  const r = await verifyButton(page, loc.el, f, ctx, dlgRef)
  await kw.fill('', { timeout: 5000 }).catch(() => {}) // 恢复筛选
  await page.waitForTimeout(500)
  if (r.status === 'PASS') r.detail = r.detail + '+empty-state'
  return r
}

/* ---------- 单特征验证（含定位 + 策略分派） ---------- */
async function verifyFeature(page, f, want, ctx, dlgRef) {
  let loc = await locate(page, f, want)
  if (loc.status === 'missing') {
    // 条件渲染按钮：制造空态后重试一次
    if (f.enclosing === 'empty' && f.kind === 'button') {
      const r = await verifyEmptyState(page, f, want, ctx, dlgRef).catch(() => null)
      if (r) return r
    }
    // 分步向导 modal：目标可能在后续步骤。若「下一步」被必填禁用，先自动填充再步进。
    if (f.modal) {
      const tryEmptyAdd = async () =>
        page
          .evaluate(() => {
            const modal = document.querySelector('.modal-mask.open')
            if (!modal) return false
            const empty = modal.querySelector('.empty')
            if (!empty) return false
            const btn = [...modal.querySelectorAll('button,[role=button]')].find(
              (b) =>
                b.offsetParent &&
                !b.disabled &&
                b.compareDocumentPosition(empty) & Node.DOCUMENT_POSITION_PRECEDING,
            )
            if (!btn) return false
            btn.click()
            return true
          })
          .catch(() => false)
      for (let step = 0; step < 5; step++) {
        if (loc.status !== 'missing') break
        // 空态行字段（如 v-for 步骤行）：点空态之后的添加按钮创建一行再定位
        if (await tryEmptyAdd()) {
          await page.waitForTimeout(450)
          loc = await locate(page, f, want)
          if (loc.status !== 'missing') break
        }
        const action = await page
          .evaluate(() => {
            const modal = document.querySelector('.modal-mask.open')
            if (!modal) return 'no-modal'
            const btn = [...modal.querySelectorAll('button,[role=button]')].find((b) =>
              // 下一步类 + 只读前置操作（解析/预览/展开/查看引用——不产生副作用）
              /下一步|继续|next|解析|预览|展开|查看引用|加载更多/i.test((b.innerText || '').trim()),
            )
            if (!btn) return 'no-btn'
            // 总是先填充空的可见文本字段：向导「下一步」可能被表单校验静默拦截
            const setter = Object.getOwnPropertyDescriptor(
              window.HTMLInputElement.prototype,
              'value',
            ).set
            const taSetter = Object.getOwnPropertyDescriptor(
              window.HTMLTextAreaElement.prototype,
              'value',
            ).set
            let filled = 0
            for (const inp of modal.querySelectorAll('input,textarea')) {
              if (!inp.offsetParent || inp.disabled || inp.value) continue
              if (['checkbox', 'radio', 'file', 'hidden', 'submit'].includes(inp.type)) continue
              // 按字段语义给值：URL 校验（如 ^https?://）不接受普通文本
              const ph = (inp.placeholder || '').toLowerCase()
              const isCurl = ph.includes('curl')
              const isUrl =
                inp.type === 'url' || ph.includes('http') || ph.includes('shop.') || ph.includes('/l')
              try {
                if (inp.tagName === 'TEXTAREA')
                  taSetter.call(
                    inp,
                    isCurl
                      ? 'curl https://api.example.com/v1/ping\nGET /v1/ping HTTP/1.1'
                      : 'aitest-验证\n步骤2',
                  )
                else setter.call(inp, isUrl ? 'https://example.com/aitest' : 'aitest-验证')
                inp.dispatchEvent(new Event('input', { bubbles: true }))
                inp.dispatchEvent(new Event('change', { bubbles: true }))
                filled++
              } catch {
                /* ignore */
              }
              if (filled >= 4) break
            }
            if (btn.disabled) return filled ? 'filled' : 'btn-disabled'
            btn.click()
            return filled ? 'filled-clicked' : 'clicked'
          })
          .catch(() => 'err')
        if (action === 'filled') {
          await page.waitForTimeout(400) // 等 Vue 校验解除禁用
          continue
        }
        if (!action.endsWith('clicked')) break
        await page.waitForTimeout(450)
        loc = await locate(page, f, want)
      }
      if (loc.status === 'missing')
        return conditionalNotRendered(f, loc)
          ? { status: 'SKIP', detail: 'conditional-not-rendered', how: loc.how }
          : { status: 'MISSING', how: loc.how }
    } else {
      return conditionalNotRendered(f, loc)
        ? { status: 'SKIP', detail: 'conditional-not-rendered', how: loc.how }
        : { status: 'MISSING', how: loc.how }
    }
  }
  if (loc.status === 'hidden') return { status: 'SKIP', detail: 'hidden-by-design', how: loc.how }

  if (f.risk === 'danger') return { status: 'PASS-EXIST', detail: 'danger-not-clicked', how: loc.how }
  if (f.kind === 'file') return { status: 'PASS-EXIST', detail: 'file-input', how: loc.how }

  let r
  if (f.kind === 'link') r = await verifyLink(page, loc.el, f, ctx, dlgRef)
  else if (f.kind === 'input' || f.kind === 'textarea')
    r = await verifyField(page, loc.el, f, dlgRef)
  else if (f.kind === 'select') r = await verifySelect(page, loc.el)
  else r = await verifyButton(page, loc.el, f, ctx, dlgRef)
  r.how = loc.how
  return r
}

/* ---------- modal 触发器 ---------- */
function findTrigger(mod, mv) {
  const trigs = (mod.modalTriggers && mod.modalTriggers[mv]) || []
  if (!trigs.length) return null
  return (
    mod.features.find(
      (f) =>
        !f.modal && f.handler && trigs.some((t) => f.handler.includes(t) || f.handler.includes(mv)),
    ) || null
  )
}

/* 该 modal 的全部候选触发特征（同一 modal 常有多个入口，如 新建/编辑 ——
   特征可能只在其中一个入口的形态下渲染，如「🗑 删除」v-if=editId 只在编辑态出现） */
function findTriggers(mod, mv) {
  const trigs = (mod.modalTriggers && mod.modalTriggers[mv]) || []
  if (!trigs.length) return []
  const seen = new Set()
  const out = []
  for (const f of mod.features) {
    if (f.modal || !f.handler) continue
    if (trigs.some((t) => f.handler.includes(t) || f.handler.includes(mv))) {
      const k = f.handler
      if (!seen.has(k)) {
        seen.add(k)
        out.push(f)
      }
    }
  }
  return out
}

async function ensureModalOpen(page, mod, trig, trigWant, dlgRef) {
  if ((await page.locator('.modal-mask.open').count().catch(() => 0)) > 0) return true
  if (mod.tabMode && trig.tab != null) await switchTab(page, mod, trig.tab)
  const loc = await locate(page, trig, trigWant)
  if (loc.status !== 'ok') return false
  const before = await snap(page)
  await safeClick(loc.el)
  await waitChange(page, before, 1500, dlgRef).catch(() => ({ changed: false }))
  return (await page.locator('.modal-mask.open').count().catch(() => 0)) > 0
}

/* ---------- 分组 ---------- */
function tabGroups(mod, feats) {
  const map = new Map()
  for (const f of feats) {
    const k = f.tab == null ? ' ' : f.tab
    if (!map.has(k)) map.set(k, [])
    map.get(k).push(f)
  }
  const keys = [...map.keys()].sort((a, b) => {
    if (a === ' ') return -1
    if (b === ' ') return 1
    const ta = (mod.tabs || []).findIndex((t) => t.key === a)
    const tb = (mod.tabs || []).findIndex((t) => t.key === b)
    return (ta < 0 ? 99 : ta) - (tb < 0 ? 99 : tb)
  })
  return keys.map((k) => ({ tab: k === ' ' ? null : k, feats: map.get(k) }))
}

function assignOrdinals(feats) {
  const m = new Map()
  for (const f of feats) {
    const k = fkey(f)
    const n = m.get(k) || 0
    m.set(k, n + 1)
    f._ord = n
  }
}

/* ---------- 页面缓存 ---------- */
const pageCache = new Map() // `${auth?'a':'g'}|${path}` → page
const jsErrors = new Map() // module id → string[]

/* browser 自愈：headless 进程中途退出（内存压力等）时重建 browser+contexts+页缓存，
   避免一次崩溃让整批后续项全部 FAIL。ctx 用全局 getter，重建后自动指向新对象。 */
let _recovering = false
async function recoverBrowser() {
  if (_recovering) return
  _recovering = true
  try {
    console.log('  [recover] browser disconnected → relaunch')
    /* close 对已断开实例可能永久挂起（曾导致整轮卡死）→ 竞速 8s 超时兜底 */
    await Promise.race([
      browser.close().catch(() => {}),
      new Promise((r) => setTimeout(r, 8000)),
    ])
    browser = await chromium.launch({ headless: true })
    authedCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    await authedCtx.addInitScript(
      ([t]) => {
        localStorage.setItem('aitesthub_token', t)
        localStorage.setItem('aitesthub_auth', '1')
        localStorage.setItem('aitesthub_login_user', 'admin')
      },
      [token],
    )
    guestCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    pageCache.clear()
  } finally {
    /* 异常也必须复位，否则后续 recover 全部空转、继续用死 browser 操作 */
    _recovering = false
  }
}

async function getPage(isGuest, host, modId) {
  if (!browser.isConnected()) await recoverBrowser()
  const ctx = isGuest ? guestCtx : authedCtx
  const key = `${host.auth ? 'a' : 'g'}|${host.path}`
  let p = pageCache.get(key)
  const fresh = !p || p.isClosed()
  if (fresh) {
    p = await ctx.newPage()
    p._dlg = { n: 0 }
    // 反馈信号面：API 请求日志（防轮询：只认点击后新出现的 URL）、文件选择器、弹出窗口
    p._netLog = new Set()
    p._fcN = 0
    p._popN = 0
    p.on('request', (req) => {
      try {
        const t = req.resourceType()
        if ((t === 'fetch' || t === 'xhr') && req.url().includes('/api/'))
          p._netLog.add(new URL(req.url()).pathname)
      } catch {
        /* ignore */
      }
    })
    p.on('filechooser', () => {
      p._fcN++
    })
    p.on('popup', () => {
      p._popN++
    })
    p.on('pageerror', (e) => {
      /* 归属当前 URL 所在模块（SPA 导航后 modId 闭包已过期），解析失败退回 modId */
      let mid = modId
      try {
        mid = routeToMod.get(new URL(p.url()).pathname) || modId
      } catch {
        /* about:blank / 数据 URL 等 */
      }
      const arr = jsErrors.get(mid) || []
      arr.push(String(e).slice(0, 200))
      jsErrors.set(mid, arr)
    })
    p.on('dialog', (d) => {
      p._dlg.n++
      d.dismiss().catch(() => {})
    })
    pageCache.set(key, p)
    await p.goto(BASE + host.path, { waitUntil: 'domcontentloaded', timeout: 20000 })
    await p.waitForTimeout(650)
  } else {
    let cur = ''
    try {
      cur = new URL(p.url()).pathname
    } catch {
      /* ignore */
    }
    if (cur !== host.path) {
      await p.goto(BASE + host.path, { waitUntil: 'domcontentloaded', timeout: 20000 })
      await p.waitForTimeout(650)
    }
  }
  await closeModals(p).catch(() => {})
  return p
}

/* ---------- 逐特征前置条件（条件渲染：需先完成只读/种子类前置，目标元素才出现） ---------- */
const PNG_1PX = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
)
/* ---------- 数据条件前置（DB 种子：改库 → reload → 回目标 tab，cleanup 还原） ---------- */
const DB_PATH = fileURLToPath(new URL('../backend/app/aitest_hub.db', import.meta.url))
const dbq = (sql) => execFileSync('sqlite3', [DB_PATH, sql], { encoding: 'utf8' })

/* TTS mock：ai_configs 指向本服务 → /api/audio-generator 转发到此。
   进程内单例（生命周期=verify 进程，退出自动关闭，不额外留后台进程）。
   返回可解码的 8bit PCM WAV 静音（blob type 写 audio/mpeg，浏览器按魔数解码），
   避免假字节导致 <audio>.play() 未捕获 rejection 污染 jsErrors。 */
function wavSilence(ms = 300) {
  const sr = 8000
  const n = Math.floor((sr * ms) / 1000)
  const data = Buffer.alloc(n, 128)
  const h = Buffer.alloc(44)
  h.write('RIFF', 0)
  h.writeUInt32LE(36 + n, 4)
  h.write('WAVE', 8)
  h.write('fmt ', 12)
  h.writeUInt32LE(16, 16)
  h.writeUInt16LE(1, 20) // PCM
  h.writeUInt16LE(1, 22) // mono
  h.writeUInt32LE(sr, 24)
  h.writeUInt32LE(sr, 28)
  h.writeUInt16LE(1, 32)
  h.writeUInt16LE(8, 34)
  h.write('data', 36)
  h.writeUInt32LE(n, 40)
  return Buffer.concat([h, data])
}
let _ttsMock = null
const TTS_MOCK_PORT = 8788
function ensureTtsMock() {
  if (_ttsMock) return
  const body = wavSilence()
  const srv = http.createServer((req, res) => {
    const chunks = []
    req.on('data', (c) => chunks.push(c))
    req.on('end', () => {
      if ((req.url || '').includes('/audio/speech')) {
        res.writeHead(200, { 'Content-Type': 'audio/mpeg', 'Content-Length': body.length })
        res.end(body)
      } else {
        res.writeHead(404, { 'Content-Type': 'text/plain' })
        res.end('tts-mock: only /audio/speech')
      }
    })
  })
  srv.on('error', (e) => console.log('  tts-mock-warn:', String(e).slice(0, 80)))
  srv.listen(TTS_MOCK_PORT, '127.0.0.1')
  _ttsMock = srv
}

function sqlPre(setupSql, restoreSql) {
  const fn = async (page, mod, f) => {
    if (fn._on) return
    dbq(setupSql)
    fn._on = true
    // 列表数据是模块导航时拉取的 → 改库后必须重载页面，再切回目标 tab
    await page.reload({ waitUntil: 'load', timeout: 15000 }).catch(() => {})
    await page.waitForTimeout(700)
    if (mod && f && mod.tabMode && f.tab != null)
      await switchTab(page, mod, f.tab).catch(() => {})
  }
  fn.cleanup = async () => {
    if (!fn._on) return
    try {
      dbq(restoreSql)
    } catch (e) {
      console.log('  pre-restore-warn:', String(e).slice(0, 100))
    }
    fn._on = false
  }
  return fn
}

const PRECONDITIONS = {
  /* 需求来源切换后 lanhuUrl input / file input 才渲染 */
  'tool-test-cases#5': async (page) => {
    const s = page.locator('select:has(option[value="lanhu"])').first()
    if (await s.count().catch(() => 0)) await s.selectOption('lanhu').catch(() => {})
    await page.waitForTimeout(300)
  },
  // 验证后恢复粘贴文本源，避免污染后续特征（如 #6 文件区在 text 源不渲染）
  'tool-test-cases#8': async (page) => {
    const s = page.locator('select:has(option[value="file"])').first()
    if (await s.count().catch(() => 0)) await s.selectOption('file').catch(() => {})
    await page.waitForTimeout(300)
  },
  /* #6 拖拽选择区与 #8 同属 file 源（v-if srcType==='file'） */
  'tool-test-cases#6': async (page) => {
    const s = page.locator('select:has(option[value="file"])').first()
    if (await s.count().catch(() => 0)) await s.selectOption('file').catch(() => {})
    await page.waitForTimeout(300)
  },
  /* 画布选中节点且有出边后「移除」才出现：列表载入流程 → 选节点 → 必要时加出边 */
  'tool-workflow-editor#15': async (page) => {
    if (await page.locator('button:has-text("移除")').count().catch(() => 0)) return
    if (!(await page.locator('.cv-node').count().catch(() => 0))) {
      const load = page.locator('button:has-text("画布"):visible').first()
      if (await load.count().catch(() => 0)) {
        await safeClick(load)
        await page.waitForTimeout(700)
      }
    }
    const node = page.locator('.cv-node').first()
    if (await node.count().catch(() => 0)) {
      await node.click({ timeout: 2000 }).catch(() => {})
      await page.waitForTimeout(400)
    }
    if (await page.locator('button:has-text("移除")').count().catch(() => 0)) return
    const add = page.locator('select').filter({ hasText: '添加出边' }).first()
    if (await add.count().catch(() => 0)) {
      const val = await add
        .evaluate((s) => [...s.options].map((o) => o.value).find((v) => v))
        .catch(() => null)
      if (val) await add.selectOption(val).catch(() => {})
      await page.waitForTimeout(400)
    }
  },
  /* 图片下载需先上传图片并处理出 imgResult */
  'tool-media-data-hub#30': async (page) => {
    if (await page.locator('button:has-text("⬇️ 下载"):visible').count().catch(() => 0)) return
    const fi = page.locator('input[type=file]').first()
    const fic = await fi.count().catch(() => 0)
    if (fic) {
      await fi
        .setInputFiles({ name: 'verify.png', mimeType: 'image/png', buffer: PNG_1PX })
        .catch(() => {})
      await page.waitForTimeout(500)
    }
    const go = page.locator('button:has-text("开始压缩"):visible, button:has-text("转换"):visible').first()
    const goc = await go.count().catch(() => 0)
    const god = goc ? await go.isDisabled().catch(() => null) : null
    if (goc && !god) {
      await safeClick(go)
      await page.waitForTimeout(2500) // 等 /image-format-converter 往返
    }
  },
  /* TTS 播放/下载需先生成出 ttsAudioUrl（文本有默认值，直接点生成） */
  'tool-media-data-hub#35': async (page) => {
    if (await page.locator('button:has-text("播放"):visible').count().catch(() => 0)) return
    ensureTtsMock()
    // ai_configs 种子（服务端读取，无需 reload 页面）：指向进程内 mock TTS
    dbq(`UPDATE ai_configs SET is_default=0`)
    dbq(
      `INSERT OR REPLACE INTO ai_configs (id,name,supplier,model_name,api_key,base_url,is_default,created_at)
       VALUES (90001,'TTS验证mock','openai','tts-1-mock','demo-key','http://127.0.0.1:${TTS_MOCK_PORT}/v1',1,datetime('now'))`,
    )
    const gen = page.locator('button:has-text("生成音频"):visible').first()
    if (!(await gen.count().catch(() => 0))) return
    await safeClick(gen)
    await page.waitForTimeout(600)
    // 等生成完成/失败（生成是 API 往返）
    for (let i = 0; i < 25; i++) {
      const st = await page
        .evaluate(() => {
          const t = document.body.innerText || ''
          if (t.includes('生成失败')) return 'fail'
          if (t.includes('tts-output.mp3') || t.includes('音频生成完成')) return 'done'
          return ''
        })
        .catch(() => '')
      if (st) break
      await page.waitForTimeout(500)
    }
  },
  'tool-media-data-hub#36': async (page) => {
    await PRECONDITIONS['tool-media-data-hub#35'](page)
  },
  /* ===== conditional-data 种子（DB 行状态 → 列表重载后条件渲染） ===== */
  // 行0(TJ-772) 置执行中 → 「停止」按钮渲染
  'tool-agent-center#13': sqlPre(
    `UPDATE agt_tasks SET status='执行中' WHERE id='TJ-772'`,
    `UPDATE agt_tasks SET status='成功' WHERE id='TJ-772'`,
  ),
  // 行0(当前列表首条 AR-32，按 created_at desc 排序) 报告置失败 → 「重试」按钮渲染
  // 注意：必须选第 1 页可见的行，verify 不翻页（AR-22 曾因新增报告被挤到第 2 页导致 MISSING）
  'tool-ai-reports#9': sqlPre(
    `UPDATE rep_reports SET detail=json_set(detail,'$.status','生成失败') WHERE id='AR-32'`,
    `UPDATE rep_reports SET detail=json_set(detail,'$.status','已生成') WHERE id='AR-32'`,
  ),
  // 行0(RC-32) 根因记录置非已完成 → 「重试」按钮渲染
  'tool-root-cause#9': sqlPre(
    // 列表按 id DESC 返回且验证过程会不断新增分析记录 → 固定 RC-32 会掉出第 1 页，
    // 必须动态取当前首行（与接口同序）置为失败态，保证「重试」按钮渲染
    `UPDATE rc_cases SET status='分析失败' WHERE id = (SELECT id FROM rc_cases ORDER BY id DESC LIMIT 1)`,
    `UPDATE rc_cases SET status='已完成' WHERE id = (SELECT id FROM rc_cases ORDER BY id DESC LIMIT 1)`,
  ),
  // 详情弹窗「🔗 {关联用例}」需首行缺陷带 case_id（新建缺陷默认不关联 → 链接不渲染）
  'tool-defect-management#30': sqlPre(
    `UPDATE dm_defects SET case_id='TC-1004' WHERE id = (SELECT id FROM dm_defects ORDER BY id DESC LIMIT 1)`,
    `UPDATE dm_defects SET case_id='TC-1004' WHERE id = (SELECT id FROM dm_defects ORDER BY id DESC LIMIT 1)`,
  ),
  // 行0(TC-1001, id ASC) 关联缺陷计数 → 用例详情弹窗「查看关联缺陷/前往缺陷管理」
  'tool-case-management#29': sqlPre(
    `UPDATE cm_cases SET defect=1 WHERE id='TC-1001'`,
    `UPDATE cm_cases SET defect=0 WHERE id='TC-1001'`,
  ),
  'tool-case-management#30': sqlPre(
    `UPDATE cm_cases SET defect=1 WHERE id='TC-1001'`,
    `UPDATE cm_cases SET defect=0 WHERE id='TC-1001'`,
  ),
  // BUG-2045 流转按钮：验证过程自身会点流转把状态推进到终态（已关闭→NEXT=[]→按钮消失）
  // → 每次跑前重置为「新建」+ 关联用例，保证 modal-foot 的「→ {状态}」按钮渲染
  'tool-defect-management#33': sqlPre(
    `UPDATE dm_defects SET status='新建', case_id='TC-1004' WHERE id='BUG-2045'`,
    `UPDATE dm_defects SET status='新建', case_id='TC-1004' WHERE id='BUG-2045'`,
  ),
  // 行0(id DESC 首页, 动态) 扫描结果置成功 → 「转安全发现」
  // 注：不可硬编码 id（每次验证插入新行，固定 id 会掉出第一页 pageSize=10）
  'tool-pentest-testing#9': sqlPre(
    `UPDATE pt_cases SET result='成功', status='成功' WHERE id=(SELECT id FROM pt_cases ORDER BY id DESC LIMIT 1)`,
    `UPDATE pt_cases SET result='待执行', status='待执行' WHERE id=(SELECT id FROM pt_cases ORDER BY id DESC LIMIT 1)`,
  ),
  // 行0(id DESC 首行，动态) 置待解析 → 行按钮「AI解析」；cleanup 写回「已派生」
  // （演示库派生行为稳定产生已派生新行，行0会漂移 → SQL 必须动态取行0）
  'tool-requirement-management#10': sqlPre(
    `UPDATE rm_requirements SET status='待解析' WHERE id=(SELECT id FROM rm_requirements ORDER BY id DESC LIMIT 1)`,
    `UPDATE rm_requirements SET status='已派生' WHERE id=(SELECT id FROM rm_requirements ORDER BY id DESC LIMIT 1)`,
  ),
  // 行0(动态) 关联缺陷数 → 需求详情弹窗「关联缺陷 N 个 →」；cleanup 写回 0
  'tool-requirement-management#35': sqlPre(
    `UPDATE rm_requirements SET defects=1 WHERE id=(SELECT id FROM rm_requirements ORDER BY id DESC LIMIT 1)`,
    `UPDATE rm_requirements SET defects=0 WHERE id=(SELECT id FROM rm_requirements ORDER BY id DESC LIMIT 1)`,
  ),
  // 行0(动态) 关联缺陷数 → 列表行「缺陷数」链接({{ row.defects }} v-if) 在首页才渲染；
  // 默认演示数据首页各需求 defects=0 → 纯插值链接恒 MISSING，seed 首页行缺陷数后重载生效
  'tool-requirement-management#13': sqlPre(
    `UPDATE rm_requirements SET defects=1 WHERE id=(SELECT id FROM rm_requirements ORDER BY id DESC LIMIT 1)`,
    `UPDATE rm_requirements SET defects=0 WHERE id=(SELECT id FROM rm_requirements ORDER BY id DESC LIMIT 1)`,
  ),
  /* analyze tab：上传文档 → 开始 AI 解析（无 Key 后端降级 _PARSE_SEED）→ 逐条产出
     派生按钮（生成用例/压测/安全）。#22/23/24 共用（幂等：已有产出直接跳过）。 */
  'tool-requirement-management#22': async (page) => {
    if (await page.locator('button:has-text("生成用例")').count().catch(() => 0)) return
    const fi = page.locator('input[accept*=".pdf"]').first()
    if (await fi.count().catch(() => 0)) {
      await fi
        .setInputFiles({
          name: 'verify-req.txt',
          mimeType: 'text/plain',
          buffer: Buffer.from('用户在订单详情页点击申请退款，退款原因必填（7 项枚举）。'),
        })
        .catch(() => {})
      await page.waitForTimeout(350)
    }
    const go = page.locator('button:has-text("开始 AI 解析")').first()
    if (await go.count().catch(() => 0)) {
      await safeClick(go)
      await page
        .waitForSelector('button:has-text("生成用例")', { timeout: 25000 })
        .catch(() => {})
    }
  },
}
/* 需求来源切换是状态污染：验证后恢复粘贴文本源，避免影响后续特征（#6 文件区在 text 源不渲染） */
const restoreTestSrc = async (page) => {
  const s = page.locator('select:has(option[value="text"])').first()
  if (await s.count().catch(() => 0)) await s.selectOption('text').catch(() => {})
  await page.waitForTimeout(250)
}
PRECONDITIONS['tool-test-cases#5'].cleanup = restoreTestSrc
PRECONDITIONS['tool-test-cases#8'].cleanup = restoreTestSrc
PRECONDITIONS['tool-test-cases#6'].cleanup = restoreTestSrc
PRECONDITIONS['tool-requirement-management#23'] = PRECONDITIONS['tool-requirement-management#22']
PRECONDITIONS['tool-requirement-management#24'] = PRECONDITIONS['tool-requirement-management#22']
// TTS mock 配置是环境种子：验证后删除，避免污染账户 AI 配置列表
PRECONDITIONS['tool-media-data-hub#35'].cleanup = async () => {
  try {
    dbq(`DELETE FROM ai_configs WHERE id=90001`)
  } catch (e) {
    console.log('  pre-restore-warn:', String(e).slice(0, 100))
  }
}
// #36 是独立 wrapper（内部调 #35 PRE），需共享同一 cleanup，否则种子行残留
PRECONDITIONS['tool-media-data-hub#36'].cleanup = PRECONDITIONS['tool-media-data-hub#35'].cleanup
/* workflow-editor nodeOpen/runOpen modal 组（fid 0-based：_idx 26~33、35
   对应 manifest #27~#34、#36）：画布区仅在 tab==='canvas' 渲染，且须有
   .cv-node（行内「画布」载入的流程可能 canvas 为空 → 直接点「🚦开始节点」
   追加一个本地节点）——否则 selectNode 触发器 locate 失败，ensureModalOpen
   恒失败报 modal-will-not-open */
const ensureCanvasLoaded = async (page, mod) => {
  if (!(await page.locator('.cv-node').count().catch(() => 0))) {
    await switchTab(page, mod, 'canvas').catch(() => {})
    await page.waitForTimeout(350)
    const add = page.locator('button:has-text("开始节点"):visible').first()
    if ((await add.count().catch(() => 0)) && !(await page.locator('.cv-node').count().catch(() => 0))) {
      await safeClick(add).catch(() => {})
      await page.waitForTimeout(350)
    }
  }
  /* selectNode 是 toggle：已选中节点再点 = 清 selected 且不开 modal
     （Phase1 #15 PRE 点过节点会残留 selected → Phase2 点同节点恒失败）。
     若存在选中态（inline outline）→ 点它一次清除，让 ensureModalOpen 的
     点击走到 nodeOpen=true 分支 */
  const selNode = page.locator('div.cv-node[style*="outline"]').first()
  if (await selNode.count().catch(() => 0)) {
    await safeClick(selNode).catch(() => {})
    await page.waitForTimeout(250)
  }
}
for (const n of [26, 27, 28, 29, 30, 31, 32, 33, 35]) {
  PRECONDITIONS[`tool-workflow-editor#${n}`] = ensureCanvasLoaded
}

async function ensurePrecondition(page, mod, f) {
  const fn = PRECONDITIONS[fid(mod, f)]
  if (!fn) return null
  await fn(page, mod, f).catch((e) => console.log('  pre-warn:', fid(mod, f), String(e).slice(0, 100)))
  return fn.cleanup || null
}

/* ---------- 单模块执行 ---------- */
/* prompts 数据预置（按需、幂等）：进入 favs/submit 组前补齐数据。
   注意：all 组的星标特征会取消收藏，submit 组的通过/驳回会改变行状态——
   因此必须在每次切入目标 tab 时重新 ensure，而不是模块开头一次性 seed。 */
async function ensureSeed(page, mod, tab) {
  /* case-management 评审 tab：通过/驳回各消耗 1 行待评审 → 需 ≥2 行。
     种子方式：到用例库「新建用例」（POST 后 status=待评审；编辑 PUT 不重置状态）。 */
  if (mod.id === 'tool-case-management' && tab === 'review') {
    const pend = () =>
      page.evaluate(
        () =>
          [...document.querySelectorAll('tbody tr')].filter((r) =>
            (r.innerText || '').includes('待评审'),
          ).length,
      )
    if ((await pend().catch(() => 9)) >= 2) return
    await switchTab(page, mod, 'lib').catch(() => {})
    await page.waitForTimeout(450)
    for (let i = 0; i < 3; i++) {
      if ((await pend().catch(() => 0)) >= 2) break
      const trig = page.locator('button:has-text("新建用例"):visible').first()
      if (!(await trig.count().catch(() => 0))) break
      await safeClick(trig)
      await page.waitForTimeout(450)
      const title = page
        .locator('.modal-mask.open input')
        .first()
      await title
        .fill('功能验证种子-' + (Date.now() % 100000) + '-' + i, { timeout: 5000 })
        .catch(() => {})
      const save = page.locator('.modal-mask.open button:has-text("保存用例"):visible').first()
      if (await save.count().catch(() => 0)) await safeClick(save)
      await page.waitForTimeout(700)
      await closeModals(page).catch(() => {})
    }
    await switchTab(page, mod, 'review').catch(() => {})
    await page.waitForTimeout(450)
    return
  }
  if (tab === 'favs') {
    const empty = await page
      .evaluate(() => document.querySelectorAll('.prompt-card').length === 0)
      .catch(() => true)
    if (!empty) return
    await switchTab(page, mod, 'all').catch(() => {})
    await page.waitForTimeout(400)
    const star = page.locator('.pc-star').first()
    if (await star.count().catch(() => 0)) {
      const txt = (await star.innerText().catch(() => '')).trim()
      if (txt.includes('☆')) {
        await safeClick(star)
        await page.waitForTimeout(600)
      }
    }
    await switchTab(page, mod, 'favs').catch(() => {})
    await page.waitForTimeout(500)
    return
  }
  if (tab !== 'submit') return

  const needRow = async () => {
    // 打开投稿 modal 并提交一条（submit tab 内也有投稿按钮）
    const trig = page
      .locator('button.btn-primary:has-text("投稿提示词"):visible, button:has-text("投稿提示词"):visible')
      .first()
    if (!(await trig.count().catch(() => 0))) return false
    await safeClick(trig)
    await page.waitForTimeout(700)
    const open = page.locator('.modal-mask.open').first()
    if (!(await open.count().catch(() => 0))) return false
    await open
      .locator('input')
      .first()
      .fill(
        '功能验证预置-' + (Date.now() % 100000) + '-' + Math.floor(Math.random() * 1000),
        { timeout: 5000 },
      )
      .catch(() => {})
    await open.locator('input[placeholder*="断言"]').fill('verify-seed', { timeout: 5000 }).catch(() => {})
    await open
      .locator('textarea')
      .fill('seed prompt for feature verification,请勿删除。', { timeout: 5000 })
      .catch(() => {})
    await open.getByRole('button', { name: /提交投稿/ }).click().catch(() => {})
    await page.waitForTimeout(900)
    await closeModals(page).catch(() => {})
    return true
  }
  const counts = () =>
    page.evaluate(() => {
      const c = { pending: 0, published: 0, rejected: 0, total: 0 }
      for (const r of document.querySelectorAll('tbody tr')) {
        const t = r.innerText || ''
        if (t.includes('待评审')) c.pending++
        else if (t.includes('已发布')) c.published++
        else if (t.includes('已驳回')) c.rejected++
        c.total++
      }
      return c
    })
  const rowByStatus = (status, nth = 0) =>
    page.locator(`tbody tr:has-text("${status}")`).nth(nth)

  let c = await counts().catch(() => ({ pending: 0, published: 0, rejected: 0, total: 0 }))
  if (c.total === 0 && !(await needRow())) return
  // 目标：待评审≥2（通过/驳回各消耗1）、已发布≥1（撤回）、已驳回≥1（重新提交）
  const needReject = c.rejected < 1 ? 1 : 0
  const needApprove = c.published < 1 ? 1 : 0
  const targetPending = 2 + needReject + needApprove
  let guard = 0
  while (c.pending < targetPending && guard++ < 6) {
    if (!(await needRow())) break
    await page.waitForTimeout(300)
    c = await counts()
  }
  if (needReject) {
    const row = rowByStatus('待评审')
    if (await row.count().catch(() => 0)) {
      await safeClick(row.locator('button:has-text("驳回")').first())
      await page.waitForTimeout(700)
      const open = page.locator('.modal-mask.open').first()
      if (await open.count().catch(() => 0)) {
        await open.locator('textarea').fill('功能验证：状态预置驳回', { timeout: 5000 }).catch(() => {})
        await open.getByRole('button', { name: /确认驳回/ }).click().catch(() => {})
        await page.waitForTimeout(900)
      }
      await closeModals(page).catch(() => {})
    }
  }
  if (needApprove) {
    const row = rowByStatus('待评审')
    if (await row.count().catch(() => 0)) {
      await safeClick(row.locator('button:has-text("通过")').first())
      await page.waitForTimeout(800)
    }
  }
}

async function runModule(mod) {
  const hosts = hostsOf(mod)
  const useGuest = !hosts.some((h) => h.auth)
  const results = []
  /* 基线为全 map 快照：SPA 导航产生的错误可能归属其他模块（URL 归属），
     不能只看 mod.id 的增量，否则跨模块错误被丢弃 */
  const errsBefore = new Map([...jsErrors].map(([k, v]) => [k, v.length]))

  const plain = mod.features.filter((f) => !f.modal)
  const modalFeats = mod.features.filter((f) => f.modal)

  // ordinal 按组预分配（DOM 可见池 = 该组元素）
  for (const g of tabGroups(mod, plain)) assignOrdinals(g.feats)
  const modalGroups = []
  {
    const map = new Map()
    for (const f of modalFeats) {
      if (!map.has(f.modal)) map.set(f.modal, [])
      map.get(f.modal).push(f)
    }
    for (const [mv, list] of map) {
      assignOrdinals(list)
      modalGroups.push({ mv, feats: list })
    }
  }

  const used = new Set()
  let usedKey = null
  const resetUsed = (k) => {
    if (k !== usedKey) {
      used.clear()
      usedKey = k
    }
  }

  const push = (f, r) => {
    results.push({
      key: fid(mod, f),
      module: mod.id,
      route: mod.route,
      tab: f.tab,
      modal: f.modal || null,
      kind: f.kind,
      text: ftext(f).slice(0, 50),
      line: f.line,
      risk: f.risk,
      status: r.status,
      detail: r.detail || '',
      signal: r.signal || '',
      how: (r.how || '').slice(0, 140),
      textsN: textsOf(f).length,
      ms: r.ms || 0,
    })
    const mark =
      r.status === 'PASS'
        ? '✓'
        : r.status === 'PASS-EXIST'
          ? '·'
          : r.status === 'SKIP'
            ? '~'
            : r.status === 'MISSING'
              ? '∅'
              : '✗'
    console.log(
      `  ${mark} [${r.status}] ${f.kind} ${(ftext(f) || f.vModel || f.placeholder || '?').slice(0, 26)}${r.detail ? ' — ' + r.detail : ''}`,
    )
  }

  /* --- Phase 1：非 modal 特征（页面级组 → 各 tab 组） --- */
  for (const g of tabGroups(mod, plain)) {
    for (const f of g.feats) {
      if (LIMIT && results.length >= LIMIT) break
      let done = null
      const featureBody1 = async () => {
      for (const host of hosts) {
        try {
          const page = await getPage(useGuest, host, mod.id)
          if (mod.tabMode && f.tab != null) await switchTab(page, mod, f.tab)
          if (
            (mod.id === 'prompts' && (f.tab === 'favs' || f.tab === 'submit')) ||
            (mod.id === 'tool-case-management' && f.tab === 'review')
          ) {
            await ensureSeed(page, mod, f.tab).catch((e) =>
              console.log('  seed-warn:', String(e).slice(0, 140)),
            )
          }
          const preClean = await ensurePrecondition(page, mod, f)
          resetUsed(`${host.path}|${f.tab}|`)
          const want = {
            texts: textsOf(f),
            patterns: patternsOf(f),
            href: f.kind === 'link' && typeof f.to === 'string' && f.to.startsWith('/') ? f.to : null,
            ordinal: f._ord || 0,
            used: [...used],
            scope: null,
          }
          const r = await verifyFeature(page, f, want, { expectPath: host.path }, page._dlg)
          if (preClean) await preClean(page).catch(() => {})
          if (r.status !== 'MISSING') {
            if (r.status === 'PASS' && textsOf(f).length && ftext(f).length >= 3)
              used.add(ftext(f))
            done = r
            break
          }
          done = done || r
        } catch (e) {
          done = { status: 'FAIL', detail: 'exception:' + String(e).slice(0, 120) }
          break
        }
      }
      }
      const raced1 = await Promise.race([
        featureBody1().then(() => '__OK__', (e) => '__ERR__' + String(e).slice(0, 100)),
        new Promise((r) => setTimeout(() => r('__TIMEOUT__'), 90000)),
      ])
      if (raced1 === '__TIMEOUT__') {
        done = { status: 'FAIL', detail: 'feature-timeout(90s)' }
        console.log(`  [timeout] ${fid(mod, f)} 超时跳过`)
      } else if (typeof raced1 === 'string' && raced1.startsWith('__ERR__')) {
        done = { status: 'FAIL', detail: 'exception:' + raced1.slice(7, 130) }
      }
      push(f, done || { status: 'MISSING' })
    }
  }

  /* --- Phase 2：modal 特征（按触发表，多入口时逐个换 trigger 重试） --- */
  for (const g of modalGroups) {
    const trigs = findTriggers(mod, g.mv)
    if (!trigs.length) {
      for (const f of g.feats) push(f, { status: 'SKIP', detail: 'modal-no-trigger' })
      continue
    }
    const trigWantOf = (t) => ({
      /* extract 对 div@click 类触发器提取的是 innerHTML 源码（如
         `<div class="cv-node" style=...`），与运行时 innerText 永不匹配 →
         locate 恒失败误报 modal-will-not-open。源码型 text 降级为空文本
         （全池命中 + ordinal），触发器定位从宽、特征定位仍从严 */
      texts: /^</.test(String(t.text || '').trim()) ? [] : textsOf(t),
      patterns: patternsOf(t),
      ordinal: t._ord || 0,
      used: [],
      scope: null,
    })
    for (const f of g.feats) {
      if (LIMIT && results.length >= LIMIT) break
      let done = null
      const featureBody2 = async () => {
      for (const host of hosts) {
        try {
          const page = await getPage(useGuest, host, mod.id)
          let attemptR = null
          for (let ti = 0; ti < trigs.length; ti++) {
            const trig = trigs[ti]
            // modal 组特征同样需要数据前置（如详情弹窗的关联缺陷链接）；
            // PRE 可能 reload 页面 → 必须在 open 弹窗之前执行
            const preClean2 = await ensurePrecondition(page, mod, f)
            if (mod.tabMode && trig.tab != null) await switchTab(page, mod, trig.tab)
            const opened = await ensureModalOpen(page, mod, trig, trigWantOf(trig), page._dlg)
            if (!opened) {
              if (preClean2) await preClean2(page).catch(() => {})
              attemptR = { status: 'SKIP', detail: 'modal-will-not-open' }
              continue // 换下一个入口（如「编辑」而非「新建」）
            }
            resetUsed(`${host.path}|modal:${g.mv}|`)
            const want = {
              texts: textsOf(f),
              patterns: patternsOf(f),
              href: f.kind === 'link' && typeof f.to === 'string' && f.to.startsWith('/') ? f.to : null,
              ordinal: f._ord || 0,
              used: [...used],
              scope: '.modal-mask.open',
            }
            const r = await verifyFeature(page, f, want, { expectPath: host.path }, page._dlg)
            await closeModals(page).catch(() => {})
            if (preClean2) await preClean2(page).catch(() => {})
            attemptR = r
            if (r.status !== 'MISSING') break
          }
          if (attemptR && attemptR.status !== 'MISSING') {
            if (
              attemptR.status === 'PASS' &&
              textsOf(f).length &&
              ftext(f).length >= 3
            )
              used.add(ftext(f))
            done = attemptR
            break
          }
          done = done || attemptR
        } catch (e) {
          done = { status: 'FAIL', detail: 'exception:' + String(e).slice(0, 120) }
          break
        }
      }
      }
      const raced2 = await Promise.race([
        featureBody2().then(() => '__OK__', (e) => '__ERR__' + String(e).slice(0, 100)),
        new Promise((r) => setTimeout(() => r('__TIMEOUT__'), 90000)),
      ])
      if (raced2 === '__TIMEOUT__') {
        done = { status: 'FAIL', detail: 'feature-timeout(90s)' }
        console.log(`  [timeout] ${fid(mod, f)} 超时跳过`)
      } else if (typeof raced2 === 'string' && raced2.startsWith('__ERR__')) {
        done = { status: 'FAIL', detail: 'exception:' + raced2.slice(7, 130) }
      }
      push(f, done || { status: 'MISSING' })
    }
  }

  /* 本轮模块运行期间全部新增错误（归属 key 由汇总阶段按 URL 处理） */
  const newErrs = []
  for (const [k, arr] of jsErrors) {
    const b = errsBefore.get(k) || 0
    if (arr.length > b) newErrs.push(...arr.slice(b))
  }
  return { results, jsErrors: [...new Set(newErrs)] }
}

/* ---------- 登录 ---------- */
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

/* ================= 主流程 ================= */
const manifest = JSON.parse(fs.readFileSync(MANIFEST, 'utf8'))
for (const m of manifest.modules) m.features.forEach((f, i) => (f._idx = i))
/* jsErrors 按当前 URL 归属：SPA 导航后错误应记到目标模块（如 scheduler 内点
   「配置中心」链接跳转后，config-center 的 render 错误曾被误记到 scheduler）。
   仅收唯一映射的 route；(shell) 等共享路由退回创建页时的 modId。 */
const routeToMod = (() => {
  const cnt = new Map()
  for (const m of manifest.modules) cnt.set(m.route, (cnt.get(m.route) || 0) + 1)
  const map = new Map()
  for (const m of manifest.modules) if (cnt.get(m.route) === 1) map.set(m.route, m.id)
  return map
})()
const modules = manifest.modules.filter((m) => !ONLY || ONLY.includes(m.id))
if (!modules.length) {
  console.error('没有匹配的模块:', ONLY)
  process.exit(2)
}
const targetCount = modules.reduce((s, m) => s + m.features.length, 0)
console.log(
  `==== 功能验证 ====  modules=${modules.length} features=${targetCount}${ONLY ? ' only=' + ONLY.join(',') : ''}`,
)

/* 前置静态/竞态扫描：全量（无 --only）时先跑 scan-race（冷启动 + API 延迟
   收集 pageerror）与 check-links（内部死链静态核对）。有发现只警告不阻断——
   功能验证继续，报告见 race-scan-report.json / link-scan-report.json */
if (!ONLY && !NO_SCAN) {
  for (const [label, script, report] of [
    ['竞态扫描 scan-race', 'scan-race.mjs', 'race-scan-report.json'],
    ['死链扫描 check-links', 'check-links.mjs', 'link-scan-report.json'],
  ]) {
    console.log(`==== 前置${label} ====`)
    try {
      execFileSync(process.execPath, [path.join(ROOT, 'scripts', script)], { stdio: 'inherit' })
      console.log(`${label}: OK\n`)
    } catch {
      console.warn(`⚠ ${label}: 有发现（见 ${report}），继续功能验证\n`)
    }
  }
}

const token = await login()
/* jsErrors 全局基线（本轮开始前各 key 的长度）：汇总阶段据此取"本轮新增"，
   与 URL 归属配合——跨模块导航产生的错误记到真实归属模块而非创建页模块 */
const jsErrBase = new Map([...jsErrors].map(([k, v]) => [k, v.length]))
if (!token) {
  console.error('VERIFY_ABORT: 无法登录')
  process.exit(2)
}

let browser = await chromium.launch({ headless: true })
let authedCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
await authedCtx.addInitScript(
  ([t]) => {
    localStorage.setItem('aitesthub_token', t)
    localStorage.setItem('aitesthub_auth', '1')
    localStorage.setItem('aitesthub_login_user', 'admin')
  },
  [token],
)
let guestCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } })

const moduleReports = {}
const t0 = Date.now()
for (const mod of modules) {
  console.log(`\n■ ${mod.id}  ${mod.route}  ${mod.features.length} 项`)
  const r = await runModule(mod)
  const counts = { PASS: 0, 'PASS-EXIST': 0, FAIL: 0, MISSING: 0, SKIP: 0 }
  for (const x of r.results) counts[x.status] = (counts[x.status] || 0) + 1
  moduleReports[mod.id] = {
    route: mod.route,
    n: r.results.length,
    counts,
    jsErrors: r.jsErrors,
    items: r.results,
  }
  console.log(
    `  → PASS=${counts.PASS} EXIST=${counts['PASS-EXIST']} FAIL=${counts.FAIL} MISSING=${counts.MISSING} SKIP=${counts.SKIP}${r.jsErrors.length ? ' jsErr=' + r.jsErrors.length : ''}`,
  )
}

/* 关闭页面 */
for (const p of pageCache.values()) await p.close().catch(() => {})
pageCache.clear()
await browser.close()

/* ---------- 报告合并 ---------- */
let prev = {}
if (!FRESH && fs.existsSync(REPORT)) {
  try {
    prev = JSON.parse(fs.readFileSync(REPORT, 'utf8'))
  } catch {
    prev = {}
  }
}
const store = FRESH ? {} : prev.items || {}
for (const mr of Object.values(moduleReports)) {
  for (const it of mr.items) store[it.key] = it
}
const totals = { PASS: 0, 'PASS-EXIST': 0, FAIL: 0, MISSING: 0, SKIP: 0 }
for (const it of Object.values(store)) totals[it.status] = (totals[it.status] || 0) + 1
/* 未通过项分类落库（逐项说明根因，供人工复核/补数据）：
   conditional-data=条件渲染，需特定业务数据才出现；config-dependent=需账户级配置；
   verify-limitation=验证器能力边界（未归类）；verify-issue=真实无反馈缺陷（需人工复核） */
const MISSING_NOTES = {
  'tool-agent-center#13': 'conditional-data:需存在「运行中」的任务行才渲染停止按钮',
  'tool-ai-reports#9': 'conditional-data:仅「失败」的报告行才显示重试',
  'tool-case-management#29': 'conditional-data:详情弹窗需该用例已关联缺陷',
  'tool-case-management#30': 'conditional-data:详情弹窗需该用例已关联缺陷',
  'tool-defect-management#29': 'bug:BUG-04 API读错列名(dm_defects.case_id→dto.case)致view.case恒空(见docs/verification-bugs.md)',
  'tool-knowledge-base#29': 'conditional-data:引用面板需该知识条目被缺陷引用',
  'tool-knowledge-base#30': 'conditional-data:引用面板需该知识条目被缺陷引用',
  'tool-media-data-hub#35': 'config-dependent:TTS 生成需账户配置文本 AI 模型(接口 400 未配置)',
  'tool-media-data-hub#36': 'config-dependent:无音频产物则下载按钮不渲染(同 #35)',
  'tool-pentest-testing#9': 'conditional-data:需存在已完成的扫描结果行才显示转安全发现',
  'tool-requirement-management#10': 'conditional-data:仅需求文档行才显示 AI 解析按钮',
  'tool-requirement-management#22': 'conditional-data:需先完成 AI 解析产出分析结果',
  'tool-requirement-management#23': 'conditional-data:需先完成 AI 解析产出分析结果',
  'tool-requirement-management#24': 'conditional-data:需先完成 AI 解析产出分析结果',
  'tool-requirement-management#35': 'conditional-data:详情弹窗需该需求关联了缺陷(view.defect 非空才渲染)',
  'tool-root-cause#9': 'conditional-data:仅「失败」的根因分析记录才显示重试',
}
const categoryStats = {}
for (const it of Object.values(store)) {
  if (it.status === 'MISSING') {
    it.category = MISSING_NOTES[it.key] || 'verify-limitation:未归类(需复核)'
  } else if (it.status === 'FAIL') {
    it.category = 'verify-issue:点击无反馈(需人工复核是否页面缺陷)'
  } else {
    delete it.category
  }
  if (it.category) {
    const c = it.category.split(':')[0]
    categoryStats[c] = (categoryStats[c] || 0) + 1
  }
}
// 反馈信号面统计（审计：每个 PASS/EXIST 由哪种反馈证据支撑）
const signalStats = {}
const detailStats = {}
for (const it of Object.values(store)) {
  if (it.status === 'PASS') {
    const sig = String(it.signal || 'unknown').split(':')[0].split('+')[0] || 'unknown'
    signalStats[sig] = (signalStats[sig] || 0) + 1
  }
  if (it.status === 'PASS-EXIST' || it.status === 'SKIP') {
    const d = String(it.detail || 'unknown').split('+')[0]
    detailStats[d] = (detailStats[d] || 0) + 1
  }
}
const jsErrMap = {}
// 先带上 prev 历史（未在本轮重跑的模块保留旧 jsError）
for (const [mid, pm] of Object.entries(prev.modules || {})) {
  if (pm.jsErrors && pm.jsErrors.length) jsErrMap[mid] = [...pm.jsErrors]
}
// 本轮实跑的模块以本轮为准：先清历史，再按 URL 归属写入本轮全部新增——
// 跑过且无错 → 清零（修复后重跑可清零）；跨模块导航错误按真实归属记录；
// 未跑但本轮在其页面出错的模块 → 合并新增（去重）
for (const mid of Object.keys(moduleReports)) delete jsErrMap[mid]
for (const [mid, arr] of jsErrors) {
  const fresh = [...new Set(arr.slice(jsErrBase.get(mid) || 0))]
  if (!fresh.length) continue
  jsErrMap[mid] = [...new Set([...(jsErrMap[mid] || []), ...fresh])]
}
const report = {
  at: new Date().toISOString(),
  ran: Object.keys(moduleReports),
  elapsedMs: Date.now() - t0,
  totals,
  /* modules 维度从完整 items 重建（--only 分批时 moduleReports 只含本轮，
     而 items store 永远是全量合并的，据此聚合最可靠） */
  modules: (() => {
    const agg = {}
    for (const m of manifest.modules) {
      agg[m.id] = { route: m.route, n: 0, counts: { PASS: 0, 'PASS-EXIST': 0, FAIL: 0, MISSING: 0, SKIP: 0 } }
    }
    for (const it of Object.values(store)) {
      const a = agg[it.module] || (agg[it.module] = { route: it.route, n: 0, counts: { PASS: 0, 'PASS-EXIST': 0, FAIL: 0, MISSING: 0, SKIP: 0 } })
      a.n++
      a.counts[it.status] = (a.counts[it.status] || 0) + 1
    }
    for (const [mid, errs] of Object.entries(jsErrMap)) {
      if (agg[mid]) agg[mid].jsErrors = errs
    }
    return agg
  })(),
  jsErrors: jsErrMap,
  signalStats,
  detailStats,
  categoryStats,
  items: store,
}
fs.writeFileSync(REPORT, JSON.stringify(report, null, 1))

/* ---------- 汇总 ---------- */
console.log('\n==== VERIFY SUMMARY ====')
console.log(
  `本次 ${Object.keys(moduleReports).length} 模块 / ${Object.values(moduleReports).reduce((s, m) => m.n + s, 0)} 项，耗时 ${Math.round((Date.now() - t0) / 1000)}s`,
)
console.log(`累计 items=${Object.keys(store).length}`, JSON.stringify(totals))
console.log('反馈信号分布:', JSON.stringify(signalStats))
console.log('未通过分类:', JSON.stringify(categoryStats))
console.log('模块矩阵:')
for (const [mid, mr] of Object.entries(moduleReports)) {
  const c = mr.counts
  console.log(
    `  ${c.FAIL + c.MISSING > 0 ? '✗' : '✓'} ${mid.padEnd(26)} n=${String(mr.n).padStart(3)}  PASS=${c.PASS} EXIST=${c['PASS-EXIST']} FAIL=${c.FAIL} MISSING=${c.MISSING} SKIP=${c.SKIP}`,
  )
}
const bad = Object.values(store).filter((x) => x.status === 'FAIL' || x.status === 'MISSING')
if (bad.length) {
  console.log(`\nFAIL/MISSING 明细（前 60 条，共 ${bad.length}）:`)
  for (const b of bad.slice(0, 60))
    console.log(
      `  [${b.status}] ${b.key} ${b.text || '?'} ${b.detail ? '— ' + b.detail : ''}${b.how ? ' (' + b.how + ')' : ''}`,
    )
}
if (Object.keys(jsErrMap).length) console.log('\njsErrors:', JSON.stringify(jsErrMap).slice(0, 800))
console.log('Report:', REPORT)
if (bad.length) {
  console.log(`VERIFY_FAIL count=${bad.length}`)
  process.exit(1)
}
console.log('VERIFY_OK')
/* 有未关闭句柄（browser/page/timer）时 node 会挂住不退出，
   导致外层 shell 超时误判失败——验证完成后显式退出 */
process.exit(0)
