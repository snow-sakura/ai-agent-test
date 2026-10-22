<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import StatCard from '@/components/ui/StatCard.vue'
import { uiToast, uiConfirm } from '@/composables/ui'
import http from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-scheduler.html + scheduler） ---------- */
interface Task {
  id: string
  name: string
  type: string
  target: string
  mode: string
  cron: string
  notify: string
  status: string
  last: string
  next: string
  onlyFail: number | boolean
}
interface ExecLog {
  id: string
  taskId?: string
  task: string
  time: string
  dur: string
  result: string
  detail: string
}
interface Stats {
  total: number
  on: number
  today: number
  fail: number
}

const TYPE_CLS: Record<string, string> = {
  接口测试: 'tag-blue',
  'UI 自动化': 'tag-purple',
  'App 自动化': 'tag-orange',
  安全扫描: 'tag-red',
}
const TYPE_OPTS = ['接口测试', 'UI 自动化', 'App 自动化', '安全扫描']
const TARGET_OPTS = [
  { label: '接口套件：支付核心链路回归（12 条）', value: '支付核心链路回归（12 条）' },
  { label: 'UI 套件：主站冒烟（5 个场景）', value: '主站冒烟（5 个场景）' },
  { label: 'App 流水线：核心冒烟-小米12', value: '核心冒烟-小米12' },
  { label: '安全扫描：支付模块基线', value: '支付模块基线' },
]
const NOTIFY_OPTS = [
  { key: '邮件', label: '📧 邮件' },
  { key: '企业微信', label: '💬 企业微信' },
  { key: '钉钉', label: '🤖 钉钉' },
  { key: '飞书', label: '✈️ 飞书' },
]

const tasks = ref<Task[]>([])
const logs = ref<ExecLog[]>([])
const stats = ref<Stats | null>(null)

const kw = ref('')
const typeF = ref('')
const statusF = ref('')
const resultF = ref('')
const logDate = ref('') // 默认不过滤（历史数据不一定覆盖今天）

const filteredTasks = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return tasks.value.filter(
    (t) =>
      (!k || t.name.toLowerCase().includes(k)) &&
      (!typeF.value || t.type === typeF.value) &&
      (!statusF.value || t.status === statusF.value),
  )
})

const filteredLogs = computed(() =>
  logs.value.filter(
    (l) =>
      (!resultF.value || l.result === resultF.value) &&
      (!logDate.value || (l.time || '').startsWith(logDate.value)),
  ),
)

function resetFilter() {
  kw.value = ''
  typeF.value = ''
  statusF.value = ''
  uiToast('筛选已重置', 'info')
}

async function loadStats() {
  const { data } = await http.get<Stats>('/scheduler/stats')
  // BUG-02 防御：卸载后不再触碰响应式状态（检查须在赋值前，await 之后）
  if (disposed) return
  stats.value = data
}
async function loadTasks() {
  const { data } = await http.get<Task[]>('/scheduler/tasks', {
    params: { q: kw.value.trim(), type: typeF.value, status: statusF.value },
  })
  if (disposed) return
  tasks.value = data || []
}
async function loadLogs() {
  const { data } = await http.get<ExecLog[]>('/scheduler/logs', {
    params: { result: resultF.value },
  })
  if (disposed) return
  logs.value = data || []
}

async function reload() {
  // BUG-02 防御见各 loadXxx：组件已卸载（验证器快速切模块/路由）后不再触碰
  // 响应式状态，避免与 Vue patch 竞态产生
  // "Cannot destructure property 'type' of 'vnode' as it is null"
  await Promise.all([loadStats(), loadTasks(), loadLogs()])
}

/* ---------- 任务 CRUD ---------- */
const taskOpen = ref(false)
const taskTitle = ref('＋ 新建定时任务')
const editId = ref('')
/** 默认「单次」时间：明天凌晨 2 点（相对当前日期） */
function defaultOnce(): string {
  const d = new Date(Date.now() + 24 * 3600 * 1000)
  d.setHours(2, 0, 0, 0)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}
const form = ref({
  name: '',
  type: TYPE_OPTS[0],
  target: TARGET_OPTS[0].value,
  mode: 'cron',
  cron: '0 2 * * *',
  interval: 60,
  once: defaultOnce(),
  notifyFlags: { 邮件: true, 企业微信: true, 钉钉: false, 飞书: false },
  onlyFail: false,
})

function parseModeFromTask(t: Task) {
  form.value.mode = t.mode || 'cron'
  if (t.mode === 'interval') {
    const m = /(\d+)/.exec(t.cron || '')
    form.value.interval = m ? Number(m[1]) : 60
    form.value.cron = '0 * * * *'
  } else if (t.mode === 'once') {
    form.value.once = (t.cron || defaultOnce().replace('T', ' ')).replace(' ', 'T')
    form.value.cron = t.cron
  } else {
    form.value.cron = t.cron || '0 2 * * *'
  }
}

