<script setup lang="ts">
import { onMounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import { uiToast } from '@/composables/ui'
import http from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-config-center.html + config_center） ---------- */
interface AiModel {
  id: number
  name: string
  supplier: string
  model: string
  base: string
  key: string
  enabled: boolean
  default: boolean
  temperature: number
  /** 计费档位：free=单任务序列（串行保护额度）；paid=可并行序列 */
  tier?: 'free' | 'paid'
}
interface RoleBinding {
  role: string
  key: string
  model: string
  temperature: number
  style: string
  desc: string
}
interface EnvConfig {
  engine: string
  browser: string
  headless: boolean
  apiPrefix: string
  timeout: number
  retry: number
  env: string
}
interface DifyConfig {
  baseUrl: string
  apiKey: string
  appType: string
  sessionMode: string
  enabled: boolean
}
interface NotifyChannel {
  name: string
  type: string
  webhook: string
  enabled: boolean
  smtp?: string
  port?: string
  from?: string
  auth?: string
  events?: string[]
}

const SUPPLIERS = ['DeepSeek', '通义千问', '硅基流动', 'OpenAI', 'Anthropic', 'Google Gemini']
const BROWSERS = ['Chromium', 'Chrome', 'Firefox', 'Edge']
const ROLE_MODEL_OPTS = ['DeepSeek-V3', '通义千问-Max', '硅基流动 · GLM-4', 'GPT-4o']

const models = ref<AiModel[]>([])
const roles = ref<RoleBinding[]>([])
const env = ref<EnvConfig>({
  engine: 'Playwright',
  browser: 'Chromium',
  headless: true,
  apiPrefix: 'http://localhost:8000/api',
  timeout: 30,
  retry: 2,
  env: 'testing',
})
const dify = ref<DifyConfig>({
  baseUrl: 'https://api.dify.ai/v1',
  apiKey: '',
  appType: '聊天助手（Chatflow）',
  sessionMode: '按用户隔离（conversation_id）',
  enabled: false,
})
const notify = ref<NotifyChannel[]>([])

/* 文本模型表单（默认模型或第一条） */
const textForm = ref({ supplier: '', base: '', key: '', model: '', temperature: 0.7, tier: 'free' as 'free' | 'paid' })
/* 本地视觉 / Cursor（后端无独立字段，保存时并入默认模型说明用） */
const visionForm = ref({ base: '', key: '', model: '' })
const cursorKey = ref('')
const testing = ref(false)
const saving = ref(false)
const diagBusy = ref(false)

/* 驱动检测（本地演示态，与 UI 一致） */
const drivers = ref([
  { name: '系统浏览器 Chrome', status: '✅ 已安装 126.0', cls: 'tag-green', action: '' },
  { name: 'Playwright 驱动', status: '✅ 正常', cls: 'tag-green', action: '' },
  { name: 'GeckoDriver（Firefox）', status: '⚠️ 未安装', cls: 'tag-orange', action: 'GeckoDriver' },
  { name: 'Appium Server', status: '未启用', cls: 'tag', action: '' },
])

function syncTextForm() {
  const m = models.value.find((x) => x.default) || models.value[0]
  if (!m) return
  textForm.value = {
    supplier: m.supplier,
    base: m.base,
    key: m.key,
    model: m.model,
    temperature: m.temperature,
    tier: m.tier === 'paid' ? 'paid' : 'free',
  }
}

function applyTextForm() {
  const m = models.value.find((x) => x.default) || models.value[0]
  if (!m) return
  m.supplier = textForm.value.supplier
  m.base = textForm.value.base
  m.key = textForm.value.key
  m.model = textForm.value.model
  m.temperature = Number(textForm.value.temperature) || 0
  m.tier = textForm.value.tier
}

function notifyChannel(type: string): NotifyChannel | undefined {
  return notify.value.find((c) => c.type === type)
}

/** BUG-01：通知数据未就绪时（首帧 notify=[]）v-model 用 `!` 断言读 undefined.smtp 抛错。
 *  统一走本函数：真实渠道存在则返回之，否则返回本地占位（不写入列表，loadAll 到达后自然替换）。 */
const emailPlaceholder = ref<NotifyChannel>({
  name: '邮件',
  type: 'email',
  webhook: '',
  enabled: false,
  smtp: '',
  port: '',
  from: '',
  auth: '',
  events: [],
})
function emailChannel(): NotifyChannel {
  return notifyChannel('email') ?? emailPlaceholder.value
}

async function loadAll() {
  const [ai, rl, ev, df, nt] = await Promise.all([
    http.get<AiModel[]>('/config/ai'),
    http.get<RoleBinding[]>('/config/roles'),
    http.get<EnvConfig>('/config/env'),
    http.get<DifyConfig>('/config/dify'),
    http.get<NotifyChannel[]>('/config/notify'),
  ])
  models.value = ai.data || []
  roles.value = rl.data || []
  if (ev.data) env.value = { ...env.value, ...ev.data }
  if (df.data) dify.value = { ...dify.value, ...df.data }
  notify.value = nt.data || []
  syncTextForm()
}

async function saveAll() {
  applyTextForm()
  saving.value = true
  try {
    await Promise.all([
      http.put('/config/ai', { items: models.value }),
      http.put('/config/roles', { items: roles.value }),
      http.put('/config/env', { data: env.value }),
      http.put('/config/dify', { data: dify.value }),
      http.put('/config/notify', { items: notify.value }),
    ])
    uiToast('全部配置已保存（Key 仅本地存储）', 'success')
  } finally {
    saving.value = false
  }
}

async function testConn(kind: string) {
  uiToast('正在测试 ' + kind + ' 连通性…', 'info')
  testing.value = true
  try {
    if (kind === '文本模型') {
      applyTextForm()
      await http.put('/config/ai', { items: models.value })
      const { data } = await http.post<{ ok: boolean; msg: string }>('/config/ai/test')
      uiToast(data.msg || (data.ok ? '连接成功 ✅' : '连接失败'), data.ok ? 'success' : 'error')
    } else {
      uiToast(kind + ' 连接成功 ✅（演示）', 'success')
    }
  } finally {
    testing.value = false
  }
}

function testNotify(name: string) {
  uiToast('测试消息已发送至 ' + name + '（演示）', 'success')
}

function installDriver(name: string) {
  uiToast('正在安装 ' + name + '…', 'info')
  const d = drivers.value.find((x) => x.action === name)
  if (!d) return
  setTimeout(() => {
    d.status = '✅ 已安装'
    d.cls = 'tag-green'
    d.action = ''
    uiToast(name + ' 安装成功', 'success')
  }, 1200)
}

function diagEnv() {
  if (diagBusy.value) return
  diagBusy.value = true
  uiToast('检测中…', 'info')
  setTimeout(() => {
    diagBusy.value = false
    uiToast('环境检测完成：3 项正常，1 项建议安装', 'success')
  }, 1300)
}

/* ---------- 角色编辑 ---------- */
const roleOpen = ref(false)
const roleForm = ref({ role: '', key: '', model: '', temperature: 0.7 })

function openRole(r: RoleBinding) {
  roleForm.value = {
    role: r.role,
    key: r.key,
    model: r.model || ROLE_MODEL_OPTS[0],
    temperature: Number(r.temperature) || 0.7,
  }
  roleOpen.value = true
}

async function saveRole() {
  const i = roles.value.findIndex((r) => r.key === roleForm.value.key || r.role === roleForm.value.role)
  if (i >= 0) {
    roles.value[i] = {
      ...roles.value[i],
      model: roleForm.value.model,
      temperature: Number(roleForm.value.temperature) || 0,
    }
  }
  await http.put('/config/roles', {
    role: roleForm.value.role,
    key: roleForm.value.key,
    model: roleForm.value.model,
    temperature: Number(roleForm.value.temperature) || 0,
  })
  roleOpen.value = false
  uiToast('角色「' + roleForm.value.role + '」已切换为 ' + roleForm.value.model, 'success')
}

onMounted(() => {
  void loadAll().catch(() => undefined)
})
</script>

<template>
  <ModuleShell slug="tool-config-center">
    <template #actions>
      <button class="btn btn-primary" :disabled="saving" @click="saveAll">
        <span v-if="saving" class="spinner"></span>{{ saving ? '保存中…' : '💾 保存全部配置' }}
      </button>
    </template>

    <template #default="{ tab }">
      <div class="banner banner-info">
        ℹ️ 参考 TestHub 统一配置中心：AI 模型支持按角色配置（用例编写 / 用例评审 / 智能模式），API Key
        仅本地存储；环境检测可一键安装浏览器驱动。
      </div>

      <!-- ============ AI 模型 ============ -->
      <template v-if="tab === 'ai'">
        <div class="grid grid-2">
          <div class="card">
            <div class="card-title">📝 文本模型 <span class="tag tag-green">已连接</span></div>
            <div class="field">
              <label>提供商</label>
              <select v-model="textForm.supplier" class="select">
                <option v-for="s in SUPPLIERS" :key="s" :value="s">{{ s }}</option>
              </select>
            </div>
            <div class="field">
              <label>API Base URL</label>
              <input v-model="textForm.base" class="input mono" />
            </div>
            <div class="field">
              <label>API Key</label>
              <input v-model="textForm.key" class="input mono" type="password" placeholder="sk-…" />
            </div>
            <div class="grid grid-2" style="gap: 10px">
              <div class="field">
                <label>模型</label>
                <input v-model="textForm.model" class="input mono" />
              </div>
              <div class="field">
                <label>Temperature</label>
                <input
                  v-model.number="textForm.temperature"
                  class="input mono"
                  type="number"
                  step="0.1"
                  min="0"
                  max="2"
                />
              </div>
            </div>
            <div class="field">
              <label>计费档位（决定序列生成并发策略）</label>
              <select v-model="textForm.tier" class="select">
                <option value="free">🆓 免费模型 · 单任务序列（并发 1，串行保护额度）</option>
                <option value="paid">💎 付费模型 · 并行序列（多任务同时跑，默认 3 路）</option>
              </select>
              <div class="hint">
                序列生成时：免费模型任务排队串行执行，避免免费额度被限流打断；
                付费模型自动开启多路并行，吞吐随并发数提升。
              </div>
            </div>
            <button class="btn btn-ghost btn-sm" :disabled="testing" @click="testConn('文本模型')">🔌 测试连接</button>
          </div>
          <div class="card">
            <div class="card-title">🖼️ 视觉模型（附件解析） <span class="tag tag-orange">未配置</span></div>
            <div class="field">
              <label>API Base URL</label>
              <input v-model="visionForm.base" class="input mono" placeholder="https://…" />
            </div>
            <div class="field">
              <label>视觉 API Key</label>
              <input v-model="visionForm.key" class="input mono" type="password" placeholder="sk-…" />
            </div>
            <div class="field">
              <label>视觉模型</label>
              <input v-model="visionForm.model" class="input mono" placeholder="如：qwen-vl-max" />
            </div>
            <div class="hint">用于需求文档图片解析、AI 用例附件上下文</div>
            <button class="btn btn-ghost btn-sm" :disabled="testing" @click="testConn('视觉模型')">🔌 测试连接</button>
          </div>
        </div>
        <div class="grid grid-2 mt-16">
          <div class="card">
            <div class="card-title">🖱️ Cursor Agent（WebUI 自动化）</div>
            <div class="field">
              <label>Cursor API Key</label>
              <input
                v-model="cursorKey"
                class="input mono"
                type="password"
                placeholder="从 Cursor → Access Tokens 获取"
              />
            </div>
            <div class="hint">用于 WebUI 自动化 Agent 执行；Agent 模型仅国内可用</div>
            <button class="btn btn-ghost btn-sm" :disabled="testing" @click="testConn('Cursor Agent')">🔌 测试连接</button>
          </div>
          <div class="card">
            <div class="card-title">🔑 使用额度 <span class="tag tag-blue">按日重置</span></div>
            <div class="table-wrap" style="border: none">
              <table class="table">
                <thead>
                  <tr>
                    <th>能力</th>
                    <th>今日已用</th>
                    <th>每日上限</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>文本 AI</td>
                    <td class="mono">128</td>
                    <td class="mono">200</td>
                  </tr>
                  <tr>
                    <td>视觉 AI</td>
                    <td class="mono">6</td>
                    <td class="mono">50</td>
                  </tr>
                  <tr>
                    <td>Cursor Agent</td>
                    <td class="mono">3</td>
                    <td class="mono">20</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <RouterLink class="btn btn-ghost btn-sm" to="/t/tool-token-usage">🪙 查看 Tokens 消费明细 →</RouterLink>
          </div>
        </div>
      </template>

      <!-- ============ 按角色配置 ============ -->
      <template v-if="tab === 'roles'">
        <div class="banner banner-green">
          ✅ 不同业务角色可使用不同模型：用例编写追求质量、用例评审追求速度、智能模式要求视觉能力。
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>业务角色</th>
                <th>当前模型</th>
                <th>Temperature</th>
                <th>说明</th>
                <th style="width: 150px">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in roles" :key="r.key || r.role">
                <td>
                  <div class="cell-main">{{ r.role }}</div>
                  <div class="cell-sub">{{ r.key }}</div>
                </td>
                <td>
                  <span v-if="r.model">{{ r.model }}</span>
                  <span v-else class="text-dim">未配置（需视觉模型）</span>
                </td>
                <td class="mono">{{ r.model ? r.temperature : '—' }}</td>
                <td class="text-dim" style="font-size: 12.5px">{{ r.desc || r.style }}</td>
                <td>
                  <button class="btn btn-sm btn-ghost" @click="openRole(r)">调整</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- ============ UI 自动化环境 ============ -->
      <template v-if="tab === 'env'">
        <div class="grid grid-2">
          <div class="card">
            <div class="card-title">🖥️ 执行环境</div>
            <div class="field">
              <label>执行引擎</label>
              <select v-model="env.engine" class="select">
                <option>Playwright</option>
                <option>Selenium</option>
              </select>
            </div>
            <div class="field">
              <label>浏览器</label>
              <select v-model="env.browser" class="select">
                <option v-for="b in BROWSERS" :key="b" :value="b">{{ b }}</option>
              </select>
            </div>
            <div class="field">
              <label>运行模式</label>
              <div class="flex" style="gap: 14px">
                <label class="checkbox">
                  <input v-model="env.headless" type="radio" :value="false" /> 有头（调试用）
                </label>
                <label class="checkbox">
                  <input v-model="env.headless" type="radio" :value="true" /> 无头（服务器执行）
                </label>
              </div>
            </div>
            <div class="grid grid-2" style="gap: 10px">
              <div class="field">
                <label>超时（秒）</label>
                <input v-model.number="env.timeout" class="input mono" type="number" min="1" />
              </div>
              <div class="field">
                <label>重试次数</label>
                <input v-model.number="env.retry" class="input mono" type="number" min="0" />
              </div>
            </div>
          </div>
          <div class="card">
            <div class="card-title">🩺 环境检测 <span class="tag tag-red">一键诊断</span></div>
            <div class="table-wrap" style="border: none">
              <table class="table">
                <thead>
                  <tr>
                    <th>检查项</th>
                    <th>状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="d in drivers" :key="d.name">
                    <td>{{ d.name }}</td>
                    <td><span class="tag" :class="d.cls">{{ d.status }}</span></td>
                    <td>
                      <button v-if="d.action" class="btn btn-sm btn-ghost" @click="installDriver(d.action)">
                        一键安装
                      </button>
                      <span v-else>—</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <button class="btn btn-primary btn-sm" :disabled="diagBusy" @click="diagEnv">
              <span v-if="diagBusy" class="spinner"></span>{{ diagBusy ? '检测中…' : '🩺 重新检测' }}
            </button>
          </div>
        </div>
      </template>

      <!-- ============ Dify 助手 ============ -->
      <template v-if="tab === 'dify'">
        <div class="card">
          <div class="card-title">💬 Dify 智能助手接入</div>
          <div class="grid grid-2" style="gap: 12px">
            <div class="field">
              <label>Dify API Base URL</label>
              <input v-model="dify.baseUrl" class="input mono" />
            </div>
            <div class="field">
              <label>API Key</label>
              <input v-model="dify.apiKey" class="input mono" type="password" placeholder="app-…" />
            </div>
          </div>
          <div class="grid grid-2" style="gap: 12px">
            <div class="field">
              <label>应用类型</label>
              <select v-model="dify.appType" class="select">
                <option>聊天助手（Chatflow）</option>
                <option>Agent</option>
                <option>工作流</option>
              </select>
            </div>
            <div class="field">
              <label>会话隔离</label>
              <select v-model="dify.sessionMode" class="select">
                <option>按用户隔离（conversation_id）</option>
                <option>共享会话</option>
              </select>
            </div>
          </div>
          <div class="flex">
            <button class="btn btn-ghost btn-sm" :disabled="testing" @click="testConn('Dify')">🔌 测试连接</button>
            <RouterLink class="btn btn-ghost btn-sm" to="/t/tool-ai-assistant">💬 去问答助手验证 →</RouterLink>
          </div>
        </div>
      </template>

      <!-- ============ 通知渠道 ============ -->
      <template v-if="tab === 'notify'">
        <div class="grid grid-2">
          <div class="card">
            <div class="card-title">📨 Webhook 机器人</div>
            <div v-for="name in ['企业微信', '钉钉', '飞书']" :key="name" class="field">
              <label>{{ name }}</label>
              <div class="input-group">
                <input
                  :value="notifyChannel(name === '企业微信' ? 'wecom' : name === '钉钉' ? 'dingtalk' : 'feishu')?.webhook || ''"
                  class="input mono"
                  placeholder="Webhook URL"
                  @input="
                    (e) => {
                      const c = notifyChannel(
                        name === '企业微信' ? 'wecom' : name === '钉钉' ? 'dingtalk' : 'feishu',
                      )
                      if (c) c.webhook = (e.target as HTMLInputElement).value
                    }
                  "
                />
                <button class="btn btn-sm btn-ghost" @click="testNotify(name)">测试</button>
              </div>
              <label class="checkbox mt-8">
                <input
                  :checked="notifyChannel(name === '企业微信' ? 'wecom' : name === '钉钉' ? 'dingtalk' : 'feishu')?.enabled"
                  type="checkbox"
                  @change="
                    (e) => {
                      const c = notifyChannel(
                        name === '企业微信' ? 'wecom' : name === '钉钉' ? 'dingtalk' : 'feishu',
                      )
                      if (c) c.enabled = (e.target as HTMLInputElement).checked
                    }
                  "
                />
                启用
              </label>
            </div>
          </div>
          <div class="card">
            <div class="card-title">✉️ 邮件通知</div>
            <div class="grid grid-2" style="gap: 10px">
              <div class="field">
                <label>SMTP 服务器</label>
                <input v-model="emailChannel().smtp" class="input mono" />
              </div>
              <div class="field">
                <label>端口</label>
                <input v-model="emailChannel().port" class="input mono" />
              </div>
            </div>
            <div class="field">
              <label>发件账号</label>
              <input v-model="emailChannel().from" class="input mono" />
            </div>
            <div class="field">
              <label>授权码</label>
              <input v-model="emailChannel().auth" class="input mono" type="password" />
            </div>
            <div class="field">
              <label>通知事件</label>
              <div class="flex" style="gap: 8px; flex-wrap: wrap">
                <label
                  v-for="ev in ['定时任务结果', '测试完成', '高危安全发现']"
                  :key="ev"
                  class="checkbox"
                >
                  <input
                    type="checkbox"
                    :checked="(notifyChannel('email')?.events || []).includes(ev)"
                    @change="
                      (e) => {
                        const c = notifyChannel('email')
                        if (!c) return
                        const list = new Set(c.events || [])
                        if ((e.target as HTMLInputElement).checked) list.add(ev)
                        else list.delete(ev)
                        c.events = Array.from(list)
                      }
                    "
                  />
                  {{ ev }}
                </label>
              </div>
            </div>
            <button class="btn btn-ghost btn-sm" @click="testNotify('邮件')">测试发送</button>
          </div>
        </div>
      </template>
    </template>
  </ModuleShell>

  <!-- 角色调整弹窗 -->
  <div class="modal-mask" :class="{ open: roleOpen }">
    <div class="modal">
      <div class="modal-head">
        <h3>调整角色模型 · {{ roleForm.role }}</h3>
        <button class="modal-close" @click="roleOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="field">
          <label>模型</label>
          <select v-model="roleForm.model" class="select">
            <option v-for="m in ROLE_MODEL_OPTS" :key="m" :value="m">{{ m }}</option>
          </select>
        </div>
        <div class="field">
          <label>Temperature</label>
          <input
            v-model.number="roleForm.temperature"
            class="input mono"
            type="number"
            step="0.1"
            min="0"
            max="2"
          />
        </div>
        <div class="hint">调整后立即对该角色的所有 AI 调用生效</div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="roleOpen = false">取消</button>
        <button class="btn btn-primary" @click="saveRole">💾 保存</button>
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
</style>
