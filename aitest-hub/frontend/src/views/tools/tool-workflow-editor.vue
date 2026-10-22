<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ModuleShell from '@/components/ui/ModuleShell.vue'
import DataTable from '@/components/ui/DataTable.vue'
import { uiToast, uiConfirm } from '@/composables/ui'
import http from '@/api/http'

/* ---------- 数据模型（对齐 UI/tool-workflow-editor.html + backend workflows.py） ---------- */
interface WfRow {
  id: number
  name: string
  desc: string
  status: string
  nodes: number
  runs: number
  created: string
  updated: string
}
interface CvNode {
  key: string
  type: string
  name: string
  cfg: Record<string, unknown>
  x?: number
  y?: number
}
interface CvEdge {
  from: string
  to: string
}
interface WfDetail extends WfRow {
  canvas: { nodes: CvNode[]; edges: CvEdge[] }
}
interface RunResult {
  key: string
  name: string
  type: string
  status: string
  dur: string
  output: string
}
interface RunResp {
  ok: boolean
  name: string
  total: number
  passed: number
  results: RunResult[]
  summary: string
}

const NT: Record<string, { label: string; icon: string; cls: string }> = {
  start: { label: '开始', icon: '🚦', cls: 'tag-green' },
  skill: { label: '技能', icon: '🛠️', cls: 'tag-blue' },
  mcp: { label: 'MCP 工具', icon: '🔌', cls: 'tag-purple' },
  judge: { label: '条件判断', icon: '⚖️', cls: 'tag-orange' },
  loop: { label: '循环', icon: '🔁', cls: 'tag' },
  end: { label: '结束', icon: '🏁', cls: 'tag-red' },
}
const NT_KEYS = Object.keys(NT)

const list = ref<WfRow[]>([])
const kw = ref('')
const statusF = ref('')

async function reload() {
  const { data } = await http.get<WfRow[]>('/workflows')
  list.value = data || []
}

onMounted(() => {
  void reload().catch(() => undefined)
})

const filtered = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return list.value.filter(
    (w) =>
      (!k || (w.name + w.desc).toLowerCase().includes(k)) &&
      (!statusF.value || w.status === statusF.value),
  )
})

function resetFilter() {
  kw.value = ''
  statusF.value = ''
  uiToast('筛选已重置', 'info')
}

const columns = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: '流程名称' },
  { key: 'nodes', label: '节点数' },
  { key: 'runs', label: '执行次数' },
  { key: 'status', label: '状态' },
  { key: 'created', label: '创建时间' },
]

/* ---------- 画布状态 ---------- */
const cvWfId = ref<number | null>(null)
const cvName = ref('未命名流程')
const cvStatus = ref('草稿')
const canvasNodes = ref<CvNode[]>([])
const canvasEdges = ref<CvEdge[]>([])
const selected = ref<string | null>(null)
const edgeAdd = ref('')

function edgesFrom(key: string): string[] {
  return canvasEdges.value.filter((e) => e.from === key).map((e) => e.to)
}

function addNode(type: string) {
  const key = `n${canvasNodes.value.length + 1}_${Math.floor(Math.random() * 90 + 10)}`
  canvasNodes.value.push({ key, type, name: `${NT[type]?.label || type}节点`, cfg: {} })
  uiToast(`已添加${NT[type]?.label || type}节点`, 'success')
}

function selectNode(key: string) {
  selected.value = selected.value === key ? null : key
  if (!selected.value) return
  const n = canvasNodes.value.find((x) => x.key === key)
  if (!n) return
  ndTitle.value = `节点配置：${n.name}`
  ndName.value = n.name
  ndType.value = `${n.type} · ${NT[n.type]?.label || n.type}`
  ndJson.value = JSON.stringify(n.cfg, null, 2)
  ndDelShow.value = n.type !== 'start'
  nodeOpen.value = true
}

async function loadToCanvas(w: WfRow) {
  const { data } = await http.get<WfDetail>(`/workflows/${w.id}`)
  cvWfId.value = w.id
  cvName.value = data.name
  cvStatus.value = data.status
  canvasNodes.value = data.canvas?.nodes || []
  canvasEdges.value = data.canvas?.edges || []
  selected.value = null
  uiToast(`已载入「${w.name}」到画布`, 'info')
}

function removeEdge(to: string) {
  if (!selected.value) return
  canvasEdges.value = canvasEdges.value.filter((e) => !(e.from === selected.value && e.to === to))
}

