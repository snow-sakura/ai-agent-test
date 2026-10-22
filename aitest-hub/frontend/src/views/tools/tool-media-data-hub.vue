<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import { uiToast } from '@/composables/ui'
import http from '@/api/http'

/* ================= JSON ================= */
const jsonIn = ref('')
const jsonOut = ref('// 格式化结果将在此显示')
const jsonStatus = ref('')

function jsonSample() {
  jsonIn.value = '{\n  "name": "AITest Hub",\n  "version": "1.0",\n  "modules": ["用例", "缺陷", "接口"]\n}'
  jsonStatus.value = ''
}
function jsonClear() {
  jsonIn.value = ''
  jsonOut.value = '// 格式化结果将在此显示'
  jsonStatus.value = ''
}
async function jsonFormat() {
  if (!jsonIn.value.trim()) {
    uiToast('请输入 JSON', 'warn')
    return
  }
  try {
    const { data } = await http.post<{ result?: string; error?: string }>('/json-formatter', {
      text: jsonIn.value,
    })
    if (data.error) {
      jsonStatus.value = '❌ ' + data.error
      uiToast(data.error, 'error')
      return
    }
    jsonOut.value = data.result || ''
    jsonStatus.value = '✅ 格式化完成 · ' + jsonOut.value.split('\n').length + ' 行'
    uiToast('格式化成功', 'success')
  } catch {
    /* interceptor toast */
  }
}
function jsonMin() {
  try {
    jsonOut.value = JSON.stringify(JSON.parse(jsonIn.value))
    jsonStatus.value = '✅ 压缩完成'
    uiToast('压缩成功', 'success')
  } catch {
    jsonStatus.value = '❌ JSON 解析失败'
    uiToast('JSON 解析失败', 'error')
  }
}
function jsonSort() {
  try {
    const sortDeep = (v: unknown): unknown => {
      if (Array.isArray(v)) return v.map(sortDeep)
      if (v && typeof v === 'object') {
        const out: Record<string, unknown> = {}
        for (const k of Object.keys(v as Record<string, unknown>).sort()) {
          out[k] = sortDeep((v as Record<string, unknown>)[k])
        }
        return out
      }
      return v
    }
    jsonOut.value = JSON.stringify(sortDeep(JSON.parse(jsonIn.value)), null, 2)
    jsonStatus.value = '✅ 键已排序'
    uiToast('键排序完成', 'success')
  } catch {
    jsonStatus.value = '❌ JSON 解析失败'
    uiToast('JSON 解析失败', 'error')
  }
}
async function jsonCopy() {
  if (!jsonOut.value || jsonOut.value.startsWith('//')) {
    uiToast('暂无可复制结果', 'warn')
    return
  }
  try {
    await navigator.clipboard.writeText(jsonOut.value)
    uiToast('已复制到剪贴板', 'success')
  } catch {
    uiToast('复制失败', 'error')
  }
}

/* ================= Diff ================= */
const diffA = ref('登录接口返回 code:0\n用户列表分页大小 10\n订单状态：待支付')
const diffB = ref(
  '登录接口返回 code:200\n用户列表分页大小 20\n订单状态：待支付\n新增：退款状态：审核中',
)
const diffStat = ref('')
const diffLines = ref<{ kind: 'same' | 'del' | 'add' | 'pad'; text: string }[]>([])

function runDiff() {
  const a = diffA.value.split('\n')
  const b = diffB.value.split('\n')
  const lines: typeof diffLines.value = []
  let add = 0
  let del = 0
  const max = Math.max(a.length, b.length)
  for (let i = 0; i < max; i++) {
    if (a[i] === b[i]) {
      lines.push({ kind: 'same', text: '  ' + (a[i] || '') })
    } else {
      if (a[i] !== undefined) {
        lines.push({ kind: 'del', text: '- ' + a[i] })
        del++
      }
      if (b[i] !== undefined) {
        lines.push({ kind: 'add', text: '+ ' + b[i] })
        add++
      }
    }
  }
  diffLines.value = lines
  diffStat.value = '差异：+' + add + ' 行 / -' + del + ' 行'
  uiToast('对比完成：+' + add + ' / -' + del, 'success')
}
function swapDiff() {
  const t = diffA.value
  diffA.value = diffB.value
  diffB.value = t
  uiToast('已交换 A/B', 'info')
}

