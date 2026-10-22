<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import DataTable from '@/components/ui/DataTable.vue'
import { uiToast, uiConfirm } from '@/composables/ui'
import http from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-mcp-center.html + mcp_center） ---------- */
interface MarketItem {
  id: string
  name: string
  cat: string
  desc: string
  tags: string[]
  conn: string
  proto: string
  url: string
  calls: number
  installed?: boolean
}
interface MineItem {
  id: string
  name: string
  url: string
  proto: string
  status: string
  created: string
  health: string
  desc?: string
}

const C_CLS: Record<string, string> = {
  测试数据: 'tag-green',
  文档解析: 'tag-blue',
  数据库: 'tag-purple',
  通知推送: 'tag-orange',
  开发工具: 'tag',
}
const CAT_OPTS = ['测试数据', '文档解析', '数据库', '通知推送', '开发工具']

const market = ref<MarketItem[]>([])
const mine = ref<MineItem[]>([])
const kw = ref('')
const catF = ref('')
const connF = ref('')
const refreshing = ref(false)

const marketCount = computed(() => market.value.length)
const mineCount = computed(() => mine.value.length)

async function loadMarket() {
  const { data } = await http.get<MarketItem[]>('/mcp/market', {
    params: { q: kw.value.trim(), cat: catF.value, conn: connF.value },
  })
  market.value = data || []
}
async function loadMine() {
  const { data } = await http.get<MineItem[]>('/mcp/mine')
  mine.value = data || []
}
async function reload() {
  await Promise.all([loadMarket(), loadMine()])
}

let kwTimer: ReturnType<typeof setTimeout> | undefined
function onKw() {
  clearTimeout(kwTimer)
  kwTimer = setTimeout(() => {
    void loadMarket()
  }, 200)
}

async function refreshAll() {
  refreshing.value = true
  try {
    await reload()
    uiToast(
      '已刷新：市场 ' + market.value.length + ' 个服务，' + market.value.filter((s) => s.conn === '已连接').length + ' 个已连接',
      'success',
    )
  } finally {
    refreshing.value = false
  }
}

async function connect(s: MarketItem) {
  uiToast('正在与「' + s.name + '」握手…', 'info')
  await http.post('/mcp/market/' + s.id + '/install')
  await reload()
  uiToast('接入成功 ✅ 已可在技能与 Agent 中调用', 'success')
}

function disconnect(s: MarketItem) {
  uiConfirm({
    title: '断开服务',
    message: '断开后依赖该服务的 AI 技能将无法调用「' + s.name + '」，确定吗？',
    danger: true,
    onOk: async () => {
      await http.post('/mcp/market/' + s.id + '/uninstall')
      await loadMarket()
      uiToast('已断开「' + s.name + '」', 'success')
    },
  })
}

/* ---------- 详情 ---------- */
const detail = ref<MarketItem | null>(null)
const detailOpen = ref(false)
function openDetail(s: MarketItem) {
  detail.value = s
  detailOpen.value = true
}
async function connectFromDetail() {
  const s = detail.value
  detailOpen.value = false
  if (s) await connect(s)
}

/* ---------- 注册 / 编辑 ---------- */
const regOpen = ref(false)
const regTitle = ref('＋ 注册服务')
const editId = ref('')
const reg = ref({
  name: '',
  proto: 'HTTP',
  url: '',
  desc: '',
  token: '',
  enable: true,
})

function openCreate() {
  editId.value = ''
  regTitle.value = '＋ 注册服务'
  reg.value = { name: '', proto: 'HTTP', url: '', desc: '', token: '', enable: true }
  regOpen.value = true
}

function openEdit(s: MineItem) {
  editId.value = s.id
  regTitle.value = '编辑服务 · ' + s.id
  reg.value = {
    name: s.name,
    proto: s.proto,
    url: s.url,
    desc: s.desc || '',
    token: '',
    enable: s.status === '启用',
  }
  regOpen.value = true
}

async function saveReg() {
  const name = reg.value.name.trim()
  const url = reg.value.url.trim()
  if (!name) {
    uiToast('请填写服务名称', 'error')
    return
  }
  if (!url) {
    uiToast('请填写服务地址', 'error')
    return
  }
  const status = reg.value.enable ? '启用' : '禁用'
  if (editId.value) {
    await http.put('/mcp/services/' + editId.value, {
      name,
      url,
      proto: reg.value.proto,
      desc: reg.value.desc,
      status,
    })
    uiToast('服务已更新', 'success')
  } else {
    await http.post('/mcp/services', {
      name,
      url,
      proto: reg.value.proto,
      desc: reg.value.desc,
      token: reg.value.token,
      status,
    })
    uiToast('服务已注册，建议先做连通测试', 'success')
  }
  regOpen.value = false
  await loadMine()
}

