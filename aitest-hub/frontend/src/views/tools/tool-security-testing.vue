<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import DataTable from '@/components/ui/DataTable.vue'
import StatCard from '@/components/ui/StatCard.vue'
import { uiToast, uiConfirm } from '@/composables/ui'
import http from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-security-testing.html + security_testing.py） ---------- */
interface Finding {
  id: string
  title: string
  sev: string
  level: string
  url: string
  target: string
  param: string
  poc: string
  detail: string
  status: string
  fix: string
  owasp: string
  req: string
  time: string
}
interface Baseline {
  id: string
  item: string
  name: string
  level: string
  required: boolean
  status: string
  note: string
  desc: string
}

const L_CLS: Record<string, string> = { 高危: 'tag-red', 中危: 'tag-orange', 低危: 'tag-blue', 提示: 'tag' }
const S_CLS: Record<string, string> = { 待处理: 'tag-orange', 修复中: 'tag-blue', 已修复: 'tag-green', 已忽略: 'tag' }
const B_CLS: Record<string, string> = { 通过: 'tag-green', 不通过: 'tag-red', 未检: 'tag' }

const findings = ref<Finding[]>([])
const baselines = ref<Baseline[]>([])

async function reload() {
  const [f, b] = await Promise.all([
    http.get<Finding[]>('/security/findings'),
    http.get<Baseline[]>('/security/baselines'),
  ])
  findings.value = f.data || []
  baselines.value = b.data || []
}

onMounted(() => {
  reload().catch(() => undefined)
})

/* ---------- 统计 ---------- */
function isOpen(f: Finding) {
  return f.status !== '已忽略' && f.status !== '已修复'
}
const highCount = computed(() => findings.value.filter((f) => f.sev === '高危' && isOpen(f)).length)
const midCount = computed(() => findings.value.filter((f) => f.sev === '中危' && isOpen(f)).length)
const lowCount = computed(
  () => findings.value.filter((f) => (f.sev === '低危' || f.sev === '提示') && isOpen(f)).length,
)
const baseRate = computed(() => {
  const checked = baselines.value.filter((b) => b.status !== '未检')
  // 后端基线无 items/pass 计数字段，按条数估算通过率
  if (!checked.length) return '—'
  const pass = checked.filter((b) => b.status === '通过').length
  return Math.round((pass / checked.length) * 100) + '%'
})

/* ---------- 安全发现 ---------- */
const kw = ref('')
const lvFilter = ref('')
const stFilter = ref('')

const filtered = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return findings.value.filter(
    (f) =>
      (!k || (f.title + f.target + f.id).toLowerCase().includes(k)) &&
      (!lvFilter.value || f.sev === lvFilter.value) &&
      (!stFilter.value || f.status === stFilter.value),
  )
})

const fColumns = [
  { key: 'id', label: '编号' },
  { key: 'title', label: '安全发现' },
  { key: 'level', label: '等级' },
  { key: 'owasp', label: 'OWASP' },
  { key: 'status', label: '状态' },
  { key: 'req', label: '需求关联' },
]

function resetFilters() {
  kw.value = ''
  lvFilter.value = ''
  stFilter.value = ''
  uiToast('筛选已重置', 'info')
}

function viewDetail(f: Finding) {
  uiToast(`${f.id}：${f.detail || f.poc}`, 'info')
}

async function toDefect(f: Finding) {
  uiConfirm({
    title: '生成安全缺陷',
    message: `将基于「${f.title}」创建缺陷单（等级：${f.sev}）并关联安全发现，确认提交吗？`,
    onOk: () => {
      uiToast('安全缺陷已提交至缺陷管理 🐞', 'success')
    },
  })
}

function aiFromFinding(f: Finding) {
  aiTarget.value = `${f.id} · ${f.title}（${f.sev}）`
  uiToast('已切换到 AI 安全助手，分析对象已选中', 'info')
  // AI tab 需要 ModuleShell 切换，由用户点击侧栏；这里只更新选中项
}

/* ---------- 安全基线 ---------- */
const bColumns = [
  { key: 'id', label: '类别' },
  { key: 'name', label: 'OWASP 类目' },
  { key: 'desc', label: '检查说明' },
  { key: 'status', label: '结论' },
]

