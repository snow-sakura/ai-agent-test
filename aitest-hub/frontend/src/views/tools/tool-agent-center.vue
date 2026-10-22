<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import DataTable from '@/components/ui/DataTable.vue'
import { uiToast, uiConfirm } from '@/composables/ui'
import http from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-agent-center.html + backend agents.py） ---------- */
interface Agent {
  id: string
  name: string
  role: string
  cat: string
  icon: string
  model: string
  status: string
  tasksOk: number
  tasksFail: number
  last: string
  desc: string
  skills: string[]
  runs: number
  succ: number
}
interface TaskRow {
  id: string
  agentId: string
  kind: string
  title: string
  status: string
  progress: number
  started: string
  finished: string
  result: string
  logs: string
}
interface AgentStats {
  agentTotal: number
  online: number
  offline: number
  taskTotal: number
  taskOk: number
  taskFail: number
  taskRunning: number
  successRate: number
}

const C_CLS: Record<string, string> = {
  需求分析: 'tag-blue',
  测试用例: 'tag-red',
  接口测试: 'tag-purple',
  'UI 测试': 'tag-orange',
  数据生成: 'tag-green',
  性能测试: 'tag-blue',
  'APP 自动化': 'tag-orange',
}
const CATS = ['需求分析', '测试用例', '接口测试', 'UI 测试', '数据生成', '性能测试', 'APP 自动化']
const MODELS = ['DeepSeek-V3', '通义千问-Max', '硅基流动 · GLM-4']
const SKILL_OPTS = ['用例补充生成', '接口异常场景补全', '失败日志根因分析', 'UI 步骤脚本化']

const agents = ref<Agent[]>([])
const tasks = ref<TaskRow[]>([])
const stats = ref<AgentStats | null>(null)

const kw = ref('')
const cat = ref('')
const status = ref('')

async function reload() {
  const [a, t, s] = await Promise.all([
    http.get<Agent[]>('/agents'),
    http.get<TaskRow[]>('/agents/tasks'),
    http.get<AgentStats>('/agents/stats').catch(() => null),
  ])
  agents.value = a.data || []
  tasks.value = t.data || []
  stats.value = s?.data || null
}

onMounted(() => {
  void reload().catch(() => undefined)
})

const filtered = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return agents.value.filter(
    (a) =>
      (!k || (a.name + a.desc).toLowerCase().includes(k)) &&
      (!cat.value || (a.cat || a.role) === cat.value) &&
      (!status.value || a.status === status.value),
  )
})

/* 执行任务列表搜索：按 ID / Agent / 描述 / 模式 / 状态 / 输出过滤 */
const taskKw = ref('')
const filteredTasks = computed(() => {
  const q = taskKw.value.trim().toLowerCase()
  if (!q) return tasks.value
  return tasks.value.filter((t) =>
    [t.id, agentName(t.agentId), t.title, t.kind, t.started, t.status, t.result]
      .join(' ')
      .toLowerCase()
      .includes(q),
  )
})

function resetFilter() {
  kw.value = ''
  cat.value = ''
  status.value = ''
  uiToast('筛选已重置', 'info')
}

const taskColumns = [
  { key: 'id', label: 'ID' },
  { key: 'agent', label: 'Agent' },
  { key: 'title', label: '任务描述' },
  { key: 'kind', label: '模式' },
  { key: 'started', label: '时间' },
  { key: 'status', label: '结果' },
  { key: 'result', label: '输出' },
]

function agentName(id: string): string {
  const a = agents.value.find((x) => x.id === id)
  return a ? `${a.id} ${a.name}` : id
}

/* ---------- 执行任务 ---------- */
const execOpen = ref(false)
const execAgent = ref<Agent | null>(null)
const execTask = ref('')
const execMode = ref('快速')
const execNotify = ref(true)
const execBusy = ref(false)

function openExec(a: Agent) {
  if (a.status === '离线') {
    uiToast(`Agent「${a.name}」离线中，无法执行`, 'warn')
    return
  }
  execAgent.value = a
  execTask.value = ''
  execMode.value = '快速'
  execNotify.value = true
  execOpen.value = true
}