function buildNotifyString(): string {
  const on = NOTIFY_OPTS.filter((n) => form.value.notifyFlags[n.key as keyof typeof form.value.notifyFlags]).map(
    (n) => n.key,
  )
  return on.length ? on.join(' + ') : '邮件'
}

function parseNotifyFlags(s: string) {
  const f = form.value.notifyFlags
  f.邮件 = s.includes('邮件')
  f.企业微信 = s.includes('企业微信')
  f.钉钉 = s.includes('钉钉')
  f.飞书 = s.includes('飞书')
  if (!f.邮件 && !f.企业微信 && !f.钉钉 && !f.飞书) f.邮件 = true
}

function openCreate() {
  editId.value = ''
  taskTitle.value = '＋ 新建定时任务'
  form.value = {
    name: '',
    type: TYPE_OPTS[0],
    target: TARGET_OPTS[0].value,
    mode: 'cron',
    cron: '0 2 * * *',
    interval: 60,
    once: defaultOnce(),
    notifyFlags: { 邮件: true, 企业微信: true, 钉钉: false, 飞书: false },
    onlyFail: false,
  }
  taskOpen.value = true
}

function openEdit(t: Task) {
  editId.value = t.id
  taskTitle.value = '编辑任务 · ' + t.id
  form.value.name = t.name
  form.value.type = t.type
  form.value.target = t.target
  form.value.onlyFail = !!t.onlyFail
  parseNotifyFlags(t.notify || '')
  parseModeFromTask(t)
  taskOpen.value = true
}

function cronPayload(): string {
  const m = form.value.mode
  if (m === 'cron') return form.value.cron.trim()
  if (m === 'interval') return '每 ' + form.value.interval + ' 分钟'
  return form.value.once.replace('T', ' ')
}

async function saveTask() {
  const name = form.value.name.trim()
  if (!name) {
    uiToast('请填写任务名称', 'error')
    return
  }
  const payload = {
    name,
    type: form.value.type,
    target: form.value.target,
    mode: form.value.mode,
    cron: cronPayload(),
    notify: buildNotifyString(),
    onlyFail: form.value.onlyFail,
    status: '启用',
  }
  if (editId.value) {
    await http.put('/scheduler/tasks/' + editId.value, payload)
    if (disposed) return
    uiToast('定时任务已更新', 'success')
  } else {
    await http.post('/scheduler/tasks', payload)
    if (disposed) return
    uiToast('定时任务已创建并启用', 'success')
  }
  taskOpen.value = false
  await reload()
}

async function runTask(t: Task) {
  if (t.status !== '启用') {
    uiToast('任务已停用，请先启用', 'warn')
    return
  }
  uiToast('任务「' + t.name + '」已触发立即执行…', 'info')
  const { data } = await http.post<{ ok: boolean; result: string; dur: string; detail: string }>(
    '/scheduler/tasks/' + t.id + '/run',
  )
  if (disposed) return
  const ok = data.result === '成功'
  uiToast(ok ? '执行成功 ✅' : '执行失败 ❌ 已按通知策略推送', ok ? 'success' : 'error')
  await reload()
}

async function toggleTask(t: Task) {
  const next = t.status === '启用' ? '停用' : '启用'
  await http.put('/scheduler/tasks/' + t.id, { status: next })
  if (disposed) return
  uiToast('任务已' + next, 'success')
  await loadTasks()
}

function delTask(t: Task) {
  uiConfirm({
    title: '删除定时任务',
    message: '确定删除「' + t.name + '」吗？其历史执行日志将保留。',
    danger: true,
    onOk: async () => {
      await http.delete('/scheduler/tasks/' + t.id)
      if (disposed) return
      uiToast('任务已删除', 'success')
      await reload()
    },
  })
}

/* ---------- 日志详情 ---------- */
const logOpen = ref(false)
const logCur = ref<ExecLog | null>(null)

function logBody(l: ExecLog): string {
  const head =
    '[INFO] 调度器触发任务：' +
    l.task +
    '\n[INFO] 加载执行目标与上下文配置…\n[INFO] 开始执行（' +
    l.time +
    '）\n'
  if (l.result === '成功') {
    return head + '[INFO] 步骤全部完成 ✓\n[INFO] 汇总：' + l.detail + '\n[INFO] 通知推送完成\n[INFO] 任务结束'
  }
  return (
    head +
    '[WARN] 步骤 4 执行异常：元素未找到（重试 2 次仍失败）\n[INFO] 已截图 failure-step4.png\n[INFO] 汇总：' +
    l.detail +
    '\n[INFO] 通知推送完成\n[INFO] 任务结束'
  )
}

function openLog(l: ExecLog) {
  logCur.value = l
  logOpen.value = true
}

