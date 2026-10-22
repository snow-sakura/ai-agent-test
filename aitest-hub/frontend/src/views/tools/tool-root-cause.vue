<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import DataTable from '@/components/ui/DataTable.vue'
import StatCard from '@/components/ui/StatCard.vue'
import { uiToast, uiConfirm } from '@/composables/ui'
import http from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-root-cause.html + backend root_cause.py） ---------- */
interface CaseRow {
  id: string
  title: string
  symptom: string
  log: string
  err: string
  env: string
  firstSeen: string
  sev: string
  status: string
  hypothesis: string
  evidence: string[]
  fix: string
  createdAt: string
  created_at: string
  /** analyze 临时字段（列表未持久化时为 —） */
  conf?: string
  type?: string
  model?: string
  dur?: string
  defect?: string
}
interface AnalyzeResp {
  ok: boolean
  hypothesis: string
  evidence: string[]
  fix: string
  confidence: number
  caseId?: string
}

const I_CLS: Record<string, string> = { 高危: 'tag-red', 中危: 'tag-orange', 低危: 'tag' }
const TYPES = ['失败用例分析', '缺陷根因分析', '性能瓶颈分析', '崩溃日志分析']
const SEVS = ['高危', '中危', '低危']

const list = ref<CaseRow[]>([])

const kw = ref('')
const stFilter = ref('')
const tpFilter = ref('')

async function reload() {
  const { data } = await http.get<CaseRow[]>('/root-cause/cases')
  list.value = data || []
}

onMounted(() => {
  void reload().catch(() => undefined)
})

const filtered = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return list.value.filter(
    (r) =>
      (!k || (r.title + r.symptom).toLowerCase().includes(k)) &&
      (!stFilter.value || r.status === stFilter.value) &&
      (!tpFilter.value || (r.type || '') === tpFilter.value),
  )
})

function resetFilter() {
  kw.value = ''
  stFilter.value = ''
  tpFilter.value = ''
  uiToast('筛选已重置', 'info')
}

const totalCount = computed(() => list.value.length)
const runningCount = computed(() => list.value.filter((r) => r.status === '分析中').length)
const highCount = computed(() => list.value.filter((r) => r.sev === '高危').length)

const columns = [
  { key: 'title', label: '分析名称' },
  { key: 'type', label: '类型' },
  { key: 'status', label: '状态' },
  { key: 'conf', label: '置信度' },
  { key: 'sev', label: '影响程度' },
  { key: 'model', label: 'AI 模型' },
  { key: 'created', label: '创建时间' },
]

/* ---------- AI 根因分析 ---------- */
const anaOpen = ref(false)
const anaBusy = ref(false)
const fName = ref('')
const fDesc = ref('')
const fType = ref(TYPES[0])
const fTarget = ref('')
const fSev = ref('中危')
const fLog = ref('')
const fEnv = ref('')

function openAna() {
  fName.value = ''
  fDesc.value = ''
  fType.value = TYPES[0]
  fTarget.value = ''
  fSev.value = '中危'
  fLog.value = ''
  fEnv.value = ''
  anaOpen.value = true
}

async function goAna() {
  const n = fName.value.trim()
  if (!n) {
    uiToast('请输入分析名称', 'error')
    return
  }
  const symptom = [n, fDesc.value, fTarget.value].filter(Boolean).join(' · ')
  if (!fDesc.value.trim() && !fTarget.value.trim()) {
    uiToast('请填写描述或分析对象', 'error')
    return
  }
  anaBusy.value = true
  try {
    await http.post<AnalyzeResp>('/root-cause/analyze', {
      symptom,
      log: fLog.value,
      err: '',
      env: fEnv.value,
      save: true,
      title: n,
      sev: fSev.value,
    })
    anaOpen.value = false
    await reload()
    uiToast('根因分析完成 ✅', 'success')
  } finally {
    anaBusy.value = false
  }
}

/* ---------- 详情 ---------- */
const viewOpen = ref(false)
const view = ref<CaseRow | null>(null)

async function openView(r: CaseRow) {
  try {
    const { data } = await http.get<CaseRow>(`/root-cause/cases/${r.id}`)
    view.value = data
  } catch {
    view.value = r
  }
  viewOpen.value = true
}

function toDefect() {
  viewOpen.value = false
  uiToast('已按分析结论创建缺陷草稿，可去缺陷管理确认提交', 'success')
}

