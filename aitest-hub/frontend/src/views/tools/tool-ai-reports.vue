<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import DataTable from '@/components/ui/DataTable.vue'
import StatCard from '@/components/ui/StatCard.vue'
import { uiToast, uiConfirm } from '@/composables/ui'
import http from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-ai-reports.html + backend reports.py） ---------- */
interface Report {
  id: string
  name: string
  type: string
  model: string
  pass: string
  passRate: number | null
  total: number
  defects: number
  high: number
  mid: number
  low: number
  risk: string
  summary: string
  createdBy: string
  createdAt: string
  created: string
  desc: string
  status: string
  dur: string
}
interface ReportStats {
  total: number
  avgPassRate: number
  totalDefects: number
  highRisk: number
  totalCases: number
  riskDist: Array<{ risk: string; count: number }>
  typeDist: Array<{ type: string; count: number }>
}
interface ListResp {
  items: Report[]
  total: number
}

const T_CLS: Record<string, string> = {
  回归测试报告: 'tag-blue',
  冒烟测试报告: 'tag-green',
  功能测试报告: 'tag-green',
  性能测试报告: 'tag-purple',
  安全测试报告: 'tag-red',
  版本质量报告: 'tag-orange',
}
const TYPES = ['回归测试报告', '冒烟测试报告', '功能测试报告', '性能测试报告', '安全测试报告', '版本质量报告']
const MODELS = ['DeepSeek-V3', '通义千问-Max', '硅基流动 · GLM-4']
const SOURCES = ['执行记录', '缺陷数据', '需求追溯矩阵', '性能基线']

const list = ref<Report[]>([])
const stats = ref<ReportStats | null>(null)

const kw = ref('')
const stFilter = ref('')
const tpFilter = ref('')

async function reload() {
  const [l, s] = await Promise.all([
    http.get<ListResp>('/reports'),
    http.get<ReportStats>('/reports/stats').catch(() => null),
  ])
  list.value = l.data?.items || []
  stats.value = s?.data || null
}

onMounted(() => {
  void reload().catch(() => undefined)
})

const filtered = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return list.value.filter(
    (r) =>
      (!k || r.name.toLowerCase().includes(k)) &&
      (!stFilter.value || r.status === stFilter.value) &&
      (!tpFilter.value || r.type === tpFilter.value),
  )
})

function resetFilter() {
  kw.value = ''
  stFilter.value = ''
  tpFilter.value = ''
  uiToast('筛选已重置', 'info')
}

const runningCount = computed(() => list.value.filter((r) => r.status === '生成中').length)

const columns = [
  { key: 'name', label: '报告名称' },
  { key: 'type', label: '类型' },
  { key: 'status', label: '状态' },
  { key: 'pass', label: '通过率' },
  { key: 'defects', label: '缺陷数' },
  { key: 'model', label: 'AI 模型' },
  { key: 'created', label: '创建时间' },
]

/* ---------- AI 生成 ---------- */
const genOpen = ref(false)
const genBusy = ref(false)
const fName = ref('')
const fDesc = ref('')
const fType = ref(TYPES[0])
const fSources = ref(['执行记录', '缺陷数据'])
const fModel = ref(MODELS[0])
const fDeai = ref(true)

function openGen() {
  fName.value = ''
  fDesc.value = ''
  fType.value = TYPES[0]
  fSources.value = ['执行记录', '缺陷数据']
  fModel.value = MODELS[0]
  fDeai.value = true
  genOpen.value = true
}

async function genReport() {
  const n = fName.value.trim()
  if (!n) {
    uiToast('请输入报告名称', 'error')
    return
  }
  genBusy.value = true
  try {
    const scope = [n, fDesc.value, fSources.value.join('+')].filter(Boolean).join(' · ')
    await http.post('/reports/generate', {
      type: fType.value,
      scope,
      model: fModel.value,
    })
    genOpen.value = false
    await reload()
    uiToast('报告生成完成 ✅', 'success')
  } finally {
    genBusy.value = false
  }
}

/* ---------- 详情 ---------- */
const viewOpen = ref(false)
const view = ref<Report | null>(null)

function openView(r: Report) {
  view.value = r
  viewOpen.value = true
}

function exportPdf() {
  uiToast('报告 PDF 导出成功（演示）', 'success')
}

