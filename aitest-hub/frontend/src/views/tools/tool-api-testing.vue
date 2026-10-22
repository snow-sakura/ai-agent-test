<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import DataTable from '@/components/ui/DataTable.vue'
import { uiToast, uiConfirm } from '@/composables/ui'
import http from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-api-testing.html + api_suite.py） ---------- */
interface Endpoint {
  id: string
  name: string
  method: string
  url: string
  headers: Record<string, string>
  body: unknown
  assert: string[]
  assertCount: number
  status: string
  lastCode: number | null
  lastMs: number | null
  tags: string[]
  updated: string
}
interface EnvVar {
  k: string
  v: string
}
interface Env {
  id: string
  name: string
  base: string
  vars: EnvVar[]
}
interface HistItem {
  id: string
  eid: string
  env: string
  count: number
  pass: number
  fail: number
  time: string
  mode: string
}
interface RunResult {
  id: string
  name?: string
  code?: number
  ms?: number
  ok: boolean
  status?: string
}

const M_CLS: Record<string, string> = { GET: 'tag-blue', POST: 'tag-green', PUT: 'tag-orange', DELETE: 'tag-red' }

const apis = ref<Endpoint[]>([])
const envs = ref<Env[]>([])
const hist = ref<HistItem[]>([])

const kw = ref('')
const methodFilter = ref('')
const groupFilter = ref('')

async function reload() {
  const [e, v, h] = await Promise.all([
    http.get<Endpoint[]>('/api-testing/endpoints'),
    http.get<Env[]>('/api-testing/envs'),
    http.get<HistItem[]>('/api-testing/history'),
  ])
  apis.value = e.data || []
  envs.value = v.data || []
  hist.value = h.data || []
}

onMounted(() => {
  reload().catch(() => undefined)
})

const groups = computed(() => {
  const s = new Set<string>()
  apis.value.forEach((a) => a.tags.forEach((t) => s.add(t)))
  return [...s]
})

const filtered = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return apis.value.filter(
    (a) =>
      (!k || (a.name + a.url).toLowerCase().includes(k)) &&
      (!methodFilter.value || a.method === methodFilter.value) &&
      (!groupFilter.value || a.tags.includes(groupFilter.value)),
  )
})

const apiColumns = [
  { key: 'id', label: '编号' },
  { key: 'name', label: '接口' },
  { key: 'group', label: '分组' },
  { key: 'method', label: '方法' },
  { key: 'url', label: '路径' },
  { key: 'assert', label: '断言' },
  { key: 'updated', label: '更新' },
]

const histColumns = [
  { key: 'id', label: '记录' },
  { key: 'env', label: '环境' },
  { key: 'mode', label: '方式' },
  { key: 'count', label: '用例数' },
  { key: 'pass', label: '通过' },
  { key: 'fail', label: '失败' },
  { key: 'time', label: '时间' },
]

function pathOf(u: string) {
  try {
    const url = new URL(u)
    return url.pathname + url.search
  } catch {
    return u
  }
}

/* ---------- 新建 / 编辑接口 ---------- */
const epOpen = ref(false)
const editingId = ref<string | null>(null)
const fName = ref('')
const fGroup = ref('用户模块')
const fMethod = ref('POST')
const fPath = ref('')
const fHeaders = ref('{"Content-Type": "application/json"}')
const fBody = ref('')
const fAssert = ref('')

function openNewEp() {
  editingId.value = null
  fName.value = ''
  fGroup.value = groups.value[0] || '用户模块'
  fMethod.value = 'POST'
  fPath.value = ''
  fHeaders.value = '{"Content-Type": "application/json"}'
  fBody.value = ''
  fAssert.value = ''
  epOpen.value = true
}

