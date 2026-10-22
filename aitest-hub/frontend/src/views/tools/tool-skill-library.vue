<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import DataTable from '@/components/ui/DataTable.vue'
import { uiToast, uiConfirm } from '@/composables/ui'
import http from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-skill-library.html） ---------- */
interface Skill {
  id: string
  name: string
  icon?: string
  cat: string
  desc: string
  uses: number
  stars?: number
  status: string
  version: string
  author?: string
  updated?: string
  content: string
  params: { tools?: string[]; [k: string]: unknown }
}
interface Usage {
  time: string
  skill: string
  by: string
  scene: string
  dur: string
  result: string
}
interface SkillsResp {
  items: Skill[]
  total: number
  cats: Array<{ cat: string; count: number }>
}
interface UsageStats {
  recent: Usage[]
}

const C_CLS: Record<string, string> = {
  用例设计: 'tag-red',
  缺陷分析: 'tag-orange',
  接口测试: 'tag-blue',
  安全测试: 'tag-purple',
  性能测试: 'tag-green',
  自动化: 'tag',
}
const S_CLS: Record<string, string> = { 已发布: 'tag-green', 草稿: 'tag-orange', 已下架: 'tag' }
const CATS = ['用例设计', '缺陷分析', '接口测试', '安全测试', '性能测试', '自动化']
const TOOL_OPTS = ['用例生成', '数据工厂', '接口测试', '安全基线', '性能分析', '缺陷查重']

const skills = ref<Skill[]>([])
const usages = ref<Usage[]>([])
const kw = ref('')
const cat = ref('')
const status = ref('')

async function reload() {
  const [s, u] = await Promise.all([
    http.get<SkillsResp>('/skills'),
    http.get<UsageStats>('/skills/usage/stats'),
  ])
  skills.value = s.data?.items || []
  usages.value = u.data?.recent || []
}

onMounted(() => {
  void reload().catch(() => undefined)
})

const filtered = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return skills.value.filter(
    (s) =>
      (!k || (s.name + s.desc).toLowerCase().includes(k)) &&
      (!cat.value || s.cat === cat.value) &&
      (!status.value || s.status === status.value),
  )
})

function toolsOf(s: Skill): string[] {
  const t = s.params?.tools
  return Array.isArray(t) ? t : []
}

/* ---------- 调用 / 收藏 ---------- */
const runId = ref<string | null>(null)
async function runSkill(s: Skill) {
  if (runId.value) return
  runId.value = s.id
  uiToast(`正在调用技能「${s.name}」…`, 'info')
  try {
    const { data } = await http.post<{ output: string; tokens: number }>(
      `/skills/${s.id}/run`,
      { input: '' },
    )
    uiToast(`技能调用完成 ✅ 耗 token ${data.tokens}，可在调用记录查看`, 'success')
    await reload()
  } finally {
    runId.value = null
  }
}

async function starSkill(s: Skill) {
  try {
    const { data } = await http.post<{ stars: number }>(`/skills/${s.id}/star`)
    const row = skills.value.find((x) => x.id === s.id)
    if (row) row.stars = data.stars
    uiToast(`已收藏 ★ ${data.stars}`, 'success')
  } catch {
    /* toast by http */
  }
}

/* ---------- 新建/编辑 ---------- */
const modalOpen = ref(false)
const editingId = ref<string | null>(null)
const saving = ref(false)
const fName = ref('')
const fCat = ref(CATS[0])
const fDesc = ref('')
const fPrompt = ref('')
const fSteps = ref('')
const fTools = ref<string[]>(['用例生成'])
const aiDrafting = ref(false)

function openNew() {
  editingId.value = null
  fName.value = ''
  fCat.value = CATS[0]
  fDesc.value = ''
  fPrompt.value = ''
  fSteps.value = ''
  fTools.value = ['用例生成']
  modalOpen.value = true
}

function openEdit(s: Skill) {
  editingId.value = s.id
  fName.value = s.name
  fCat.value = s.cat
  fDesc.value = s.desc
  fPrompt.value = s.content
  fSteps.value = ''
  fTools.value = toolsOf(s)
  modalOpen.value = true
}

