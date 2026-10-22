/**
 * /prompts 第四轮修复验证：真分页展示
 * 断言：
 *  1) 默认每页 6 条（grid-3 两行）
 *  2) 分页条始终完整在视口内（不被裁切），且滚动列表后仍可见
 *  3) 末行卡片在列表滚动区内可达且完整
 *  4) 主区/页面自身不需要滚动（scrollHeight ≈ clientHeight），滚动只发生在 .prompts-scroll
 *  5) 翻页/每页条数切换生效
 *  6) 顶栏仍 58px、无 pageerror
 * 多视口：1917×967 / 1440×900 / 1366×768 / 1280×720 / 1920×1080
 */
import { createRequire } from 'node:module'
import path from 'node:path'
import fs from 'node:fs'

const require = createRequire(import.meta.url)
const { chromium } = require('/Users/snow-sakura/.npm-global/lib/node_modules/playwright')

const BASE = 'http://127.0.0.1:5173'
const OUT = path.resolve('.playwright-mcp/screens/prompts-pagination')
fs.mkdirSync(OUT, { recursive: true })

const VIEWPORTS = [
  { w: 1917, h: 967 },
  { w: 1440, h: 900 },
  { w: 1366, h: 768 },
  { w: 1280, h: 720 },
  { w: 1920, h: 1080 },
]

let pass = 0
let fail = 0
function assert(cond, msg) {
  if (cond) { pass++; console.log('  PASS', msg) }
  else { fail++; console.log('  FAIL', msg) }
}

async function login(page) {
  await page.goto(BASE + '/auth', { waitUntil: 'networkidle', timeout: 30000 })
  await page.fill('#account', process.env.DEMO_ACCOUNT || 'demo_tester')
  await page.fill('#password', process.env.DEMO_PASSWORD || 'Demo@2026')
  await page.click('form button[type="submit"]')
  await page.waitForURL('**/app', { timeout: 15000 }).catch(() => {})
}

const browser = await chromium.launch()

