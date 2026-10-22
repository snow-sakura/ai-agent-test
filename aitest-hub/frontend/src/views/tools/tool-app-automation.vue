<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import DataTable from '@/components/ui/DataTable.vue'
import StatCard from '@/components/ui/StatCard.vue'
import { uiToast, uiConfirm } from '@/composables/ui'
import http from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-app-automation.html + app_automation_ui.py） ---------- */
interface Device {
  id: string
  udid: string
  name: string
  model: string
  android: string
  os: string
  res: string
  status: string
  ver: string
}
interface Package {
  id: string
  pkg: string
  ver: string
  size: string
  note: string
  time: string
  by: string
}
interface Script {
  id: string
  name: string
  fw: string
  pkg: string
  steps: string[]
  stepCount: number
  last: string
  upd: string
}
interface Pipeline {
  id: string
  name: string
  scriptIds: string[]
  device: string
  failPolicy: string
  createdAt: string
}
interface Job {
  id: string
  name: string
  scripts: string
  device: string
  status: string
  cur: number
  total: number
  time: string
  by: string
}
interface Timer {
  id: string
  name: string
  expr: string
  cron: string
  target: string
  pipeline: string
  last: string
  status: string
}

const ST_CLS: Record<string, string> = {
  在线: 'tag-green',
  离线: 'tag',
  执行中: 'tag-orange',
  运行中: 'tag-orange',
  成功: 'tag-green',
  失败: 'tag-red',
  排队中: 'tag-blue',
  启用: 'tag-green',
  停用: 'tag',
}

const devices = ref<Device[]>([])
const packages = ref<Package[]>([])
const scripts = ref<Script[]>([])
const pipelines = ref<Pipeline[]>([])
const jobs = ref<Job[]>([])
const timers = ref<Timer[]>([])

async function reload() {
  const [d, p, s, pl, j, t] = await Promise.all([
    http.get<Device[]>('/app-automation/devices'),
    http.get<Package[]>('/app-automation/packages'),
    http.get<Script[]>('/app-automation/scripts'),
    http.get<Pipeline[]>('/app-automation/pipelines'),
    http.get<Job[]>('/app-automation/jobs'),
    http.get<Timer[]>('/app-automation/timers'),
  ])
  devices.value = d.data || []
  packages.value = p.data || []
  scripts.value = s.data || []
  pipelines.value = pl.data || []
  jobs.value = j.data || []
  timers.value = t.data || []
}

onMounted(() => {
  reload().catch(() => undefined)
  loadElements().catch(() => undefined)
  loadElCats().catch(() => undefined)
})

/* ---------- 统计 ---------- */
const onlineCount = computed(() => devices.value.filter((d) => d.status !== '离线').length)
const apkCount = computed(() => packages.value.length)
const runningCount = computed(() => jobs.value.filter((j) => j.status === '运行中').length)
const timerOnCount = computed(() => timers.value.filter((t) => t.status === '启用').length)

/* ---------- 设备管理 ---------- */
const devKw = ref('')
const devStatus = ref('')

const devColumns = [
  { key: 'name', label: '设备' },
  { key: 'udid', label: 'UDID' },
  { key: 'os', label: '系统' },
  { key: 'res', label: '分辨率' },
  { key: 'status', label: '状态' },
]

const filteredDevices = computed(() => {
  const k = devKw.value.trim().toLowerCase()
  return devices.value.filter(
    (d) =>
      (!k || (d.name + d.udid).toLowerCase().includes(k)) &&
      (!devStatus.value || d.status === devStatus.value),
  )
})

function devInfo(d: Device) {
  uiToast(`设备 ${d.name}：SDK ${d.os} · ${d.res} · ${d.status}`, 'info')
}
function devShell(d: Device) {
  if (d.status === '离线') return
  uiToast('已打开 ADB Shell 会话（演示）', 'success')
}
function devLog(d: Device) {
  if (d.status === '离线') return
  uiToast('Logcat 流已接入（演示）', 'success')
}
function adbScan() {
  uiToast('正在执行 ADB devices 扫描…', 'info')
  setTimeout(() => {
    uiToast(`扫描完成：发现 ${onlineCount.value} 台在线设备`, 'success')
  }, 1200)
}

/* ---------- 应用包 ---------- */
const pkgColumns = [
  { key: 'pkg', label: '包名' },
  { key: 'ver', label: '版本' },
  { key: 'size', label: '大小' },
  { key: 'note', label: '备注' },
  { key: 'time', label: '上传' },
]

function installPkg(p: Package) {
  uiToast(`演示环境：${p.pkg} v${p.ver} 已安装到默认设备`, 'success')
}
function dropPkg(p: Package) {
  uiConfirm({
    title: '删除应用包',
    message: `确定删除 ${p.pkg} v${p.ver} 吗？关联脚本将失去默认包。`,
    danger: true,
    onOk: async () => {
      await http.delete(`/app-automation/packages/${encodeURIComponent(p.id)}`)
      await reload()
      uiToast('应用包已删除', 'success')
    },
  })
}

const apkOpen = ref(false)
const apkFile = ref<File | null>(null)
const apkNote = ref('')
const apkParsed = ref<{ pkg: string; ver: string } | null>(null)
/** 后端解析出的完整包结构信息（manifest / dex / abis / assets …） */
const apkInfo = ref<Record<string, any> | null>(null)
const apkBusy = ref(false)
const apkSaving = ref(false)