/* ================= 时间戳 ================= */
const tsIn = ref('')
const tsOut = ref('')
const tsNow = ref('—')
const tsDate = ref('')
const tsRevOut = ref('')
let tsTimer: ReturnType<typeof setInterval> | undefined

function fmtDate(d: Date) {
  return (
    d.toLocaleDateString('zh-CN') +
    ' ' +
    d.toLocaleTimeString('zh-CN', { hour12: false }) +
    ' (' +
    d.toISOString() +
    ')'
  )
}
function tsConvert() {
  const v = tsIn.value.trim()
  if (!/^\d+$/.test(v)) {
    uiToast('请输入纯数字时间戳', 'error')
    return
  }
  let n = Number(v)
  if (n < 1e12) n *= 1000
  tsOut.value = fmtDate(new Date(n))
}
async function copyTs(text: string, msg: string) {
  try {
    await navigator.clipboard.writeText(text)
    uiToast(msg, 'success')
  } catch {
    uiToast('复制失败', 'error')
  }
}
function tsReverse() {
  if (!tsDate.value) {
    uiToast('请先选择日期时间', 'error')
    return
  }
  const ts = Math.floor(new Date(tsDate.value).getTime() / 1000)
  tsRevOut.value = '秒级：' + ts + ' ｜ 毫秒级：' + ts * 1000
}

/* ================= Base64 / URL ================= */
const b64In = ref('')
const b64Out = ref('')
const urlIn = ref('')
const urlOut = ref('')

async function b64Enc() {
  if (!b64In.value) {
    uiToast('请输入文本', 'warn')
    return
  }
  try {
    const { data } = await http.post<{ result?: string; error?: string }>('/base64-converter', {
      action: 'encode',
      text: b64In.value,
      plus: '',
    })
    if (data.error) {
      uiToast(data.error, 'error')
      return
    }
    b64Out.value = data.result || ''
    uiToast('Base64 编码成功', 'success')
  } catch {
    /* interceptor */
  }
}
async function b64Dec() {
  if (!b64In.value) {
    uiToast('请输入内容', 'warn')
    return
  }
  try {
    const { data } = await http.post<{ result?: string; error?: string }>('/base64-converter', {
      action: 'decode',
      text: b64In.value,
      plus: '',
    })
    if (data.error) {
      uiToast(data.error, 'error')
      return
    }
    b64Out.value = data.result || ''
    uiToast('Base64 解码成功', 'success')
  } catch {
    /* interceptor */
  }
}
async function urlEnc() {
  if (!urlIn.value) {
    uiToast('请输入文本', 'warn')
    return
  }
  try {
    const { data } = await http.post<{ result?: string; error?: string }>('/url-converter', {
      action: 'encode',
      text: urlIn.value,
      plus: '',
    })
    if (data.error) {
      uiToast(data.error, 'error')
      return
    }
    urlOut.value = data.result || ''
    uiToast('URL 编码成功', 'success')
  } catch {
    /* interceptor */
  }
}
async function urlDec() {
  if (!urlIn.value) {
    uiToast('请输入内容', 'warn')
    return
  }
  try {
    const { data } = await http.post<{ result?: string; error?: string }>('/url-converter', {
      action: 'decode',
      text: urlIn.value,
      plus: '',
    })
    if (data.error) {
      uiToast(data.error, 'error')
      return
    }
    urlOut.value = data.result || ''
    uiToast('URL 解码成功', 'success')
  } catch {
    /* interceptor */
  }
}

