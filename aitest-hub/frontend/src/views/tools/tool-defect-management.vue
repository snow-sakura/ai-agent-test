<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import DataTable from '@/components/ui/DataTable.vue'
import StatCard from '@/components/ui/StatCard.vue'
import { uiToast, uiConfirm } from '@/composables/ui'
import http from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-defect-management.html） ---------- */
interface Bug {
  id: string
  title: string
  module: string
  sev: string
  pri: string
  env: string
  status: string
  reporter: string
  assignee: string
  case: string
  time: string
  steps: string
  actual: string
  expected: string
  attachments?: string[]
}
interface Comment {
  by: string
  text: string
  time: string
}
interface DupResult {
  found: boolean
  id?: string
  title?: string
  percent: number
}

const SEV_CLS: Record<string, string> = {
  'S0 致命': 'tag-red',
  'S1 严重': 'tag-orange',
  'S2 一般': 'tag-blue',
  'S3 轻微': 'tag',
}
const ST_CLS: Record<string, string> = {
  新建: 'tag-orange',
  处理中: 'tag-blue',
  待验证: 'tag-purple',
  已关闭: 'tag-green',
  已拒绝: 'tag',
}
// 状态流转：新建→处理中→待验证→已关闭；新建/处理中可拒绝
const NEXT: Record<string, string[]> = {
  新建: ['处理中', '已拒绝'],
  处理中: ['待验证', '已拒绝'],
  待验证: ['已关闭', '处理中'],
  已关闭: [],
  已拒绝: ['新建'],
}

const defects = ref<Bug[]>([])

async function reload() {
  const { data } = await http.get<Bug[]>('/bugs')
  defects.value = data
}

onMounted(() => {
  reload().catch(() => undefined)
})

/* ---------- 统计 ---------- */
const stNew = computed(() => defects.value.filter((d) => d.status === '新建').length)
const stFixing = computed(() => defects.value.filter((d) => d.status === '处理中').length)
const stVerify = computed(() => defects.value.filter((d) => d.status === '待验证').length)
const stClosed = computed(() => defects.value.filter((d) => d.status === '已关闭').length)

/* ---------- 列表筛选 ---------- */
const kw = ref('')
const stFilter = ref('')
const sevFilter = ref('')

const filtered = computed(() =>
  defects.value.filter((x) => {
    const k = kw.value.trim().toLowerCase()
    return (
      (!k || (x.title + x.id).toLowerCase().includes(k)) &&
      (!stFilter.value || x.status === stFilter.value) &&
      (!sevFilter.value || x.sev === sevFilter.value)
    )
  }),
)

function resetFilter() {
  kw.value = ''
  stFilter.value = ''
  sevFilter.value = ''
  uiToast('筛选已重置', 'info')
}

const listColumns = [
  { key: 'id', label: '编号' },
  { key: 'title', label: '标题' },
  { key: 'sev', label: '严重等级' },
  { key: 'status', label: '状态' },
  { key: 'assignee', label: '处理人' },
  { key: 'case', label: '关联用例' },
  { key: 'time', label: '提交时间' },
]

/* ---------- 状态看板 ---------- */
const BOARD_COLS = ['新建', '处理中', '待验证', '已关闭']
function boardCards(col: string) {
  return defects.value.filter((x) => x.status === col)
}

/* ---------- 详情 + 流转 ---------- */
const view = ref<Bug | null>(null)
const viewOpen = ref(false)
const comments = ref<Comment[]>([])
const commentText = ref('')
const flowBusy = ref(false)

async function openDetail(id: string) {
  const x = defects.value.find((d) => d.id === id)
  if (!x) return
  view.value = x
  comments.value = []
  viewOpen.value = true
  try {
    const { data } = await http.get<{ bug: Bug; comments: Comment[] }>(
      `/bugs/${encodeURIComponent(id)}`,
    )
    comments.value = data.comments || []
  } catch {
    /* http 拦截器已 toast */
  }
}

const timeline = computed(() => {
  const x = view.value
  if (!x) return []
  return [
    { by: x.reporter || '匿名', text: `提交缺陷，当前状态「${x.status}」`, time: x.time },
    ...comments.value,
  ]
})

