<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppTopBar from '@/components/shell/AppTopBar.vue'
import { useApp, type PromptsTabKey } from '@/stores/app'
import { T } from '@/data/root-texts'

/* 通用工作区：顶栏 + workspace（侧栏 + main 滚动区）
   对齐 UI/common.js buildSidebar：/prompts 空侧栏注入 mod-head + side-nav，并隐藏主区 tabs */
withDefaults(
  defineProps<{
    withSidebar?: boolean
    showBack?: boolean
  }>(),
  { withSidebar: true, showBack: false },
)

const route = useRoute()
const app = useApp()

const isPrompts = computed(() => route.path.startsWith('/prompts'))

/** 与 PromptsView TABS / 设计稿注入数据一致 */
const PROMPT_NAV: { key: PromptsTabKey; label: string }[] = [
  { key: 'all', label: '📚 提示词列表' },
  { key: 'favs', label: '⭐ 我的收藏' },
  { key: 'submit', label: '📮 投稿管理' },
]

function tabIcon(label: string): string {
  const cp = label ? label.codePointAt(0) : undefined
  return cp ? String.fromCodePoint(cp) : ''
}
function tabText(label: string): string {
  return label ? label.slice(tabIcon(label).length).trim() : ''
}

function clickNav(key: PromptsTabKey) {
  app.setPromptsTab(key)
}
</script>

<template>
  <div class="workspace-page">
    <AppTopBar :show-back="showBack" />
    <div class="workspace" data-shell="workspace">
      <aside v-if="withSidebar" class="sidebar" data-shell="sidebar">
        <!-- 注入侧栏（对照 common.js buildSidebar）：/prompts -->
        <template v-if="isPrompts">
          <div class="mod-head">
            <RouterLink class="mod-back" to="/app">{{ T.back }}</RouterLink>
            <div class="mod-title">
              <span class="mt-ico">🧩</span>提示词库
            </div>
          </div>
          <nav class="side-nav">
            <a
              v-for="item in PROMPT_NAV"
              :key="item.key"
              href="#"
              :class="['side-item', { active: app.promptsTab === item.key }]"
              @click.prevent="clickNav(item.key)"
            >
              <span class="si-ico">{{ tabIcon(item.label) }}</span>
              <span class="si-txt">{{ tabText(item.label) }}</span>
            </a>
          </nav>
        </template>
        <slot name="sidebar" />
      </aside>
      <main class="main-area" data-shell="main">
        <router-view v-slot="{ Component }">
          <component :is="Component" />
        </router-view>
        <slot />
      </main>
    </div>
  </div>
</template>

<style scoped>
/* 一屏锁定：页面本身不滚，超高内容只在 .main-area / .sidebar 内滚
   用 height + overflow:hidden 而非 min-height，避免内容把页面撑出二级滚动条、
   导致 100vh 算好的主区底部落在视口外（末行卡片被视口裁掉） */
.workspace-page {
  height: 100vh;
  height: 100dvh;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.workspace-page .workspace {
  /* basis:0 — 不以内容高度为基准，只吃顶栏之外的剩余空间；
     否则 flex-shrink 会先压扁顶栏 */
  flex: 1 1 0;
  min-height: 0;
  height: auto;
  overflow: hidden;
}
/* 设计稿：侧栏注入后隐藏主区横向 tabs */
.workspace-page .main-area :deep(.tabs) {
  display: none;
}
</style>
