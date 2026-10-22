<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import DataTable from '@/components/ui/DataTable.vue'
import { uiToast, uiConfirm } from '@/composables/ui'
import http from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-knowledge-base.html） ---------- */
interface Pattern {
  id: string
  name: string
  title?: string
  cat: string
  uses: number
  tags: string[]
  desc: string
  detail: string
}
interface BugKb {
  id: string
  title: string
  cat: string
  cause: string
  solution: string
  tags: string[]
}
interface Entry {
  id: string
  title: string
  cat: string
  tags: string[]
  created: string
  body: string
  summary?: string
}
interface RagHit {
  type: string
  id: string
  title: string
  snippet: string
  source: string
  score: number
}
interface DetailData {
  title: string
  tags: string[]
  desc: string
  lines: Array<{ k: string; v: string } | null> | null
  body: string
  kind: 'pattern' | 'bug' | 'entry'
  id: string
  cat?: string
  uses?: number
  created?: string
}

const router = useRouter()

const patterns = ref<Pattern[]>([])
const bugs = ref<BugKb[]>([])
const entries = ref<Entry[]>([])

async function reload() {
  const [p, b, e] = await Promise.all([
    http.get<Pattern[]>('/knowledge/patterns'),
    http.get<BugKb[]>('/knowledge/bugs'),
    http.get<Entry[]>('/knowledge/entries'),
  ])
  patterns.value = p.data || []
  bugs.value = b.data || []
  entries.value = e.data || []
}

onMounted(() => {
  reload().catch(() => undefined)
})

/* ================= AI 智能检索（RAG） ================= */
const ragQ = ref('')
const ragOut = ref<RagHit[] | null>(null)
const ragBusy = ref(false)

async function ragSearch() {
  const q = ragQ.value.trim()
  if (!q) {
    uiToast('请输入问题', 'warn')
    return
  }
  ragBusy.value = true
  ragOut.value = []
  try {
    const { data } = await http.get<{ q: string; hits: RagHit[]; total: number }>(
      '/knowledge/rag',
      { params: { q } },
    )
    ragOut.value = data.hits || []
    uiToast(`检索完成，命中 ${data.total ?? ragOut.value.length} 条`, 'success')
  } finally {
    ragBusy.value = false
  }
}

function ragClear() {
  ragQ.value = ''
  ragOut.value = null
}

function scorePct(s: number) {
  return Math.round((s || 0) * 100)
}

/* ================= 测试模式 ================= */
const ptKw = ref('')
const ptCat = ref('')
const ptCats = ['登录', '支付', '表单', '列表', '文件上传']

const ptFiltered = computed(() => {
  const kw = ptKw.value.trim().toLowerCase()
  return patterns.value.filter(
    (p) =>
      (!kw || (p.name + p.desc).toLowerCase().includes(kw)) &&
      (!ptCat.value || p.cat === ptCat.value),
  )
})

/* ================= Bug 知识 ================= */
const bgKw = ref('')
const bgCat = ref('')
const bgCats = ['逻辑缺陷', '边界缺陷', '并发缺陷', '安全缺陷', '兼容缺陷']

const bgFiltered = computed(() => {
  const kw = bgKw.value.trim().toLowerCase()
  return bugs.value.filter(
    (b) =>
      (!kw || (b.title + b.cause).toLowerCase().includes(kw)) &&
      (!bgCat.value || b.cat === bgCat.value),
  )
})

const bugColumns = [
  { key: 'id', label: 'ID' },
  { key: 'title', label: 'Bug 标题' },
  { key: 'cat', label: '类型' },
  { key: 'cause', label: '根因' },
  { key: 'solution', label: '解决方案' },
  { key: 'tags', label: '标签' },
]

function bugCatCls(c: string) {
  if (c === '安全缺陷') return 'tag-red'
  if (c === '并发缺陷') return 'tag-purple'
  return 'tag-orange'
}

/* ================= 知识条目 ================= */
const enKw = ref('')
const enCat = ref('')
const enCats = ['测试规范', '环境手册', '工具指南', '流程说明']

const enFiltered = computed(() => {
  const kw = enKw.value.trim().toLowerCase()
  return entries.value.filter(
    (e) =>
      (!kw || (e.title + e.body).toLowerCase().includes(kw)) &&
      (!enCat.value || e.cat === enCat.value),
  )
})

