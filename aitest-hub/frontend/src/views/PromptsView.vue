<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import http from '@/api/http'
import { uiToast } from '@/composables/ui'
import { useApp } from '@/stores/app'

/* 提示词库主内容（对照 UI/prompts.html）：breadcrumb + page-head + tabs
   三个子模块：
   ① 提示词列表 — 公共库 CRUD + 收藏 + 查看/复制 + 分页
   ② 我的收藏   — 与列表同款卡片/筛选/分页，按用户收藏
   ③ 投稿管理   — 三栏流程引导 + 我的投稿表格 + 状态流（待评审/已发布/已驳回）
   顶栏与 workspace 壳由 WorkspaceLayout 提供 */
interface PromptItem {
  id: number
  title: string
  cat: string
  tags: string[]
  stars: number
  uses: number
  updated: string
  content: string
  visibility: string
  status: string
  starred: boolean
  owner_id?: number | null
  note?: string
  reject_reason?: string
}

const CATS = ['测试设计', '缺陷分析', '接口测试', '自动化', '性能测试', 'AI 用例']
const STATUS_TAG: Record<string, string> = {
  已发布: 'tag-green',
  待评审: 'tag-orange',
  已驳回: 'tag-red',
  草稿: '',
}

const TABS = [
  { key: 'all', label: '📚 提示词列表' },
  { key: 'favs', label: '⭐ 我的收藏' },
  { key: 'submit', label: '📮 投稿管理' },
] as const
type TabKey = (typeof TABS)[number]['key']

const app = useApp()
/* 与 WorkspaceLayout 注入侧栏共享；主区 tabs 仍保留 DOM（设计稿隐藏显示） */
const activeTab = computed({
  get: () => app.promptsTab as TabKey,
  set: (v: TabKey) => app.setPromptsTab(v),
})

const list = ref<PromptItem[]>([])
const loading = ref(false)

const kw = ref('')
const cat = ref('')
const sort = ref<'hot' | 'new'>('hot')
const page = ref(1)
/* 分页展示（用户第四轮反馈）：每页 6 条 = grid-3 两行，配合钉底分页条，
   一屏内可见末行卡片与分页，不再依赖"整页滑到底" */
const pageSize = ref(6)

/* ---- 收藏 tab（独立数据 + 筛选 + 分页，样式与列表一致） ---- */
const favs = ref<PromptItem[]>([])
const favKw = ref('')
const favCat = ref('')
const favSort = ref<'hot' | 'new'>('hot')
const favPage = ref(1)
const favsLoading = ref(false)

/* ---- 投稿管理 ---- */
const mine = ref<PromptItem[]>([])
const mineLoading = ref(false)
const subFilter = ref('') // '' | 待评审 | 已发布 | 已驳回

/* ---- 新建/编辑弹窗（列表 CRUD + 投稿共用表单） ---- */
const showForm = ref(false)
const formMode = ref<'create' | 'edit' | 'submit'>('create')
const formId = ref<number | null>(null)
const formTitle = ref('')
const formCat = ref(CATS[0])
const formContent = ref('')
const formTags = ref('')
const formNote = ref('')
const formBusy = ref(false)

/* ---- 删除确认 ---- */
const showDel = ref(false)
const delItem = ref<PromptItem | null>(null)
const delBusy = ref(false)

/* ---- 驳回原因 ---- */
const showReject = ref(false)
const rejectItem = ref<PromptItem | null>(null)
const rejectReason = ref('')
const rejectBusy = ref(false)

/* ---- 查看弹窗 ---- */
const showView = ref(false)
const viewItem = ref<PromptItem | null>(null)

let kwTimer: ReturnType<typeof setTimeout> | null = null
let favKwTimer: ReturnType<typeof setTimeout> | null = null

/* ================= 列表：过滤 / 分页 ================= */
const filtered = computed(() => {
  let d = list.value.slice()
  if (cat.value) d = d.filter((p) => p.cat === cat.value)
  const q = kw.value.trim().toLowerCase()
  if (q) {
    d = d.filter((p) =>
      (p.title + p.content + p.tags.join('')).toLowerCase().includes(q),
    )
  }
  d.sort((a, b) =>
    sort.value === 'hot' ? b.uses - a.uses : b.updated.localeCompare(a.updated),
  )
  return d
})

const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize.value)))

const pageRows = computed(() => {
  const p = Math.min(page.value, pages.value)
  return filtered.value.slice((p - 1) * pageSize.value, p * pageSize.value)
})