function addEdge() {
  if (!selected.value || !edgeAdd.value) return
  canvasEdges.value.push({ from: selected.value, to: edgeAdd.value })
  edgeAdd.value = ''
}

const edgeTargets = computed(() => {
  if (!selected.value) return []
  const cur = edgesFrom(selected.value)
  return canvasNodes.value.filter((n) => n.key !== selected.value && n.type !== 'start' && !cur.includes(n.key))
})

const edgeCurrent = computed(() => {
  if (!selected.value) return []
  return edgesFrom(selected.value).map((k) => ({
    key: k,
    name: canvasNodes.value.find((n) => n.key === k)?.name || k,
  }))
})

/* ---------- 节点配置弹窗 ---------- */
const nodeOpen = ref(false)
const ndTitle = ref('节点配置')
const ndName = ref('')
const ndType = ref('')
const ndJson = ref('{}')
const ndDelShow = ref(true)

function saveNode() {
  if (!selected.value) return
  const n = canvasNodes.value.find((x) => x.key === selected.value)
  if (!n) return
  const nm = ndName.value.trim()
  if (!nm) {
    uiToast('请填写节点名称', 'error')
    return
  }
  try {
    n.cfg = JSON.parse(ndJson.value || '{}')
  } catch (e) {
    uiToast('JSON 格式错误：' + String((e as Error).message).slice(0, 40), 'error')
    return
  }
  n.name = nm
  nodeOpen.value = false
  uiToast('节点配置已保存', 'success')
}

function delNode() {
  if (!selected.value) return
  const key = selected.value
  canvasNodes.value = canvasNodes.value.filter((x) => x.key !== key)
  canvasEdges.value = canvasEdges.value.filter((e) => e.from !== key && e.to !== key)
  selected.value = null
  nodeOpen.value = false
  uiToast('节点已删除（出边同步清理）', 'success')
}

function clearCanvas() {
  uiConfirm({
    title: '清空画布',
    message: '将移除全部节点与出边（不影响已保存流程），确定吗？',
    onOk: () => {
      canvasNodes.value = []
      canvasEdges.value = []
      selected.value = null
      uiToast('画布已清空', 'success')
    },
  })
}

async function saveCanvas() {
  const payload = {
    canvas: { nodes: canvasNodes.value, edges: canvasEdges.value },
  }
  if (cvWfId.value) {
    await http.put(`/workflows/${cvWfId.value}`, payload)
  } else {
    const { data } = await http.post<WfDetail>('/workflows', {
      name: cvName.value,
      description: '画布新建流程',
      status: '草稿',
      canvas: payload.canvas,
    })
    cvWfId.value = data.id
  }
  await reload()
  uiToast(`流程已保存（${canvasNodes.value.length} 节点）`, 'success')
}

/* ---------- 试运行 ---------- */
const runOpen = ref(false)
const runBusy = ref(false)
const runSummary = ref('')
const runRows = ref<RunResult[]>([])

async function runWf() {
  if (!cvWfId.value) {
    if (!canvasNodes.value.length) {
      uiToast('画布为空，先添加节点', 'warn')
      return
    }
    await saveCanvas()
  }
  if (!cvWfId.value) return
  runBusy.value = true
  try {
    const { data } = await http.post<RunResp>(`/workflows/${cvWfId.value}/run`)
    runSummary.value = data.summary || `${data.passed}/${data.total} 通过`
    runRows.value = data.results || []
    runOpen.value = true
    await reload()
    uiToast('执行完成，结果已写入日志中心', 'success')
  } finally {
    runBusy.value = false
  }
}

const runColumns = [
  { key: 'name', label: '节点名称' },
  { key: 'type', label: '类型' },
  { key: 'status', label: '状态' },
  { key: 'dur', label: '耗时' },
]

/* ---------- 列表操作 ---------- */
async function runFromList(w: WfRow) {
  uiToast(`流程「${w.name}」开始执行…`, 'info')
  const { data } = await http.post<RunResp>(`/workflows/${w.id}/run`)
  runSummary.value = data.summary || `${data.passed}/${data.total} 通过`
  runRows.value = data.results || []
  runOpen.value = true
  await reload()
  uiToast('执行完成，结果已写入日志中心', 'success')
}

