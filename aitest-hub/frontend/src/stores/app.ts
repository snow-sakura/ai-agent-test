import { defineStore } from 'pinia'
import { ref } from 'vue'

/** 全局 UI 状态：工具台分组 tab、提示词库 tab、侧栏折叠等 */
export type HubTabKey = 'manage' | 'exec' | 'ai' | 'plat'
export type PromptsTabKey = 'all' | 'favs' | 'submit'

export const useApp = defineStore('app', () => {
  const hubTab = ref<HubTabKey>('manage')
  const sidebarCollapsed = ref(false)
  /** /prompts 主区 tab（与 WorkspaceLayout 注入侧栏双向同步） */
  const promptsTab = ref<PromptsTabKey>('all')

  function setHubTab(tab: HubTabKey) {
    hubTab.value = tab
  }

  function setPromptsTab(tab: PromptsTabKey) {
    promptsTab.value = tab
  }

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  return {
    hubTab,
    sidebarCollapsed,
    promptsTab,
    setHubTab,
    setPromptsTab,
    toggleSidebar,
  }
})
