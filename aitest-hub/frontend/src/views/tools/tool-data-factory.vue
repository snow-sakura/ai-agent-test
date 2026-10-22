<script setup lang="ts">
import { onMounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import { uiToast, uiPrompt } from '@/composables/ui'
import http from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-data-factory.html + data_factory.py） ---------- */
interface TestDataRow {
  [k: string]: string
}
interface AiTestDataResp {
  rows: TestDataRow[]
  fields: string[]
  source: string
  count: number
}
interface CronResp {
  expr: string
  ok: boolean
  next: string[]
  next5: string[]
}

const SURNAMES = '张王李赵刘陈杨黄周吴徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭'.split('')
const GIVEN = ['伟', '芳', '娜', '敏', '静', '磊', '军', '洋', '勇', '艳', '杰', '涛', '明', '超', '秀英']
const CITIES = [
  '北京市朝阳区',
  '上海市浦东新区',
  '广州市天河区',
  '深圳市南山区',
  '杭州市西湖区',
  '成都市高新区',
]

function rnd<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)]
}
function rint(a: number, b: number): number {
  return Math.floor(Math.random() * (b - a + 1)) + a
}
function uuid(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

function genOne(): TestDataRow {
  return {
    name: rnd(SURNAMES) + rnd(GIVEN) + (Math.random() > 0.6 ? rnd(GIVEN) : ''),
    phone: '1' + rnd(['3', '5', '7', '8', '9']) + String(rint(100000000, 999999999)),
    email: 'test_' + rint(1000, 9999) + '@' + rnd(['qq.com', '163.com', 'gmail.com']),
    addr:
      rnd(CITIES) +
      rnd(['幸福路', '望江道', '科技园', '创业大街']) +
      rint(1, 999) +
      '号',
    idcard:
      '1101011990' +
      String(rint(1, 12)).padStart(2, '0') +
      String(rint(1, 28)).padStart(2, '0') +
      rint(1000, 9999),
    bank: '62' + String(rint(1000000000000000, 9999999999999999)).slice(0, 17),
    credit: '91310000MA' + rint(100000, 999999) + 'X' + rint(10, 99),
    uuid: uuid(),
  }
}

async function copyText(text: string, okMsg: string) {
  try {
    await navigator.clipboard.writeText(text)
    uiToast(okMsg, 'success')
  } catch {
    uiToast('复制失败，请手动选择复制', 'error')
  }
}

/* ================= 测试数据生成 ================= */
const td = ref<TestDataRow>({
  name: '',
  phone: '',
  email: '',
  addr: '',
  idcard: '',
  bank: '',
  credit: '',
  uuid: '',
})
const tdBatch = ref(false)
const tdBatchOut = ref('')
const tdAiInput = ref('')
const tdAiOut = ref('')
const tdAiLoading = ref(false)

function fillOne(d: TestDataRow) {
  td.value = { ...td.value, ...d }
}

function tdGen() {
  if (tdBatch.value) {
    const rows: string[] = []
    for (let i = 0; i < 100; i++) {
      const d = genOne()
      rows.push([d.name, d.phone, d.email, d.addr].join(','))
    }
    tdBatchOut.value = 'name,phone,email,addr\n' + rows.join('\n')
    uiToast('已生成 100 条批量数据', 'success')
  } else {
    fillOne(genOne())
    tdBatchOut.value = ''
  }
}

function tdCopy() {
  const vals = [td.value.name, td.value.phone, td.value.email, td.value.addr]
  if (vals.every((v) => !v)) {
    uiToast('请先生成数据', 'warn')
    return
  }
  copyText(vals.join('\n'), '已复制全部字段')
}

function tdExport() {
  const src = tdBatchOut.value || td.value
  let csv: string
  if (typeof src === 'string' && src) {
    csv = src
  } else {
    const keys = ['name', 'phone', 'email', 'addr', 'idcard', 'bank', 'credit', 'uuid']
    csv = keys.join(',') + '\n' + keys.map((k) => (td.value[k] ?? '')).join(',')
  }
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'test-data.csv'
  a.click()
  URL.revokeObjectURL(a.href)
  uiToast('test-data.csv 导出成功', 'success')
}

async function tdAiGo() {
  const q = tdAiInput.value.trim()
  if (!q) {
    uiToast('请描述数据场景', 'error')
    return
  }
  tdAiLoading.value = true
  try {
    const { data } = await http.post<AiTestDataResp>('/data-factory/ai-testdata', { desc: q, n: 5 })
    tdAiOut.value = (data.rows || [])
      .map((r) => JSON.stringify(r))
      .join('\n')
    uiToast(
      `AI 已生成 ${data.count} 条场景数据（${data.source === 'ai' ? 'AI' : '本地回退'}），可复制到接口测试引用`,
      'success',
    )
  } finally {
    tdAiLoading.value = false
  }
}

/* ================= 随机工具 ================= */
const rdMin = ref(0)
const rdMax = ref(100)
const rdLen = ref(16)
const rdCharset = ref('字母+数字')
const rdOut = ref('// 结果…')

const CHARSETS: Record<string, string> = {
  '字母+数字': 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789',
  纯字母: 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ',
  纯数字: '0123456789',
  含特殊字符: 'abcdefghijkmnpqrstuvwxyz23456789!@#$%^&*',
}

function rdNum() {
  rdOut.value = String(rint(rdMin.value, rdMax.value))
}
function rdStr() {
  const len = rdLen.value || 16
  const cs = CHARSETS[rdCharset.value] || CHARSETS['字母+数字']
  let s = ''
  for (let i = 0; i < len; i++) s += cs[rint(0, cs.length - 1)]
  rdOut.value = s
}
function rdBool() {
  rdOut.value = Math.random() > 0.5 ? 'true' : 'false'
}
function rdPick() {
  uiPrompt({
    title: '🎯 随机列表元素',
    label: '候选列表（逗号分隔）',
    defaultValue: 'Chrome,Firefox,Edge',
    onOk: (val) => {
      const list = (val || '')
        .split(',')
        .map((x) => x.trim())
        .filter(Boolean)
      if (!list.length) {
        uiToast('请至少输入一个候选项', 'warn')
        return
      }
      const picked = rnd(list)
      rdOut.value = picked
      uiToast('已随机选出：' + picked, 'success')
    },
  })
}
function rdCopy() {
  if (!rdOut.value || rdOut.value.startsWith('//')) {
    uiToast('暂无结果', 'warn')
    return
  }
  copyText(rdOut.value, '已复制结果')
}

/* ================= 加密工具 ================= */
const crIn = ref('')
const crKey = ref('')
const crOut = ref('')
const jwtIn = ref('')
const jwtOut = ref('// Header / Payload 将在此显示')

function demoHash(alg: string, text: string): string {
  let seed = 0
  for (let i = 0; i < text.length; i++) seed = (seed * 31 + text.charCodeAt(i)) >>> 0
  const hex = seed.toString(16).padStart(8, '0')
  const lenMap: Record<string, number> = { MD5: 32, SHA1: 40, SHA256: 64, SHA512: 128 }
  const len = lenMap[alg] || 32
  let s = ''
  while (s.length < len) s += (hex + Math.random().toString(16).slice(2)).slice(0, 8)
  return s.slice(0, len)
}

function doHash(alg: string) {
  const v = crIn.value
  if (!v) {
    uiToast('请输入明文', 'warn')
    return
  }
  crOut.value = demoHash(alg, v)
  uiToast(alg + ' 完成（演示格式）', 'success')
}
function aesEnc() {
  const v = crIn.value
  const k = crKey.value
  if (!v || !k) {
    uiToast('请输入明文与密钥', 'warn')
    return
  }
  crOut.value = btoa(unescape(encodeURIComponent(v + '::' + k)))
  uiToast('AES 加密完成（演示）', 'success')
}
function aesDec() {
  try {
    const raw = decodeURIComponent(escape(atob(crOut.value.trim())))
    crOut.value = raw.split('::')[0]
    uiToast('AES 解密完成（演示）', 'success')
  } catch {
    uiToast('解密失败：内容非本工具加密结果', 'error')
  }
}
function hmacSign() {
  const v = crIn.value
  const k = crKey.value
  if (!v || !k) {
    uiToast('请输入明文与密钥', 'warn')
    return
  }
  crOut.value = 'hmac:' + demoHash('SHA256', v + k)
  uiToast('HMAC 签名完成（演示）', 'success')
}
function crCopy() {
  if (!crOut.value) {
    uiToast('暂无结果', 'warn')
    return
  }
  copyText(crOut.value, '已复制结果')
}
function b64Decode(s: string): string {
  const b = s.replace(/-/g, '+').replace(/_/g, '/')
  return decodeURIComponent(escape(atob(b)))
}
function jwtDec() {
  const t = jwtIn.value.trim()
  if (!t) {
    uiToast('请输入 JWT', 'warn')
    return
  }
  const parts = t.split('.')
  if (parts.length < 2) {
    uiToast('JWT 格式不正确', 'error')
    return
  }
  try {
    const h = JSON.parse(b64Decode(parts[0]))
    const p = JSON.parse(b64Decode(parts[1]))
    jwtOut.value =
      '// Header\n' + JSON.stringify(h, null, 2) + '\n\n// Payload\n' + JSON.stringify(p, null, 2)
    uiToast('JWT 解码成功', 'success')
  } catch (e) {
    uiToast('解码失败：' + (e as Error).message, 'error')
  }
}

/* ================= 字符工具 ================= */
const stIn = ref('')
const stOut = ref('')
const stRegex = ref('')
const stRegexShow = ref(false)
const stDiffA = ref('预期：支付成功后订单状态为已支付')
const stDiffB = ref('预期：支付成功后订单状态为待支付')
const stDiffOut = ref('// 差异…')

function stOp(op: string) {
  const v = stIn.value
  if (op === 'regex') {
    stRegexShow.value = true
    return
  }
  if (!v && op !== 'count') {
    uiToast('请输入文本', 'warn')
    return
  }
  if (op === 'upper') stOut.value = v.toUpperCase()
  if (op === 'lower') stOut.value = v.toLowerCase()
  if (op === 'trim') stOut.value = v.trim()
  if (op === 'reverse') stOut.value = v.split('').reverse().join('')
  if (op === 'count') {
    const words = v.trim().split(/\s+/).filter(Boolean).length
    stOut.value = `字符数：${v.length} · 行数：${v.split('\n').length} · 词数（空格分隔）：${words}`
  }
}
function stRegexGo() {
  const v = stIn.value
  try {
    const m = v.match(new RegExp(stRegex.value, 'g'))
    stOut.value = m ? `匹配 ${m.length} 处：\n` + m.join('\n') : '无匹配'
  } catch {
    uiToast('正则语法错误', 'error')
  }
}
function stCopy() {
  if (!stOut.value) {
    uiToast('暂无结果', 'warn')
    return
  }
  copyText(stOut.value, '已复制结果')
}
function stDiffGo() {
  const a = stDiffA.value.split('\n')
  const b = stDiffB.value.split('\n')
  let html = ''
  let add = 0
  let del = 0
  const max = Math.max(a.length, b.length)
  for (let i = 0; i < max; i++) {
    if (a[i] === b[i]) {
      html += '  ' + (a[i] || '') + '\n'
    } else {
      if (a[i] !== undefined) {
        html += '- ' + a[i].replace(/</g, '&lt;') + '\n'
        del++
      }
      if (b[i] !== undefined) {
        html += '+ ' + b[i].replace(/</g, '&lt;') + '\n'
        add++
      }
    }
  }
  stDiffOut.value = html
  uiToast(`对比完成：+${add} / -${del}`, 'success')
}

/* ================= JSON 工具 ================= */
const jsIn = ref('')
const jsOut = ref('// 结果…')
const jsPath = ref('')

function tryParse(): unknown | null {
  try {
    return JSON.parse(jsIn.value)
  } catch (e) {
    uiToast('JSON 语法错误：' + (e as Error).message.slice(0, 40), 'error')
    return null
  }
}
function jout(t: string) {
  jsOut.value = t
}
function jsFmt() {
  const o = tryParse()
  if (o !== null) {
    jout(JSON.stringify(o, null, 2))
    uiToast('格式化成功', 'success')
  }
}
function jsMin() {
  const o = tryParse()
  if (o !== null) {
    jout(JSON.stringify(o))
    uiToast('压缩成功', 'success')
  }
}
function jsValidate() {
  const o = tryParse()
  if (o !== null) {
    const top = Array.isArray(o) ? 'Array' : typeof o
    const keys =
      typeof o === 'object' && o !== null ? Object.keys(o as Record<string, unknown>).length : '-'
    jout(`✅ JSON 合法\n顶层类型：${top}\n顶层键数：${keys}`)
    uiToast('校验通过', 'success')
  }
}
function toXml(obj: unknown, indent: string): string {
  if (typeof obj !== 'object' || obj === null) return indent + String(obj) + '\n'
  let x = ''
  for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
    if (typeof v === 'object' && v !== null) {
      x += indent + '<' + k + '>\n' + toXml(v, indent + '  ') + indent + '</' + k + '>\n'
    } else {
      x += indent + '<' + k + '>' + String(v) + '</' + k + '>\n'
    }
  }
  return x
}
function jsXml() {
  const o = tryParse()
  if (o === null) return
  jout('<root>\n' + toXml(o, '  ') + '</root>')
  uiToast('已转 XML（演示）', 'success')
}
function toYaml(obj: unknown, depth: number): string {
  if (typeof obj !== 'object' || obj === null) return String(obj)
  const pad = '  '.repeat(depth)
  let y = ''
  for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
    if (typeof v === 'object' && v !== null) y += pad + k + ':\n' + toYaml(v, depth + 1)
    else y += pad + k + ': ' + String(v) + '\n'
  }
  return y
}
function jsYaml() {
  const o = tryParse()
  if (o === null) return
  jout(toYaml(o, 0))
  uiToast('已转 YAML（演示）', 'success')
}
function jsCsv() {
  const o = tryParse()
  if (o === null) return
  const arr = Array.isArray(o) ? (o as TestDataRow[]) : [o as TestDataRow]
  const keys = Object.keys(arr[0] || {})
  jout(
    keys.join(',') +
      '\n' +
      arr.map((r) => keys.map((k) => String(r[k] ?? '')).join(',')).join('\n'),
  )
  uiToast('已转 CSV（演示）', 'success')
}
function jsPathGo() {
  const o = tryParse()
  if (o === null) return
  const p = jsPath.value.trim()
  try {
    const parts = p
      .replace(/^\$\.?/, '')
      .split(/\.|\[(\d+)\]/)
      .filter(Boolean)
    let cur: unknown = o
    for (const part of parts) {
      if (typeof cur !== 'object' || cur === null) {
        cur = undefined
        break
      }
      cur = (cur as Record<string, unknown>)[part]
      if (cur === undefined) break
    }
    jout(cur === undefined ? '路径不存在' : JSON.stringify(cur, null, 2))
    uiToast(cur === undefined ? '路径不存在' : '查询成功', cur === undefined ? 'warn' : 'success')
  } catch {
    uiToast('查询失败', 'error')
  }
}