function openEditEp(a: Endpoint) {
  editingId.value = a.id
  fName.value = a.name
  fGroup.value = a.tags[0] || '用户模块'
  fMethod.value = a.method
  fPath.value = a.url
  try {
    fHeaders.value = JSON.stringify(a.headers || {}, null, 0)
  } catch {
    fHeaders.value = '{}'
  }
  fBody.value = typeof a.body === 'string' ? a.body : a.body ? JSON.stringify(a.body) : ''
  fAssert.value = a.assert.join('\n')
  epOpen.value = true
}

async function saveEp() {
  const name = fName.value.trim()
  const path = fPath.value.trim()
  if (!name) {
    uiToast('请填写接口名称', 'error')
    return
  }
  if (!path) {
    uiToast('请填写路径', 'error')
    return
  }
  let headers: Record<string, string> = {}
  try {
    const h = JSON.parse(fHeaders.value || '{}')
    if (h && typeof h === 'object') headers = h as Record<string, string>
  } catch {
    uiToast('请求头需为合法 JSON', 'error')
    return
  }
  let body: unknown = ''
  if (fBody.value.trim()) {
    try {
      body = JSON.parse(fBody.value)
    } catch {
      body = fBody.value
    }
  }
  const assertList = fAssert.value
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
  const payload = {
    name,
    method: fMethod.value,
    url: path,
    headers,
    body,
    assertList,
    tags: [fGroup.value],
  }
  if (editingId.value) {
    await http.put(`/api-testing/endpoints/${editingId.value}`, payload)
  } else {
    await http.post('/api-testing/endpoints', payload)
  }
  epOpen.value = false
  editingId.value = null
  await reload()
  uiToast('接口已保存', 'success')
}

function dropEp(a: Endpoint) {
  uiConfirm({
    title: '删除接口',
    message: `确定删除接口「${a.name}」吗？其执行历史将保留。`,
    onOk: async () => {
      await http.delete(`/api-testing/endpoints/${a.id}`)
      await reload()
      uiToast('接口已删除', 'success')
    },
  })
}

/* ---------- 详情 ---------- */
const view = ref<Endpoint | null>(null)
const viewOpen = ref(false)
function openView(a: Endpoint) {
  view.value = a
  viewOpen.value = true
}

/* ---------- AI 生成断言 ---------- */
const aiLoading = ref(false)
async function aiAssert() {
  if (aiLoading.value) return
  aiLoading.value = true
  uiToast('AI 正在分析接口生成断言…', 'info')
  try {
    const body = fBody.value.trim() || fPath.value
    const { data } = await http.post<{ asserts: string[] }>('/api-testing/ai-assert', {
      response: body,
      expect: '',
    })
    fAssert.value = (data.asserts || []).join('\n')
    uiToast(`AI 已生成 ${data.asserts?.length || 0} 条断言，请确认后保存`, 'success')
  } finally {
    aiLoading.value = false
  }
}

/* ---------- 导入 ---------- */
const importOpen = ref(false)
const swaggerText = ref('')
async function doImport() {
  const raw = swaggerText.value.trim()
  if (!raw) {
    uiToast('请粘贴 Swagger / YApi 内容', 'warn')
    return
  }
  const { data } = await http.post<{ endpoints: Endpoint[] }>('/api-testing/ai-parse', { swagger: raw })
  const list = data.endpoints || []
  for (const e of list) {
    await http.post('/api-testing/endpoints', {
      id: e.id,
      name: e.name,
      method: e.method || 'GET',
      url: e.url,
      headers: {},
      body: '',
      assertList: [],
      tags: e.tags || ['swagger'],
    }).catch(() => undefined)
  }
  importOpen.value = false
  swaggerText.value = ''
  await reload()
  uiToast(`已导入 ${list.length} 个接口`, 'success')
}

/* ---------- 环境变量 ---------- */
const envOpen = ref(false)
const curEnvId = ref('')
const envDraft = ref<EnvVar[]>([])

