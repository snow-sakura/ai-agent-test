<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import DataTable from '@/components/ui/DataTable.vue'
import { uiToast, uiConfirm } from '@/composables/ui'
import http from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-deai-flavor.html + backend deai.py） ---------- */
interface Policy {
  id: string
  name: string
  desc: string
  status: string
  scope: string[]
  created: string
  uses: number
  trigger: string
  suffix: string
  updated_at: string
}
interface ApplyResp {
  text: string
  scope: string
  ok: boolean
}

const S_CLS: Record<string, string> = {
  测试用例: 'tag-blue',
  测试报告: 'tag-purple',
  缺陷描述: 'tag-orange',
  'AI 问答': 'tag-green',
}
const SCOPES = ['测试用例', '测试报告', '缺陷描述', 'AI 问答']
const TRY_TYPES = ['测试用例', '测试报告', '缺陷描述']

const list = ref<Policy[]>([])

const kw = ref('')
const stFilter = ref('')

async function reload() {
  const { data } = await http.get<Policy[]>('/deai/policies')
  list.value = data || []
}

onMounted(() => {
  void reload().catch(() => undefined)
})

const filtered = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return list.value.filter(
    (p) =>
      (!k || (p.name + p.desc).toLowerCase().includes(k)) &&
      (!stFilter.value || p.status === stFilter.value),
  )
})

function resetFilter() {
  kw.value = ''
  stFilter.value = ''
  uiToast('筛选已重置', 'info')
}

const columns = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: '策略名称' },
  { key: 'scope', label: '作用范围' },
  { key: 'uses', label: '使用次数' },
  { key: 'created', label: '创建时间' },
  { key: 'status', label: '状态' },
]

/* ---------- 查看 ---------- */
const viewOpen = ref(false)
const view = ref<Policy | null>(null)

function openView(p: Policy) {
  view.value = p
  viewOpen.value = true
}

/* ---------- 新建/编辑 ---------- */
const modalOpen = ref(false)
const editingId = ref<string | null>(null)
const saving = ref(false)
const fName = ref('')
const fStatus = ref('启用')
const fDesc = ref('')
const fSuffix = ref('')
const fScope = ref<string[]>(['测试用例', '测试报告'])

function openNew() {
  editingId.value = null
  fName.value = ''
  fStatus.value = '启用'
  fDesc.value = ''
  fSuffix.value = ''
  fScope.value = ['测试用例', '测试报告']
  modalOpen.value = true
}

function openEdit(p: Policy) {
  editingId.value = p.id
  fName.value = p.name
  fStatus.value = p.status
  fDesc.value = p.desc
  fSuffix.value = p.suffix
  fScope.value = p.scope.length ? [...p.scope] : ['测试用例']
  modalOpen.value = true
}

async function savePolicy() {
  const n = fName.value.trim()
  if (!n) {
    uiToast('请填写策略名称', 'error')
    return
  }
  if (!fSuffix.value.trim()) {
    uiToast('请填写提示词后缀', 'error')
    return
  }
  saving.value = true
  try {
    const payload = {
      name: n,
      desc: fDesc.value,
      status: fStatus.value,
      scope: fScope.value.length ? fScope.value : ['测试用例'],
      suffix: fSuffix.value,
      trigger: '全部',
    }
    if (editingId.value) {
      await http.put(`/deai/policies/${editingId.value}`, payload)
      uiToast('策略已更新', 'success')
    } else {
      await http.post('/deai/policies', payload)
      uiToast('策略已保存', 'success')
    }
    modalOpen.value = false
    await reload()
  } finally {
    saving.value = false
  }
}

async function togglePolicy(p: Policy) {
  const next = p.status === '启用' ? '禁用' : '启用'
  await http.put(`/deai/policies/${p.id}`, {
    name: p.name,
    desc: p.desc,
    status: next,
    scope: p.scope,
    suffix: p.suffix,
    trigger: p.trigger,
    uses: p.uses,
  })
  await reload()
  uiToast('策略已' + next + (next === '启用' ? '，对全站 AI 生成生效' : ''), 'success')
}

function dropPolicy(p: Policy) {
  uiConfirm({
    title: '删除策略',
    message: `确定删除「${p.name}」吗？已生成的文本不受影响。`,
    onOk: async () => {
      await http.delete(`/deai/policies/${p.id}`)
      await reload()
      uiToast('策略已删除', 'success')
    },
  })
}

/* ---------- 试运行对比 ---------- */
const tryPolicy = ref('策略组合（全部启用项）')
const tryType = ref('测试用例')
const tryIn = ref(
  '验证用户登录功能：在用户名输入框输入合法的用户名字符串，在密码输入框输入对应的合法密码字符串，随后触发登录按钮的点击事件，系统应当对该次提交进行服务端校验并返回相应的认证结果。',
)
const tryBefore = ref('')
const tryAfter = ref('// 点击「执行润色」后显示')
const tryScore = ref('AI 味：—')
const tryBusy = ref(false)

