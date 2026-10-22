<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import { uiToast, uiConfirm } from '@/composables/ui'
import { TOKEN_KEY } from '@/api/http'
import http from '@/api/http'

/* ---------- 数据模型 ---------- */
interface GenCase {
  id: string
  title: string
  pri: string
  pre: string
  steps: string
  exp: string
  module?: string
  type?: string
}
interface ChatMsg {
  id: number
  who: 'user' | 'ai'
  text: string
  streaming?: boolean
}
interface HistoryItem {
  name: string
  time: string
  count: number
}
interface AiModel {
  id: number
  name: string
  configured?: boolean
  is_default?: boolean
  /** 计费档位：free=单任务序列；paid=并行序列 */
  tier?: 'free' | 'paid'
}
interface DoneEvent {
  success?: boolean
  summary?: string
  cases?: Array<Record<string, string>>
  raw?: string
  error?: string
}

let _mid = 0

const cases = ref<GenCase[]>([])
const models = ref<AiModel[]>([])
const modelId = ref<number | ''>('')

/* ---------- 需求输入 ---------- */
const srcType = ref('text')
const reqText = ref(`订单退款功能需求：
1. 用户在订单详情页点击「申请退款」按钮，进入退款申请页
2. 退款原因为必填下拉框，共 7 项枚举（不想要了/拍错了/质量问题/与描述不符/未按约定时间发货/其他/商家原因）
3. 退款说明为选填文本框，最多 200 字，超出禁止输入
4. 提交后生成退款单，状态为「待审核」，可撤销
5. 审核通过后 1-3 个工作日原路退回；拒绝后可重新申请`)
const lanhuUrl = ref('')
/** 已选附件（保留 File 对象，生成前先提取正文再提交给 AI） */
const files = ref<File[]>([])
/** 附件提取到的正文（供 buildRequirement 拼入需求上下文） */
const fileTexts = ref<string[]>([])
const MAX_FILE_SIZE = 5 * 1024 * 1024
const fileInput = ref<HTMLInputElement | null>(null)
const styles = ref<string[]>(['功能', '边界'])
const STYLE_OPTS = ['功能', '边界', '异常', '接口']

function addFiles(list: FileList | null) {
  if (!list || !list.length) return
  let added = 0
  let skipped = 0
  for (let i = 0; i < list.length; i++) {
    const f = list[i]
    if (files.value.length >= 5) {
      skipped++
      continue
    }
    if (f.size > MAX_FILE_SIZE) {
      uiToast(`${f.name} 超过 5MB 限制，已跳过`, 'error')
      skipped++
      continue
    }
    files.value.push(f)
    added++
  }
  if (added) uiToast(`已添加 ${added} 个附件`, 'success')
  if (skipped) uiToast(`有 ${skipped} 个文件被跳过（上限 5 个 / 单个 5MB）`, 'warn')
}

