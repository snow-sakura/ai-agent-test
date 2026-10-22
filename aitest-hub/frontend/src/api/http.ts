import axios from 'axios'
import { uiToast } from '@/composables/ui'

declare module 'axios' {
  export interface AxiosRequestConfig<D = any, P = any> {
    /** 失败时不弹出全局 Toast */
    silent?: boolean
  }
}

export const TOKEN_KEY = 'aitesthub_token'
export const AUTH_KEY = 'aitesthub_auth'
export const LOGIN_USER_KEY = 'aitesthub_login_user'

export const http = axios.create({ baseURL: '/api', timeout: 60000 })

http.interceptors.request.use((cfg) => {
  const t = localStorage.getItem(TOKEN_KEY)
  if (t) cfg.headers.Authorization = 'Bearer ' + t
  return cfg
})

http.interceptors.response.use(
  (r) => r,
  async (err) => {
    let detail = err?.response?.data?.detail
    // responseType: 'blob' 时，错误响应体也是 Blob，需读取文本后解析 detail
    if (
      detail === undefined &&
      typeof Blob !== 'undefined' &&
      err?.response?.data instanceof Blob
    ) {
      try {
        const txt = await err.response.data.text()
        const parsed = txt ? JSON.parse(txt) : null
        detail = parsed?.detail ?? (txt && txt.length < 300 ? txt : undefined)
      } catch {
        /* 非 JSON 错误体，忽略 */
      }
    }
    const msg =
      typeof detail === 'string' ? detail : 'HTTP ' + String(err?.response?.status ?? 0)
    const silent = (err.config as Record<string, unknown> | undefined)?.silent === true
    if (!silent) uiToast(msg, 'error')
    if (err?.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(AUTH_KEY)
      const back = encodeURIComponent(location.pathname + location.search)
      if (!location.pathname.startsWith('/auth')) location.href = '/auth?redirect=' + back
    }
    const e = new Error(msg)
    // 保留原始 response，便于调用方读取状态码/错误体
    ;(e as any).response = err?.response
    ;(e as any).config = err?.config
    return Promise.reject(e)
  },
)

export default http