const pageNums = computed(() => {
  const total = pages.value
  const cur = Math.min(page.value, total)
  const start = Math.max(1, cur - 2)
  const end = Math.min(total, start + 4)
  const out: number[] = []
  for (let i = start; i <= end; i++) out.push(i)
  return out
})

const resultCount = computed(() => `共 ${filtered.value.length} 条模板`)

/** 设计稿 renderCard：预览内容 slice(0,90) + '…'（UI/prompts.html） */
function clipPreview(s: string) {
  return s.slice(0, 90) + '…'
}

/* ================= 收藏：过滤 / 分页 ================= */
const favFiltered = computed(() => {
  let d = favs.value.slice()
  if (favCat.value) d = d.filter((p) => p.cat === favCat.value)
  const q = favKw.value.trim().toLowerCase()
  if (q) {
    d = d.filter((p) =>
      (p.title + p.content + p.tags.join('')).toLowerCase().includes(q),
    )
  }
  d.sort((a, b) =>
    favSort.value === 'hot' ? b.uses - a.uses : b.updated.localeCompare(a.updated),
  )
  return d
})

const favPages = computed(() =>
  Math.max(1, Math.ceil(favFiltered.value.length / pageSize.value)),
)

const favPageRows = computed(() => {
  const p = Math.min(favPage.value, favPages.value)
  return favFiltered.value.slice((p - 1) * pageSize.value, p * pageSize.value)
})

const favNums = computed(() => {
  const total = favPages.value
  const cur = Math.min(favPage.value, total)
  const start = Math.max(1, cur - 2)
  const end = Math.min(total, start + 4)
  const out: number[] = []
  for (let i = start; i <= end; i++) out.push(i)
  return out
})

/* ================= 投稿统计（三栏流程用） ================= */
const mineFiltered = computed(() => {
  let d = mine.value.slice()
  if (subFilter.value) d = d.filter((p) => p.status === subFilter.value)
  return d
})

const mineStats = computed(() => ({
  total: mine.value.length,
  pending: mine.value.filter((p) => p.status === '待评审').length,
  published: mine.value.filter((p) => p.status === '已发布').length,
  rejected: mine.value.filter((p) => p.status === '已驳回').length,
}))

/* ================= 加载 ================= */
async function load() {
  loading.value = true
  try {
    const params: Record<string, string> = {}
    if (cat.value) params.cat = cat.value
    if (kw.value.trim()) params.q = kw.value.trim()
    const { data } = await http.get<PromptItem[]>('/prompts', { params })
    list.value = Array.isArray(data) ? data : []
  } catch {
    list.value = []
  }
  loading.value = false
}

async function loadFavs() {
  favsLoading.value = true
  try {
    const { data } = await http.get<PromptItem[]>('/prompts/favorites')
    favs.value = Array.isArray(data) ? data : []
  } catch {
    favs.value = []
  }
  favsLoading.value = false
}

async function loadMine() {
  mineLoading.value = true
  try {
    const { data } = await http.get<PromptItem[]>('/prompts/mine')
    mine.value = Array.isArray(data) ? data : []
  } catch {
    mine.value = []
  }
  mineLoading.value = false
}

async function reloadAll() {
  await Promise.all([load(), loadFavs(), loadMine()])
}

/* ================= 筛选交互 ================= */
function onKwInput() {
  if (kwTimer) clearTimeout(kwTimer)
  kwTimer = setTimeout(() => {
    page.value = 1
    void load()
  }, 250)
}

function onCatChange() {
  page.value = 1
  void load()
}

function onSortChange() {
  page.value = 1
}

function resetFilters() {
  kw.value = ''
  cat.value = ''
  page.value = 1
  void load()
}

function goto(p: number) {
  if (p >= 1 && p <= pages.value) page.value = p
}

function onSizeChange() {
  page.value = 1
  favPage.value = 1
}

function onFavKwInput() {
  if (favKwTimer) clearTimeout(favKwTimer)
  favKwTimer = setTimeout(() => {
    favPage.value = 1
  }, 250)
}

function favGoto(p: number) {
  if (p >= 1 && p <= favPages.value) favPage.value = p
}

