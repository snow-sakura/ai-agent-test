<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAuth } from '@/stores/auth'
import AppTopBar from '@/components/shell/AppTopBar.vue'

/* 门户壳：顶栏 + 路由内容（官网首页 / 工具台卡片页） */
const route = useRoute()
const auth = useAuth()

const showAuthCtas = computed(() => route.path === '/' && !auth.isLogin())
const showBack = computed(() => route.path === '/')
</script>

<template>
  <div class="portal-layout">
    <AppTopBar :show-auth-ctas="showAuthCtas" :show-back="showBack" />
    <router-view v-slot="{ Component }">
      <component :is="Component" />
    </router-view>
  </div>
</template>

<style scoped>
.portal-layout {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}
/* 顶栏禁止伸缩（与 .topbar flex:0 0 auto 一致，此处提高特异性防被 * 覆盖） */
.portal-layout > :deep(.topbar) {
  flex: 0 0 auto;
}
.portal-layout > :deep(*:not(.topbar)) {
  flex: 1 1 auto;
  min-width: 0;
}
</style>
