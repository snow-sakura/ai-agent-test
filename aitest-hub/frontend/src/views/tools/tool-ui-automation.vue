<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import DataTable from '@/components/ui/DataTable.vue'
import StatCard from '@/components/ui/StatCard.vue'
import { uiToast, uiConfirm } from '@/composables/ui'
import http from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-ui-automation.html + ui_automation.py） ---------- */
interface Step {
  action: string
  selector: string
  value: string
}
interface Scene {
  id: string
  name: string
  url: string
  status: string
  browser: string
  ssh: boolean
  steps: Step[]
  stepCount: number
  lastRun: string
  lastResult: string
}
interface RunRow {
  id: string
  scene: string
  sceneId: string
  time: string
  dur: string
  result: string
  steps: number
}
interface RunLogLine {
  i: number
  ok: boolean
  action: string
  text: string
}
interface RunDetail {
  run: RunRow
  log: RunLogLine[]
  screenshots: string[]
  recording: string
  message: string
}

const R_CLS: Record<string, string> = { 成功: 'tag-green', 失败: 'tag-red', 运行中: 'tag-orange' }
const S_CLS: Record<string, string> = { 启用: 'tag-blue', 停用: 'tag' }

const STEP_LIB: Record<string, { icon: string; label: string; ph: string }> = {
  goto: { icon: '🌐', label: '打开页面', ph: 'https://…' },
  fill: { icon: '⌨️', label: '输入', ph: '在 #username 输入 admin' },
  click: { icon: '👆', label: '点击', ph: '点击按钮「登录」' },
  llm: { icon: '🤖', label: 'LLM 操作', ph: 'AI 识别页面并点击「购物车」入口' },
  assert: { icon: '✅', label: '验证', ph: '断言页面包含「订单提交成功」' },
  wait: { icon: '⏱️', label: '等待', ph: '等待 2 秒 / 等待元素 .loading 消失' },
  upload: { icon: '📎', label: '上传', ph: '上传文件 ~/data/avatar.png 至 #file' },
}

const scenes = ref<Scene[]>([])
const runs = ref<RunRow[]>([])

const scKw = ref('')
const scStatus = ref('')
const runSceneFilter = ref('')
const runResult = ref('')

async function reload() {
  const [s, r] = await Promise.all([
    http.get<Scene[]>('/ui-automation/scenes'),
    http.get<RunRow[]>('/ui-automation/runs'),
  ])
  scenes.value = s.data || []
  runs.value = r.data || []
}

onMounted(() => {
  reload().catch(() => undefined)
})

/* ---------- 统计 ---------- */
const sceneCount = computed(() => scenes.value.length)
const okCount = computed(() => runs.value.filter((r) => r.result === '成功').length)
const failCount = computed(() => runs.value.filter((r) => r.result === '失败').length)
const runCount = computed(() => runs.value.length)

/* ---------- 场景表 ---------- */
const sceneColumns = [
  { key: 'name', label: '场景' },
  { key: 'browser', label: '浏览器' },
  { key: 'stepCount', label: '步骤数' },
  { key: 'lastRun', label: '最近执行' },
  { key: 'lastResult', label: '最近结果' },
  { key: 'status', label: '状态' },
]

const filteredScenes = computed(() => {
  const k = scKw.value.trim().toLowerCase()
  return scenes.value.filter(
    (s) =>
      (!k || (s.name + s.url).toLowerCase().includes(k)) &&
      (!scStatus.value || s.status === scStatus.value),
  )
})

const runningIds = ref<Set<string>>(new Set())

async function runScene(s: Scene) {
  if (runningIds.value.has(s.id)) return
  runningIds.value.add(s.id)
  uiToast(`场景「${s.name}」已提交无头执行…`, 'info')
  try {
    const { data } = await http.post<RunDetail>(`/ui-automation/scenes/${s.id}/run`)
    await reload()
    openRunDetail(data)
    uiToast(data.message || '执行完成', data.run?.result === '成功' ? 'success' : 'error')
  } finally {
    runningIds.value.delete(s.id)
  }
}

function dropScene(s: Scene) {
  uiConfirm({
    title: '删除场景',
    message: `确定删除场景「${s.name}」吗？其执行记录将保留。`,
    danger: true,
    onOk: async () => {
      await http.delete(`/ui-automation/scenes/${s.id}`)
      await reload()
      uiToast('场景已删除', 'success')
    },
  })
}

/* ---------- 新建/编辑场景向导 ---------- */
const sceneOpen = ref(false)
const nsCur = ref(1)
const editId = ref('')
const nsName = ref('')
const nsUrl = ref('')
const nsBrowser = ref('Chromium（无头）')
const nsSsh = ref(false)
const nsSteps = ref<Step[]>([])
const aiDesc = ref('')
const aiLoading = ref(false)

