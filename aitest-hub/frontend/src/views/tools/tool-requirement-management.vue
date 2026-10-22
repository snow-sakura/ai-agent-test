<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import DataTable from '@/components/ui/DataTable.vue'
import StatCard from '@/components/ui/StatCard.vue'
import { uiToast, uiConfirm } from '@/composables/ui'
import http from '@/api/http'

/* ---------- 数据模型（与 UI/tool-requirement-management.html 对齐） ---------- */
interface Req {
  id: string
  title: string
  pri: string
  status: string
  src: string
  items: number
  cases: number
  perf: number
  sec: number
  defects: number
  desc: string
}
interface ParseItem {
  no: string
  text: string
  dim: string
}

const PRI_CLS: Record<string, string> = { P0: 'tag-red', P1: 'tag-orange', P2: 'tag' }
const ST_CLS: Record<string, string> = {
  待解析: 'tag-orange',
  已解析: 'tag-blue',
  已派生: 'tag-green',
  已归档: 'tag',
}
const DIM_CLS: Record<string, string> = {
  业务需求: 'tag-blue',
  边界条件: 'tag-orange',
  异常流: 'tag-purple',
  性能指标: 'tag-green',
  安全要求: 'tag-red',
}

const reqs = ref<Req[]>([])

/* ---------- 统计 ---------- */
const stTotal = computed(() => reqs.value.length)
const stItems = computed(() => reqs.value.reduce((s, r) => s + (r.items || 0), 0))
const stCases = computed(() => reqs.value.reduce((s, r) => s + (r.cases || 0), 0))
const stRisk = computed(
  () => reqs.value.filter((r) => r.status !== '已归档' && !r.cases).length,
)

/* ---------- 列表筛选 ---------- */
const kw = ref('')
const stFilter = ref('')
const priFilter = ref('')

const filtered = computed(() =>
  reqs.value.filter((r) => {
    const k = kw.value.trim().toLowerCase()
    return (
      (!k || (r.id + r.title).toLowerCase().includes(k)) &&
      (!stFilter.value || r.status === stFilter.value) &&
      (!priFilter.value || r.pri === priFilter.value)
    )
  }),
)

function resetFilter() {
  kw.value = ''
  stFilter.value = ''
  priFilter.value = ''
  uiToast('筛选已重置', 'info')
}

/* 追溯矩阵搜索：按需求编号 / 标题 / 覆盖结论过滤 */
const traceKw = ref('')
const filteredTrace = computed(() => {
  const q = traceKw.value.trim().toLowerCase()
  if (!q) return reqs.value
  return reqs.value.filter((r) => {
    const cover = r.cases > 0 ? '已覆盖' : r.status === '已归档' ? '已归档' : '覆盖遗漏'
    return (r.id + r.title + cover).toLowerCase().includes(q)
  })
})

async function reload() {
  const { data } = await http.get<Req[]>('/requirements')
  reqs.value = data
}

onMounted(() => {
  reload().catch(() => undefined)
})

/* ---------- 列表操作 ---------- */
const listColumns = [
  { key: 'id', label: '编号' },
  { key: 'title', label: '需求' },
  { key: 'pri', label: '优先级' },
  { key: 'status', label: '状态' },
  { key: 'items', label: '条目' },
  { key: 'cases', label: '用例' },
  { key: 'perf', label: '压测' },
  { key: 'sec', label: '安全项' },
]

function viewReq(r: Req) {
  view.value = r
  viewOpen.value = true
}

async function parseReq(r: Req) {
  uiToast(`AI 正在解析「${r.title}」…`, 'info')
  await http.post(`/requirements/${encodeURIComponent(r.id)}/parse`, {})
  await reload()
  uiToast(`解析完成：${r.id} 已更新需求条目`, 'success')
}

function archiveReq(r: Req) {
  uiConfirm({
    title: '归档需求',
    message: `确定归档「${r.title}」吗？归档后不再纳入覆盖统计，关联资产保留。`,
    onOk: async () => {
      await http.post(`/requirements/${encodeURIComponent(r.id)}/archive`, {})
      await reload()
      uiToast('需求已归档', 'success')
    },
  })
}

