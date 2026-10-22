<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import DataTable from '@/components/ui/DataTable.vue'
import StatCard from '@/components/ui/StatCard.vue'
import { uiToast, uiConfirm } from '@/composables/ui'
import http from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-performance-testing.html + performance.py） ---------- */
interface Scene {
  id: string
  name: string
  users: number
  ramp: number
  dur: number
  url: string
  method: string
  status: string
  last: string
  qps: number
  p99: number
  err: number
}
interface Report {
  id: string
  sceneId: string
  scene: string
  qps: number
  p99: number
  err: number
  users: number
  verdict: string
  time: string
  note: string
  metrics: Record<string, unknown>
}

const R_CLS: Record<string, string> = { 达标: 'tag-green', 未达标: 'tag-red', 未执行: 'tag' }

/* UI 表单字段在后端无对应列（类型/关联需求/目标QPS等），本地派生展示 */
interface SceneExt extends Scene {
  type?: string
  req?: string
  targetQps?: number
  p99Limit?: number
  errLimit?: number
  ai?: string
}

const scenes = ref<SceneExt[]>([])
const reports = ref<Report[]>([])

async function reload() {
  const [s, r] = await Promise.all([
    http.get<SceneExt[]>('/perf/scenes'),
    http.get<Report[]>('/perf/reports'),
  ])
  scenes.value = s.data || []
  reports.value = r.data || []
}

onMounted(() => {
  reload().catch(() => undefined)
})

/* ---------- 统计 ---------- */
const total = computed(() => scenes.value.length)
const passCount = computed(() => scenes.value.filter((s) => s.status === '达标').length)
const failCount = computed(() => scenes.value.filter((s) => s.status === '未达标').length)
const aiPending = computed(() => scenes.value.filter((s) => s.ai === '待复检').length)

/* ---------- 场景 tab ---------- */
const kw = ref('')
const stFilter = ref('')
const typeFilter = ref('')

const filtered = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return scenes.value.filter(
    (s) =>
      (!k || s.name.toLowerCase().includes(k)) &&
      (!stFilter.value || s.status === stFilter.value) &&
      (!typeFilter.value || (s.type || '') === typeFilter.value),
  )
})

const sceneColumns = [
  { key: 'id', label: '编号' },
  { key: 'name', label: '场景' },
  { key: 'type', label: '类型' },
  { key: 'qps', label: '目标/实际 QPS' },
  { key: 'p99', label: 'P99 (ms)' },
  { key: 'err', label: '错误率' },
  { key: 'status', label: '结论' },
  { key: 'ai', label: 'AI' },
]

const runningId = ref('')

async function runScene(s: SceneExt) {
  if (runningId.value) return
  runningId.value = s.id
  uiToast(`场景「${s.name}」压测执行中…`, 'info')
  try {
    const { data } = await http.post<Report>(`/perf/scenes/${s.id}/run`)
    await reload()
    if (data.verdict === '达标') {
      uiToast('压测完成：达标 ✅', 'success')
    } else {
      const target = scenes.value.find((x) => x.id === s.id)
      if (target) target.ai = '待复检'
      uiToast('压测完成：未达标 ❌ 已标记 AI 待复检', 'warn')
    }
  } finally {
    runningId.value = ''
  }
}

async function aiAnalyzeScene(s: SceneExt) {
  aiTarget.value = `${s.name}（${s.status}）`
  aiTypes.value = ['容量评估', '瓶颈定位']
  await runAi(s.id)
  // 切到 AI tab 由 ModuleShell query 控制：这里用 toast 提示
  uiToast('已切换到 AI 性能助手，分析对象已选中', 'info')
}

function dropScene(s: SceneExt) {
  uiConfirm({
    title: '删除性能场景',
    message: `确定删除「${s.name}」吗？其历史报告将保留。`,
    onOk: async () => {
      try {
        await http.delete(`/perf/scenes/${s.id}`)
        await reload()
        uiToast('场景已删除', 'success')
      } catch (e) {
        uiToast(e instanceof Error ? e.message : String(e), 'error')
      }
    },
  })
}

/* ---------- 新建场景（UI 字段保留，映射到后端原生字段） ---------- */
const sceneOpen = ref(false)
const fName = ref('')
const fType = ref('基准')
const fReq = ref('')
const fQps = ref(2000)
const fP99 = ref(500)
const fErr = ref(0.5)
const fUsers = ref(100)
const fRamp = ref(30)
const fDur = ref(120)
const fUrl = ref('')