async function togglePub(w: WfRow) {
  const toPub = w.status === '草稿'
  const doIt = async () => {
    await http.put(`/workflows/${w.id}`, { status: toPub ? '已发布' : '草稿' })
    await reload()
    uiToast(toPub ? '流程已发布' : '已撤回为草稿', 'success')
  }
  if (toPub) {
    uiConfirm({
      title: '发布流程',
      message: `发布后「${w.name}」可被 Agent 与定时任务调用，确定发布？`,
      onOk: doIt,
    })
  } else {
    await doIt()
  }
}

function dropWf(w: WfRow) {
  uiConfirm({
    title: '删除流程',
    message: `确定删除「${w.name}」吗？引用它的定时任务将失效。`,
    onOk: async () => {
      await http.delete(`/workflows/${w.id}`)
      if (cvWfId.value === w.id) {
        cvWfId.value = null
        cvName.value = '未命名流程'
        canvasNodes.value = []
        canvasEdges.value = []
        selected.value = null
      }
      await reload()
      uiToast('流程已删除', 'success')
    },
  })
}

/* ---------- 新建流程 ---------- */
const newOpen = ref(false)
const newBusy = ref(false)
const nName = ref('')
const nDesc = ref('')

function openNew() {
  nName.value = ''
  nDesc.value = ''
  newOpen.value = true
}

async function createWf() {
  const n = nName.value.trim()
  if (!n) {
    uiToast('请填写流程名称', 'error')
    return
  }
  newBusy.value = true
  try {
    const { data } = await http.post<WfDetail>('/workflows', {
      name: n,
      description: nDesc.value || '—',
      status: '草稿',
      canvas: { nodes: [], edges: [] },
    })
    newOpen.value = false
    cvWfId.value = data.id
    cvName.value = data.name
    cvStatus.value = data.status
    canvasNodes.value = []
    canvasEdges.value = []
    selected.value = null
    await reload()
    uiToast('流程已创建，请添加节点', 'success')
  } finally {
    newBusy.value = false
  }
}
</script>