function openApk() {
  apkFile.value = null
  apkNote.value = ''
  apkParsed.value = null
  apkInfo.value = null
  apkBusy.value = false
  apkOpen.value = true
}

function onApkPick(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  if (!f) return
  if (!/\.(apk|aab)$/i.test(f.name)) {
    uiToast('仅支持 APK / AAB 文件', 'error')
    input.value = ''
    return
  }
  if (f.size > 500 * 1024 * 1024) {
    uiToast('应用包超过 500MB 限制', 'error')
    input.value = ''
    return
  }
  apkFile.value = f
  apkParsed.value = null
  apkInfo.value = null
  apkBusy.value = true
  // 真实上传到后端解析 AndroidManifest（dry_run=true 只解析不落库）
  const fd = new FormData()
  fd.append('file', f, f.name)
  fd.append('dry_run', 'true')
  http
    .post<Record<string, any>>('/app-automation/packages/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      silent: true,
    })
    .then(({ data }) => {
      apkInfo.value = data
      apkParsed.value = { pkg: data.pkg, ver: data.ver }
      uiToast(
        `解析完成：${data.pkg} v${data.ver}（${
          data.parsed_from === 'manifest' ? '来自 AndroidManifest' : '来自文件名'
        }）`,
        'success',
      )
    })
    .catch((err: any) => {
      uiToast(err?.message || '应用包解析失败', 'error')
      apkFile.value = null
    })
    .finally(() => {
      apkBusy.value = false
      input.value = ''
    })
}

async function saveApk() {
  if (!apkFile.value || !apkParsed.value) {
    uiToast('请先选择 APK / AAB 文件', 'error')
    return
  }
  apkSaving.value = true
  try {
    // 真实上传 APK 文件本体（后端再次解析并落库）
    const fd = new FormData()
    fd.append('file', apkFile.value, apkFile.value.name)
    fd.append('note', apkNote.value || '')
    await http.post('/app-automation/packages/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      silent: true, // 由下方 catch 统一提示，避免全局拦截器重复弹
    })
    apkOpen.value = false
    await reload()
    uiToast('应用包已上传并保存', 'success')
  } catch (err: any) {
    uiToast(err?.message || '应用包上传失败', 'error')
  } finally {
    apkSaving.value = false
  }
}

/* ---------- 自动化脚本 ---------- */
const scKw = ref('')
const scFw = ref('')

const scriptColumns = [
  { key: 'id', label: '编号' },
  { key: 'name', label: '脚本' },
  { key: 'fw', label: '框架' },
  { key: 'pkg', label: '目标包' },
  { key: 'stepCount', label: '步骤' },
  { key: 'last', label: '最近结果' },
  { key: 'upd', label: '更新' },
]

const filteredScripts = computed(() => {
  const k = scKw.value.trim().toLowerCase()
  return scripts.value.filter(
    (s) => (!k || s.name.toLowerCase().includes(k)) && (!scFw.value || s.fw === scFw.value),
  )
})

const runningScripts = ref<Set<string>>(new Set())

async function runScript(s: Script) {
  const online = devices.value.find((d) => d.status === '在线' || d.status === '执行中')
  if (!online) {
    uiToast('无在线设备，请先接入设备', 'error')
    return
  }
  if (runningScripts.value.has(s.id)) return
  runningScripts.value.add(s.id)
  uiToast(`脚本「${s.name}」已下发至 ${online.name} 执行…`, 'info')
  try {
    await http.post('/app-automation/jobs', {
      name: `${s.name}·单脚本`,
      scripts: s.name,
      device: online.name,
      status: '运行中',
      total: 1,
    })
    await reload()
    uiToast('脚本执行任务已创建，可在执行流水线查看进度', 'success')
  } finally {
    runningScripts.value.delete(s.id)
  }
}

const scriptOpen = ref(false)
const editScriptId = ref('')
const fsName = ref('')
const fsFw = ref('Appium')
const fsPkg = ref('com.example.shop')
const fsSteps = ref('')
const fsAiLoading = ref(false)

function openNewScript() {
  editScriptId.value = ''
  fsName.value = ''
  fsFw.value = 'Appium'
  fsPkg.value = packages.value[0]?.pkg || 'com.example.shop'
  fsSteps.value = ''
  scriptOpen.value = true
}

function openEditScript(s: Script) {
  editScriptId.value = s.id
  fsName.value = s.name
  fsFw.value = s.fw
  fsPkg.value = s.pkg
  fsSteps.value = s.steps.join('\n')
  scriptOpen.value = true
}

async function genScriptAi() {
  const d = fsName.value.trim() || fsSteps.value.trim()
  if (!d) {
    uiToast('请先填写脚本名称或目标描述', 'error')
    return
  }
  fsAiLoading.value = true
  try {
    const { data } = await http.post<{ steps: string[]; text: string; count: number; source: string }>(
      '/app-automation/ai-script',
      { desc: d, pkg: fsPkg.value },
    )
    fsSteps.value = data.text
    uiToast(`AI 已生成 ${data.count} 步脚本，请确认后保存`, 'success')
  } finally {
    fsAiLoading.value = false
  }
}