/* ---------- 详情 / 派生 ---------- */
const view = ref<Req | null>(null)
const viewOpen = ref(false)

async function derive(type: 'case' | 'perf' | 'sec') {
  const r = view.value
  if (!r) return
  const label = { case: 'AI 生成用例', perf: '压测场景', sec: '安全测试项' }[type]
  uiToast(`正在为「${r.title}」派生${label}…`, 'info')
  await http.post(`/requirements/${encodeURIComponent(r.id)}/derive`, { type })
  await reload()
  viewOpen.value = false
  uiToast('派生成功！可在对应模块查看，追溯矩阵已更新', 'success')
}

/* ---------- 新建需求 ---------- */
const createOpen = ref(false)
const frNo = ref('')
const frPri = ref('P0')
const frTitle = ref('')
const frDesc = ref('')
const frSrc = ref('产品 PRD')

async function saveReq() {
  const t = frTitle.value.trim()
  if (!t) {
    uiToast('请填写需求标题', 'error')
    return
  }
  await http.post('/requirements', {
    title: t,
    pri: frPri.value,
    src: frSrc.value,
    desc: frDesc.value,
    id: frNo.value.trim(),
  })
  createOpen.value = false
  frTitle.value = ''
  frDesc.value = ''
  frNo.value = ''
  await reload()
  uiToast('需求已创建，可上传文档进行 AI 解析', 'success')
}

/* ---------- 追溯矩阵 ---------- */
const traceColumns = [
  { key: 'title', label: '需求' },
  { key: 'cases', label: '用例覆盖' },
  { key: 'defects', label: '缺陷' },
  { key: 'perf', label: '压测' },
  { key: 'sec', label: '安全' },
  { key: 'status', label: '覆盖结论' },
]

/* ---------- AI 需求解析 ---------- */
/** 已选需求文档（保留 File 对象，解析时真实上传正文给后端） */
const docs = ref<File[]>([])
const MAX_DOC_SIZE = 5 * 1024 * 1024 // 与后端 5MB 限制一致
/** 可解析的文档扩展名白名单（与 accept / 后端 _extract_doc_text 保持一致） */
const DOC_EXTS = [
  'txt', 'md', 'markdown', 'csv', 'json', 'log', 'yml', 'yaml', 'xml',
  'html', 'htm', 'docx', 'xlsx', 'xlsm', 'sql', 'py', 'js', 'ts', 'vue',
  'java', 'properties', 'ini', 'conf', 'text', 'rtf', 'pdf', 'doc',
]
const aiModel = ref('DeepSeek-V3')
const dims = ref<string[]>(['业务需求', '边界条件'])
/** 解析页签当前关联的需求编号（首次派生时落库，后续条目复用） */
const parseReqId = ref('')
const DIM_OPTS = ['业务需求', '边界条件', '异常流', '性能指标', '安全要求']
const MODEL_OPTS = ['DeepSeek-V3', '通义千问-Max', '硅基流动 · GLM-4', 'GPT-4o']
const parsing = ref(false)
const parseItems = ref<ParseItem[]>([])
const parseBusy = ref(false)
const docInput = ref<HTMLInputElement | null>(null)

function pickDocs() {
  docInput.value?.click()
}

function addDocs(list: FileList | null) {
  if (!list || !list.length) return
  let added = 0
  let skipped = 0
  let rejectedType = ''
  for (let i = 0; i < list.length; i++) {
    const f = list[i]
    if (docs.value.length >= 5) {
      skipped++
      continue
    }
    // 类型白名单：图片/压缩包等无法解析的文件在选择时即拒绝，避免到解析才报错
    const ext = (f.name.split('.').pop() || '').toLowerCase()
    if (!DOC_EXTS.includes(ext)) {
      rejectedType = f.name
      skipped++
      continue
    }
    if (f.size > MAX_DOC_SIZE) {
      uiToast(`${f.name} 超过 5MB 限制，已跳过`, 'error')
      skipped++
      continue
    }
    docs.value.push(f)
    added++
  }
  if (added) uiToast(`已添加 ${added} 个文档`, 'success')
  if (rejectedType) {
    uiToast(
      `不支持的文件类型：${rejectedType}（支持 TXT/MD/CSV/JSON/DOCX/XLSX 等）`,
      'error',
    )
  }
  if (skipped && !rejectedType) {
    uiToast(`有 ${skipped} 个文件被跳过（上限 5 个 / 单个 5MB）`, 'warn')
  }
}

