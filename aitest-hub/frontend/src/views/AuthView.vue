<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '@/api/http'
import { useAuth } from '@/stores/auth'
import { uiToast } from '@/composables/ui'

/* 登录页：左侧品牌区 + 右侧表单（对照 UI/auth.html） */
const route = useRoute()
const router = useRouter()
const auth = useAuth()

// 演示账号由服务端下发（GET /api/config/demo-account），前端不内置任何账号口令；
// 服务端由 DEMO_ACCOUNT / DEMO_PASSWORD 环境变量控制，DEMO_ACCOUNT_PUBLIC=0 时接口返回 404。
const demoAccount = ref('')
const demoPassword = ref('')
const demoAvailable = ref(false)
const REMEMBER_KEY = 'aitesthub_remember'

const account = ref('')
const password = ref('')
const remember = ref(true)
const showPw = ref(false)
const loading = ref(false)
const errAccount = ref('')
const errPassword = ref('')

function setErrAccount(msg: string) {
  errAccount.value = msg
}
function setErrPassword(msg: string) {
  errPassword.value = msg
}
function clearErrAccount() {
  errAccount.value = ''
}
function clearErrPassword() {
  errPassword.value = ''
}

function maskPw(p: string): string {
  if (!p) return ''
  if (p.length <= 4) return '••••'
  return `${p.slice(0, 2)}******${p.slice(-2)}`
}

function fillDemo() {
  account.value = demoAccount.value
  password.value = demoPassword.value
  clearErrAccount()
  clearErrPassword()
  uiToast('已填充演示账号', 'info')
}

function togglePw() {
  showPw.value = !showPw.value
}

function onForgot() {
  uiToast('演示环境：请联系管理员重置密码', 'info')
}

async function onSubmit() {
  clearErrAccount()
  clearErrPassword()
  const acc = account.value.trim()
  const pw = password.value
  let ok = true
  // 后端按 username OR phone 匹配，这里同步放开：11 位手机号或 3-50 位用户名
  // （原实现只认手机号，导致 seed 的 admin 等无手机号账号无法从登录页进入）
  if (!/^1\d{10}$/.test(acc) && !/^[A-Za-z0-9_.-]{3,50}$/.test(acc)) {
    setErrAccount('请输入 11 位手机号或 3-50 位账号')
    ok = false
  }
  if (!pw) {
    setErrPassword('密码不能为空')
    ok = false
  }
  if (!ok) {
    uiToast('请检查表单填写', 'error')
    return
  }

  loading.value = true
  try {
    await auth.login(acc, pw)
    if (remember.value) localStorage.setItem(REMEMBER_KEY, acc)
    uiToast('登录成功，欢迎回来！', 'success')
    const back = String(route.query.redirect || '/app')
    setTimeout(() => {
      void router.push(back || '/app')
    }, 400)
  } catch {
    // http 拦截器已 toast；这里只标字段错误
    loading.value = false
    setErrPassword('账号或密码错误')
    return
  }
  loading.value = false
}

onMounted(async () => {
  const remembered = localStorage.getItem(REMEMBER_KEY)
  if (remembered) account.value = remembered
  try {
    const { data } = await http.get<{ account: string; password: string }>(
      '/config/demo-account',
    )
    demoAccount.value = data.account
    demoPassword.value = data.password
    demoAvailable.value = true
  } catch {
    demoAvailable.value = false // 服务端未开放演示账号：隐藏提示条
  }
})
</script>

<template>
  <div class="auth-wrap">
    <!-- 左侧品牌区 -->
    <div class="auth-left">
      <div class="auth-brandline">
        <RouterLink class="brand" to="/"><span class="logo">AT</span>AITest Hub</RouterLink>
      </div>
      <div style="max-width:420px; position:relative; z-index:1">
        <h1 style="font-size:30px; line-height:1.35">AI 驱动的<br>测试工程师在线工具箱</h1>
        <p class="text-dim mt-16" style="font-size:14.5px">可视化压测 · AI 用例 · 提示词库 · UI 自动化 · 工具箱，五大能力浏览器打开即用。</p>
        <div class="grid grid-2 mt-24" style="gap:10px">
          <div class="card" style="padding:12px 14px"><span class="tag tag-blue">🧪 压测编排</span></div>
          <div class="card" style="padding:12px 14px"><span class="tag tag-purple">🤖 AI 用例</span></div>
          <div class="card" style="padding:12px 14px"><span class="tag tag-green">📚 提示词库</span></div>
          <div class="card" style="padding:12px 14px"><span class="tag tag-orange">🖱️ UI 自动化</span></div>
        </div>
      </div>
    </div>

    <!-- 右侧登录表单 -->
    <div class="auth-panel">
      <div class="auth-card">
        <div class="tabs" style="margin-bottom:18px">
          <button class="tab active" type="button">登录</button>
          <RouterLink
            class="tab"
            :to="{ path: '/register', query: route.query }"
          >注册</RouterLink>
        </div>
        <h2>欢迎回来 👋</h2>
        <p class="sub">登录 AITest Hub，继续你的测试工作</p>

        <!-- 演示账号提示 -->
        <div v-if="demoAvailable" class="demo-cred">
          <span>🎭 演示账号：<span class="mono">{{ demoAccount }}</span> / <span class="mono">{{ maskPw(demoPassword) }}</span></span>
          <button class="btn btn-sm btn-ghost" type="button" @click="fillDemo">一键填充</button>
        </div>

        <form novalidate @submit.prevent="onSubmit">
          <div class="field" :class="{ 'has-err': !!errAccount }">
            <label for="account">手机号 / 账号</label>
            <input
              id="account"
              v-model="account"
              class="input"
              type="tel"
              placeholder="请输入手机号"
              maxlength="11"
              autocomplete="username"
              @input="clearErrAccount"
            >
            <div class="err-msg">{{ errAccount || '请输入 11 位手机号或 3-50 位账号' }}</div>
          </div>

          <div class="field" :class="{ 'has-err': !!errPassword }">
            <label for="password">密码</label>
            <div class="relative">
              <input
                id="password"
                v-model="password"
                class="input"
                :type="showPw ? 'text' : 'password'"
                placeholder="请输入密码"
                autocomplete="current-password"
                style="padding-right:44px"
                @input="clearErrPassword"
              >
              <button type="button" class="pw-toggle" @click="togglePw">{{ showPw ? '🙈' : '👁' }}</button>
            </div>
            <div class="err-msg">{{ errPassword || '密码不能为空' }}</div>
          </div>

          <div class="flex-between mb-16">
            <label class="checkbox"><input v-model="remember" type="checkbox"> 记住我</label>
            <a href="#" style="font-size:12.5px" @click.prevent="onForgot">忘记密码？</a>
          </div>

          <button class="btn btn-primary btn-lg" type="submit" style="width:100%" :disabled="loading">
            <span v-if="loading" class="spinner"></span>
            {{ loading ? '登录中…' : '登 录' }}
          </button>

          <p class="text-faint mt-16" style="font-size:12.5px; text-align:center">
            没有账号？<RouterLink to="/register">注册账号</RouterLink>
            · <RouterLink to="/">返回首页</RouterLink>
          </p>
        </form>
      </div>
    </div>
  </div>
</template>