/* ================= Crontab ================= */
const WEEK = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
const ctIn = ref('0 2 * * *')
const ctOut = ref('// 解析结果…')
const ctLoading = ref(false)

function parseCronLocal(c: string): string | null {
  const p = c.trim().split(/\s+/)
  if (p.length !== 5) return null
  function desc(f: string, unit: string, names?: string[]): string {
    if (f === '*') return '每' + unit
    if (f.startsWith('*/')) return '每 ' + f.slice(2) + ' ' + unit
    if (f.includes('-') && !f.includes('/')) {
      const r = f.split('-')
      return names
        ? r.map((x) => names[+x]).join('、')
        : r[0] + ' 至 ' + r[1] + ' ' + unit
    }
    if (f.includes(',')) return '在 ' + f + ' ' + unit
    return names && names[+f] !== undefined ? names[+f] : f + ' ' + unit
  }
  return (
    '分：' +
    desc(p[0], '分钟') +
    '｜时：' +
    desc(p[1], '小时') +
    '｜日：' +
    desc(p[2], '日') +
    '｜月：' +
    desc(p[3], '月') +
    '｜周：' +
    desc(p[4], '周', WEEK)
  )
}

async function ctParse() {
  const local = parseCronLocal(ctIn.value)
  if (!local) {
    ctOut.value = '❌ 表达式格式不正确（需 5 段：分 时 日 月 周）'
    uiToast('表达式格式不正确', 'error')
    return
  }
  ctLoading.value = true
  try {
    const { data } = await http.post<CronResp>('/data-factory/crontab-parse', { expr: ctIn.value })
    ctOut.value =
      local +
      '\n\n下次执行：\n' +
      (data.next || []).map((t, i) => `  ${i + 1}. ${t}`).join('\n')
    uiToast('解析成功', 'success')
  } finally {
    ctLoading.value = false
  }
}