async function persistFlow(to: string) {
  const x = view.value
  if (!x || flowBusy.value) return
  flowBusy.value = true
  try {
    const payload: Record<string, string> = { status: to }
    if (to === '处理中' && x.assignee === '未分配') payload.assignee = 'wxh'
    await http.patch(`/bugs/${encodeURIComponent(x.id)}`, payload)
    x.status = to
    if (payload.assignee) x.assignee = payload.assignee
    await reload()
    if (to === '已拒绝') {
      uiToast('缺陷已拒绝', 'warn')
      viewOpen.value = false
    } else if (to === '已关闭') {
      uiToast('缺陷已关闭 🎉', 'success')
      viewOpen.value = false
    } else {
      uiToast(`状态已流转至「${to}」`, 'success')
      await openDetail(x.id)
    }
  } finally {
    flowBusy.value = false
  }
}

function flow(to: string) {
  const x = view.value
  if (!x) return
  if (to === '已拒绝') {
    uiConfirm({
      title: '拒绝缺陷',
      message: `确定拒绝「${x.title}」吗？需说明原因。`,
      onOk: () => persistFlow('已拒绝'),
    })
  } else if (to === '已关闭') {
    uiConfirm({
      title: '关闭缺陷',
      message: `回归验证通过，确定关闭「${x.id}」吗？`,
      onOk: () => persistFlow('已关闭'),
    })
  } else {
    persistFlow(to)
  }
}

function flowCls(s: string) {
  if (s === '已关闭') return 'btn-success'
  if (s === '已拒绝') return 'btn-ghost'
  return 'btn-primary'
}

async function addComment() {
  const x = view.value
  const v = commentText.value.trim()
  if (!x) return
  if (!v) {
    uiToast('请输入备注内容', 'warn')
    return
  }
  await http.post(`/bugs/${encodeURIComponent(x.id)}/comments`, { text: v })
  commentText.value = ''
  const { data } = await http.get<{ comments: Comment[] }>(`/bugs/${encodeURIComponent(x.id)}`)
  comments.value = data.comments || []
  uiToast('备注已添加', 'success')
}

/* ---------- 提交 / 编辑缺陷 ---------- */
const dfOpen = ref(false)
const editId = ref<string | null>(null)
const fdTitle = ref('')
const fdModule = ref('支付模块')
const fdSev = ref('S2 一般')
const fdPri = ref('P2')
const fdEnv = ref('TEST')
const fdCase = ref('')
const fdSteps = ref('')
const fdActual = ref('')
const fdExpected = ref('')
/** 缺陷附件项：url 为空表示历史数据（仅文件名），非空为已真实上传的文件地址 */
interface DfAtt {
  name: string
  url: string
}

const dfFiles = ref<DfAtt[]>([])
const dfFileInput = ref<HTMLInputElement | null>(null)
const dfUploading = ref(false)
const MAX_DF_FILES = 5
const MAX_DF_SIZE = 5 * 1024 * 1024 // 单文件 5MB
const DF_ACCEPT = /\.(png|jpe?g|gif|webp|bmp|log|txt|zip|json|csv)$/i
const dupResult = ref<DupResult | null>(null)
const dupBusy = ref(false)
const MODULE_OPTS = ['支付模块', '订单模块', '用户模块', '库存模块']

function openNewBug() {
  editId.value = null
  fdTitle.value = ''
  fdSteps.value = ''
  fdActual.value = ''
  fdExpected.value = ''
  fdCase.value = ''
  fdSev.value = 'S2 一般'
  fdPri.value = 'P2'
  fdEnv.value = 'TEST'
  if (MODULE_OPTS.length) fdModule.value = MODULE_OPTS[0]
  dfFiles.value = []
  dupResult.value = null
  dfOpen.value = true
}

function openEditBug(x: Bug) {
  editId.value = x.id
  fdTitle.value = x.title
  fdModule.value = x.module
  fdSev.value = x.sev
  fdPri.value = x.pri
  fdEnv.value = x.env
  fdCase.value = x.case
  fdSteps.value = x.steps
  fdActual.value = x.actual
  fdExpected.value = x.expected
  dfFiles.value = (x.attachments || []).slice(0, MAX_DF_FILES).map(attToItem)
  dupResult.value = null
  dfOpen.value = true
}