function bDetail(b: Baseline) {
  uiToast(`${b.id} ${b.name}：${b.status}（演示环境明细页建设中）`, 'info')
}
function bAi(b: Baseline) {
  aiTarget.value = `OWASP ${b.id} · ${b.name}（基线不通过）`
  uiToast('已切换到 AI 安全助手', 'info')
}

/* ---------- AI 安全助手 ---------- */
const aiTarget = ref('')
const aiTypes = ref<string[]>(['修复建议', '风险评级'])
const aiCtx = ref('')
const aiLoading = ref(false)
const aiMsgs = ref<{ text: string; html?: boolean }[]>([
  {
    text: '我是安全分析助手。选择安全发现后点击「开始 AI 分析」，我将输出风险评级、修复建议与复验用例，并可一键生成安全缺陷单。渗透测试请前往渗透测试模块。',
    html: false,
  },
])

function toggleAiType(t: string) {
  const i = aiTypes.value.indexOf(t)
  if (i >= 0) aiTypes.value.splice(i, 1)
  else aiTypes.value.push(t)
}

async function runAi() {
  if (aiLoading.value) return
  if (!aiTarget.value) {
    const f = findings.value[0]
    if (f) aiTarget.value = `${f.id} · ${f.title}（${f.sev}）`
  }
  aiLoading.value = true
  aiMsgs.value.push({ text: '正在比对 OWASP Top 10 / CWE / CVE 知识库与目标报文…' })
  try {
    const text = aiCtx.value.trim() || aiTarget.value || '安全分析'
    const { data } = await http.post<{ text: string }>('/security/ai-review', { text })
    aiMsgs.value.push({ text: data.text || '分析完成（无返回内容）', html: false })
    uiToast('AI 分析完成', 'success')
  } finally {
    aiLoading.value = false
  }
}

function aiToDefect() {
  uiToast('安全缺陷已提交至缺陷管理并关联发现 🐞', 'success')
}
function aiToCases() {
  uiToast('复验用例已写入用例管理，关联需求追溯矩阵', 'success')
}

/* ---------- 新建扫描 ---------- */
const scanOpen = ref(false)
const fsName = ref('')
const fsTarget = ref('支付模块 API（/v1/pay, /v1/refunds）')
const fsReq = ref('')
const scanning = ref(false)

function openScan() {
  fsName.value = ''
  fsTarget.value = '支付模块 API（/v1/pay, /v1/refunds）'
  fsReq.value = ''
  scanOpen.value = true
}

async function saveScan() {
  const n = fsName.value.trim()
  if (!n) {
    uiToast('请填写扫描任务名称', 'error')
    return
  }
  scanning.value = true
  scanOpen.value = false
  uiToast('扫描任务已创建，正在执行基线检查…', 'info')
  try {
    const target = fsTarget.value.split('（')[0]
    const { data } = await http.post<{ count: number; findings: Finding[] }>('/security/scan', {
      target,
      count: 3,
    })
    await reload()
    const created = data.findings || []
    if (created.length && fsReq.value) {
      const reqId = fsReq.value.split(' · ')[0]
      for (const c of created) {
        await http.put(`/security/findings/${c.id}`, { req: reqId }).catch(() => undefined)
      }
      await reload()
    }
    uiToast(`扫描完成：新发现 ${data.count} 项，已入发现列表`, 'success')
  } finally {
    scanning.value = false
  }
}
</script>