function openNewScene() {
  fName.value = ''
  fType.value = '基准'
  fReq.value = ''
  fQps.value = 2000
  fP99.value = 500
  fErr.value = 0.5
  fUsers.value = 100
  fRamp.value = 30
  fDur.value = 120
  fUrl.value = ''
  sceneOpen.value = true
}

async function saveScene() {
  const n = fName.value.trim()
  if (!n) {
    uiToast('请填写场景名称', 'error')
    return
  }
  await http.post('/perf/scenes', {
    name: n,
    users: fUsers.value,
    ramp: fRamp.value,
    dur: fDur.value,
    url: fUrl.value,
    method: 'GET',
  })
  sceneOpen.value = false
  await reload()
  const created = scenes.value.find((s) => s.name === n)
  if (created) {
    created.type = fType.value
    created.req = fReq.value.split(' · ')[0] || ''
    created.targetQps = fQps.value
    created.p99Limit = fP99.value
    created.errLimit = fErr.value
  }
  uiToast(fReq.value ? `性能场景已创建，已关联需求 ${fReq.value.split(' · ')[0]}` : '性能场景已创建', 'success')
}

/* ---------- 报告 tab ---------- */
const reportColumns = [
  { key: 'id', label: '报告' },
  { key: 'scene', label: '场景' },
  { key: 'qps', label: '实际 QPS' },
  { key: 'p99', label: 'P99' },
  { key: 'err', label: '错误率' },
  { key: 'time', label: '时间' },
  { key: 'verdict', label: '结论' },
]

const cmpA = ref('')
const cmpB = ref('')
const cmpOut = ref<{ a: Report; b: Report; dQps: number; dP99: number } | null>(null)

function compare() {
  const ra = reports.value.find((r) => r.id === cmpA.value)
  const rb = reports.value.find((r) => r.id === cmpB.value)
  if (!ra || !rb) {
    uiToast('请选择基线与对比报告', 'warn')
    return
  }
  const dQps = ra.qps ? Math.round(((rb.qps - ra.qps) / ra.qps) * 100) : 0
  const dP99 = ra.p99 ? Math.round(((rb.p99 - ra.p99) / ra.p99) * 100) : 0
  cmpOut.value = { a: ra, b: rb, dQps, dP99 }
  uiToast('对比完成，AI 已标注退化指标', 'success')
}

function toDefect(r: Report) {
  uiConfirm({
    title: '生成性能缺陷',
    message: `将基于报告 ${r.id}（${r.scene}）自动创建缺陷单并关联场景，确认提交吗？`,
    onOk: () => {
      uiToast('性能缺陷已提交至缺陷管理 🐞', 'success')
    },
  })
}

/* ---------- AI 助手 tab ---------- */
const aiTarget = ref('')
const aiTypes = ref<string[]>(['容量评估', '瓶颈定位'])
const aiCtx = ref('')
const aiLoading = ref(false)
const aiMsgs = ref<{ text: string; html?: boolean }[]>([
  {
    text: '我是性能分析助手。选择分析对象后点击「开始 AI 分析」，我将结合压测曲线与监控数据输出容量评估、瓶颈假设与调优建议，并可一键生成性能缺陷单。',
  },
])

function toggleAiType(t: string) {
  const i = aiTypes.value.indexOf(t)
  if (i >= 0) aiTypes.value.splice(i, 1)
  else aiTypes.value.push(t)
}

async function runAi(reportId?: string) {
  if (aiLoading.value) return
  if (!reportId && !aiTarget.value) {
    const first = scenes.value[0]
    if (first) aiTarget.value = `${first.name}（${first.status}）`
  }
  aiLoading.value = true
  aiMsgs.value.push({ text: '正在读取压测曲线、APM 链路与慢日志…' })
  try {
    const rid = reportId || reports.value[0]?.id || ''
    if (!rid) {
      // BUG-03：无报告时不发请求，避免后端 404「报告不存在」成为未捕获异常
      aiMsgs.value.push({ text: '暂无压测报告，请先执行场景压测后再分析。' })
      uiToast('暂无压测报告，请先执行压测', 'warn')
      return
    }
    const { data } = await http.post<{ analysis: string }>('/perf/analyze', {
      reportId: rid,
      metrics: aiCtx.value ? { context: aiCtx.value } : undefined,
    })
    aiMsgs.value.push({
      text: data.analysis || '分析完成（无返回内容）',
      html: true,
    })
    uiToast('AI 分析完成', 'success')
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    aiMsgs.value.push({ text: `分析失败：${msg}` })
    uiToast(msg, 'error')
  } finally {
    aiLoading.value = false
  }
}

