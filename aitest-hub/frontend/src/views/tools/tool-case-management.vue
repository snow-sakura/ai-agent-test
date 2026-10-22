<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import DataTable from '@/components/ui/DataTable.vue'
import { uiToast, uiConfirm } from '@/composables/ui'
import http from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-case-management.html） ---------- */
interface CaseRow {
  id: string
  title: string
  module: string
  pri: string
  type: string
  status: string
  owner: string
  run: number
  pass: number
  defect: number
  pre: string
  steps: string
  exp: string
}
interface Batch {
  id: string
  name: string
  scope: string
  total: number
  pass: number
  fail: number
  time: string
  by: string
  status: string
}

const PRI_CLS: Record<string, string> = { P0: 'tag-red', P1: 'tag-orange', P2: 'tag' }

const modules = ref<string[]>([])
const cases = ref<CaseRow[]>([])
const batches = ref<Batch[]>([])
const curModule = ref('')

async function reload() {
  const [m, c, b] = await Promise.all([
    http.get<string[]>('/case-modules'),
    http.get<CaseRow[]>('/cases'),
    http.get<Batch[]>('/case-batches'),
  ])
  modules.value = m.data || []
  cases.value = c.data || []
  batches.value = b.data || []
}

onMounted(() => {
  reload().catch(() => undefined)
})

function statusTag(s: string) {
  if (s === '已评审') return 'tag-green'
  if (s === '待评审') return 'tag-orange'
  return ''
}

function statusLabel(s: string) {
  return s === '已评审' || s === '待评审' ? s : '已废弃'
}

/* ---------- 模块树 ---------- */
function moduleCount(name: string) {
  return cases.value.filter((c) => c.module === name).length
}

const modOpen = ref(false)
const modName = ref('')

async function saveModule() {
  const n = modName.value.trim()
  if (!n) {
    uiToast('请填写模块名称', 'error')
    return
  }
  try {
    const { data } = await http.post<string[]>('/case-modules', { name: n })
    modules.value = data || []
    modOpen.value = false
    modName.value = ''
    uiToast('模块已创建', 'success')
    await reload()
  } catch (e) {
    const m = e instanceof Error ? e.message : ''
    if (m.includes('存在')) uiToast('模块已存在', 'warn')
  }
}

/* ---------- 用例表 ---------- */
const kw = ref('')
const priFilter = ref('')
const stFilter = ref('')

const filtered = computed(() =>
  cases.value.filter((c) => {
    const k = kw.value.trim().toLowerCase()
    return (
      (!curModule.value || c.module === curModule.value) &&
      (!k || (c.title + c.id).toLowerCase().includes(k)) &&
      (!priFilter.value || c.pri === priFilter.value) &&
      (!stFilter.value || c.status === stFilter.value)
    )
  }),
)

const caseColumns = [
  { key: 'id', label: '编号' },
  { key: 'title', label: '标题' },
  { key: 'module', label: '模块' },
  { key: 'pri', label: '优先级' },
  { key: 'type', label: '类型' },
  { key: 'status', label: '状态' },
  { key: 'run', label: '执行' },
]

/* ---------- 详情 ---------- */
const view = ref<CaseRow | null>(null)
const viewOpen = ref(false)

function openView(c: CaseRow) {
  view.value = c
  viewOpen.value = true
}

/* ---------- 新建 / 编辑用例 ---------- */
const caseOpen = ref(false)
const editingId = ref<string | null>(null)
const fTitle = ref('')
const fModule = ref('订单模块')
const fPri = ref('P0')
const fType = ref('功能')
const fPre = ref('')
const fSteps = ref('')
const fExp = ref('')

function openNewCase() {
  editingId.value = null
  fTitle.value = ''
  fPre.value = ''
  fSteps.value = ''
  fExp.value = ''
  fPri.value = 'P0'
  fType.value = '功能'
  if (modules.value.length) fModule.value = modules.value[0]
  caseOpen.value = true
}