let kwTimer: ReturnType<typeof setTimeout> | undefined
let disposed = false
function onKw() {
  clearTimeout(kwTimer)
  kwTimer = setTimeout(() => {
    if (disposed) return
    void loadTasks()
  }, 200)
}

onMounted(() => {
  disposed = false
  void reload().catch(() => undefined)
})
onUnmounted(() => {
  disposed = true
  clearTimeout(kwTimer)
})
</script>

<template>
  <ModuleShell slug="tool-scheduler">
    <template #actions>
      <RouterLink class="btn btn-ghost" to="/t/tool-data-factory?tab=crontab">🏭 Crontab 工具</RouterLink>
      <button class="btn btn-primary" @click="openCreate">＋ 新建定时任务</button>
    </template>

    <template #default="{ tab }">
      <div class="banner banner-info">
        ℹ️ 参考 TestHub 定时任务：任务类型可选接口测试套件或 UI 自动化套件，按 Cron / 固定间隔 / 单次三种方式调度；执行完成自动推送邮件与
        Webhook 机器人，全部执行留痕可查日志。
      </div>

      <div class="grid grid-4 mb-16">
        <StatCard label="任务总数" :value="stats?.total ?? 0" />
        <StatCard label="启用中" :value="stats?.on ?? 0" color="var(--green)" />
        <StatCard label="今日触发" :value="stats?.today ?? 0" color="var(--blue)" />
        <StatCard label="最近失败" :value="stats?.fail ?? 0" color="var(--red)" />
      </div>

      <!-- ============ 任务列表 ============ -->
      <template v-if="tab === 'tasks'">
        <div class="filter-bar">
          <input v-model="kw" class="input search" placeholder="🔍 搜索任务名称" @input="onKw" />
          <select v-model="typeF" class="select" @change="loadTasks">
            <option value="">全部类型</option>
            <option v-for="t in TYPE_OPTS" :key="t" :value="t">{{ t }}</option>
          </select>
          <select v-model="statusF" class="select" @change="loadTasks">
            <option value="">全部状态</option>
            <option>启用</option>
            <option>停用</option>
          </select>
          <button class="btn btn-ghost btn-sm" @click="resetFilter">重置</button>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>任务</th>
                <th>类型</th>
                <th>调度</th>
                <th>通知</th>
                <th>最近执行</th>
                <th>下次执行</th>
                <th>状态</th>
                <th style="width: 250px">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!filteredTasks.length">
                <td colspan="8">
                  <div class="empty">
                    <div class="e-icon">⏰</div>
                    <div class="e-text">无匹配任务</div>
                  </div>
                </td>
              </tr>
              <tr v-for="t in filteredTasks" :key="t.id">
                <td>
                  <div class="cell-main">{{ t.name }}</div>
                  <div class="cell-sub mono">{{ t.id }} · {{ t.target }}</div>
                </td>
                <td><span class="tag" :class="TYPE_CLS[t.type] || 'tag'">{{ t.type }}</span></td>
                <td class="mono" style="font-size: 12px">
                  {{ t.cron }}
                  <span v-if="t.onlyFail" class="tag" style="font-size: 10.5px">仅失败通知</span>
                </td>
                <td class="cell-sub" style="font-size: 12px">{{ t.notify }}</td>
                <td class="cell-sub" style="font-size: 12px">{{ t.last }}</td>
                <td class="mono" style="font-size: 12px">{{ t.next }}</td>
                <td>
                  <span v-if="t.status === '启用'" class="tag tag-green">启用</span>
                  <span v-else class="tag">停用</span>
                </td>
                <td>
                  <div class="row-actions" style="opacity: 1">
                    <button class="btn btn-sm btn-success" @click="runTask(t)">▶ 立即执行</button>
                    <button class="btn btn-sm btn-ghost" @click="toggleTask(t)">
                      {{ t.status === '启用' ? '停用' : '启用' }}
                    </button>
                    <button class="btn btn-sm btn-ghost" @click="openEdit(t)">编辑</button>
                    <button class="btn btn-sm btn-danger" @click="delTask(t)">删除</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- ============ 执行日志 ============ -->
      <template v-if="tab === 'logs'">
        <div class="filter-bar">
          <select v-model="resultF" class="select" @change="loadLogs">
            <option value="">全部结果</option>
            <option>成功</option>
            <option>失败</option>
          </select>
          <input class="input" type="date" v-model="logDate" style="width: 160px" />
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>记录</th>
                <th>任务</th>
                <th>执行时间</th>
                <th>耗时</th>
                <th>结果</th>
                <th>摘要</th>
                <th style="width: 110px">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!filteredLogs.length">
                <td colspan="7">
                  <div class="empty">
                    <div class="e-icon">📜</div>
                    <div class="e-text">暂无执行日志</div>
                  </div>
                </td>
              </tr>
              <tr v-for="l in filteredLogs" :key="l.id">
                <td class="mono">{{ l.id }}</td>
                <td><div class="cell-main">{{ l.task }}</div></td>
                <td class="mono" style="font-size: 12px">{{ l.time }}</td>
                <td class="mono">{{ l.dur }}</td>
                <td>
                  <span v-if="l.result === '成功'" class="tag tag-green">成功</span>
                  <span v-else class="tag tag-red">失败</span>
                </td>
                <td class="cell-sub" style="font-size: 12px">{{ l.detail }}</td>
                <td>
                  <div class="row-actions" style="opacity: 1">
                    <button class="btn btn-sm btn-ghost" @click="openLog(l)">日志</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </template>
  </ModuleShell>

  <!-- 新建/编辑任务弹窗 -->
  <div class="modal-mask" :class="{ open: taskOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>{{ taskTitle }}</h3>
        <button class="modal-close" @click="taskOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="grid grid-2" style="gap: 12px">
          <div class="field">
            <label>任务名称 <span class="text-red">*</span></label>
            <input v-model="form.name" class="input" placeholder="如：每夜接口回归" />
          </div>
          <div class="field">
            <label>任务类型</label>
            <select v-model="form.type" class="select">
              <option v-for="t in TYPE_OPTS" :key="t" :value="t">{{ t }}</option>
            </select>
          </div>
        </div>
        <div class="field">
          <label>执行目标</label>
          <select v-model="form.target" class="select">
            <option v-for="o in TARGET_OPTS" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>
        </div>
        <div class="field">
          <label>调度方式</label>
          <div class="flex" style="gap: 14px; flex-wrap: wrap">
            <label class="checkbox">
              <input v-model="form.mode" type="radio" value="cron" /> Cron 表达式
            </label>
            <label class="checkbox">
              <input v-model="form.mode" type="radio" value="interval" /> 固定间隔
            </label>
            <label class="checkbox">
              <input v-model="form.mode" type="radio" value="once" /> 单次执行
            </label>
          </div>
        </div>
        <div v-if="form.mode === 'cron'" class="field">
          <label>Cron 表达式</label>
          <div class="input-group">
            <input v-model="form.cron" class="input mono" placeholder="分 时 日 月 周" />
            <button
              class="btn btn-ghost"
              type="button"
              @click="uiToast('解析：' + form.cron + '（演示）', 'info')"
            >
              解析
            </button>
          </div>
          <div class="hint">
            可在<RouterLink to="/t/tool-data-factory?tab=crontab">数据工厂 Crontab 工具</RouterLink>生成与验证
          </div>
        </div>
        <div v-if="form.mode === 'interval'" class="field">
          <label>间隔（分钟）</label>
          <input v-model.number="form.interval" class="input mono" type="number" min="5" />
        </div>
        <div v-if="form.mode === 'once'" class="field">
          <label>执行时间</label>
          <input v-model="form.once" class="input" type="datetime-local" />
        </div>
        <div class="field">
          <label>通知设置</label>
          <div class="flex" style="gap: 8px; flex-wrap: wrap">
            <label v-for="n in NOTIFY_OPTS" :key="n.key" class="checkbox">
              <input v-model="form.notifyFlags[n.key as '邮件']" type="checkbox" />
              {{ n.label }}
            </label>
          </div>
          <div class="hint">
            通知渠道在<RouterLink to="/t/tool-config-center?tab=notify">配置中心</RouterLink>维护；仅失败时通知可勾选「仅失败提醒」
          </div>
        </div>
        <label class="checkbox">
          <input v-model="form.onlyFail" type="checkbox" /> 仅失败时通知
        </label>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="taskOpen = false">取消</button>
        <button class="btn btn-primary" @click="saveTask">💾 保存任务</button>
      </div>
    </div>
  </div>

  <!-- 执行日志详情弹窗 -->
  <div class="modal-mask" :class="{ open: logOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>{{ logCur ? '执行日志 · ' + logCur.id : '执行日志' }}</h3>
        <button class="modal-close" @click="logOpen = false">✕</button>
      </div>
      <div v-if="logCur" class="modal-body">
        <div class="flex mb-16">
          <span class="tag tag-blue">{{ logCur.task }}</span>
          <span class="tag">{{ logCur.time }}</span>
          <span class="tag">⏱ {{ logCur.dur }}</span>
          <span v-if="logCur.result === '成功'" class="tag tag-green">成功</span>
          <span v-else class="tag tag-red">失败</span>
        </div>
        <div class="code-block" style="max-height: 300px; overflow-y: auto">{{ logBody(logCur) }}</div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-primary" @click="logOpen = false">关闭</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hint {
  font-size: 12px;
  color: var(--text-faint);
  margin-top: 5px;
}
.hint a {
  color: var(--blue);
}
</style>