/* ================= 图片处理 ================= */
const imgFile = ref<File | null>(null)
const imgPreviewUrl = ref('')
const imgInfo = ref('')
const imgFmt = ref('WebP')
const imgQuality = ref(80)
const imgTargetMB = ref(1)
const imgBusy = ref(false)
const imgResult = ref<{ text: string; url: string; name: string } | null>(null)
const imgInput = ref<HTMLInputElement | null>(null)

function onImgPick(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files?.[0]) loadImg(input.files[0])
}
function onImgDrop(e: DragEvent) {
  const f = e.dataTransfer?.files?.[0]
  if (f) loadImg(f)
}
function pickImg() {
  imgInput.value?.click()
}
function loadImg(f: File) {
  if (!f.type.startsWith('image/')) {
    uiToast('请选择图片文件', 'error')
    return
  }
  if (f.size > 10 * 1024 * 1024) {
    uiToast('图片超过 10MB 限制', 'error')
    return
  }
  imgFile.value = f
  if (imgPreviewUrl.value) URL.revokeObjectURL(imgPreviewUrl.value)
  imgPreviewUrl.value = URL.createObjectURL(f)
  imgInfo.value = f.name + ' · ' + (f.size / 1024).toFixed(1) + 'KB'
  imgResult.value = null
  uiToast('图片已加载：' + f.name, 'success')
}
async function convertImg() {
  if (!imgFile.value) return
  imgBusy.value = true
  try {
    const fd = new FormData()
    fd.append('file', imgFile.value)
    fd.append('target_format', imgFmt.value)
    fd.append('quality', String(imgQuality.value))
    const { data } = await http.post<Blob>('/image-format-converter', fd, {
      responseType: 'blob',
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    const blob = data instanceof Blob ? data : new Blob([data])
    const ext = imgFmt.value.toLowerCase()
    const name = imgFile.value.name.replace(/\.[^.]+$/, '') + '.' + ext
    const url = URL.createObjectURL(blob)
    const after = (blob.size / 1024).toFixed(1)
    imgResult.value = {
      text:
        '✅ 转换为 ' +
        imgFmt.value +
        ' 完成：' +
        (imgFile.value.size / 1024).toFixed(1) +
        'KB → ' +
        after +
        'KB',
      url,
      name,
    }
    uiToast('图片处理完成，压缩 ' + Math.round((1 - blob.size / imgFile.value.size) * 100) + '%', 'success')
  } catch (err: any) {
    // responseType 为 blob 时，错误响应体也是 Blob，需要读取后解析 detail
    let detail = ''
    const resp = err?.response
    if (resp?.data instanceof Blob) {
      try {
        const txt = await resp.data.text()
        detail = JSON.parse(txt)?.detail || txt
      } catch {
        /* 忽略解析失败 */
      }
    } else {
      detail = resp?.data?.detail || err?.message || ''
    }
    uiToast('图片转换失败' + (detail ? '：' + detail : ''), 'error')
    imgResult.value = {
      text: '❌ 转换失败：' + (detail || '未知错误'),
      url: '',
      name: '',
    }
  } finally {
    imgBusy.value = false
  }
}
/* 按目标大小压缩：后端二分质量 + 逐步缩尺寸，直到不超过 target_size(MB) */
async function resizeImg() {
  if (!imgFile.value) return
  const mb = Number(imgTargetMB.value)
  if (!Number.isFinite(mb) || mb <= 0) {
    uiToast('目标大小必须是大于 0 的数字（MB）', 'error')
    return
  }
  imgBusy.value = true
  try {
    const fd = new FormData()
    fd.append('file', imgFile.value)
    fd.append('target_size', String(mb))
    const { data } = await http.post<Blob>('/image-sizer', fd, {
      responseType: 'blob',
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    const blob = data instanceof Blob ? data : new Blob([data])
    const ext = (imgFile.value.name.split('.').pop() || 'png').toLowerCase()
    const name = imgFile.value.name.replace(/\.[^.]+$/, '') + '_' + mb + 'mb.' + ext
    const url = URL.createObjectURL(blob)
    imgResult.value = {
      text:
        '✅ 已压缩到 ≤ ' +
        mb +
        'MB：' +
        (imgFile.value.size / 1024).toFixed(1) +
        'KB → ' +
        (blob.size / 1024).toFixed(1) +
        'KB',
      url,
      name,
    }
    uiToast('已压缩到 ≤ ' + mb + 'MB', 'success')
  } catch (err: any) {
    let detail = ''
    const resp = err?.response
    if (resp?.data instanceof Blob) {
      try {
        const txt = await resp.data.text()
        detail = JSON.parse(txt)?.detail || txt
      } catch {
        /* 忽略解析失败 */
      }
    } else {
      detail = resp?.data?.detail || err?.message || ''
    }
    uiToast('压缩失败' + (detail ? '：' + detail : ''), 'error')
    imgResult.value = {
      text: '❌ 压缩失败：' + (detail || '未知错误'),
      url: '',
      name: '',
    }
  } finally {
    imgBusy.value = false
  }
}
function downloadImg() {
  if (!imgResult.value) return
  const a = document.createElement('a')
  a.href = imgResult.value.url
  a.download = imgResult.value.name
  a.click()
  uiToast('演示环境：文件已保存', 'success')
}

/* ================= TTS ================= */
const ttsText = ref(
  '欢迎使用 AITest Hub 测试平台，今日冒烟用例全部通过，暂无阻塞缺陷。',
)
const ttsVoice = ref('alloy')
const ttsSpeed = ref(1.0)
const ttsBusy = ref(false)
const ttsStatus = ref('')
const ttsAudioUrl = ref('')
const ttsAudio = ref<HTMLAudioElement | null>(null)
const ttsProgress = ref(0)
const ttsPlaying = ref(false)

const VOICE_OPTS = [
  { label: '晓晓 · 温柔女声', value: 'alloy' },
  { label: '宇轩 · 沉稳男声', value: 'onyx' },
  { label: '灵儿 · 活泼女声', value: 'nova' },
]
const SPEED_OPTS = [0.8, 1.0, 1.2, 1.5]

const ttsCount = computed(() => ttsText.value.length)
const ttsClamped = computed(() => ttsText.value.slice(0, 500))

function onTtsInput() {
  if (ttsText.value.length > 500) {
    ttsText.value = ttsText.value.slice(0, 500)
    uiToast('最多 500 字', 'warn')
  }
}

async function genTts() {
  const t = ttsText.value.trim()
  if (!t) {
    uiToast('请输入文本内容', 'error')
    return
  }
  ttsBusy.value = true
  ttsStatus.value = '音频生成中…'
  try {
    const { data } = await http.post<Blob>(
      '/audio-generator',
      {
        text: ttsClamped.value,
        voice: ttsVoice.value,
        speed: ttsSpeed.value,
        format: 'mp3',
      },
      { responseType: 'blob' },
    )
    const blob = data instanceof Blob ? data : new Blob([data], { type: 'audio/mpeg' })
    if (ttsAudioUrl.value) URL.revokeObjectURL(ttsAudioUrl.value)
    ttsAudioUrl.value = URL.createObjectURL(blob)
    ttsAudio.value = new Audio(ttsAudioUrl.value)
    ttsProgress.value = 0
    ttsPlaying.value = false
    ttsAudio.value.ontimeupdate = () => {
      const a = ttsAudio.value
      if (a && a.duration) ttsProgress.value = (a.currentTime / a.duration) * 100
    }
    ttsAudio.value.onended = () => {
      ttsPlaying.value = false
      ttsProgress.value = 0
    }
    const voiceLabel = VOICE_OPTS.find((v) => v.value === ttsVoice.value)?.value || ttsVoice.value
    ttsStatus.value = 'tts-output.mp3 · ' + voiceLabel + ' · ' + ttsSpeed.value
    uiToast('音频生成完成', 'success')
  } catch {
    ttsStatus.value = '生成失败'
    uiToast('音频生成失败', 'error')
  } finally {
    ttsBusy.value = false
  }
}

function togglePlay() {
  const a = ttsAudio.value
  if (!a) return
  if (ttsPlaying.value) {
    a.pause()
    ttsPlaying.value = false
  } else {
    void a.play()
    ttsPlaying.value = true
  }
}
function downloadTts() {
  if (!ttsAudioUrl.value) return
  const a = document.createElement('a')
  a.href = ttsAudioUrl.value
  a.download = 'tts-output.mp3'
  a.click()
  uiToast('tts-output.mp3 下载成功', 'success')
}

onMounted(() => {
  const tick = () => {
    tsNow.value = Math.floor(Date.now() / 1000) + ' ｜ ' + fmtDate(new Date())
  }
  tick()
  tsTimer = setInterval(tick, 1000)
})

onUnmounted(() => {
  if (tsTimer) clearInterval(tsTimer)
  if (imgPreviewUrl.value) URL.revokeObjectURL(imgPreviewUrl.value)
  if (ttsAudioUrl.value) URL.revokeObjectURL(ttsAudioUrl.value)
  if (ttsAudio.value) {
    ttsAudio.value.pause()
    ttsAudio.value = null
  }
})
</script>

<template>
  <ModuleShell slug="tool-media-data-hub">
    <template #default="{ tab }">
      <!-- ============ JSON ============ -->
      <template v-if="tab === 'json'">
        <div class="grid grid-2">
          <div class="card">
            <div class="flex-between mb-8">
              <div class="card-title" style="margin: 0">输入</div>
              <div class="flex">
                <button class="btn btn-sm btn-ghost" @click="jsonSample">示例</button>
                <button class="btn btn-sm btn-ghost" @click="jsonClear">清空</button>
              </div>
            </div>
            <textarea
              v-model="jsonIn"
              class="textarea mono"
              rows="12"
              placeholder='{"name":"AITest Hub","version":"1.0"}'
            ></textarea>
            <div class="flex mt-8">
              <button class="btn btn-primary btn-sm" @click="jsonFormat">✨ 格式化</button>
              <button class="btn btn-ghost btn-sm" @click="jsonMin">压缩</button>
              <button class="btn btn-ghost btn-sm" @click="jsonSort">键排序</button>
              <button class="btn btn-ghost btn-sm" @click="jsonCopy">复制结果</button>
            </div>
            <div class="mt-8" style="font-size: 12.5px">{{ jsonStatus }}</div>
          </div>
          <div class="card">
            <div class="card-title">输出</div>
            <div class="code-block" style="min-height: 280px">{{ jsonOut }}</div>
          </div>
        </div>
      </template>

      <!-- ============ Diff ============ -->
      <template v-if="tab === 'diff'">
        <div class="grid grid-2">
          <div class="card">
            <div class="card-title">原文（A）</div>
            <textarea v-model="diffA" class="textarea mono" rows="10" placeholder="粘贴原始文本…"></textarea>
          </div>
          <div class="card">
            <div class="card-title">新文（B）</div>
            <textarea v-model="diffB" class="textarea mono" rows="10" placeholder="粘贴对比文本…"></textarea>
          </div>
        </div>
        <div class="flex mt-16">
          <button class="btn btn-primary" @click="runDiff">🔍 对比</button>
          <button class="btn btn-ghost" @click="swapDiff">⇄ 交换 A/B</button>
          <span class="text-dim" style="font-size: 12.5px">{{ diffStat }}</span>
        </div>
        <div class="card mt-16">
          <div class="card-title">差异结果</div>
          <div class="code-block">
            <template v-if="!diffLines.length">// 点击「对比」查看差异</template>
            <template v-else>
              <div
                v-for="(l, i) in diffLines"
                :key="i"
                :class="l.kind === 'del' ? 'n' : l.kind === 'add' ? 's' : ''"
              >{{ l.text }}</div>
            </template>
          </div>
        </div>
      </template>

      <!-- ============ 时间戳 ============ -->
      <template v-if="tab === 'ts'">
        <div class="grid grid-2">
          <div class="card">
            <div class="card-title">时间戳 → 日期</div>
            <div class="field">
              <label>时间戳（秒或毫秒）</label>
              <div class="input-group">
                <input v-model="tsIn" class="input mono" placeholder="1727000000" />
                <button class="btn btn-primary" @click="tsConvert">转换</button>
              </div>
            </div>
            <div class="card" style="background: var(--bg-soft)">
              <span v-if="tsOut" class="text-green mono">{{ tsOut }}</span>
              <span v-else class="text-faint">结果将在此显示</span>
            </div>
          </div>
          <div class="card">
            <div class="card-title">当前时间</div>
            <div class="mono" style="font-size: 18px">{{ tsNow }}</div>
            <div class="flex mt-8">
              <button class="btn btn-sm btn-ghost" @click="copyTs(String(Math.floor(Date.now() / 1000)), '已复制秒级时间戳')">
                复制秒级
              </button>
              <button class="btn btn-sm btn-ghost" @click="copyTs(String(Date.now()), '已复制毫秒级时间戳')">
                复制毫秒级
              </button>
            </div>
            <hr style="border: none; border-top: 1px solid var(--border); margin: 14px 0" />
            <div class="field">
              <label>日期 → 时间戳</label>
              <input v-model="tsDate" class="input" type="datetime-local" />
            </div>
            <button class="btn btn-primary btn-sm" @click="tsReverse">反向转换</button>
            <div class="mono mt-8" style="color: var(--green)">{{ tsRevOut }}</div>
          </div>
        </div>
      </template>

      <!-- ============ Base64 / URL ============ -->
      <template v-if="tab === 'codec'">
        <div class="grid grid-2">
          <div class="card">
            <div class="card-title">Base64</div>
            <textarea v-model="b64In" class="textarea mono" rows="5" placeholder="输入文本…"></textarea>
            <div class="flex mt-8">
              <button class="btn btn-primary btn-sm" @click="b64Enc">编码 →</button>
              <button class="btn btn-ghost btn-sm" @click="b64Dec">← 解码</button>
            </div>
            <textarea v-model="b64Out" class="textarea mono mt-8" rows="5" placeholder="结果…"></textarea>
          </div>
          <div class="card">
            <div class="card-title">URL 编解码</div>
            <textarea v-model="urlIn" class="textarea mono" rows="5" placeholder="输入 URL 或含特殊字符文本…"></textarea>
            <div class="flex mt-8">
              <button class="btn btn-primary btn-sm" @click="urlEnc">编码 →</button>
              <button class="btn btn-ghost btn-sm" @click="urlDec">← 解码</button>
            </div>
            <textarea v-model="urlOut" class="textarea mono mt-8" rows="5" placeholder="结果…"></textarea>
          </div>
        </div>
      </template>

      <!-- ============ 图片处理 ============ -->
      <template v-if="tab === 'img'">
        <div class="grid" style="grid-template-columns: 1fr 1.2fr">
          <div class="card">
            <div class="card-title">上传图片</div>
            <div
              class="card"
              style="border-style: dashed; text-align: center; padding: 34px; cursor: pointer"
              @click="pickImg"
              @dragover.prevent
              @drop.prevent="onImgDrop"
            >
              <div style="font-size: 32px">🖼️</div>
              <div class="text-dim mt-8">点击选择或拖拽图片到此处</div>
              <div class="text-faint" style="font-size: 12px">支持 PNG / JPG / WebP，≤ 10MB</div>
              <img
                v-if="imgPreviewUrl"
                :src="imgPreviewUrl"
                alt="preview"
                style="max-width: 100%; max-height: 180px; margin-top: 12px; border-radius: 8px"
              />
            </div>
            <input ref="imgInput" type="file" class="file-input" accept="image/*" @change="onImgPick" />
            <div class="mt-8 text-faint" style="font-size: 12.5px">{{ imgInfo }}</div>
            <div class="field mt-16">
              <label>目标格式</label>
              <select v-model="imgFmt" class="select">
                <option>WebP</option>
                <option>JPEG</option>
                <option>PNG</option>
              </select>
            </div>
            <div class="field">
              <label>质量（1-100）</label>
              <input v-model.number="imgQuality" class="input mono" type="range" min="1" max="100" />
              <div class="hint">{{ imgQuality }}</div>
            </div>
            <div class="field">
              <label>目标大小（MB，按大小压缩用）</label>
              <input
                v-model.number="imgTargetMB"
                class="input mono"
                type="number"
                min="0.1"
                step="0.1"
                placeholder="如：1"
              />
            </div>
            <div class="flex" style="gap: 8px">
              <button
                class="btn btn-primary btn-sm"
                :disabled="!imgFile || imgBusy"
                @click="convertImg"
              >
                <span v-if="imgBusy" class="spinner"></span>{{ imgBusy ? '处理中…' : '⚙️ 开始压缩 / 转换' }}
              </button>
              <button
                class="btn btn-ghost btn-sm"
                :disabled="!imgFile || imgBusy"
                @click="resizeImg"
              >
                🎯 压到指定大小
              </button>
            </div>
          </div>
          <div class="card">
            <div class="card-title">处理结果</div>
            <div v-if="imgResult" class="code-block">
              <span class="text-green">{{ imgResult.text }}</span>
            </div>
            <div v-else class="empty">
              <div class="e-icon">🖼️</div>
              <div class="e-text">选择图片后开始转换</div>
            </div>
            <button
              v-if="imgResult && imgResult.url"
              class="btn btn-sm btn-ghost mt-8"
              @click="downloadImg"
            >
              ⬇️ 下载
            </button>
          </div>
        </div>
      </template>

      <!-- ============ TTS ============ -->
      <template v-if="tab === 'tts'">
        <div class="grid grid-2">
          <div class="card">
            <div class="card-title">输入文本</div>
            <textarea
              v-model="ttsText"
              class="textarea"
              rows="8"
              maxlength="500"
              placeholder="输入要转成语音的文本…"
              @input="onTtsInput"
            ></textarea>
            <div class="flex-between mt-8">
              <span class="text-faint" style="font-size: 12px">{{ ttsCount }} / 500</span>
              <div class="flex">
                <select v-model="ttsVoice" class="select" style="width: auto">
                  <option v-for="v in VOICE_OPTS" :key="v.value" :value="v.value">{{ v.label }}</option>
                </select>
                <select v-model.number="ttsSpeed" class="select" style="width: auto">
                  <option v-for="s in SPEED_OPTS" :key="s" :value="s">{{ s }}x</option>
                </select>
              </div>
            </div>
            <button class="btn btn-primary mt-8" :disabled="ttsBusy" @click="genTts">
              <span v-if="ttsBusy" class="spinner"></span>{{ ttsBusy ? '生成中…' : '🎵 生成音频' }}
            </button>
          </div>
          <div class="card">
            <div class="card-title">播放器</div>
            <div v-if="ttsStatus" class="text-dim" style="font-size: 13px; margin-bottom: 12px">
              {{ ttsStatus }}
            </div>
            <div v-else class="empty">
              <div class="e-icon">🔊</div>
              <div class="e-text">生成后可在此播放</div>
            </div>
            <template v-if="ttsAudioUrl">
              <div class="progress">
                <div class="bar" :style="{ width: ttsProgress + '%' }"></div>
              </div>
              <div class="flex mt-8">
                <button class="btn btn-sm btn-primary" @click="togglePlay">
                  {{ ttsPlaying ? '⏸ 暂停' : '▶ 播放' }}
                </button>
                <button class="btn btn-sm btn-ghost" @click="downloadTts">⬇️ 下载</button>
              </div>
              <audio :src="ttsAudioUrl" style="display: none"></audio>
            </template>
          </div>
        </div>
      </template>
    </template>
  </ModuleShell>
</template>

<style scoped>
.hint {
  font-size: 12px;
  color: var(--text-faint);
  margin-top: 5px;
}
</style>