function openEnv() {
  curEnvId.value = envs.value[0]?.id || ''
  syncEnvDraft()
  envOpen.value = true
}
function syncEnvDraft() {
  const cur = envs.value.find((e) => e.id === curEnvId.value)
  envDraft.value = (cur?.vars || []).map((v) => ({ ...v }))
}
function addEnvVar() {
  envDraft.value.push({ k: 'NEW_VAR', v: '' })
}
function delEnvVar(i: number) {
  envDraft.value.splice(i, 1)
}
async function saveEnv() {
  if (!curEnvId.value) {
    envOpen.value = false
    return
  }
  await http.put(`/api-testing/envs/${curEnvId.value}`, { vars: envDraft.value })
  envOpen.value = false
  await reload()
  uiToast('环境变量已保存', 'success')
}

/* ---------- 用例执行 ---------- */
const picked = ref<Record<string, boolean>>({})
const runEnv = ref('')
const runMode = ref<'串行' | '并行'>('串行')
const running = ref(false)
const rTotal = ref(0)
const rPass = ref(0)
const rFail = ref(0)
const rResults = ref<RunResult[]>([])

const pickCount = computed(() => Object.keys(picked.value).filter((k) => picked.value[k]).length)
const rRate = computed(() => (rTotal.value ? Math.round((rPass.value / rTotal.value) * 100) + '%' : '—'))
const rBar = computed(() => (pickCount.value ? Math.round((rTotal.value / pickCount.value) * 100) : 0))

async function runSuite() {
  const ids = Object.keys(picked.value).filter((k) => picked.value[k])
  if (!ids.length) {
    uiToast('请先勾选要执行的接口', 'warn')
    return
  }
  running.value = true
  rTotal.value = 0
  rPass.value = 0
  rFail.value = 0
  rResults.value = []
  uiToast(`开始${runMode.value}执行 ${ids.length} 个接口（${envName.value}）`, 'info')
  try {
    const { data } = await http.post<{
      total: number
      pass: number
      fail: number
      results: RunResult[]
    }>('/api-testing/run-batch', { ids, env: envName.value, mode: runMode.value })
    rResults.value = data.results || []
    rTotal.value = data.total || 0
    rPass.value = data.pass || 0
    rFail.value = data.fail || 0
    await reload()
    uiToast(
      `执行完成：通过 ${rPass.value} / 失败 ${rFail.value}`,
      rFail.value ? 'warn' : 'success',
    )
  } finally {
    running.value = false
  }
}

function stopSuite() {
  running.value = false
  uiToast('执行已停止', 'warn')
}

const envName = computed(() => {
  if (runEnv.value) return runEnv.value
  return envs.value[0]?.name || 'TEST'
})
</script>