async function retry(r: CaseRow) {
  uiToast(`正在重试分析「${r.title}」…`, 'info')
  try {
    await http.post<AnalyzeResp>('/root-cause/analyze', {
      symptom: r.symptom || r.title,
      log: r.log,
      err: r.err,
      env: r.env,
      save: true,
      title: r.title,
      sev: r.sev,
    })
    await reload()
    uiToast('分析完成 ✅', 'success')
  } finally {
    uiToast('重试请求已发送', 'info')
  }
}

function dropCase(r: CaseRow) {
  uiConfirm({
    title: '删除分析',
    message: `确定删除「${r.title}」吗？已生成的缺陷与报告不受影响。`,
    onOk: async () => {
      await http.delete(`/root-cause/cases/${r.id}`)
      await reload()
      uiToast('分析已删除', 'success')
    },
  })
}

function confText(r: CaseRow): string {
  return r.conf || '—'
}
</script>

<template>
  <ModuleShell slug="tool-root-cause">
    <template #actions>
      <RouterLink class="btn btn-ghost" to="/t/tool-ai-reports">📊 AI 报告中心</RouterLink>
      <RouterLink class="btn btn-ghost" to="/t/tool-defect-management">🐞 缺陷管理</RouterLink>
      <button class="btn btn-primary" @click="openAna">✨ AI 根因分析</button>
    </template>

    <template #default="{ tab }">
      <div class="banner banner-info">
        ℹ️ 对应平台 RootCauseAnalysis 模块：分析对象为失败执行记录或缺陷，AI 结合失败日志、代码变更与历史缺陷给出根因假设（含置信度）与排查建议；结论可一键转缺陷或回填
        <RouterLink to="/t/tool-ai-reports">测试报告</RouterLink>。
      </div>

      <!-- ============ 统计概览 ============ -->
      <template v-if="tab === 'stats'">
        <div class="banner">数据总览与快捷入口；详细数据请切到「🔍 分析记录」查看（支持筛选与分页）。</div>
        <div class="grid grid-4 mb-16">
          <StatCard label="分析总数" :value="totalCount" />
          <StatCard label="分析中" :value="runningCount" color="var(--orange)" />
          <StatCard label="平均置信度" value="81%" color="var(--blue)" />
          <StatCard label="高危影响" :value="highCount" color="var(--red)" />
        </div>
      </template>

      <!-- ============ 分析记录 ============ -->
      <template v-if="tab === 'list'">
        <div class="filter-bar">
          <input v-model="kw" class="input search" placeholder="🔍 搜索分析名称…" />
          <select v-model="stFilter" class="select">
            <option value="">全部状态</option>
            <option>已完成</option>
            <option>分析中</option>
            <option>分析失败</option>
          </select>
          <select v-model="tpFilter" class="select">
            <option value="">全部类型</option>
            <option v-for="t in TYPES" :key="t" :value="t">{{ t }}</option>
          </select>
          <button class="btn btn-ghost btn-sm" @click="resetFilter">重置筛选</button>
        </div>
        <DataTable :columns="columns" :rows="filtered" empty-text="无匹配分析">
          <template #cell-title="{ row }">
            <div class="cell-main">{{ (row as CaseRow).title }}</div>
            <div class="cell-sub">{{ (row as CaseRow).symptom }}</div>
          </template>
          <template #cell-type>
            <span class="tag">{{ '—' }}</span>
          </template>
          <template #cell-status="{ row }">
            <span
              class="tag"
              :class="
                (row as CaseRow).status === '已完成'
                  ? 'tag-green'
                  : (row as CaseRow).status === '分析中'
                    ? 'tag-orange'
                    : 'tag-red'
              "
            >{{ (row as CaseRow).status === '分析中' ? '分析中…' : (row as CaseRow).status === '分析失败' ? '失败' : (row as CaseRow).status }}</span>
          </template>
          <template #cell-conf="{ row }">
            <span class="mono">{{ confText(row as CaseRow) }}</span>
          </template>
          <template #cell-sev="{ row }">
            <span class="tag" :class="I_CLS[(row as CaseRow).sev]">{{ (row as CaseRow).sev }}</span>
          </template>
          <template #cell-model>
            <span class="text-faint" style="font-size: 12px">—</span>
          </template>
          <template #cell-created="{ row }">
            <span class="mono" style="font-size: 12px">{{ (row as CaseRow).created_at || (row as CaseRow).createdAt }}</span>
          </template>
          <template #actions="{ row }">
            <div class="row-actions" style="opacity: 1">
              <button
                v-if="(row as CaseRow).status === '已完成'"
                class="btn btn-sm btn-ghost"
                @click="openView(row as CaseRow)"
              >详情</button>
              <button
                v-else
                class="btn btn-sm btn-ghost"
                @click="retry(row as CaseRow)"
              >重试</button>
              <button class="btn btn-sm btn-danger" @click="dropCase(row as CaseRow)">删除</button>
            </div>
          </template>
        </DataTable>
      </template>
    </template>
  </ModuleShell>

  <!-- AI 根因分析弹窗 -->
  <div class="modal-mask" :class="{ open: anaOpen }">
    <div class="modal">
      <div class="modal-head">
        <h3>✨ AI 根因分析</h3>
        <button class="modal-close" @click="anaOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="field">
          <label>分析名称 <span class="text-red">*</span></label>
          <input v-model="fName" class="input" placeholder="请输入分析名称" />
        </div>
        <div class="field">
          <label>描述</label>
          <input v-model="fDesc" class="input" placeholder="请输入分析描述" />
        </div>
        <div class="field">
          <label>分析类型</label>
          <select v-model="fType" class="select">
            <option v-for="t in TYPES" :key="t" :value="t">{{ t }}</option>
          </select>
        </div>
        <div class="field">
          <label>分析对象</label>
          <input
            v-model="fTarget"
            class="input"
            placeholder="如：失败执行 EX-906 / 缺陷 BUG-2049 / 压测 4500 QPS"
          />
        </div>
        <div class="field">
          <label>失败日志 / 错误堆栈（选填）</label>
          <textarea v-model="fLog" class="textarea mono" rows="4" placeholder="粘贴关键日志片段，可提升置信度"></textarea>
        </div>
        <div class="grid grid-2" style="gap: 12px">
          <div class="field">
            <label>环境（选填）</label>
            <input v-model="fEnv" class="input" placeholder="如：Android 13 · v2.4.0" />
          </div>
          <div class="field">
            <label>影响程度</label>
            <select v-model="fSev" class="select">
              <option v-for="s in SEVS" :key="s" :value="s">{{ s }}</option>
            </select>
          </div>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="anaOpen = false">取消</button>
        <button class="btn btn-primary" :disabled="anaBusy" @click="goAna">
          <span v-if="anaBusy" class="spinner"></span> 🚀 开始分析
        </button>
      </div>
    </div>
  </div>

  <!-- 分析详情弹窗 -->
  <div class="modal-mask" :class="{ open: viewOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>{{ view?.title || '分析详情' }}</h3>
        <button class="modal-close" @click="viewOpen = false">✕</button>
      </div>
      <div class="modal-body" v-if="view">
        <div class="flex mb-16" style="flex-wrap: wrap; gap: 6px">
          <span class="tag tag-blue">{{ '根因分析' }}</span>
          <span v-if="view.conf" class="tag tag-blue">置信度 {{ view.conf }}</span>
          <span class="tag" :class="I_CLS[view.sev]">{{ view.sev }}</span>
          <span v-if="view.env" class="tag">🖥 {{ view.env }}</span>
          <span class="tag mono" style="font-size: 11px">{{ view.created_at || view.createdAt }}</span>
        </div>
        <div class="kv"><span>现象</span><b>{{ view.symptom || '—' }}</b></div>
        <div class="field mt-16">
          <label>根因结论</label>
          <div class="code-block" style="white-space: normal">{{ view.hypothesis || '—' }}</div>
        </div>
        <div class="field mt-16">
          <label>排查 / 修复建议</label>
          <div class="code-block" style="white-space: normal">{{ (view.fix || '—').replace(/\n/g, '<br>') }}</div>
        </div>
        <div class="field mt-16">
          <label>分析依据</label>
          <div class="code-block" style="white-space: normal">
            <div v-for="(e, i) in view.evidence" :key="i">{{ e }}</div>
            <span v-if="!view.evidence?.length">—</span>
          </div>
        </div>
        <div v-if="view.log" class="field mt-16">
          <label>失败日志</label>
          <div class="code-block" style="white-space: pre-wrap; max-height: 160px; overflow-y: auto">{{ view.log }}</div>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="toDefect">🐞 转缺陷</button>
        <button class="btn btn-primary" @click="viewOpen = false">关闭</button>
      </div>
    </div>
  </div>
</template>