async function saveScript() {
  const n = fsName.value.trim()
  if (!n) {
    uiToast('请填写脚本名称', 'error')
    return
  }
  const steps = fsSteps.value
    .split('\n')
    .map((x) => x.trim())
    .filter(Boolean)
  if (editScriptId.value) {
    await http.put(`/app-automation/scripts/${editScriptId.value}`, {
      name: n,
      fw: fsFw.value,
      pkg: fsPkg.value,
      steps,
    })
    uiToast('脚本已更新', 'success')
  } else {
    await http.post('/app-automation/scripts', { name: n, fw: fsFw.value, pkg: fsPkg.value, steps })
    uiToast('脚本已保存', 'success')
  }
  scriptOpen.value = false
  await reload()
}

function dropScript(s: Script) {
  uiConfirm({
    title: '删除脚本',
    message: `确定删除脚本「${s.name}」吗？`,
    danger: true,
    onOk: async () => {
      await http.delete(`/app-automation/scripts/${s.id}`)
      await reload()
      uiToast('脚本已删除', 'success')
    },
  })
}

/* ---------- 执行流水线 ---------- */
const jobColumns = [
  { key: 'name', label: '流水线' },
  { key: 'scripts', label: '脚本' },
  { key: 'device', label: '设备' },
  { key: 'progress', label: '进度' },
  { key: 'status', label: '状态' },
  { key: 'by', label: '发起' },
]

const pipeOpen = ref(false)
const fpName = ref('')
const fpScripts = ref<string[]>([])
const fpDevice = ref('')
const fpFail = ref('失败即中止')

function openPipeline() {
  fpName.value = ''
  fpScripts.value = []
  fpDevice.value = devices.value.find((d) => d.status !== '离线')?.name || ''
  fpFail.value = '失败即中止'
  pipeOpen.value = true
}

function toggleFpScript(id: string) {
  const i = fpScripts.value.indexOf(id)
  if (i >= 0) fpScripts.value.splice(i, 1)
  else fpScripts.value.push(id)
}

async function savePipeline() {
  const n = fpName.value.trim()
  if (!n) {
    uiToast('请填写流水线名称', 'error')
    return
  }
  if (!fpScripts.value.length) {
    uiToast('请至少选择一个脚本', 'warn')
    return
  }
  const dev = devices.value.find((d) => d.name === fpDevice.value)
  if (dev && dev.status === '离线') {
    uiToast('该设备离线，请选择在线设备', 'error')
    return
  }
  await http.post('/app-automation/pipelines', {
    name: n,
    script_ids: fpScripts.value,
    device: fpDevice.value,
    fail_policy: fpFail.value,
    run: true,
  })
  pipeOpen.value = false
  await reload()
  uiToast('流水线已创建并开始执行', 'success')
}

const jobOpen = ref(false)
const jobDetail = ref<Job | null>(null)

function jobLog(j: Job) {
  const fail = j.status === '失败'
  return (
    `[INFO] 设备连接成功：${j.device}\n` +
    `[INFO] 安装应用包 com.example.shop v3.2.1\n` +
    `[INFO] 启动 Appium 会话…\n` +
    `[INFO] 步骤 1/${j.total || 1}：启动应用 ✓\n` +
    (fail
      ? `[ERROR] 步骤执行失败\n[WARN] 已截图 failure.png\n[INFO] 流水线按失败策略结束`
      : `[INFO] 全部 ${j.total} 步执行完成 ✓\n[INFO] 流水线执行成功`)
  )
}

function openJob(j: Job) {
  jobDetail.value = j
  jobOpen.value = true
}

async function stopJob(j: Job) {
  uiConfirm({
    title: '取消流水线',
    message: `确定取消执行中的流水线「${j.name}」吗？`,
    danger: true,
    onOk: async () => {
      await http.post(`/app-automation/jobs/${j.id}/stop`)
      await reload()
      uiToast('流水线已取消', 'warn')
    },
  })
}

async function retryJob() {
  const j = jobDetail.value
  if (!j) return
  jobOpen.value = false
  await http.put(`/app-automation/jobs/${j.id}`, { status: '运行中', cur: 0 })
  await reload()
  uiToast('流水线已重新执行', 'info')
}

/* ---------- 定时任务 ---------- */
const timerColumns = [
  { key: 'name', label: '任务' },
  { key: 'cron', label: 'Cron' },
  { key: 'pipeline', label: '关联流水线' },
  { key: 'last', label: '最近触发' },
  { key: 'status', label: '状态' },
]

const timerOpen = ref(false)
const ftName = ref('')
const ftCron = ref('')
const ftPipeline = ref('')

function openTimer() {
  ftName.value = ''
  ftCron.value = ''
  ftPipeline.value = pipelines.value[0]?.name || jobs.value[0]?.name || ''
  timerOpen.value = true
}

async function saveTimer() {
  const n = ftName.value.trim()
  const cron = ftCron.value.trim()
  if (!n) {
    uiToast('请填写任务名称', 'error')
    return
  }
  if (!/^[\d\*\/\,\-\s]+$/.test(cron)) {
    uiToast('Cron 表达式格式不正确', 'error')
    return
  }
  await http.post('/app-automation/timers', { name: n, cron, pipeline: ftPipeline.value })
  timerOpen.value = false
  await reload()
  uiToast('定时任务已创建', 'success')
}