/* ================= 收藏 ================= */
async function toggleStar(p: PromptItem) {
  try {
    const { data } = await http.post<PromptItem>(`/prompts/${p.id}/star`)
    syncItem(data)
    if (data.starred) {
      if (!favs.value.some((x) => x.id === data.id)) favs.value.unshift(data)
      uiToast('已收藏', 'success')
    } else {
      favs.value = favs.value.filter((x) => x.id !== data.id)
      uiToast('已取消收藏', 'info')
    }
  } catch {
    /* 拦截器已 toast */
  }
}

function syncItem(data: PromptItem) {
  const i = list.value.findIndex((x) => x.id === data.id)
  if (i >= 0) list.value[i] = data
  const j = favs.value.findIndex((x) => x.id === data.id)
  if (j >= 0) favs.value[j] = data
  const k = mine.value.findIndex((x) => x.id === data.id)
  if (k >= 0) mine.value[k] = data
}

/* ================= 查看 / 复制 ================= */
function preview(p: PromptItem) {
  viewItem.value = p
  showView.value = true
}

async function copyText(text: string, okMsg: string) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.left = '-9999px'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    uiToast(okMsg, 'success')
  } catch {
    uiToast('复制失败，请手动选择文本', 'error')
  }
}

function copyOne(p: PromptItem) {
  void copyText(p.content, `已复制「${p.title}」`)
}

function copyView() {
  if (viewItem.value) void copyText(viewItem.value.content, '已复制全文')
}

/* ================= 表单：新建 / 编辑 / 投稿 ================= */
function openCreate() {
  formMode.value = 'create'
  formId.value = null
  formTitle.value = ''
  formCat.value = CATS[0]
  formContent.value = ''
  formTags.value = ''
  formNote.value = ''
  showForm.value = true
}

function openSubmit() {
  formMode.value = 'submit'
  formId.value = null
  formTitle.value = ''
  formCat.value = CATS[0]
  formContent.value = ''
  formTags.value = ''
  formNote.value = ''
  showForm.value = true
}

function openEdit(p: PromptItem) {
  formMode.value = 'edit'
  formId.value = p.id
  formTitle.value = p.title
  formCat.value = p.cat
  formContent.value = p.content
  formTags.value = p.tags.join(', ')
  formNote.value = p.note || ''
  showForm.value = true
}

function closeForm() {
  showForm.value = false
}

function parseTags(raw: string): string[] {
  return raw
    .split(/[,，]/)
    .map((t) => t.trim())
    .filter(Boolean)
}

async function saveForm() {
  const t = formTitle.value.trim()
  const c = formContent.value.trim()
  if (!t) {
    uiToast('请填写标题', 'error')
    return
  }
  if (!c) {
    uiToast('请填写提示词内容', 'error')
    return
  }
  formBusy.value = true
  try {
    const tags = parseTags(formTags.value)
    const note = formNote.value.trim()
    if (formMode.value === 'edit' && formId.value != null) {
      const { data } = await http.put<PromptItem>(`/prompts/${formId.value}`, {
        title: t,
        cat: formCat.value,
        content: c,
        tags: tags.length ? tags : undefined,
        note,
      })
      syncItem(data)
      uiToast('已保存修改', 'success')
    } else {
      const status = formMode.value === 'submit' ? '待评审' : '已发布'
      const payloadTags = tags.length ? tags : formMode.value === 'submit' ? ['投稿'] : []
      await http.post('/prompts', {
        title: t,
        cat: formCat.value,
        content: c,
        tags: payloadTags,
        note,
        status,
      })
      if (formMode.value === 'submit') {
        uiToast('投稿成功，已进入「待评审」', 'success')
        activeTab.value = 'submit'
      } else {
        uiToast('已创建并加入列表', 'success')
        sort.value = 'new'
      }
      page.value = 1
    }
    showForm.value = false
    await reloadAll()
  } catch {
    /* 拦截器已 toast */
  }
  formBusy.value = false
}

function formTitleText() {
  if (formMode.value === 'edit') return '✏️ 编辑提示词'
  if (formMode.value === 'submit') return '📮 投稿提示词'
  return '＋ 新建提示词'
}

function formOkText() {
  if (formMode.value === 'edit') return '保存修改'
  if (formMode.value === 'submit') return '提交投稿'
  return '创建提示词'
}

/* ================= 删除 ================= */
function askDelete(p: PromptItem) {
  delItem.value = p
  showDel.value = true
}

function closeDel() {
  showDel.value = false
  delItem.value = null
}