async function goExec() {
  const a = execAgent.value
  const task = execTask.value.trim()
  if (!a) return
  if (!task) {
    uiToast('请描述任务', 'error')
    return
  }
  execBusy.value = true
  try {
    uiToast(`Agent「${a.name}」开始执行（${execMode.value}模式）…`, 'info')
    await http.post(`/agents/${a.id}/run`, { task, kind: execMode.value })
    execOpen.value = false
    await reload()
    uiToast('任务执行成功 ✅' + (execNotify.value ? ' 通知已推送' : ''), 'success')
  } finally {
    execBusy.value = false
  }
}

/* ---------- Agent 日志 ---------- */
const logOpen = ref(false)
const logTitle = ref('')
const logBody = ref('')

function openLog(a: Agent) {
  logTitle.value = `Agent 日志 · ${a.name}`
  const last = tasks.value.find((t) => t.agentId === a.id)
  logBody.value =
    `[AGENT] ${a.id} ${a.name}（${a.model}）\n` +
    `[AGENT] 技能集：${a.skills.join('、') || '无'}\n` +
    (last
      ? `[TASK ] ${last.id} ${last.title}\n` +
        `[STAT ] ${last.status} · ${last.progress}%\n` +
        `[OUT  ] ${last.result || '—'}\n` +
        `[LOG  ]\n${last.logs || '—'}`
      : '[TASK ] 暂无任务记录')
  logOpen.value = true
}

async function stopTask(t: TaskRow) {
  await http.post(`/agents/tasks/${t.id}/stop`)
  await reload()
  uiToast('任务已停止', 'success')
}

/* ---------- 注册 Agent ---------- */
const regOpen = ref(false)
const regBusy = ref(false)
const fName = ref('')
const fCat = ref(CATS[1])
const fDesc = ref('')
const fModel = ref(MODELS[0])
const fSkills = ref<string[]>(['用例补充生成'])

function openReg() {
  fName.value = ''
  fCat.value = CATS[1]
  fDesc.value = ''
  fModel.value = MODELS[0]
  fSkills.value = ['用例补充生成']
  regOpen.value = true
}

async function saveAgent() {
  const n = fName.value.trim()
  if (!n) {
    uiToast('请填写 Agent 名称', 'error')
    return
  }
  regBusy.value = true
  try {
    await http.post('/agents', {
      name: n,
      role: fCat.value,
      desc: fDesc.value,
      model: fModel.value,
      status: '在线',
      skills: fSkills.value,
    })
    regOpen.value = false
    await reload()
    uiToast('Agent 已注册并上线', 'success')
  } finally {
    regBusy.value = false
  }
}

function dropAgent(a: Agent) {
  uiConfirm({
    title: '删除 Agent',
    message: `确定删除「${a.name}」吗？其任务记录将一并删除。`,
    onOk: async () => {
      await http.delete(`/agents/${a.id}`)
      await reload()
      uiToast('Agent 已删除', 'success')
    },
  })
}
</script>

