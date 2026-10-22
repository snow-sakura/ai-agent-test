<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import { uiToast, uiConfirm } from '@/composables/ui'
import http, { TOKEN_KEY } from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-ai-assistant.html） ---------- */
interface ChatMsg {
  id: number
  who: 'user' | 'ai'
  text: string
  streaming?: boolean
  sources?: Array<{ title: string; snippet: string; score: number }>
}
interface Session {
  id: string
  title: string
  createdAt?: string
  updatedAt?: string
  model?: string
  messages: number
}
interface MatchedSkill {
  id: string
  name: string
  cat?: string
  score?: number
}

let _mid = 0

const MODELS = ['DeepSeek-V3', '通义千问-Max', '硅基流动 · GLM-4', 'GPT-4o']
const STYLES = ['专业严谨', '简明扼要', '手把手教学']
const QUICKS = [
  '🧪 帮我设计登录接口的测试用例',
  '🐞 这个崩溃堆栈怎么分析？',
  '🚀 秒杀场景压测方案怎么定 QPS？',
  '🛡️ 支付接口有哪些安全测试点？',
  '⏰ Crontab「工作日 9 点」怎么写？',
]
const WELCOME =
  '你好，我是 AITest 智能助手 👋\n可以咨询用例设计、缺陷分析、自动化、性能与安全测试问题。我会自动匹配技能库能力来完成任务，回答附带知识来源。试试左侧的快捷提问吧。'

const model = ref(MODELS[0])
const style = ref(STYLES[0])
const rag = ref(true)
const autoSkill = ref(true)

const msgs = ref<ChatMsg[]>([{ id: ++_mid, who: 'ai', text: WELCOME }])
const input = ref('')
const sending = ref(false)
const sessionId = ref<string | null>(null)
const matched = ref<MatchedSkill | null>(null)
const chatEl = ref<HTMLElement | null>(null)

const histOpen = ref(false)
const sessions = ref<Session[]>([])

async function scrollBottom() {
  await nextTick()
  const el = chatEl.value
  if (el) el.scrollTop = el.scrollHeight
}

function pushMsg(who: 'user' | 'ai', text: string): ChatMsg {
  const m: ChatMsg = { id: ++_mid, who, text }
  msgs.value.push(m)
  void scrollBottom()
  return m
}

async function loadSessions() {
  try {
    const { data } = await http.get<Session[]>('/assistant/sessions')
    sessions.value = data || []
  } catch {
    sessions.value = []
  }
}

async function openSession(s: Session) {
  try {
    const { data } = await http.get<Array<{ role: string; content: string }>>(
      `/assistant/sessions/${s.id}/messages`,
    )
    sessionId.value = s.id
    msgs.value = (data || []).map((m) => ({
      id: ++_mid,
      who: m.role === 'user' ? 'user' : 'ai',
      text: m.content,
    }))
    if (!msgs.value.length) pushMsg('ai', '会话为空，请继续提问。')
    histOpen.value = false
    matched.value = null
    uiToast(`已载入会话「${s.title}」`, 'info')
    void scrollBottom()
  } catch {
    /* toast by http */
  }
}

function clearSession() {
  uiConfirm({
    title: '开启新会话',
    message: '当前会话将清空（历史会话保留），确定吗？',
    onOk: () => {
      sessionId.value = null
      matched.value = null
      msgs.value = [{ id: ++_mid, who: 'ai', text: '新会话已开始，请问有什么测试问题？' }]
      void scrollBottom()
      uiToast('已开启新会话', 'success')
    },
  })
}

async function matchSkill(q: string) {
  if (!autoSkill.value) {
    matched.value = null
    return
  }
  try {
    const { data } = await http.post<{ skill: MatchedSkill | null }>('/assistant/match-skill', {
      content: q,
    })
    matched.value = data?.skill || null
  } catch {
    matched.value = null
  }
}