async function toggleTimer(t: Timer) {
  const next = t.status === '启用' ? '停用' : '启用'
  await http.put(`/app-automation/timers/${t.id}`, { status: next })
  await reload()
  uiToast(`任务已${next}`, 'success')
}

function dropTimer(t: Timer) {
  uiConfirm({
    title: '删除定时任务',
    message: `确定删除定时任务「${t.name}」吗？`,
    danger: true,
    onOk: async () => {
      await http.delete(`/app-automation/timers/${t.id}`)
      await reload()
      uiToast('定时任务已删除', 'success')
    },
  })
}

/* ---------- 元素库（元素截图模板上传 + 元素记录管理） ---------- */
interface ElementRow {
  id: number
  name: string
  element_type: string
  tags: string[]
  config: Record<string, any>
  updated_at: string | null
}
const elements = ref<ElementRow[]>([])
const elQ = ref('')
const elCats = ref<{ name: string; image_count: number }[]>([])
const elCat = ref('common')
const elBusy = ref(false)
const elNewCat = ref('')

const elColumns = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: '名称' },
  { key: 'element_type', label: '类型' },
  { key: 'tags', label: '标签' },
  { key: 'image', label: '截图' },
  { key: 'updated_at', label: '更新时间' },
  { key: 'actions', label: '操作' },
]

async function loadElements() {
  try {
    const r = await http.get<ElementRow[]>('/app-automation/elements', {
      params: { q: elQ.value.trim() },
    })
    elements.value = r.data || []
  } catch {
    /* 列表加载失败保持空态 */
  }
}

async function loadElCats() {
  try {
    const r = await http.get<{ name: string; image_count: number }[]>(
      '/app-automation/elements/image-categories',
    )
    elCats.value = r.data || []
    if (elCats.value.length && !elCats.value.some((c) => c.name === elCat.value)) {
      elCat.value = elCats.value[0].name
    }
  } catch {
    /* 分类加载失败保持默认 */
  }
}