function aiDraft() {
  aiDrafting.value = true
  uiToast('AI 正在根据技能名称生成草稿…', 'info')
  setTimeout(() => {
    fPrompt.value =
      '你是一名资深测试工程师。请基于输入的需求或问题，按以下步骤输出结果：\n1. 提取关键业务规则与边界\n2. 给出结构化测试点\n3. 标注优先级与风险'
    fSteps.value = '1. 解析输入内容\n2. 调用用例生成工具\n3. 汇总输出结构化结果'
    aiDrafting.value = false
    uiToast('AI 草稿已生成，请确认后保存', 'success')
  }, 1100)
}

async function saveSkill() {
  const n = fName.value.trim()
  if (!n) {
    uiToast('请填写技能名称', 'error')
    return
  }
  saving.value = true
  try {
    const content = [fPrompt.value, fSteps.value].filter(Boolean).join('\n\n')
    const payload = {
      name: n,
      cat: fCat.value,
      desc: fDesc.value,
      content,
      params: { tools: fTools.value },
    }
    if (editingId.value) {
      await http.put(`/skills/${editingId.value}`, payload)
      uiToast('技能已更新', 'success')
    } else {
      await http.post('/skills', { ...payload, status: '草稿', version: 'v0.1' })
      uiToast('技能已保存为草稿，发布后可被 AI 助手调用', 'success')
    }
    modalOpen.value = false
    await reload()
  } finally {
    saving.value = false
  }
}

function dropSkill(s: Skill) {
  uiConfirm({
    title: '删除技能',
    message: `确定删除「${s.name}」吗？AI 助手将无法再匹配该技能。`,
    onOk: async () => {
      await http.delete(`/skills/${s.id}`)
      await reload()
      uiToast('技能已删除', 'success')
    },
  })
}

const usageColumns = [
  { key: 'time', label: '时间' },
  { key: 'skill', label: '技能' },
  { key: 'by', label: '调用方' },
  { key: 'scene', label: '场景' },
  { key: 'dur', label: '耗时' },
  { key: 'result', label: '结果' },
]
</script>

