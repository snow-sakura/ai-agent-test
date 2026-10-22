<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import StatCard from '@/components/ui/StatCard.vue'
import { uiToast } from '@/composables/ui'
import { T } from '@/data/root-texts'
import http from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-token-usage.html + 后端 token_usage） ---------- */
interface TuPrice {
  in: number
  out: number
  hit: number
}
interface TuRow {
  id: string
  time: string
  module: string
  model: string
  content: string
  input: number
  output: number
  hit: number
  dur: number
  logId: string
  cost: number
  price: TuPrice
}
interface TuStats {
  totalCost: number
  totalIn: number
  totalOut: number
  totalHit: number
  requests: number
  saved: number
}

const MODULE_OPTS = [
  '用例生成',
  'AI问答',
  'AI报告',
  '根因分析',
  '技能中心',
  '技能库',
  'Agent中心',
  '需求解析',
  '数据工厂',
  '缺陷查重',
  '性能分析',
  '安全测试',
  '接口测试',
  '渗透测试',
  '知识库',
  '提示词',
  '去AI味',
  '工作流',
  'UI自动化',
  'APP自动化',
  '文档编辑',
  'JMeter助手',
  '配置中心',
]
const MODEL_OPTS = [
  'DeepSeek-V4-Flash',
  'DeepSeek-V3',
  '通义千问-Max',
  '硅基流动 · GLM-4',
]
// 默认最近 7 天（相对当前日期，避免硬编码过期区间）
const _today = new Date()
const _weekAgo = new Date(_today.getTime() - 7 * 24 * 3600 * 1000)
const DEFAULT_START = _weekAgo.toISOString().slice(0, 10)
const DEFAULT_END = _today.toISOString().slice(0, 10)