const entryColumns = [
  { key: 'id', label: 'ID' },
  { key: 'title', label: '标题' },
  { key: 'cat', label: '分类' },
  { key: 'tags', label: '标签' },
  { key: 'created', label: '创建时间' },
]

/* ================= 详情弹窗（模式 / Bug / 条目复用） ================= */
const detailOpen = ref(false)
const detail = ref<DetailData | null>(null)

function viewPattern(p: Pattern) {
  detail.value = {
    title: p.name,
    tags: [],
    desc: p.desc,
    lines: null,
    body: p.detail,
    kind: 'pattern',
    id: p.id,
    cat: p.cat,
    uses: p.uses,
  }
  detailOpen.value = true
}

function viewBug(b: BugKb) {
  detail.value = {
    title: b.title,
    tags: b.tags,
    desc: '',
    lines: [
      { k: '根因', v: b.cause },
      { k: '解决方案', v: b.solution },
      { k: '标签', v: b.tags.map((t) => '#' + t).join(' ') },
    ],
    body: '',
    kind: 'bug',
    id: b.id,
    cat: b.cat,
  }
  detailOpen.value = true
}

function viewEntry(e: Entry) {
  detail.value = {
    title: e.title,
    tags: e.tags,
    desc: '',
    lines: null,
    body: e.body,
    kind: 'entry',
    id: e.id,
    cat: e.cat,
    created: e.created,
  }
  detailOpen.value = true
}

async function usePattern(p: Pattern) {
  try {
    await http.put(`/knowledge/patterns/${encodeURIComponent(p.id)}`, {
      name: p.name,
      cat: p.cat,
      tags: p.tags,
      desc: p.desc,
      detail: p.detail,
      uses: (p.uses || 0) + 1,
    })
  } catch {
    /* 计数失败不阻断跳转 */
  }
  uiToast(`已套用「${p.name}」→ 正在跳转 AI 用例工作台…`, 'success')
  setTimeout(() => {
    router.push({ path: '/t/tool-test-cases', query: { pattern: p.name } })
  }, 900)
}

async function deleteDetail() {
  const d = detail.value
  if (!d) return
  const label = d.kind === 'pattern' ? '测试模式' : d.kind === 'bug' ? 'Bug 知识' : '知识条目'
  const urlMap = {
    pattern: `/knowledge/patterns/${encodeURIComponent(d.id)}`,
    bug: `/knowledge/bugs/${encodeURIComponent(d.id)}`,
    entry: `/knowledge/entries/${encodeURIComponent(d.id)}`,
  }
  uiConfirm({
    title: `删除${label}`,
    message: `确定删除「${d.title}」吗？已被 AI 回答引用的记录不受影响。`,
    danger: true,
    onOk: async () => {
      await http.delete(urlMap[d.kind])
      detailOpen.value = false
      await reload()
      uiToast('已删除', 'success')
    },
  })
}

/* ================= 新建知识条目 ================= */
const enOpen = ref(false)
const efTitle = ref('')
const efCat = ref('测试规范')
const efBody = ref('')
const efTags = ref('')
const efBusy = ref(false)

function openNewEntry() {
  efTitle.value = ''
  efCat.value = '测试规范'
  efBody.value = ''
  efTags.value = ''
  enOpen.value = true
}

async function aiExpand() {
  const t = efTitle.value.trim()
  if (!efBody.value.trim()) {
    // 与设计稿一致：本地生成扩写模板
    efBody.value = `# ${t || '新条目'}

## 适用场景
（AI 扩写：描述何时使用本条知识）

## 步骤 / 规范
1. …
2. …

## 注意事项
- …`
    uiToast('AI 扩写完成，请核对后保存', 'success')
    return
  }
  if (!t) {
    uiToast('请先填写标题', 'warn')
    return
  }
  efBusy.value = true
  uiToast('AI 正在抽取摘要并入库…', 'info')
  try {
    await http.post('/knowledge/entries/ai-ingest', { name: t, text: efBody.value })
    enOpen.value = false
    await reload()
    uiToast('AI 摘要抽取完成，知识条目已入库，可被 AI 检索引用', 'success')
  } finally {
    efBusy.value = false
  }
}