async function confirmDelete() {
  if (!delItem.value) return
  delBusy.value = true
  try {
    await http.delete(`/prompts/${delItem.value.id}`)
    const id = delItem.value.id
    list.value = list.value.filter((x) => x.id !== id)
    favs.value = favs.value.filter((x) => x.id !== id)
    mine.value = mine.value.filter((x) => x.id !== id)
    uiToast('已删除', 'success')
    showDel.value = false
    delItem.value = null
  } catch {
    /* 拦截器已 toast */
  }
  delBusy.value = false
}

/* ================= 投稿状态流 ================= */
async function setStatus(p: PromptItem, action: 'review' | 'approve') {
  try {
    const { data } = await http.post<PromptItem>(`/prompts/${p.id}/${action}`)
    syncItem(data)
    uiToast(action === 'approve' ? '已通过并发布' : '已提交评审', 'success')
    await reloadAll()
  } catch {
    /* 拦截器已 toast */
  }
}

function askReject(p: PromptItem) {
  rejectItem.value = p
  rejectReason.value = ''
  showReject.value = true
}

function closeReject() {
  showReject.value = false
  rejectItem.value = null
}

async function confirmReject() {
  if (!rejectItem.value) return
  rejectBusy.value = true
  try {
    const { data } = await http.post<PromptItem>(
      `/prompts/${rejectItem.value.id}/reject`,
      { reason: rejectReason.value.trim() },
    )
    syncItem(data)
    uiToast('已驳回', 'info')
    showReject.value = false
    rejectItem.value = null
    await reloadAll()
  } catch {
    /* 拦截器已 toast */
  }
  rejectBusy.value = false
}

function closeView() {
  showView.value = false
}

/* 切 tab 时按需加载 */
function onTabChange(t: TabKey) {
  activeTab.value = t
  if (t === 'favs') void loadFavs()
  if (t === 'submit') void loadMine()
}

onMounted(() => {
  void reloadAll()
})

onUnmounted(() => {
  if (kwTimer) clearTimeout(kwTimer)
  if (favKwTimer) clearTimeout(favKwTimer)
})
</script>