async function ctNext() {
  ctLoading.value = true
  try {
    const { data } = await http.post<CronResp>('/data-factory/crontab-parse', { expr: ctIn.value })
    ctOut.value = '下次执行：\n' + (data.next || []).map((t) => '  ' + t).join('\n')
    uiToast('已计算下次执行时间', 'success')
  } finally {
    ctLoading.value = false
  }
}

function ctFill(expr: string) {
  ctIn.value = expr
  ctOut.value = parseCronLocal(expr) || ''
  uiToast('已填入模板', 'info')
}

onMounted(() => {
  fillOne(genOne())
})
</script>

<template>
  <ModuleShell slug="tool-data-factory">
    <template #actions>
      <RouterLink class="btn btn-ghost" to="/t/tool-media-data-hub">🧰 媒体工具箱</RouterLink>
      <RouterLink class="btn btn-ghost" to="/t/tool-api-testing">🔗 去接口测试引用</RouterLink>
    </template>

    <template #default="{ tab }">
      <div class="banner banner-info">
        ℹ️ 参考 TestHub 数据工厂：所有工具本地执行、结果可复制；生成的测试数据（姓名/手机号/邮箱）可在接口测试环境变量中通过
        <span class="mono" v-pre>{{df.name}}</span> 直接引用。
      </div>

      <!-- ============ 测试数据生成 ============ -->
      <template v-if="tab === 'testdata'">
        <div class="card">
          <div class="card-title">
            👤 测试数据批量生成 <span class="tag tag-red">AI 增强</span>
          </div>
          <div class="grid grid-4" style="gap: 10px">
            <div class="field">
              <label>中文姓名</label>
              <input class="input mono" :value="td.name" readonly />
            </div>
            <div class="field">
              <label>手机号</label>
              <input class="input mono" :value="td.phone" readonly />
            </div>
            <div class="field">
              <label>邮箱</label>
              <input class="input mono" :value="td.email" readonly />
            </div>
            <div class="field">
              <label>地址</label>
              <input class="input mono" :value="td.addr" readonly />
            </div>
          </div>
          <div class="grid grid-4" style="gap: 10px">
            <div class="field">
              <label>身份证号</label>
              <input class="input mono" :value="td.idcard" readonly />
            </div>
            <div class="field">
              <label>银行卡号</label>
              <input class="input mono" :value="td.bank" readonly />
            </div>
            <div class="field">
              <label>统一社会信用代码</label>
              <input class="input mono" :value="td.credit" readonly />
            </div>
            <div class="field">
              <label>UUID</label>
              <input class="input mono" :value="td.uuid" readonly />
            </div>
          </div>
          <div class="flex">
            <button class="btn btn-primary" @click="tdGen">🎲 生成一批</button>
            <button class="btn btn-ghost" @click="tdCopy">📋 复制全部</button>
            <button class="btn btn-ghost" @click="tdExport">⬇️ 导出 CSV</button>
            <label class="checkbox">
              <input v-model="tdBatch" type="checkbox" /> 批量模式（100 条）
            </label>
          </div>
          <pre v-if="tdBatchOut" class="code-block mt-16" style="max-height: 220px; overflow-y: auto; white-space: pre-wrap">{{ tdBatchOut }}</pre>
          <div class="mt-16">
            <div class="card-title" style="font-size: 13.5px">🤖 AI 数据造景（按场景生成业务数据）</div>
            <div class="input-group">
              <input
                v-model="tdAiInput"
                class="input"
                placeholder="描述场景，如：生成 10 条电商退款订单测试数据（含金额、原因、时间）"
              />
              <button class="btn btn-primary" :disabled="tdAiLoading" @click="tdAiGo">
                <span v-if="tdAiLoading" class="spinner"></span> ✨ AI 生成
              </button>
            </div>
            <pre v-if="tdAiOut" class="code-block mt-8" style="white-space: pre-wrap">{{ tdAiOut }}</pre>
          </div>
        </div>
      </template>

      <!-- ============ 随机工具 ============ -->
      <template v-if="tab === 'random'">
        <div class="grid grid-2">
          <div class="card">
            <div class="card-title">🎲 随机数 / 随机字符串</div>
            <div class="grid grid-2" style="gap: 10px">
              <div class="field">
                <label>最小值</label>
                <input v-model.number="rdMin" class="input mono" type="number" />
              </div>
              <div class="field">
                <label>最大值</label>
                <input v-model.number="rdMax" class="input mono" type="number" />
              </div>
            </div>
            <div class="grid grid-2" style="gap: 10px">
              <div class="field">
                <label>字符串长度</label>
                <input v-model.number="rdLen" class="input mono" type="number" />
              </div>
              <div class="field">
                <label>字符集</label>
                <select v-model="rdCharset" class="select">
                  <option>字母+数字</option>
                  <option>纯字母</option>
                  <option>纯数字</option>
                  <option>含特殊字符</option>
                </select>
              </div>
            </div>
            <div class="flex" style="flex-wrap: wrap">
              <button class="btn btn-primary btn-sm" @click="rdNum">生成随机数</button>
              <button class="btn btn-primary btn-sm" @click="rdStr">生成随机字符串</button>
              <button class="btn btn-ghost btn-sm" @click="rdBool">随机布尔</button>
              <button class="btn btn-ghost btn-sm" @click="rdPick">随机列表元素</button>
            </div>
            <div class="code-block mt-16" style="white-space: pre-wrap">{{ rdOut }}</div>
            <button class="btn btn-ghost btn-sm mt-8" @click="rdCopy">📋 复制结果</button>
          </div>
          <div class="card">
            <div class="card-title">📋 随机工具说明</div>
            <div style="display: flex; flex-direction: column; gap: 10px; font-size: 13px; color: var(--text-dim)">
              <div>• <b>随机数</b>：指定区间 [min, max] 均匀分布</div>
              <div>• <b>随机字符串</b>：四种字符集，可用于临时密码 / Token</div>
              <div>• <b>随机布尔</b>：true / false 各 50%</div>
              <div>• <b>随机列表元素</b>：从逗号分隔列表中随机抽取</div>
              <div class="banner banner-info" style="margin: 0">
                💡 所有随机结果均可点击「复制」，或在环境变量中以 <span class="mono" v-pre>{{df.random}}</span> 引用
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- ============ 加密工具 ============ -->
      <template v-if="tab === 'crypto'">
        <div class="grid grid-2">
          <div class="card">
            <div class="card-title">🔐 哈希 / 加密</div>
            <div class="field">
              <label>明文</label>
              <textarea v-model="crIn" class="textarea mono" rows="4" placeholder="输入待加密内容…"></textarea>
            </div>
            <div class="field">
              <label>AES 密钥（加密 / 解密时使用）</label>
              <input v-model="crKey" class="input mono" placeholder="16 位密钥" />
            </div>
            <div class="flex" style="flex-wrap: wrap; gap: 6px">
              <button class="btn btn-primary btn-sm" @click="doHash('MD5')">MD5</button>
              <button class="btn btn-ghost btn-sm" @click="doHash('SHA1')">SHA1</button>
              <button class="btn btn-ghost btn-sm" @click="doHash('SHA256')">SHA256</button>
              <button class="btn btn-ghost btn-sm" @click="doHash('SHA512')">SHA512</button>
              <button class="btn btn-ghost btn-sm" @click="aesEnc">AES 加密</button>
              <button class="btn btn-ghost btn-sm" @click="aesDec">AES 解密</button>
              <button class="btn btn-ghost btn-sm" @click="hmacSign">HMAC 签名</button>
            </div>
            <div class="field mt-16">
              <label>结果</label>
              <textarea v-model="crOut" class="textarea mono" rows="4" readonly></textarea>
            </div>
            <button class="btn btn-ghost btn-sm" @click="crCopy">📋 复制结果</button>
          </div>
          <div class="card">
            <div class="card-title">🔓 JWT 解码</div>
            <div class="field">
              <label>JWT Token</label>
              <textarea v-model="jwtIn" class="textarea mono" rows="5" placeholder="eyJhbGciOi…"></textarea>
            </div>
            <button class="btn btn-primary btn-sm" @click="jwtDec">解码 JWT</button>
            <div class="code-block mt-16" style="min-height: 120px; white-space: pre-wrap">{{ jwtOut }}</div>
            <div class="banner banner-warn mt-8" style="margin-bottom: 0">
              ⚠️ JWT 解码仅做 Base64 还原，不验证签名；请勿在工具中粘贴生产 Token。
            </div>
          </div>
        </div>
      </template>

      <!-- ============ 字符工具 ============ -->
      <template v-if="tab === 'string'">
        <div class="grid grid-2">
          <div class="card">
            <div class="card-title">🔤 字符处理</div>
            <div class="field">
              <label>输入文本</label>
              <textarea v-model="stIn" class="textarea mono" rows="5" placeholder="输入或粘贴文本…"></textarea>
            </div>
            <div class="flex" style="flex-wrap: wrap; gap: 6px">
              <button class="btn btn-primary btn-sm" @click="stOp('upper')">转大写</button>
              <button class="btn btn-ghost btn-sm" @click="stOp('lower')">转小写</button>
              <button class="btn btn-ghost btn-sm" @click="stOp('trim')">去首尾空格</button>
              <button class="btn btn-ghost btn-sm" @click="stOp('reverse')">反转</button>
              <button class="btn btn-ghost btn-sm" @click="stOp('count')">字数统计</button>
              <button class="btn btn-ghost btn-sm" @click="stOp('regex')">正则测试</button>
            </div>
            <div v-if="stRegexShow" class="field mt-16">
              <label>正则表达式</label>
              <div class="input-group">
                <input v-model="stRegex" class="input mono" placeholder="\\d+" />
                <button class="btn btn-primary" @click="stRegexGo">匹配</button>
              </div>
            </div>
            <div class="field">
              <label>输出</label>
              <textarea v-model="stOut" class="textarea mono" rows="5" readonly></textarea>
            </div>
            <button class="btn btn-ghost btn-sm" @click="stCopy">📋 复制结果</button>
          </div>
          <div class="card">
            <div class="card-title">📐 文本对比（Diff）</div>
            <div class="field">
              <label>原文 A</label>
              <textarea v-model="stDiffA" class="textarea mono" rows="4"></textarea>
            </div>
            <div class="field">
              <label>文本 B</label>
              <textarea v-model="stDiffB" class="textarea mono" rows="4"></textarea>
            </div>
            <button class="btn btn-primary btn-sm" @click="stDiffGo">🔍 对比</button>
            <div class="code-block mt-16" style="white-space: pre-wrap">{{ stDiffOut }}</div>
          </div>
        </div>
      </template>

      <!-- ============ JSON 工具 ============ -->
      <template v-if="tab === 'json'">
        <div class="grid grid-2">
          <div class="card">
            <div class="card-title">🧾 JSON 处理</div>
            <div class="field">
              <label>输入 JSON</label>
              <textarea
                v-model="jsIn"
                class="textarea mono"
                rows="8"
                placeholder='{"code":0,"data":{"list":[1,2,3]}}'
              ></textarea>
            </div>
            <div class="flex" style="flex-wrap: wrap; gap: 6px">
              <button class="btn btn-primary btn-sm" @click="jsFmt">格式化</button>
              <button class="btn btn-ghost btn-sm" @click="jsMin">压缩</button>
              <button class="btn btn-ghost btn-sm" @click="jsValidate">校验</button>
              <button class="btn btn-ghost btn-sm" @click="jsXml">转 XML</button>
              <button class="btn btn-ghost btn-sm" @click="jsYaml">转 YAML</button>
              <button class="btn btn-ghost btn-sm" @click="jsCsv">转 CSV</button>
            </div>
            <div class="field mt-16">
              <label>JSONPath 查询</label>
              <div class="input-group">
                <input v-model="jsPath" class="input mono" placeholder="$.data.list[0]" />
                <button class="btn btn-primary" @click="jsPathGo">查询</button>
              </div>
            </div>
          </div>
          <div class="card">
            <div class="card-title">输出</div>
            <div class="code-block" style="min-height: 300px; white-space: pre-wrap">{{ jsOut }}</div>
          </div>
        </div>
      </template>

      <!-- ============ Crontab 工具 ============ -->
      <template v-if="tab === 'crontab'">
        <div class="grid grid-2">
          <div class="card">
            <div class="card-title">⏰ Crontab 表达式</div>
            <div class="field">
              <label>表达式</label>
              <input v-model="ctIn" class="input mono" placeholder="分 时 日 月 周" />
            </div>
            <div class="flex" style="flex-wrap: wrap; gap: 6px">
              <button class="btn btn-primary btn-sm" :disabled="ctLoading" @click="ctParse">
                <span v-if="ctLoading" class="spinner"></span> 解析
              </button>
              <button class="btn btn-ghost btn-sm" :disabled="ctLoading" @click="ctNext">下次执行时间</button>
              <button class="btn btn-ghost btn-sm" @click="ctFill('0 2 * * *')">每日 2 点</button>
              <button class="btn btn-ghost btn-sm" @click="ctFill('0 */4 * * *')">每 4 小时</button>
              <button class="btn btn-ghost btn-sm" @click="ctFill('30 3 * * 1')">每周一 3:30</button>
            </div>
            <div class="code-block mt-16" style="white-space: pre-wrap">{{ ctOut }}</div>
            <div class="mt-8">
              <RouterLink class="btn btn-ghost btn-sm" to="/t/tool-app-automation?tab=timer">
                ⏰ 去定时任务模块使用 →
              </RouterLink>
            </div>
          </div>
          <div class="card">
            <div class="card-title">📖 常用表达式参考</div>
            <div class="table-wrap" style="border: none">
              <table class="table">
                <thead>
                  <tr><th>表达式</th><th>含义</th></tr>
                </thead>
                <tbody>
                  <tr><td class="mono">0 2 * * *</td><td>每天凌晨 2:00</td></tr>
                  <tr><td class="mono">*/30 * * * *</td><td>每 30 分钟</td></tr>
                  <tr><td class="mono">0 0 1 * *</td><td>每月 1 号 0:00</td></tr>
                  <tr><td class="mono">0 9-18 * * 1-5</td><td>工作日 9-18 点整点</td></tr>
                  <tr><td class="mono">0 3 * * 0</td><td>每周日 3:00</td></tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </template>
    </template>
  </ModuleShell>
</template>
