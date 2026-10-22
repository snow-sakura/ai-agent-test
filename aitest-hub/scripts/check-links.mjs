#!/usr/bin/env node
/* 死链静态扫描：manifest 全部内部 RouterLink 目标 vs 路由表 + TOOL_CATALOG。
   本项目 catch-all 会把未知路径静默重定向 /app（不报 404），死链表现为
   "点击后跳到工具台首页"——静态检查比运行时更可靠。
   输出：.playwright-mcp/link-scan-report.json；exit 1 = 有死链。 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, '.playwright-mcp/features-manifest.json'), 'utf8'))
const catalog = fs.readFileSync(path.join(ROOT, 'frontend/src/data/catalog.ts'), 'utf8')
const slugs = new Set([...catalog.matchAll(/"slug":\s*"([^"]+)"/g)].map((m) => m[1]))

/* 与 frontend/src/router/index.ts 保持同步的一级静态路由 */
const STATIC_ROUTES = new Set(['', '/', '/app', '/auth', '/register', '/prompts'])

const dead = []
const noise = []
let ok = 0
for (const mod of manifest.modules) {
  for (let i = 0; i < mod.features.length; i++) {
    const f = mod.features[i]
    if (f.kind !== 'link' || !f.to) continue
    const to = f.to
    // 提取噪音：锚点、对象绑定、动态表达式、外链（外链不在本检查范围）
    if (to.startsWith('http') || !to.startsWith('/') || to.includes('{') || to.includes('.href')) {
      noise.push({ mod: mod.id, idx: i, to })
      continue
    }
    const p = to.split('?')[0].split('#')[0]
    if (STATIC_ROUTES.has(p)) ok++
    else if (p.startsWith('/t/') && slugs.has(p.slice(3))) ok++
    else dead.push({ mod: mod.id, idx: i, to, path: p })
  }
}

const report = { at: new Date().toISOString(), slugs: slugs.size, ok, dead, noise }
fs.writeFileSync(path.join(ROOT, '.playwright-mcp/link-scan-report.json'), JSON.stringify(report, null, 1))
console.log(`catalog slugs ${slugs.size} | 有效 ${ok} | 死链 ${dead.length} | 提取噪音 ${noise.length}`)
for (const d of dead) console.log(`✗ ${d.mod}[${d.idx}] → ${d.to}`)
process.exit(dead.length ? 1 : 0)