<template>
  <ModuleShell slug="tool-workflow-editor">
    <template #actions>
      <RouterLink class="btn btn-ghost" to="/t/tool-skills-center">🛠️ Skills 技能中心</RouterLink>
      <RouterLink class="btn btn-ghost" to="/t/tool-agent-center">🤖 Agent 中心</RouterLink>
      <button class="btn btn-primary" @click="openNew">＋ 新建流程</button>
    </template>

    <template #default="{ tab }">
      <div class="banner banner-info">
        ℹ️ 对应平台 WorkflowEditor 模块：节点类型来自<RouterLink to="/t/tool-skills-center">技能中心</RouterLink>与
        <RouterLink to="/t/tool-mcp-center">MCP 服务</RouterLink>；出边决定执行顺序（一个节点可有多条出边按序执行），流程发布后可被
        <RouterLink to="/t/tool-agent-center">Agent</RouterLink>与<RouterLink to="/t/tool-scheduler">定时任务</RouterLink>调用。
      </div>

      <!-- ============ 流程列表 ============ -->
      <template v-if="tab === 'list'">
        <div class="filter-bar">
          <input v-model="kw" class="input search" placeholder="🔍 搜索流程名称 / 描述" />
          <select v-model="statusF" class="select">
            <option value="">全部状态</option>
            <option>草稿</option>
            <option>已发布</option>
          </select>
          <button class="btn btn-ghost btn-sm" @click="resetFilter">重置</button>
        </div>
        <DataTable :columns="columns" :rows="filtered" empty-text="无匹配流程">
          <template #cell-id="{ row }">
            <span class="mono">{{ (row as WfRow).id }}</span>
          </template>
          <template #cell-name="{ row }">
            <div class="cell-main">{{ (row as WfRow).name }}</div>
            <div class="cell-sub">{{ (row as WfRow).desc }}</div>
          </template>
          <template #cell-nodes="{ row }">
            <span class="mono">{{ (row as WfRow).nodes }}</span>
          </template>
          <template #cell-runs="{ row }">
            <span class="mono">{{ (row as WfRow).runs }}</span>
          </template>
          <template #cell-status="{ row }">
            <span
              class="tag"
              :class="(row as WfRow).status === '已发布' ? 'tag-green' : 'tag-orange'"
            >{{ (row as WfRow).status }}</span>
          </template>
          <template #cell-created="{ row }">
            <span class="mono" style="font-size: 12px">{{ (row as WfRow).created }}</span>
          </template>
          <template #actions="{ row }">
            <div class="row-actions" style="opacity: 1">
              <button class="btn btn-sm btn-ghost" @click="loadToCanvas(row as WfRow)">画布</button>
              <button class="btn btn-sm btn-ghost" @click="runFromList(row as WfRow)">执行</button>
              <button class="btn btn-sm btn-ghost" @click="togglePub(row as WfRow)">
                {{ (row as WfRow).status === '草稿' ? '发布' : '撤回' }}
              </button>
              <button class="btn btn-sm btn-danger" @click="dropWf(row as WfRow)">删除</button>
            </div>
          </template>
        </DataTable>
      </template>

      <!-- ============ 可视化画布 ============ -->
      <template v-if="tab === 'canvas'">
        <div class="grid" style="grid-template-columns: 230px 1fr; gap: 14px">
          <div>
            <div class="card" style="padding: 14px">
              <div class="card-title" style="font-size: 13.5px">➕ 添加节点（点击追加）</div>
              <div style="display: flex; flex-direction: column; gap: 6px">
                <button
                  v-for="t in NT_KEYS"
                  :key="t"
                  class="btn btn-sm btn-ghost"
                  style="text-align: left; justify-content: flex-start"
                  @click="addNode(t)"
                >{{ NT[t].icon }} {{ NT[t].label }}节点</button>
              </div>
            </div>
            <div class="card mt-16" style="padding: 14px">
              <div class="card-title" style="font-size: 13.5px">🔗 出边顺序配置</div>
              <div class="text-faint" style="font-size: 11.5px; margin-bottom: 8px">选中节点后为其配置后续节点（按序执行）</div>
              <div style="display: flex; flex-direction: column; gap: 8px">
                <div v-if="!selected" class="text-faint" style="font-size: 12px">先选中画布中的节点</div>
                <template v-else>
                  <div style="font-size: 12.5px; font-weight: 600; margin-bottom: 6px">出边（按序）</div>
                  <div
                    v-for="(e, i) in edgeCurrent"
                    :key="e.key"
                    class="flex-between"
                    style="padding: 6px 10px; border: 1px solid var(--border); border-radius: 8px; font-size: 12.5px"
                  >
                    <span>{{ i + 1 }}. {{ e.name }}</span>
                    <button class="btn btn-sm btn-ghost" @click="removeEdge(e.key)">移除</button>
                  </div>
                  <select v-model="edgeAdd" class="select mt-8" @change="addEdge">
                    <option value="">＋ 添加出边…</option>
                    <option v-for="o in edgeTargets" :key="o.key" :value="o.key">{{ o.name }}</option>
                  </select>
                </template>
              </div>
            </div>
          </div>

          <div class="card" style="padding: 14px">
            <div class="flex-between mb-8">
              <div class="card-title" style="margin: 0; font-size: 13.5px">
                🎨 画布 · {{ cvName }}
                <span class="tag">{{ cvStatus }}</span>
              </div>
              <div class="flex">
                <button class="btn btn-sm btn-ghost" @click="clearCanvas">清空</button>
                <button class="btn btn-sm btn-success" :disabled="runBusy" @click="runWf">
                  <span v-if="runBusy" class="spinner"></span> ▶ 试运行
                </button>
                <button class="btn btn-sm btn-primary" @click="saveCanvas">💾 保存流程</button>
              </div>
            </div>
            <div
              style="
                min-height: 380px;
                border: 1.5px dashed var(--border);
                border-radius: 10px;
                padding: 14px;
                display: flex;
                flex-wrap: wrap;
                gap: 10px;
                align-content: flex-start;
                background: repeating-linear-gradient(45deg, transparent, transparent 12px, rgba(0, 0, 0, 0.015) 12px, rgba(0, 0, 0, 0.015) 24px);
              "
            >
              <template v-if="canvasNodes.length">
                <template v-for="n in canvasNodes" :key="n.key">
                  <div
                    class="cv-node"
                    style="
                      border: 1.5px solid var(--border);
                      border-radius: 10px;
                      padding: 10px 14px;
                      cursor: pointer;
                      background: #fff;
                      min-width: 130px;
                    "
                    :style="selected === n.key ? 'outline: 2px solid var(--primary); outline-offset: 2px;' : ''"
                    @click="selectNode(n.key)"
                  >
                    <div style="font-size: 18px">{{ NT[n.type]?.icon || '⚙️' }}</div>
                    <div style="font-size: 13px; font-weight: 700; margin-top: 4px">{{ n.name }}</div>
                    <div style="margin-top: 4px">
                      <span class="tag" :class="NT[n.type]?.cls" style="font-size: 10.5px">{{ NT[n.type]?.label || n.type }}</span>
                      <span v-if="edgesFrom(n.key).length" class="text-faint" style="font-size: 10.5px; margin-left: 4px">
                        → {{ edgesFrom(n.key).length }} 边
                      </span>
                    </div>
                  </div>
                  <div
                    v-if="edgesFrom(n.key).length"
                    style="align-self: center; color: var(--text-faint); font-size: 16px"
                  >→</div>
                </template>
              </template>
              <div v-else class="text-faint" style="padding: 40px; width: 100%; text-align: center">
                画布为空，从左侧点击节点类型添加
              </div>
            </div>
            <div class="text-faint mt-8" style="font-size: 11.5px">
              💡 点击节点选中（高亮），再次点击配置名称 / JSON；选中后可在左侧配置出边
            </div>
          </div>
        </div>
      </template>
    </template>
  </ModuleShell>

  <!-- 新建流程弹窗 -->
  <div class="modal-mask" :class="{ open: newOpen }">
    <div class="modal">
      <div class="modal-head">
        <h3>＋ 新建流程</h3>
        <button class="modal-close" @click="newOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="field">
          <label>流程名称 <span class="text-red">*</span></label>
          <input v-model="nName" class="input" placeholder="如：退款回归全链路" />
        </div>
        <div class="field">
          <label>描述</label>
          <input v-model="nDesc" class="input" placeholder="流程用途说明" />
        </div>
        <div class="hint">创建后进入画布添加节点与出边</div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="newOpen = false">取消</button>
        <button class="btn btn-primary" :disabled="newBusy" @click="createWf">
          <span v-if="newBusy" class="spinner"></span> 💾 创建并进入画布
        </button>
      </div>
    </div>
  </div>

  <!-- 节点配置弹窗 -->
  <div class="modal-mask" :class="{ open: nodeOpen }">
    <div class="modal">
      <div class="modal-head">
        <h3>{{ ndTitle }}</h3>
        <button class="modal-close" @click="nodeOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="field">
          <label>节点名称</label>
          <input v-model="ndName" class="input" placeholder="如：执行登录用例" />
        </div>
        <div class="field">
          <label>节点类型</label>
          <input v-model="ndType" class="input mono" readonly />
        </div>
        <div class="field">
          <label>配置 (JSON)</label>
          <textarea
            v-model="ndJson"
            class="textarea mono"
            rows="5"
            placeholder='{"skill": "AG-08", "params": {}}'
          ></textarea>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn btn-ghost" @click="nodeOpen = false">取消</button>
        <button v-if="ndDelShow" class="btn btn-danger" @click="delNode">删除节点</button>
        <button class="btn btn-primary" @click="saveNode">保存配置</button>
      </div>
    </div>
  </div>

  <!-- 执行结果弹窗 -->
  <div class="modal-mask" :class="{ open: runOpen }">
    <div class="modal modal-lg">
      <div class="modal-head">
        <h3>执行结果</h3>
        <button class="modal-close" @click="runOpen = false">✕</button>
      </div>
      <div class="modal-body">
        <div class="mb-16">
          <span class="tag tag-blue">{{ cvName }}</span>
          <span class="tag">{{ runRows.length }} 节点</span>
          <span class="tag tag-green">{{ runSummary }}</span>
        </div>
        <DataTable :columns="runColumns" :rows="runRows" :page-size="20" empty-text="无节点结果">
          <template #cell-name="{ row }">{{ (row as RunResult).name }}</template>
          <template #cell-type="{ row }">
            <span class="tag" :class="NT[(row as RunResult).type]?.cls">{{ NT[(row as RunResult).type]?.label || (row as RunResult).type }}</span>
          </template>
          <template #cell-status="{ row }">
            <span class="tag" :class="(row as RunResult).status === '成功' ? 'tag-green' : 'tag-red'">{{ (row as RunResult).status }}</span>
          </template>
          <template #cell-dur="{ row }">
            <span class="mono">{{ (row as RunResult).dur }}</span>
          </template>
        </DataTable>
      </div>
      <div class="modal-foot">
        <RouterLink class="btn btn-ghost" to="/t/tool-log-center">📜 查看日志中心</RouterLink>
        <button class="btn btn-primary" @click="runOpen = false">关闭</button>
      </div>
    </div>
  </div>
</template>
