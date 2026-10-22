<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'
import { uiToast } from '@/composables/ui'

/* 注册页：左侧品牌区 + 右侧注册表单（对照 UI/register.html） */
const route = useRoute()
const router = useRouter()
const auth = useAuth()

const nick = ref('')
const phone = ref('')
const code = ref('')
const pass = ref('')
const pass2 = ref('')
const agree = ref(false)
const showPw = ref(false)
const loading = ref(false)

const errNick = ref('')
const errPhone = ref('')
const errCode = ref('')
const errPass = ref('')
const errPass2 = ref('')
const errAgree = ref('')

const countdown = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

const sendLabel = computed(() =>
  countdown.value > 0 ? `${countdown.value}s 后重发` : '获取验证码',
)

const pwScore = computed(() => {
  const v = pass.value
  let score = 0
  if (v.length >= 8) score++
  if (/[a-zA-Z]/.test(v) && /\d/.test(v)) score++
  if (/[^a-zA-Z0-9]/.test(v)) score++
  if (v.length >= 12) score++
  return score
})
const pwPct = computed(() => [0, 30, 55, 80, 100][pwScore.value] ?? 0)
const pwLabel = computed(() => ['—', '弱', '一般', '较强', '强'][pwScore.value] ?? '—')
const pwColor = computed(
  () =>
    ['var(--border-light)', 'var(--red)', 'var(--orange)', 'var(--blue)', 'var(--green)'][
      pwScore.value
    ] ?? 'var(--border-light)',
)

function clearAllErr() {
  errNick.value = ''
  errPhone.value = ''
  errCode.value = ''
  errPass.value = ''
  errPass2.value = ''
  errAgree.value = ''
}

function togglePw() {
  showPw.value = !showPw.value
}

function onSendCode() {
  if (!/^1\d{10}$/.test(phone.value.trim())) {
    errPhone.value = '请输入正确的 11 位手机号'
    uiToast('请先输入正确的手机号', 'error')
    return
  }
  if (countdown.value > 0) return
  countdown.value = 60
  uiToast('验证码已发送（演示：任意 6 位数字）', 'success')
  timer = setInterval(() => {
    countdown.value--
    if (countdown.value <= 0 && timer) {
      clearInterval(timer)
      timer = null
    }
  }, 1000)
}

async function onSubmit() {
  clearAllErr()
  const pv = pass.value
  let ok = true
  if (!nick.value.trim()) {
    errNick.value = '昵称不能为空'
    ok = false
  }
  if (!/^1\d{10}$/.test(phone.value.trim())) {
    errPhone.value = '请输入正确的 11 位手机号'
    ok = false
  }
  if (!/^\d{6}$/.test(code.value.trim())) {
    errCode.value = '请输入 6 位验证码'
    ok = false
  }
  if (pv.length < 8 || !/[a-zA-Z]/.test(pv) || !/\d/.test(pv)) {
    errPass.value = '密码需 8 位以上且同时包含字母和数字'
    ok = false
  }
  if (!pass2.value || pass2.value !== pv) {
    errPass2.value = '两次输入的密码不一致'
    ok = false
  }
  if (!agree.value) {
    errAgree.value = '请先勾选同意协议'
    ok = false
  }
  if (!ok) {
    uiToast('请检查表单填写', 'error')
    return
  }

  loading.value = true
  try {
    // 账号=手机号，保证注册后可用手机号登录；email 空串由后端自动补全
    await auth.register(phone.value.trim(), pv, '')
    uiToast('注册成功！请使用手机号登录', 'success')
    setTimeout(() => {
      void router.push({ path: '/auth', query: route.query })
    }, 500)
  } catch {
    // http 拦截器已 toast
    loading.value = false
    return
  }
  loading.value = false
}

function onAgreeLink(e: Event, msg: string) {
  e.preventDefault()
  uiToast(msg, 'info')
}

