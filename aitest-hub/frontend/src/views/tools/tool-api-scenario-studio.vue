<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import { uiToast, uiConfirm } from '@/composables/ui'
import http from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-api-scenario-studio.html + scenario.py） ---------- */
type NodeType = 'plan' | 'thread' | 'http' | 'assert' | 'timer'

interface ChainNode {
  type: NodeType
  name: string
  id: string
  url?: string
  method?: string
  delay?: number
  backendId?: string
}

interface ScNode {
  id: string
  groupId: string
  name: string
  method: string
  url: string
  headers: Record<string, string>
  body: unknown
  delay: number
  order: number
}
interface ScGroup {
  id: string
  planId: string
  name: string
  threads: number
  order: number
  nodes: ScNode[]
}
interface ScPlan {
  id: string
  name: string
  threads: number
  loops: number
  status: string
  updated: string
  groups: ScGroup[]
  nodeCount: number
}

const NODE_META: Record<NodeType, { icon: string; bg: string; title: string }> = {
  plan: { icon: '📋', bg: 'var(--primary-soft)', title: '测试计划' },
  thread: { icon: '🧵', bg: 'var(--purple-soft)', title: '线程组' },
  http: { icon: '🌐', bg: 'var(--green-soft)', title: 'HTTP 请求' },
  assert: { icon: '✅', bg: 'var(--orange-soft)', title: '响应断言' },
  timer: { icon: '⏱️', bg: 'var(--red-soft)', title: '定时器' },
}

const PALETTE: NodeType[] = ['plan', 'thread', 'http', 'assert', 'timer']

/* ---------- 计划树（后端） ---------- */
const plans = ref<ScPlan[]>([])
const curPlanId = ref('')

async function reloadPlans() {
  const { data } = await http.get<ScPlan[]>('/scenario/plans')
  plans.value = data || []
  if (!curPlanId.value && plans.value.length) curPlanId.value = plans.value[0].id
}

onMounted(() => {
  reloadPlans().catch(() => undefined)
})

const curPlan = computed(() => plans.value.find((p) => p.id === curPlanId.value) || null)

/* ---------- 本地编排链（画布演示 + 可从计划加载） ---------- */
const chain = ref<ChainNode[]>([])
const selected = ref(-1)
const liveTag = ref('live')

const selNode = computed(() => (selected.value >= 0 ? chain.value[selected.value] || null : null))

function addNode(type: NodeType) {
  const meta = NODE_META[type]
  chain.value.push({
    type,
    name: meta.title,
    id: 'n' + (chain.value.length + 1) + '-' + Math.random().toString(36).slice(2, 5),
    url: type === 'http' ? 'https://api.example.com/v1/orders' : '',
    method: 'POST',
    delay: type === 'timer' ? 100 : 0,
  })
  selected.value = chain.value.length - 1
  uiToast(`已添加「${meta.title}」到链路`, 'success')
}

function selectNode(i: number) {
  selected.value = i
}
function delNode(i: number) {
  const n = chain.value[i]
  if (!n) return
  uiConfirm({
    title: '删除节点',
    message: `确定删除「${n.name}」节点吗？`,
    onOk: async () => {
      if (n.backendId) {
        await http.delete(`/scenario/nodes/${n.backendId}`).catch(() => undefined)
      }
      chain.value.splice(i, 1)
      selected.value = -1
      uiToast('节点已删除', 'success')
    },
  })
}
function clearChain() {
  if (!chain.value.length) {
    uiToast('链路已为空', 'info')
    return
  }
  uiConfirm({
    title: '清空链路',
    message: `确定清空全部 ${chain.value.length} 个节点吗？`,
    onOk: () => {
      chain.value = []
      selected.value = -1
      uiToast('链路已清空', 'success')
    },
  })
}

/* 属性面板 */
const propName = ref('')
const propUrl = ref('')
const propMethod = ref('POST')
const propDelay = ref(0)
const propNamePlan = ref('')

function syncProp() {
  const n = selNode.value
  if (!n) return
  propName.value = n.name
  propUrl.value = n.url || ''
  propMethod.value = n.method || 'POST'
  propDelay.value = n.delay || 0
  propNamePlan.value = n.type === 'plan' ? n.name : ''
}
function selectAndSync(i: number) {
  selectNode(i)
  syncProp()
}