/* SSE 流式（fetch ReadableStream），失败时降级非流式 */
async function streamChat(q: string): Promise<{ reply: string; sources?: ChatMsg['sources'] }> {
  const token = localStorage.getItem(TOKEN_KEY)
  const res = await fetch('/api/assistant/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: 'Bearer ' + token } : {}),
    },
    body: JSON.stringify({
      sessionId: sessionId.value || undefined,
      content: q,
      model: model.value,
    }),
  })
  if (!res.ok || !res.body) throw new Error('stream unavailable')
  const reader = res.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  let full = ''
  let streamSid = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    const parts = buf.split('\n\n')
    buf = parts.pop() || ''
    for (const part of parts) {
      const line = part.trim()
      if (!line.startsWith('data:')) continue
      try {
        const ev = JSON.parse(line.slice(5).trim()) as {
          delta?: string
          done?: boolean
          usage?: { input: number; output: number }
          sessionId?: string
        }
        if (ev.delta) {
          full += ev.delta
          const tip = msgs.value[msgs.value.length - 1]
          if (tip && tip.who === 'ai') {
            tip.text = full
            void scrollBottom()
          }
        }
        if (ev.done && ev.sessionId) streamSid = ev.sessionId
      } catch {
        /* skip bad frame */
      }
    }
  }
  // 流式 done 事件已带 sessionId，无需再打一次非流式接口（避免重复 AI 调用）
  if (streamSid) sessionId.value = streamSid
  return { reply: full }
}

async function fallbackChat(q: string) {
  const { data } = await http.post<{
    sessionId: string
    reply: string
    sources?: ChatMsg['sources']
    skillMatched?: MatchedSkill | null
  }>('/assistant/chat', { sessionId: sessionId.value || undefined, content: q, model: model.value })
  sessionId.value = data.sessionId
  if (data.skillMatched) matched.value = data.skillMatched
  return { reply: data.reply, sources: data.sources }
}

async function send(text?: string) {
  const q = (text ?? input.value).trim()
  if (!q || sending.value) return
  if (!text) input.value = ''
  pushMsg('user', q)
  sending.value = true
  const tip = pushMsg(
    'ai',
    style.value === '简明扼要' ? '…' : '思考中…',
  )
  tip.streaming = true
  void matchSkill(q)
  try {
    let out: { reply: string; sources?: ChatMsg['sources'] }
    try {
      out = await streamChat(q)
      if (!out.reply) throw new Error('empty')
    } catch {
      out = await fallbackChat(q)
    }
    let body = out.reply || '（空回复）'
    if (style.value === '简明扼要') {
      const lines = body.split('\n')
      body = lines.slice(0, 5).join('\n') + '\n…（简明模式已截断，可切换回答风格）'
    } else if (style.value === '手把手教学') {
      body =
        '🖐 手把手模式：\n' +
        body +
        '\n\n第一步：打开对应模块 → 第二步：按上述配置填写 → 第三步：执行并核对结果。'
    }
    if (!rag.value) body += '\n\n📎 知识引用：未开启 RAG'
    tip.text = body
    tip.sources = out.sources
    tip.streaming = false
  } catch (e) {
    tip.text = '发送失败：' + (e instanceof Error ? e.message : '未知错误')
    tip.streaming = false
  } finally {
    sending.value = false
    void scrollBottom()
  }
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    void send()
  }
}

onMounted(() => {
  void loadSessions()
  void scrollBottom()
})
</script>