function openEditCase(c: CaseRow) {
  editingId.value = c.id
  fTitle.value = c.title
  fModule.value = c.module
  fPri.value = c.pri
  fType.value = c.type
  fPre.value = c.pre
  fSteps.value = c.steps
  fExp.value = c.exp
  caseOpen.value = true
}

async function saveCase() {
  const t = fTitle.value.trim()
  if (!t) {
    uiToast('请填写用例标题', 'error')
    return
  }
  const payload = {
    title: t,
    module: fModule.value,
    pri: fPri.value,
    type: fType.value,
    pre: fPre.value || '-',
    steps: fSteps.value || '-',
    exp: fExp.value || '-',
  }
  const isEdit = !!editingId.value
  if (isEdit) {
    await http.put(`/cases/${editingId.value}`, payload)
  } else {
    await http.post('/cases', payload)
  }
  caseOpen.value = false
  editingId.value = null
  await reload()
  uiToast(isEdit ? '用例已更新' : '用例已保存，进入待评审', 'success')
}

function dropCase(c: CaseRow) {
  uiConfirm({
    title: '废弃用例',
    message: `确定废弃用例「${c.title}」吗？废弃后不再纳入执行统计。`,
    onOk: async () => {
      await http.post(`/cases/${c.id}/drop`)
      await reload()
      uiToast('用例已废弃', 'success')
    },
  })
}

/* ---------- 评审 ---------- */
const reviewRows = computed(() => cases.value.filter((c) => c.status === '待评审'))
const reviewColumns = [
  { key: 'id', label: '编号' },
  { key: 'title', label: '标题' },
  { key: 'module', label: '模块' },
  { key: 'pri', label: '优先级' },
  { key: 'owner', label: '编写人' },
]

async function approve(c: CaseRow) {
  await http.post(`/cases/${c.id}/review`, { action: 'approve' })
  await reload()
  uiToast('评审通过 ✅', 'success')
}

function reject(c: CaseRow) {
  uiConfirm({
    title: '驳回用例',
    message: `确定驳回用例「${c.title}」吗？将通知编写人 ${c.owner} 修改。`,
    onOk: async () => {
      await http.post(`/cases/${c.id}/review`, { action: 'reject' })
      await reload()
      uiToast(`已驳回并通知 ${c.owner}`, 'warn')
    },
  })
}

/* ---------- 执行批次 ---------- */
const batchColumns = [
  { key: 'id', label: '批次' },
  { key: 'name', label: '名称' },
  { key: 'scope', label: '范围' },
  { key: 'total', label: '用例' },
  { key: 'pass', label: '通过' },
  { key: 'fail', label: '失败' },
  { key: 'progress', label: '进度' },
  { key: 'status', label: '状态' },
]

function batchPct(b: Batch) {
  if (!b.total) return 0
  return Math.round(((b.pass + b.fail) / b.total) * 100)
}

const batchOpen = ref(false)
const fbName = ref('')
const fbScope = ref('全部已评审用例')

async function saveBatch() {
  const n = fbName.value.trim()
  if (!n) {
    uiToast('请填写批次名称', 'error')
    return
  }
  await http.post('/case-batches', { name: n, scope: fbScope.value })
  batchOpen.value = false
  fbName.value = ''
  await reload()
  uiToast('批次已创建并开始执行', 'success')
}

function stopBatch(b: Batch) {
  uiConfirm({
    title: '停止批次',
    message: `确定停止执行批次「${b.name}」吗？`,
    onOk: async () => {
      await http.post(`/case-batches/${b.id}/stop`)
      await reload()
      uiToast('批次已停止', 'success')
    },
  })
}
</script>