/* 上传元素截图 → 自动登记为 image 类型元素,列表即可管理 */
async function onElPick(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  input.value = ''
  if (!f) return
  if (!/^image\/(png|jpe?g)$/.test(f.type)) {
    uiToast('仅支持 PNG / JPG 图片模板', 'error')
    return
  }
  if (f.size > 5 * 1024 * 1024) {
    uiToast('图片超过 5MB 限制', 'error')
    return
  }
  elBusy.value = true
  try {
    const fd = new FormData()
    fd.append('file', f, f.name)
    fd.append('category', elCat.value)
    const up = await http.post<{
      success: boolean
      image_path: string
      image_category: string
      image_url?: string
      url: string
      file_hash: string
    }>('/app-automation/elements/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    let name = f.name.replace(/\.[^.]+$/, '')
    let n = 1
    while (elements.value.some((x) => x.name === name)) name = `${f.name.replace(/\.[^.]+$/, '')}-${++n}`
    await http.post('/app-automation/elements', {
      name,
      element_type: 'image',
      tags: [up.data.image_category],
      config: {
        image: up.data.url,
        image_path: up.data.image_path,
        image_category: up.data.image_category,
      },
    })
    await Promise.all([loadElements(), loadElCats()])
    uiToast(`已上传并登记元素：${name}`, 'success')
  } catch (err: any) {
    const detail = err?.response?.data?.detail || err?.message || ''
    uiToast('元素上传失败' + (detail ? '：' + detail : ''), 'error')
  } finally {
    elBusy.value = false
  }
}

async function addElCat() {
  const n = elNewCat.value.trim()
  if (!n) {
    uiToast('请填写分类名', 'error')
    return
  }
  if (!/^[a-zA-Z0-9_-]+$/.test(n)) {
    uiToast('分类名仅支持字母 / 数字 / - / _', 'error')
    return
  }
  try {
    await http.post('/app-automation/elements/image-categories/create', { name: n })
    elNewCat.value = ''
    elCat.value = n
    await loadElCats()
    uiToast(`分类「${n}」已创建`, 'success')
  } catch (err: any) {
    const detail = err?.response?.data?.detail || err?.message || ''
    uiToast('创建分类失败' + (detail ? '：' + detail : ''), 'error')
  }
}

function dropElement(row: ElementRow) {
  uiConfirm({
    title: '删除元素',
    message: `确定删除元素「${row.name}」吗？`,
    danger: true,
    onOk: async () => {
      await http.delete(`/app-automation/elements/${row.id}`)
      await Promise.all([loadElements(), loadElCats()])
      uiToast('元素已删除', 'success')
    },
  })
}
</script>

<template>
  <ModuleShell slug="tool-app-automation">
    <template #actions>
      <button class="btn btn-ghost" @click="openApk">📦 上传应用包</button>
      <button class="btn btn-primary" @click="openNewScript">＋ 新建自动化脚本</button>
    </template>

    <template #default="{ tab }">
      <!-- 统计 -->
      <div class="grid grid-4 mb-16">
        <StatCard label="在线设备" :value="onlineCount" />
        <StatCard label="应用包" :value="apkCount" color="var(--blue)" />
        <StatCard label="执行中" :value="runningCount" color="var(--orange)" />
        <StatCard label="启用定时" :value="timerOnCount" color="var(--green)" />
      </div>

      <!-- ============ 设备管理 ============ -->
      <template v-if="tab === 'devices'">
        <div class="filter-bar">
          <input v-model="devKw" class="input search" placeholder="🔍 搜索设备名称 / UDID" />
          <select v-model="devStatus" class="select">
            <option value="">全部状态</option>
            <option>在线</option>
            <option>离线</option>
            <option>执行中</option>
          </select>
          <button class="btn btn-ghost btn-sm" @click="adbScan">🔄 ADB 扫描设备</button>
        </div>
        <DataTable :columns="devColumns" :rows="filteredDevices" empty-text="无匹配设备">
          <template #cell-name="{ row }">
            <div class="cell-main">{{ (row as Device).name }}</div>
            <div v-if="(row as Device).ver" class="cell-sub">{{ (row as Device).ver }}</div>
          </template>
          <template #cell-udid="{ row }">
            <span class="mono" style="font-size: 12px">{{ (row as Device).udid }}</span>
          </template>
          <template #cell-os="{ row }">{{ (row as Device).os }}</template>
          <template #cell-res="{ row }">
            <span class="mono" style="font-size: 12px">{{ (row as Device).res }}</span>
          </template>
          <template #cell-status="{ row }">
            <span class="tag" :class="ST_CLS[(row as Device).status]">{{ (row as Device).status }}</span>
          </template>
          <template #actions="{ row }">
            <button class="btn btn-sm btn-ghost" @click="devInfo(row as Device)">详情</button>
            <button
              class="btn btn-sm btn-ghost"
              :disabled="(row as Device).status === '离线'"
              @click="devShell(row as Device)"
            >Shell</button>
            <button
              class="btn btn-sm btn-ghost"
              :disabled="(row as Device).status === '离线'"
              @click="devLog(row as Device)"
            >Logcat</button>
          </template>
        </DataTable>
      </template>

      <!-- ============ 应用包 ============ -->
      <template v-if="tab === 'apps'">
        <div class="flex mb-16" style="justify-content: flex-end">
          <button class="btn btn-primary" @click="openApk">📦 上传应用包</button>
        </div>
        <DataTable :columns="pkgColumns" :rows="packages" empty-text="暂无应用包">
          <template #cell-pkg="{ row }"><span class="mono">{{ (row as Package).pkg }}</span></template>
          <template #cell-ver="{ row }">
            <span class="tag tag-blue">v{{ (row as Package).ver }}</span>
          </template>
          <template #cell-size="{ row }"><span class="mono">{{ (row as Package).size }}</span></template>
          <template #cell-note="{ row }">{{ (row as Package).note }}</template>
          <template #cell-time="{ row }">
            <div class="cell-sub">{{ (row as Package).by }} · {{ (row as Package).time }}</div>
          </template>
          <template #actions="{ row }">
            <button class="btn btn-sm btn-ghost" @click="installPkg(row as Package)">安装</button>
            <button class="btn btn-sm btn-danger" @click="dropPkg(row as Package)">删除</button>
          </template>
        </DataTable>
      </template>

      <!-- ============ 自动化脚本 ============ -->
      <template v-if="tab === 'scripts'">
        <div class="filter-bar">
          <input v-model="scKw" class="input search" placeholder="🔍 搜索脚本名称" />
          <select v-model="scFw" class="select">
            <option value="">全部框架</option>
            <option>Appium</option>
            <option>ADB 原生</option>
            <option>Python 脚本</option>
          </select>
        </div>
        <DataTable :columns="scriptColumns" :rows="filteredScripts" empty-text="无匹配脚本">
          <template #cell-id="{ row }"><span class="mono">{{ (row as Script).id }}</span></template>
          <template #cell-name="{ row }">
            <div class="cell-main">{{ (row as Script).name }}</div>
          </template>
          <template #cell-fw="{ row }"><span class="tag">{{ (row as Script).fw }}</span></template>
          <template #cell-pkg="{ row }">
            <span class="mono" style="font-size: 12px">{{ (row as Script).pkg }}</span>
          </template>
          <template #cell-stepCount="{ row }">
            <span class="mono">{{ (row as Script).stepCount }}</span>
          </template>
          <template #cell-last="{ row }">
            <span class="tag" :class="ST_CLS[(row as Script).last]">{{ (row as Script).last }}</span>
          </template>
          <template #cell-upd="{ row }">
            <span class="mono" style="font-size: 12px">{{ (row as Script).upd }}</span>
          </template>
          <template #actions="{ row }">
            <button
              class="btn btn-sm btn-success"
              :disabled="runningScripts.has((row as Script).id)"
              @click="runScript(row as Script)"
            >
              <span v-if="runningScripts.has((row as Script).id)" class="spinner"></span>
              ▶ 执行
            </button>
            <button class="btn btn-sm btn-ghost" @click="openEditScript(row as Script)">编辑</button>
            <button class="btn btn-sm btn-danger" @click="dropScript(row as Script)">删除</button>
          </template>
        </DataTable>
      </template>

      <!-- ============ 执行流水线 ============ -->
      <template v-if="tab === 'jobs'">
        <div class="banner banner-info">
          ℹ️ 流水线 = 选择脚本 × 选择设备 × 依次执行；执行完成后可查看日志、截图与运行结果。
        </div>
        <div class="flex mb-16" style="justify-content: flex-end">
          <button class="btn btn-primary" @click="openPipeline">＋ 新建流水线</button>
        </div>
        <DataTable :columns="jobColumns" :rows="jobs" empty-text="暂无流水线执行记录">
          <template #cell-name="{ row }">
            <div class="cell-main">{{ (row as Job).name }}</div>
            <div class="cell-sub">{{ (row as Job).id }} · {{ (row as Job).time }}</div>
          </template>
          <template #cell-scripts="{ row }">{{ (row as Job).scripts }}</template>
          <template #cell-device="{ row }">{{ (row as Job).device }}</template>
          <template #cell-progress="{ row }">
            <div class="flex">
              <div class="progress" style="width: 80px">
                <div
                  class="bar"
                  :style="{
                    width:
                      Math.round(((row as Job).cur / Math.max(1, (row as Job).total)) * 100) + '%',
                  }"
                ></div>
              </div>
              <span class="mono" style="font-size: 11.5px">
                {{ (row as Job).cur }}/{{ (row as Job).total }}
              </span>
            </div>
          </template>
          <template #cell-status="{ row }">
            <span class="tag" :class="ST_CLS[(row as Job).status]">{{ (row as Job).status }}</span>
          </template>
          <template #cell-by="{ row }">{{ (row as Job).by }}</template>
          <template #actions="{ row }">
            <button class="btn btn-sm btn-ghost" @click="openJob(row as Job)">详情</button>
            <button
              v-if="(row as Job).status === '运行中'"
              class="btn btn-sm btn-danger"
              @click="stopJob(row as Job)"
            >取消</button>
          </template>
        </DataTable>
      </template>

      <!-- ============ 定时任务 ============ -->
      <template v-if="tab === 'timer'">
        <div class="flex mb-16" style="justify-content: flex-end">
          <button class="btn btn-primary" @click="openTimer">＋ 新建定时任务</button>
        </div>
        <DataTable :columns="timerColumns" :rows="timers" empty-text="暂无定时任务">
          <template #cell-name="{ row }">
            <div class="cell-main">{{ (row as Timer).name }}</div>
            <div class="cell-sub">{{ (row as Timer).id }}</div>
          </template>
          <template #cell-cron="{ row }"><span class="mono">{{ (row as Timer).cron }}</span></template>
          <template #cell-pipeline="{ row }">{{ (row as Timer).pipeline }}</template>
          <template #cell-last="{ row }">
            <span class="cell-sub">{{ (row as Timer).last }}</span>
          </template>
          <template #cell-status="{ row }">
            <span class="tag" :class="ST_CLS[(row as Timer).status]">{{ (row as Timer).status }}</span>
          </template>
          <template #actions="{ row }">
            <button class="btn btn-sm btn-ghost" @click="toggleTimer(row as Timer)">
              {{ (row as Timer).status === '启用' ? '停用' : '启用' }}
            </button>
            <button class="btn btn-sm btn-danger" @click="dropTimer(row as Timer)">删除</button>
          </template>
        </DataTable>
      </template>

      <!-- ============ 元素库（元素截图模板上传） ============ -->
      <template v-if="tab === 'elements'">
        <div class="grid" style="grid-template-columns: 340px 1fr">
          <div class="card">
            <div class="card-title">⬆️ 上传元素截图模板</div>
            <div class="field">
              <label>图片分类</label>
              <select v-model="elCat" class="select">
                <option v-for="c in elCats" :key="c.name" :value="c.name">
                  {{ c.name }}（{{ c.image_count }} 张）
                </option>
              </select>
            </div>
            <label
              class="card"
              style="border-style: dashed; text-align: center; padding: 26px; cursor: pointer; display: block"
            >
              <div style="font-size: 28px">🖼️</div>
              <div class="text-dim mt-8" style="font-size: 12.5px">点击选择元素截图（PNG / JPG）</div>
              <div class="text-faint" style="font-size: 11.5px">≤ 5MB，上传后自动登记为 image 元素</div>
              <input
                type="file"
                accept="image/png,image/jpeg"
                style="display: none"
                @change="onElPick"
              />
            </label>
            <div v-if="elBusy" class="mt-8 text-dim" style="font-size: 12.5px">
              <span class="spinner"></span> 上传中…
            </div>
            <div class="field mt-16">
              <label>新建图片分类</label>
              <div class="flex" style="gap: 8px">
                <input v-model="elNewCat" class="input" placeholder="如：login" />
                <button class="btn btn-ghost btn-sm" @click="addElCat">创建</button>
              </div>
            </div>
          </div>
          <div class="card">
            <div class="card-title" style="display: flex; justify-content: space-between; align-items: center">
              <span>🧩 元素列表（{{ elements.length }}）</span>
              <input
                v-model="elQ"
                class="input"
                style="max-width: 240px"
                placeholder="🔍 搜索名称 / 标签，回车查询"
                @keyup.enter="loadElements"
              />
            </div>
            <DataTable :columns="elColumns" :rows="elements" empty-text="暂无元素">
              <template #cell-id="{ row }">
                <span class="mono">#{{ (row as ElementRow).id }}</span>
              </template>
              <template #cell-name="{ row }">
                <div class="cell-main">{{ (row as ElementRow).name }}</div>
                <div class="cell-sub">{{ (row as ElementRow).config?.image_category || '' }}</div>
              </template>
              <template #cell-element_type="{ row }">
                <span class="tag tag-blue">{{ (row as ElementRow).element_type }}</span>
              </template>
              <template #cell-tags="{ row }">
                <span
                  v-for="t in (row as ElementRow).tags"
                  :key="t"
                  class="tag"
                  style="margin-right: 4px"
                  >{{ t }}</span
                >
              </template>
              <template #cell-image="{ row }">
                <img
                  v-if="(row as ElementRow).config?.image"
                  :src="(row as ElementRow).config.image"
                  alt="el"
                  style="width: 44px; height: 33px; object-fit: cover; border-radius: 4px; border: 1px solid rgba(0, 0, 0, 0.1)"
                />
                <span v-else class="text-faint">—</span>
              </template>
              <template #cell-updated_at="{ row }">
                <span class="cell-sub">{{
                  ((row as ElementRow).updated_at || '').slice(0, 16).replace('T', ' ')
                }}</span>
              </template>
              <template #actions="{ row }">
                <button class="btn btn-sm btn-danger" @click="dropElement(row as ElementRow)">
                  删除
                </button>
              </template>
            </DataTable>
          </div>
        </div>
      </template>
    </template>
  </ModuleShell>

  <!-- 上传应用包弹窗 -->
  <div class="modal-mask" :class="{ open: apkOpen }">
    <div class="modal">
      <div class="modal-head">
        <h3>📦 上传应用包</h3>
        <button class="modal-close" @click="apkOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <label
          class="card"
          style="border-style: dashed; text-align: center; padding: 26px; cursor: pointer; display: block"
        >
          <div style="font-size: 28px">📦</div>
          <div class="text-dim mt-8" style="font-size: 12.5px">点击选择或拖拽 APK / AAB 文件</div>
          <div class="text-faint" style="font-size: 11.5px">≤ 500MB，上传后自动解析包名与版本</div>
          <input type="file" accept=".apk,.aab" style="display: none" @change="onApkPick" />
        </label>
        <div v-if="apkFile" class="mt-8">
          <span class="tag tag-blue">
            📦 {{ apkFile.name }}（{{ (apkFile.size / 1024 / 1024).toFixed(1) }}MB）
          </span>
        </div>
        <div v-if="apkBusy" class="msg" style="margin-top: 8px">
          <span class="typing-dots"><span></span><span></span><span></span></span>
          正在上传并解析 AndroidManifest…
        </div>
        <div class="field mt-16">
          <label>备注（选填）</label>
          <input v-model="apkNote" class="input" placeholder="如：大促预发布版本" />
        </div>
        <div v-if="apkParsed" class="banner banner-green" style="margin: 0">
          ✅ 解析成功：<span class="mono">{{ apkParsed.pkg }}</span> ·
          v<span>{{ apkParsed.ver }}</span>
          <span class="text-faint" style="font-size: 11.5px; margin-left: 6px">
            （{{ apkInfo?.parsed_from === 'manifest' ? '来自 AndroidManifest' : '来自文件名' }}）
          </span>
        </div>
        <div v-if="apkInfo" class="card mt-8" style="padding: 10px 12px">
          <div class="text-dim" style="font-size: 11.5px; margin-bottom: 6px">📦 包结构</div>
          <div class="flex" style="gap: 6px; flex-wrap: wrap">
            <span class="tag">大小 {{ apkInfo.size }}</span>
            <span class="tag">文件 {{ apkInfo.files }}</span>
            <span class="tag">DEX {{ apkInfo.dex }}</span>
            <span class="tag" v-if="apkInfo.assets">Assets {{ apkInfo.assets }}</span>
            <span class="tag" v-for="a in apkInfo.abis" :key="a">{{ a }}</span>
            <span class="tag tag-green" v-if="apkInfo.has_res">含 res</span>
          </div>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="apkOpen = false">取消</button>
        <button
          class="btn btn-primary"
          :disabled="!apkParsed || apkBusy || apkSaving"
          @click="saveApk"
        >
          <span v-if="apkSaving" class="spinner"></span>
          {{ apkSaving ? '上传中…' : '💾 保存应用包' }}
        </button>
      </div>
    </div>
  </div>

  <!-- 新建/编辑脚本弹窗 -->
  <div class="modal-mask" :class="{ open: scriptOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>{{ editScriptId ? '编辑自动化脚本' : '＋ 新建自动化脚本' }}</h3>
        <button class="modal-close" @click="scriptOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="grid grid-2" style="gap: 12px">
          <div class="field">
            <label>脚本名称 <span class="text-red">*</span></label>
            <input v-model="fsName" class="input" placeholder="如：登录-浏览-下单冒烟" />
          </div>
          <div class="field">
            <label>自动化框架</label>
            <select v-model="fsFw" class="select">
              <option>Appium</option>
              <option>ADB 原生</option>
              <option>Python 脚本</option>
            </select>
          </div>
        </div>
        <div class="field">
          <label>目标应用包</label>
          <select v-model="fsPkg" class="select">
            <option v-for="p in packages" :key="p.id" :value="p.pkg">
              {{ p.pkg }}（v{{ p.ver }}）
            </option>
            <option v-if="!packages.length" value="com.example.shop">com.example.shop</option>
          </select>
        </div>
        <div class="field">
          <label>脚本步骤（每行一步，支持 AI 生成）</label>
          <textarea
            v-model="fsSteps"
            class="textarea mono"
            rows="6"
            placeholder="启动应用&#10;点击 #login_btn&#10;输入 username=admin&#10;断言页面包含「首页」"
          ></textarea>
        </div>
        <button class="btn btn-ghost btn-sm" :disabled="fsAiLoading" @click="genScriptAi">
          <span v-if="fsAiLoading" class="spinner"></span> 🤖 AI 生成脚本步骤
        </button>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="scriptOpen = false">取消</button>
        <button class="btn btn-primary" @click="saveScript">💾 保存脚本</button>
      </div>
    </div>
  </div>

  <!-- 新建流水线弹窗 -->
  <div class="modal-mask" :class="{ open: pipeOpen }">
    <div class="modal">
      <div class="modal-head">
        <h3>＋ 新建执行流水线</h3>
        <button class="modal-close" @click="pipeOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="field">
          <label>流水线名称 <span class="text-red">*</span></label>
          <input v-model="fpName" class="input" placeholder="如：核心冒烟-小米12" />
        </div>
        <div class="field">
          <label>选择脚本（可多选）</label>
          <div
            style="border: 1px solid var(--border); border-radius: 8px; padding: 8px; max-height: 130px; overflow-y: auto"
          >
            <label
              v-for="s in scripts"
              :key="s.id"
              class="checkbox"
              style="display: flex; padding: 4px 6px"
            >
              <input
                type="checkbox"
                :checked="fpScripts.includes(s.id)"
                @change="toggleFpScript(s.id)"
              />
              <span style="font-size: 12.5px">
                {{ s.name }} <span class="text-faint mono">({{ s.fw }})</span>
              </span>
            </label>
          </div>
        </div>
        <div class="field">
          <label>执行设备</label>
          <select v-model="fpDevice" class="select">
            <option v-for="d in devices" :key="d.id" :value="d.name">
              {{ d.name }}（{{ d.status }}{{ d.status === '离线' ? '，不可选' : '' }}）
            </option>
          </select>
        </div>
        <div class="field">
          <label>失败策略</label>
          <div class="flex" style="gap: 14px">
            <label class="checkbox">
              <input v-model="fpFail" type="radio" value="失败即中止" /> 失败即中止
            </label>
            <label class="checkbox">
              <input v-model="fpFail" type="radio" value="失败继续" /> 失败继续
            </label>
          </div>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="pipeOpen = false">取消</button>
        <button class="btn btn-primary" @click="savePipeline">▶️ 创建并执行</button>
      </div>
    </div>
  </div>

  <!-- 执行详情弹窗 -->
  <div class="modal-mask" :class="{ open: jobOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3 v-if="jobDetail">执行详情 · {{ jobDetail.id }}</h3>
        <h3 v-else>执行详情</h3>
        <button class="modal-close" @click="jobOpen = false">✕</button>
      </div>
      <div class="modal-body" v-if="jobDetail">
        <div class="flex mb-16">
          <span class="tag tag-blue">{{ jobDetail.name }}</span>
          <span class="tag">设备 {{ jobDetail.device }}</span>
          <span class="tag">{{ jobDetail.time }}</span>
          <span class="tag" :class="ST_CLS[jobDetail.status]">{{ jobDetail.status }}</span>
        </div>
        <div class="grid grid-2" style="gap: 12px">
          <div>
            <div class="card-title" style="font-size: 13.5px">📱 运行截图</div>
            <div class="grid grid-2" style="gap: 8px">
              <div
                v-for="n in ['01-启动', '02-登录页', '03-首页', '04-结果']"
                :key="n"
                class="card"
                style="padding: 0; text-align: center; overflow: hidden"
              >
                <div
                  style="aspect-ratio: 9/14; max-height: 110px; display: grid; place-items: center; background: linear-gradient(135deg,#f3e8d8,#efe2cf); font-size: 20px"
                >📱</div>
                <div style="font-size: 11px; padding: 5px" class="text-faint">{{ n }}.png</div>
              </div>
            </div>
          </div>
          <div>
            <div class="card-title" style="font-size: 13.5px">📜 执行日志</div>
            <div class="code-block" style="height: 210px; overflow-y: auto; white-space: pre-wrap">{{ jobLog(jobDetail) }}</div>
          </div>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="retryJob">🔄 重新执行</button>
        <button class="btn btn-primary" @click="jobOpen = false">关闭</button>
      </div>
    </div>
  </div>

  <!-- 新建定时任务弹窗 -->
  <div class="modal-mask" :class="{ open: timerOpen }">
    <div class="modal">
      <div class="modal-head">
        <h3>＋ 新建定时任务</h3>
        <button class="modal-close" @click="timerOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="field">
          <label>任务名称 <span class="text-red">*</span></label>
          <input v-model="ftName" class="input" placeholder="如：每夜回归冒烟" />
        </div>
        <div class="field">
          <label>触发规则（Cron）</label>
          <input v-model="ftCron" class="input mono" placeholder="0 2 * * *（每日凌晨 2 点）" />
        </div>
        <div class="field">
          <label>关联流水线</label>
          <select v-model="ftPipeline" class="select">
            <option v-for="p in pipelines" :key="p.id" :value="p.name">{{ p.name }}</option>
            <option v-if="!pipelines.length" value="">（暂无流水线）</option>
          </select>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="timerOpen = false">取消</button>
        <button class="btn btn-primary" @click="saveTimer">💾 创建任务</button>
      </div>
    </div>
  </div>
</template>