onUnmounted(() => {
  if (timer) clearInterval(timer)
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
        <h1 style="font-size:30px; line-height:1.35">加入 AITest Hub<br>开始你的第一叠测试拍立得</h1>
        <p class="text-dim mt-16" style="font-size:14.5px">注册即享九大模块免费体验：压测编排 · AI 用例 · 接口测试 · 用例与缺陷管理 · UI / App 自动化 · 提示词库 · 工具箱。</p>
        <div class="grid grid-2 mt-24" style="gap:10px">
          <div class="card" style="padding:12px 14px"><span class="tag tag-orange">🧪 压测编排</span></div>
          <div class="card" style="padding:12px 14px"><span class="tag tag-red">🤖 AI 用例</span></div>
          <div class="card" style="padding:12px 14px"><span class="tag tag-blue">🔗 接口测试</span></div>
          <div class="card" style="padding:12px 14px"><span class="tag tag-purple">📱 App 自动化</span></div>
        </div>
      </div>
    </div>

    <!-- 右侧注册表单 -->
    <div class="auth-panel">
      <div class="auth-card">
        <h2>创建账号 ✨</h2>
        <p class="sub">已有账号？<RouterLink to="/auth">直接登录</RouterLink></p>

        <form novalidate @submit.prevent="onSubmit">
          <div class="field" :class="{ 'has-err': !!errNick }">
            <label for="nick">昵称</label>
            <input
              id="nick"
              v-model="nick"
              class="input"
              type="text"
              placeholder="给自己起个名字，如：wxh"
              maxlength="20"
              @input="errNick = ''"
            >
            <div class="err-msg">{{ errNick || '昵称不能为空' }}</div>
          </div>

          <div class="field" :class="{ 'has-err': !!errPhone }">
            <label for="phone">手机号</label>
            <input
              id="phone"
              v-model="phone"
              class="input"
              type="tel"
              placeholder="请输入 11 位手机号"
              maxlength="11"
              @input="errPhone = ''"
            >
            <div class="err-msg">{{ errPhone || '请输入正确的 11 位手机号' }}</div>
          </div>

          <div class="field" :class="{ 'has-err': !!errCode }">
            <label for="code">短信验证码</label>
            <div class="input-group">
              <input
                id="code"
                v-model="code"
                class="input"
                type="text"
                placeholder="6 位验证码"
                maxlength="6"
                style="flex:1"
                @input="errCode = ''"
              >
              <button
                type="button"
                class="btn btn-ghost"
                style="white-space:nowrap"
                :disabled="countdown > 0"
                @click="onSendCode"
              >{{ sendLabel }}</button>
            </div>
            <div class="err-msg">{{ errCode || '请输入 6 位验证码' }}</div>
            <div class="hint">演示环境：任意 6 位数字均可通过</div>
          </div>

          <div class="field" :class="{ 'has-err': !!errPass }">
            <label for="pass">设置密码</label>
            <div class="relative">
              <input
                id="pass"
                v-model="pass"
                class="input"
                :type="showPw ? 'text' : 'password'"
                placeholder="8-32 位，含字母与数字"
                style="padding-right:44px"
                @input="errPass = ''"
              >
              <button type="button" class="pw-toggle" @click="togglePw">{{ showPw ? '🙈' : '👁' }}</button>
            </div>
            <div class="err-msg">{{ errPass || '密码需 8 位以上且同时包含字母和数字' }}</div>
            <div class="progress mt-8"><div class="bar" :style="{ width: pwPct + '%', background: pwColor }"></div></div>
            <div class="hint">密码强度：{{ pwLabel }}</div>
          </div>

          <div class="field" :class="{ 'has-err': !!errPass2 }">
            <label for="pass2">确认密码</label>
            <input
              id="pass2"
              v-model="pass2"
              class="input"
              type="password"
              placeholder="再输入一次密码"
              @input="errPass2 = ''"
            >
            <div class="err-msg">{{ errPass2 || '两次输入的密码不一致' }}</div>
          </div>

          <div class="field" :class="{ 'has-err': !!errAgree }">
            <label class="checkbox">
              <input v-model="agree" type="checkbox" @change="errAgree = ''">
              我已阅读并同意
              <a href="#" @click="onAgreeLink($event, '演示环境：服务协议占位页')">《服务协议》</a>
              与
              <a href="#" @click="onAgreeLink($event, '演示环境：隐私政策占位页')">《隐私政策》</a>
            </label>
            <div class="err-msg">{{ errAgree || '请先勾选同意协议' }}</div>
          </div>

          <button class="btn btn-primary btn-lg" type="submit" style="width:100%" :disabled="loading">
            <span v-if="loading" class="spinner"></span>
            {{ loading ? '注册中…' : '注 册' }}
          </button>

          <p class="text-faint mt-16" style="font-size:12.5px; text-align:center">
            已有账号？<RouterLink to="/auth">登录</RouterLink> · <RouterLink to="/">返回首页</RouterLink>
          </p>
        </form>
      </div>
    </div>
  </div>
</template>