function openNewScene() {
  editId.value = ''
  nsName.value = ''
  nsUrl.value = ''
  nsBrowser.value = 'Chromium（无头）'
  nsSsh.value = false
  nsSteps.value = []
  aiDesc.value = ''
  nsCur.value = 1
  sceneOpen.value = true
}

function openEditScene(s: Scene) {
  editId.value = s.id
  nsName.value = s.name
  nsUrl.value = s.url
  nsBrowser.value = s.browser
  nsSsh.value = s.ssh
  nsSteps.value = s.steps.map((x) => ({ ...x }))
  aiDesc.value = ''
  nsCur.value = 1
  sceneOpen.value = true
}

function nsNext() {
  if (nsCur.value === 1) {
    if (!nsName.value.trim()) {
      uiToast('请填写场景名称', 'error')
      return
    }
    if (!/^https?:\/\//.test(nsUrl.value.trim())) {
      uiToast('请填写合法目标 URL', 'error')
      return
    }
  }
  if (nsCur.value < 3) {
    nsCur.value++
    return
  }
  saveScene().catch(() => undefined)
}

function nsPrev() {
  if (nsCur.value > 1) nsCur.value--
}

function addStep(action: string) {
  nsSteps.value.push({ action, selector: '', value: '' })
}
function delStep(i: number) {
  nsSteps.value.splice(i, 1)
}

async function saveScene() {
  const payload = {
    name: nsName.value.trim(),
    url: nsUrl.value.trim(),
    status: '启用',
    browser: nsBrowser.value,
    ssh: nsSsh.value,
    steps: nsSteps.value,
  }
  if (editId.value) {
    await http.put(`/ui-automation/scenes/${editId.value}`, payload)
    uiToast('场景已更新', 'success')
  } else {
    await http.post('/ui-automation/scenes', payload)
    uiToast('场景已创建', 'success')
  }
  sceneOpen.value = false
  await reload()
}

async function genAiSteps() {
  const d = aiDesc.value.trim()
  if (!d) {
    uiToast('请先描述自然语言步骤', 'error')
    return
  }
  aiLoading.value = true
  try {
    const { data } = await http.post<{ steps: Step[]; count: number; source: string }>(
      '/ui-automation/ai-steps',
      { desc: d, url: nsUrl.value },
    )
    nsSteps.value = data.steps || []
    uiToast(
      `AI 已生成 ${data.count} 步（${data.source === 'ai' ? 'AI' : '本地回退'}），请确认后保存`,
      'success',
    )
    nsCur.value = 2
  } finally {
    aiLoading.value = false
  }
}

/* ---------- 执行记录 ---------- */
const runColumns = [
  { key: 'id', label: '记录 ID' },
  { key: 'scene', label: '场景' },
  { key: 'time', label: '执行时间' },
  { key: 'dur', label: '耗时' },
  { key: 'steps', label: '步骤' },
  { key: 'result', label: '结果' },
]

const runKw = ref('')
const filteredRuns = computed(() => {
  const q = runKw.value.trim().toLowerCase()
  return runs.value.filter(
    (r) =>
      (!q || (r.id + r.scene + r.result + r.time).toLowerCase().includes(q)) &&
      (!runSceneFilter.value || r.sceneId === runSceneFilter.value) &&
      (!runResult.value || r.result === runResult.value),
  )
})

function resetRunFilters() {
  runSceneFilter.value = ''
  runResult.value = ''
  uiToast('筛选已重置', 'info')
}

const runOpen = ref(false)
const runDetail = ref<RunDetail | null>(null)
const replayPct = ref(0)
const replaying = ref(false)
let replayTimer: ReturnType<typeof setInterval> | null = null

function openRunDetail(d: RunDetail) {
  runDetail.value = d
  replayPct.value = 0
  replaying.value = false
  if (replayTimer) {
    clearInterval(replayTimer)
    replayTimer = null
  }
  runOpen.value = true
}

async function viewRun(id: string) {
  try {
    const { data } = await http.get<RunDetail>(`/ui-automation/runs/${id}`)
    openRunDetail(data)
  } catch {
    /* toast already handled by interceptor */
  }
}

function playReplay() {
  if (replaying.value) return
  replaying.value = true
  replayPct.value = 0
  replayTimer = setInterval(() => {
    replayPct.value += 4
    if (replayPct.value >= 100) {
      replayPct.value = 100
      replaying.value = false
      if (replayTimer) {
        clearInterval(replayTimer)
        replayTimer = null
      }
      setTimeout(() => (replayPct.value = 0), 400)
    }
  }, 120)
}