<template>
  <ModuleShell slug="tool-api-testing">
    <template #actions>
      <button class="btn btn-ghost" @click="openEnv">🌍 环境变量</button>
      <button class="btn btn-ghost" @click="importOpen = true">📥 导入接口（YApi / Swagger）</button>
      <button class="btn btn-primary" @click="openNewEp">＋ 新建接口</button>
    </template>

    <template #default="{ tab }">
      <!-- ============ 接口集合 ============ -->
      <template v-if="tab === 'apis'">
        <div class="filter-bar">
          <input v-model="kw" class="input search" placeholder="🔍 搜索接口名称 / 路径" />
          <select v-model="methodFilter" class="select">
            <option value="">全部方法</option>
            <option>GET</option>
            <option>POST</option>
            <option>PUT</option>
            <option>DELETE</option>
          </select>
          <select v-model="groupFilter" class="select">
            <option value="">全部分组</option>
            <option v-for="g in groups" :key="g" :value="g">{{ g }}</option>
          </select>
        </div>
        <DataTable :columns="apiColumns" :rows="filtered" empty-text="无匹配接口">
          <template #cell-id="{ row }">
            <span class="mono">{{ (row as Endpoint).id }}</span>
          </template>
          <template #cell-name="{ row }">
            <div class="cell-main">{{ (row as Endpoint).name }}</div>
          </template>
          <template #cell-group="{ row }">
            <span class="tag">{{ (row as Endpoint).tags[0] || '—' }}</span>
          </template>
          <template #cell-method="{ row }">
            <span class="tag" :class="M_CLS[(row as Endpoint).method]">{{ (row as Endpoint).method }}</span>
          </template>
          <template #cell-url="{ row }">
            <span class="mono" style="font-size: 12px">{{ pathOf((row as Endpoint).url) }}</span>
          </template>
          <template #cell-assert="{ row }">
            <span class="mono">{{ (row as Endpoint).assertCount }} 条</span>
          </template>
          <template #cell-updated="{ row }">
            <span class="mono" style="font-size: 12px">{{ (row as Endpoint).updated }}</span>
          </template>
          <template #actions="{ row }">
            <button class="btn btn-sm btn-ghost" @click="openView(row as Endpoint)">详情</button>
            <button class="btn btn-sm btn-ghost" @click="openEditEp(row as Endpoint)">编辑</button>
            <button class="btn btn-sm btn-danger" @click="dropEp(row as Endpoint)">删除</button>
          </template>
        </DataTable>
      </template>

      <!-- ============ 用例执行 ============ -->
      <template v-if="tab === 'run'">
        <div class="grid" style="grid-template-columns: 1fr 1.4fr; gap: 14px">
          <div class="card">
            <div class="card-title">⚙️ 执行配置</div>
            <div class="field">
              <label>选择环境</label>
              <select v-model="runEnv" class="select">
                <option value="">（默认 TEST）</option>
                <option v-for="e in envs" :key="e.id" :value="e.name">{{ e.name }} · {{ e.base }}</option>
              </select>
            </div>
            <div class="field">
              <label>执行方式</label>
              <div class="flex" style="gap: 14px">
                <label class="checkbox">
                  <input v-model="runMode" type="radio" value="串行" /> 串行执行
                </label>
                <label class="checkbox">
                  <input v-model="runMode" type="radio" value="并行" /> 并行执行
                </label>
              </div>
            </div>
            <div class="field">
              <label>选择接口用例</label>
              <div
                style="border: 1px solid var(--border); border-radius: 8px; max-height: 200px; overflow-y: auto; padding: 8px"
              >
                <label
                  v-for="a in apis"
                  :key="a.id"
                  class="checkbox"
                  style="display: flex; padding: 4px 6px"
                >
                  <input v-model="picked[a.id]" type="checkbox" />
                  <span class="tag" :class="M_CLS[a.method]" style="margin-right: 6px">{{ a.method }}</span>
                  <span style="font-size: 12.5px">{{ a.name }}</span>
                </label>
              </div>
              <div class="hint">已选 <span class="text-green">{{ pickCount }}</span> 个接口</div>
            </div>
            <div class="flex">
              <button class="btn btn-primary flex-1" :disabled="running" @click="runSuite">🚀 执行选中用例</button>
              <button class="btn btn-ghost" :disabled="!running" @click="stopSuite">⏹ 停止</button>
            </div>
          </div>
          <div class="card">
            <div class="card-title">📊 执行结果</div>
            <div class="grid grid-4" style="gap: 8px; margin-bottom: 12px">
              <div class="card" style="padding: 10px; text-align: center">
                <div class="text-faint" style="font-size: 11.5px">总数</div>
                <div class="mono" style="font-size: 16px">{{ rTotal }}</div>
              </div>
              <div class="card" style="padding: 10px; text-align: center">
                <div class="text-faint" style="font-size: 11.5px">通过</div>
                <div class="mono" style="font-size: 16px; color: var(--green)">{{ rPass }}</div>
              </div>
              <div class="card" style="padding: 10px; text-align: center">
                <div class="text-faint" style="font-size: 11.5px">失败</div>
                <div class="mono" style="font-size: 16px; color: var(--red)">{{ rFail }}</div>
              </div>
              <div class="card" style="padding: 10px; text-align: center">
                <div class="text-faint" style="font-size: 11.5px">通过率</div>
                <div class="mono" style="font-size: 16px; color: var(--blue)">{{ rRate }}</div>
              </div>
            </div>
            <div class="progress mb-16">
              <div class="bar bar-green" :style="{ width: rBar + '%' }"></div>
            </div>
            <div style="display: flex; flex-direction: column; gap: 6px">
              <div v-if="!rResults.length" class="empty" style="padding: 30px">
                <div class="e-icon">▶️</div>
                <div class="e-text">选择接口后点击「执行选中用例」</div>
              </div>
              <div
                v-for="r in rResults"
                :key="r.id"
                class="flex-between"
                style="padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px; font-size: 12.5px"
              >
                <div class="flex">
                  <span class="tag" :class="M_CLS[apis.find((x) => x.id === r.id)?.method || 'GET']">{{ apis.find((x) => x.id === r.id)?.method || 'GET' }}</span>
                  <span class="mono text-faint">{{ apis.find((x) => x.id === r.id)?.url || r.id }}</span>
                </div>
                <div class="flex">
                  <span class="mono">{{ r.ms }}ms</span>
                  <span v-if="r.ok" class="tag tag-green">✅ 通过</span>
                  <span v-else class="tag tag-red">❌ 断言失败</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- ============ 执行历史 ============ -->
      <template v-if="tab === 'history'">
        <DataTable :columns="histColumns" :rows="hist" empty-text="暂无执行历史">
          <template #cell-id="{ row }">
            <span class="mono">{{ (row as HistItem).id }}</span>
          </template>
          <template #cell-env="{ row }">
            <span class="tag tag-blue">{{ (row as HistItem).env }}</span>
          </template>
          <template #cell-count="{ row }">
            <span class="mono">{{ (row as HistItem).count }}</span>
          </template>
          <template #cell-pass="{ row }">
            <span class="mono text-green">{{ (row as HistItem).pass }}</span>
          </template>
          <template #cell-fail="{ row }">
            <span class="mono text-red">{{ (row as HistItem).fail }}</span>
          </template>
          <template #cell-time="{ row }">
            <span class="mono" style="font-size: 12px">{{ (row as HistItem).time }}</span>
          </template>
          <template #actions>
            <button class="btn btn-sm btn-ghost" @click="uiToast('演示环境：报告详情页建设中', 'info')">查看报告</button>
          </template>
        </DataTable>
      </template>
    </template>
  </ModuleShell>

  <!-- 新建/编辑接口弹窗 -->
  <div class="modal-mask" :class="{ open: epOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>{{ editingId ? '编辑接口 · ' + editingId : '＋ 新建接口' }}</h3>
        <button class="modal-close" @click="epOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="grid grid-2" style="gap: 12px">
          <div class="field">
            <label>接口名称 <span class="text-red">*</span></label>
            <input v-model="fName" class="input" placeholder="如：创建订单" />
          </div>
          <div class="field">
            <label>所属分组</label>
            <select v-model="fGroup" class="select">
              <option v-for="g in groups.length ? groups : ['用户模块', '订单模块', '支付模块']" :key="g" :value="g">{{ g }}</option>
            </select>
          </div>
        </div>
        <div class="grid grid-2" style="gap: 12px">
          <div class="field">
            <label>请求方法</label>
            <select v-model="fMethod" class="select">
              <option>GET</option><option>POST</option><option>PUT</option><option>DELETE</option>
            </select>
          </div>
          <div class="field">
            <label>路径 <span class="text-red">*</span></label>
            <input v-model="fPath" class="input mono" placeholder="/v1/orders 或完整 URL" />
          </div>
        </div>
        <div class="field">
          <label>请求头（JSON）</label>
          <textarea v-model="fHeaders" class="textarea mono" rows="2"></textarea>
        </div>
        <div class="field">
          <label>请求体模板（JSON）</label>
          <textarea v-model="fBody" class="textarea mono" rows="4" placeholder='{"sku": "{{sku}}", "count": {{count}}}'></textarea>
        </div>
        <div class="field">
          <label>断言规则（每行一条）</label>
          <textarea
            v-model="fAssert"
            class="textarea mono"
            rows="3"
            placeholder="状态码 == 200&#10;$.code == 0&#10;$.data.id 非空"
          ></textarea>
          <div class="hint">支持 JSONPath 与比较运算符；点击右侧按钮让 AI 生成断言</div>
        </div>
        <button class="btn btn-ghost btn-sm" :disabled="aiLoading" @click="aiAssert">
          <span v-if="aiLoading" class="spinner"></span> 🤖 AI 生成断言
        </button>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="epOpen = false">取消</button>
        <button class="btn btn-primary" @click="saveEp">💾 保存接口</button>
      </div>
    </div>
  </div>

  <!-- 接口详情弹窗 -->
  <div class="modal-mask" :class="{ open: viewOpen }">
    <div class="modal">
      <div class="modal-head">
        <h3>{{ view ? view.id + ' · ' + view.name : '接口详情' }}</h3>
        <button class="modal-close" @click="viewOpen = false">✕</button>
      </div>
      <div class="modal-body" v-if="view">
        <div class="flex mb-16">
          <span class="tag" :class="M_CLS[view.method]">{{ view.method }}</span>
          <span class="tag">{{ view.tags[0] || '—' }}</span>
          <span class="tag">{{ view.assertCount }} 条断言</span>
        </div>
        <div class="field"><label>路径</label><div class="code-block mono">{{ view.url }}</div></div>
        <div class="field"><label>断言规则</label><div class="code-block">{{ view.assert.join('\n') || '—' }}</div></div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-primary" @click="viewOpen = false">关闭</button>
      </div>
    </div>
  </div>

  <!-- 环境变量弹窗 -->
  <div class="modal-mask" :class="{ open: envOpen }">
    <div class="modal">
      <div class="modal-head">
        <h3>🌍 环境变量</h3>
        <button class="modal-close" @click="envOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="field">
          <label>切换环境</label>
          <select v-model="curEnvId" class="select" @change="syncEnvDraft">
            <option v-for="e in envs" :key="e.id" :value="e.id">{{ e.name }}</option>
          </select>
        </div>
        <table class="table">
          <thead><tr><th>变量名</th><th>值</th><th style="width: 60px">操作</th></tr></thead>
          <tbody>
            <tr v-for="(v, i) in envDraft" :key="i">
              <td><input v-model="v.k" class="input mono" /></td>
              <td><input v-model="v.v" class="input mono" /></td>
              <td><button class="btn btn-sm btn-danger" @click="delEnvVar(i)">删</button></td>
            </tr>
            <tr v-if="!envDraft.length">
              <td colspan="3" class="empty" style="padding: 18px">暂无变量</td>
            </tr>
          </tbody>
        </table>
        <button class="btn btn-sm btn-ghost mt-8" @click="addEnvVar">＋ 新增变量</button>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="envOpen = false">取消</button>
        <button class="btn btn-primary" @click="saveEnv">💾 保存</button>
      </div>
    </div>
  </div>

  <!-- 导入接口弹窗 -->
  <div class="modal-mask" :class="{ open: importOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>📥 导入接口（YApi / Swagger）</h3>
        <button class="modal-close" @click="importOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="field">
          <label>粘贴 Swagger / OpenAPI JSON 或 YApi 导出内容</label>
          <textarea v-model="swaggerText" class="textarea mono" rows="10" placeholder='{"openapi":"3.0.0","paths":{...}}'></textarea>
          <div class="hint">系统将优先本地解析 paths 结构，失败时回退 AI 解析</div>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="importOpen = false">取消</button>
        <button class="btn btn-primary" @click="doImport">📥 解析并导入</button>
      </div>
    </div>
  </div>
</template>
