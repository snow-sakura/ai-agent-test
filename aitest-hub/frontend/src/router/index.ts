import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { TOOL_CATALOG } from '@/data/catalog'
import { useAuth } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: () => import('@/layouts/PortalLayout.vue'),
    children: [
      {
        path: '',
        name: 'home',
        component: () => import('@/views/IndexView.vue'),
        meta: {
          public: true,
          title: 'AITest Hub — AI 驱动的测试与质量工具聚合平台',
        },
      },
      {
        path: 'app',
        name: 'cards',
        component: () => import('@/views/AppCardsView.vue'),
        meta: { title: '工具台首页 — AITest Hub' },
      },
    ],
  },
  {
    path: '/auth',
    name: 'auth',
    component: () => import('@/views/AuthView.vue'),
    meta: { public: true, title: '登录 — AITest Hub' },
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/views/RegisterView.vue'),
    meta: { public: true, title: '注册 — AITest Hub' },
  },
  {
    path: '/prompts',
    component: () => import('@/layouts/WorkspaceLayout.vue'),
    children: [
      {
        path: '',
        name: 'prompts',
        component: () => import('@/views/PromptsView.vue'),
        meta: { title: '提示词库 — AITest Hub' },
      },
    ],
  },
  {
    path: '/t/:slug',
    name: 'tool',
    component: () => import('@/views/ToolView.vue'),
  },
  { path: '/:pathMatch(.*)*', redirect: '/app' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach((to) => {
  const auth = useAuth()
  if (!to.meta.public && !auth.isLogin()) {
    return '/auth?redirect=' + encodeURIComponent(to.fullPath)
  }
  return true
})

router.afterEach((to) => {
  const slug = to.params.slug as string | undefined
  const def = slug ? TOOL_CATALOG.find((t) => t.slug === slug) : null
  if (def) {
    document.title = def.title + ' — AITest Hub'
    return
  }
  document.title =
    (typeof to.meta.title === 'string' && to.meta.title) || 'AITest Hub'
})

export default router