function onDocDrop(e: DragEvent) {
  e.preventDefault()
  addDocs(e.dataTransfer?.files || null)
}

function toggleDim(d: string, on: boolean) {
  if (on) {
    if (!dims.value.includes(d)) dims.value.push(d)
  } else {
    dims.value = dims.value.filter((x) => x !== d)
  }
}

function delay(ms: number) {
  return new Promise((r) => setTimeout(r, ms))
}

async function startParse() {
  if (!docs.value.length) {
    uiToast('请先上传需求文档', 'error')
    return
  }
  parsing.value = true
  parseItems.value = []
  parseBusy.value = true
  parseReqId.value = ''
  uiToast('AI 正在解析文档，提取业务需求、边界条件与异常流…', 'info')
  try {
    // 真实上传文件正文（multipart），后端提取文本后交给 AI 解析
    const fd = new FormData()
    for (const f of docs.value) fd.append('files', f, f.name)
    fd.append('model', aiModel.value)
    const { data } = await http.post<{
      items: ParseItem[]
      files?: string[]
    }>('/requirements/ai-parse-file', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
    if (data.files?.length) {
      uiToast(`已解析文档：${data.files.join('、')}`, 'success')
    }
    for (const it of data.items) {
      await delay(700)
      parseItems.value.push(it)
    }
    uiToast(`解析完成：提取 ${data.items.length} 条需求条目`, 'success')
  } catch {
    // 错误原因已由 http 全局拦截器 toast（含后端 detail），此处仅收尾加载态
  } finally {
    parsing.value = false
    parseBusy.value = false
  }
}

const itemBusy = ref(false)

async function deriveFromItem(it: ParseItem, kind: string) {
  if (itemBusy.value) return
  const tips: Record<string, string> = {
    case: '已派生测试用例并关联，见用例管理',
    perf: '已派生压测场景并关联，见性能测试',
    sec: '已派生安全测试项并关联，见安全测试',
  }
  itemBusy.value = true
  uiToast(`正在为 ${it.no} 派生${kind === 'case' ? '测试用例' : kind === 'perf' ? '压测场景' : '安全测试项'}…`, 'info')
  try {
    // 确保有承载需求（解析结果尚未落库时，用条目文本建一条轻量需求）
    let rid = parseReqId.value
    if (!rid) {
      const { data: created } = await http.post<Req>('/requirements', {
        title: (it.no ? `${it.no} ` : '') + it.text.slice(0, 40),
        pri: it.dim === '安全要求' || it.dim === '性能指标' ? 'P1' : 'P0',
        src: 'AI 解析',
        desc: it.text,
      })
      rid = created.id
      parseReqId.value = rid
    }
    // 更新需求侧派生计数/状态（与详情弹窗同一接口）
    await http.post(`/requirements/${encodeURIComponent(rid)}/derive`, { type: kind })
    // 同步创建可跳转的真实资产，保证 toast 文案可验证
    if (kind === 'case') {
      await http.post('/cases', {
        title: `${it.no} ${it.text.slice(0, 48)}`,
        module: 'AI 派生',
        pri: 'P1',
        type: it.dim === '边界条件' || it.dim === '异常流' ? '异常' : '功能',
        pre: '已登录并进入相关业务页面',
        steps: `1. 按需求条目 ${it.no} 准备前置数据\n2. 执行：${it.text.slice(0, 120)}\n3. 观察返回与界面反馈`,
        exp: `功能符合「${it.text.slice(0, 60)}」的预期描述`,
      })
    } else if (kind === 'perf') {
      await http.post('/perf/scenes', {
        name: `${it.no} ${it.text.slice(0, 36)}`,
        users: 100,
        ramp: 30,
        dur: 120,
        url: '/api/demo',
        method: 'GET',
      })
    } else if (kind === 'sec') {
      await http.post('/security/findings', {
        title: `${it.no} ${it.text.slice(0, 48)}`,
        sev: '中危',
        poc: it.text.slice(0, 200),
        status: '待处理',
      })
    }
    await reload()
    uiToast(tips[kind] || '已派生', 'success')
  } catch (e) {
    uiToast('派生失败，请稍后重试', 'error')
    console.error(e)
  } finally {
    itemBusy.value = false
  }
}

/* ---------- AI 模型配置（对接配置中心 /config/ai，Key 真实落库并全站生效） ---------- */
interface AiModelCfg {
  id: number
  name: string
  supplier: string
  model: string
  base: string
  key: string
  enabled: boolean
  default: boolean
  temperature: number
}

const cfgOpen = ref(false)
const cfgLoading = ref(false)
const cfgTesting = ref(false)
const cfgModels = ref<AiModelCfg[]>([])
const cfgForm = ref<AiModelCfg>({
  id: 0,
  name: '',
  supplier: '',
  model: '',
  base: '',
  key: '',
  enabled: true,
  default: true,
  temperature: 0.7,
})

async function openCfg() {
  cfgOpen.value = true
  cfgLoading.value = true
  try {
    const { data } = await http.get<AiModelCfg[]>('/config/ai')
    cfgModels.value = data || []
    const def = cfgModels.value.find((m) => m.default) || cfgModels.value[0]
    if (def) cfgForm.value = { ...def }
  } catch {
    uiToast('读取 AI 模型配置失败', 'error')
  } finally {
    cfgLoading.value = false
  }
}

async function saveCfg() {
  if (!cfgForm.value.model.trim() || !cfgForm.value.name.trim()) {
    uiToast('请填写模型名称与模型标识', 'error')
    return
  }
  // 未勾选默认时，至少保证有一条 default
  const items = cfgModels.value.length ? [...cfgModels.value] : [{ ...cfgForm.value }]
  const idx = items.findIndex((m) => m.id === cfgForm.value.id)
  if (idx >= 0) items[idx] = { ...cfgForm.value }
  else items.push({ ...cfgForm.value })
  if (!items.some((m) => m.default)) items[0] = { ...items[0], default: true }
  try {
    await http.put('/config/ai', { items })
    uiToast('AI 模型已保存，Key 已同步到全站 AI 服务 ✅', 'success')
    cfgOpen.value = false
  } catch {
    uiToast('保存失败', 'error')
  }
}

async function testConnection() {
  cfgTesting.value = true
  uiToast(`正在测试 ${cfgForm.value.model || cfgForm.value.name} 连通性…`, 'info')
  try {
    // 先保存再测，确保测试用的是表单里的最新 Key
    const items = cfgModels.value.length ? [...cfgModels.value] : [{ ...cfgForm.value }]
    const idx = items.findIndex((m) => m.id === cfgForm.value.id)
    if (idx >= 0) items[idx] = { ...cfgForm.value }
    else items.push({ ...cfgForm.value })
    if (!items.some((m) => m.default)) items[0] = { ...items[0], default: true }
    await http.put('/config/ai', { items })
    const { data } = await http.post<{ ok: boolean; msg: string }>('/config/ai/test')
    uiToast(data?.msg || (data?.ok ? '连接成功 ✅' : '连接失败'), data?.ok ? 'success' : 'error')
  } catch {
    uiToast('连接测试失败', 'error')
  } finally {
    cfgTesting.value = false
  }
}
</script>

<template>
  <ModuleShell slug="tool-requirement-management">
    <template #actions>
      <button class="btn btn-ghost" @click="openCfg">🤖 AI 模型配置</button>
      <button class="btn btn-primary" @click="createOpen = true">＋ 新建需求</button>
    </template>

    <template #default="{ tab }">
      <div class="banner banner-info">
        ℹ️ 参考 TestHub「AI 需求分析」能力：上传需求文档后 AI 自动解析业务需求并条目化，每条需求可一键派生测试资产，派生结果自动双向关联。
      </div>

      <!-- 统计 -->
      <div class="grid grid-4 mb-16">
        <StatCard label="需求总数" :value="stTotal" />
        <StatCard label="已解析条目" :value="stItems" color="var(--blue)" />
        <StatCard label="已派生用例" :value="stCases" color="var(--green)" />
        <StatCard label="覆盖遗漏风险" :value="stRisk" color="var(--orange)" />
      </div>

      <!-- ============ 需求列表 ============ -->
      <template v-if="tab === 'list'">
        <div class="filter-bar">
          <input v-model="kw" class="input search" placeholder="🔍 搜索需求编号 / 标题" />
          <select v-model="stFilter" class="select">
            <option value="">全部状态</option>
            <option>待解析</option>
            <option>已解析</option>
            <option>已派生</option>
            <option>已归档</option>
          </select>
          <select v-model="priFilter" class="select">
            <option value="">全部优先级</option>
            <option>P0</option>
            <option>P1</option>
            <option>P2</option>
          </select>
          <button class="btn btn-ghost btn-sm" @click="resetFilter">重置</button>
        </div>
        <DataTable
          :columns="listColumns"
          :rows="filtered"
          empty-text="无匹配需求"
        >
          <template #cell-id="{ row }">
            <span class="mono">{{ (row as Req).id }}</span>
          </template>
          <template #cell-title="{ row }">
            <div class="cell-main">{{ (row as Req).title }}</div>
            <div class="cell-sub">{{ (row as Req).src }}</div>
          </template>
          <template #cell-pri="{ row }">
            <span class="tag" :class="PRI_CLS[(row as Req).pri]">{{ (row as Req).pri }}</span>
          </template>
          <template #cell-status="{ row }">
            <span class="tag" :class="ST_CLS[(row as Req).status]">{{ (row as Req).status }}</span>
          </template>
          <template #cell-items="{ row }">
            <span class="mono">{{ (row as Req).items }}</span>
          </template>
          <template #cell-cases="{ row }">
            <RouterLink v-if="(row as Req).cases" class="mono" to="/t/tool-case-management">{{ (row as Req).cases }}</RouterLink>
            <span v-else class="mono">0</span>
          </template>
          <template #cell-perf="{ row }">
            <RouterLink v-if="(row as Req).perf" class="mono" to="/t/tool-api-scenario-studio">{{ (row as Req).perf }}</RouterLink>
            <span v-else class="mono">0</span>
          </template>
          <template #cell-sec="{ row }">
            <RouterLink v-if="(row as Req).sec" class="mono" to="/t/tool-security-testing">{{ (row as Req).sec }}</RouterLink>
            <span v-else class="mono">0</span>
          </template>
          <template #actions="{ row }">
            <button class="btn btn-sm btn-ghost" @click="viewReq(row as Req)">详情</button>
            <button
              v-if="(row as Req).status === '待解析'"
              class="btn btn-sm btn-primary"
              @click="parseReq(row as Req)"
            >AI解析</button>
            <button class="btn btn-sm btn-danger" @click="archiveReq(row as Req)">归档</button>
          </template>
        </DataTable>
      </template>

      <!-- ============ 追溯矩阵 ============ -->
      <template v-if="tab === 'trace'">
        <div class="banner banner-green">
          ✅ 需求 → 用例 → 缺陷全链路追溯；覆盖遗漏的需求行会以橙色提醒。
        </div>
        <div class="flex mb-16" style="gap: 8px">
          <input
            v-model="traceKw"
            class="input"
            style="max-width: 320px"
            placeholder="🔍 搜索需求：编号 / 标题 / 覆盖结论"
          />
        </div>
        <DataTable :columns="traceColumns" :rows="filteredTrace" empty-text="暂无需求">
          <template #cell-title="{ row }">
            <div class="cell-main">{{ (row as Req).title }}</div>
            <div class="cell-sub mono">{{ (row as Req).id }}</div>
          </template>
          <template #cell-cases="{ row }">
            <RouterLink v-if="(row as Req).cases" class="mono" to="/t/tool-case-management">{{ (row as Req).cases }} 条</RouterLink>
            <span v-else class="mono">0</span>
          </template>
          <template #cell-defects="{ row }">
            <RouterLink v-if="(row as Req).defects" class="mono" to="/t/tool-defect-management">{{ (row as Req).defects }}</RouterLink>
            <span v-else class="mono">0</span>
          </template>
          <template #cell-perf="{ row }">
            <RouterLink v-if="(row as Req).perf" class="mono" to="/t/tool-api-scenario-studio">{{ (row as Req).perf }}</RouterLink>
            <span v-else class="mono">0</span>
          </template>
          <template #cell-sec="{ row }">
            <RouterLink v-if="(row as Req).sec" class="mono" to="/t/tool-security-testing">{{ (row as Req).sec }}</RouterLink>
            <span v-else class="mono">0</span>
          </template>
          <template #cell-status="{ row }">
            <span v-if="(row as Req).cases > 0" class="tag tag-green">✅ 已覆盖</span>
            <span v-else-if="(row as Req).status === '已归档'" class="tag">已归档</span>
            <span v-else class="tag tag-orange">⚠️ 覆盖遗漏</span>
          </template>
        </DataTable>
      </template>

      <!-- ============ AI 需求解析 ============ -->
      <template v-if="tab === 'analyze'">
        <div class="grid" style="grid-template-columns: 1fr 1.3fr; gap: 14px">
          <div class="card">
            <div class="card-title">📄 上传需求文档 <span class="tag tag-red">AI</span></div>
            <div
              class="card"
              style="border-style: dashed; text-align: center; padding: 28px; cursor: pointer"
              @click="pickDocs"
              @dragover.prevent
              @drop="onDocDrop"
            >
              <div style="font-size: 30px">📄</div>
              <div class="text-dim mt-8" style="font-size: 12.5px">点击选择或拖拽文档</div>
              <div class="text-faint" style="font-size: 11.5px">
                支持 TXT / MD / CSV / JSON / DOCX / XLSX，≤ 5MB，最多 5 个
              </div>
            </div>
            <input
              ref="docInput"
              type="file"
              class="file-input"
              accept=".txt,.md,.markdown,.csv,.json,.log,.yml,.yaml,.xml,.html,.htm,.sql,.py,.js,.ts,.vue,.java,.properties,.ini,.conf,.text,.rtf,.docx,.xlsx,.xlsm,.pdf,.doc"
              multiple
              @change="addDocs(($event.target as HTMLInputElement).files)"
            />
            <div class="mt-8">
              <span
                v-for="(f, i) in docs"
                :key="f.name + i"
                class="tag tag-blue"
                style="margin-right: 6px"
              >📄 {{ f.name }}
                <button
                  style="background: none; border: none; color: inherit; cursor: pointer"
                  @click="docs.splice(i, 1)"
                >✕</button>
              </span>
            </div>
            <div class="field mt-16">
              <label>AI 模型</label>
              <select v-model="aiModel" class="select">
                <option v-for="m in MODEL_OPTS" :key="m" :value="m">{{ m }}</option>
              </select>
              <div class="hint">多模型支持，可在「AI 模型配置」中测试连通性</div>
            </div>
            <div class="field">
              <label>解析维度</label>
              <div class="flex" style="gap: 8px; flex-wrap: wrap">
                <label v-for="d in DIM_OPTS" :key="d" class="checkbox">
                  <input
                    type="checkbox"
                    :checked="dims.includes(d)"
                    @change="toggleDim(d, ($event.target as HTMLInputElement).checked)"
                  /> {{ d }}
                </label>
              </div>
            </div>
            <button class="btn btn-primary" style="width: 100%" :disabled="parsing" @click="startParse">
              <span v-if="parsing" class="spinner"></span>
              {{ parsing ? ' AI 解析中…' : '✨ 开始 AI 解析' }}
            </button>
          </div>

          <div class="card">
            <div class="card-title">
              🧠 解析结果（条目化） <span class="tag tag-blue">{{ parseItems.length }} 条</span>
            </div>
            <div style="display: flex; flex-direction: column; gap: 8px; max-height: 420px; overflow-y: auto">
              <div v-if="parseBusy" class="msg ai" style="max-width: 100%">
                <div class="m-avatar">🤖</div>
                <div class="m-body">
                  <span class="typing-dots"><span></span><span></span><span></span></span>
                  {{ aiModel }} 正在解析文档，提取业务需求、边界条件与异常流…
                </div>
              </div>
              <div v-else-if="!parseItems.length" class="empty">
                <div class="e-icon">🤖</div>
                <div class="e-text">
                  上传文档并开始解析，AI 将自动提取需求条目<br />
                  每条可一键派生测试用例 / 压测场景 / 安全测试项
                </div>
              </div>
              <div
                v-for="it in parseItems"
                :key="it.no"
                class="card"
                style="padding: 12px 14px"
              >
                <div class="flex-between">
                  <div class="flex">
                    <span class="mono text-faint">{{ it.no }}</span>
                    <span class="tag" :class="DIM_CLS[it.dim] || 'tag'">{{ it.dim }}</span>
                  </div>
                  <div class="flex">
                    <button class="btn btn-sm btn-ghost" :disabled="itemBusy" @click="deriveFromItem(it, 'case')">🤖 生成用例</button>
                    <button class="btn btn-sm btn-ghost" :disabled="itemBusy" @click="deriveFromItem(it, 'perf')">🚀 压测</button>
                    <button class="btn btn-sm btn-ghost" :disabled="itemBusy" @click="deriveFromItem(it, 'sec')">🛡️ 安全</button>
                  </div>
                </div>
                <div class="mt-8" style="font-size: 13px">{{ it.text }}</div>
              </div>
            </div>
          </div>
        </div>
      </template>
    </template>
  </ModuleShell>

  <!-- 新建需求弹窗 -->
  <div class="modal-mask" :class="{ open: createOpen }">
    <div class="modal modal-lg">
      <div class="modal-head"><h3>＋ 新建需求</h3><button class="modal-close" @click="createOpen = false">✕</button></div>
      <div class="modal-body">
        <div class="grid grid-2" style="gap: 12px">
          <div class="field">
            <label>需求编号</label>
            <input v-model="frNo" class="input mono" placeholder="REQ-2026-0125（留空自动生成）" />
          </div>
          <div class="field">
            <label>优先级</label>
            <select v-model="frPri" class="select"><option>P0</option><option>P1</option><option>P2</option></select>
          </div>
        </div>
        <div class="field">
          <label>需求标题 <span class="text-red">*</span></label>
          <input v-model="frTitle" class="input" placeholder="如：订单退款功能" />
        </div>
        <div class="field">
          <label>需求描述</label>
          <textarea
            v-model="frDesc"
            class="textarea"
            rows="5"
            placeholder="粘贴需求描述，或保存后上传文档由 AI 解析…"
          ></textarea>
        </div>
        <div class="field">
          <label>需求来源</label>
          <select v-model="frSrc" class="select">
            <option>产品 PRD</option><option>蓝湖原型</option><option>用户反馈</option><option>线上缺陷反推</option>
          </select>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="createOpen = false">取消</button>
        <button class="btn btn-primary" @click="saveReq">💾 保存需求</button>
      </div>
    </div>
  </div>

  <!-- 需求详情 / 派生弹窗 -->
  <div class="modal-mask" :class="{ open: viewOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>{{ view ? view.id + ' · ' + view.title : '需求详情' }}</h3>
        <button class="modal-close" @click="viewOpen = false">✕</button>
      </div>
      <div class="modal-body" v-if="view">
        <div class="flex mb-16">
          <span class="tag" :class="PRI_CLS[view.pri]">{{ view.pri }}</span>
          <span class="tag" :class="ST_CLS[view.status]">{{ view.status }}</span>
          <span class="tag">来源 {{ view.src }}</span>
        </div>
        <div class="field">
          <label>需求描述</label>
          <div class="code-block" style="white-space: normal">{{ view.desc }}</div>
        </div>
        <div class="card-title" style="font-size: 13.5px">
          🔗 关联测试资产 <span class="tag tag-green">双向追溯</span>
        </div>
        <div style="display: flex; flex-direction: column; gap: 8px">
          <div v-if="view.cases || view.defects || view.perf || view.sec" class="flex" style="flex-wrap: wrap; gap: 6px">
            <RouterLink v-if="view.cases" class="tag tag-green" to="/t/tool-case-management">🗂️ 测试用例 {{ view.cases }} 条 →</RouterLink>
            <RouterLink v-if="view.defects" class="tag tag-red" to="/t/tool-defect-management">🐞 关联缺陷 {{ view.defects }} 个 →</RouterLink>
            <RouterLink v-if="view.perf" class="tag tag-blue" to="/t/tool-api-scenario-studio">🚀 压测场景 {{ view.perf }} 个 →</RouterLink>
            <RouterLink v-if="view.sec" class="tag tag-purple" to="/t/tool-security-testing">🛡️ 安全测试项 {{ view.sec }} 条 →</RouterLink>
          </div>
          <span v-else class="tag">暂无关联资产，可从下方一键派生</span>
        </div>
        <div class="card-title mt-16" style="font-size: 13.5px">⚡ 一键派生</div>
        <div class="grid grid-3" style="gap: 10px">
          <button
            class="card card-hover"
            style="cursor: pointer; text-align: center; padding: 14px"
            @click="derive('case')"
          >
            <div style="font-size: 22px">🤖</div><div class="mt-8" style="font-size: 13px">AI 生成用例</div>
          </button>
          <button
            class="card card-hover"
            style="cursor: pointer; text-align: center; padding: 14px"
            @click="derive('perf')"
          >
            <div style="font-size: 22px">🚀</div><div class="mt-8" style="font-size: 13px">派生压测场景</div>
          </button>
          <button
            class="card card-hover"
            style="cursor: pointer; text-align: center; padding: 14px"
            @click="derive('sec')"
          >
            <div style="font-size: 22px">🛡️</div><div class="mt-8" style="font-size: 13px">派生安全测试项</div>
          </button>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="viewOpen = false">关闭</button>
      </div>
    </div>
  </div>

  <!-- AI 模型配置弹窗（真实落库：保存后全站 AI 服务立即生效） -->
  <div class="modal-mask" :class="{ open: cfgOpen }">
    <div class="modal">
      <div class="modal-head">
        <h3>🤖 AI 模型配置</h3>
        <button class="modal-close" @click="cfgOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div v-if="cfgLoading" class="banner banner-info" style="margin: 0">⏳ 正在读取配置…</div>
        <template v-else>
          <div class="field">
            <label>模型名称</label>
            <input v-model="cfgForm.name" class="input" placeholder="如：DeepSeek-V3" />
          </div>
          <div class="field">
            <label>模型标识（Model）</label>
            <input v-model="cfgForm.model" class="input mono" placeholder="如：deepseek-chat" />
          </div>
          <div class="field">
            <label>Base URL</label>
            <input v-model="cfgForm.base" class="input mono" placeholder="https://api.deepseek.com/v1" />
          </div>
          <div class="field">
            <label>API Key</label>
            <input v-model="cfgForm.key" class="input mono" type="password" placeholder="sk-…（填入后全站 AI 功能真调）" />
          </div>
          <div class="banner banner-info" style="margin: 0">
            ℹ️ Key 保存在服务端配置中心，保存后需求解析、用例生成、报告等全站 AI 能力立即切换为真实模型；留空则继续使用演示模式。
          </div>
        </template>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" :disabled="cfgTesting || cfgLoading" @click="testConnection">🔌 测试连接</button>
        <button class="btn btn-primary" :disabled="cfgLoading" @click="saveCfg">保存</button>
      </div>
    </div>
  </div>
</template>