/** 上传附件到后端提取正文（可提取的返回文本，不可提取的降级为文件名） */
async function extractFileTexts(): Promise<string[]> {
  if (!files.value.length) return []
  const fd = new FormData()
  for (const f of files.value) fd.append('files', f, f.name)
  try {
    const { data } = await http.post<{
      docs: { name: string; text: string }[]
      errors: { name: string; error: string }[]
    }>('/doc-extract', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
    const parts = (data.docs || []).map((d) => `【附件: ${d.name}】\n${d.text}`)
    const failed = data.errors || []
    if (failed.length) {
      // 图片/PDF 等无法提取文本的附件，保留文件名作为上下文并提示
      parts.push(
        '【无法提取正文的附件（仅供参考）】\n' +
          failed.map((e) => `${e.name}（${e.error}）`).join('\n'),
      )
      uiToast(
        `${failed.length} 个附件无法提取正文：${failed.map((e) => e.name).join('、')}`,
        'warn',
      )
    }
    return parts
  } catch {
    return []
  }
}

function onFileDrop(e: DragEvent) {
  e.preventDefault()
  addFiles(e.dataTransfer?.files || null)
}

function toggleStyle(s: string, on: boolean) {
  if (on) {
    if (!styles.value.includes(s)) styles.value.push(s)
  } else {
    styles.value = styles.value.filter((x) => x !== s)
  }
}

/* ---------- AI 会话 ---------- */
const chatBox = ref<HTMLElement | null>(null)
const chatInput = ref('')
const chatMsgs = ref<ChatMsg[]>([
  {
    id: ++_mid,
    who: 'ai',
    text: '你好，我是用例生成助手。请在左侧粘贴需求或填写蓝湖链接，选择生成风格后点击「AI 生成用例」。生成后你可以继续对话精修，例如：<b>“补充支付失败场景”</b>、<b>“边界值再细化”</b>。',
  },
])
const aiStatus = ref<'ready' | 'streaming'>('ready')
const generating = ref(false)
let streamMsgId = 0

function scrollChat() {
  const el = chatBox.value
  if (el) el.scrollTop = el.scrollHeight
}

function addMsg(text: string, who: 'user' | 'ai', streaming = false): number {
  const id = ++_mid
  chatMsgs.value.push({ id, who, text, streaming })
  scrollChat()
  return id
}

function patchMsg(id: number, text: string) {
  const m = chatMsgs.value.find((x) => x.id === id)
  if (m) m.text = text
  scrollChat()
}

/* ---------- 用例表筛选 ---------- */
const caseSearch = ref('')
const casePri = ref('')

const filteredCases = computed(() => {
  const kw = caseSearch.value.trim().toLowerCase()
  return cases.value.filter(
    (c) =>
      (!kw || (c.title + c.steps).toLowerCase().includes(kw)) &&
      (!casePri.value || c.pri === casePri.value),
  )
})

function priCls(p: string) {
  return p === 'P0' ? 'tag-red' : p === 'P1' ? 'tag-orange' : 'tag'
}

/* 用例表分页（默认 10 条/页） */
const casePage = ref(1)
const casePageSize = ref(10)
const casePageCount = computed(() =>
  Math.max(1, Math.ceil(filteredCases.value.length / casePageSize.value)),
)
const pagedCases = computed(() => {
  const s = casePageSize.value
  return filteredCases.value.slice((casePage.value - 1) * s, casePage.value * s)
})
function setCasePage(p: number) {
  casePage.value = Math.min(casePageCount.value, Math.max(1, p))
}
watch([caseSearch, casePri, () => filteredCases.value.length], () => {
  if (casePage.value > casePageCount.value) casePage.value = casePageCount.value
})

/* ---------- 流式生成（fetch + ReadableStream 解析 SSE） ---------- */
function buildRequirement(): string {
  if (srcType.value === 'lanhu') return `蓝湖需求链接：${lanhuUrl.value.trim()}`
  if (srcType.value === 'file') {
    const names = files.value.map((f) => f.name).join('、')
    const body = fileTexts.value.length ? fileTexts.value.join('\n\n---\n\n') : ''
    return `附件需求文档：${names}\n${body ? body + '\n' : ''}\n${reqText.value}`
  }
  return reqText.value.trim()
}

async function generate() {
  const src = srcType.value
  const text = reqText.value.trim()
  if (src === 'text' && !text) {
    uiToast('请先填写需求描述', 'error')
    return
  }
  if (src === 'lanhu' && !/^https?:\/\//.test(lanhuUrl.value.trim())) {
    uiToast('请填写合法的蓝湖链接', 'error')
    return
  }
  if (src === 'file' && !files.value.length) {
    uiToast('请上传至少一个附件', 'error')
    return
  }

  generating.value = true
  aiStatus.value = 'streaming'
  addMsg('正在解析需求并生成用例…', 'ai')
  streamMsgId = addMsg(
    '<span class="typing-dots"><span></span><span></span><span></span></span> AI 正在分析需求要点…',
    'ai',
    true,
  )
  let acc = ''
  // 客户端停滞看门狗：底层连接不断开且无数据时，UI 会永远卡在生成中；120s 静默自动断开
  const ac = new AbortController()
  const IDLE_MS = 120000
  let idleTimer = 0
  const resetIdle = () => {
    window.clearTimeout(idleTimer)
    idleTimer = window.setTimeout(() => ac.abort(), IDLE_MS)
  }
  resetIdle()

  try {
    if (src === 'file') {
      // 真实上传附件 → 后端提取正文 → 拼入需求上下文（失败则仅用文件名）
      patchMsg(streamMsgId, '<span class="typing-dots"><span></span><span></span><span></span></span> 正在上传并解析附件…')
      fileTexts.value = await extractFileTexts()
      patchMsg(streamMsgId, '<span class="typing-dots"><span></span><span></span><span></span></span> AI 正在分析需求要点…')
    }
    const tk = localStorage.getItem(TOKEN_KEY) || ''
    const resp = await fetch('/api/case-generator/generate/stream', {
      method: 'POST',
      signal: ac.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(tk ? { Authorization: 'Bearer ' + tk } : {}),
      },
      body: JSON.stringify({
        requirement: buildRequirement(),
        project_type: 'web',
        test_type: styles.value.includes('异常')
          ? 'exception'
          : styles.value.includes('边界')
            ? 'boundary'
            : 'functional',
        ...(modelId.value !== '' ? { model_id: modelId.value } : {}),
      }),
    })
    if (!resp.ok || !resp.body) {
      let detail = 'HTTP ' + resp.status
      try {
        const j = await resp.json()
        if (j && j.detail) detail = String(j.detail)
      } catch {
        /* ignore */
      }
      throw new Error(detail)
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    let doneEv: DoneEvent | null = null

    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      resetIdle()
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop() || ''
      for (const line of lines) {
        if (!line.startsWith('data:')) continue
        const payload = line.slice(5).trim()
        if (!payload || payload === '[DONE]') continue
        let ev: Record<string, unknown>
        try {
          ev = JSON.parse(payload) as Record<string, unknown>
        } catch {
          continue
        }
        const type = String(ev.type || '')
        if (type === 'reasoning') {
          acc += String(ev.content || '')
          patchMsg(streamMsgId, acc)
        } else if (type === 'content') {
          acc += String(ev.delta || '')
          patchMsg(streamMsgId, acc)
        } else if (type === 'error') {
          throw new Error(String(ev.error || 'AI 请求失败'))
        } else if (type === 'done') {
          doneEv = ev as DoneEvent
        }
      }
    }

    if (doneEv && doneEv.success && doneEv.cases && doneEv.cases.length) {
      const list = doneEv.cases
      cases.value = list.map((c, i) => ({
        id: 'TC-' + (1001 + i),
        title: c.name || c.title || '未命名用例',
        pri: c.priority || c.pri || 'P2',
        pre: c.precondition || c.pre || '-',
        steps: c.steps || '-',
        exp: c.expected || c.exp || '-',
        module: c.module || '',
        type: c.type || '',
      }))
      const summary =
        doneEv.summary ||
        `✅ 需求解析完成，共生成 <b>${list.length}</b> 条用例。已写入下方用例表，可点击行内「编辑」精修。`
      patchMsg(streamMsgId, summary)
      saveHistory(text || '蓝湖需求解析')
      uiToast(`AI 用例生成完成：${list.length} 条`, 'success')
    } else {
      patchMsg(
        streamMsgId,
        doneEv && !doneEv.success
          ? doneEv.summary || doneEv.raw || 'AI 返回内容未能解析出结构化用例'
          : acc
            ? '⚠️ 连接已结束但未收到完成信号，输出可能中途中断。请重试，或改用「序列生成」（后端队列更稳）。'
            : '生成结束，但未返回结构化用例。',
      )
      if (doneEv && !doneEv.success) uiToast(doneEv.summary || '用例生成失败', 'warn')
    }
  } catch (e) {
    const aborted = e instanceof DOMException && e.name === 'AbortError'
    const msg = aborted
      ? '流式响应 120 秒无更新，已自动断开；可稍后重试或改用序列生成'
      : e instanceof Error
        ? e.message
        : 'network error'
    patchMsg(streamMsgId, '❌ ' + msg + (acc ? '\n\n已生成的部分内容：\n' + acc : ''))
    uiToast(msg, 'error')
  } finally {
    window.clearTimeout(idleTimer)
    generating.value = false
    aiStatus.value = 'ready'
  }
}

