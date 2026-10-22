<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import StatCard from '@/components/ui/StatCard.vue'
import { uiToast } from '@/composables/ui'
import { T } from '@/data/root-texts'
import http from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-log-center.html + logs） ---------- */
interface LogRow {
  id: string
  time: string
  type: string
  mod: string
  content: string
  user: string
  ip: string
  dur: string | number
  status: string
  body: string
}
interface LogStats {
  today: number
  fail: number
  total: number
  weekUsers: number
  byType: { type: string; count: number }[]
  byModule: { module: string; count: number }[]
}

const T_CLS: Record<string, string> = {
  登录: 'tag-blue',
  新增: 'tag-green',
  修改: 'tag-orange',
  删除: 'tag-red',
  执行: 'tag-purple',
  'AI 调用': 'tag-red',
  导出: 'tag',
}
const TYPE_OPTS = ['登录', '新增', '修改', '删除', '执行', 'AI 调用', '导出']
const MODULE_OPTS = [
  '需求解析',
  'AI问答',
  '根因分析',
  '安全测试',
  '去AI味',
  '配置中心',
  '渗透测试',
  '接口测试',
  '性能分析',
  '数据工厂',
  '技能库',
  'UI自动化',
  'AI报告',
  'APP自动化',
  '缺陷查重',
  '用例生成',
  '技能中心',
  '系统',
  '知识库',
  '用例管理',
  'Agent中心',
  '缺陷管理',
  '文档编辑',
  'JMeter助手',
]
const USER_OPTS = ['wxh', 'admin', 'li-qa', 'system']
// 默认最近 7 天（相对当前日期，避免硬编码过期区间）
const _today = new Date()
const _weekAgo = new Date(_today.getTime() - 7 * 24 * 3600 * 1000)
const DEFAULT_START = _weekAgo.toISOString().slice(0, 10)
const DEFAULT_END = _today.toISOString().slice(0, 10)

const stats = ref<LogStats | null>(null)
const rows = ref<LogRow[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)

const kw = ref('')
const typeF = ref('')
const moduleF = ref('')
const userF = ref('')
const startD = ref(DEFAULT_START)
const endD = ref(DEFAULT_END)

const pages = computed(() => Math.max(1, Math.ceil(total.value / size.value)))
const nums = computed(() => {
  const start = Math.max(1, Math.min(pages.value - 4, page.value - 2))
  return Array.from({ length: Math.min(5, pages.value) }, (_, i) => start + i)
})

const aiCalls = computed(
  () => stats.value?.byType.find((x) => x.type === 'AI 调用')?.count ?? 0,
)

function fmtDur(d: string | number): string {
  const n = Number(d)
  if (Number.isNaN(n)) return String(d ?? '')
  if (n < 60) return n + 's'
  const m = Math.floor(n / 60)
  const s = n % 60
  return m + 'm' + String(s).padStart(2, '0') + 's'
}

async function loadList() {
  const { data } = await http.get<{ items: LogRow[]; total: number }>('/logs', {
    params: {
      q: kw.value.trim(),
      type: typeF.value,
      module: moduleF.value,
      user: userF.value,
      start: startD.value,
      end: endD.value,
      page: page.value,
      size: size.value,
    },
  })
  rows.value = data.items || []
  total.value = data.total || 0
  const ps = Math.max(1, Math.ceil(total.value / size.value))
  if (page.value > ps) {
    page.value = ps
    await loadList()
  }
}

async function loadStats() {
  const { data } = await http.get<LogStats>('/logs/stats')
  stats.value = data
}

async function reload(reset = false) {
  if (reset) page.value = 1
  await Promise.all([loadList(), loadStats()])
}

let kwTimer: ReturnType<typeof setTimeout> | undefined
function onKw() {
  clearTimeout(kwTimer)
  kwTimer = setTimeout(() => {
    void reload(true)
  }, 200)
}

function resetFilter() {
  kw.value = ''
  typeF.value = ''
  moduleF.value = ''
  userF.value = ''
  startD.value = DEFAULT_START
  endD.value = DEFAULT_END
  void reload(true)
  uiToast('筛选已重置', 'info')
}