<template>
  <ModuleShell slug="tool-ai-assistant">
    <template #actions>
      <RouterLink class="btn btn-ghost" to="/t/tool-skill-library">🧩 技能库</RouterLink>
      <button class="btn btn-ghost" @click="histOpen = true; void loadSessions()">🕘 历史会话</button>
      <button class="btn btn-ghost" @click="clearSession">🗑 新会话</button>
    </template>

    <template #default>
      <div class="banner banner-info">
        ℹ️ 参考 TestHub 智能助手（Dify 集成）：助手可调用
        <RouterLink to="/t/tool-skill-library">技能库</RouterLink>
        中的技能执行任务，回答附知识引用来源；提问建议附带功能点、操作步骤与报错信息。
      </div>

      <div class="grid" style="grid-template-columns: 300px 1fr; gap: 14px">
        <div>
          <div class="card" style="padding: 14px">
            <div class="card-title" style="font-size: 13.5px">🤖 模型配置 <span class="tag tag-red">AI</span></div>
            <div class="field">
              <label>当前模型</label>
              <select v-model="model" class="select">
                <option v-for="m in MODELS" :key="m" :value="m">{{ m }}</option>
              </select>
            </div>
            <div class="field">
              <label>回答风格</label>
              <select v-model="style" class="select">
                <option v-for="s in STYLES" :key="s" :value="s">{{ s }}</option>
              </select>
            </div>
            <div class="field">
              <label>知识库检索</label>
              <label class="checkbox">
                <input v-model="rag" type="checkbox" /> 开启 RAG（引用平台文档与历史缺陷）
              </label>
            </div>
            <div class="field">
              <label>技能自动匹配</label>
              <label class="checkbox">
                <input v-model="autoSkill" type="checkbox" /> 根据问题自动匹配并调用技能
              </label>
            </div>
            <div class="banner banner-green" style="margin: 0; font-size: 12px">
              📊 今日额度：文本 128/200 次
            </div>
          </div>

          <div class="card mt-16" style="padding: 14px">
            <div class="card-title" style="font-size: 13.5px">⚡ 快捷提问</div>
            <div style="display: flex; flex-direction: column; gap: 6px">
              <button
                v-for="q in QUICKS"
                :key="q"
                class="btn btn-sm btn-ghost"
                style="text-align: left; justify-content: flex-start"
                @click="send(q.replace(/^[^\s]+\s/, ''))"
              >{{ q }}</button>
            </div>
          </div>

          <div class="card mt-16" style="padding: 14px">
            <div class="card-title" style="font-size: 13.5px">🔗 已匹配技能</div>
            <div style="display: flex; flex-direction: column; gap: 6px">
              <div
                v-if="!matched"
                class="text-faint"
                style="font-size: 12px"
              >发送问题后，自动匹配的技能将显示在这里</div>
              <div
                v-else
                class="flex-between"
                style="padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px"
              >
                <div>
                  <div style="font-size: 12.5px; font-weight: 600">{{ matched.name }}</div>
                  <div class="text-faint mono" style="font-size: 11px">
                    {{ matched.id }} · Function Calling
                  </div>
                </div>
                <span class="tag tag-green">已调用</span>
              </div>
            </div>
          </div>
        </div>

        <div class="card" style="display: flex; flex-direction: column; min-height: 560px">
          <div
            ref="chatEl"
            class="chat-box flex-1"
            style="flex: 1; overflow-y: auto; max-height: 480px; min-height: 420px"
          >
            <div
              v-for="m in msgs"
              :key="m.id"
              class="msg"
              :class="m.who === 'user' ? 'user' : 'ai'"
            >
              <div class="m-avatar">{{ m.who === 'user' ? '🙂' : '🤖' }}</div>
              <div class="m-body">
                <span v-if="m.streaming" class="typing-dots"><span></span><span></span><span></span></span>
                <span style="white-space: pre-wrap">{{ m.text }}</span>
                <div v-if="m.sources?.length" class="mt-8" style="font-size: 12px">
                  <div v-for="(s, i) in m.sources" :key="i" class="text-faint">
                    📎 {{ s.title }}（{{ Math.round(s.score * 100) }}%）
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div class="input-group mt-16">
            <input
              v-model="input"
              class="input"
              placeholder="输入你的问题，Enter 发送…（Shift+Enter 换行请用长文本模式）"
              :disabled="sending"
              @keydown="onKey"
            />
            <button class="btn btn-primary" :disabled="sending" @click="send()">
              <span v-if="sending" class="spinner"></span> 发送
            </button>
          </div>
          <div class="flex mt-8" style="font-size: 11.5px; color: var(--text-faint)">
            <span>💡 提问请尽量附带：功能点、操作步骤与报错/截图描述</span>
            <span style="margin-left: auto">内容由 AI 生成，仅供参考</span>
          </div>
        </div>
      </div>
    </template>
  </ModuleShell>

  <!-- 历史会话弹窗 -->
  <div class="modal-mask" :class="{ open: histOpen }">
    <div class="modal">
      <div class="modal-head">
        <h3>🕘 历史会话</h3>
        <button class="modal-close" @click="histOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div style="display: flex; flex-direction: column; gap: 8px">
          <div
            v-for="s in sessions"
            :key="s.id"
            class="flex-between"
            style="padding: 9px 12px; border: 1px solid var(--border); border-radius: 8px"
          >
            <div>
              <div style="font-size: 13px; font-weight: 600">{{ s.title }}</div>
              <div class="text-faint" style="font-size: 11.5px">
                {{ s.updatedAt || s.createdAt || '' }} · {{ s.messages }} 条消息
              </div>
            </div>
            <button class="btn btn-sm btn-ghost" @click="openSession(s)">查看</button>
          </div>
          <div v-if="!sessions.length" class="empty" style="padding: 24px">
            <div class="e-text">暂无历史会话</div>
          </div>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="histOpen = false">关闭</button>
      </div>
    </div>
  </div>
</template>
