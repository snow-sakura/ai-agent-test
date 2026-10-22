<script setup lang="ts">
import { computed } from 'vue'
import { useAuth } from '@/stores/auth'
import { uiToast } from '@/composables/ui'

/* 统一顶栏：对齐 UI/assets/common.js buildTopbar()
   brand +（可选返回卡片列表）+ 登录态操作 / 登录注册 CTA */
withDefaults(
  defineProps<{
    /** 未登录且无侧栏时，是否展示「卡片列表」返回入口 */
    showBack?: boolean
    /** 未登录时是否展示登录/注册按钮 */
    showAuthCtas?: boolean
  }>(),
  { showBack: false, showAuthCtas: false },
)

const auth = useAuth()

const isLogin = computed(() => auth.isLogin())
const initial = computed(() => (auth.user || 'W').slice(0, 1).toUpperCase())
const userName = computed(() => auth.user || 'wxh')
const roleLabel = '测试工程师'

function onSettings() {
  uiToast('演示环境：个人设置未开放', 'info')
}
</script>

<template>
  <header class="topbar" data-shell="topbar">
    <RouterLink class="brand" to="/">
      <span class="logo">AT</span>
      AITest Hub
    </RouterLink>

    <!-- 设计稿 common.js buildTopbar：顶栏只保留品牌与用户操作，模块导航由侧栏承担 -->

    <div class="topbar-right">
      <RouterLink
        v-if="showBack && !isLogin"
        class="btn btn-ghost btn-sm"
        to="/app"
      >🗂️ 卡片列表</RouterLink>

      <div v-if="isLogin" class="tb-actions">
        <RouterLink class="tb-act" to="/app"><span class="ta-ico">🗂️</span>卡片列表</RouterLink>
        <RouterLink class="tb-act" to="/"><span class="ta-ico">🌐</span>官网首页</RouterLink>
        <button class="tb-act" type="button" @click="onSettings">
          <span class="ta-ico">⚙️</span>个人设置
        </button>
        <button class="tb-act danger" type="button" @click="auth.logout()">
          <span class="ta-ico">🚪</span>退出登录
        </button>
      </div>

      <span v-if="isLogin" class="user-chip static">
        <span class="avatar">{{ initial }}</span>
        <span class="uc-name">{{ userName }} · {{ roleLabel }}</span>
      </span>

      <template v-else-if="showAuthCtas">
        <RouterLink class="btn btn-ghost btn-sm" to="/auth">登录</RouterLink>
        <RouterLink class="btn btn-primary btn-sm" to="/register">注册</RouterLink>
      </template>
    </div>
  </header>
</template>