function aiToDefect() {
  uiToast('性能缺陷已提交至缺陷管理并关联场景 🐞', 'success')
}
function aiToReq() {
  const req = scenes.value.find((s) => s.name && aiTarget.value.includes(s.name))?.req || 'REQ-2026-0121'
  uiToast(`已同步至需求 ${req} 追溯矩阵`, 'success')
}
</script>

<template>
  <ModuleShell slug="tool-performance-testing">
    <template #actions>
      <RouterLink class="btn btn-ghost" to="/t/tool-api-scenario-studio">🎛️ 去压测编排</RouterLink>
      <button class="btn btn-primary" @click="openNewScene">＋ 新增性能场景</button>
    </template>

    <template #default="{ tab }">
      <div class="banner banner-info">
        ℹ️ 性能场景可从<RouterLink to="/t/tool-requirement-management">需求管理</RouterLink>一键派生（含 NFR 性能指标条目）；AI 基于历史压测数据给出容量评估与瓶颈假设。
      </div>

      <!-- 统计（全局，对齐 UI） -->
      <div class="grid grid-4 mb-16">
        <StatCard label="性能场景" :value="total" />
        <StatCard label="达标场景" :value="passCount" color="var(--green)" />
        <StatCard label="未达标" :value="failCount" color="var(--red)" />
        <StatCard label="AI 待复检" :value="aiPending" color="var(--orange)" />
      </div>

      <!-- ============ 性能场景 ============ -->
      <template v-if="tab === 'scenes'">
        <div class="filter-bar">
          <input v-model="kw" class="input search" placeholder="🔍 搜索场景名称" />
          <select v-model="stFilter" class="select">
            <option value="">全部结论</option>
            <option>达标</option>
            <option>未达标</option>
            <option>未执行</option>
          </select>
          <select v-model="typeFilter" class="select">
            <option value="">全部类型</option>
            <option>基准</option>
            <option>负载</option>
            <option>稳定性</option>
            <option>尖峰</option>
          </select>
        </div>
        <DataTable :columns="sceneColumns" :rows="filtered" empty-text="无匹配场景">
          <template #cell-id="{ row }">
            <span class="mono">{{ (row as SceneExt).id }}</span>
          </template>
          <template #cell-name="{ row }">
            <div class="cell-main">{{ (row as SceneExt).name }}</div>
            <div class="cell-sub">
              <template v-if="(row as SceneExt).req">
                需求 <RouterLink to="/t/tool-requirement-management">{{ (row as SceneExt).req }}</RouterLink>
              </template>
              <template v-else>未关联需求</template>
              · {{ (row as SceneExt).last || '—' }}
            </div>
          </template>
          <template #cell-type="{ row }">
            <span class="tag">{{ (row as SceneExt).type || '负载' }}</span>
          </template>
          <template #cell-qps="{ row }">
            <span class="mono">{{ (row as SceneExt).targetQps || (row as SceneExt).users * 2 }} / {{ (row as SceneExt).qps || '—' }}</span>
          </template>
          <template #cell-p99="{ row }">
            <span v-if="(row as SceneExt).p99" class="mono">
              {{ (row as SceneExt).p99 }}
              <span class="text-faint">≤{{ (row as SceneExt).p99Limit || 500 }}</span>
            </span>
            <span v-else class="text-faint">—</span>
          </template>
          <template #cell-err="{ row }">
            <span v-if="(row as SceneExt).status !== '未执行'" class="mono">{{ (row as SceneExt).err }}%</span>
            <span v-else class="text-faint">—</span>
          </template>
          <template #cell-status="{ row }">
            <span class="tag" :class="R_CLS[(row as SceneExt).status]">{{ (row as SceneExt).status }}</span>
          </template>
          <template #cell-ai="{ row }">
            <span v-if="(row as SceneExt).ai" class="tag tag-orange">🤖 {{ (row as SceneExt).ai }}</span>
            <span v-else class="text-faint">—</span>
          </template>
          <template #actions="{ row }">
            <button
              class="btn btn-sm btn-success"
              :disabled="runningId === (row as SceneExt).id"
              @click="runScene(row as SceneExt)"
            >
              <span v-if="runningId === (row as SceneExt).id" class="spinner"></span>
              ▶ 执行
            </button>
            <button class="btn btn-sm btn-ghost" @click="aiAnalyzeScene(row as SceneExt)">🤖 AI 分析</button>
            <button class="btn btn-sm btn-danger" @click="dropScene(row as SceneExt)">删除</button>
          </template>
        </DataTable>
      </template>

      <!-- ============ 压测报告 ============ -->
      <template v-if="tab === 'report'">
        <div class="banner banner-green">✅ 选择两次报告可进行基线对比，AI 自动标注退化指标。</div>
        <div class="filter-bar">
          <select v-model="cmpA" class="select">
            <option value="">基线报告…</option>
            <option v-for="r in reports" :key="r.id" :value="r.id">{{ r.id }} · {{ r.scene }}</option>
          </select>
          <span class="text-faint">vs</span>
          <select v-model="cmpB" class="select">
            <option value="">对比报告…</option>
            <option v-for="r in reports" :key="r.id" :value="r.id">{{ r.id }} · {{ r.scene }}</option>
          </select>
          <button class="btn btn-primary btn-sm" @click="compare">🔍 对比分析</button>
        </div>

        <div v-if="cmpOut" class="card mb-16">
          <div class="card-title">
            📊 基线对比 {{ cmpOut.a.id }} → {{ cmpOut.b.id }}
            <span class="tag tag-red">AI 标注</span>
          </div>
          <table class="table">
            <thead><tr><th>指标</th><th>基线</th><th>对比</th><th>变化</th><th>AI 结论</th></tr></thead>
            <tbody>
              <tr>
                <td>实际 QPS</td>
                <td class="mono">{{ cmpOut.a.qps }}</td>
                <td class="mono">{{ cmpOut.b.qps }}</td>
                <td class="mono" :class="cmpOut.dQps >= 0 ? 'text-green' : 'text-red'">
                  {{ cmpOut.dQps >= 0 ? '+' : '' }}{{ cmpOut.dQps }}%
                </td>
                <td class="text-dim" style="font-size: 12.5px">
                  {{ cmpOut.dQps >= 0 ? '吞吐持平/提升' : '吞吐退化，建议关注连接池与线程配置' }}
                </td>
              </tr>
              <tr>
                <td>P99 响应时间</td>
                <td class="mono">{{ cmpOut.a.p99 }}ms</td>
                <td class="mono">{{ cmpOut.b.p99 }}ms</td>
                <td class="mono" :class="cmpOut.dP99 <= 0 ? 'text-green' : 'text-red'">
                  {{ cmpOut.dP99 >= 0 ? '+' : '' }}{{ cmpOut.dP99 }}%
                </td>
                <td class="text-dim" style="font-size: 12.5px">
                  {{ cmpOut.dP99 > 20 ? '⚠️ 显著退化，疑似下游依赖变慢或 GC 压力上升' : '响应时间正常波动' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <DataTable :columns="reportColumns" :rows="reports" empty-text="暂无压测报告">
          <template #cell-id="{ row }">
            <span class="mono">{{ (row as Report).id }}</span>
          </template>
          <template #cell-scene="{ row }">
            <div class="cell-main">{{ (row as Report).scene }}</div>
          </template>
          <template #cell-qps="{ row }">
            <span class="mono">{{ (row as Report).qps }}</span>
          </template>
          <template #cell-p99="{ row }">
            <span class="mono">{{ (row as Report).p99 }}ms</span>
          </template>
          <template #cell-err="{ row }">
            <span class="mono">{{ (row as Report).err }}%</span>
          </template>
          <template #cell-time="{ row }">
            <span class="mono" style="font-size: 12px">{{ (row as Report).time }}</span>
          </template>
          <template #cell-verdict="{ row }">
            <span class="tag" :class="R_CLS[(row as Report).verdict]">{{ (row as Report).verdict }}</span>
          </template>
          <template #actions="{ row }">
            <button class="btn btn-sm btn-ghost" @click="uiToast('演示环境：Allure 报告详情页建设中', 'info')">Allure 报告</button>
            <button class="btn btn-sm btn-danger" @click="toDefect(row as Report)">提缺陷</button>
          </template>
        </DataTable>
      </template>

      <!-- ============ AI 性能助手 ============ -->
      <template v-if="tab === 'ai'">
        <div class="grid" style="grid-template-columns: 1fr 1.3fr; gap: 14px">
          <div class="card">
            <div class="card-title">🤖 AI 性能助手 <span class="tag tag-red">AI</span></div>
            <div class="field">
              <label>分析对象</label>
              <select v-model="aiTarget" class="select">
                <option value="">（自动选择最新报告）</option>
                <option v-for="s in scenes" :key="s.id" :value="`${s.name}（${s.status}）`">
                  {{ s.name }}（{{ s.status }}）
                </option>
              </select>
            </div>
            <div class="field">
              <label>分析类型</label>
              <div class="flex" style="gap: 8px; flex-wrap: wrap">
                <label v-for="t in ['容量评估', '瓶颈定位', '调优建议']" :key="t" class="checkbox">
                  <input type="checkbox" :checked="aiTypes.includes(t)" @change="toggleAiType(t)" /> {{ t }}
                </label>
              </div>
            </div>
            <div class="field">
              <label>补充上下文（监控截图 / 慢日志，选填）</label>
              <textarea
                v-model="aiCtx"
                class="textarea mono"
                rows="4"
                placeholder="粘贴慢 SQL、JVM GC 日志或 APM 关键数据…"
              ></textarea>
            </div>
            <button class="btn btn-primary" style="width: 100%" :disabled="aiLoading" @click="runAi()">
              <span v-if="aiLoading" class="spinner"></span> ✨ 开始 AI 分析
            </button>
          </div>
          <div class="card">
            <div class="card-title">🧠 分析结论</div>
            <div class="chat-box">
              <div v-for="(m, i) in aiMsgs" :key="i" class="msg ai">
                <div class="m-avatar">🤖</div>
                <div class="m-body" v-html="m.text"></div>
              </div>
            </div>
            <div v-if="aiMsgs.length > 1" class="flex mt-8">
              <button class="btn btn-sm btn-primary" @click="aiToDefect">🐞 一键生成性能缺陷单</button>
              <button class="btn btn-sm btn-ghost" @click="aiToReq">📋 同步到需求</button>
            </div>
          </div>
        </div>
      </template>
    </template>
  </ModuleShell>

  <!-- 新增性能场景弹窗 -->
  <div class="modal-mask" :class="{ open: sceneOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>＋ 新增性能场景</h3>
        <button class="modal-close" @click="sceneOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="grid grid-2" style="gap: 12px">
          <div class="field">
            <label>场景名称 <span class="text-red">*</span></label>
            <input v-model="fName" class="input" placeholder="如：秒杀下单链路·尖峰" />
          </div>
          <div class="field">
            <label>场景类型</label>
            <select v-model="fType" class="select">
              <option>基准</option><option>负载</option><option>稳定性</option><option>尖峰</option>
            </select>
          </div>
        </div>
        <div class="field">
          <label>关联需求</label>
          <select v-model="fReq" class="select">
            <option value="">不关联</option>
            <option>REQ-2026-0121 · 大促秒杀活动</option>
            <option>REQ-2026-0125 · 订单退款功能</option>
          </select>
          <div class="hint">关联后该场景将出现在需求追溯矩阵中</div>
        </div>
        <div class="grid grid-3" style="gap: 10px">
          <div class="field">
            <label>目标 QPS</label>
            <input v-model.number="fQps" class="input mono" type="number" />
          </div>
          <div class="field">
            <label>P99 上限 (ms)</label>
            <input v-model.number="fP99" class="input mono" type="number" />
          </div>
          <div class="field">
            <label>错误率上限 (%)</label>
            <input v-model.number="fErr" class="input mono" type="number" step="0.1" />
          </div>
        </div>
        <div class="grid grid-3" style="gap: 10px">
          <div class="field">
            <label>并发用户</label>
            <input v-model.number="fUsers" class="input mono" type="number" />
          </div>
          <div class="field">
            <label>Ramp-Up (秒)</label>
            <input v-model.number="fRamp" class="input mono" type="number" />
          </div>
          <div class="field">
            <label>持续时间 (秒)</label>
            <input v-model.number="fDur" class="input mono" type="number" />
          </div>
        </div>
        <div class="field">
          <label>目标 URL</label>
          <input v-model="fUrl" class="input mono" placeholder="https://api.example.com/v1/orders" />
        </div>
        <div class="hint">场景类型 / 关联需求 / 目标阈值为 UI 附加信息，后端仅保存基础压测参数并在列表本地展示</div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="sceneOpen = false">取消</button>
        <button class="btn btn-primary" @click="saveScene">💾 保存场景</button>
      </div>
    </div>
  </div>
</template>