/* ---------- 序列生成（免费=串行单任务序列 / 付费=并行序列） ---------- */
interface SeqTaskItem {
  name: string
  status: string
  cases: Array<Record<string, string>>
  summary?: string
  error?: string
}
interface SeqView {
  id: string
  title: string
  model_name: string
  tier: 'free' | 'paid'
  mode: 'serial' | 'parallel'
  concurrency: number
  status: string
  total: number
  done_cnt: number
  fail_cnt: number
  items: SeqTaskItem[]
}
interface SchedPreview {
  mode: 'serial' | 'parallel'
  concurrency: number
  label: string
  tier: 'free' | 'paid'
  model_name: string
  configured: boolean
}

const genTab = ref<'single' | 'seq'>('single')
const seqText = ref(
  '订单退款的申请退款流程，设计功能与边界用例\n优惠券领取与下单使用流程，重点并发领取与过期边界\n发票抬头申请与邮件送达，含校验失败异常用例',
)
const seqModelId = ref<number | ''>('')
const seqConcurrency = ref(3)
const seqBusy = ref(false)
const seq = ref<SeqView | null>(null)
const seqPreview = ref<SchedPreview | null>(null)
/* 最近序列：时间线只挂在内存里，刷新页面就丢了，
   导致执行中/已中断的序列无法重新打开（B5 的重试入口也就看不见了），
   这里用列表接口把它接回来。 */
interface SeqBrief {
  id: string
  title: string
  model_name: string
  tier: 'free' | 'paid'
  status: string
  total: number
  done_cnt: number
  fail_cnt: number
  created_at: string | null
}
const seqHistory = ref<SeqBrief[]>([])
let seqTimer = 0
let seqPreviewTimer = 0

const seqTasks = computed(() =>
  seqText.value
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean),
)
const seqRunning = computed(
  () => !!seq.value && ['排队中', '执行中'].includes(seq.value.status),
)
const seqHasFailed = computed(() => !!seq.value && seq.value.fail_cnt > 0)
const visibleSeqHistory = computed(() =>
  seqHistory.value.filter((s) => s.id !== seq.value?.id),
)
const seqCaseCount = computed(() =>
  (seq.value?.items || []).reduce((n, it) => n + (it.cases?.length || 0), 0),
)
const seqProgress = computed(() => {
  if (!seq.value || !seq.value.total) return 0
  return Math.min(
    100,
    Math.round(((seq.value.done_cnt + seq.value.fail_cnt) / seq.value.total) * 100),
  )
})

function itemChip(s: string): { icon: string; cls: string } {
  if (s === '成功') return { icon: '✅', cls: 'tag-green' }
  if (s === '执行中') return { icon: '🔄', cls: 'tag-purple' }
  if (s === '失败') return { icon: '❌', cls: 'tag-red' }
  if (s === '已取消') return { icon: '⊘', cls: 'tag' }
  if (s === '已中断') return { icon: '⚠️', cls: 'tag-orange' }
  return { icon: '⏳', cls: 'tag' } // 等待中
}
function seqStatusCls(s: string): string {
  if (s === '已完成') return 'tag-green'
  if (s === '执行中' || s === '排队中') return 'tag-purple'
  if (s === '部分失败') return 'tag-orange'
  if (s === '全部失败') return 'tag-red'
  return 'tag'
}

async function refreshSeqPreview() {
  try {
    const { data } = await http.get<SchedPreview>('/gen-queue/scheduling-preview', {
      params: {
        ...(seqModelId.value !== '' ? { model_id: seqModelId.value } : {}),
        task_count: Math.max(1, seqTasks.value.length),
      },
    })
    seqPreview.value = data
    if (data?.tier === 'paid' && data.concurrency) seqConcurrency.value = data.concurrency
  } catch {
    seqPreview.value = null
  }
}
watch([seqModelId, () => seqTasks.value.length], () => {
  window.clearTimeout(seqPreviewTimer)
  seqPreviewTimer = window.setTimeout(refreshSeqPreview, 300)
})

function stopSeqPoll() {
  if (seqTimer) window.clearTimeout(seqTimer)
  seqTimer = 0
}

async function pollSeq() {
  seqTimer = 0
  if (!seq.value) return
  try {
    const { data } = await http.get<SeqView>('/gen-queue/sequences/' + seq.value.id)
    seq.value = data
  } catch {
    /* 网络抖动：下一轮重试 */
  }
  if (seq.value && !['排队中', '执行中'].includes(seq.value.status)) {
    const st = seq.value.status
    if (st === '已完成') uiToast(`序列完成：${seq.value.done_cnt}/${seq.value.total} 任务成功`, 'success')
    else if (st === '部分失败') uiToast(`序列部分失败：${seq.value.fail_cnt} 个任务可重试`, 'warn')
    else if (st === '全部失败') uiToast('序列生成全部失败，请检查模型配置', 'error')
    void refreshSeqHistory()
    return
  }
  seqTimer = window.setTimeout(pollSeq, 2000)
}

