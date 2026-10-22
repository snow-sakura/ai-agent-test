import { defineStore } from 'pinia'
import { ref } from 'vue'
import http from '@/api/http'
import { TOKEN_KEY, AUTH_KEY, LOGIN_USER_KEY } from '@/api/http'

export const useAuth = defineStore('auth', () => {
  const token = ref(localStorage.getItem(TOKEN_KEY) || '')
  const user = ref(localStorage.getItem(LOGIN_USER_KEY) || '')

  function isLogin(): boolean {
    return localStorage.getItem(AUTH_KEY) === '1' && !!localStorage.getItem(TOKEN_KEY)
  }

  async function login(account: string, password: string) {
    const body = new URLSearchParams({ username: account, phone: account, password })
    const { data } = await http.post('/auth/login', body, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
    token.value = data.access_token
    user.value = data.user?.username || account
    localStorage.setItem(TOKEN_KEY, token.value)
    localStorage.setItem(AUTH_KEY, '1')
    localStorage.setItem(LOGIN_USER_KEY, user.value)
    return data
  }

  async function register(account: string, password: string, email: string) {
    const body = new URLSearchParams({ username: account, email, password })
    const { data } = await http.post('/auth/register', body, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
    return data
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(AUTH_KEY)
    localStorage.removeItem(LOGIN_USER_KEY)
    token.value = ''
    user.value = ''
    window.location.href = '/'
  }

  return { token, user, isLogin, login, register, logout }
})