function goto(p: number) {
  page.value = Math.min(pages.value, Math.max(1, p))
  void loadList()
}

async function exportCsv() {
  const all: LogRow[] = []
  let p = 1
  let ps = 1
  try {
    do {
      const { data } = await http.get<{ items: LogRow[]; total: number }>('/logs', {
        params: {
          q: kw.value.trim(),
          type: typeF.value,
          module: moduleF.value,
          user: userF.value,
          start: startD.value,
          end: endD.value,
          page: p,
          size: 100,
        },
      })
      all.push(...(data.items || []))
      ps = Math.max(1, Math.ceil((data.total || 0) / 100))
      p++
    } while (p <= ps && all.length < 5000)
  } catch {
    return
  }
  if (!all.length) {
    uiToast('当前筛选无数据可导出', 'warn')
    return
  }
  const head = ['时间', '操作类型', '操作模块', '操作内容', '操作人', '请求 IP', '耗时', '状态']
  const esc = (v: string) => '"' + String(v ?? '').replace(/"/g, '""') + '"'
  const lines = [
    head.map(esc).join(','),
    ...all.map((r) =>
      [r.time, r.type, r.mod, r.content, r.user, r.ip, fmtDur(r.dur), r.status]
        .map((v) => esc(String(v)))
        .join(','),
    ),
  ]
  const blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'operation-logs.csv'
  a.click()
  URL.revokeObjectURL(a.href)
  uiToast('已导出 ' + all.length + ' 条操作日志为 CSV', 'success')
}

/* ---------- 详情 ---------- */
const detail = ref<LogRow | null>(null)
const detailOpen = ref(false)
function openDetail(r: LogRow) {
  detail.value = r
  detailOpen.value = true
}

onMounted(() => {
  void reload().catch(() => undefined)
})
</script>

<template>
  <ModuleShell slug="tool-log-center">
    <template #actions>
      <RouterLink class="btn btn-ghost" to="/t/tool-scheduler?tab=logs">⏰ 定时任务日志</RouterLink>
      <button class="btn btn-primary" @click="exportCsv">⬇️ 导出 CSV</button>
    </template>

    <template #default="{ tab }">
      <div class="banner banner-info">
        ℹ️ 对应平台 SystemLog 模块：记录全站关键操作（登录、AI 调用、配置变更、数据增删改），操作日志不可修改、仅审计员可导出；与定时任务执行日志分表存储。
      </div>

      <!-- ============ 统计概览 ============ -->
      <template v-if="tab === 'stats'">
        <div class="banner">数据总览与快捷入口；详细数据请切到「📜 操作日志」查看（支持筛选与分页）。</div>
        <div class="grid grid-4 mb-16">
          <StatCard label="今日操作" :value="stats?.today ?? 0" />
          <StatCard label="AI 调用记录" :value="aiCalls" color="var(--red)" />
          <StatCard label="失败 / 异常" :value="stats?.fail ?? 0" color="var(--orange)" />
          <StatCard label="本周操作人" :value="stats?.weekUsers ?? 0" color="var(--blue)" />
        </div>
      </template>

      <!-- ============ 操作日志 ============ -->
      <template v-if="tab === 'list'">
        <div class="filter-bar">
          <input v-model="kw" class="input search" placeholder="🔍 搜索操作内容" @input="onKw" />
          <select v-model="typeF" class="select" @change="reload(true)">
            <option value="">操作类型</option>
            <option v-for="t in TYPE_OPTS" :key="t" :value="t">{{ t }}</option>
          </select>
          <select v-model="moduleF" class="select" @change="reload(true)">
            <option value="">操作模块</option>
            <option v-for="m in MODULE_OPTS" :key="m" :value="m">{{ m }}</option>
          </select>
          <select v-model="userF" class="select" @change="reload(true)">
            <option value="">操作人</option>
            <option v-for="u in USER_OPTS" :key="u" :value="u">{{ u }}</option>
          </select>
          <input v-model="startD" class="input" type="date" style="width: 145px" @change="reload(true)" />
          <span class="text-faint">至</span>
          <input v-model="endD" class="input" type="date" style="width: 145px" @change="reload(true)" />
          <button class="btn btn-ghost btn-sm" @click="resetFilter">重置</button>
        </div>

        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>时间</th>
                <th>操作类型</th>
                <th>操作模块</th>
                <th>操作内容</th>
                <th>操作人</th>
                <th>请求 IP</th>
                <th>耗时</th>
                <th>状态</th>
                <th style="width: 80px">详情</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!rows.length">
                <td colspan="9">
                  <div class="empty">
                    <div class="e-icon">📜</div>
                    <div class="e-text">无匹配日志</div>
                  </div>
                </td>
              </tr>
              <tr v-for="l in rows" :key="l.id">
                <td class="mono" style="font-size: 12px; white-space: nowrap">{{ l.time }}</td>
                <td><span class="tag" :class="T_CLS[l.type] || 'tag'">{{ l.type }}</span></td>
                <td class="cell-sub" style="font-size: 12.5px">{{ l.mod }}</td>
                <td style="max-width: 280px">
                  <div class="cell-main" style="font-size: 12.5px; white-space: normal">{{ l.content }}</div>
                </td>
                <td>{{ l.user }}</td>
                <td class="mono" style="font-size: 12px">{{ l.ip }}</td>
                <td class="mono">{{ fmtDur(l.dur) }}</td>
                <td>
                  <span v-if="l.status === '成功'" class="tag tag-green">成功</span>
                  <span v-else class="tag tag-red">失败</span>
                </td>
                <td>
                  <div class="row-actions" style="opacity: 1">
                    <button class="btn btn-sm btn-ghost" @click="openDetail(l)">详情</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="total > 0" class="pagination">
          <span class="page-info">共 {{ total }} 条 · 第 {{ page }}/{{ pages }} 页</span>
          <label class="pg-size">
            每页
            <select
              v-model.number="size"
              class="pg-size-sel"
              @change="
                page = 1;
                loadList()
              "
            >
              <option v-for="n in [10, 20, 50, 100]" :key="n" :value="n">{{ n }}</option>
            </select>
            条
          </label>
          <button class="page-btn txt" :disabled="page <= 1" @click="goto(1)">{{ T.first }}</button>
          <button class="page-btn txt" :disabled="page <= 1" @click="goto(page - 1)">{{ T.prev }}</button>
          <button
            v-for="n in nums"
            :key="n"
            :class="'page-btn' + (n === page ? ' active' : '')"
            @click="goto(n)"
          >{{ n }}</button>
          <button class="page-btn txt" :disabled="page >= pages" @click="goto(page + 1)">{{ T.next }}</button>
          <button class="page-btn txt" :disabled="page >= pages" @click="goto(pages)">{{ T.last }}</button>
        </div>
      </template>
    </template>
  </ModuleShell>

  <!-- 日志详情弹窗 -->
  <div class="modal-mask" :class="{ open: detailOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>操作详情</h3>
        <button class="modal-close" @click="detailOpen = false">✕</button>
      </div>
      <div v-if="detail" class="modal-body">
        <div class="mb-16">
          <span class="tag tag-blue">{{ detail.type }}</span>
          <span class="tag">{{ detail.mod }}</span>
          <span class="tag">{{ detail.user }}</span>
          <span class="tag mono" style="font-size: 11px">{{ detail.time }}</span>
          <span class="tag mono" style="font-size: 11px">IP {{ detail.ip }}</span>
          <span class="tag">⏱ {{ fmtDur(detail.dur) }}</span>
          <span v-if="detail.status === '成功'" class="tag tag-green">成功</span>
          <span v-else class="tag tag-red">失败</span>
          <div class="text-dim mt-8" style="font-size: 13px">
            {{ detail.content }}（{{ detail.id }}）
          </div>
        </div>
        <div class="field">
          <label>请求 / 响应摘要</label>
          <div class="code-block" style="max-height: 260px; overflow-y: auto">{{ detail.body }}</div>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-primary" @click="detailOpen = false">关闭</button>
      </div>
    </div>
  </div>
</template>