function retry(r: Report) {
  uiToast(`正在重试生成「${r.name}」…`, 'info')
  void (async () => {
    await http.post('/reports/generate', {
      type: r.type,
      scope: r.desc || r.name,
      model: r.model,
    })
    await reload()
    uiToast('报告已重新生成 ✅', 'success')
  })()
}

function dropReport(r: Report) {
  uiConfirm({
    title: '删除报告',
    message: `确定删除「${r.name}」吗？该操作不可恢复。`,
    onOk: async () => {
      await http.delete(`/reports/${r.id}`)
      await reload()
      uiToast('报告已删除', 'success')
    },
  })
}
</script>

<template>
  <ModuleShell slug="tool-ai-reports">
    <template #actions>
      <RouterLink class="btn btn-ghost" to="/t/tool-root-cause">🔍 根因分析</RouterLink>
      <button class="btn btn-primary" @click="openGen">✨ AI 生成报告</button>
    </template>

    <template #default="{ tab }">
      <div class="banner banner-info">
        ℹ️ 对应平台 AIReports 模块：报告由 AI 汇总测试执行结果与缺陷数据自动生成；生成时应用的「去 AI 味」策略与模型来自
        <RouterLink to="/t/tool-config-center">配置中心</RouterLink>，结论措辞受
        <RouterLink to="/t/tool-deai-flavor">去 AI 味中心</RouterLink>策略约束。
      </div>

      <!-- ============ 统计概览 ============ -->
      <template v-if="tab === 'stats'">
        <div class="banner">数据总览与快捷入口；详细数据请切到「📄 报告列表」查看（支持筛选与分页）。</div>
        <div class="grid grid-4 mb-16">
          <StatCard label="报告总数" :value="stats?.total ?? list.length" />
          <StatCard label="生成中" :value="runningCount" color="var(--orange)" />
          <StatCard label="平均通过率" :value="(stats?.avgPassRate ?? 0) + '%'" color="var(--green)" />
          <StatCard label="累计缺陷发现" :value="stats?.totalDefects ?? 0" color="var(--red)" />
        </div>
        <div class="grid grid-4" v-if="stats?.typeDist?.length">
          <div v-for="t in stats.typeDist" :key="t.type" class="card stat-card">
            <div class="s-label">{{ t.type }}</div>
            <div class="s-value" style="color: var(--blue)">{{ t.count }}</div>
          </div>
        </div>
      </template>

      <!-- ============ 报告列表 ============ -->
      <template v-if="tab === 'list'">
        <div class="filter-bar">
          <input v-model="kw" class="input search" placeholder="🔍 搜索报告名称…" />
          <select v-model="stFilter" class="select">
            <option value="">全部状态</option>
            <option>已生成</option>
            <option>生成中</option>
            <option>生成失败</option>
          </select>
          <select v-model="tpFilter" class="select">
            <option value="">全部类型</option>
            <option v-for="t in TYPES" :key="t" :value="t">{{ t }}</option>
          </select>
          <button class="btn btn-ghost btn-sm" @click="resetFilter">重置筛选</button>
        </div>
        <DataTable :columns="columns" :rows="filtered" empty-text="无匹配报告">
          <template #cell-name="{ row }">
            <div class="cell-main">{{ (row as Report).name }}</div>
            <div class="cell-sub">{{ (row as Report).desc }}</div>
          </template>
          <template #cell-type="{ row }">
            <span class="tag" :class="T_CLS[(row as Report).type]">{{ (row as Report).type }}</span>
          </template>
          <template #cell-status="{ row }">
            <span
              class="tag"
              :class="
                (row as Report).status === '已生成'
                  ? 'tag-green'
                  : (row as Report).status === '生成中'
                    ? 'tag-orange'
                    : 'tag-red'
              "
            >{{ (row as Report).status === '生成中' ? '生成中…' : (row as Report).status === '生成失败' ? '失败' : (row as Report).status }}</span>
          </template>
          <template #cell-pass="{ row }">
            <span class="mono">{{ (row as Report).pass }}</span>
          </template>
          <template #cell-defects="{ row }">
            <span class="mono">{{ (row as Report).defects || '—' }}</span>
          </template>
          <template #cell-model="{ row }">
            <div class="cell-sub" style="font-size: 12px">{{ (row as Report).model }}</div>
          </template>
          <template #cell-created="{ row }">
            <span class="mono" style="font-size: 12px">{{ (row as Report).created }}</span>
          </template>
          <template #actions="{ row }">
            <div class="row-actions" style="opacity: 1">
              <button
                v-if="(row as Report).status === '已生成'"
                class="btn btn-sm btn-ghost"
                @click="openView(row as Report)"
              >详情</button>
              <button
                v-else
                class="btn btn-sm btn-ghost"
                @click="retry(row as Report)"
              >重试</button>
              <button class="btn btn-sm btn-danger" @click="dropReport(row as Report)">删除</button>
            </div>
          </template>
        </DataTable>
      </template>
    </template>
  </ModuleShell>

  <!-- AI 生成报告弹窗 -->
  <div class="modal-mask" :class="{ open: genOpen }">
    <div class="modal">
      <div class="modal-head">
        <h3>✨ AI 生成报告</h3>
        <button class="modal-close" @click="genOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="field">
          <label>报告名称 <span class="text-red">*</span></label>
          <input v-model="fName" class="input" placeholder="请输入报告名称" />
        </div>
        <div class="field">
          <label>描述</label>
          <input v-model="fDesc" class="input" placeholder="请输入报告描述" />
        </div>
        <div class="field">
          <label>报告类型</label>
          <select v-model="fType" class="select">
            <option v-for="t in TYPES" :key="t" :value="t">{{ t }}</option>
          </select>
        </div>
        <div class="field">
          <label>数据来源</label>
          <div class="flex" style="gap: 8px; flex-wrap: wrap">
            <label v-for="s in SOURCES" :key="s" class="checkbox">
              <input v-model="fSources" type="checkbox" :value="s" /> {{ s }}
            </label>
          </div>
        </div>
        <div class="field">
          <label>AI 模型</label>
          <select v-model="fModel" class="select">
            <option v-for="m in MODELS" :key="m" :value="m">{{ m }}</option>
          </select>
        </div>
        <label class="checkbox">
          <input v-model="fDeai" type="checkbox" /> 应用「去 AI 味」策略（简报压缩 · 测试术语规范化）
        </label>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="genOpen = false">取消</button>
        <button class="btn btn-primary" :disabled="genBusy" @click="genReport">
          <span v-if="genBusy" class="spinner"></span> 🚀 开始生成
        </button>
      </div>
    </div>
  </div>

  <!-- 报告详情弹窗 -->
  <div class="modal-mask" :class="{ open: viewOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>{{ view?.name || '报告详情' }}</h3>
        <button class="modal-close" @click="viewOpen = false">✕</button>
      </div>
      <div class="modal-body" v-if="view">
        <div class="flex mb-16" style="flex-wrap: wrap; gap: 6px">
          <span class="tag" :class="T_CLS[view.type]">{{ view.type }}</span>
          <span class="tag tag-green">通过率 {{ view.pass }}</span>
          <span class="tag tag-red">缺陷 {{ view.defects }}</span>
          <span class="tag">🧠 {{ view.model }}</span>
          <span class="tag mono" style="font-size: 11px">{{ view.created }}</span>
          <span class="tag">⏱ {{ view.dur }}</span>
        </div>
        <div class="kv"><span>风险等级</span><b>{{ view.risk }}</b></div>
        <div class="kv">
          <span>缺陷分布</span><b>高 {{ view.high }} · 中 {{ view.mid }} · 低 {{ view.low }}</b>
        </div>
        <div class="field">
          <label>AI 报告结论</label>
          <div class="code-block" style="white-space: normal">{{ view.summary || '—' }}</div>
        </div>
        <div class="mt-16 flex" style="gap: 8px">
          <RouterLink class="btn btn-ghost btn-sm" to="/t/tool-defect-management">🐞 缺陷管理</RouterLink>
          <RouterLink class="btn btn-ghost btn-sm" to="/t/tool-root-cause">🔍 对失败项做根因分析 →</RouterLink>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="exportPdf">⬇️ 导出 PDF</button>
        <button class="btn btn-primary" @click="viewOpen = false">关闭</button>
      </div>
    </div>
  </div>
</template>