<template>
  <div class="prompts-view">
    <div class="breadcrumb"><RouterLink to="/app">工具台</RouterLink> / 提示词库</div>
    <div class="page-head">
      <div>
        <h1>📚 提示词库</h1>
        <div class="sub">实战验证的测试提示词模板，按场景分类，一键复制到 Cursor / Agent 即用</div>
      </div>
      <div class="flex">
        <button class="btn" type="button" @click="openCreate">＋ 新建提示词</button>
        <button class="btn btn-primary" type="button" @click="openSubmit">＋ 投稿提示词</button>
      </div>
    </div>

    <div class="tabs">
      <button
        v-for="t in TABS"
        :key="t.key"
        class="tab"
        :class="{ active: activeTab === t.key }"
        type="button"
        @click="onTabChange(t.key)"
      >{{ t.label }}</button>
    </div>

    <!-- 结构：header 固定 + panes 占满剩余高度（滚动区 + 钉底分页） -->
    <div class="tab-panes prompts-panes">
      <!-- ========== ① 提示词列表 ========== -->
      <div v-if="activeTab === 'all'" class="tab-pane active prompts-pane">
        <div class="prompts-scroll">
          <div class="filter-bar">
            <input
              v-model="kw"
              class="input search"
              placeholder="🔍 搜索标题 / 标签 / 内容关键词"
              @input="onKwInput"
            >
            <select v-model="cat" class="select" @change="onCatChange">
              <option value="">全部分类</option>
              <option v-for="c in CATS" :key="c" :value="c">{{ c }}</option>
            </select>
            <select v-model="sort" class="select" @change="onSortChange">
              <option value="hot">按热度排序</option>
              <option value="new">按最新排序</option>
            </select>
            <span class="text-faint" style="font-size:12.5px">{{ resultCount }}</span>
          </div>

          <div v-if="loading && !list.length" class="card">
            <div class="empty"><span class="spinner"></span><div class="e-text mt-8">加载中…</div></div>
          </div>

          <div v-else-if="!pageRows.length" class="card">
            <div class="empty">
              <div class="e-icon">🔍</div>
              <div class="e-text">未找到匹配的提示词</div>
              <button class="btn btn-sm btn-ghost mt-8" type="button" @click="resetFilters">重置筛选</button>
            </div>
          </div>

          <div v-else class="grid grid-3">
            <div v-for="p in pageRows" :key="p.id" class="card card-hover prompt-card">
              <div class="pc-top">
                <div class="pc-top-left">
                  <span class="tag tag-blue">{{ p.cat }}</span>
                  <span v-if="p.status && p.status !== '已发布'" class="tag" :class="STATUS_TAG[p.status]">{{ p.status }}</span>
                </div>
                <button class="btn btn-sm btn-ghost pc-star" type="button" title="收藏" @click="toggleStar(p)">
                  {{ p.starred ? '⭐' : '☆' }}
                </button>
              </div>
              <h3 class="pc-title">{{ p.title }}</h3>
              <div class="pc-meta">🔥 {{ p.uses }} · {{ p.updated }}</div>
              <div class="prompt-preview pc-preview">{{ clipPreview(p.content) }}</div>
              <div class="pc-foot">
                <div class="pc-tags">
                  <span v-for="t in p.tags" :key="t" class="tag">{{ t }}</span>
                </div>
                <div class="pc-actions">
                  <button class="btn btn-sm btn-ghost" type="button" @click="preview(p)">查看</button>
                  <button class="btn btn-sm btn-ghost" type="button" @click="openEdit(p)">编辑</button>
                  <button class="btn btn-sm btn-danger" type="button" @click="askDelete(p)">删除</button>
                  <button class="btn btn-sm btn-primary" type="button" @click="copyOne(p)">复制</button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 分页条：滚动区外、pane 底部 flex:none —— 不依赖 sticky/margin/v-if -->
        <div class="prompts-pager">
          <div class="pagination">
            <span class="page-info">共 {{ filtered.length }} 条 · 第 {{ Math.min(page, pages) }}/{{ pages }} 页</span>
            <label class="pg-size">每页
              <select v-model.number="pageSize" class="pg-size-sel" @change="onSizeChange">
                <option :value="6">6</option>
                <option :value="10">10</option>
                <option :value="20">20</option>
                <option :value="50">50</option>
                <option :value="100">100</option>
              </select> 条
            </label>
            <button class="page-btn txt" type="button" @click="goto(1)">首页</button>
            <button
              class="page-btn txt"
              type="button"
              :disabled="Math.min(page, pages) <= 1"
              @click="goto(Math.min(page, pages) - 1)"
            >上一页</button>
            <button
              v-for="n in pageNums"
              :key="n"
              class="page-btn"
              :class="{ active: n === Math.min(page, pages) }"
              type="button"
              @click="goto(n)"
            >{{ n }}</button>
            <button
              class="page-btn txt"
              type="button"
              :disabled="Math.min(page, pages) >= pages"
              @click="goto(Math.min(page, pages) + 1)"
            >下一页</button>
            <button class="page-btn txt" type="button" @click="goto(pages)">末页</button>
          </div>
        </div>
      </div>

      <!-- ========== ② 我的收藏（与列表同款） ========== -->
      <div v-else-if="activeTab === 'favs'" class="tab-pane active prompts-pane">
        <div class="prompts-scroll">
          <div class="banner">收藏内容来自「提示词列表」中点击 ☆/⭐ 收藏的模板，按你的账号独立保存，可直接查看与复制。</div>
          <div class="filter-bar">
            <input
              v-model="favKw"
              class="input search"
              placeholder="🔍 搜索已收藏标题 / 标签 / 内容"
              @input="onFavKwInput"
            >
            <select v-model="favCat" class="select">
              <option value="">全部分类</option>
              <option v-for="c in CATS" :key="c" :value="c">{{ c }}</option>
            </select>
            <select v-model="favSort" class="select">
              <option value="hot">按热度排序</option>
              <option value="new">按最新排序</option>
            </select>
            <span class="text-faint" style="font-size:12.5px">共 {{ favFiltered.length }} 条收藏</span>
          </div>

          <div v-if="favsLoading && !favs.length" class="card">
            <div class="empty"><span class="spinner"></span><div class="e-text mt-8">加载中…</div></div>
          </div>

          <div v-else-if="!favPageRows.length" class="card">
            <div class="empty">
              <div class="e-icon">⭐</div>
              <div class="e-text">还没有收藏 —— 在「提示词列表」点击 ☆ 收藏常用模板</div>
            </div>
          </div>

          <div v-else class="grid grid-3">
            <div v-for="p in favPageRows" :key="p.id" class="card card-hover prompt-card">
              <div class="pc-top">
                <div class="pc-top-left">
                  <span class="tag tag-blue">{{ p.cat }}</span>
                  <span v-if="p.status && p.status !== '已发布'" class="tag" :class="STATUS_TAG[p.status]">{{ p.status }}</span>
                </div>
                <button class="btn btn-sm btn-ghost pc-star" type="button" title="取消收藏" @click="toggleStar(p)">⭐</button>
              </div>
              <h3 class="pc-title">{{ p.title }}</h3>
              <div class="pc-meta">🔥 {{ p.uses }} · {{ p.updated }}</div>
              <div class="prompt-preview pc-preview">{{ clipPreview(p.content) }}</div>
              <div class="pc-foot">
                <div class="pc-tags">
                  <span v-for="t in p.tags" :key="t" class="tag">{{ t }}</span>
                </div>
                <div class="pc-actions">
                  <button class="btn btn-sm btn-ghost" type="button" @click="preview(p)">查看</button>
                  <button class="btn btn-sm btn-ghost" type="button" @click="toggleStar(p)">取消收藏</button>
                  <button class="btn btn-sm btn-primary" type="button" @click="copyOne(p)">复制</button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="prompts-pager">
          <div class="pagination">
            <span class="page-info">共 {{ favFiltered.length }} 条 · 第 {{ Math.min(favPage, favPages) }}/{{ favPages }} 页</span>
            <label class="pg-size">每页
              <select v-model.number="pageSize" class="pg-size-sel" @change="onSizeChange">
                <option :value="6">6</option>
                <option :value="10">10</option>
                <option :value="20">20</option>
                <option :value="50">50</option>
                <option :value="100">100</option>
              </select> 条
            </label>
            <button class="page-btn txt" type="button" @click="favGoto(1)">首页</button>
            <button
              class="page-btn txt"
              type="button"
              :disabled="Math.min(favPage, favPages) <= 1"
              @click="favGoto(Math.min(favPage, favPages) - 1)"
            >上一页</button>
            <button
              v-for="n in favNums"
              :key="n"
              class="page-btn"
              :class="{ active: n === Math.min(favPage, favPages) }"
              type="button"
              @click="favGoto(n)"
            >{{ n }}</button>
            <button
              class="page-btn txt"
              type="button"
              :disabled="Math.min(favPage, favPages) >= favPages"
              @click="favGoto(Math.min(favPage, favPages) + 1)"
            >下一页</button>
            <button class="page-btn txt" type="button" @click="favGoto(favPages)">末页</button>
          </div>
        </div>
      </div>

      <!-- ========== ③ 投稿管理：三栏流程 + 我的投稿 ========== -->
      <div v-else-if="activeTab === 'submit'" class="tab-pane active prompts-pane">
        <div class="prompts-scroll">
          <!-- 三栏 = 完整投稿流程（编写 → 提交 → 入库），带实时状态计数 -->
          <div class="flow-steps">
            <div class="card flow-card">
              <div class="flow-num">①</div>
              <div class="card-title">编写提示词</div>
              <div class="text-dim" style="font-size:12.5px">
                角色设定 + 方法论 + 结构化输出要求 + <span class="mono" v-pre>{{变量占位符}}</span>，四件齐备易复用
              </div>
              <div class="flow-stat text-faint">草稿可随时编辑，提交前不进公共库</div>
            </div>
            <div class="flow-arrow" aria-hidden="true">→</div>
            <div class="card flow-card">
              <div class="flow-num">②</div>
              <div class="card-title">提交投稿 <span class="tag tag-orange">待评审 {{ mineStats.pending }}</span></div>
              <div class="text-dim" style="font-size:12.5px">
                点击「投稿提示词」进入待评审队列；可在下方表格编辑、撤回或重新提交
              </div>
              <div class="flow-stat text-faint">演示环境：登录用户可直接通过/驳回</div>
            </div>
            <div class="flow-arrow" aria-hidden="true">→</div>
            <div class="card flow-card">
              <div class="flow-num">③</div>
              <div class="card-title">入库共享 <span class="tag tag-green">已发布 {{ mineStats.published }}</span></div>
              <div class="text-dim" style="font-size:12.5px">
                审核通过后进入「提示词列表」公共库，按热度排序供全员一键复制
              </div>
              <div class="flow-stat text-faint">累计投稿 {{ mineStats.total }} · 驳回 {{ mineStats.rejected }}</div>
            </div>
          </div>

          <div class="flex mt-16" style="justify-content:space-between">
            <div class="flex">
              <button class="btn btn-primary" type="button" @click="openSubmit">＋ 投稿提示词</button>
              <button class="btn" type="button" @click="loadMine">刷新</button>
            </div>
            <div class="flex">
              <button
                v-for="f in [
                  { v: '', label: '全部' },
                  { v: '待评审', label: '待评审' },
                  { v: '已发布', label: '已发布' },
                  { v: '已驳回', label: '已驳回' },
                ]"
                :key="f.v"
                class="btn btn-sm"
                :class="{ 'btn-primary': subFilter === f.v, 'btn-ghost': subFilter !== f.v }"
                type="button"
                @click="subFilter = f.v"
              >{{ f.label }}</button>
            </div>
          </div>

          <div v-if="mineLoading && !mine.length" class="card mt-16">
            <div class="empty"><span class="spinner"></span><div class="e-text mt-8">加载中…</div></div>
          </div>

          <div v-else-if="!mineFiltered.length" class="card mt-16">
            <div class="empty">
              <div class="e-icon">📮</div>
              <div class="e-text">
                {{ subFilter ? `没有「${subFilter}」的投稿` : '还没有投稿 —— 点击上方按钮提交你的第一个提示词' }}
              </div>
              <button v-if="!subFilter" class="btn btn-sm btn-primary mt-8" type="button" @click="openSubmit">＋ 投稿提示词</button>
            </div>
          </div>

          <div v-else class="table-wrap mt-16">
            <table class="table">
              <thead>
                <tr>
                  <th style="text-align:left">标题</th>
                  <th>分类</th>
                  <th>状态</th>
                  <th>热度</th>
                  <th>更新</th>
                  <th style="text-align:left">说明 / 驳回原因</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="p in mineFiltered" :key="p.id">
                  <td style="text-align:left">
                    <div class="cell-main">{{ p.title }}</div>
                    <div class="cell-sub">{{ p.tags.join(' · ') || '—' }}</div>
                  </td>
                  <td><span class="tag tag-blue">{{ p.cat }}</span></td>
                  <td><span class="tag" :class="STATUS_TAG[p.status]">{{ p.status }}</span></td>
                  <td>🔥 {{ p.uses }} · ⭐ {{ p.stars }}</td>
                  <td>{{ p.updated }}</td>
                  <td style="text-align:left; max-width:220px">
                    <div class="cell-sub" style="white-space:normal; word-break:break-word">
                      <template v-if="p.status === '已驳回' && p.reject_reason">
                        <span class="text-red">驳回：</span>{{ p.reject_reason }}
                      </template>
                      <template v-else-if="p.note">{{ p.note }}</template>
                      <template v-else>—</template>
                    </div>
                  </td>
                  <td>
                    <div class="row-actions" style="opacity:1">
                      <button class="btn btn-sm btn-ghost" type="button" @click="preview(p)">查看</button>
                      <button class="btn btn-sm btn-ghost" type="button" @click="openEdit(p)">编辑</button>
                      <button
                        v-if="p.status === '待评审'"
                        class="btn btn-sm btn-success"
                        type="button"
                        title="演示：审核通过"
                        @click="setStatus(p, 'approve')"
                      >通过</button>
                      <button
                        v-if="p.status === '待评审'"
                        class="btn btn-sm btn-danger"
                        type="button"
                        @click="askReject(p)"
                      >驳回</button>
                      <button
                        v-if="p.status === '已驳回' || p.status === '草稿'"
                        class="btn btn-sm btn-primary"
                        type="button"
                        @click="setStatus(p, 'review')"
                      >重新提交</button>
                      <button
                        v-if="p.status === '已发布'"
                        class="btn btn-sm btn-ghost"
                        type="button"
                        title="撤回公共库，重新走评审"
                        @click="setStatus(p, 'review')"
                      >撤回</button>
                      <button class="btn btn-sm btn-danger" type="button" @click="askDelete(p)">删除</button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- 新建 / 编辑 / 投稿 弹窗（共用） -->
    <div class="modal-mask" :class="{ open: showForm }" @click.self="closeForm">
      <div class="modal">
        <div class="modal-head">
          <h3>{{ formTitleText() }}</h3>
          <button class="modal-close" type="button" @click="closeForm">✕</button>
        </div>
        <div class="modal-body">
          <div class="field">
            <label>标题 <span class="text-red">*</span></label>
            <input v-model="formTitle" class="input" placeholder="如：接口断言设计专家">
          </div>
          <div class="field">
            <label>分类 <span class="text-red">*</span></label>
            <select v-model="formCat" class="select">
              <option v-for="c in CATS" :key="c" :value="c">{{ c }}</option>
            </select>
          </div>
          <div class="field">
            <label>标签（逗号分隔，选填）</label>
            <input v-model="formTags" class="input" placeholder="如：断言, API">
          </div>
          <div class="field">
            <label>提示词内容 <span class="text-red">*</span></label>
            <textarea v-model="formContent" class="textarea mono" rows="6" placeholder="粘贴完整提示词模板…"></textarea>
          </div>
          <div class="field">
            <label>适用说明（选填）</label>
            <input v-model="formNote" class="input" placeholder="如：适用于 Cursor / Claude 等编码 Agent">
          </div>
          <div v-if="formMode === 'submit'" class="banner banner-info">
            投稿后状态为「待评审」，通过后进入公共库；可在「投稿管理」查看进度。
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn btn-ghost" type="button" @click="closeForm">取消</button>
          <button class="btn btn-primary" type="button" :disabled="formBusy" @click="saveForm">
            <span v-if="formBusy" class="spinner"></span>
            {{ formOkText() }}
          </button>
        </div>
      </div>
    </div>

    <!-- 删除确认 -->
    <div class="modal-mask" :class="{ open: showDel }" @click.self="closeDel">
      <div class="modal modal-sm">
        <div class="modal-head">
          <h3>确认删除</h3>
          <button class="modal-close" type="button" @click="closeDel">✕</button>
        </div>
        <div class="modal-body">
          <p>确定删除提示词「<strong>{{ delItem?.title }}</strong>」吗？</p>
          <p class="text-faint" style="font-size:12.5px; margin-top:8px">删除后不可恢复，相关收藏也会一并移除。</p>
        </div>
        <div class="modal-foot">
          <button class="btn btn-ghost" type="button" @click="closeDel">取消</button>
          <button class="btn btn-danger" type="button" :disabled="delBusy" @click="confirmDelete">
            <span v-if="delBusy" class="spinner"></span>
            确认删除
          </button>
        </div>
      </div>
    </div>

    <!-- 驳回原因 -->
    <div class="modal-mask" :class="{ open: showReject }" @click.self="closeReject">
      <div class="modal modal-sm">
        <div class="modal-head">
          <h3>驳回投稿</h3>
          <button class="modal-close" type="button" @click="closeReject">✕</button>
        </div>
        <div class="modal-body">
          <p style="margin-bottom:10px">「<strong>{{ rejectItem?.title }}</strong>」</p>
          <div class="field">
            <label>驳回原因</label>
            <textarea v-model="rejectReason" class="textarea" rows="3" placeholder="如：占位符不规范，请补充输出格式说明"></textarea>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn btn-ghost" type="button" @click="closeReject">取消</button>
          <button class="btn btn-danger" type="button" :disabled="rejectBusy" @click="confirmReject">
            <span v-if="rejectBusy" class="spinner"></span>
            确认驳回
          </button>
        </div>
      </div>
    </div>

    <!-- 查看弹窗 -->
    <div class="modal-mask" :class="{ open: showView }" @click.self="closeView">
      <div class="modal modal-lg">
        <div class="modal-head">
          <h3>{{ viewItem?.title || '' }}</h3>
          <button class="modal-close" type="button" @click="closeView">✕</button>
        </div>
        <div class="modal-body">
          <div v-if="viewItem" class="flex mb-16" style="flex-wrap:wrap">
            <span class="tag tag-blue">{{ viewItem.cat }}</span>
            <span v-if="viewItem.status && viewItem.status !== '已发布'" class="tag" :class="STATUS_TAG[viewItem.status]">{{ viewItem.status }}</span>
            <span class="tag">🔥 {{ viewItem.uses }}</span>
            <span class="tag">⭐ {{ viewItem.stars }}</span>
            <span class="tag">{{ viewItem.updated }}</span>
            <span v-for="t in viewItem.tags" :key="t" class="tag">{{ t }}</span>
          </div>
          <div v-if="viewItem?.note" class="banner banner-info mb-16">{{ viewItem.note }}</div>
          <div v-if="viewItem" class="code-block" style="white-space:pre-wrap">{{ viewItem.content }}</div>
        </div>
        <div class="modal-foot">
          <button class="btn btn-ghost" type="button" @click="copyView">📋 复制全文</button>
          <button class="btn btn-primary" type="button" @click="closeView">关闭</button>
        </div>
      </div>
    </div>
  </div><!-- /.prompts-view -->
</template>