async function goTry() {
  const text = tryIn.value.trim()
  if (!text) {
    uiToast('请输入 AI 原文', 'warn')
    return
  }
  tryBefore.value = text
  tryAfter.value = '润色中…'
  tryBusy.value = true
  try {
    const { data } = await http.post<ApplyResp>('/deai/apply', {
      text,
      scope: tryType.value,
      policy: tryPolicy.value.startsWith('策略组合') ? '' : tryPolicy.value,
    })
    tryAfter.value = data.text || '—'
    tryScore.value = 'AI 味：已下降 ↓'
    uiToast('润色完成，AI 味显著下降', 'success')
  } finally {
    tryBusy.value = false
  }
}

function canCopy(): boolean {
  return !!tryAfter.value && !tryAfter.value.startsWith('// 点击') && tryAfter.value !== '润色中…'
}

async function copyAfter() {
  if (!canCopy()) {
    uiToast('请先执行润色', 'warn')
    return
  }
  try {
    await navigator.clipboard.writeText(tryAfter.value)
    uiToast('已复制润色后文本', 'success')
  } catch {
    uiToast('复制失败，请手动选择文本', 'error')
  }
}

function saveSample() {
  if (!canCopy()) {
    uiToast('请先执行润色', 'warn')
    return
  }
  uiToast('样例已保存至当前策略（演示）', 'success')
}
</script>

