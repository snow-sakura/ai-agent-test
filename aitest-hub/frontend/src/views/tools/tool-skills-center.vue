<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import DataTable from '@/components/ui/DataTable.vue'
import StatCard from '@/components/ui/StatCard.vue'
import { uiToast, uiConfirm } from '@/composables/ui'
import http from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-skills-center.html） ---------- */
interface Atomic {
  id: string
  name: string
  kind: string
  input: string
  output: string
  desc: string
  status: string
  version: string
  uses: number
  prompt: string
}
interface ListResp {
  items: Atomic[]
  total: number
  enabled: number
  kinds: Array<{ kind: string; count: number }>
  totalUses: number
}

const C_CLS: Record<string, string> = {
  测试用例: 'tag-blue',
  分析: 'tag-purple',
  自动化: 'tag-orange',
}
const KINDS = ['测试用例', '分析', '自动化']
const MCP_OPTS = ['数据工厂', '需求文档解析', 'MySQL 查询', '企业微信通知', '本地命令执行']

const list = ref<Atomic[]>([])
const total = ref(0)
const enabled = ref(0)
const totalUses = ref(0)

const kw = ref('')
const kind = ref('')
const status = ref('')

async function reload() {
  const { data } = await http.get<ListResp>('/skills-center')
  list.value = data?.items || []
  total.value = data?.total ?? list.value.length
  enabled.value = data?.enabled ?? 0
  totalUses.value = data?.totalUses ?? 0
}

onMounted(() => {
  void reload().catch(() => undefined)
})

const filtered = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return list.value.filter(
    (s) =>
      (!k || (s.name + s.desc).toLowerCase().includes(k)) &&
      (!kind.value || s.kind === kind.value) &&
      (!status.value || s.status === status.value),
  )
})

function resetFilter() {
  kw.value = ''
  kind.value = ''
  status.value = ''
  uiToast('筛选已重置', 'info')
}

const columns = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: '技能名称' },
  { key: 'kind', label: '类型' },
  { key: 'mcp', label: 'MCP 绑定' },
  { key: 'uses', label: '使用次数' },
  { key: 'status', label: '状态' },
]

/* ---------- 查看 ---------- */
const viewOpen = ref(false)
const view = ref<Atomic | null>(null)
function openView(s: Atomic) {
  view.value = s
  viewOpen.value = true
}

/* ---------- 新建/编辑 ---------- */
const modalOpen = ref(false)
const editingId = ref<string | null>(null)
const saving = ref(false)
const fName = ref('')
const fKind = ref(KINDS[0])
const fDesc = ref('')
const fPrompt = ref('')
const fMcp = ref<string[]>(['需求文档解析'])
const fEnable = ref(true)

function openNew() {
  editingId.value = null
  fName.value = ''
  fKind.value = KINDS[0]
  fDesc.value = ''
  fPrompt.value = ''
  fMcp.value = ['需求文档解析']
  fEnable.value = true
  modalOpen.value = true
}

function openEdit(s: Atomic) {
  editingId.value = s.id
  fName.value = s.name
  fKind.value = s.kind
  fDesc.value = s.desc
  fPrompt.value = s.prompt
  fMcp.value = []
  fEnable.value = s.status === '启用'
  modalOpen.value = true
}

async function saveSkill() {
  const n = fName.value.trim()
  if (!n) {
    uiToast('请填写技能名称', 'error')
    return
  }
  if (!fPrompt.value.trim()) {
    uiToast('请填写提示词模板', 'error')
    return
  }
  saving.value = true
  try {
    const payload = {
      name: n,
      kind: fKind.value,
      desc: fDesc.value,
      prompt: fPrompt.value,
      status: fEnable.value ? '启用' : '禁用',
    }
    if (editingId.value) {
      await http.put(`/skills-center/atomic/${editingId.value}`, payload)
      uiToast('技能已更新', 'success')
    } else {
      await http.post('/skills-center/atomic', payload)
      uiToast('技能已创建' + (fEnable.value ? '并启用' : ''), 'success')
    }
    modalOpen.value = false
    await reload()
  } finally {
    saving.value = false
  }
}