async function testService(s: MineItem) {
  uiToast('正在测试「' + s.name + '」连通性…', 'info')
  const { data } = await http.post<{ ok: boolean; health: string; latencyMs: number }>(
    '/mcp/services/' + s.id + '/test',
  )
  if (data.ok) {
    await loadMine()
    uiToast(s.name + ' 连通正常 ✅（延迟 ' + data.latencyMs + 'ms）', 'success')
  }
}

function delService(s: MineItem) {
  uiConfirm({
    title: '删除服务',
    message: '确定删除「' + s.name + '」吗？该操作不可恢复。',
    danger: true,
    onOk: async () => {
      await http.delete('/mcp/services/' + s.id)
      await loadMine()
      uiToast('服务已删除', 'success')
    },
  })
}

onMounted(() => {
  void reload().catch(() => undefined)
})
</script>

<template>
  <ModuleShell slug="tool-mcp-center">
    <template #actions>
      <button class="btn btn-ghost" :disabled="refreshing" @click="refreshAll">
        <span v-if="refreshing" class="spinner"></span>{{ refreshing ? '刷新中…' : '🔄 刷新状态' }}
      </button>
      <button class="btn btn-primary" @click="openCreate">＋ 注册服务</button>
    </template>

    <template #default="{ tab }">
      <div class="banner banner-info">
        ℹ️ 对应平台 MCPMarketplace 模块：市场服务一键接入，自有服务支持 HTTP / WebSocket / Stdio
        三种协议；连通性测试通过后即可在 AI 用例 / 自动化 / 问答助手中作为工具调用。
      </div>

      <!-- ============ 服务市场 ============ -->
      <template v-if="tab === 'market'">
        <div class="filter-bar">
          <input v-model="kw" class="input search" placeholder="🔍 搜索服务名称 / 描述 / 标签" @input="onKw" />
          <select v-model="catF" class="select" @change="loadMarket">
            <option value="">全部分类</option>
            <option v-for="c in CAT_OPTS" :key="c" :value="c">{{ c }}</option>
          </select>
          <select v-model="connF" class="select" @change="loadMarket">
            <option value="">全部状态</option>
            <option>已连接</option>
            <option>未连接</option>
          </select>
        </div>
        <div class="grid grid-3">
          <div v-if="!market.length" class="card" style="grid-column: 1 / -1">
            <div class="empty">
              <div class="e-icon">🛒</div>
              <div class="e-text">无匹配服务</div>
            </div>
          </div>
          <div v-for="s in market" :key="s.id" class="card card-hover">
            <div class="flex-between">
              <span class="tag" :class="C_CLS[s.cat] || 'tag'">{{ s.cat }}</span>
              <span v-if="s.conn === '已连接'" class="tag tag-green">● 已连接</span>
              <span v-else class="tag">未连接</span>
            </div>
            <h3 style="font-size: 15px; margin: 10px 0 6px">{{ s.name }}</h3>
            <p class="text-dim" style="font-size: 12.5px">{{ s.desc }}</p>
            <div class="mt-8">
              <span
                v-for="t in s.tags"
                :key="t"
                class="tag"
                style="margin-right: 4px"
              >#{{ t }}</span>
            </div>
            <div class="flex-between mt-16">
              <span class="text-faint mono" style="font-size: 11px">{{ s.proto }} · {{ s.calls }} 次调用</span>
              <div class="flex">
                <button class="btn btn-sm btn-ghost" @click="openDetail(s)">详情</button>
                <button
                  v-if="s.conn === '已连接'"
                  class="btn btn-sm btn-ghost"
                  @click="disconnect(s)"
                >断开</button>
                <button v-else class="btn btn-sm btn-primary" @click="connect(s)">接入</button>
              </div>
            </div>
          </div>
        </div>
        <div class="mt-8 text-faint" style="font-size: 12.5px">共 {{ marketCount }} 个市场服务</div>
      </template>

      <!-- ============ 我的服务 ============ -->
      <template v-if="tab === 'mine'">
        <div class="mt-8 mb-8 text-faint" style="font-size: 12.5px">共 {{ mineCount }} 个自有服务</div>
        <DataTable
          :rows="mine"
          :columns="[
            { key: 'id', label: 'ID' },
            { key: 'name', label: '服务名称' },
            { key: 'url', label: '地址' },
            { key: 'proto', label: '协议' },
            { key: 'health', label: '健康' },
            { key: 'status', label: '状态' },
            { key: 'created', label: '创建时间' },
          ]"
        >
          <template #cell-health="{ row }">
            <span v-if="row.health === '正常'" class="tag tag-green">正常</span>
            <span v-else class="tag">{{ row.health || '—' }}</span>
          </template>
          <template #cell-status="{ row }">
            <span v-if="row.status === '启用'" class="tag tag-green">启用</span>
            <span v-else class="tag">禁用</span>
          </template>
          <template #actions="{ row }">
            <div class="row-actions" style="opacity: 1">
              <button class="btn btn-sm btn-ghost" @click="testService(row as MineItem)">连通测试</button>
              <button class="btn btn-sm btn-ghost" @click="openEdit(row as MineItem)">编辑</button>
              <button class="btn btn-sm btn-danger" @click="delService(row as MineItem)">删除</button>
            </div>
          </template>
        </DataTable>
      </template>
    </template>
  </ModuleShell>

  <!-- 服务详情弹窗 -->
  <div class="modal-mask" :class="{ open: detailOpen }">
    <div class="modal">
      <div class="modal-head">
        <h3>{{ detail?.name || '服务详情' }}</h3>
        <button class="modal-close" @click="detailOpen = false">✕</button>
      </div>
      <div v-if="detail" class="modal-body">
        <div class="kv"><span>服务 ID</span><b class="mono">{{ detail.id }}</b></div>
        <div class="kv"><span>分类</span><b>{{ detail.cat }}</b></div>
        <div class="kv"><span>协议</span><b class="mono">{{ detail.proto }}</b></div>
        <div class="kv">
          <span>地址</span>
          <b class="mono" style="font-size: 12px; word-break: break-all">{{ detail.url }}</b>
        </div>
        <div class="kv">
          <span>状态</span>
          <b>
            <span v-if="detail.conn === '已连接'" class="tag tag-green">已连接</span>
            <span v-else class="tag">未连接</span>
          </b>
        </div>
        <div class="kv"><span>累计调用</span><b class="mono">{{ detail.calls }}</b></div>
        <div class="text-dim" style="font-size: 12.5px; margin-top: 10px">{{ detail.desc }}</div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="detailOpen = false">关闭</button>
        <button class="btn btn-primary" @click="connectFromDetail">🔗 接入此服务</button>
      </div>
    </div>
  </div>

  <!-- 注册/编辑服务弹窗 -->
  <div class="modal-mask" :class="{ open: regOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>{{ regTitle }}</h3>
        <button class="modal-close" @click="regOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="grid grid-2" style="gap: 12px">
          <div class="field">
            <label>服务名称 <span class="text-red">*</span></label>
            <input v-model="reg.name" class="input" placeholder="如：内部知识库 MCP" />
          </div>
          <div class="field">
            <label>协议</label>
            <div class="flex" style="gap: 14px">
              <label class="checkbox"><input v-model="reg.proto" type="radio" value="HTTP" /> HTTP</label>
              <label class="checkbox"><input v-model="reg.proto" type="radio" value="WebSocket" /> WebSocket</label>
              <label class="checkbox"><input v-model="reg.proto" type="radio" value="Stdio" /> Stdio</label>
            </div>
          </div>
        </div>
        <div class="field">
          <label>服务地址 <span class="text-red">*</span></label>
          <input v-model="reg.url" class="input mono" placeholder="http://localhost:3000/mcp" />
        </div>
        <div class="field">
          <label>描述</label>
          <input v-model="reg.desc" class="input" placeholder="服务用途说明" />
        </div>
        <div class="field">
          <label>鉴权 Token（选填）</label>
          <input v-model="reg.token" class="input mono" type="password" placeholder="Bearer Token / API Key" />
        </div>
        <label class="checkbox">
          <input v-model="reg.enable" type="checkbox" />
          {{ editId ? '启用该服务' : '注册后立即启用' }}
        </label>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="regOpen = false">取消</button>
        <button class="btn btn-primary" @click="saveReg">💾 保存</button>
      </div>
    </div>
  </div>
</template>