async function saveEntry() {
  const t = efTitle.value.trim()
  if (!t) {
    uiToast('请填写标题', 'error')
    return
  }
  if (!efBody.value.trim()) {
    uiToast('请填写内容', 'error')
    return
  }
  await http.post('/knowledge/entries', {
    title: t,
    cat: efCat.value,
    tags: efTags.value.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
    body: efBody.value,
  })
  enOpen.value = false
  await reload()
  uiToast('知识条目已保存，可被 AI 检索引用', 'success')
}

function deleteEntry(e: Entry) {
  uiConfirm({
    title: '删除知识条目',
    message: `确定删除「${e.title}」吗？已被 AI 回答引用的记录不受影响。`,
    danger: true,
    onOk: async () => {
      await http.delete(`/knowledge/entries/${encodeURIComponent(e.id)}`)
      await reload()
      uiToast('条目已删除', 'success')
    },
  })
}
</script>

<template>
  <ModuleShell slug="tool-knowledge-base">
    <template #actions>
      <RouterLink class="btn btn-ghost" to="/t/tool-ai-assistant">💬 去 AI 问答验证引用</RouterLink>
      <button class="btn btn-primary" @click="openNewEntry">＋ 新建知识条目</button>
    </template>

    <template #default="{ tab }">
      <div class="banner banner-info">
        ℹ️ 对应平台 KnowledgeBase 模块：三类资产——<strong>测试模式</strong>（可复用测试套路）、<strong>Bug 知识</strong>（根因 + 解决方案）、<strong>知识条目</strong>（通用文档）；AI 问答助手开启 RAG 时将检索本库并在回答中标注引用来源。
      </div>

      <!-- AI 智能检索 -->
      <div class="card mb-16">
        <div class="card-title">🧠 AI 智能检索 <span class="tag tag-red">RAG</span></div>
        <div class="input-group">
          <input
            v-model="ragQ"
            class="input"
            placeholder="输入问题，如：如何测试登录功能 / 支付金额校验出过哪些 Bug"
            @keydown.enter="ragSearch"
          />
          <button class="btn btn-primary" :disabled="ragBusy" @click="ragSearch">🔍 智能检索</button>
          <button class="btn btn-ghost" @click="ragClear">清除</button>
        </div>
        <div v-if="ragOut !== null" style="margin-top: 12px">
          <div v-if="ragBusy" class="text-dim" style="font-size: 13px">🔍 正在检索知识库…</div>
          <template v-else>
            <div class="card-title" style="font-size: 13.5px">
              🎯 命中 {{ ragOut.length }} 条知识（按相关度排序）
            </div>
            <div
              v-for="h in ragOut"
              :key="h.type + h.id"
              class="flex-between"
              style="padding: 9px 12px; border: 1px solid var(--border); border-radius: 8px; margin-top: 8px"
            >
              <div style="min-width: 0">
                <div style="font-size: 13px; font-weight: 600">
                  {{ h.title }} <span class="tag" style="font-size: 10.5px">{{ h.type }}</span>
                </div>
                <div class="text-dim" style="font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
                  {{ h.snippet }}
                </div>
              </div>
              <span class="tag tag-green" style="flex-shrink: 0">相关 {{ scorePct(h.score) }}%</span>
            </div>
            <div class="text-faint mt-8" style="font-size: 11.5px">
              💡 以上引用已同步至 AI 问答助手 RAG 上下文；如需追问可前往
              <RouterLink to="/t/tool-ai-assistant">AI 问答助手</RouterLink>
            </div>
          </template>
        </div>
      </div>

      <!-- ============ 测试模式 ============ -->
      <template v-if="tab === 'patterns'">
        <div class="filter-bar">
          <input v-model="ptKw" class="input search" placeholder="🔍 搜索模式名称 / 描述" />
          <select v-model="ptCat" class="select">
            <option value="">全部类型</option>
            <option v-for="c in ptCats" :key="c" :value="c">{{ c }}</option>
          </select>
        </div>
        <div class="grid grid-3">
          <template v-if="ptFiltered.length">
            <div v-for="p in ptFiltered" :key="p.id" class="card card-hover">
              <div class="flex-between">
                <span class="tag tag-blue">{{ p.cat }}</span>
                <span class="text-faint" style="font-size: 11.5px">📊 {{ p.uses }} 次</span>
              </div>
              <h3 style="font-size: 15px; margin: 10px 0 6px">{{ p.name }}</h3>
              <p class="text-dim" style="font-size: 12.5px">{{ p.desc }}</p>
              <div class="mt-8">
                <span
                  v-for="t in p.tags"
                  :key="t"
                  class="tag tag-orange"
                  style="margin-right: 4px"
                >#{{ t }}</span>
              </div>
              <div class="flex-between mt-16">
                <span class="text-faint mono" style="font-size: 11px">{{ p.id }}</span>
                <div class="flex">
                  <button class="btn btn-sm btn-ghost" @click="viewPattern(p)">查看</button>
                  <button class="btn btn-sm btn-primary" @click="usePattern(p)">使用</button>
                </div>
              </div>
            </div>
          </template>
          <div v-else class="card" style="grid-column: 1 / -1">
            <div class="empty"><div class="e-icon">🧪</div><div class="e-text">无匹配测试模式</div></div>
          </div>
        </div>
      </template>

      <!-- ============ Bug 知识 ============ -->
      <template v-if="tab === 'bugs'">
        <div class="filter-bar">
          <input v-model="bgKw" class="input search" placeholder="🔍 搜索 Bug 标题 / 根因" />
          <select v-model="bgCat" class="select">
            <option value="">全部类型</option>
            <option v-for="c in bgCats" :key="c" :value="c">{{ c }}</option>
          </select>
        </div>
        <DataTable :columns="bugColumns" :rows="bgFiltered" empty-text="无匹配 Bug 知识">
          <template #cell-id="{ row }">
            <span class="mono">{{ (row as BugKb).id }}</span>
          </template>
          <template #cell-title="{ row }">
            <div class="cell-main" style="font-size: 12.5px">{{ (row as BugKb).title }}</div>
          </template>
          <template #cell-cat="{ row }">
            <span class="tag" :class="bugCatCls((row as BugKb).cat)">{{ (row as BugKb).cat }}</span>
          </template>
          <template #cell-cause="{ row }">
            <div class="cell-sub" style="font-size: 12px; max-width: 200px">{{ (row as BugKb).cause }}</div>
          </template>
          <template #cell-solution="{ row }">
            <div class="cell-sub" style="font-size: 12px; max-width: 220px">{{ (row as BugKb).solution }}</div>
          </template>
          <template #cell-tags="{ row }">
            <span
              v-for="t in (row as BugKb).tags"
              :key="t"
              class="tag"
              style="margin-right: 3px"
            >#{{ t }}</span>
          </template>
          <template #actions="{ row }">
            <button class="btn btn-sm btn-ghost" @click="viewBug(row as BugKb)">详情</button>
          </template>
        </DataTable>
      </template>

      <!-- ============ 知识条目 ============ -->
      <template v-if="tab === 'entries'">
        <div class="filter-bar">
          <input v-model="enKw" class="input search" placeholder="🔍 搜索条目标题 / 内容" />
          <select v-model="enCat" class="select">
            <option value="">全部分类</option>
            <option v-for="c in enCats" :key="c" :value="c">{{ c }}</option>
          </select>
        </div>
        <DataTable :columns="entryColumns" :rows="enFiltered" empty-text="无匹配条目">
          <template #cell-id="{ row }">
            <span class="mono">{{ (row as Entry).id }}</span>
          </template>
          <template #cell-title="{ row }">
            <div class="cell-main" style="font-size: 12.5px">{{ (row as Entry).title }}</div>
          </template>
          <template #cell-cat="{ row }">
            <span class="tag tag-blue">{{ (row as Entry).cat }}</span>
          </template>
          <template #cell-tags="{ row }">
            <span
              v-for="t in (row as Entry).tags"
              :key="t"
              class="tag"
              style="margin-right: 3px"
            >#{{ t }}</span>
          </template>
          <template #cell-created="{ row }">
            <span class="mono" style="font-size: 12px">{{ (row as Entry).created }}</span>
          </template>
          <template #actions="{ row }">
            <button class="btn btn-sm btn-ghost" @click="viewEntry(row as Entry)">查看</button>
            <button class="btn btn-sm btn-danger" @click="deleteEntry(row as Entry)">删除</button>
          </template>
        </DataTable>
      </template>
    </template>
  </ModuleShell>

  <!-- 新建/编辑条目弹窗 -->
  <div class="modal-mask" :class="{ open: enOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>＋ 新建知识条目</h3>
        <button class="modal-close" @click="enOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="grid grid-2" style="gap: 12px">
          <div class="field">
            <label>标题 <span class="text-red">*</span></label>
            <input v-model="efTitle" class="input" placeholder="知识条目标题" />
          </div>
          <div class="field">
            <label>分类</label>
            <select v-model="efCat" class="select">
              <option v-for="c in enCats" :key="c" :value="c">{{ c }}</option>
            </select>
          </div>
        </div>
        <div class="field">
          <label>内容（Markdown） <span class="text-red">*</span></label>
          <textarea
            v-model="efBody"
            class="textarea mono"
            rows="6"
            placeholder="支持 Markdown 语法…"
          ></textarea>
        </div>
        <div class="field">
          <label>标签</label>
          <input v-model="efTags" class="input" placeholder="逗号分隔，如：登录,安全,P0" />
        </div>
        <button class="btn btn-ghost btn-sm" :disabled="efBusy" @click="aiExpand">🤖 AI 辅助扩写</button>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="enOpen = false">取消</button>
        <button class="btn btn-primary" @click="saveEntry">💾 保存条目</button>
      </div>
    </div>
  </div>

  <!-- 详情弹窗（模式 / Bug / 条目） -->
  <div class="modal-mask" :class="{ open: detailOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>{{ detail?.title || '详情' }}</h3>
        <button class="modal-close" @click="detailOpen = false">✕</button>
      </div>
      <div class="modal-body" v-if="detail">
        <div class="flex mb-8" v-if="detail.kind === 'pattern'">
          <span class="tag tag-blue">{{ detail.cat }}</span>
          <span class="tag">{{ detail.id }}</span>
          <span class="tag tag-green">使用 {{ detail.uses ?? 0 }} 次</span>
        </div>
        <div class="flex mb-8" v-else-if="detail.kind === 'bug'">
          <span class="tag tag-orange">{{ detail.cat }}</span>
          <span class="tag">{{ detail.id }}</span>
        </div>
        <div class="flex mb-8" v-else>
          <span class="tag tag-blue">{{ detail.cat }}</span>
          <span class="tag">{{ detail.id }}</span>
          <span class="tag mono" style="font-size: 11px">{{ detail.created }}</span>
        </div>

        <template v-if="detail.kind === 'pattern'">
          <div class="text-dim" style="font-size: 13px; margin-bottom: 12px">{{ detail.desc }}</div>
          <div class="field">
            <label>模式要点（测试点清单）</label>
            <div class="code-block" style="white-space: pre-wrap">{{ detail.body }}</div>
          </div>
        </template>

        <template v-else-if="detail.kind === 'bug'">
          <div v-for="l in detail.lines" :key="l?.k" class="kv">
            <span>{{ l?.k }}</span>
            <b style="font-weight: 500">{{ l?.v }}</b>
          </div>
        </template>

        <template v-else>
          <div class="code-block" style="white-space: pre-wrap">{{ detail.body }}</div>
        </template>
      </div>
      <div class="modal-foot">
        <button class="btn btn-danger" @click="deleteDetail">🗑 删除</button>
        <button class="btn btn-ghost" @click="detailOpen = false">关闭</button>
        <RouterLink
          v-if="detail?.kind === 'pattern'"
          class="btn btn-primary"
          to="/t/tool-test-cases"
        >✨ 去用例工作台套用 →</RouterLink>
        <RouterLink
          v-else-if="detail?.kind === 'bug'"
          class="btn btn-primary"
          to="/t/tool-defect-management"
        >🐞 前往缺陷管理 →</RouterLink>
        <RouterLink
          v-else-if="detail?.kind === 'entry'"
          class="btn btn-primary"
          to="/t/tool-ai-assistant"
        >💬 在 AI 问答中引用 →</RouterLink>
      </div>
    </div>
  </div>
</template>