<template>
  <ModuleShell slug="tool-skill-library">
    <template #actions>
      <RouterLink class="btn btn-ghost" to="/prompts">📚 提示词库</RouterLink>
      <RouterLink class="btn btn-ghost" to="/t/tool-ai-assistant">💬 AI 问答助手</RouterLink>
      <button class="btn btn-primary" @click="openNew">＋ 新建技能</button>
    </template>

    <template #default="{ tab }">
      <div class="banner banner-info">
        ℹ️ 技能 = 提示词模板 + 执行步骤 + 可调用工具的组合包。AI 问答助手会根据问题自动匹配技能；技能可发布版本、统计调用，并在 AI 用例 / 安全 / 性能等模块中直接引用。
      </div>

      <!-- ============ 技能列表 ============ -->
      <template v-if="tab === 'lib'">
        <div class="filter-bar">
          <input v-model="kw" class="input search" placeholder="🔍 搜索技能名称 / 描述" />
          <select v-model="cat" class="select">
            <option value="">全部分类</option>
            <option v-for="c in CATS" :key="c" :value="c">{{ c }}</option>
          </select>
          <select v-model="status" class="select">
            <option value="">全部状态</option>
            <option>已发布</option>
            <option>草稿</option>
            <option>已下架</option>
          </select>
        </div>
        <div class="grid grid-3">
          <div v-for="s in filtered" :key="s.id" class="card card-hover">
            <div class="flex-between">
              <span class="tag" :class="C_CLS[s.cat]">{{ s.cat }}</span>
              <span class="tag">{{ s.version }}</span>
            </div>
            <h3 style="font-size: 15px; margin: 10px 0 6px">{{ s.name }}</h3>
            <p class="text-dim" style="font-size: 12.5px">{{ s.desc }}</p>
            <div class="mt-8">
              <span
                v-for="t in toolsOf(s)"
                :key="t"
                class="tag tag-red"
                style="margin-right: 4px"
              >🔧 {{ t }}</span>
            </div>
            <div class="flex-between mt-16">
              <span class="text-faint" style="font-size: 12px">📊 调用 {{ s.uses }} 次</span>
              <div class="flex">
                <span class="tag" :class="S_CLS[s.status]">{{ s.status }}</span>
                <button class="btn btn-sm btn-ghost" @click="starSkill(s)">★{{ s.stars || 0 }}</button>
                <button class="btn btn-sm btn-ghost" @click="openEdit(s)">编辑</button>
                <button
                  class="btn btn-sm btn-primary"
                  :disabled="runId === s.id"
                  @click="runSkill(s)"
                >
                  <span v-if="runId === s.id" class="spinner"></span>
                  <span v-else>调用</span>
                </button>
                <button class="btn btn-sm btn-danger" @click="dropSkill(s)">删除</button>
              </div>
            </div>
          </div>
          <div v-if="!filtered.length" class="card" style="grid-column: 1 / -1">
            <div class="empty">
              <div class="e-icon">🧩</div>
              <div class="e-text">无匹配技能</div>
            </div>
          </div>
        </div>
      </template>

      <!-- ============ 调用记录 ============ -->
      <template v-if="tab === 'usage'">
        <DataTable
          :columns="usageColumns"
          :rows="usages"
          empty-text="暂无调用记录"
        >
          <template #cell-time="{ row }">
            <span class="mono" style="font-size: 12px">{{ (row as Usage).time }}</span>
          </template>
          <template #cell-skill="{ row }">
            <div class="cell-main">{{ (row as Usage).skill }}</div>
          </template>
          <template #cell-scene="{ row }">
            <span class="cell-sub">{{ (row as Usage).scene }}</span>
          </template>
          <template #cell-dur="{ row }">
            <span class="mono">{{ (row as Usage).dur }}</span>
          </template>
          <template #cell-result="{ row }">
            <span
              class="tag"
              :class="(row as Usage).result === '成功' ? 'tag-green' : 'tag-red'"
            >{{ (row as Usage).result }}</span>
          </template>
        </DataTable>
      </template>
    </template>
  </ModuleShell>

  <!-- 新建/编辑技能弹窗 -->
  <div class="modal-mask" :class="{ open: modalOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>{{ editingId ? '编辑技能 · ' + editingId : '＋ 新建技能' }}</h3>
        <button class="modal-close" @click="modalOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="grid grid-2" style="gap: 12px">
          <div class="field">
            <label>技能名称 <span class="text-red">*</span></label>
            <input v-model="fName" class="input" placeholder="如：退款需求→用例技能包" />
          </div>
          <div class="field">
            <label>分类</label>
            <select v-model="fCat" class="select">
              <option v-for="c in CATS" :key="c" :value="c">{{ c }}</option>
            </select>
          </div>
        </div>
        <div class="field">
          <label>技能描述</label>
          <input v-model="fDesc" class="input" placeholder="一句话说明技能用途" />
        </div>
        <div class="field">
          <label>系统提示词（System Prompt）</label>
          <textarea
            v-model="fPrompt"
            class="textarea mono"
            rows="5"
            placeholder="你是一名资深测试工程师，擅长…"
          ></textarea>
        </div>
        <div class="field">
          <label>执行步骤（每行一步）</label>
          <textarea
            v-model="fSteps"
            class="textarea mono"
            rows="4"
            placeholder="1. 解析需求要点&#10;2. 调用用例生成&#10;3. 输出结构化用例"
          ></textarea>
        </div>
        <div class="field">
          <label>可调用工具（AI 关联）</label>
          <div class="flex" style="gap: 8px; flex-wrap: wrap">
            <label v-for="t in TOOL_OPTS" :key="t" class="checkbox">
              <input v-model="fTools" type="checkbox" :value="t" /> {{ t }}
            </label>
          </div>
          <div class="hint">AI 助手执行该技能时可自动调用以上模块能力（Function Calling）</div>
        </div>
        <button class="btn btn-ghost btn-sm" :disabled="aiDrafting" @click="aiDraft">
          <span v-if="aiDrafting" class="spinner"></span>
          🤖 AI 生成技能草稿
        </button>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="modalOpen = false">取消</button>
        <button class="btn btn-primary" :disabled="saving" @click="saveSkill">
          <span v-if="saving" class="spinner"></span> 💾 保存技能
        </button>
      </div>
    </div>
  </div>
</template>