for (const vp of VIEWPORTS) {
  console.log(`\n== viewport ${vp.w}×${vp.h} ==`)
  const ctx = await browser.newContext({ viewport: { width: vp.w, height: vp.h } })
  const page = await ctx.newPage()
  const pageErrors = []
  page.on('pageerror', (e) => pageErrors.push(String(e)))

  await login(page)
  await page.goto(BASE + '/prompts', { waitUntil: 'networkidle', timeout: 30000 })
  await page.waitForTimeout(600)

  // --- 默认 6 条 ---
  const cards = await page.locator('.prompts-scroll .grid-3 > .card').count()
  assert(cards === 6, `默认每页 6 条，实际 ${cards}`)

  const selVal = await page.locator('.pagination .pg-size-sel').inputValue()
  assert(selVal === '6', `每页条数选择器 = 6，实际 ${selVal}`)

  // --- 分页条完整在视口内 ---
  const pagerBox = await page.locator('.prompts-pager .pagination').boundingBox()
  assert(!!pagerBox, '分页条存在')
  if (pagerBox) {
    assert(pagerBox.y >= 0 && pagerBox.y + pagerBox.height <= vp.h + 1,
      `分页条在视口内 (y=${Math.round(pagerBox.y)} h=${Math.round(pagerBox.height)} vh=${vp.h})`)
  }

  // --- 顶栏 58px ---
  const topH = await page.locator('.topbar').evaluate((el) => Math.round(el.getBoundingClientRect().height))
  assert(topH === 58, `顶栏 58px，实际 ${topH}`)

  // --- 主区/页面不滚：滚动只在 .prompts-scroll ---
  const scrolls = await page.evaluate(() => {
    const main = document.querySelector('.main-area')
    const scroll = document.querySelector('.prompts-scroll')
    return {
      mainOverflow: main ? main.scrollHeight - main.clientHeight : -1,
      bodyOverflow: document.documentElement.scrollHeight - document.documentElement.clientHeight,
      scrollable: scroll ? scroll.scrollHeight - scroll.clientHeight : -1,
      sbw: window.innerWidth - document.documentElement.clientWidth,
    }
  })
  assert(scrolls.mainOverflow <= 1, `主区自身不滚 (overflow=${scrolls.mainOverflow})`)
  assert(scrolls.bodyOverflow <= 1, `页面 body 不滚 (overflow=${scrolls.bodyOverflow})`)
  assert(scrolls.scrollable >= 0, `列表滚动区存在 (可滚 ${scrolls.scrollable}px)`)

  // --- 滚动列表到末尾：末行卡片完整可见 + 分页条仍完整 ---
  await page.evaluate(() => {
    const s = document.querySelector('.prompts-scroll')
    if (s) s.scrollTop = s.scrollHeight
  })
  await page.waitForTimeout(250)

  const lastCard = page.locator('.prompts-scroll .grid-3 > .card').last()
  const cardBox = await lastCard.boundingBox()
  const scrollBox = await page.locator('.prompts-scroll').boundingBox()
  assert(!!cardBox && !!scrollBox, '末卡与滚动区可测量')
  if (cardBox && scrollBox) {
    const inside =
      cardBox.y >= scrollBox.y - 1 &&
      cardBox.y + cardBox.height <= scrollBox.y + scrollBox.height + 1
    assert(inside,
      `末行卡片完整在滚动视口内 (card=${Math.round(cardBox.y)}..${Math.round(cardBox.y + cardBox.height)} scroll=${Math.round(scrollBox.y)}..${Math.round(scrollBox.y + scrollBox.height)})`)
  }

  const pagerBox2 = await page.locator('.prompts-pager .pagination').boundingBox()
  assert(!!pagerBox2 && pagerBox2.y >= 0 && pagerBox2.y + pagerBox2.height <= vp.h + 1,
    '滚动后分页条仍完整在视口内')

  await page.screenshot({ path: path.join(OUT, `bottom-${vp.w}x${vp.h}.png`) })

  // --- 翻页 ---
  await page.locator('.pagination .page-btn.txt', { hasText: '下一页' }).click()
  await page.waitForTimeout(300)
  const info2 = await page.locator('.pagination .page-info').textContent()
  assert(/第 2\//.test(info2 || ''), `下一页 → 第 2 页，实际 "${info2}"`)
  const active2 = await page.locator('.pagination .page-btn.active').textContent()
  assert((active2 || '').trim() === '2', `激活页码 = 2，实际 "${active2}"`)

  // 翻页后滚动条重置并仍可见（grid 回顶部）
  await page.evaluate(() => {
    const s = document.querySelector('.prompts-scroll')
    if (s) s.scrollTop = 0
  })
  const firstCardBox = await page.locator('.prompts-scroll .grid-3 > .card').first().boundingBox()
  const scrollBox2 = await page.locator('.prompts-scroll').boundingBox()
  assert(!!firstCardBox && !!scrollBox2 && firstCardBox.y >= scrollBox2.y - 1,
    '第 2 页首卡在滚动区顶部可见')

  // --- 每页条数切换 10 ---
  await page.locator('.pagination .pg-size-sel').selectOption('10')
  await page.waitForTimeout(300)
  const cards10 = await page.locator('.prompts-scroll .grid-3 > .card').count()
  assert(cards10 === 10, `切到每页 10 条，实际 ${cards10}`)
  const pagerBox3 = await page.locator('.prompts-pager .pagination').boundingBox()
  assert(!!pagerBox3 && pagerBox3.y + pagerBox3.height <= vp.h + 1,
    '每页 10 条时分页条仍完整在视口内')

  // 10 条时列表内滚，末卡滚到底可达
  await page.evaluate(() => {
    const s = document.querySelector('.prompts-scroll')
    if (s) s.scrollTop = s.scrollHeight
  })
  await page.waitForTimeout(200)
  const last10 = await page.locator('.prompts-scroll .grid-3 > .card').last().boundingBox()
  const scrollBox3 = await page.locator('.prompts-scroll').boundingBox()
  if (last10 && scrollBox3) {
    const inside10 =
      last10.y + last10.height <= scrollBox3.y + scrollBox3.height + 1
    assert(inside10, '每页 10 条滚到底末卡完整可见')
  }
  await page.screenshot({ path: path.join(OUT, `size10-${vp.w}x${vp.h}.png`) })

  assert(pageErrors.length === 0, `无 pageerror: ${pageErrors.slice(0, 3).join(';')}`)

  await ctx.close()
}

await browser.close()

console.log(`\nRESULT pass=${pass} fail=${fail}`)
process.exit(fail ? 1 : 0)