async function retryRun() {
  const d = runDetail.value
  if (!d) return
  runOpen.value = false
  const s = scenes.value.find((x) => x.id === d.run.sceneId)
  if (s) await runScene(s)
}

function stepIcon(action: string) {
  return STEP_LIB[action]?.icon || '•'
}
function stepPh(action: string) {
  return STEP_LIB[action]?.ph || ''
}
</script>

<template>
  <ModuleShell slug="tool-ui-automation">
    <template #actions>
      <RouterLink class="btn btn-ghost" to="/t/tool-app-automation">📱 App 自动化</RouterLink>
      <button class="btn btn-primary" @click="openNewScene">＋ 新建场景</button>
    </template>

    <template #default="{ tab }">
      <div class="banner banner-info">
        ℹ️ 本模块为 Web UI 自动化；App（Android · ADB/Appium）与桌面端（Windows）自动化能力独立开通，如需咨询请通过投稿 / 建议联系。
      </div>

      <!-- 统计 -->
      <div class="grid grid-4 mb-16">
        <StatCard label="场景" :value="sceneCount" />
        <StatCard label="执行记录" :value="runCount" color="var(--blue)" />
        <StatCard label="成功" :value="okCount" color="var(--green)" />
        <StatCard label="失败" :value="failCount" color="var(--red)" />
      </div>

      <!-- ============ 场景管理 ============ -->
      <template v-if="tab === 'scenes'">
        <div class="filter-bar">
          <input v-model="scKw" class="input search" placeholder="🔍 搜索场景名称 / URL" />
          <select v-model="scStatus" class="select">
            <option value="">全部状态</option>
            <option>启用</option>
            <option>停用</option>
          </select>
          <span class="text-faint" style="font-size: 12.5px">共 {{ filteredScenes.length }} 个场景</span>
        </div>
        <DataTable :columns="sceneColumns" :rows="filteredScenes" empty-text="无匹配场景">
          <template #cell-name="{ row }">
            <div class="cell-main">
              {{ (row as Scene).name }}
              <span v-if="(row as Scene).ssh" class="tag tag-purple" title="SSH 隧道">SSH</span>
            </div>
            <div class="cell-sub mono">{{ (row as Scene).url }}</div>
          </template>
          <template #cell-browser="{ row }">{{ (row as Scene).browser }}</template>
          <template #cell-stepCount="{ row }">
            <span class="mono">{{ (row as Scene).stepCount }}</span>
          </template>
          <template #cell-lastRun="{ row }">
            <span class="mono" style="font-size: 12.5px">{{ (row as Scene).lastRun }}</span>
          </template>
          <template #cell-lastResult="{ row }">
            <span v-if="(row as Scene).lastResult" class="tag" :class="R_CLS[(row as Scene).lastResult]">
              {{ (row as Scene).lastResult }}
            </span>
            <span v-else class="text-faint">—</span>
          </template>
          <template #cell-status="{ row }">
            <span class="tag" :class="S_CLS[(row as Scene).status]">{{ (row as Scene).status }}</span>
          </template>
          <template #actions="{ row }">
            <button
              class="btn btn-sm btn-success"
              :disabled="runningIds.has((row as Scene).id)"
              @click="runScene(row as Scene)"
            >
              <span v-if="runningIds.has((row as Scene).id)" class="spinner"></span>
              ▶ 执行
            </button>
            <button class="btn btn-sm btn-ghost" @click="openEditScene(row as Scene)">编辑</button>
            <button class="btn btn-sm btn-ghost" @click="dropScene(row as Scene)">删除</button>
          </template>
        </DataTable>
      </template>

      <!-- ============ 执行记录 ============ -->
      <template v-if="tab === 'runs'">
        <div class="filter-bar">
          <input v-model="runKw" class="input search" placeholder="🔍 搜索记录 ID / 场景 / 结果" />
          <select v-model="runSceneFilter" class="select">
            <option value="">全部场景</option>
            <option v-for="s in scenes" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
          <select v-model="runResult" class="select">
            <option value="">全部结果</option>
            <option>成功</option>
            <option>失败</option>
            <option>运行中</option>
          </select>
          <button class="btn btn-ghost btn-sm" @click="resetRunFilters">重置</button>
        </div>
        <DataTable :columns="runColumns" :rows="filteredRuns" empty-text="暂无执行记录">
          <template #cell-id="{ row }"><span class="mono">{{ (row as RunRow).id }}</span></template>
          <template #cell-scene="{ row }">
            <div class="cell-main">{{ (row as RunRow).scene }}</div>
          </template>
          <template #cell-time="{ row }">
            <span class="mono" style="font-size: 12.5px">{{ (row as RunRow).time }}</span>
          </template>
          <template #cell-dur="{ row }">
            <span class="mono">{{ (row as RunRow).dur }}</span>
          </template>
          <template #cell-steps="{ row }">
            <span class="mono">{{ (row as RunRow).steps }}</span>
          </template>
          <template #cell-result="{ row }">
            <span class="tag" :class="R_CLS[(row as RunRow).result]">{{ (row as RunRow).result }}</span>
          </template>
          <template #actions="{ row }">
            <button class="btn btn-sm btn-ghost" @click="viewRun((row as RunRow).id)">详情 / 回放</button>
          </template>
        </DataTable>
      </template>
    </template>
  </ModuleShell>

  <!-- 新建/编辑场景弹窗（3 步向导） -->
  <div class="modal-mask" :class="{ open: sceneOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>{{ editId ? '编辑场景 · ' + editId : '＋ 新建场景' }}</h3>
        <button class="modal-close" @click="sceneOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="steps mb-16">
          <div class="step" :class="{ active: nsCur === 1, done: nsCur > 1 }">
            <span class="s-num">1</span>基础信息
          </div>
          <div class="step-line"></div>
          <div class="step" :class="{ active: nsCur === 2, done: nsCur > 2 }">
            <span class="s-num">2</span>步骤编排
          </div>
          <div class="step-line"></div>
          <div class="step" :class="{ active: nsCur === 3 }">
            <span class="s-num">3</span>场景配置
          </div>
        </div>

        <!-- Step 1 -->
        <div v-if="nsCur === 1">
          <div class="field">
            <label>场景名称 <span class="text-red">*</span></label>
            <input v-model="nsName" class="input" placeholder="如：登录-下单-支付主流程" />
          </div>
          <div class="field">
            <label>目标 URL <span class="text-red">*</span></label>
            <input v-model="nsUrl" class="input mono" placeholder="https://shop.example.com/login" />
          </div>
          <div class="field">
            <label>浏览器</label>
            <select v-model="nsBrowser" class="select">
              <option>Chromium（无头）</option>
              <option>Chrome</option>
              <option>Firefox</option>
            </select>
          </div>
        </div>

        <!-- Step 2 -->
        <div v-if="nsCur === 2">
          <div style="display: flex; flex-direction: column; gap: 8px">
            <div
              v-for="(st, i) in nsSteps"
              :key="i"
              class="flex"
              style="gap: 8px"
            >
              <span class="tag tag-blue" style="min-width: 30px; justify-content: center">{{ i + 1 }}</span>
              <span
                class="n-icon"
                style="width: 30px; height: 30px; border-radius: 8px; display: grid; place-items: center; background: var(--bg-soft)"
              >{{ stepIcon(st.action) }}</span>
              <input v-model="st.value" class="input" :placeholder="stepPh(st.action)" style="flex: 1" />
              <input v-model="st.selector" class="input mono" placeholder="选择器（可选）" style="flex: 0.6" />
              <button class="btn btn-sm btn-ghost" @click="delStep(i)">✕</button>
            </div>
            <div v-if="!nsSteps.length" class="empty" style="padding: 20px">
              <div class="e-text text-faint">暂无步骤，从下方按钮添加</div>
            </div>
          </div>
          <div class="flex mt-8" style="gap: 6px; flex-wrap: wrap">
            <button
              v-for="(lib, key) in STEP_LIB"
              :key="key"
              class="btn btn-sm btn-ghost"
              @click="addStep(key)"
            >{{ lib.icon }} {{ lib.label }}</button>
          </div>
          <div class="mt-16">
            <div class="card-title" style="font-size: 13.5px">🤖 AI 生成步骤</div>
            <div class="input-group">
              <input
                v-model="aiDesc"
                class="input"
                placeholder="用自然语言描述流程，如：打开登录页，输入账号密码登录，进入订单列表并验证"
              />
              <button class="btn btn-primary" :disabled="aiLoading" @click="genAiSteps">
                <span v-if="aiLoading" class="spinner"></span> ✨ 生成
              </button>
            </div>
          </div>
        </div>

        <!-- Step 3 -->
        <div v-if="nsCur === 3">
          <div class="card mb-16" style="padding: 14px">
            <div class="card-title" style="font-size: 13.5px">🔐 登录步骤</div>
            <div class="grid grid-2" style="gap: 10px">
              <div class="field">
                <label>登录 URL</label>
                <input class="input mono" placeholder="https://shop.example.com/login" />
              </div>
              <div class="field">
                <label>凭证变量</label>
                <select class="select">
                  <option>使用公共变量 USER / PASS</option>
                  <option>手动输入</option>
                </select>
              </div>
            </div>
          </div>
          <div class="card" style="padding: 14px">
            <div class="card-title" style="font-size: 13.5px">
              🌐 内网 SSH 隧道 + CDP <span class="tag tag-purple">进阶</span>
            </div>
            <label class="checkbox mb-8">
              <input v-model="nsSsh" type="checkbox" /> 启用 SSH 隧道（内网站点）
            </label>
            <div class="grid grid-2" style="gap: 10px">
              <div class="field">
                <label>SSH 主机</label>
                <input
                  class="input mono"
                  placeholder="jump@10.0.0.5"
                  :disabled="!nsSsh"
                />
              </div>
              <div class="field">
                <label>CDP 端口（Chrome 9222）</label>
                <input class="input mono" placeholder="9222" :disabled="!nsSsh" />
              </div>
            </div>
            <div class="hint text-faint" style="font-size: 12px">
              开启后服务器经隧道映射内网 Chrome 9222，平台可直连调试
            </div>
          </div>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="sceneOpen = false">取消</button>
        <button v-if="nsCur > 1" class="btn btn-ghost" @click="nsPrev">← 上一步</button>
        <button class="btn btn-primary" @click="nsNext">
          {{ nsCur === 3 ? '💾 保存场景' : '下一步 →' }}
        </button>
      </div>
    </div>
  </div>

  <!-- 执行详情 / 回放弹窗 -->
  <div class="modal-mask" :class="{ open: runOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3 v-if="runDetail">执行详情 · {{ runDetail.run.id }}</h3>
        <h3 v-else>执行详情</h3>
        <button class="modal-close" @click="runOpen = false">✕</button>
      </div>
      <div class="modal-body" v-if="runDetail">
        <div class="flex mb-16">
          <span class="tag tag-blue">{{ runDetail.run.scene }}</span>
          <span class="tag">{{ runDetail.run.time }}</span>
          <span class="tag">⏱ {{ runDetail.run.dur }}</span>
          <span class="tag" :class="R_CLS[runDetail.run.result]">
            {{ runDetail.run.result === '成功' ? '✅ 成功' : '❌ ' + runDetail.run.result }}
          </span>
        </div>
        <div class="grid grid-2" style="gap: 12px">
          <div>
            <div class="card-title" style="font-size: 13.5px">📸 关键截图</div>
            <div class="grid grid-2" style="gap: 8px">
              <div
                v-for="(n, i) in runDetail.screenshots"
                :key="i"
                class="card"
                style="padding: 0; text-align: center; overflow: hidden"
              >
                <div
                  style="aspect-ratio: 16/10; display: grid; place-items: center; background: linear-gradient(135deg,#f3e8d8,#efe2cf); font-size: 22px"
                >🖼️</div>
                <div style="font-size: 11.5px; padding: 6px" class="text-faint">{{ n }}.png</div>
              </div>
            </div>
          </div>
          <div>
            <div class="card-title" style="font-size: 13.5px">🎥 录像回放</div>
            <div
              style="background: var(--bg-soft); border: 1px solid var(--border); border-radius: 10px; aspect-ratio: 16/9; display: grid; place-items: center; position: relative"
            >
              <div style="text-align: center">
                <div style="font-size: 34px">▶️</div>
                <div class="text-dim" style="font-size: 12.5px">{{ runDetail.recording }}</div>
                <button class="btn btn-primary btn-sm mt-8" :disabled="replaying" @click="playReplay">
                  {{ replaying ? '播放中…' : '播放录像' }}
                </button>
              </div>
              <div class="progress" style="position: absolute; bottom: 8px; left: 8px; right: 8px">
                <div class="bar" :style="{ width: replayPct + '%' }"></div>
              </div>
            </div>
            <div class="card-title mt-16" style="font-size: 13.5px">🧾 步骤结果</div>
            <div class="code-block" style="height: 120px; overflow-y: auto">
              <span class="c">// 步骤执行日志</span>
              <template v-for="(l, i) in runDetail.log" :key="i">
                <br />
                <span :class="l.ok ? 's' : 'n'">
                  {{ l.ok ? '✔' : '✖' }} [{{ l.i }}] {{ l.action }} {{ l.text }}
                </span>
              </template>
            </div>
          </div>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="retryRun">🔄 重新执行</button>
        <button class="btn btn-primary" @click="runOpen = false">关闭</button>
      </div>
    </div>
  </div>
</template>
