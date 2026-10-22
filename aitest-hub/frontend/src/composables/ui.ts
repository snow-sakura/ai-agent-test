import { reactive } from 'vue'

/* Global UI services replicating the design-system behaviours
   (toast / confirm / prompt / "more content" modal). */

export type ToastKind = 'success' | 'error' | 'warn' | 'info'
export interface ToastItem {
  id: number
  text: string
  kind: ToastKind
}

export const TOAST_ICONS: Record<ToastKind, string> = {
  success: '\u2705',
  error: '\u274c',
  warn: '\u26a0\ufe0f',
  info: '\u2139\ufe0f',
}

export const toasts = reactive<ToastItem[]>([])
let _tid = 0

export function uiToast(text: string, kind: ToastKind = 'info', ms = 2600) {
  const id = ++_tid
  toasts.push({ id, text, kind })
  setTimeout(() => {
    const i = toasts.findIndex((t) => t.id === id)
    if (i >= 0) toasts.splice(i, 1)
  }, ms)
}

export interface ConfirmState {
  show: boolean
  title: string
  message: string
  danger: boolean
  onOk: (() => void) | null
}
export const confirmState = reactive<ConfirmState>({
  show: false,
  title: '',
  message: '',
  danger: false,
  onOk: null,
})

export function uiConfirm(o: { title?: string; message?: string; danger?: boolean; onOk?: () => void }) {
  confirmState.title = o.title || ''
  confirmState.message = o.message || ''
  confirmState.danger = !!o.danger
  confirmState.onOk = o.onOk || null
  confirmState.show = true
}

export function uiConfirmResolve(ok: boolean) {
  const fn = confirmState.onOk
  confirmState.show = false
  confirmState.onOk = null
  if (ok && fn) fn()
}

export interface PromptState {
  show: boolean
  title: string
  label: string
  value: string
  onOk: ((v: string) => void) | null
}
export const promptState = reactive<PromptState>({
  show: false,
  title: '',
  label: '',
  value: '',
  onOk: null,
})

export function uiPrompt(o: { title?: string; label?: string; defaultValue?: string; onOk?: (v: string) => void }) {
  promptState.title = o.title || ''
  promptState.label = o.label || ''
  promptState.value = o.defaultValue || ''
  promptState.onOk = o.onOk || null
  promptState.show = true
}

export function uiPromptResolve(ok: boolean) {
  const fn = promptState.onOk
  const v = promptState.value
  promptState.show = false
  promptState.onOk = null
  if (ok && fn) fn(v)
}

export interface MoreState {
  show: boolean
  title: string
  html: string
}
export const moreState = reactive<MoreState>({ show: false, title: '', html: '' })

export function uiMore(title: string, html: string) {
  moreState.title = title
  moreState.html = html
  moreState.show = true
}