<template>
  <ModuleShell slug="tool-security-testing">
    <template #actions>
      <RouterLink class="btn btn-ghost" to="/t/tool-pentest-testing">🎯 去渗透测试</RouterLink>
      <button class="btn btn-primary" :disabled="scanning" @click="openScan">＋ 新建安全扫描</button>
    </template>

    <template #default="{ tab }">
      <div class="banner banner-info">
        ℹ️ 安全测试项可从<RouterLink to="/t/tool-requirement-management">需求管理</RouterLink>派生（SEC 条目自动关联）；AI 基于 OWASP Top 10 与 CVE 库给出修复建议，可一键生成安全缺陷单。
      </div>

      <!-- 统计 -->
      <div class="grid grid-4 mb-16">
        <StatCard label="高危发现" :value="highCount" color="var(--red)" />
        <StatCard label="中危发现" :value="midCount" color="var(--orange)" />
        <StatCard label="低危发现" :value="lowCount" color="var(--blue)" />
        <StatCard label="基线通过率" :value="baseRate" color="var(--green)" />
      </div>

      <!-- ============ 安全发现 ============ -->
      <template v-if="tab === 'findings'">
        <div class="filter-bar">
          <input v-model="kw" class="input search" placeholder="🔍 搜索漏洞 / 目标" />
          <select v-model="lvFilter" class="select">
            <option value="">全部等级</option>
            <option>高危</option><option>中危</option><option>低危</option><option>提示</option>
          </select>
          <select v-model="stFilter" class="select">
            <option value="">全部状态</option>
            <option>待处理</option><option>修复中</option><option>已修复</option><option>已忽略</option>
          </select>
          <button class="btn btn-ghost btn-sm" @click="resetFilters">重置</button>
        </div>
        <DataTable :columns="fColumns" :rows="filtered" empty-text="无匹配安全发现">
          <template #cell-id="{ row }">
            <span class="mono">{{ (row as Finding).id }}</span>
          </template>
          <template #cell-title="{ row }">
            <div class="cell-main">{{ (row as Finding).title }}</div>
            <div class="cell-sub mono">{{ (row as Finding).target }} · {{ (row as Finding).time }}</div>
          </template>
          <template #cell-level="{ row }">
            <span class="tag" :class="L_CLS[(row as Finding).sev]">{{ (row as Finding).sev }}</span>
          </template>
          <template #cell-owasp="{ row }">
            <span class="text-dim" style="font-size: 12.5px">{{ (row as Finding).owasp }}</span>
          </template>
          <template #cell-status="{ row }">
            <span class="tag" :class="S_CLS[(row as Finding).status]">{{ (row as Finding).status }}</span>
          </template>
          <template #cell-req="{ row }">
            <RouterLink v-if="(row as Finding).req" class="mono" to="/t/tool-requirement-management">
              {{ (row as Finding).req }}
            </RouterLink>
            <span v-else class="text-faint">—</span>
          </template>
          <template #actions="{ row }">
            <button class="btn btn-sm btn-ghost" @click="viewDetail(row as Finding)">详情</button>
            <button class="btn btn-sm btn-primary" @click="aiFromFinding(row as Finding)">🤖 AI 修复建议</button>
            <button class="btn btn-sm btn-danger" @click="toDefect(row as Finding)">提缺陷</button>
          </template>
        </DataTable>
      </template>

      <!-- ============ 安全基线 ============ -->
      <template v-if="tab === 'baseline'">
        <div class="banner banner-green">
          ✅ 基于 OWASP Top 10 与等保要求的检查基线；不通过项可一键转安全发现或生成缺陷。
        </div>
        <DataTable :columns="bColumns" :rows="baselines" empty-text="暂无基线数据">
          <template #cell-id="{ row }">
            <span class="mono">{{ (row as Baseline).id }}</span>
          </template>
          <template #cell-name="{ row }">
            <div class="cell-main">{{ (row as Baseline).name }}</div>
          </template>
          <template #cell-desc="{ row }">
            <span class="text-dim" style="font-size: 12.5px">{{ (row as Baseline).desc }}</span>
          </template>
          <template #cell-status="{ row }">
            <span class="tag" :class="B_CLS[(row as Baseline).status]">{{ (row as Baseline).status }}</span>
          </template>
          <template #actions="{ row }">
            <button class="btn btn-sm btn-ghost" @click="bDetail(row as Baseline)">检查明细</button>
            <button
              v-if="(row as Baseline).status === '不通过'"
              class="btn btn-sm btn-primary"
              @click="bAi(row as Baseline)"
            >🤖 AI 建议</button>
          </template>
        </DataTable>
      </template>

      <!-- ============ AI 安全助手 ============ -->
      <template v-if="tab === 'ai'">
        <div class="grid" style="grid-template-columns: 1fr 1.3fr; gap: 14px">
          <div class="card">
            <div class="card-title">🤖 AI 安全助手 <span class="tag tag-red">AI</span></div>
            <div class="field">
              <label>分析对象</label>
              <select v-model="aiTarget" class="select">
                <option value="">（自动选择最新发现）</option>
                <option v-for="f in findings" :key="f.id" :value="`${f.id} · ${f.title}（${f.sev}）`">
                  {{ f.id }} · {{ f.title }}（{{ f.sev }}）
                </option>
              </select>
            </div>
            <div class="field">
              <label>输出内容</label>
              <div class="flex" style="gap: 8px; flex-wrap: wrap">
                <label v-for="t in ['修复建议', '风险评级', '复验用例']" :key="t" class="checkbox">
                  <input type="checkbox" :checked="aiTypes.includes(t)" @change="toggleAiType(t)" /> {{ t }}
                </label>
              </div>
            </div>
            <div class="field">
              <label>补充上下文（请求报文 / 代码片段，选填）</label>
              <textarea
                v-model="aiCtx"
                class="textarea mono"
                rows="4"
                placeholder='粘贴可疑请求报文，如：{"orderId": 1001, "amount": 0.01}'
              ></textarea>
            </div>
            <button class="btn btn-primary" style="width: 100%" :disabled="aiLoading" @click="runAi">
              <span v-if="aiLoading" class="spinner"></span> ✨ 开始 AI 分析
            </button>
          </div>
          <div class="card">
            <div class="card-title">🧠 分析结论</div>
            <div class="chat-box">
              <div v-for="(m, i) in aiMsgs" :key="i" class="msg ai">
                <div class="m-avatar">🤖</div>
                <div class="m-body">{{ m.text }}</div>
              </div>
            </div>
            <div v-if="aiMsgs.length > 1" class="flex mt-8">
              <button class="btn btn-sm btn-primary" @click="aiToDefect">🐞 一键生成安全缺陷单</button>
              <button class="btn btn-sm btn-ghost" @click="aiToCases">🗂️ 复验用例入用例库</button>
            </div>
          </div>
        </div>
      </template>
    </template>
  </ModuleShell>

  <!-- 新建扫描弹窗 -->
  <div class="modal-mask" :class="{ open: scanOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>＋ 新建安全扫描</h3>
        <button class="modal-close" @click="scanOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="field">
          <label>扫描任务名称 <span class="text-red">*</span></label>
          <input v-model="fsName" class="input" placeholder="如：支付模块安全基线扫描" />
        </div>
        <div class="field">
          <label>扫描目标</label>
          <select v-model="fsTarget" class="select">
            <option>支付模块 API（/v1/pay, /v1/refunds）</option>
            <option>用户模块 API（/v1/auth, /v1/users）</option>
            <option>Web 站点（https://shop.example.com）</option>
          </select>
        </div>
        <div class="field">
          <label>检查策略</label>
          <div class="flex" style="gap: 8px; flex-wrap: wrap">
            <label class="checkbox"><input type="checkbox" checked disabled /> OWASP Top 10</label>
            <label class="checkbox"><input type="checkbox" checked disabled /> 敏感信息泄露</label>
            <label class="checkbox"><input type="checkbox" /> 依赖组件 CVE</label>
            <label class="checkbox"><input type="checkbox" /> 配置基线（CIS）</label>
          </div>
        </div>
        <div class="field">
          <label>关联需求</label>
          <select v-model="fsReq" class="select">
            <option value="">不关联</option>
            <option>REQ-2026-0125 · 订单退款功能</option>
            <option>REQ-2026-0121 · 大促秒杀活动</option>
          </select>
        </div>
        <div class="banner banner-warn" style="margin: 0">
          ⚠️ 主动扫描可能对目标产生少量脏数据，请确认目标为测试环境；生产环境请使用只读被动模式。
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="scanOpen = false">取消</button>
        <button class="btn btn-primary" :disabled="scanning" @click="saveScan">
          <span v-if="scanning" class="spinner"></span> ▶️ 创建并扫描
        </button>
      </div>
    </div>
  </div>
</template>