function beginSeqPoll(delay = 800) {
  stopSeqPoll()
  seqTimer = window.setTimeout(pollSeq, delay)
}

async function refreshSeqHistory() {
  try {
    const { data } = await http.get<SeqBrief[]>('/gen-queue/sequences', {
      params: { limit: 8 },
    })
    seqHistory.value = data || []
  } catch {
    /* http 拦截器已 toast */
  }
}

/** 重新打开历史序列：执行中的继续轮询，终态的用于取消/重试/载入 */
async function openSeq(sid: string) {
  try {
    const { data } = await http.get<SeqView>('/gen-queue/sequences/' + sid)
    stopSeqPoll()
    seq.value = data
    if (['排队中', '执行中'].includes(data.status)) beginSeqPoll(200)
  } catch {
    /* http 拦截器已 toast */
  }
}

function closeSeqView() {
  stopSeqPoll()
  seq.value = null
  void refreshSeqHistory()
}

function seqTimeText(t: string | null): string {
  if (!t) return '—'
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?$/.test(t)) return t.slice(5, 16)
  const d = new Date(t)
  return Number.isNaN(d.getTime()) ? t : d.toLocaleString('zh-CN', { hour12: false })
}

async function startSeq() {
  const tasks = seqTasks.value
  if (!tasks.length) {
    uiToast('请至少填写一条任务需求（每行一条）', 'error')
    return
  }
  if (tasks.length > 20) {
    uiToast('单序列最多 20 个任务', 'error')
    return
  }
  seqBusy.value = true
  try {
    const testType = styles.value.includes('异常')
      ? 'exception'
      : styles.value.includes('边界')
        ? 'boundary'
        : 'functional'
    const { data } = await http.post<SeqView>('/gen-queue/sequences', {
      title: '用例生成序列 · ' + new Date().toLocaleTimeString('zh-CN', { hour12: false }),
      ...(seqModelId.value !== '' ? { model_id: seqModelId.value } : {}),
      ...(seqPreview.value?.tier === 'paid' ? { concurrency: seqConcurrency.value } : {}),
      items: tasks.map((r) => ({ requirement: r, project_type: 'web', test_type: testType })),
    })
    seq.value = data
    genTab.value = 'seq'
    void refreshSeqHistory()
    beginSeqPoll()
    uiToast(
      `序列已提交：${data.total} 个任务 · ${data.mode === 'parallel' ? '并行 ' + data.concurrency + ' 路' : '单任务串行'}`,
      'success',
    )
  } catch (e) {
    uiToast(e instanceof Error ? e.message : '提交失败', 'error')
  } finally {
    seqBusy.value = false
  }
}

function cancelSeq() {
  if (!seq.value) return
  uiConfirm({
    title: '取消序列',
    message: '未完成的任务将被标记为已取消，确定吗？',
    onOk: async () => {
      try {
        const { data } = await http.post<SeqView>(
          '/gen-queue/sequences/' + seq.value!.id + '/cancel',
        )
        seq.value = data
        void refreshSeqHistory()
        stopSeqPoll()
      } catch {
        /* http 拦截器已 toast */
      }
    },
  })
}

async function retrySeq() {
  if (!seq.value) return
  try {
    const { data } = await http.post<SeqView>(
      '/gen-queue/sequences/' + seq.value.id + '/retry-failed',
    )
    seq.value = data
    void refreshSeqHistory()
    beginSeqPoll()
    uiToast('失败任务已重新入队', 'info')
  } catch (e) {
    uiToast(e instanceof Error ? e.message : '重试失败', 'error')
  }
}

function loadSeqCases() {
  if (!seq.value) return
  const flat = (seq.value.items || []).flatMap((it) => it.cases || [])
  if (!flat.length) {
    uiToast('序列中暂无可用用例', 'warn')
    return
  }
  let n = cases.value.length
  cases.value = cases.value.concat(
    flat.map((c) => ({
      id: 'TC-' + (1001 + n++),
      title: c.name || c.title || '未命名用例',
      pri: c.priority || c.pri || 'P2',
      pre: c.precondition || c.pre || '-',
      steps: c.steps || '-',
      exp: c.expected || c.exp || '-',
      module: c.module || '',
      type: c.type || '',
    })),
  )
  saveHistory(seq.value?.title || '序列用例')
  uiToast(`已载入 ${flat.length} 条用例到用例表`, 'success')
}

/* ---------- 会话精修（真实 AI） ---------- */
let chatSessionId = ''

async function sendChat() {
  const t = chatInput.value.trim()
  if (!t || aiStatus.value === 'streaming') return
  chatInput.value = ''
  addMsg(t, 'user')
  const tipId = addMsg('<span class="typing-dots"><span></span><span></span><span></span></span>', 'ai')
  aiStatus.value = 'streaming'
  try {
    // 把当前用例表作为上下文拼进 prompt，让 AI 能精准精修
    const ctx = cases.value
      .map((c) => `${c.id} | ${c.title} | ${c.pri} | ${c.exp}`)
      .join('\n')
    const content = `当前用例表：\n${ctx || '(空)'}\n\n用户精修指令：${t}\n\n请用中文简洁回复。若指令是补充/细化用例，请在回复中用 JSON 数组列出新增或修改的用例（字段：title/pri/pre/steps/exp），放在 \`\`\`json 代码块中；否则直接给出改进建议文字。`
    const { data } = await http.post<{ sessionId?: string; reply: string }>(
      '/assistant/chat',
      { sessionId: chatSessionId || undefined, content },
    )
    chatSessionId = data.sessionId || chatSessionId
    // 尝试从回复里提取 JSON 用例块并追加
    let reply = data.reply || '(空回复)'
    const jsonMatch = reply.match(/```json\s*([\s\S]*?)```/i)
    if (jsonMatch) {
      try {
        const arr = JSON.parse(jsonMatch[1].trim())
        if (Array.isArray(arr) && arr.length) {
          const added: string[] = []
          for (const item of arr) {
            const tc: GenCase = {
              id: 'TC-' + (1001 + cases.value.length),
              title: String(item.title || '未命名用例'),
              pri: String(item.pri || 'P2'),
              pre: String(item.pre || ''),
              steps: String(item.steps || ''),
              exp: String(item.exp || ''),
            }
            cases.value.push(tc)
            added.push(tc.id)
          }
          reply = reply.replace(jsonMatch[0], `✅ 已写入用例表：${added.join('、')}`)
        }
      } catch {
        /* JSON 解析失败则原文展示 */
      }
    }
    patchMsg(tipId, reply)
  } catch (e) {
    patchMsg(tipId, '❌ ' + (e instanceof Error ? e.message : 'network error'))
  } finally {
    aiStatus.value = 'ready'
    scrollChat()
  }
}

