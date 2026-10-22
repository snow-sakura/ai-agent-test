#!/usr/bin/env node
/* 审查 SKIP 项：实测 workflow-editor 节点 modal / skill-library 技能 modal
   是否真打不开（modal-will-not-open）或触发器真不存在（modal-no-trigger） */
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const { chromium } = require('/Users/snow-sakura/.npm-global/lib/node_modules/playwright')

const BASE = 'http://127.0.0.1:5173'
const out = []
const browser = await chromium.launch()
const ctx = await browser.newContext()
const token = await (await fetch('http://127.0.0.1:8000/api/auth/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({
    username: process.env.DEMO_ACCOUNT || 'demo_tester',
    password: process.env.DEMO_PASSWORD || 'Demo@2026',
  }).toString(),
})).json().then((d) => d.access_token)
await ctx.addInitScript((t) => {
  localStorage.setItem('aitesthub_token', t)
  localStorage.setItem('aitesthub_auth', '1')
  localStorage.setItem('aitesthub_login_user', 'admin')
}, token)
const page = await ctx.newPage()
page.on('pageerror', (e) => out.push('pageerror: ' + String(e).slice(0, 150)))

// 1) workflow-editor：加载画布 → 点击节点 → modal 开？
await page.goto(BASE + '/t/tool-workflow-editor', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(2500)
const wf = await page.evaluate(() => {
  const mask = document.querySelector('.modal-mask')
  const nodes = document.querySelectorAll('.canvas-node, [class*=canvas] [style*="cursor: pointer"], [style*="cursor: pointer"]')
  return { maskExists: !!mask, nodeCount: nodes.length }
})
out.push(`workflow: mask=${wf.maskExists} nodes=${wf.nodeCount}`)
if (wf.nodeCount) {
  await page.click('[style*="cursor: pointer"]', { timeout: 5000 }).catch((e) => out.push('clickNode: ' + e.message.slice(0, 100)))
  await page.waitForTimeout(800)
  const opened = await page.evaluate(() => !!document.querySelector('.modal-mask.open'))
  out.push(`workflow: 点击节点后 modal.open=${opened}`)
  if (opened) {
    const has = await page.evaluate(() => ({
      ndType: !!document.querySelector('.modal-mask.open input.input[readonly]'),
      saveBtn: [...document.querySelectorAll('.modal-mask.open button')].some((b) => b.textContent.includes('保存配置')),
      cancel: [...document.querySelectorAll('.modal-mask.open button')].some((b) => b.textContent.includes('取消')),
      close: [...document.querySelectorAll('.modal-mask.open button')].some((b) => b.textContent.includes('✕')),
    }))
    out.push('workflow modal 内控件: ' + JSON.stringify(has))
  }
}

// 2) skill-library：触发器按钮存在性 + 打开 modal
await page.goto(BASE + '/t/tool-skill-library', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(2500)
const trig = await page.evaluate(() => {
  const btns = [...document.querySelectorAll('button')]
  const has = (t) => btns.some((b) => b.textContent.includes(t) && b.offsetParent)
  return { newSkill: has('新建技能'), edit: has('编辑'), replay: has('重新执行') }
})
out.push('skill-library 可见触发器: ' + JSON.stringify(trig))
if (trig.newSkill) {
  await page.click('button:has-text("新建技能")', { timeout: 5000 }).catch((e) => out.push('clickNew: ' + e.message.slice(0, 80)))
  await page.waitForTimeout(800)
  const opened = await page.evaluate(() => !!document.querySelector('.modal-mask.open'))
  out.push('skill-library 点击新建后 modal.open=' + opened)
  if (opened) {
    const has = await page.evaluate(() => [...document.querySelectorAll('.modal-mask.open button')].map((b) => b.textContent.trim()).filter(Boolean))
    out.push('skill modal 按钮: ' + JSON.stringify(has))
  }
}
// 重新执行触发器（可能在 hover 行内）
if (trig.replay) {
  out.push('skill-library「重新执行」可见存在')
} else {
  const anyReplay = await page.evaluate(() => [...document.querySelectorAll('button')].some((b) => b.textContent.includes('重新执行')))
  out.push('skill-library「重新执行」任意存在(可能折叠): ' + anyReplay)
}

await browser.close()
console.log(out.join('\n'))