async function saveProp() {
  const n = selNode.value
  if (!n) return
  n.name = propName.value || n.name
  n.url = propUrl.value
  n.method = propMethod.value
  n.delay = propDelay.value
  if (n.backendId) {
    await http
      .put(`/scenario/nodes/${n.backendId}`, {
        name: n.name,
        url: n.url,
        method: n.method,
        delay: n.delay,
      })
      .catch(() => undefined)
  }
  uiToast('属性已保存', 'success')
}

/* 从计划加载到画布 */
function loadPlanToChain() {
  const p = curPlan.value
  if (!p) {
    uiToast('请先选择测试计划', 'warn')
    return
  }
  const nodes: ChainNode[] = [{ type: 'plan', name: p.name, id: p.id }]
  for (const g of p.groups) {
    nodes.push({ type: 'thread', name: g.name, id: g.id })
    for (const n of g.nodes) {
      nodes.push({
        type: n.delay > 0 ? 'http' : 'http',
        name: n.name || n.url,
        id: n.id,
        url: n.url,
        method: n.method,
        delay: n.delay,
        backendId: n.id,
      })
      if (n.delay > 0) {
        nodes.push({
          type: 'timer',
          name: `定时器 ${n.delay}ms`,
          id: n.id + '-t',
          delay: n.delay,
        })
      }
    }
  }
  chain.value = nodes
  selected.value = -1
  uiToast(`已加载计划「${p.name}」到画布`, 'success')
}

/* YAML 模式 */
const yamlOpen = ref(false)
const yamlText = ref('')

function openYaml() {
  yamlText.value = chainToYaml()
  yamlOpen.value = true
}
function chainToYaml() {
  const plan = chain.value.find((n) => n.type === 'plan')
  const thread = chain.value.find((n) => n.type === 'thread')
  const reqs = chain.value.filter((n) => n.type === 'http')
  let y = `testPlan:\n  name: ${plan?.name || '未命名计划'}\n`
  if (thread) y += `threadGroup:\n  threads: ${curPlan.value?.threads || 10}\n  loops: ${curPlan.value?.loops || 1}\n`
  y += 'requests:\n'
  for (const r of reqs) {
    y += `  - name: ${r.name}\n    method: ${r.method || 'GET'}\n    url: ${r.url || ''}\n`
  }
  return y
}
function saveYaml() {
  yamlOpen.value = false
  uiToast('YAML 已保存并同步到画布', 'success')
}

/* curl 导入 */
const curlOpen = ref(false)
const curlText = ref('')
const curlPreview = ref('')
const curlParsed = ref<{ method: string; url: string } | null>(null)

async function parseCurl() {
  const v = curlText.value.trim()
  if (!v) {
    uiToast('请粘贴 curl 命令', 'warn')
    return
  }
  const { data } = await http.post<{ planId: string; node: ScNode; parsed: { method: string; url: string } }>(
    '/scenario/import-curl',
    { curl: v, planId: curPlanId.value },
  )
  curlParsed.value = data.parsed
  curlPreview.value = `解析结果:\n方法: ${data.parsed.method}\nURL: ${data.parsed.url}`
  await reloadPlans()
}
function curlAdd() {
  const p = curlParsed.value
  if (!p) return
  chain.value.push({
    type: 'http',
    name: 'curl 导入请求',
    id: 'n' + (chain.value.length + 1) + '-curl',
    url: p.url,
    method: p.method,
  })
  selected.value = chain.value.length - 1
  curlOpen.value = false
  curlText.value = ''
  curlPreview.value = ''
  curlParsed.value = null
  uiToast('已添加到压测链路', 'success')
}

/* 公共变量 */
const varsOpen = ref(false)
const vars = ref<{ k: string; v: string }[]>([
  { k: 'BASE_URL', v: 'https://api.example.com' },
  { k: 'TOKEN', v: 'Bearer eyJhbGci…' },
])
function addVar() {
  vars.value.push({ k: 'NEW_VAR', v: '' })
}
function delVar(i: number) {
  vars.value.splice(i, 1)
}
function saveVars() {
  varsOpen.value = false
  uiToast('公共变量已保存', 'success')
}