/* ---------- 编辑用例 ---------- */
const editingIdx = ref(-1)
const editOpen = ref(false)
const editTitle = ref('')
const editPri = ref('P0')
const editPre = ref('')
const editSteps = ref('')
const editExp = ref('')

function openEdit(id: string) {
  const i = cases.value.findIndex((c) => c.id === id)
  if (i < 0) return
  editingIdx.value = i
  const c = cases.value[i]
  editTitle.value = c.title
  editPri.value = c.pri
  editPre.value = c.pre
  editSteps.value = c.steps
  editExp.value = c.exp
  editOpen.value = true
}

function saveEdit() {
  const c = cases.value[editingIdx.value]
  if (!c) return
  c.title = editTitle.value || c.title
  c.pri = editPri.value
  c.pre = editPre.value
  c.steps = editSteps.value
  c.exp = editExp.value
  editOpen.value = false
  uiToast('用例已保存', 'success')
}

function deleteEdit() {
  const c = cases.value[editingIdx.value]
  if (!c) return
  uiConfirm({
    title: '删除用例',
    message: `确定删除用例「${c.title}」吗？`,
    onOk: () => {
      cases.value.splice(editingIdx.value, 1)
      editOpen.value = false
      uiToast('用例已删除', 'success')
    },
  })
}

/* ---------- 历史 ---------- */
const HISTORY_KEY = 'aitesthub_history'
const history = ref<HistoryItem[]>([])

function getHistory(): HistoryItem[] {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]') as HistoryItem[]
  } catch {
    return []
  }
}

function saveHistory(name: string) {
  const h = getHistory()
  h.unshift({
    name: (name || '需求').slice(0, 18) + '…',
    time: new Date().toLocaleString('zh-CN', { hour12: false }),
    count: cases.value.length,
  })
  localStorage.setItem(HISTORY_KEY, JSON.stringify(h.slice(0, 8)))
  history.value = getHistory()
}

function clearHistory() {
  uiConfirm({
    title: '清空历史',
    message: '确定清空全部历史用例集记录吗？',
    onOk: () => {
      localStorage.removeItem(HISTORY_KEY)
      history.value = []
      uiToast('历史已清空', 'success')
    },
  })
}

/* ---------- 导出 / 保存 ---------- */
function exportMd() {
  if (!cases.value.length) {
    uiToast('暂无用例可导出', 'warn')
    return
  }
  uiToast(`test-cases.md 导出成功（演示，${cases.value.length} 条）`, 'success')
}

function exportXlsx() {
  if (!cases.value.length) {
    uiToast('暂无用例可导出', 'warn')
    return
  }
  uiToast(`test-cases.xlsx 导出成功（演示，${cases.value.length} 条）`, 'success')
}

function saveSuite() {
  if (!cases.value.length) {
    uiToast('暂无用例可保存', 'warn')
    return
  }
  saveHistory('会话保存-' + new Date().toLocaleTimeString('zh-CN', { hour12: false }))
  uiToast('用例集已保存', 'success')
}

/* ---------- 初始化 ---------- */
onMounted(async () => {
  history.value = getHistory()
  try {
    const [cRes, mRes] = await Promise.all([
      http.get<Array<Record<string, unknown>>>('/cases'),
      http.get<AiModel[]>('/case-generator/models'),
    ])
    cases.value = (cRes.data || []).map((c) => ({
      id: String(c.id || ''),
      title: String(c.title || ''),
      pri: String(c.pri || 'P2'),
      pre: String(c.pre || '-'),
      steps: String(c.steps || '-'),
      exp: String(c.exp || '-'),
      module: String(c.module || ''),
      type: String(c.type || ''),
    }))
    models.value = mRes.data || []
    const def = models.value.find((m) => m.is_default)
    if (def) modelId.value = def.id
    void refreshSeqPreview()
    await refreshSeqHistory()
    const running = seqHistory.value.find((s) => ['排队中', '执行中'].includes(s.status))
    if (running) await openSeq(running.id)
  } catch {
    /* http 拦截器已 toast */
  }
})

onUnmounted(() => {
  stopSeqPoll()
  window.clearTimeout(seqPreviewTimer)
})
</script>