async function toggleSkill(s: Atomic) {
  const next = s.status === '启用' ? '禁用' : '启用'
  await http.put(`/skills-center/atomic/${s.id}`, { status: next })
  await reload()
  uiToast('技能已' + next + (next === '启用' ? '，对全站 AI 生效' : ''), 'success')
}

function dropSkill(s: Atomic) {
  uiConfirm({
    title: '删除技能',
    message: `确定删除「${s.name}」吗？引用该技能的工作流节点将失效。`,
    onOk: async () => {
      await http.delete(`/skills-center/atomic/${s.id}`)
      await reload()
      uiToast('技能已删除', 'success')
    },
  })
}
</script>

<template>
  <ModuleShell slug="tool-skills-center">
    <template #actions>
      <RouterLink class="btn btn-ghost" to="/t/tool-skill-library">🧩 技能库（提示词组合包）</RouterLink>
      <RouterLink class="btn btn-ghost" to="/t/tool-mcp-center">🔌 MCP 服务中心</RouterLink>
      <button class="btn btn-primary" @click="openNew">＋ 创建技能</button>
    </template>

    <template #default="{ tab }">
      <div class="banner banner-info">
        ℹ️ 对应平台 SkillManagement 模块：与「技能库」定位不同——技能库面向<strong>提示词与工具组合包</strong>，技能中心面向 <strong>Agent 可执行的原子技能</strong>（含 MCP 工具绑定与工作流节点）。技能经启用后出现在
        <RouterLink to="/t/tool-ai-assistant">AI 问答助手</RouterLink>与 Agent 编排的可选列表中。
      </div>

      <!-- ============ 统计概览 ============ -->
      <template v-if="tab === 'stats'">
        <div class="banner">数据总览与快捷入口；详细数据请切到「🛠️ 技能列表」查看（支持筛选与分页）。</div>
        <div class="grid grid-4 mb-16">
          <StatCard label="技能总数" :value="total" />
          <StatCard label="启用中" :value="enabled" color="var(--green)" />
          <StatCard label="本周调用" :value="totalUses" color="var(--blue)" />
          <StatCard label="MCP 工具绑定" :value="4" color="var(--orange)" />
        </div>
      </template>

      <!-- ============ 技能列表 ============ -->
      <template v-if="tab === 'list'">
        <div class="filter-bar">
          <input v-model="kw" class="input search" placeholder="🔍 搜索技能名称 / 描述" />
          <select v-model="kind" class="select">
            <option value="">全部类型</option>
            <option v-for="k in KINDS" :key="k" :value="k">{{ k }}</option>
          </select>
          <select v-model="status" class="select">
            <option value="">全部状态</option>
            <option>启用</option>
            <option>禁用</option>
          </select>
          <button class="btn btn-ghost btn-sm" @click="resetFilter">重置</button>
        </div>

        <DataTable :columns="columns" :rows="filtered" empty-text="无匹配技能">
          <template #cell-id="{ row }">
            <span class="mono">{{ (row as Atomic).id }}</span>
          </template>
          <template #cell-name="{ row }">
            <div class="cell-main">{{ (row as Atomic).name }}</div>
            <div class="cell-sub">{{ (row as Atomic).desc }}</div>
          </template>
          <template #cell-kind="{ row }">
            <span class="tag" :class="C_CLS[(row as Atomic).kind]">{{ (row as Atomic).kind }}</span>
          </template>
          <template #cell-mcp>
            <span class="text-faint" style="font-size: 12px">无</span>
          </template>
          <template #cell-uses="{ row }">
            <span class="mono">{{ (row as Atomic).uses }}</span>
          </template>
          <template #cell-status="{ row }">
            <span
              class="tag"
              :class="(row as Atomic).status === '启用' ? 'tag-green' : ''"
            >{{ (row as Atomic).status }}</span>
          </template>
          <template #actions="{ row }">
            <div class="row-actions" style="opacity: 1">
              <button class="btn btn-sm btn-ghost" @click="openView(row as Atomic)">查看</button>
              <button class="btn btn-sm btn-ghost" @click="openEdit(row as Atomic)">编辑</button>
              <button class="btn btn-sm btn-ghost" @click="toggleSkill(row as Atomic)">
                {{ (row as Atomic).status === '启用' ? '禁用' : '启用' }}
              </button>
              <button class="btn btn-sm btn-danger" @click="dropSkill(row as Atomic)">删除</button>
            </div>
          </template>
        </DataTable>
      </template>
    </template>
  </ModuleShell>

  <!-- 创建/编辑技能弹窗 -->
  <div class="modal-mask" :class="{ open: modalOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>{{ editingId ? '编辑技能 · ' + editingId : '＋ 创建技能' }}</h3>
        <button class="modal-close" @click="modalOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="grid grid-2" style="gap: 12px">
          <div class="field">
            <label>技能名称 <span class="text-red">*</span></label>
            <input v-model="fName" class="input" placeholder="如：接口异常场景补全" />
          </div>
          <div class="field">
            <label>类型</label>
            <div class="flex" style="gap: 14px">
              <label v-for="k in KINDS" :key="k" class="checkbox">
                <input v-model="fKind" type="radio" name="kf-cat" :value="k" /> {{ k }}
              </label>
            </div>
          </div>
        </div>
        <div class="field">
          <label>描述</label>
          <input v-model="fDesc" class="input" placeholder="技能用途说明" />
        </div>
        <div class="field">
          <label>提示词模板 <span class="text-red">*</span></label>
          <textarea
            v-model="fPrompt"
            class="textarea mono"
            rows="6"
            placeholder="技能的提示词模板，支持变量：{{input}} {{context}} {{mcp.data}}"
          ></textarea>
          <div class="hint">
            支持占位变量；绑定 MCP 服务后可用 <span class="mono" v-pre>{{mcp.服务名}}</span> 引用其返回
          </div>
        </div>
        <div class="field">
          <label>MCP 工具绑定（AI 关联）</label>
          <div class="flex" style="gap: 8px; flex-wrap: wrap">
            <label v-for="m in MCP_OPTS" :key="m" class="checkbox">
              <input v-model="fMcp" type="checkbox" :value="m" /> {{ m }}
            </label>
          </div>
          <div class="hint">
            绑定 <RouterLink to="/t/tool-mcp-center">MCP 服务中心</RouterLink> 已连接的服务，技能执行时自动调用
          </div>
        </div>
        <label class="checkbox">
          <input v-model="fEnable" type="checkbox" /> 创建后立即启用
        </label>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="modalOpen = false">取消</button>
        <button class="btn btn-primary" :disabled="saving" @click="saveSkill">
          <span v-if="saving" class="spinner"></span> 💾 保存
        </button>
      </div>
    </div>
  </div>

  <!-- 技能详情弹窗 -->
  <div class="modal-mask" :class="{ open: viewOpen }">
    <div class="modal">
      <div class="modal-head">
        <h3>{{ view?.name || '技能详情' }}</h3>
        <button class="modal-close" @click="viewOpen = false">✕</button>
      </div>
      <div class="modal-body" v-if="view">
        <div class="kv"><span>ID</span><b class="mono">{{ view.id }}</b></div>
        <div class="kv"><span>类型</span><b>{{ view.kind }}</b></div>
        <div class="kv">
          <span>状态</span><b>{{ view.status }} · 调用 {{ view.uses }} 次</b>
        </div>
        <div class="field mt-16">
          <label>提示词模板</label>
          <div class="code-block">{{ view.prompt || '—' }}</div>
        </div>
        <div class="kv"><span>MCP 绑定</span><b>{{ fMcp.join('、') || '无' }}</b></div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-primary" @click="viewOpen = false">关闭</button>
      </div>
    </div>
  </div>
</template>