<template>
  <ModuleShell slug="tool-case-management">
    <template #actions>
      <RouterLink class="btn btn-ghost" to="/t/tool-test-cases">🤖 去AI生成</RouterLink>
      <RouterLink class="btn btn-ghost" to="/t/tool-defect-management">🐞 关联缺陷</RouterLink>
      <button class="btn btn-primary" @click="openNewCase">＋ 新建用例</button>
    </template>

    <template #default="{ tab }">
      <!-- ============ 用例库 ============ -->
      <template v-if="tab === 'lib'">
        <div class="grid" style="grid-template-columns: 240px 1fr; gap: 14px">
          <!-- 模块树 -->
          <div class="card" style="padding: 14px">
            <div class="card-title" style="font-size: 13.5px">
              🌳 模块树
              <button class="btn btn-sm btn-ghost" @click="modOpen = true">＋</button>
            </div>
            <div style="display: flex; flex-direction: column; gap: 2px; font-size: 13px">
              <a
                href="#"
                class="side-item"
                :class="{ active: curModule === '' }"
                @click.prevent="curModule = ''"
              >📁 全部用例 ({{ cases.length }})</a>
              <a
                v-for="m in modules"
                :key="m"
                href="#"
                class="side-item"
                :class="{ active: curModule === m }"
                @click.prevent="curModule = m"
              >📂 {{ m }} ({{ moduleCount(m) }})</a>
            </div>
          </div>
          <!-- 用例表 -->
          <div>
            <div class="filter-bar">
              <input v-model="kw" class="input search" placeholder="🔍 搜索标题 / 编号" />
              <select v-model="priFilter" class="select">
                <option value="">全部优先级</option>
                <option>P0</option>
                <option>P1</option>
                <option>P2</option>
              </select>
              <select v-model="stFilter" class="select">
                <option value="">全部状态</option>
                <option>待评审</option>
                <option>已评审</option>
                <option>已废弃</option>
              </select>
            </div>
            <DataTable
              :columns="caseColumns"
              :rows="filtered"
              empty-text="无匹配用例，去 AI 生成 →"
            >
              <template #cell-id="{ row }">
                <span class="mono">{{ (row as CaseRow).id }}</span>
              </template>
              <template #cell-title="{ row }">
                <div class="cell-main">{{ (row as CaseRow).title }}</div>
                <div class="cell-sub">{{ (row as CaseRow).owner }}</div>
              </template>
              <template #cell-module="{ row }">
                <span class="tag">{{ (row as CaseRow).module }}</span>
              </template>
              <template #cell-pri="{ row }">
                <span class="tag" :class="PRI_CLS[(row as CaseRow).pri]">{{ (row as CaseRow).pri }}</span>
              </template>
              <template #cell-status="{ row }">
                <span class="tag" :class="statusTag((row as CaseRow).status)">
                  {{ statusLabel((row as CaseRow).status) }}
                </span>
              </template>
              <template #cell-run="{ row }">
                <span class="mono" style="font-size: 12px">
                  {{ (row as CaseRow).pass }}/{{ (row as CaseRow).run }}
                  <RouterLink
                    v-if="(row as CaseRow).defect"
                    to="/t/tool-defect-management"
                    title="关联缺陷"
                  >🐞{{ (row as CaseRow).defect }}</RouterLink>
                </span>
              </template>
              <template #actions="{ row }">
                <button class="btn btn-sm btn-ghost" @click="openView(row as CaseRow)">详情</button>
                <button class="btn btn-sm btn-ghost" @click="openEditCase(row as CaseRow)">编辑</button>
                <button class="btn btn-sm btn-danger" @click="dropCase(row as CaseRow)">废弃</button>
              </template>
            </DataTable>
          </div>
        </div>
      </template>

      <!-- ============ 评审 ============ -->
      <template v-if="tab === 'review'">
        <div class="banner banner-info">
          ℹ️ 待评审用例需由评审人给出「通过 / 驳回」结论；驳回需填写原因，用例将退回编写人修改。
        </div>
        <DataTable
          :columns="reviewColumns"
          :rows="reviewRows"
          empty-text="全部用例已评审完毕 🎉"
        >
          <template #cell-id="{ row }">
            <span class="mono">{{ (row as CaseRow).id }}</span>
          </template>
          <template #cell-title="{ row }">
            <div class="cell-main">{{ (row as CaseRow).title }}</div>
          </template>
          <template #cell-module="{ row }">
            <span class="tag">{{ (row as CaseRow).module }}</span>
          </template>
          <template #cell-pri="{ row }">
            <span class="tag" :class="PRI_CLS[(row as CaseRow).pri]">{{ (row as CaseRow).pri }}</span>
          </template>
          <template #actions="{ row }">
            <div class="flex">
              <button class="btn btn-sm btn-success" @click="approve(row as CaseRow)">✅ 通过</button>
              <button class="btn btn-sm btn-danger" @click="reject(row as CaseRow)">❌ 驳回</button>
            </div>
          </template>
        </DataTable>
      </template>

      <!-- ============ 执行批次 ============ -->
      <template v-if="tab === 'batches'">
        <div class="flex mb-16" style="justify-content: flex-end">
          <button class="btn btn-primary" @click="batchOpen = true">＋ 新建执行批次</button>
        </div>
        <DataTable :columns="batchColumns" :rows="batches" empty-text="暂无执行批次">
          <template #cell-id="{ row }">
            <span class="mono">{{ (row as Batch).id }}</span>
          </template>
          <template #cell-name="{ row }">
            <div class="cell-main">{{ (row as Batch).name }}</div>
            <div class="cell-sub">{{ (row as Batch).by }} · {{ (row as Batch).time }}</div>
          </template>
          <template #cell-total="{ row }">
            <span class="mono">{{ (row as Batch).total }}</span>
          </template>
          <template #cell-pass="{ row }">
            <span class="mono text-green">{{ (row as Batch).pass }}</span>
          </template>
          <template #cell-fail="{ row }">
            <span class="mono text-red">{{ (row as Batch).fail }}</span>
          </template>
          <template #cell-progress="{ row }">
            <div class="progress" style="width: 90px">
              <div class="bar bar-green" :style="{ width: batchPct(row as Batch) + '%' }"></div>
            </div>
          </template>
          <template #cell-status="{ row }">
            <span v-if="(row as Batch).status === '已完成'" class="tag tag-blue">已完成</span>
            <span v-else class="tag tag-orange">执行中</span>
          </template>
          <template #actions="{ row }">
            <button class="btn btn-sm btn-ghost" @click="uiToast('演示环境：批次详情页建设中', 'info')">详情</button>
            <button
              v-if="(row as Batch).status !== '已完成'"
              class="btn btn-sm btn-danger"
              @click="stopBatch(row as Batch)"
            >停止</button>
          </template>
        </DataTable>
      </template>
    </template>
  </ModuleShell>

  <!-- 新建/编辑用例弹窗 -->
  <div class="modal-mask" :class="{ open: caseOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>{{ editingId ? '编辑用例 · ' + editingId : '＋ 新建用例' }}</h3>
        <button class="modal-close" @click="caseOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="grid grid-2" style="gap: 12px">
          <div class="field">
            <label>用例标题 <span class="text-red">*</span></label>
            <input v-model="fTitle" class="input" placeholder="如：正常提交退款申请" />
          </div>
          <div class="field">
            <label>所属模块</label>
            <select v-model="fModule" class="select">
              <option v-for="m in modules" :key="m" :value="m">{{ m }}</option>
            </select>
          </div>
        </div>
        <div class="grid grid-2" style="gap: 12px">
          <div class="field">
            <label>优先级</label>
            <select v-model="fPri" class="select"><option>P0</option><option>P1</option><option>P2</option></select>
          </div>
          <div class="field">
            <label>用例类型</label>
            <select v-model="fType" class="select">
              <option>功能</option><option>边界</option><option>异常流</option><option>接口</option>
            </select>
          </div>
        </div>
        <div class="field">
          <label>前置条件</label>
          <input v-model="fPre" class="input" placeholder="用户已登录…" />
        </div>
        <div class="field">
          <label>操作步骤</label>
          <textarea v-model="fSteps" class="textarea" rows="4" placeholder="1. …&#10;2. …"></textarea>
        </div>
        <div class="field">
          <label>预期结果</label>
          <textarea v-model="fExp" class="textarea" rows="2"></textarea>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="caseOpen = false">取消</button>
        <button class="btn btn-primary" @click="saveCase">💾 保存用例</button>
      </div>
    </div>
  </div>

  <!-- 用例详情弹窗 -->
  <div class="modal-mask" :class="{ open: viewOpen }">
    <div class="modal">
      <div class="modal-head">
        <h3>{{ view ? view.id + ' · ' + view.title : '用例详情' }}</h3>
        <button class="modal-close" @click="viewOpen = false">✕</button>
      </div>
      <div class="modal-body" v-if="view">
        <div class="flex mb-16">
          <span class="tag" :class="PRI_CLS[view.pri]">{{ view.pri }}</span>
          <span class="tag">{{ view.module }}</span>
          <span class="tag">{{ view.type }}</span>
          <span class="tag" :class="statusTag(view.status)">{{ statusLabel(view.status) }}</span>
        </div>
        <div class="field"><label>前置条件</label><div class="code-block">{{ view.pre }}</div></div>
        <div class="field"><label>操作步骤</label><div class="code-block">{{ view.steps }}</div></div>
        <div class="field"><label>预期结果</label><div class="code-block">{{ view.exp }}</div></div>
        <div class="flex">
          <template v-if="view.defect">
            <span class="tag tag-red">🐞 关联缺陷 {{ view.defect }} 个</span>
            <RouterLink to="/t/tool-defect-management" style="font-size: 12.5px">前往缺陷管理 →</RouterLink>
          </template>
          <span v-else class="tag">暂无关联缺陷</span>
        </div>
      </div>
      <div class="modal-foot">
        <RouterLink
          v-if="view && view.defect"
          class="btn btn-ghost"
          to="/t/tool-defect-management"
        >🐞 查看关联缺陷</RouterLink>
        <button class="btn btn-primary" @click="viewOpen = false">关闭</button>
      </div>
    </div>
  </div>

  <!-- 新建模块弹窗 -->
  <div class="modal-mask" :class="{ open: modOpen }">
    <div class="modal modal-sm">
      <div class="modal-head"><h3>＋ 新建模块</h3><button class="modal-close" @click="modOpen = false">✕</button></div>
      <div class="modal-body">
        <div class="field">
          <label>模块名称 <span class="text-red">*</span></label>
          <input v-model="modName" class="input" placeholder="如：优惠券模块" />
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="modOpen = false">取消</button>
        <button class="btn btn-primary" @click="saveModule">💾 保存</button>
      </div>
    </div>
  </div>

  <!-- 新建执行批次弹窗 -->
  <div class="modal-mask" :class="{ open: batchOpen }">
    <div class="modal">
      <div class="modal-head"><h3>＋ 新建执行批次</h3><button class="modal-close" @click="batchOpen = false">✕</button></div>
      <div class="modal-body">
        <div class="field">
          <label>批次名称 <span class="text-red">*</span></label>
          <input v-model="fbName" class="input" placeholder="如：9月第4周回归" />
        </div>
        <div class="field">
          <label>包含用例</label>
          <select v-model="fbScope" class="select">
            <option>全部已评审用例</option>
            <option>按模块选择</option>
            <option>仅 P0 用例</option>
          </select>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="batchOpen = false">取消</button>
        <button class="btn btn-primary" @click="saveBatch">💾 创建批次</button>
      </div>
    </div>
  </div>
</template>