<template>
  <ModuleShell slug="tool-test-cases">
    <template #actions>
      <button class="btn btn-ghost" @click="exportMd">⬇️ 导出 Markdown</button>
      <button class="btn btn-ghost" @click="exportXlsx">⬇️ 导出 Excel</button>
      <button class="btn btn-primary" @click="saveSuite">💾 保存用例集</button>
    </template>

    <template #default>
      <div class="grid" style="grid-template-columns: 340px 1fr; gap: 14px">
        <!-- 左：需求输入 + 历史会话 -->
        <div>
          <div class="flex" style="gap: 6px; margin-bottom: 10px">
            <button class="btn btn-sm" :class="genTab === 'single' ? 'btn-primary' : 'btn-ghost'" @click="genTab = 'single'">✍️ 单条生成</button>
            <button class="btn btn-sm" :class="genTab === 'seq' ? 'btn-primary' : 'btn-ghost'" @click="genTab = 'seq'">🚀 序列生成</button>
          </div>
          <div v-if="genTab === 'single'" class="card">
            <div class="card-title">📋 需求输入 <span class="tag tag-purple">AI</span></div>
            <div class="field">
              <label>需求来源</label>
              <select v-model="srcType" class="select">
                <option value="text">📝 粘贴需求文本</option>
                <option value="lanhu">🎨 蓝湖需求链接</option>
                <option value="file">📎 上传附件（PRD / 图片）</option>
              </select>
            </div>
            <div v-if="srcType === 'text'" class="field">
              <label>需求描述 <span class="text-red">*</span></label>
              <textarea
                v-model="reqText"
                class="textarea"
                rows="7"
                placeholder="粘贴 PRD 需求描述，或输入功能点说明…"
              ></textarea>
            </div>
            <div v-if="srcType === 'lanhu'" class="field">
              <label>蓝湖项目链接 <span class="text-red">*</span></label>
              <input v-model="lanhuUrl" class="input" placeholder="https://lanhuapp.com/url/xxxxx" />
              <div class="hint">AI 将自动拉取页面与交互说明</div>
            </div>
            <div v-if="srcType === 'file'" class="field">
              <label>附件</label>
              <div
                class="card"
                style="border-style: dashed; text-align: center; padding: 18px; cursor: pointer"
                @click="fileInput?.click()"
                @dragover.prevent
                @drop="onFileDrop"
              >
                <div style="font-size: 22px">📎</div>
                <div class="text-dim mt-8" style="font-size: 12.5px">点击选择或拖拽文件到此处</div>
                <div class="text-faint" style="font-size: 11.5px">
                  支持 TXT / MD / CSV / JSON / DOCX / XLSX，≤ 5MB，最多 5 个
                </div>
              </div>
              <div class="mt-8">
                <span
                  v-for="(f, i) in files"
                  :key="f.name + i"
                  class="tag tag-blue"
                  style="margin-right: 6px"
                >📎 {{ f.name }}
                  <button
                    style="background: none; border: none; color: inherit; cursor: pointer"
                    @click="files.splice(i, 1)"
                  >✕</button>
                </span>
              </div>
              <input
                ref="fileInput"
                type="file"
                class="file-input"
                multiple
                accept=".txt,.md,.markdown,.csv,.json,.log,.yml,.yaml,.xml,.html,.htm,.sql,.py,.js,.ts,.vue,.java,.properties,.ini,.conf,.text,.rtf,.docx,.xlsx,.xlsm,.pdf,.doc,.png,.jpg,.jpeg"
                @change="addFiles(($event.target as HTMLInputElement).files)"
              />
            </div>
            <div class="field">
              <label>用例生成风格</label>
              <div class="flex" style="gap: 8px; flex-wrap: wrap">
                <label v-for="s in STYLE_OPTS" :key="s" class="checkbox">
                  <input
                    type="checkbox"
                    :checked="styles.includes(s)"
                    @change="toggleStyle(s, ($event.target as HTMLInputElement).checked)"
                  /> {{ s === '功能' ? '功能用例' : s === '边界' ? '边界分析' : s === '异常' ? '异常流' : '接口用例' }}
                </label>
              </div>
            </div>
            <div class="field">
              <label>AI 模型</label>
              <select v-model="modelId" class="select">
                <option value="">默认模型</option>
                <option v-for="m in models" :key="m.id" :value="m.id">
                  {{ m.tier === 'paid' ? '💎' : '🆓' }} {{ m.name }}{{ m.configured === false ? '（未配置 Key）' : '' }}
                </option>
              </select>
            </div>
            <button
              class="btn btn-primary"
              style="width: 100%"
              :disabled="generating"
              @click="generate"
            >✨ AI 生成用例</button>
          </div>

          <!-- 序列生成面板：免费=串行 / 付费=并行 -->
          <div v-if="genTab === 'seq'" class="card">
            <div class="card-title">
              🚀 序列生成
              <span v-if="seqPreview" class="tag" :class="seqPreview.tier === 'paid' ? 'tag-orange' : 'tag-green'">{{ seqPreview.tier === 'paid' ? '💎 付费 · 并行' : '🆓 免费 · 串行' }}</span>
            </div>
            <div class="field">
              <label>任务清单（每行一条任务需求，≤ 20 条） <span class="text-red">*</span></label>
              <textarea
                v-model="seqText"
                class="textarea"
                rows="7"
                placeholder="每行一条任务需求，例如：&#10;登录模块的验证码登录流程用例&#10;购物车合并去重与库存边界用例"
              ></textarea>
              <div class="hint">共 {{ seqTasks.length }} 个任务 · 生成风格与单条生成共用上方选择</div>
            </div>
            <div class="field">
              <label>AI 模型（档位决定调度策略）</label>
              <select v-model="seqModelId" class="select">
                <option value="">默认模型</option>
                <option v-for="m in models" :key="m.id" :value="m.id">
                  {{ m.tier === 'paid' ? '💎' : '🆓' }} {{ m.name }}{{ m.configured === false ? '（未配置 Key）' : '' }}
                </option>
              </select>
            </div>
            <div v-if="seqPreview" class="field" style="padding: 10px 12px; border: 1px dashed var(--border); border-radius: 8px">
              <div style="font-size: 12.5px">{{ seqPreview.mode === 'parallel' ? '🔀' : '➡️' }} {{ seqPreview.label }}</div>
              <div class="text-faint" style="font-size: 11.5px; margin-top: 4px">
                {{ seqTasks.length }} 个任务 · 模型「{{ seqPreview.model_name }}」{{ seqPreview.configured ? '' : '（未配置 Key，将走演示模式）' }} · 预计墙钟 ≈ {{ seqPreview.mode === 'parallel' ? 'ceil(任务数 ÷ 并发) 批' : '各任务耗时之和' }}
              </div>
            </div>
            <div v-if="seqPreview && seqPreview.tier === 'paid'" class="field">
              <label>并发路数（付费模型 1-8）</label>
              <input v-model.number="seqConcurrency" class="input mono" type="number" min="1" max="8" />
            </div>
            <button
              class="btn btn-primary"
              style="width: 100%"
              :disabled="seqBusy || seqRunning"
              @click="startSeq"
            >{{ seqBusy ? '提交中…' : seqRunning ? '序列执行中…' : '🚀 开始序列生成' }}</button>
            <div class="hint mt-8">
              免费模型任务自动排队串行，保护免费额度不被限流打断；付费模型多路并行提速。
              提交后可在右侧查看实时时间线，不阻塞其他操作。
            </div>
          </div>

          <div class="card mt-16">
            <div class="card-title">
              🕘 历史用例集
              <button class="btn btn-sm btn-ghost" @click="clearHistory">清空</button>
            </div>
            <div style="display: flex; flex-direction: column; gap: 6px">
              <template v-if="history.length">
                <div
                  v-for="(it, i) in history"
                  :key="i"
                  class="flex-between"
                  style="padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px"
                >
                  <div>
                    <div style="font-size: 13px">{{ it.name }}</div>
                    <div class="text-faint" style="font-size: 11.5px">{{ it.time }} · {{ it.count }} 条</div>
                  </div>
                  <button class="btn btn-sm btn-ghost" @click="uiToast('演示环境：加载历史用例集', 'info')">载入</button>
                </div>
              </template>
              <div v-else class="text-faint" style="font-size: 12.5px; padding: 8px">暂无历史记录</div>
            </div>
          </div>
        </div>

        <!-- 右：序列监控 + AI 会话 + 用例表 -->
        <div>
          <div
            v-if="genTab === 'seq' && visibleSeqHistory.length"
            class="card"
            style="margin-bottom: 14px"
          >
            <div class="card-title">
              🕘 最近序列
              <button class="btn btn-sm btn-ghost" style="margin-left: auto" @click="refreshSeqHistory">
                🔄 刷新
              </button>
            </div>
            <div style="display: flex; flex-direction: column; gap: 6px">
              <div
                v-for="s in visibleSeqHistory"
                :key="s.id"
                class="flex-between"
                style="padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px"
              >
                <div style="min-width: 0">
                  <div style="font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
                    {{ s.title || s.id }}
                  </div>
                  <div class="text-faint" style="font-size: 11.5px; margin-top: 2px">
                    {{ seqTimeText(s.created_at) }} · {{ s.model_name || '默认模型' }} ·
                    {{ s.done_cnt + s.fail_cnt }}/{{ s.total }}
                  </div>
                </div>
                <div class="flex" style="gap: 6px; align-items: center">
                  <span class="tag" :class="seqStatusCls(s.status)">{{ s.status }}</span>
                  <button class="btn btn-sm btn-ghost" @click="openSeq(s.id)">查看</button>
                </div>
              </div>
            </div>
          </div>

          <div v-if="seq" class="card" style="margin-bottom: 14px">
            <div class="card-title">
              🚀 {{ seq.title }}
              <span class="tag" :class="seqStatusCls(seq.status)">{{ seq.status }}</span>
              <span class="tag" :class="seq.tier === 'paid' ? 'tag-orange' : 'tag-green'">{{ seq.tier === 'paid' ? '💎 付费' : '🆓 免费' }}</span>
              <span class="tag tag-blue">{{ seq.mode === 'parallel' ? '并行 ' + seq.concurrency + ' 路' : '单任务串行' }}</span>
            </div>
            <div class="flex-between" style="font-size: 12px; margin-bottom: 6px">
              <span class="text-dim">任务进度 {{ seq.done_cnt + seq.fail_cnt }}/{{ seq.total }}（✅ {{ seq.done_cnt }} ❌ {{ seq.fail_cnt }}）</span>
              <span class="mono">{{ seqProgress }}%</span>
            </div>
            <div style="height: 8px; border: 1px solid var(--border); border-radius: 99px; overflow: hidden; margin-bottom: 10px">
              <div :style="{ width: seqProgress + '%', height: '100%', background: seq.fail_cnt ? '#f59e0b' : '#22c55e', transition: 'width .5s' }"></div>
            </div>
            <div style="display: flex; flex-direction: column; gap: 6px">
              <div
                v-for="(it, i) in seq.items"
                :key="i"
                style="padding: 7px 10px; border: 1px solid var(--border); border-radius: 8px"
              >
                <div class="flex" style="gap: 8px; align-items: center">
                  <span class="mono text-faint" style="min-width: 20px">{{ String(i + 1).padStart(2, '0') }}</span>
                  <span class="tag" :class="itemChip(it.status).cls">{{ itemChip(it.status).icon }} {{ it.status }}</span>
                  <span style="flex: 1; font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">{{ it.name || '任务 ' + (i + 1) }}</span>
                  <span v-if="it.status === '成功'" class="text-faint mono" style="font-size: 11.5px">{{ it.cases?.length || 0 }} 条用例</span>
                </div>
                <div v-if="it.error" class="text-red" style="font-size: 11px; margin-top: 4px; word-break: break-all">❌ {{ it.error }}</div>
              </div>
            </div>
            <div class="flex mt-8" style="gap: 8px; flex-wrap: wrap">
              <button v-if="seqRunning" class="btn btn-sm btn-ghost" @click="cancelSeq">⏹ 取消序列</button>
              <button v-if="!seqRunning && seqHasFailed" class="btn btn-sm btn-ghost" @click="retrySeq">🔁 重试失败任务</button>
              <button v-if="seqCaseCount" class="btn btn-sm btn-primary" @click="loadSeqCases">📥 载入用例表（{{ seqCaseCount }} 条）</button>
              <button
                v-if="!seqRunning && visibleSeqHistory.length"
                class="btn btn-sm btn-ghost"
                @click="closeSeqView"
              >
                🕘 查看最近序列
              </button>
            </div>
          </div>

          <div class="card">
            <div class="card-title">
              💬 AI 会话
              <span class="tag tag-green" v-if="aiStatus === 'ready'"><span class="dot dot-green"></span>就绪</span>
              <span class="tag tag-purple" v-else><span class="dot" style="background: var(--purple)"></span>流式生成中…</span>
            </div>
            <div
              ref="chatBox"
              class="chat-box"
              style="min-height: 120px; max-height: 260px; overflow-y: auto; margin-bottom: 14px"
            >
              <div
                v-for="m in chatMsgs"
                :key="m.id"
                class="msg"
                :class="m.who === 'user' ? 'user' : 'ai'"
              >
                <div class="m-avatar">{{ m.who === 'user' ? '🙂' : '🤖' }}</div>
                <!-- eslint-disable-next-line vue/no-v-html — AI 流式富文本预览 -->
                <div class="m-body" v-html="m.text"></div>
              </div>
            </div>
            <div class="input-group">
              <input
                v-model="chatInput"
                class="input"
                placeholder="输入精修指令，如：补充退款审核拒绝的异常场景…"
                @keydown.enter="sendChat"
              />
              <button class="btn btn-primary" @click="sendChat">发送</button>
            </div>
          </div>

          <div class="card mt-16">
            <div class="flex-between mb-8">
              <div class="card-title" style="margin: 0">
                📝 生成的用例 <span class="tag tag-blue">{{ cases.length }} 条</span>
              </div>
              <div class="flex">
                <input
                  v-model="caseSearch"
                  class="input"
                  placeholder="🔍 搜索用例…"
                  style="width: 180px; padding: 5px 10px; font-size: 12.5px"
                />
                <select
                  v-model="casePri"
                  class="select"
                  style="width: 110px; padding: 5px 10px; font-size: 12.5px"
                >
                  <option value="">全部优先级</option>
                  <option>P0</option>
                  <option>P1</option>
                  <option>P2</option>
                </select>
              </div>
            </div>
            <div v-if="!cases.length" class="empty">
              <div class="e-icon">📝</div>
              <div class="e-text">暂无用例，点击左侧「AI 生成用例」开始</div>
            </div>
            <div v-else class="table-wrap">
              <table class="table">
                <thead>
                  <tr>
                    <th style="width: 90px">编号</th>
                    <th>标题</th>
                    <th style="width: 60px">优先级</th>
                    <th style="width: 150px">前置条件</th>
                    <th style="width: 120px">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-if="!filteredCases.length">
                    <td colspan="5">
                      <div class="empty" style="padding: 24px"><div class="e-text">无匹配用例</div></div>
                    </td>
                  </tr>
                  <tr v-for="c in pagedCases" :key="c.id">
                    <td class="mono">{{ c.id }}</td>
                    <td><div class="cell-main">{{ c.title }}</div></td>
                    <td><span class="tag" :class="priCls(c.pri)">{{ c.pri }}</span></td>
                    <td class="cell-sub">{{ c.pre }}</td>
                    <td>
                      <div class="row-actions" style="opacity: 1">
                        <button class="btn btn-sm btn-ghost" @click="openEdit(c.id)">编辑</button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
              <div class="pagination">
                <span class="page-info">共 {{ filteredCases.length }} 条 · 第 {{ casePage }}/{{ casePageCount }} 页</span>
                <button class="page-btn txt" :disabled="casePage <= 1" @click="setCasePage(1)">首页</button>
                <button class="page-btn txt" :disabled="casePage <= 1" @click="setCasePage(casePage - 1)">上一页</button>
                <span class="page-btn active">{{ casePage }}</span>
                <button class="page-btn txt" :disabled="casePage >= casePageCount" @click="setCasePage(casePage + 1)">下一页</button>
                <button class="page-btn txt" :disabled="casePage >= casePageCount" @click="setCasePage(casePageCount)">末页</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </ModuleShell>

  <!-- 用例查看/编辑弹窗 -->
  <div class="modal-mask" :class="{ open: editOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>{{ editingIdx >= 0 ? '编辑用例 · ' + (cases[editingIdx]?.id || '') : '查看用例' }}</h3>
        <button class="modal-close" @click="editOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="grid grid-2" style="gap: 12px">
          <div class="field"><label>用例标题</label><input v-model="editTitle" class="input" /></div>
          <div class="field">
            <label>优先级</label>
            <select v-model="editPri" class="select"><option>P0</option><option>P1</option><option>P2</option></select>
          </div>
        </div>
        <div class="field"><label>前置条件</label><input v-model="editPre" class="input" /></div>
        <div class="field"><label>操作步骤</label><textarea v-model="editSteps" class="textarea" rows="4"></textarea></div>
        <div class="field"><label>预期结果</label><textarea v-model="editExp" class="textarea" rows="3"></textarea></div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-danger" @click="deleteEdit">🗑 删除</button>
        <button class="btn btn-ghost" @click="editOpen = false">取消</button>
        <button class="btn btn-primary" @click="saveEdit">💾 保存</button>
      </div>
    </div>
  </div>
</template>
