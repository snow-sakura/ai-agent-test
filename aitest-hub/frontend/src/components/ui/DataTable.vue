<script setup lang="ts" generic="T extends Record<string, any>">
import { computed, ref, watch } from 'vue'
import { T } from '@/data/root-texts'

/* Design table: centered cells, auto layout, one-screen paging (10/page). */
export interface Column {
  key: string
  label: string
  width?: string
}

const props = withDefaults(
  defineProps<{
    columns: Column[]
    rows: T[]
    pageSize?: number
    emptyText?: string
  }>(),
  { pageSize: 10, emptyText: undefined },
)

const page = ref(1)
const size = ref(props.pageSize)
watch(
  () => props.rows.length,
  () => {
    const ps = Math.max(1, Math.ceil(props.rows.length / size.value))
    if (page.value > ps) page.value = ps
  },
)
watch(size, () => (page.value = 1))

const pages = computed(() => Math.max(1, Math.ceil(props.rows.length / size.value)))
const paged = computed(() => props.rows.slice((page.value - 1) * size.value, page.value * size.value))

function setPage(p: number) {
  page.value = Math.min(pages.value, Math.max(1, p))
}
const MID = ' \u00b7 '
const nums = computed(() => {
  const start = Math.max(1, Math.min(pages.value - 4, page.value - 2))
  return Array.from({ length: Math.min(5, pages.value) }, (_, i) => start + i)
})
</script>

<template>
  <div class="table-wrap">
    <table class="table">
      <thead>
        <tr>
          <th v-for="c in columns" :key="c.key" :style="c.width ? { width: c.width } : {}">{{ c.label }}</th>
          <th v-if="$slots.actions" style="width:200px">{{ '\u64cd\u4f5c' }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="!paged.length">
          <td :colspan="columns.length + ($slots.actions ? 1 : 0)">
            <div class="empty"><div class="e-text">{{ emptyText || '\u6682\u65e0\u6570\u636e' }}</div></div>
          </td>
        </tr>
        <tr v-for="(row, i) in paged" :key="i">
          <td v-for="c in columns" :key="c.key">
            <slot :name="'cell-' + c.key" :row="row" :value="row[c.key]">{{ row[c.key] }}</slot>
          </td>
          <td v-if="$slots.actions">
            <div class="row-actions"><slot name="actions" :row="row" /></div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="pagination" v-if="rows.length > size || pages > 1 || rows.length > 0">
    <span class="page-info">{{ T.total }} {{ rows.length }} {{ T.items }}{{ MID }}{{ T.page }} {{ page }}/{{ pages }} {{ T.page }}</span>
    <label class="pg-size">{{ T.perPage }}
      <select class="pg-size-sel" v-model.number="size">
        <option v-for="n in [10, 20, 50, 100]" :key="n" :value="n">{{ n }}</option>
      </select>
    </label>
    <button class="page-btn txt" :disabled="page <= 1" @click="setPage(1)">{{ T.first }}</button>
    <button class="page-btn txt" :disabled="page <= 1" @click="setPage(page - 1)">{{ T.prev }}</button>
    <button
      v-for="n in nums"
      :key="n"
      :class="'page-btn' + (n === page ? ' active' : '')"
      @click="setPage(n)"
    >{{ n }}</button>
    <button class="page-btn txt" :disabled="page >= pages" @click="setPage(page + 1)">{{ T.next }}</button>
    <button class="page-btn txt" :disabled="page >= pages" @click="setPage(pages)">{{ T.last }}</button>
  </div>
</template>