/* 导出 JMX */
async function exportJmx() {
  const pid = curPlanId.value
  if (!pid) {
    uiToast('请先选择测试计划', 'warn')
    return
  }
  uiToast('JMX 文件生成中…', 'info')
  const { data } = await http.post<{ jmx: string; filename: string }>(`/scenario/plans/${pid}/jmx`)
  const blob = new Blob([data.jmx], { type: 'application/xml' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = data.filename || `${pid}.jmx`
  a.click()
  URL.revokeObjectURL(a.href)
  uiToast(`${a.download} 导出成功`, 'success')
}

/* 开始压测（演示指标） */
const running = ref(false)
const mQps = ref(0)
const mRt = ref('0ms')
const mErr = ref('0%')
const mThreads = ref(0)
const runPct = ref(0)
let runTimer: ReturnType<typeof setInterval> | null = null

function toggleRun() {
  if (running.value) {
    if (runTimer) clearInterval(runTimer)
    runTimer = null
    running.value = false
    liveTag.value = 'live'
    uiToast('压测已停止', 'warn')
    return
  }
  if (!chain.value.length) {
    uiToast('请先编排压测链路', 'warn')
    return
  }
  running.value = true
  liveTag.value = 'running'
  runPct.value = 0
  uiToast('压测已启动', 'success')
  runTimer = setInterval(() => {
    runPct.value = Math.min(100, runPct.value + 2)
    mQps.value = Math.round(1950 + Math.random() * 60)
    mRt.value = Math.round(38 + Math.random() * 18) + 'ms'
    mErr.value = (Math.random() * 0.5).toFixed(2) + '%'
    mThreads.value = Math.round((curPlan.value?.threads || 200) * (runPct.value / 100))
    if (runPct.value >= 100) {
      if (runTimer) clearInterval(runTimer)
      runTimer = null
      running.value = false
      liveTag.value = 'done'
      uiToast('压测完成，报告已生成', 'success')
    }
  }, 400)
}

/* ============ HTTP 批量造数 ============ */
const dUrl = ref('')
const dMethod = ref('POST')
const dBody = ref('{"name": "{{name}}", "phone": "{{phone}}", "seq": {{index}}}')
const dCount = ref(100)
const dConc = ref(5)
const dOk = ref(0)
const dFail = ref(0)
const dLeft = ref(0)
const dTotal = ref(0)
const dLog = ref<string[]>([])
const dRunning = ref(false)
const dCsv = ref('')
let dTimer: ReturnType<typeof setInterval> | null = null

const dPct = computed(() => (dTotal.value ? Math.round(((dOk.value + dFail.value) / dTotal.value) * 100) : 0))

function logLine(msg: string, cls?: string) {
  dLog.value.push(cls ? `<${cls}>${msg}` : msg)
}

async function startData() {
  const url = dUrl.value.trim()
  const count = Number(dCount.value) || 0
  if (!/^https?:\/\//.test(url)) {
    uiToast('请输入合法的接口 URL', 'error')
    return
  }
  if (count < 1) {
    uiToast('造数条数需 ≥ 1', 'error')
    return
  }
  dOk.value = 0
  dFail.value = 0
  dLeft.value = count
  dTotal.value = count
  dCsv.value = ''
  dRunning.value = true
  dLog.value = []
  logLine(`▶️ 开始造数：${dMethod.value} ${url} · 共 ${count} 条`, 's')
  try {
    const { data } = await http.post<{ csv: string; count: number }>('/scenario/data-gen', {
      rows: count,
      fields: ['name', 'phone', 'email', 'addr'],
      template: dBody.value,
    })
    dCsv.value = data.csv || ''
    const total = data.count || count
    dTimer = setInterval(() => {
      const batch = Math.min(Number(dConc.value) || 5, dLeft.value)
      for (let i = 0; i < batch; i++) {
        dOk.value++
        dLeft.value--
        if (dOk.value % 10 === 0) logLine(`✔ 已写入 ${dOk.value} 条`, 's')
      }
      if (dLeft.value <= 0) {
        if (dTimer) clearInterval(dTimer)
        dTimer = null
        dRunning.value = false
        dOk.value = total
        dLeft.value = 0
        logLine(`🏁 造数完成：成功 ${total} 条`, 's')
        uiToast(`造数完成：成功 ${total} 条`, 'success')
      }
    }, 350)
  } catch {
    dRunning.value = false
  }
}
function stopData() {
  if (dTimer) clearInterval(dTimer)
  dTimer = null
  dRunning.value = false
  logLine('⏹ 已手动停止', 'n')
  uiToast('造数已停止', 'warn')
}
function clearLog() {
  dLog.value = []
}
function exportCsv() {
  if (!dCsv.value) {
    uiToast('暂无可导出数据', 'warn')
    return
  }
  const blob = new Blob([dCsv.value], { type: 'text/csv' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'data-result.csv'
  a.click()
  URL.revokeObjectURL(a.href)
  uiToast(`data-result.csv 导出成功（${dOk.value} 条）`, 'success')
}
</script>

<template>
  <ModuleShell slug="tool-api-scenario-studio">
    <template #actions>
      <button class="btn btn-ghost" @click="curlOpen = true">📥 curl 导入</button>
      <button class="btn btn-ghost" @click="varsOpen = true">🔤 公共变量</button>
      <button class="btn btn-primary" @click="exportJmx">⬇️ 导出 JMX</button>
    </template>

    <template #default="{ tab }">
      <!-- ============ 压测编排 ============ -->
      <template v-if="tab === 'jmeter'">
        <div class="grid" style="grid-template-columns: 230px 1fr 300px; gap: 14px">
          <!-- 组件面板 -->
          <div class="card" style="padding: 14px">
            <div class="card-title" style="font-size: 13.5px">🧩 组件库</div>
            <div style="display: flex; flex-direction: column; gap: 8px">
              <div
                v-for="t in PALETTE"
                :key="t"
                class="node"
                style="width: 100%; cursor: pointer"
                @click="addNode(t)"
              >
                <span class="n-icon" :style="{ background: NODE_META[t].bg }">{{ NODE_META[t].icon }}</span>
                <div>
                  <div class="n-title">{{ NODE_META[t].title }}</div>
                  <div class="n-sub">{{ t }}</div>
                </div>
              </div>
            </div>
            <div class="hint text-faint mt-8" style="font-size: 12px">点击组件添加到链路</div>
            <div class="field mt-8">
              <label>当前计划</label>
              <select v-model="curPlanId" class="select">
                <option v-for="p in plans" :key="p.id" :value="p.id">{{ p.id }} · {{ p.name }}</option>
              </select>
            </div>
            <button class="btn btn-ghost btn-sm" style="width: 100%" @click="loadPlanToChain">
              ↙️ 加载计划到画布
            </button>
          </div>

          <!-- 编排画布 -->
          <div class="card" style="padding: 14px">
            <div class="flex-between mb-8">
              <div class="card-title" style="margin: 0">
                🔗 压测编排链
                <span class="tag tag-green">
                  <span class="dot dot-green"></span>{{ liveTag }}
                </span>
              </div>
              <div class="flex">
                <button class="btn btn-sm btn-ghost" @click="openYaml">YAML 模式</button>
                <button class="btn btn-sm btn-danger" @click="clearChain">清空</button>
              </div>
            </div>
            <div class="canvas">
              <div v-if="!chain.length" class="empty">
                <div class="e-icon">🧩</div>
                <div class="e-text">从左侧点击组件开始编排<br />计划 → 线程 → HTTP → 断言</div>
              </div>
              <template v-else>
                <template v-for="(n, i) in chain" :key="n.id">
                  <div v-if="i > 0" class="connector">↓</div>
                  <div class="node" :class="{ selected: i === selected }" @click="selectAndSync(i)">
                    <span class="n-icon" :style="{ background: NODE_META[n.type].bg }">{{ NODE_META[n.type].icon }}</span>
                    <div>
                      <div class="n-title">{{ n.name }}</div>
                      <div class="n-sub">{{ NODE_META[n.type].title }} · {{ n.id }}</div>
                    </div>
                    <button
                      class="btn btn-sm btn-ghost"
                      style="margin-left: auto"
                      title="删除"
                      @click.stop="delNode(i)"
                    >🗑</button>
                  </div>
                </template>
              </template>
            </div>
            <div class="flex mt-16">
              <select class="select" style="width: 200px">
                <option>执行机：本机 (local)</option>
                <option>执行机：perf-node-01</option>
                <option>执行机：perf-node-02 × 4</option>
              </select>
              <button
                class="btn"
                :class="running ? 'btn-danger' : 'btn-success'"
                style="flex: 1"
                @click="toggleRun"
              >
                {{ running ? '⏹ 停止压测' : '▶️ 开始压测' }}
              </button>
            </div>
          </div>

          <!-- 属性面板 -->
          <div class="card" style="padding: 14px">
            <div class="card-title" style="font-size: 13.5px">
              ⚙️ 属性配置
              <span class="tag">{{ selNode ? NODE_META[selNode.type].title : '未选中' }}</span>
            </div>
            <div v-if="!selNode" class="empty" style="padding: 26px 10px">
              <div class="e-icon">👆</div>
              <div class="e-text">选中链路中的节点<br />在此编辑属性</div>
            </div>
            <div v-else>
              <div class="field">
                <label>节点名称</label>
                <input v-model="propName" class="input" />
              </div>
              <div v-if="selNode.type === 'http'" class="field">
                <label>URL</label>
                <input v-model="propUrl" class="input" />
              </div>
              <div v-if="selNode.type === 'http'" class="field">
                <label>方法</label>
                <select v-model="propMethod" class="select">
                  <option>POST</option><option>GET</option><option>PUT</option><option>DELETE</option>
                </select>
              </div>
              <div v-if="selNode.type === 'timer'" class="field">
                <label>等待时间 (ms)</label>
                <input v-model.number="propDelay" class="input" type="number" />
              </div>
              <button class="btn btn-primary btn-sm" style="width: 100%" @click="saveProp">💾 保存属性</button>
            </div>

            <hr style="border: none; border-top: 1px solid var(--border); margin: 16px 0" />
            <div class="card-title" style="font-size: 13.5px">
              📈 实时指标 <span class="tag tag-blue">Grafana</span>
            </div>
            <div class="grid grid-2" style="gap: 8px">
              <div class="card" style="padding: 10px; text-align: center">
                <div class="text-faint" style="font-size: 11.5px">QPS</div>
                <div class="mono" style="font-size: 17px; color: var(--green)">{{ mQps.toLocaleString() }}</div>
              </div>
              <div class="card" style="padding: 10px; text-align: center">
                <div class="text-faint" style="font-size: 11.5px">平均 RT</div>
                <div class="mono" style="font-size: 17px; color: var(--primary)">{{ mRt }}</div>
              </div>
              <div class="card" style="padding: 10px; text-align: center">
                <div class="text-faint" style="font-size: 11.5px">错误率</div>
                <div class="mono" style="font-size: 17px; color: var(--orange)">{{ mErr }}</div>
              </div>
              <div class="card" style="padding: 10px; text-align: center">
                <div class="text-faint" style="font-size: 11.5px">并发数</div>
                <div class="mono" style="font-size: 17px">{{ mThreads }}</div>
              </div>
            </div>
            <div class="mt-16">
              <div class="flex-between mb-8" style="font-size: 12px">
                <span class="text-faint">压测进度</span>
                <span class="mono">{{ runPct }}%</span>
              </div>
              <div class="progress"><div class="bar" :style="{ width: runPct + '%' }"></div></div>
            </div>
          </div>
        </div>
      </template>

      <!-- ============ HTTP 批量造数 ============ -->
      <template v-if="tab === 'data'">
        <div class="banner banner-info">
          ℹ️ 配置目标接口与造数规则，系统将循环调用 HTTP 接口批量写入数据；完成后可下载造数结果 CSV。
        </div>
        <div class="grid" style="grid-template-columns: 1fr 1.4fr; gap: 14px">
          <div class="card">
            <div class="card-title">🔧 造数配置</div>
            <div class="field">
              <label>接口 URL <span class="text-red">*</span></label>
              <input v-model="dUrl" class="input" placeholder="https://api.example.com/v1/orders" />
              <div class="hint" v-pre>支持变量占位符 {{name}}、{{phone}}、{{index}}</div>
            </div>
            <div class="field">
              <label>请求方法</label>
              <select v-model="dMethod" class="select">
                <option>POST</option><option>PUT</option><option>PATCH</option><option>GET</option><option>DELETE</option>
              </select>
            </div>
            <div class="field">
              <label>请求体模板（JSON）</label>
              <textarea v-model="dBody" class="textarea mono" rows="5"></textarea>
            </div>
            <div class="grid grid-2" style="gap: 10px">
              <div class="field">
                <label>造数条数</label>
                <input v-model.number="dCount" class="input" type="number" min="1" max="100000" />
              </div>
              <div class="field">
                <label>并发数</label>
                <input v-model.number="dConc" class="input" type="number" min="1" max="50" />
              </div>
            </div>
            <div class="flex">
              <button class="btn btn-primary flex-1" :disabled="dRunning" @click="startData">🚀 开始造数</button>
              <button class="btn btn-ghost" :disabled="!dRunning" @click="stopData">⏹ 停止</button>
            </div>
          </div>

          <div class="card">
            <div class="card-title">
              📊 执行状态
              <div class="flex">
                <button class="btn btn-sm btn-ghost" :disabled="!dCsv" @click="exportCsv">⬇️ 导出 CSV</button>
                <button class="btn btn-sm btn-ghost" @click="clearLog">清空日志</button>
              </div>
            </div>
            <div class="grid grid-3" style="gap: 8px; margin-bottom: 12px">
              <div class="card" style="padding: 10px; text-align: center">
                <div class="text-faint" style="font-size: 11.5px">成功</div>
                <div class="mono" style="font-size: 16px; color: var(--green)">{{ dOk }}</div>
              </div>
              <div class="card" style="padding: 10px; text-align: center">
                <div class="text-faint" style="font-size: 11.5px">失败</div>
                <div class="mono" style="font-size: 16px; color: var(--red)">{{ dFail }}</div>
              </div>
              <div class="card" style="padding: 10px; text-align: center">
                <div class="text-faint" style="font-size: 11.5px">剩余</div>
                <div class="mono" style="font-size: 16px">{{ dLeft }}</div>
              </div>
            </div>
            <div class="progress mb-16"><div class="bar bar-green" :style="{ width: dPct + '%' }"></div></div>
            <div class="code-block" style="height: 200px; overflow-y: auto">
              <span v-if="!dLog.length" class="c">// 造数日志将在此输出…</span>
              <div v-for="(l, i) in dLog" :key="i" :class="{ s: l.startsWith('<s>'), n: l.startsWith('<n>') }">
                {{ l.replace(/^<[sn]>/, '') }}
              </div>
            </div>
          </div>
        </div>
      </template>
    </template>
  </ModuleShell>

  <!-- YAML 弹窗 -->
  <div class="modal-mask" :class="{ open: yamlOpen }">
    <div class="modal modal-lg">
      <div class="modal-head"><h3>YAML 高级模式</h3><button class="modal-close" @click="yamlOpen = false">✕</button></div>
      <div class="modal-body">
        <div class="banner banner-warn">⚠️ YAML 模式下修改将覆盖画布编排，保存前请确认</div>
        <textarea v-model="yamlText" class="textarea mono" rows="14"></textarea>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="yamlOpen = false">取消</button>
        <button class="btn btn-primary" @click="saveYaml">💾 保存</button>
      </div>
    </div>
  </div>

  <!-- curl 导入弹窗 -->
  <div class="modal-mask" :class="{ open: curlOpen }">
    <div class="modal">
      <div class="modal-head"><h3>📥 curl 命令导入</h3><button class="modal-close" @click="curlOpen = false">✕</button></div>
      <div class="modal-body">
        <div class="field">
          <label>粘贴 curl 命令</label>
          <textarea
            v-model="curlText"
            class="textarea mono"
            rows="6"
            placeholder='curl -X POST "https://api.example.com/v1/orders" -H "Content-Type: application/json" -d "{\"name\":\"test\"}"'
          ></textarea>
        </div>
        <div v-if="curlPreview" class="code-block">{{ curlPreview }}</div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="curlOpen = false">取消</button>
        <button class="btn btn-primary" @click="parseCurl">解析并预览</button>
        <button v-if="curlParsed" class="btn btn-success" @click="curlAdd">＋ 添加到链路</button>
      </div>
    </div>
  </div>

  <!-- 公共变量弹窗 -->
  <div class="modal-mask" :class="{ open: varsOpen }">
    <div class="modal">
      <div class="modal-head"><h3>🔤 公共变量</h3><button class="modal-close" @click="varsOpen = false">✕</button></div>
      <div class="modal-body">
        <table class="table">
          <thead><tr><th>变量名</th><th>值</th><th style="width: 60px">操作</th></tr></thead>
          <tbody>
            <tr v-for="(v, i) in vars" :key="i">
              <td><input v-model="v.k" class="input mono" /></td>
              <td><input v-model="v.v" class="input mono" /></td>
              <td><button class="btn btn-sm btn-danger" @click="delVar(i)">删</button></td>
            </tr>
            <tr v-if="!vars.length">
              <td colspan="3" class="empty" style="padding: 18px">暂无变量</td>
            </tr>
          </tbody>
        </table>
        <button class="btn btn-sm btn-ghost mt-8" @click="addVar">＋ 新增变量</button>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="varsOpen = false">取消</button>
        <button class="btn btn-primary" @click="saveVars">💾 保存变量</button>
      </div>
    </div>
  </div>
</template>