const rows = ref<TuRow[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const stats = ref<TuStats | null>(null)

const kw = ref('')
const moduleF = ref('')
const modelF = ref('')
const startD = ref(DEFAULT_START)
const endD = ref(DEFAULT_END)

const pages = computed(() => Math.max(1, Math.ceil(total.value / size.value)))
const nums = computed(() => {
  const start = Math.max(1, Math.min(pages.value - 4, page.value - 2))
  return Array.from({ length: Math.min(5, pages.value) }, (_, i) => start + i)
})

function fmt(n: number) {
  return Number(n || 0).toLocaleString('zh-CN')
}
function money(v: number) {
  return '¥' + Number(v || 0).toFixed(4)
}
function fmtDur(sec: number) {
  const s = Number(sec || 0)
  if (s < 60) return s + 's'
  const m = Math.floor(s / 60)
  const r = s % 60
  return m + 'm' + String(r).padStart(2, '0') + 's'
}

async function loadList() {
  const { data } = await http.get<{ items: TuRow[]; total: number; page: number; size: number }>(
    '/token-usage',
    {
      params: {
        q: kw.value.trim(),
        module: moduleF.value,
        model: modelF.value,
        start: startD.value,
        end: endD.value,
        page: page.value,
        size: size.value,
      },
    },
  )
  rows.value = data.items || []
  total.value = data.total || 0
  const ps = Math.max(1, Math.ceil(total.value / size.value))
  if (page.value > ps) {
    page.value = ps
    await loadList()
  }
}

async function loadStats() {
  const { data } = await http.get<TuStats>('/token-usage/stats', {
    params: { start: startD.value, end: endD.value },
  })
  stats.value = data
}

async function reload(resetPage = false) {
  if (resetPage) page.value = 1
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
  moduleF.value = ''
  modelF.value = ''
  startD.value = DEFAULT_START
  endD.value = DEFAULT_END
  void reload(true)
  uiToast('筛选已重置', 'info')
}

function goto(p: number) {
  page.value = Math.min(pages.value, Math.max(1, p))
  void loadList()
}

/* ---------- 详情弹窗 ---------- */
const detail = ref<TuRow | null>(null)
const detailOpen = ref(false)

function openDetail(r: TuRow) {
  detail.value = r
  detailOpen.value = true
}

/* ---------- 导出 CSV ---------- */
async function exportCsv() {
  const all: TuRow[] = []
  let p = 1
  let ps = 1
  try {
    do {
      const { data } = await http.get<{ items: TuRow[]; total: number }>('/token-usage', {
        params: {
          q: kw.value.trim(),
          module: moduleF.value,
          model: modelF.value,
          start: startD.value,
          end: endD.value,
          page: p,
          size: 100,
        },
      })
      all.push(...(data.items || []))
      total.value = data.total || all.length
      ps = Math.max(1, Math.ceil((data.total || 0) / 100))
      p++
    } while (p <= ps && all.length < 5000)
  } catch {
    /* 拦截器已 toast */
    return
  }
  if (!all.length) {
    uiToast('当前筛选无数据可导出', 'warn')
    return
  }
  const head = ['记录 ID', '时间', '来源模块', '模型', '调用内容', '输入', '输出', '命中', '费用']
  const esc = (v: string) => '"' + String(v ?? '').replace(/"/g, '""') + '"'
  const lines = [
    head.map(esc).join(','),
    ...all.map((r) =>
      [r.id, r.time, r.module, r.model, r.content, r.input, r.output, r.hit, Number(r.cost || 0).toFixed(4)]
        .map((v) => esc(String(v)))
        .join(','),
    ),
  ]
  const blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'tokens-usage.csv'
  a.click()
  URL.revokeObjectURL(a.href)
  uiToast(`已导出 ${all.length} 条消费记录（tokens-usage.csv）`, 'success')
  void reload(false)
}

onMounted(() => {
  void reload().catch(() => undefined)
})
</script>

<template>
  <ModuleShell slug="tool-token-usage">
    <template #actions>
      <RouterLink class="btn btn-ghost" to="/t/tool-config-center?tab=ai">⚙️ 模型与额度</RouterLink>
      <RouterLink class="btn btn-ghost" to="/t/tool-log-center">📜 日志中心</RouterLink>
      <button class="btn btn-primary" @click="exportCsv">⬇️ 导出对账 CSV</button>
    </template>

    <template #default>
      <div class="banner banner-info">
        ℹ️ 计量口径：命中（RAG / 缓存 / 前缀复用）部分按 2 折计费；费用 = 输入×单价 + 输出×单价 +
        命中×单价的 20%。单价在<RouterLink to="/t/tool-config-center?tab=ai">配置中心</RouterLink>按模型维护，数据与<RouterLink
          to="/t/tool-log-center"
        >日志中心</RouterLink>的 AI 调用记录一一对应。
      </div>

      <div class="grid grid-4 mb-16">
        <StatCard
          label="本月总消费"
          :value="'¥' + (stats?.totalCost ?? 0).toFixed(2)"
          :sub="(stats?.requests ?? 0) + ' 次调用'"
        />
        <StatCard
          label="输入 Tokens"
          :value="fmt(stats?.totalIn ?? 0)"
          sub="单价最低成本项"
          color="var(--blue)"
        />
        <StatCard
          label="输出 Tokens"
          :value="fmt(stats?.totalOut ?? 0)"
          sub="输出单价通常为输入 2~4 倍"
          color="var(--purple)"
        />
        <StatCard
          label="命中 Tokens"
          :value="fmt(stats?.totalHit ?? 0)"
          :sub="'⬇ 已为你节省 ¥' + (stats?.saved ?? 0).toFixed(2)"
          color="var(--green)"
        />
      </div>

      <div class="filter-bar">
        <input v-model="kw" class="input search" placeholder="🔍 搜索调用内容 / 记录 ID" @input="onKw" />
        <select v-model="moduleF" class="select" @change="reload(true)">
          <option value="">全部来源模块</option>
          <option v-for="m in MODULE_OPTS" :key="m" :value="m">{{ m }}</option>
        </select>
        <select v-model="modelF" class="select" @change="reload(true)">
          <option value="">全部模型</option>
          <option v-for="m in MODEL_OPTS" :key="m" :value="m">{{ m }}</option>
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
              <th>记录 ID</th>
              <th>时间</th>
              <th>来源模块</th>
              <th>模型</th>
              <th>调用内容</th>
              <th>输入</th>
              <th>输出</th>
              <th>命中</th>
              <th>费用</th>
              <th style="width: 70px">详情</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!rows.length">
              <td colspan="10">
                <div class="empty">
                  <div class="e-icon">🪙</div>
                  <div class="e-text">无匹配消费记录</div>
                </div>
              </td>
            </tr>
            <tr v-for="r in rows" :key="r.id">
              <td class="mono">{{ r.id }}</td>
              <td class="mono" style="font-size: 12px; white-space: nowrap">{{ r.time }}</td>
              <td><span class="tag tag-blue">{{ r.module }}</span></td>
              <td class="cell-sub" style="font-size: 12px">{{ r.model }}</td>
              <td style="max-width: 240px">
                <div class="cell-main" style="font-size: 12.5px; white-space: normal">{{ r.content }}</div>
              </td>
              <td class="mono" style="color: var(--blue)">{{ fmt(r.input) }}</td>
              <td class="mono" style="color: var(--purple)">{{ fmt(r.output) }}</td>
              <td class="mono" style="color: var(--green)">{{ fmt(r.hit) }}</td>
              <td class="mono" style="font-weight: 700">{{ money(r.cost) }}</td>
              <td>
                <div class="row-actions" style="opacity: 1">
                  <button class="btn btn-sm btn-ghost" @click="openDetail(r)">详情</button>
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
  </ModuleShell>

  <!-- 消费详情弹窗 -->
  <div class="modal-mask" :class="{ open: detailOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>{{ detail ? '消费详情 · ' + detail.id : '消费详情' }}</h3>
        <button class="modal-close" @click="detailOpen = false">✕</button>
      </div>
      <div v-if="detail" class="modal-body">
        <div class="mb-16" style="display: flex; gap: 8px; flex-wrap: wrap">
          <span class="tag tag-blue">{{ detail.module }}</span>
          <span class="tag">🧠 {{ detail.model }}</span>
          <span class="tag mono" style="font-size: 11px">{{ detail.time }}</span>
          <span class="tag">⏱ {{ fmtDur(detail.dur) }}</span>
        </div>
        <div class="field">
          <label>调用内容</label>
          <div class="code-block" style="white-space: normal; max-height: 120px; overflow-y: auto">
            {{ detail.content }}
          </div>
        </div>
        <div class="table-wrap mt-16" style="border: none">
          <table class="table">
            <thead>
              <tr>
                <th>计量项</th>
                <th>Tokens</th>
                <th>单价（¥/千 Token）</th>
                <th>计费规则</th>
                <th>费用</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>输入 Tokens</td>
                <td class="mono">{{ fmt(detail.input) }}</td>
                <td class="mono">{{ (detail.price?.in ?? 0).toFixed(4) }}</td>
                <td class="cell-sub">全价</td>
                <td class="mono">{{ money((detail.input / 1000) * (detail.price?.in ?? 0)) }}</td>
              </tr>
              <tr>
                <td>输出 Tokens</td>
                <td class="mono">{{ fmt(detail.output) }}</td>
                <td class="mono">{{ (detail.price?.out ?? 0).toFixed(4) }}</td>
                <td class="cell-sub">全价</td>
                <td class="mono">{{ money((detail.output / 1000) * (detail.price?.out ?? 0)) }}</td>
              </tr>
              <tr>
                <td>命中 Tokens</td>
                <td class="mono">{{ fmt(detail.hit) }}</td>
                <td class="mono">{{ (detail.price?.hit ?? 0).toFixed(4) }}</td>
                <td class="cell-sub">RAG/缓存 2 折</td>
                <td class="mono">{{ money((detail.hit / 1000) * (detail.price?.hit ?? 0) * 0.2) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div
          class="flex-between mt-16"
          style="padding: 10px 14px; background: var(--primary-soft); border-radius: 8px"
        >
          <span style="font-weight: 700">合计费用</span>
          <b class="mono" style="font-size: 16px; color: var(--primary)">{{ money(detail.cost) }}</b>
        </div>
      </div>
      <div class="modal-foot">
        <RouterLink class="btn btn-ghost" to="/t/tool-log-center">📜 查看对应日志</RouterLink>
        <button class="btn btn-primary" @click="detailOpen = false">关闭</button>
      </div>
    </div>
  </div>
</template>