<template>
  <ModuleShell slug="tool-deai-flavor">
    <template #actions>
      <RouterLink class="btn btn-ghost" to="/t/tool-test-cases">✨ AI 用例工作台</RouterLink>
      <RouterLink class="btn btn-ghost" to="/t/tool-config-center">⚙️ 配置中心</RouterLink>
      <button class="btn btn-primary" @click="openNew">＋ 新建策略</button>
    </template>

    <template #default="{ tab }">
      <div class="banner banner-info">
        ℹ️ 对应平台 DeAIConfig 模块：策略本质是<strong>追加到 AI 提示词末尾的指令后缀</strong>，启用后对全站 AI 生成（用例 / 报告 / 分析结论）统一生效，可按策略试运行对比润色前后效果。
      </div>

      <!-- ============ 策略管理 ============ -->
      <template v-if="tab === 'list'">
        <div class="filter-bar">
          <input v-model="kw" class="input search" placeholder="🔍 搜索策略名称 / 描述" />
          <select v-model="stFilter" class="select">
            <option value="">全部状态</option>
            <option>启用</option>
            <option>禁用</option>
          </select>
          <button class="btn btn-ghost btn-sm" @click="resetFilter">重置</button>
        </div>
        <DataTable :columns="columns" :rows="filtered" empty-text="无匹配策略">
          <template #cell-id="{ row }">
            <span class="mono">{{ (row as Policy).id }}</span>
          </template>
          <template #cell-name="{ row }">
            <div class="cell-main">{{ (row as Policy).name }}</div>
            <div class="cell-sub">{{ (row as Policy).desc }}</div>
          </template>
          <template #cell-scope="{ row }">
            <span
              v-for="s in (row as Policy).scope"
              :key="s"
              class="tag"
              :class="S_CLS[s]"
              style="margin-right: 3px"
            >{{ s }}</span>
          </template>
          <template #cell-uses="{ row }">
            <span class="mono">{{ (row as Policy).uses }}</span>
          </template>
          <template #cell-created="{ row }">
            <span class="mono" style="font-size: 12px">{{ (row as Policy).created }}</span>
          </template>
          <template #cell-status="{ row }">
            <span
              class="tag"
              :class="(row as Policy).status === '启用' ? 'tag-green' : ''"
            >{{ (row as Policy).status }}</span>
          </template>
          <template #actions="{ row }">
            <div class="row-actions" style="opacity: 1">
              <button class="btn btn-sm btn-ghost" @click="openView(row as Policy)">查看</button>
              <button class="btn btn-sm btn-ghost" @click="openEdit(row as Policy)">编辑</button>
              <button class="btn btn-sm btn-ghost" @click="togglePolicy(row as Policy)">
                {{ (row as Policy).status === '启用' ? '禁用' : '启用' }}
              </button>
              <button class="btn btn-sm btn-danger" @click="dropPolicy(row as Policy)">删除</button>
            </div>
          </template>
        </DataTable>
      </template>

      <!-- ============ 试运行对比 ============ -->
      <template v-if="tab === 'try'">
        <div class="card">
          <div class="card-title">🧪 润色效果对比 <span class="tag tag-red">AI</span></div>
          <div class="grid grid-2" style="gap: 12px">
            <div class="field">
              <label>应用策略</label>
              <select v-model="tryPolicy" class="select">
                <option>策略组合（全部启用项）</option>
                <option v-for="p in list" :key="p.id" :value="p.name">{{ p.name }}</option>
              </select>
            </div>
            <div class="field">
              <label>原文类型</label>
              <select v-model="tryType" class="select">
                <option v-for="t in TRY_TYPES" :key="t" :value="t">{{ t }}</option>
              </select>
            </div>
          </div>
          <div class="field">
            <label>AI 原文</label>
            <textarea v-model="tryIn" class="textarea mono" rows="5"></textarea>
          </div>
          <button class="btn btn-primary" :disabled="tryBusy" @click="goTry">
            <span v-if="tryBusy" class="spinner"></span> ✨ 执行润色
          </button>
          <div class="grid grid-2 mt-16" style="gap: 12px">
            <div>
              <div class="card-title" style="font-size: 13.5px">
                润色前 <span class="text-faint" style="font-size: 11px">AI 味：92%</span>
              </div>
              <div class="code-block" style="min-height: 140px; white-space: pre-wrap">{{ tryBefore || '（点击执行润色后显示原文）' }}</div>
            </div>
            <div>
              <div class="card-title" style="font-size: 13.5px">
                润色后 <span class="tag tag-green">{{ tryScore }}</span>
              </div>
              <div class="code-block" style="min-height: 140px; white-space: pre-wrap">{{ tryAfter }}</div>
            </div>
          </div>
          <div class="flex mt-8">
            <button class="btn btn-ghost btn-sm" @click="copyAfter">📋 复制润色后文本</button>
            <button class="btn btn-ghost btn-sm" @click="saveSample">💾 存为策略样例</button>
          </div>
        </div>
      </template>
    </template>
  </ModuleShell>

  <!-- 新建/编辑策略弹窗 -->
  <div class="modal-mask" :class="{ open: modalOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>{{ editingId ? '编辑策略 · ' + editingId : '＋ 新建策略' }}</h3>
        <button class="modal-close" @click="modalOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="grid grid-2" style="gap: 12px">
          <div class="field">
            <label>策略名称 <span class="text-red">*</span></label>
            <input v-model="fName" class="input" placeholder="如：口语化人味" />
          </div>
          <div class="field">
            <label>启用状态</label>
            <div class="flex" style="gap: 14px">
              <label class="checkbox"><input v-model="fStatus" type="radio" value="启用" /> 启用</label>
              <label class="checkbox"><input v-model="fStatus" type="radio" value="禁用" /> 禁用</label>
            </div>
          </div>
        </div>
        <div class="field">
          <label>描述</label>
          <input v-model="fDesc" class="input" placeholder="策略用途说明" />
        </div>
        <div class="field">
          <label>提示词后缀 <span class="text-red">*</span></label>
          <textarea
            v-model="fSuffix"
            class="textarea mono"
            rows="5"
            placeholder="追加到 AI 提示词后的指令，如：避免排比句与总-分-总模板腔…"
          ></textarea>
          <div class="hint">该后缀将拼接在所有 AI 生成提示词末尾（用例 / 报告 / 缺陷描述）</div>
        </div>
        <div class="field">
          <label>作用范围</label>
          <div class="flex" style="gap: 8px; flex-wrap: wrap">
            <label v-for="s in SCOPES" :key="s" class="checkbox">
              <input v-model="fScope" type="checkbox" :value="s" /> {{ s }}
            </label>
          </div>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="modalOpen = false">取消</button>
        <button class="btn btn-primary" :disabled="saving" @click="savePolicy">
          <span v-if="saving" class="spinner"></span> 💾 保存策略
        </button>
      </div>
    </div>
  </div>

  <!-- 策略详情弹窗 -->
  <div class="modal-mask" :class="{ open: viewOpen }">
    <div class="modal">
      <div class="modal-head">
        <h3>{{ view?.name || '策略详情' }}</h3>
        <button class="modal-close" @click="viewOpen = false">✕</button>
      </div>
      <div class="modal-body" v-if="view">
        <div class="kv"><span>ID</span><b class="mono">{{ view.id }}</b></div>
        <div class="kv"><span>描述</span><b>{{ view.desc }}</b></div>
        <div class="kv"><span>作用范围</span><b>{{ view.scope.join('、') }}</b></div>
        <div class="kv">
          <span>状态</span><b>{{ view.status }} · 已应用 {{ view.uses }} 次</b>
        </div>
        <div class="field mt-16">
          <label>提示词后缀</label>
          <div class="code-block" style="white-space: pre-wrap">{{ view.suffix }}</div>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-primary" @click="viewOpen = false">关闭</button>
      </div>
    </div>
  </div>
</template>