/** attachments 中的字符串 → 显示项：URL 取文件名，纯文件名原样保留 */
function attToItem(att: string): DfAtt {
  const isUrl = att.startsWith('/')
  if (!isUrl) return { name: att, url: '' }
  try {
    const decoded = decodeURIComponent(att.split('/').pop() || att)
    // 去掉服务端追加的唯一化后缀（name-8位hex.ext）
    const m = decoded.match(/^(.+)-[0-9a-f]{8}(\.[^.]+)$/)
    return { name: m ? m[1] + m[2] : decoded, url: att }
  } catch {
    return { name: att, url: att }
  }
}

async function onDfFiles(list: FileList | null) {
  if (!list || !list.length) return
  const input = dfFileInput.value
  const picked: File[] = []
  for (const f of Array.from(list)) {
    if (dfFiles.value.length + picked.length >= MAX_DF_FILES) {
      uiToast(`附件最多 ${MAX_DF_FILES} 个`, 'warn')
      break
    }
    if (!DF_ACCEPT.test(f.name)) {
      uiToast(`不支持的附件类型：${f.name}`, 'error')
      continue
    }
    if (f.size > MAX_DF_SIZE) {
      uiToast(`${f.name} 超过 5MB 大小限制`, 'error')
      continue
    }
    picked.push(f)
  }
  if (input) input.value = '' // 允许重复选择同名文件
  if (!picked.length) return

  // 真实上传到后端落盘，成功后才进入列表
  dfUploading.value = true
  try {
    const fd = new FormData()
    picked.forEach((f) => fd.append('files', f, f.name))
    const { data } = await http.post<{ files: DfAtt[] }>('/bugs/attachments/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    dfFiles.value = [...dfFiles.value, ...(data.files || [])].slice(0, MAX_DF_FILES)
    uiToast(`已上传 ${data.files?.length || 0} 个附件`, 'success')
  } catch (err: any) {
    uiToast(err?.message || '附件上传失败', 'error')
  } finally {
    dfUploading.value = false
  }
}

async function aiDupCheck() {
  const t = fdTitle.value.trim()
  if (!t) {
    uiToast('请先填写缺陷标题', 'warn')
    return
  }
  dupBusy.value = true
  uiToast('AI 正在与历史缺陷比对…', 'info')
  try {
    const { data } = await http.post<DupResult>('/bugs/dup-check', {
      title: t,
      module: fdModule.value,
    })
    dupResult.value = data
  } finally {
    dupBusy.value = false
  }
}

async function saveBug() {
  if (dfUploading.value) {
    uiToast('附件正在上传，请稍候', 'warn')
    return
  }
  const t = fdTitle.value.trim()
  if (!t) {
    uiToast('请填写缺陷标题', 'error')
    return
  }
  if (!fdSteps.value.trim()) {
    uiToast('请填写复现步骤', 'error')
    return
  }
  const payload = {
    title: t,
    module: fdModule.value,
    sev: fdSev.value,
    pri: fdPri.value,
    env: fdEnv.value,
    case: fdCase.value,
    steps: fdSteps.value,
    actual: fdActual.value || '-',
    expected: fdExpected.value || '-',
    attachments: dfFiles.value.map((a) => a.url || a.name).slice(0, MAX_DF_FILES),
  }
  if (editId.value) {
    await http.patch(`/bugs/${encodeURIComponent(editId.value)}`, payload)
  } else {
    await http.post('/bugs', payload)
  }
  dfOpen.value = false
  await reload()
  uiToast(editId.value ? '缺陷已更新' : '缺陷已提交，等待分配处理人', 'success')
  editId.value = null
}

function deleteBug() {
  const id = editId.value
  if (!id) return
  uiConfirm({
    title: '删除缺陷',
    message: `确定删除缺陷「${fdTitle.value}」吗？`,
    danger: true,
    onOk: async () => {
      await http.delete(`/bugs/${encodeURIComponent(id)}`)
      dfOpen.value = false
      editId.value = null
      await reload()
      uiToast('缺陷已删除', 'success')
    },
  })
}

/* ---------- 导出 CSV（本地生成） ---------- */
function exportCsv() {
  if (!defects.value.length) {
    uiToast('暂无缺陷可导出', 'warn')
    return
  }
  const head = ['编号', '标题', '模块', '严重等级', '优先级', '状态', '处理人', '关联用例', '提交时间']
  const esc = (v: string) => '"' + String(v ?? '').replace(/"/g, '""') + '"'
  const lines = [
    head.map(esc).join(','),
    ...defects.value.map((x) =>
      [x.id, x.title, x.module, x.sev, x.pri, x.status, x.assignee, x.case, x.time]
        .map((v) => esc(String(v)))
        .join(','),
    ),
  ]
  const blob = new Blob(['\uFEFF' + lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'defects.csv'
  a.click()
  URL.revokeObjectURL(a.href)
  uiToast(`defects.csv 导出成功（${defects.value.length} 条）`, 'success')
}
</script>

<template>
  <ModuleShell slug="tool-defect-management">
    <template #actions>
      <RouterLink class="btn btn-ghost" to="/t/tool-case-management">🗂️ 关联用例</RouterLink>
      <button class="btn btn-ghost" @click="exportCsv">⬇️ 导出 CSV</button>
      <button class="btn btn-primary" @click="openNewBug">＋ 提交缺陷</button>
    </template>

    <template #default="{ tab }">
      <!-- 统计卡 -->
      <div class="grid grid-4 mb-16">
        <StatCard label="新增（待处理）" :value="stNew" color="var(--orange)" />
        <StatCard label="处理中" :value="stFixing" color="var(--blue)" />
        <StatCard label="待回归验证" :value="stVerify" color="var(--purple)" />
        <StatCard label="本周已关闭" :value="stClosed" color="var(--green)" />
      </div>

      <!-- ============ 缺陷列表 ============ -->
      <template v-if="tab === 'list'">
        <div class="filter-bar">
          <input v-model="kw" class="input search" placeholder="🔍 搜索标题 / 编号" />
          <select v-model="stFilter" class="select">
            <option value="">全部状态</option>
            <option>新建</option>
            <option>处理中</option>
            <option>待验证</option>
            <option>已关闭</option>
            <option>已拒绝</option>
          </select>
          <select v-model="sevFilter" class="select">
            <option value="">全部严重等级</option>
            <option>S0 致命</option>
            <option>S1 严重</option>
            <option>S2 一般</option>
            <option>S3 轻微</option>
          </select>
          <button class="btn btn-ghost btn-sm" @click="resetFilter">重置</button>
        </div>
        <DataTable :columns="listColumns" :rows="filtered" empty-text="无匹配缺陷">
          <template #cell-id="{ row }">
            <span class="mono">{{ (row as Bug).id }}</span>
          </template>
          <template #cell-title="{ row }">
            <div class="cell-main">{{ (row as Bug).title }}</div>
            <div class="cell-sub">{{ (row as Bug).reporter }} · {{ (row as Bug).env }}</div>
          </template>
          <template #cell-sev="{ row }">
            <span class="tag" :class="SEV_CLS[(row as Bug).sev]">{{ (row as Bug).sev }}</span>
          </template>
          <template #cell-status="{ row }">
            <span class="tag" :class="ST_CLS[(row as Bug).status]">{{ (row as Bug).status }}</span>
          </template>
          <template #cell-case="{ row }">
            <RouterLink
              v-if="(row as Bug).case"
              class="mono"
              to="/t/tool-case-management"
            >{{ (row as Bug).case }}</RouterLink>
            <span v-else class="text-faint">—</span>
          </template>
          <template #cell-time="{ row }">
            <span class="mono" style="font-size: 12px">{{ (row as Bug).time }}</span>
          </template>
          <template #actions="{ row }">
            <button class="btn btn-sm btn-ghost" @click="openDetail((row as Bug).id)">详情</button>
            <button class="btn btn-sm btn-ghost" @click="openEditBug(row as Bug)">编辑</button>
          </template>
        </DataTable>
      </template>

      <!-- ============ 状态看板 ============ -->
      <template v-if="tab === 'board'">
        <div class="grid grid-4">
          <div
            v-for="col in BOARD_COLS"
            :key="col"
            class="card"
            style="padding: 14px; background: var(--panel-2)"
          >
            <div class="card-title" style="font-size: 13px; margin-bottom: 10px">
              {{ col }} <span class="tag">{{ boardCards(col).length }}</span>
            </div>
            <div style="display: flex; flex-direction: column; gap: 8px">
              <template v-if="boardCards(col).length">
                <div
                  v-for="x in boardCards(col)"
                  :key="x.id"
                  class="card"
                  style="padding: 10px; cursor: pointer"
                  @click="openDetail(x.id)"
                >
                  <div style="font-size: 12.5px; font-weight: 600">{{ x.title }}</div>
                  <div class="flex mt-8">
                    <span class="tag" :class="SEV_CLS[x.sev]" style="font-size: 10.5px">{{ x.sev }}</span>
                    <span class="text-faint mono" style="font-size: 11px">{{ x.id }}</span>
                  </div>
                </div>
              </template>
              <div v-else class="text-faint" style="font-size: 12px; text-align: center; padding: 16px">空</div>
            </div>
          </div>
        </div>
      </template>
    </template>
  </ModuleShell>

  <!-- 提交/编辑缺陷弹窗 -->
  <div class="modal-mask" :class="{ open: dfOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>{{ editId ? '编辑缺陷 · ' + editId : '＋ 提交缺陷' }}</h3>
        <button class="modal-close" @click="dfOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="grid grid-2" style="gap: 12px">
          <div class="field">
            <label>缺陷标题 <span class="text-red">*</span></label>
            <input
              v-model="fdTitle"
              class="input"
              placeholder="环境+模块+现象，如：TEST·支付·支付成功但订单状态未更新"
            />
          </div>
          <div class="field">
            <label>所属模块</label>
            <select v-model="fdModule" class="select">
              <option v-for="m in MODULE_OPTS" :key="m" :value="m">{{ m }}</option>
            </select>
          </div>
        </div>
        <div class="grid grid-2" style="gap: 12px">
          <div class="field">
            <label>严重等级</label>
            <select v-model="fdSev" class="select">
              <option>S0 致命</option><option>S1 严重</option><option>S2 一般</option><option>S3 轻微</option>
            </select>
          </div>
          <div class="field">
            <label>优先级</label>
            <select v-model="fdPri" class="select">
              <option>P0</option><option>P1</option><option>P2</option><option>P3</option>
            </select>
          </div>
        </div>
        <div class="field">
          <label>复现环境</label>
          <select v-model="fdEnv" class="select">
            <option>TEST</option><option>DEV</option><option>STAGING</option><option>生产</option>
          </select>
        </div>
        <div class="field">
          <label>复现步骤 <span class="text-red">*</span></label>
          <textarea
            v-model="fdSteps"
            class="textarea"
            rows="4"
            placeholder="1. 进入…&#10;2. 点击…&#10;3. 观察…"
          ></textarea>
        </div>
        <div class="grid grid-2" style="gap: 12px">
          <div class="field"><label>实际结果</label><textarea v-model="fdActual" class="textarea" rows="2"></textarea></div>
          <div class="field"><label>期望结果</label><textarea v-model="fdExpected" class="textarea" rows="2"></textarea></div>
        </div>
        <div class="field">
          <label>关联用例</label>
          <input v-model="fdCase" class="input mono" placeholder="如：TC-1004（留空不关联）" />
        </div>
        <div class="field">
          <label>附件截图</label>
          <div
            class="card"
            style="border-style: dashed; text-align: center; padding: 14px; cursor: pointer"
            @click="dfFileInput?.click()"
          >
            <span class="text-dim" style="font-size: 12.5px">
              📎 点击上传截图 / 日志（图片、log、txt、zip、json、csv；≤ 5 个，单个 ≤ 5MB）
            </span>
          </div>
          <input
            ref="dfFileInput"
            type="file"
            class="file-input"
            multiple
            accept="image/*,.log,.txt,.zip,.json,.csv"
            @change="onDfFiles(($event.target as HTMLInputElement).files)"
          />
          <div v-if="dfUploading" class="msg" style="margin-top: 8px">
            <span class="typing-dots"><span></span><span></span><span></span></span>
            正在上传附件…
          </div>
          <div class="mt-8">
            <span
              v-for="(f, i) in dfFiles"
              :key="(f.url || f.name) + '-' + i"
              class="tag tag-blue"
              style="margin-right: 6px"
            >📎
              <a
                v-if="f.url"
                :href="f.url"
                target="_blank"
                rel="noopener"
                style="color: inherit; text-decoration: underline"
                title="点击预览附件"
              >{{ f.name }}</a>
              <template v-else>{{ f.name }}</template>
              <button
                style="background: none; border: none; color: inherit; cursor: pointer"
                @click="dfFiles.splice(i, 1)"
              >✕</button>
            </span>
          </div>
        </div>
        <button class="btn btn-ghost btn-sm" :disabled="dupBusy" @click="aiDupCheck">🤖 AI 查重检测</button>
        <div class="mt-8">
          <div v-if="dupResult && dupResult.found" class="banner banner-warn" style="margin: 0">
            ⚠️ 发现 1 条高相似缺陷：<b>{{ dupResult.id }}「{{ dupResult.title }}」</b>（相似度 {{ dupResult.percent }}%）。请确认是否为重复提交，仍可继续提交为新缺陷。
          </div>
          <div v-else-if="dupResult" class="banner banner-ok" style="margin: 0">
            ✅ 未发现重复缺陷（最高相似度 {{ dupResult.percent }}%）。
          </div>
        </div>
      </div>
      <div class="modal-foot">
        <button v-if="editId" class="btn btn-danger" @click="deleteBug">🗑 删除</button>
        <button class="btn btn-ghost" @click="dfOpen = false">取消</button>
        <button class="btn btn-primary" :disabled="dfUploading" @click="saveBug">
          {{ dfUploading ? '⏳ 附件上传中…' : '💾 ' + (editId ? '保存修改' : '提交缺陷') }}
        </button>
      </div>
    </div>
  </div>

  <!-- 缺陷详情弹窗 -->
  <div class="modal-mask" :class="{ open: viewOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>{{ view ? view.id + ' · ' + view.title : '缺陷详情' }}</h3>
        <button class="modal-close" @click="viewOpen = false">✕</button>
      </div>
      <div class="modal-body" v-if="view">
        <div class="flex mb-16">
          <span class="tag" :class="SEV_CLS[view.sev]">{{ view.sev }}</span>
          <span class="tag" :class="ST_CLS[view.status]">{{ view.status }}</span>
          <span class="tag">环境 {{ view.env }}</span>
          <span class="tag">报告人 {{ view.reporter }}</span>
          <span class="tag">处理人 {{ view.assignee }}</span>
          <RouterLink v-if="view.case" class="tag tag-blue" to="/t/tool-case-management">🔗 {{ view.case }}</RouterLink>
        </div>
        <div class="grid grid-2" style="gap: 12px">
          <div class="field"><label>复现步骤</label><div class="code-block">{{ view.steps }}</div></div>
          <div>
            <div class="field"><label>实际结果</label><div class="code-block">{{ view.actual }}</div></div>
            <div class="field"><label>期望结果</label><div class="code-block">{{ view.expected }}</div></div>
          </div>
        </div>
        <div class="card-title" style="font-size: 13.5px">💬 处理记录</div>
        <div style="display: flex; flex-direction: column; gap: 10px">
          <div
            v-for="(m, i) in timeline"
            :key="i"
            class="flex"
            style="gap: 10px; align-items: flex-start"
          >
            <span
              class="avatar"
              style="width: 26px; height: 26px; border-radius: 50%; background: linear-gradient(135deg, #e0685a, #d98e2b); display: grid; place-items: center; color: #fff; font-size: 11px; font-weight: 700"
            >{{ (m.by || '?').slice(0, 1) }}</span>
            <div>
              <div style="font-size: 13px">{{ m.text }}</div>
              <div class="text-faint" style="font-size: 11.5px">{{ m.by }} · {{ m.time }}</div>
            </div>
          </div>
        </div>
        <div class="input-group mt-16">
          <input
            v-model="commentText"
            class="input"
            placeholder="添加处理备注…"
            @keydown.enter="addComment"
          />
          <button class="btn btn-primary" @click="addComment">发送</button>
        </div>
      </div>
      <div class="modal-foot">
        <template v-if="view">
          <button
            v-for="s in NEXT[view.status] || []"
            :key="s"
            class="btn"
            :class="flowCls(s)"
            :disabled="flowBusy"
            @click="flow(s)"
          >→ {{ s }}</button>
        </template>
        <button class="btn btn-ghost" @click="viewOpen = false">关闭</button>
      </div>
    </div>
  </div>
</template>