<template>
  <ModuleShell slug="tool-agent-center">
    <template #actions>
      <RouterLink class="btn btn-ghost" to="/t/tool-workflow-editor">🔀 工作流编排</RouterLink>
      <RouterLink class="btn btn-ghost" to="/t/tool-skills-center">🛠️ Skills 技能中心</RouterLink>
      <button class="btn btn-primary" @click="openReg">＋ 注册 Agent</button>
    </template>

    <template #default="{ tab }">
      <div class="banner banner-info">
        ℹ️ 对应平台 AgentCenter 模块：每个 Agent 绑定模型（<RouterLink to="/t/tool-config-center">配置中心</RouterLink>按角色配置）+ 技能集
        + 可选<RouterLink to="/t/tool-workflow-editor">工作流</RouterLink>；执行任务自动调用技能与 MCP 工具，全过程写入
        <RouterLink to="/t/tool-log-center">日志中心</RouterLink>。
      </div>

      <!-- ============ Agent 编队 ============ -->
      <template v-if="tab === 'agents'">
        <div class="filter-bar">
          <input v-model="kw" class="input search" placeholder="🔍 搜索 Agent 名称 / 描述" />
          <select v-model="cat" class="select">
            <option value="">全部分类</option>
            <option v-for="c in CATS" :key="c" :value="c">{{ c }}</option>
          </select>
          <select v-model="status" class="select">
            <option value="">全部状态</option>
            <option>在线</option>
            <option>离线</option>
          </select>
          <button class="btn btn-ghost btn-sm" @click="resetFilter">重置</button>
        </div>

        <div class="grid grid-3">
          <div v-for="a in filtered" :key="a.id" class="card card-hover">
            <div class="flex-between">
              <span class="tag" :class="C_CLS[a.cat || a.role]">{{ a.cat || a.role }}</span>
              <span v-if="a.status === '在线'" class="tag tag-green">● 在线</span>
              <span v-else class="tag">○ 离线</span>
            </div>
            <h3 style="font-size: 15.5px; margin: 10px 0 6px">{{ a.icon || '🤖' }} {{ a.name }}</h3>
            <p class="text-dim" style="font-size: 12.5px">{{ a.desc }}</p>
            <div class="mt-8" style="font-size: 11.5px; color: var(--text-faint)">🧠 {{ a.model }}</div>
            <div class="mt-8">
              <span
                v-for="s in a.skills"
                :key="s"
                class="tag"
                style="margin-right: 4px; font-size: 10.5px"
              >🛠️ {{ s }}</span>
            </div>
            <div class="flex-between mt-16">
              <span class="text-faint" style="font-size: 11.5px">📊 {{ a.runs }} 次 · 成功率 {{ a.succ }}%</span>
              <div class="flex">
                <button class="btn btn-sm btn-ghost" @click="openLog(a)">日志</button>
                <button class="btn btn-sm btn-primary" @click="openExec(a)">执行任务</button>
                <button class="btn btn-sm btn-danger" @click="dropAgent(a)">删除</button>
              </div>
            </div>
          </div>
          <div v-if="!filtered.length" class="card" style="grid-column: 1 / -1">
            <div class="empty"><div class="e-icon">🤖</div><div class="e-text">无匹配 Agent</div></div>
          </div>
        </div>
      </template>

      <!-- ============ 任务记录 ============ -->
      <template v-if="tab === 'tasks'">
        <div class="banner">Agent 执行任务的留痕记录（自动写入📜日志中心，可按 Agent 查看完整日志）</div>
        <div class="grid grid-4 mb-16" v-if="stats">
          <div class="card stat-card">
            <div class="s-label">Agent 总数</div>
            <div class="s-value">{{ stats.agentTotal }}</div>
          </div>
          <div class="card stat-card">
            <div class="s-label">在线</div>
            <div class="s-value" style="color: var(--green)">{{ stats.online }}</div>
          </div>
          <div class="card stat-card">
            <div class="s-label">任务总数</div>
            <div class="s-value" style="color: var(--blue)">{{ stats.taskTotal }}</div>
          </div>
          <div class="card stat-card">
            <div class="s-label">成功率</div>
            <div class="s-value" style="color: var(--orange)">{{ stats.successRate }}%</div>
          </div>
        </div>
        <div class="flex mb-16" style="gap: 8px">
          <input
            v-model="taskKw"
            class="input"
            style="max-width: 320px"
            placeholder="🔍 搜索任务：ID / Agent / 描述 / 状态 / 输出"
          />
        </div>
        <DataTable :columns="taskColumns" :rows="filteredTasks" empty-text="暂无任务记录">
          <template #cell-id="{ row }">
            <span class="mono">{{ (row as TaskRow).id }}</span>
          </template>
          <template #cell-agent="{ row }">
            <div class="cell-main" style="font-size: 12.5px">{{ agentName((row as TaskRow).agentId) }}</div>
          </template>
          <template #cell-title="{ row }">
            <div class="cell-sub" style="font-size: 12px; max-width: 220px">{{ (row as TaskRow).title }}</div>
          </template>
          <template #cell-kind="{ row }">
            <span class="tag" :class="(row as TaskRow).kind === '深度' ? 'tag-purple' : ''">{{ (row as TaskRow).kind }}</span>
          </template>
          <template #cell-started="{ row }">
            <span class="mono" style="font-size: 12px">{{ (row as TaskRow).started }}</span>
          </template>
          <template #cell-status="{ row }">
            <span
              class="tag"
              :class="(row as TaskRow).status === '成功' ? 'tag-green' : (row as TaskRow).status === '失败' ? 'tag-red' : 'tag-orange'"
            >{{ (row as TaskRow).status }}</span>
          </template>
          <template #cell-result="{ row }">
            <div class="cell-sub" style="font-size: 12px; max-width: 180px">{{ (row as TaskRow).result || '—' }}</div>
          </template>
          <template #actions="{ row }">
            <div class="row-actions" style="opacity: 1">
              <button
                v-if="(row as TaskRow).status === '执行中'"
                class="btn btn-sm btn-danger"
                @click="stopTask(row as TaskRow)"
              >停止</button>
              <span v-else class="text-faint" style="font-size: 12px">—</span>
            </div>
          </template>
        </DataTable>
      </template>
    </template>
  </ModuleShell>

  <!-- 执行任务弹窗 -->
  <div class="modal-mask" :class="{ open: execOpen }">
    <div class="modal">
      <div class="modal-head">
        <h3>执行任务{{ execAgent ? ' · ' + execAgent.name : '' }}</h3>
        <button class="modal-close" @click="execOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="field">
          <label>任务描述 <span class="text-red">*</span></label>
          <textarea
            v-model="execTask"
            class="textarea"
            rows="3"
            placeholder="描述要让 Agent 完成的任务，如：为退款功能生成 20 条测试用例"
          ></textarea>
        </div>
        <div class="field">
          <label>执行模式</label>
          <div class="flex" style="gap: 14px">
            <label class="checkbox"><input v-model="execMode" type="radio" value="快速" /> 快速（单技能）</label>
            <label class="checkbox"><input v-model="execMode" type="radio" value="深度" /> 深度（走工作流）</label>
          </div>
        </div>
        <label class="checkbox"><input v-model="execNotify" type="checkbox" /> 完成后推送通知（企业微信）</label>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="execOpen = false">取消</button>
        <button class="btn btn-primary" :disabled="execBusy" @click="goExec">
          <span v-if="execBusy" class="spinner"></span> 🚀 执行
        </button>
      </div>
    </div>
  </div>

  <!-- Agent 日志弹窗 -->
  <div class="modal-mask" :class="{ open: logOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>{{ logTitle }}</h3>
        <button class="modal-close" @click="logOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="code-block" style="max-height: 320px; overflow-y: auto; white-space: pre-wrap">{{ logBody }}</div>
      </div>
      <div class="modal-foot">
        <RouterLink class="btn btn-ghost" to="/t/tool-log-center">📜 前往日志中心</RouterLink>
        <button class="btn btn-primary" @click="logOpen = false">关闭</button>
      </div>
    </div>
  </div>

  <!-- 注册 Agent 弹窗 -->
  <div class="modal-mask" :class="{ open: regOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>＋ 注册 Agent</h3>
        <button class="modal-close" @click="regOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="grid grid-2" style="gap: 12px">
          <div class="field">
            <label>Agent 名称 <span class="text-red">*</span></label>
            <input v-model="fName" class="input" placeholder="如：回归测试管家" />
          </div>
          <div class="field">
            <label>分类</label>
            <select v-model="fCat" class="select">
              <option v-for="c in CATS" :key="c" :value="c">{{ c }}</option>
            </select>
          </div>
        </div>
        <div class="field">
          <label>描述</label>
          <input v-model="fDesc" class="input" placeholder="Agent 职责说明" />
        </div>
        <div class="field">
          <label>绑定模型</label>
          <select v-model="fModel" class="select">
            <option v-for="m in MODELS" :key="m" :value="m">{{ m }}</option>
          </select>
        </div>
        <div class="field">
          <label>技能集（AI 关联）</label>
          <div class="flex" style="gap: 8px; flex-wrap: wrap">
            <label v-for="s in SKILL_OPTS" :key="s" class="checkbox">
              <input v-model="fSkills" type="checkbox" :value="s" /> {{ s }}
            </label>
          </div>
          <div class="hint">
            技能来自<RouterLink to="/t/tool-skills-center">Skills 技能中心</RouterLink>，执行时经 Function Calling 调用
          </div>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="regOpen = false">取消</button>
        <button class="btn btn-primary" :disabled="regBusy" @click="saveAgent">
          <span v-if="regBusy" class="spinner"></span> 💾 注册
        </button>
      </div>
    </div>
  </div>
</template>
