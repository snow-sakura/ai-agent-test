<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { TOOL_CATALOG, type ToolDef } from '@/data/catalog'
import { useApp, type HubTabKey } from '@/stores/app'

/* 工具台门户首页内容：TAB 分类 + 卡片直达（对照 UI/app.html）
   顶栏由 PortalLayout / AppTopBar 提供；分组 tab 共享 app.hubTab */
const route = useRoute()
const router = useRouter()
const app = useApp()

type TagDef = [string, string?] // [label, color?]
interface HubCard {
  slug: string
  title: string
  icon: string
  sub: string
  tags: TagDef[]
  isNew: boolean
  href: string
}

/* 本地附加：标签 + NEW 徽标（app.html G 数据，catalog 不含这些字段） */
const EXTRAS: Record<string, { tags: TagDef[]; isNew?: boolean }> = {
  'tool-requirement-management': { tags: [['AI 解析', 'red'], ['追溯矩阵', 'green']] },
  'tool-test-cases': { tags: [['AI 生成', 'red'], ['会话精修']] },
  'tool-case-management': { tags: [['模块树'], ['评审', 'orange']] },
  'tool-defect-management': { tags: [['状态流转'], ['AI 查重', 'red']] },
  'tool-knowledge-base': { tags: [['RAG', 'red'], ['经验沉淀']], isNew: true },
  'tool-api-scenario-studio': { tags: [['编排画布', 'blue'], ['JMX 导出']] },
  'tool-performance-testing': { tags: [['基线对比', 'blue'], ['AI 分析', 'red']] },
  'tool-api-testing': { tags: [['集合管理', 'blue'], ['断言']] },
  'tool-security-testing': { tags: [['基线', 'purple'], ['AI 修复', 'red']] },
  'tool-pentest-testing': { tags: [['PTES', 'purple'], ['AI 向量', 'red']] },
  'tool-ui-automation': { tags: [['步骤编排', 'blue'], ['录像回放']] },
  'tool-app-automation': { tags: [['设备池', 'purple'], ['流水线']] },
  'tool-ai-assistant': { tags: [['RAG', 'red'], ['技能匹配']], isNew: true },
  'tool-skill-library': { tags: [['AI 调用', 'red'], ['版本管理']], isNew: true },
  'tool-skills-center': { tags: [['Agent', 'red'], ['MCP 绑定']], isNew: true },
  'tool-agent-center': { tags: [['AI 编队', 'red'], ['任务执行']], isNew: true },
  'tool-workflow-editor': { tags: [['画布', 'purple'], ['节点编排']], isNew: true },
  'tool-ai-reports': { tags: [['AI 生成', 'red'], ['PDF 导出']], isNew: true },
  'tool-root-cause': { tags: [['置信度', 'purple'], ['AI 溯源', 'red']], isNew: true },
  'tool-token-usage': { tags: [['计量', 'green'], ['费用核算', 'red']], isNew: true },
  'tool-deai-flavor': { tags: [['策略', 'green'], ['AI 对比', 'red']], isNew: true },
  'tool-config-center': { tags: [['多模型', 'blue'], ['连接测试']], isNew: true },
  'tool-scheduler': { tags: [['Cron', 'purple'], ['通知推送']], isNew: true },
  'tool-mcp-center': { tags: [['市场', 'blue'], ['连通测试']], isNew: true },
  'tool-log-center': { tags: [['审计', 'blue'], ['导出']], isNew: true },
  'tool-data-factory': { tags: [['测试数据', 'green'], ['AI 造景', 'red']], isNew: true },
  'tool-media-data-hub': { tags: [['JSON', 'green'], ['本地处理']] },
}

function toCard(def: ToolDef): HubCard {
  const ex = EXTRAS[def.slug]
  return {
    slug: def.slug,
    title: def.title,
    icon: def.icon,
    sub: def.sub,
    tags: ex?.tags ?? [],
    isNew: !!ex?.isNew,
    href: '/t/' + def.slug,
  }
}

const PROMPTS_CARD: HubCard = {
  slug: 'prompts',
  title: '提示词库',
  icon: '📚',
  sub: '集中存放可复用提示词，按场景分类、搜索与一键复制到 Cursor / Agent。',
  tags: [['分类', 'orange'], ['一键复制']],
  isNew: false,
  href: '/prompts',
}

const GROUP_KEYS: readonly HubTabKey[] = ['manage', 'exec', 'ai', 'plat']

const GROUP_LABELS: Record<HubTabKey, string> = {
  manage: '📐 测试管理',
  exec: '⚡ 测试执行',
  ai: '🤖 AI 中心',
  plat: '🧰 平台与数据',
}

/* 分组归属（与 app.html G 一致）；提示词库插入 manage 组 */
const GROUP_SLUGS: Record<HubTabKey, string[]> = {
  manage: [
    'tool-requirement-management',
    'tool-test-cases',
    'tool-case-management',
    'tool-defect-management',
    'tool-knowledge-base',
  ],
  exec: [
    'tool-api-scenario-studio',
    'tool-performance-testing',
    'tool-api-testing',
    'tool-security-testing',
    'tool-pentest-testing',
    'tool-ui-automation',
    'tool-app-automation',
  ],
  ai: [
    'tool-ai-assistant',
    'tool-skill-library',
    'tool-skills-center',
    'tool-agent-center',
    'tool-workflow-editor',
    'tool-ai-reports',
    'tool-root-cause',
    'tool-token-usage',
    'tool-deai-flavor',
  ],
  plat: [
    'tool-config-center',
    'tool-scheduler',
    'tool-mcp-center',
    'tool-log-center',
    'tool-data-factory',
    'tool-media-data-hub',
  ],
}

