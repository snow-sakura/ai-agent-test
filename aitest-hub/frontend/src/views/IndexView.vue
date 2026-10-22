<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

/* 官网首页内容：Hero + Mega 导航 + 照片墙 + 模块 + 流程 + CTA + 页脚
   顶栏由 PortalLayout / AppTopBar 提供 */
const openIdx = ref(-1)

function onMegaEnter(i: number) {
  openIdx.value = i
}
function onMegaLeave() {
  openIdx.value = -1
}
function onMegaBtn(i: number, e: MouseEvent) {
  e.stopPropagation()
  openIdx.value = openIdx.value === i ? -1 : i
}
function closeAllMega() {
  openIdx.value = -1
}

function scrollToFeatures() {
  document.getElementById('features')?.scrollIntoView({ behavior: 'smooth' })
}

onMounted(() => document.addEventListener('click', closeAllMega))
onBeforeUnmount(() => document.removeEventListener('click', closeAllMega))
</script>

<template>
  <!-- ====== Hero：天空视觉 ====== -->
  <section class="home-hero">
    <div class="sky-sun"></div><div class="sky-ring r1"></div><div class="sky-ring r2"></div>
    <span class="deco d1">🌿</span><span class="deco d2">🧪</span><span class="deco d3">🤖</span><span class="deco d4">📱</span>
    <div class="container inner">
      <div class="brandline">AI TEST HUB · 测试与质量工具聚合平台</div>
      <h1>把测试工作<span class="hl">拍成一叠拍立得</span><br>每一张都是可复用的资产</h1>
      <p class="sub" style="max-width:640px; margin:18px auto 26px; color:var(--text-dim); font-size:16px">
        可视化压测、AI 用例、接口测试、用例与缺陷管理、UI / App 自动化、提示词库与工具箱——九大模块，浏览器打开即用。
      </p>
      <div class="hero-actions">
        <RouterLink class="btn btn-primary btn-lg" to="/auth">免费开始使用 →</RouterLink>
        <RouterLink class="btn btn-ghost btn-lg" to="/register">注册新账号</RouterLink>
        <a class="btn btn-ghost btn-lg" href="#features" @click.prevent="scrollToFeatures">浏览能力模块 ↓</a>
      </div>
      <div class="flex mt-24" style="justify-content:center; gap:22px; color:var(--text-faint); font-size:12.5px">
        <span>✅ 无需安装</span><span>✅ 个人免费</span><span>✅ 数据本地</span><span>✅ 9 大模块</span>
      </div>
    </div>
  </section>

  <!-- ====== Mega 导航：三组分类 + 提示词库 ====== -->
  <section class="container" style="padding:26px 0 4px">
    <div class="meganav">
      <div
        class="m-group"
        :class="{ open: openIdx === 0 }"
        @mouseenter="onMegaEnter(0)"
        @mouseleave="onMegaLeave"
        @click.stop
      >
        <button class="m-btn" type="button" @click="onMegaBtn(0, $event)">🧪 测试执行 <span style="font-size:10px">▾</span></button>
        <div class="m-panel">
          <RouterLink to="/app?tab=manage"><span class="mi">📋</span>需求管理</RouterLink>
          <RouterLink to="/app?tab=exec"><span class="mi">🎛️</span>压测编排工作台</RouterLink>
          <RouterLink to="/app?tab=exec"><span class="mi">🚀</span>性能测试</RouterLink>
          <RouterLink to="/app?tab=exec"><span class="mi">🔗</span>接口测试</RouterLink>
          <RouterLink to="/app?tab=exec"><span class="mi">🖱️</span>UI 自动化</RouterLink>
          <RouterLink to="/app?tab=exec"><span class="mi">📱</span>App 自动化</RouterLink>
        </div>
      </div>
      <div
        class="m-group"
        :class="{ open: openIdx === 1 }"
        @mouseenter="onMegaEnter(1)"
        @mouseleave="onMegaLeave"
        @click.stop
      >
        <button class="m-btn" type="button" @click="onMegaBtn(1, $event)">🤖 AI 与资产 <span style="font-size:10px">▾</span></button>
        <div class="m-panel">
          <RouterLink to="/app?tab=manage"><span class="mi">✨</span>AI 用例工作台</RouterLink>
          <RouterLink to="/app?tab=manage"><span class="mi">🗂️</span>用例管理</RouterLink>
          <RouterLink to="/app?tab=manage"><span class="mi">🐞</span>缺陷管理</RouterLink>
        </div>
      </div>
      <div
        class="m-group"
        :class="{ open: openIdx === 2 }"
        @mouseenter="onMegaEnter(2)"
        @mouseleave="onMegaLeave"
        @click.stop
      >
        <button class="m-btn" type="button" @click="onMegaBtn(2, $event)">🧰 效率工具 <span style="font-size:10px">▾</span></button>
        <div class="m-panel">
          <RouterLink to="/app?tab=plat"><span class="mi">🖼️</span>媒体与数据工具箱</RouterLink>
          <RouterLink to="/app?tab=plat"><span class="mi">🏭</span>数据工厂</RouterLink>
          <RouterLink to="/prompts"><span class="mi">📚</span>提示词库</RouterLink>
          <RouterLink to="/app?tab=ai"><span class="mi">🧩</span>技能库</RouterLink>
          <RouterLink to="/app?tab=ai"><span class="mi">💬</span>AI 问答助手</RouterLink>
          <RouterLink to="/app?tab=plat"><span class="mi">⚙️</span>配置中心</RouterLink>
          <RouterLink to="/app?tab=plat"><span class="mi">⏰</span>定时任务</RouterLink>
          <RouterLink to="/app?tab=plat"><span class="mi">🔌</span>MCP 服务中心</RouterLink>
          <RouterLink to="/app?tab=ai"><span class="mi">🛠️</span>Skills 技能中心</RouterLink>
          <RouterLink to="/app?tab=ai"><span class="mi">🧽</span>去 AI 味中心</RouterLink>
          <RouterLink to="/app?tab=manage"><span class="mi">📚</span>知识库</RouterLink>
          <RouterLink to="/app?tab=plat"><span class="mi">📜</span>日志中心</RouterLink>
          <RouterLink to="/app?tab=ai"><span class="mi">🔀</span>工作流编排</RouterLink>
          <RouterLink to="/app?tab=ai"><span class="mi">🤖</span>Agent 中心</RouterLink>
          <RouterLink to="/app?tab=ai"><span class="mi">📊</span>AI 报告中心</RouterLink>
          <RouterLink to="/app?tab=ai"><span class="mi">🔍</span>根因分析</RouterLink>
          <RouterLink to="/t/tool-token-usage"><span class="mi">🪙</span>Tokens 消费记录</RouterLink>
        </div>
      </div>
      <RouterLink class="btn btn-ghost" to="/prompts">✨ 提示词库</RouterLink>
      <RouterLink class="btn btn-ghost" to="/app">📊 进入工具台</RouterLink>
    </div>
  </section>

  <!-- ====== 拍立得照片墙 ====== -->
  <section class="container" style="padding:30px 0 10px">
    <div class="photo-wall">
      <div class="polaroid tilt-l"><span class="tape"></span><div class="p-photo">🧪</div><div class="p-caption">压测编排</div></div>
      <div class="polaroid tilt-r"><span class="tape tape-red"></span><div class="p-photo">🤖</div><div class="p-caption">AI 用例</div></div>
      <div class="polaroid tilt-l"><span class="tape tape-blue"></span><div class="p-photo">🔗</div><div class="p-caption">接口测试</div></div>
      <div class="polaroid tilt-r"><span class="tape"></span><div class="p-photo">🐞</div><div class="p-caption">缺陷管理</div></div>
      <div class="polaroid tilt-l"><span class="tape tape-right"></span><div class="p-photo">📱</div><div class="p-caption">App 自动化</div></div>
    </div>
  </section>

  <!-- ====== 功能模块 ====== -->
  <section class="section container" id="features">
    <h2 class="section-title">九大能力模块</h2>
    <p class="section-sub">覆盖测试设计 → 执行 → 管理 → 分析全流程</p>
    <div class="grid grid-3">

      <div class="card card-hover feature-card">
        <div class="f-num">01 · LOAD ORCHESTRATION</div>
        <h3>🧪 可视化压测编排</h3>
        <p>拖拽式编排测试计划、线程组与 HTTP 请求，自动生成 JMX；对接 InfluxDB + Grafana 实时观测 QPS、RT 与错误率。</p>
        <div class="mt-8"><span class="tag">测试计划</span> <span class="tag">JMX 导出</span> <span class="tag">批量造数</span></div>
        <RouterLink class="f-link" to="/app?tab=exec">打开压测工作台 →</RouterLink>
      </div>

      <div class="card card-hover feature-card">
        <div class="f-num">02 · AI CASES</div>
        <h3>🤖 AI 需求转用例</h3>
        <p>粘贴需求文档，AI 生成结构化可执行测试用例；支持会话精修、智能改写与附件上下文，需求到用例一条流水线。</p>
        <div class="mt-8"><span class="tag">需求解析</span> <span class="tag">流式生成</span> <span class="tag">会话精修</span></div>
        <RouterLink class="f-link" to="/app?tab=manage">打开 AI 用例工作台 →</RouterLink>
      </div>

      <div class="card card-hover feature-card">
        <div class="f-num">03 · API TESTING</div>
        <h3>🔗 接口测试</h3>
        <p>接口集合管理、参数化断言、环境变量切换、用例编排串行/并行执行；AI 辅助生成断言与 Mock 数据。</p>
        <div class="mt-8"><span class="tag">集合管理</span> <span class="tag">环境变量</span> <span class="tag">断言</span></div>
        <RouterLink class="f-link" to="/app?tab=exec">打开接口测试 →</RouterLink>
      </div>

      <div class="card card-hover feature-card">
        <div class="f-num">04 · CASE MANAGEMENT</div>
        <h3>🗂️ 用例管理</h3>
        <p>模块树 + 用例库双视图，评审流程、批次执行与结果统计；与 AI 生成、缺陷管理双向关联。</p>
        <div class="mt-8"><span class="tag">模块树</span> <span class="tag">评审</span> <span class="tag">执行批次</span></div>
        <RouterLink class="f-link" to="/app?tab=manage">打开用例管理 →</RouterLink>
      </div>

      <div class="card card-hover feature-card">
        <div class="f-num">05 · DEFECTS</div>
        <h3>🐞 缺陷管理</h3>
        <p>缺陷全生命周期流转，严重等级与优先级矩阵、重复缺陷 AI 检测、关联用例与执行记录。</p>
        <div class="mt-8"><span class="tag">状态流转</span> <span class="tag">AI 查重</span> <span class="tag">关联追溯</span></div>
        <RouterLink class="f-link" to="/app?tab=manage">打开缺陷管理 →</RouterLink>
      </div>

      <div class="card card-hover feature-card">
        <div class="f-num">06 · OMNIFLOW UI</div>
        <h3>🖱️ 可视化 UI 自动化</h3>
        <p>填写目标 URL，用自然语言步骤搭场景；服务器无头执行，运行后查看截图、录像，进入运行记录与回放。</p>
        <div class="mt-8"><span class="tag">步骤编排</span> <span class="tag">截图录像</span> <span class="tag">运行回放</span></div>
        <RouterLink class="f-link" to="/app?tab=exec">打开 UI 自动化 →</RouterLink>
      </div>

      <div class="card card-hover feature-card">
        <div class="f-num">07 · APP AUTOMATION</div>
        <h3>📱 App 自动化</h3>
        <p>Android · ADB/Appium 设备管理、应用包管理、自动化脚本与执行流水线，边缘设备接入与定时任务。</p>
        <div class="mt-8"><span class="tag">设备管理</span> <span class="tag">ADB / Appium</span> <span class="tag">执行流水线</span></div>
        <RouterLink class="f-link" to="/app?tab=exec">打开 App 自动化 →</RouterLink>
      </div>

      <div class="card card-hover feature-card">
        <div class="f-num">08 · PROMPT LIBRARY</div>
        <h3>📚 实战提示词库</h3>
        <p>按场景分类浏览模板，一键复制到 Cursor / Agent 即用。覆盖测试设计、缺陷分析、接口与自动化等高频场景。</p>
        <div class="mt-8"><span class="tag">分类筛选</span> <span class="tag">一键复制</span> <span class="tag">Agent 就绪</span></div>
        <RouterLink class="f-link" to="/prompts">浏览提示词库 →</RouterLink>
      </div>

      <div class="card card-hover feature-card">
        <div class="f-num">09 · TOOLKIT</div>
        <h3>🧰 媒体与数据工具箱</h3>
        <p>图片压缩、格式转换、音频生成，以及 JSON 格式化、Base64、文本 Diff、时间戳、URL 编解码，一页集齐。</p>
        <div class="mt-8"><span class="tag">JSON</span> <span class="tag">Diff</span> <span class="tag">时间戳</span></div>
        <RouterLink class="f-link" to="/app?tab=plat">打开工具箱 →</RouterLink>
      </div>

    </div>
  </section>

  <!-- ====== 工作流 ====== -->
  <section class="section container">
    <h2 class="section-title">三步开始你的第一场测试</h2>
    <p class="section-sub">零代码，像整理一叠照片一样管理测试资产</p>
    <div class="grid grid-3">
      <div class="polaroid tilt-l"><span class="tape"></span>
        <div class="p-photo" style="height:130px">✍️</div>
        <div class="p-caption">STEP 1 · 设计用例</div>
      </div>
      <div class="polaroid"><span class="tape tape-blue"></span>
        <div class="p-photo" style="height:130px">▶️</div>
        <div class="p-caption">STEP 2 · 执行观测</div>
      </div>
      <div class="polaroid tilt-r"><span class="tape tape-red"></span>
        <div class="p-photo" style="height:130px">📒</div>
        <div class="p-caption">STEP 3 · 管理追溯</div>
      </div>
    </div>
    <div style="text-align:center" class="mt-24">
      <RouterLink class="btn btn-primary btn-lg" to="/app?tab=exec">立即体验压测编排 →</RouterLink>
    </div>
  </section>

  <!-- ====== CTA ====== -->
  <section class="section container">
    <div class="card" style="text-align:center; padding:44px 20px; background:linear-gradient(135deg, rgba(224,104,90,.10), rgba(217,142,43,.10))">
      <h2 style="font-size:26px">准备好提升测试效率了吗？</h2>
      <p class="text-dim mt-8">九大能力一页集齐，浏览器打开即用，个人学习与日用免费。</p>
      <div class="flex mt-16" style="justify-content:center">
        <RouterLink class="btn btn-primary btn-lg" to="/auth">登录 / 注册</RouterLink>
        <RouterLink class="btn btn-ghost btn-lg" to="/prompts">先看提示词库</RouterLink>
      </div>
    </div>
  </section>

  <footer class="footer">
    <div class="container">
      <div>© 2026 AITest Hub · AI 驱动的测试平台（演示环境）</div>
      <div class="flex">
        <RouterLink to="/">首页</RouterLink>
        <RouterLink to="/app">工具台</RouterLink>
        <RouterLink to="/app?tab=exec">接口测试</RouterLink>
        <RouterLink to="/prompts">提示词库</RouterLink>
        <RouterLink to="/auth">登录</RouterLink>
        <RouterLink to="/register">注册</RouterLink>
      </div>
    </div>
  </footer>
</template>
