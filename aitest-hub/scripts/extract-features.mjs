#!/usr/bin/env node
/**
 * 全模块最小功能点提取器
 * 扫描 frontend/src 的 SFC 模板，提取按钮/链接/输入/选择器/文本域等
 * 可交互元素，按「模块 → tab → 最小功能」分级输出清单。
 *
 * 用法: node scripts/extract-features.mjs
 * 输出: .playwright-mcp/features-manifest.json (+ 控制台分级摘要)
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const VIEWS = path.join(ROOT, 'frontend/src/views')
const LAYOUTS = path.join(ROOT, 'frontend/src/layouts')
const SHELL = path.join(ROOT, 'frontend/src/components/shell')

/* catalog：27 工具的 tab 定义 */
const catSrc = fs.readFileSync(path.join(ROOT, 'frontend/src/data/catalog.ts'), 'utf8')
const ki = catSrc.indexOf('TOOL_CATALOG')
const CATALOG = JSON.parse(catSrc.slice(catSrc.indexOf('[{', ki), catSrc.lastIndexOf(']') + 1))

/* root-texts 字典（T.xxx 静态求值） */
let T_DICT = {}
try {
  const ts = fs.readFileSync(path.join(ROOT, 'frontend/src/data/root-texts.ts'), 'utf8')
  for (const m of ts.matchAll(/"([^"]+)":\s*"((?:\\.|[^"\\])*)"/g)) {
    try { T_DICT[m[1]] = JSON.parse('"' + m[2] + '"') } catch { /* ignore */ }
  }
} catch { /* root-texts 不存在则空字典 */ }

/** 动态文本的静态候选：三元字面量两分支 + T.xxx 替换；无法静态求值返回 [] */
function textAltCandidates(t) {
  const alts = []
  if (!t.includes('{{')) return alts
  /* {{ cond ? 'A' : 'B' }}（单/双引号字面量） */
  const tern = t.match(/\{\{\s*[^?{}]*?\?\s*(["'])((?:\\.|(?!\1).)*)\1\s*:\s*(["'])((?:\\.|(?!\3).)*)\3[^}]*\}\}/)
  if (tern) { alts.push(tern[2], tern[4]); return alts }
  /* {{ T.xxx }} 纯字典拼接：全部可解则组出静态文本 */
  if (/^\s*(?:[^{}]*\{\{\s*T\.\w+\s*\}\})+\s*$/.test(t)) {
    let ok = true
    const s = t.replace(/\{\{\s*T\.(\w+)\s*\}\}/g, (_, k) => {
      if (!(k in T_DICT)) { ok = false; return '' }
      return T_DICT[k]
    })
    if (ok) alts.push(s)
  }
  return alts
}

/* 危险操作词（验证时只做存在性/可见性断言，不真实点击）；「重置」=清筛选无副作用，归 safe */
const DANGER_RE =
  /删除|清空|清除|移除|注销|断开|停止|终止|退出|销毁|\bkill\b|destroy|\bdrop\b|一键清/i
/* 表单提交类（空表单点一次，观察校验/反馈，无严重副作用） */
const SUBMIT_RE = /提交|保存|发送|注册|登录|确定|确认|创建|新增|生成|申请|执行|运行|开始|发起|发布|导入|上传|复制|导出/i
/* AI 类（可能调 LLM，长等待观察反馈） */
const AI_RE = /🤖|AI|智能|一键/i

/* ---------- 模板切分与行号 ---------- */
function templateSpan(src) {
  const s = src.indexOf('<template>')
  if (s < 0) return null
  const e = src.lastIndexOf('</template>')
  return e > s ? [s, e] : null
}
function lineOf(src, idx) {
  return src.slice(0, idx).split('\n').length
}

/* ---------- 单文件提取 ---------- */
function extractFile(absPath, moduleId, route, tabMode) {
  const src = fs.readFileSync(absPath, 'utf8')
  const span = templateSpan(src)
  if (!span) return { id: moduleId, route, features: [] }
  const [ts, te] = span
  const tpl = src.slice(ts, te)
  const baseLine = lineOf(src, ts)

  /* tab 上下文：记录条件行缩进，缩进回退时重置 */
  const marks = [] // {tab, indent, idx}
  const condRe = /v-(?:else-)?if\s*=\s*"(?:activeTab|tab)\s*===?\s*'([^']+)'/g
  let m
  while ((m = condRe.exec(tpl))) {
    const lineStart = tpl.lastIndexOf('\n', m.index) + 1
    const indent = tpl.slice(lineStart).search(/\S/) // 行首缩进（非属性位置）
    marks.push({ tab: m[1], indent, idx: m.index })
  }
  function tabAt(pos) {
    let cur = null
    for (const k of marks) {
      if (k.idx > pos) break
      cur = k
    }
    if (!cur) return null
    const seg = tpl.slice(cur.idx + 1, pos)
    const lines = seg.split('\n')
    for (const ln of lines) {
      const t = ln.trim()
      if (!t.startsWith('<')) continue
      const ind = ln.length - ln.trimStart().length
      if (ind <= cur.indent && !/^<(!--|\/)/.test(t) && !t.startsWith('v-else')) {
        if (/^<\//.test(t) || /^<[a-zA-Z]/.test(t)) return null
      }
    }
    return cur.tab
  }

  /* ---------- modal 归属（.modal-mask 的 :class="{ open: VAR }" / v-if="VAR"） ---------- */
  const modalMarks = []
  const modRe = /<div\b[^>]*class="[^"]*modal-mask[^"]*"[^>]*/g
  let mm
  while ((mm = modRe.exec(tpl))) {
    const tag = mm[0]
    const varM = tag.match(/open:\s*(\w+)/) || tag.match(/v-if\s*=\s*"(\w+)"/)
    const lineStart = tpl.lastIndexOf('\n', mm.index) + 1
    const indent = tpl.slice(lineStart).search(/\S/)
    modalMarks.push({ modal: varM ? varM[1] : 'staticModal', indent, idx: mm.index })
  }
  function modalAt(pos) {
    let cur = null
    for (const k of modalMarks) {
      if (k.idx > pos) break
      cur = k
    }
    if (!cur) return null
    const seg = tpl.slice(cur.idx + 1, pos)
    for (const ln of seg.split('\n')) {
      const t = ln.trim()
      if (!t.startsWith('<')) continue
      const ind = ln.length - ln.trimStart().length
      if (ind <= cur.indent && (/^<\//.test(t) || /^<[a-zA-Z]/.test(t)) && !t.startsWith('v-else')) {
        return null
      }
    }
    return cur.modal
  }

  /* ---------- modal 触发器：script 中 VAR.value = true 所在函数名 ---------- */
  const scriptM = src.match(/<script[\s\S]*?>([\s\S]*?)<\/script>/)
  const script = scriptM ? scriptM[1] : ''
  const modalTriggers = {}
  for (const mk of modalMarks) {
    if (mk.modal === 'staticModal') continue
    const trig = new Set()
    const re = new RegExp(`\\b${mk.modal}\\.value\\s*=\\s*true\\b|\\b${mk.modal}\\s*=\\s*true\\b`, 'g')
    let t
    while ((t = re.exec(script))) {
      const before = script.slice(0, t.index)
      const fnRe = /(?:async\s+)?function\s+(\w+)\s*\(|const\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>|const\s+(\w+)\s*=\s*(?:async\s*)?\(\)/g
      let f2, last = null
      while ((f2 = fnRe.exec(before))) last = f2[1] || f2[2] || f2[3]
      if (last) trig.add(last)
    }
    /* 模板内联触发：@click="VAR = true" / @click="VAR.value = true" */
    const inlineRe = new RegExp(`@click="\\s*${mk.modal}(?:\\.value)?\\s*=\\s*true[^"]*"`, 'g')
    let inl
    while ((inl = inlineRe.exec(tpl))) trig.add(inl[0].replace(/^@click="/, '').replace(/"$/, ''))
    modalTriggers[mk.modal] = [...trig]
  }

  /* ---------- 最近容器类（enclosing）：供验证器限定 ordinal 定位范围 ---------- */
  const CONT_RE = /<(\/?)(div|nav|section|ul|ol|form|table|aside|main|header|footer|tbody)(?=[\s/>])((?:[^>"']|"[^"]*"|'[^']*')*)>/g
  function enclosingAt(pos) {
    const stack = []
    CONT_RE.lastIndex = 0
    let m
    while ((m = CONT_RE.exec(tpl))) {
      if (m.index >= pos) break
      if (m[1] === '/') {
        for (let i = stack.length - 1; i >= 0; i--)
          if (stack[i].tag === m[2]) { stack.length = i; break }
      } else {
        if (m[0].endsWith('/>')) continue
        const cm = m[3].match(/class="([^"]*)"/)
        const cls = cm ? cm[1].trim().split(/\s+/).find((c) => /^[A-Za-z][\w-]*$/.test(c)) : null
        stack.push({ tag: m[2], cls })
      }
    }
    for (let i = stack.length - 1; i >= 0; i--) if (stack[i].cls) return stack[i].cls
    return null
  }

  const feats = []
  const seen = new Set()
  const push = (kind, idx, attrs, text, extra = {}) => {
    const key = kind + ':' + idx
    if (seen.has(key)) return
    seen.add(key)
    const click = (attrs.match(/@click\s*=\s*"([^"]+)"/) || [])[1] || null
    const vModel = (attrs.match(/v-model(?:\.[a-zA-Z]+)?\s*=\s*"([^"]+)"/) || [])[1] || null
    const placeholder = (attrs.match(/placeholder\s*=\s*"([^"]*)"/) || [])[1] || null
    const to = (attrs.match(/(?:^|\s)(?::)?to\s*=\s*"([^"]+)"/) || [])[1] || null
    const href = (attrs.match(/href\s*=\s*"([^"]+)"/) || [])[1] || null
    const hasVFor = /v-for\s*=/.test(attrs)
    const typeM = attrs.match(/type\s*=\s*"([^"]+)"/)
    const clsM = attrs.match(/class\s*=\s*"([^"]+)"/)
    const t = (text || '').replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim().slice(0, 60)
    const name = t || vModel || placeholder || click || extra.tag
    const danger = DANGER_RE.test(name) || (click && DANGER_RE.test(click))
    const submit = SUBMIT_RE.test(name)
    const ai = AI_RE.test(name)
    const isLink = extra.tag === 'a' || extra.tag === 'RouterLink'
    feats.push({
      kind,
      tag: extra.tag || null,
      cls: clsM ? clsM[1] : null,
      text: t,
      textAlt: textAltCandidates(t),
      handler: click,
      vModel,
      placeholder,
      to: to || href,
      internal: isLink && to ? /^\//.test(to) : null,
      type: typeM ? typeM[1] : null,
      repeat: hasVFor,
      enclosing: enclosingAt(idx),
      line: baseLine + lineOf(src, ts + idx) - 1,
      tab: tabAt(idx),
      modal: modalAt(idx),
      risk: danger ? 'danger' : ai ? 'ai' : submit ? 'submit' : 'safe',
    })
  }

  /* --- button（标签头允许属性值内含 >，如 v-if="n >= 1"；attrs 走捕获组避免截断） --- */
  const btnRe = /<button((?:[^>"']|"[^"]*"|'[^']*')*)>([\s\S]*?)<\/button>/g
  let b
  while ((b = btnRe.exec(tpl))) push('button', b.index, b[1] + ' ' + b[2], b[2], { tag: 'button' })
  /* --- a / RouterLink --- */
  const aRe = /<(a|RouterLink)((?:[^>"']|"[^"]*"|'[^']*')*)>([\s\S]*?)<\/(?:a|RouterLink)>/g
  while ((b = aRe.exec(tpl))) push('link', b.index, b[2] + ' ' + b[3], b[3], { tag: b[1] })
  /* --- input（含自闭合/非自闭合） --- */
  const inRe = /<input((?:[^>"']|"[^"]*"|'[^']*')*)(?:\/>|>)/g
  while ((b = inRe.exec(tpl))) {
    const attrs = b[1]
    if (/type\s*=\s*"(hidden|file)"/.test(attrs)) {
      if (/type\s*=\s*"file"/.test(attrs)) push('file', b.index, attrs, '', { tag: 'input[type=file]' })
      continue
    }
    push('input', b.index, attrs, '', { tag: 'input' })
  }
  /* --- select --- */
  const selRe = /<select((?:[^>"']|"[^"]*"|'[^']*')*)>([\s\S]*?)<\/select>/g
  while ((b = selRe.exec(tpl))) push('select', b.index, b[1], '', { tag: 'select' })
  /* --- textarea --- */
  const taRe = /<textarea((?:[^>"']|"[^"]*"|'[^']*')*)>([\s\S]*?)<\/textarea>/g
  while ((b = taRe.exec(tpl))) push('textarea', b.index, b[1], '', { tag: 'textarea' })

  /* --- div[role=button] / div 带 @click（排除遮罩 @click.self 与 modal-mask） --- */
  const divRe = /<div\b((?:[^>"']|"[^"]*"|'[^']*')*@click(?:[^>"']|"[^"]*"|'[^']*')*)>/g
  while ((b = divRe.exec(tpl))) {
    const attrs = b[1]
    if (/@click\.self/.test(attrs) || /class="[^"]*modal-mask/.test(attrs)) continue
    const raw = tpl.slice(b.index, b.index + 400)
    const text = raw
      .replace(/<div\b[^>]*>/g, ' ')
      .replace(/<[^>]*>/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 60)
    push('button', b.index, attrs, text, { tag: 'div@click' })
  }

  feats.sort((x, y) => x.line - y.line)
  return { id: moduleId, route, tabMode, features: feats, modalTriggers }
}

/* ---------- 组装清单 ---------- */
const modules = []

/* 门户/账户/hub/prompts */
modules.push(extractFile(path.join(VIEWS, 'IndexView.vue'), 'home', '/', null))
modules.push(extractFile(path.join(VIEWS, 'AuthView.vue'), 'auth', '/auth', null))
modules.push(extractFile(path.join(VIEWS, 'RegisterView.vue'), 'register', '/register', null))
modules.push(extractFile(path.join(VIEWS, 'AppCardsView.vue'), 'hub', '/app', null))
modules.push(extractFile(path.join(VIEWS, 'PromptsView.vue'), 'prompts', '/prompts', 'activeTab'))

/* 壳层功能（顶栏 / prompts 侧栏 / 工具页侧栏+面包屑） */
const shell = extractFile(path.join(SHELL, 'AppTopBar.vue'), 'shell:topbar', '(shell)', null)
shell.features.forEach((f) => (f.scope = 'topbar'))
const wsShell = extractFile(path.join(LAYOUTS, 'WorkspaceLayout.vue'), 'shell:prompts-sidebar', '(shell)', null)
wsShell.features.forEach((f) => (f.scope = 'prompts-sidebar'))
const toolShell = extractFile(path.join(LAYOUTS, 'ToolLayout.vue'), 'shell:tool-sidebar', '(shell)', null)
toolShell.features.forEach((f) => (f.scope = 'tool-sidebar'))
modules.push(shell, wsShell, toolShell)

/* 27 工具页 */
for (const t of CATALOG) {
  const p = path.join(VIEWS, 'tools', t.slug + '.vue')
  if (!fs.existsSync(p)) {
    console.error('MISSING view:', t.slug)
    continue
  }
  const mod = extractFile(p, t.slug, '/t/' + t.slug, 'tab')
  mod.title = t.title
  mod.tabs = t.tabs
  modules.push(mod)
}

/* ---------- 校验 & 汇总 ---------- */
const manifest = { at: new Date().toISOString(), modules }
const outPath = path.join(ROOT, '.playwright-mcp', 'features-manifest.json')
fs.mkdirSync(path.dirname(outPath), { recursive: true })
fs.writeFileSync(outPath, JSON.stringify(manifest, null, 2))

let total = 0
console.log('==== 功能清单（模块 → tab → 最小功能） ====')
for (const mod of modules) {
  const byTab = {}
  for (const f of mod.features) {
    const k = f.tab || '(页面级)'
    ;(byTab[k] = byTab[k] || []).push(f)
    total++
  }
  const tabs = mod.tabs ? ` [${mod.tabs.map((t) => t.key).join(',')}]` : ''
  console.log(`\n■ ${mod.id}  ${mod.route}${tabs}  ${mod.features.length} 项`)
  for (const [k, list] of Object.entries(byTab)) {
    const brief = list
      .map((f) => `${f.kind[0].toUpperCase()}:${(f.text || f.vModel || f.placeholder || '?').slice(0, 18)}${f.risk === 'danger' ? '⚠' : ''}`)
      .join(' | ')
    console.log(`  ├ ${k} (${list.length}) ${brief}`)
  }
}
console.log(`\nTOTAL features: ${total}  → ${outPath}`)

/* tab 归属完整性：catalog 声明的 tab 是否都有 v-if 出现 */
const warnings = []
for (const mod of modules) {
  if (!mod.tabs) continue
  const hit = new Set(mod.features.map((f) => f.tab).filter(Boolean))
  for (const t of mod.tabs) {
    if (!hit.has(t.key)) warnings.push(`${mod.id}: tab "${t.key}" 下未提取到元素`)
  }
}
if (warnings.length) {
  console.log('\nWARN tab 归属:')
  for (const w of warnings) console.log('  -', w)
}
