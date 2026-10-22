#!/usr/bin/env node
/* API 死链静态核对：前端 API 调用 vs 后端运行时路由表（/openapi.json 权威）。
   前端 axios baseURL='/api'，调用字面量不带前缀：提取 http.verb('/path') 与
   fetch('/api/...')，统一补 /api 后与 openapi paths 逐段匹配（:param/* 泛化）。
   输出未匹配项；exit 1 = 有 API 死链或后端缺路由。 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const OPENAPI = process.env.OPENAPI_URL || 'http://127.0.0.1:8000/openapi.json'

/* ---------- 后端路由（运行时权威） ---------- */
let spec
try {
  spec = await (await fetch(OPENAPI)).json()
} catch (e) {
  console.error('无法获取 openapi:', String(e).slice(0, 120))
  process.exit(2)
}
const routeSegs = Object.keys(spec.paths).map((p) => p.split('/').filter(Boolean))

/* ---------- 前端调用收集 ---------- */
const fe = path.join(ROOT, 'frontend/src')
const calls = new Set()
function walkFe(dir) {
  for (const name of fs.readdirSync(dir)) {
    const p = path.join(dir, name)
    if (fs.statSync(p).isDirectory()) walkFe(p)
    else if (/\.(vue|ts|js)$/.test(name)) {
      const src = fs.readFileSync(p, 'utf8')
      // axios 封装: http.get('/path') / http.post(`/path...`)
      for (const m of src.matchAll(/\bhttp\.(get|post|put|delete|patch)\(\s*[`'"](\/[^`'"\s]*)[`'"]/g)) {
        calls.add('/api' + m[2].split('?')[0])
      }
      // 直接 fetch('/api/...')——仅限 fetch( 调用，排除业务数据里的同形 URL
      for (const m of src.matchAll(/\bfetch\(\s*[`'"](\/api\/[A-Za-z0-9_\-/${}.?=&]*)[`'"]/g)) {
        calls.add(m[1].split('?')[0])
      }
    }
  }
}
walkFe(fe)

/* ---------- 匹配（逐段，动态段泛化为 *） ---------- */
const seg = (u) => u.split('/').filter(Boolean).map((s) => (s.startsWith('${') || s.includes('${') ? '*' : s))
const unmatched = []
let ok = 0
for (const c of [...calls].sort()) {
  const a = seg(c)
  const hit = routeSegs.some((b) => a.length === b.length && a.every((s, i) => s === b[i] || s === '*' || b[i].startsWith('{')))
  if (hit) ok++
  else unmatched.push(c)
}

console.log(`后端 openapi 路由 ${routeSegs.length} | 前端调用 ${calls.size} | 匹配 ${ok} | 未匹配 ${unmatched.length}`)
for (const u of unmatched) console.log('✗ ' + u)
fs.writeFileSync(
  path.join(ROOT, '.playwright-mcp/api-scan-report.json'),
  JSON.stringify({ at: new Date().toISOString(), openapi: routeSegs.length, frontend: calls.size, ok, unmatched }, null, 1),
)
process.exit(unmatched.length ? 1 : 0)
