<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { TOOL_CATALOG } from '@/data/catalog'
import { T } from '@/data/root-texts'
import AppTopBar from '@/components/shell/AppTopBar.vue'

/* 工具模块壳：顶栏 + 模块侧栏 + 面包屑/页头 + 内容（tab 由 route query 驱动）
   由 ModuleShell 薄适配层复用，保持 27 工具页 API 不变 */
const props = defineProps<{ slug: string }>()

const route = useRoute()
const router = useRouter()

const def = computed(() => TOOL_CATALOG.find((d) => d.slug === props.slug))
const tabs = computed(() => def.value?.tabs ?? [])
const title = computed(() => def.value?.title ?? 'AITest Hub')
const sub = computed(() => def.value?.sub ?? '')
const icon = computed(() => def.value?.icon ?? String.fromCodePoint(0x1f9e9))

function resolveTab(q: string): string {
  const keys = tabs.value.map((t) => t.key)
  if (q && keys.includes(q)) return q
  return keys[0] || ''
}

const activeTab = ref(resolveTab(String(route.query.tab || '')))

watch(
  () => [route.query.tab, tabs.value] as const,
  () => {
    const next = resolveTab(String(route.query.tab || ''))
    if (next !== activeTab.value) activeTab.value = next
  },
  { immediate: true },
)

function clickTab(key: string) {
  activeTab.value = key
  void router.replace({ query: { ...route.query, tab: key } })
}

function tabIcon(label: string): string {
  const cp = label ? label.codePointAt(0) : undefined
  return cp ? String.fromCodePoint(cp) : ''
}
function tabText(label: string): string {
  return label ? label.slice(tabIcon(label).length).trim() : ''
}
</script>

<template>
  <div class="tool-layout">
    <AppTopBar />

    <div class="workspace" data-shell="workspace">
      <aside class="sidebar" data-shell="sidebar">
        <div class="mod-head">
          <RouterLink class="mod-back" to="/app">{{ T.back }}</RouterLink>
          <div class="mod-title"><span class="mt-ico">{{ icon }}</span>{{ title }}</div>
        </div>
        <nav class="side-nav">
          <a
            v-for="tb in tabs"
            :key="tb.key"
            href="#"
            :class="['side-item', { active: activeTab === tb.key }]"
            @click.prevent="clickTab(tb.key)"
          >
            <span class="si-ico">{{ tabIcon(tb.label) }}</span>
            <span class="si-txt">{{ tabText(tb.label) }}</span>
          </a>
          <a v-if="!tabs.length" class="side-item active">
            <span class="si-ico">🏠</span>
            <span class="si-txt">{{ T.overview }}</span>
          </a>
        </nav>
      </aside>

      <main class="main-area" data-shell="main">
        <div class="breadcrumb">
          <RouterLink to="/app">工具台</RouterLink> / {{ title }}
        </div>
        <div class="page-head">
          <div>
            <h1>{{ icon }} {{ title }}</h1>
            <div class="sub">{{ sub }}</div>
          </div>
          <div class="flex">
            <slot name="actions" />
          </div>
        </div>
        <slot :tab="activeTab" />
      </main>
    </div>
  </div>
</template>

<style scoped>
.tool-layout {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}
/* 与 workspace 壳一致：顶栏不缩，工作区吃剩余高度 */
.tool-layout > :deep(.topbar) {
  flex: 0 0 auto;
}
.tool-layout .workspace {
  flex: 1 1 0;
  min-height: 0;
  overflow: hidden;
}
</style>