function buildGroup(key: HubTabKey): HubCard[] {
  const cards: HubCard[] = []
  for (const slug of GROUP_SLUGS[key]) {
    const def = TOOL_CATALOG.find((t) => t.slug === slug)
    if (def) cards.push(toCard(def))
  }
  if (key === 'manage') {
    // 与 app.html 一致：提示词库排在缺陷管理之后
    const idx = cards.findIndex((c) => c.slug === 'tool-defect-management')
    cards.splice(idx >= 0 ? idx + 1 : cards.length, 0, PROMPTS_CARD)
  }
  return cards
}

const groups = GROUP_KEYS.map((key) => ({
  key,
  label: GROUP_LABELS[key],
  cards: buildGroup(key),
}))

const counts = Object.fromEntries(groups.map((g) => [g.key, g.cards.length])) as Record<
  HubTabKey,
  number
>

/* 共享 store：跨路由保留分组 tab；?tab= 与 store 双向同步 */
const activeTab = computed(() => app.hubTab)

watch(
  () => route.query.tab,
  (v) => {
    const s = String(v || '')
    if (GROUP_KEYS.includes(s as HubTabKey)) {
      app.setHubTab(s as HubTabKey)
    }
  },
  { immediate: true },
)

/* 离开 /app 时把当前 tab 写回 query，返回时恢复 */
watch(activeTab, (v) => {
  if (route.path === '/app' && route.query.tab !== v) {
    void router.replace({ query: { ...route.query, tab: v } })
  }
})

function clickTab(key: HubTabKey) {
  app.setHubTab(key)
  void router.replace({ query: { ...route.query, tab: key } })
}

const paneCards = computed(() => groups.find((g) => g.key === activeTab.value)?.cards ?? [])

function openCard(c: HubCard) {
  void router.push(c.href)
}
</script>

<template>
  <!-- 门户首页内容：无侧栏；TAB 分类功能模块，点击卡片进入对应工作台 -->
  <div class="container page hub">
    <div class="hub-head">
      <div>
        <h1>☀️ Solar Grove · AITest 工具台</h1>
        <div class="sub">按 TAB 分类浏览功能模块，点击任意卡片进入对应工作台。</div>
      </div>
      <div class="flex">
        <RouterLink class="btn btn-ghost" to="/">🏠 返回官网首页</RouterLink>
        <RouterLink class="btn btn-primary" to="/t/tool-test-cases">✨ 打开 AI 测试用例</RouterLink>
      </div>
    </div>

    <!-- 统计条 -->
    <div class="grid grid-4 mb-16">
      <div class="card stat-card">
        <div class="s-label">可用工具入口</div>
        <div class="s-value">{{ TOOL_CATALOG.length }}</div>
        <div class="s-trend text-faint">覆盖需求到缺陷全链路与平台治理</div>
      </div>
      <div class="card stat-card">
        <div class="s-label">本月生成用例</div>
        <div class="s-value" style="color:var(--green)">248</div>
        <div class="s-trend text-green">↑ 18% 环比上月</div>
      </div>
      <div class="card stat-card">
        <div class="s-label">执行成功率</div>
        <div class="s-value" style="color:var(--blue)">94.6%</div>
        <div class="s-trend text-faint">UI / App / 接口近 30 天</div>
      </div>
      <div class="card stat-card">
        <div class="s-label">AI 助手调用</div>
        <div class="s-value" style="color:var(--orange)">1,204</div>
        <div class="s-trend text-faint">解析 / 生成 / 修复建议合计</div>
      </div>
    </div>

    <!-- TAB 分类 -->
    <div class="tabs hub-tabs">
      <button
        v-for="g in groups"
        :key="g.key"
        class="tab"
        :class="{ active: activeTab === g.key }"
        type="button"
        @click="clickTab(g.key)"
      >{{ g.label }}<span class="badge-count">{{ counts[g.key] }}</span></button>
      <span class="hint">点击卡片进入工作台 →</span>
    </div>

    <!-- 卡片面板 -->
    <div class="tab-pane active">
      <div class="grid grid-tools">
        <div
          v-for="c in paneCards"
          :key="c.slug"
          class="card card-hover tool-card"
          role="button"
          tabindex="0"
          @click="openCard(c)"
          @keydown.enter="openCard(c)"
        >
          <span v-if="c.isNew" class="tc-badge-new">NEW</span>
          <div class="tc-icon">{{ c.icon }}</div>
          <h3>{{ c.title }}</h3>
          <p>{{ c.sub }}</p>
          <div class="tc-tags">
            <span
              v-for="(t, ti) in c.tags"
              :key="ti"
              class="tag"
              :class="t[1] ? 'tag-' + t[1] : ''"
            >{{ t[0] }}</span>
          </div>
          <div class="tc-foot">
            <a class="tc-enter" :href="c.href" @click.prevent.stop="openCard(c)">打开 →</a>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
