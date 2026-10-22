# SPEC · aitest-hub 2026-10 迭代：生成可靠性修复 + 序列调度 + 纯 GitHub 演示

> 状态：执行中 ｜ 作者：build-agent ｜ 日期：2026-10-19
> 推进方式：Loop Engineering（每模块实现 → 浏览器实测 → 截图 → 发现问题即修 → 通过后进入下一模块）

---

## 1. 需求背景（PRD 摘要）

### 1.1 用户痛点
1. **生成结果"不是没有成功就是缺失"**：AI 用例等生成任务经常转圈无结果、或结束时没有结构化数据。
2. 无法按模型付费档位区分执行策略：免费模型并发跑会限流/失败，付费模型串行跑浪费时间。
3. 前端缺少"按序列循环"的过程可视化，批量任务无法追踪每条结果。
4. 文档缺失、仓库有大量测试产物、未接入 GitHub、缺少可直接打开的在线演示。

### 1.2 根因定位（实测证据）
| # | 问题 | 证据 | 结论 |
|---|------|------|------|
| R1 | SSE 流式生成无终止帧 | 实测 `/api/case-generator/generate/stream`：输出 1756 个 content 块、4246 字后模型停滞，90s 内无 `done`/`error` 帧，前端永远"生成中" | 慢模型 + 无 max_tokens 兜底 + 无流停滞看门狗 |
| R2 | 截断 JSON 无挽救 | 停滞时 JSON 恰好中断在对象中部，直接路径无空闲超时→不触发截断修复 | 需 idle-timeout 后走 `_parse_generated_cases` 截断修复 |
| R3 | 非流式 AI 静默降级 | `services/ai.py` 固定 120s 超时，慢模型结构化输出（≥90s）易超时→返回 mock 文本，用户感知"结果缺失" | 超时提至可配置，重试保留，降级文案须醒目标注 |
| R4 | 无序列调度能力 | 全站无批量任务队列；模型配置无免费/付费档位概念 | 本期新增 |

## 2. 功能需求

### F1 生成结果修复（缺陷）
- A1 生成流默认 `max_tokens=4096`，可被请求覆盖。
- A2 流式停滞看门狗：连续 75s 无新块 → 主动收敛，用已有内容做截断修复。
- A3 终止帧兜底：任何路径（成功/截断/失败/取消）必须发出且只发出一次 `done` 或 `error`。
- A4 捕获 `finish_reason=length` → summary 注明"达到输出上限已自动修复"。
- A5 非流式超时 120s→180s；降级 mock 的提示语必须显著（现有逻辑保留 + 文案强化）。
- A6 前端：SSE 读流结束但没有 `done` 帧时，展示已捕获片段并提示重试，不再无限转圈；前端 100s 无数据主动断开。

### F2 生成序列调度（新能力）
- B1 模型档位：AI 模型新增 `tier: free|paid`（配置中心可编辑；默认 free）。
- B2 调度规则：
  - `free` 模型 → **单任务序列**（并发=1，任务按提交顺序串行执行）；
  - `paid` 模型 → **并行序列**（并发 N，默认 3，可配置 1~8；`asyncio.Semaphore` 控制）。
- B3 序列 API：提交（批量任务）、列表、详情（含每条状态/结果）、取消、重试失败项、调度预览（选定模型后实时显示"单任务/并行 N"）。
- B4 执行器：复用统一 AI 服务（重试/计量/降级一致），结果结构化解析失败时保留原始文本与错误。
- B5 状态持久化 SQLite，服务重启后未完成任务标记"已中断"可重试。

### F3 前端显示优化（循环按序列）
- C1 用例生成工具新增「🔁 序列生成」页签：批量任务输入（一行一条）、调度模式徽标、垂直序号时间线（01/02/03…，排队→执行中→成功/失败）、进度条、单任务结果展开查看/载入用例表、取消/重试失败。
- C2 单条生成会话增加阶段步骤条（解析需求→调用模型→结构化→写入表格），实时反映当前阶段。
- C3 配置中心 AI 模型卡片增加 免费/付费 档位标签与编辑项；付费模型显示"可并行"，免费显示"串行保护"。

### F4 演示与交付
- D1 `demo/`：纯 GitHub 托管的静态演示（GitHub Pages，域名全部 github.io）：复刻"序列调度+免费/付费策略"交互；数据记录用 localStorage + 通过 GitHub raw 读取仓库内 JSON 种子数据（完全 GitHub 实现，无第三方后端）。
- D2 README.md：全流程文档，每步骤含主标题/副标题/文字/截图；附 demo 直达链接。
- D3 docs/：需求文档、技术文档、操作说明。
- D4 清理测试产物（截图/日志/缓存/旧版本目录），隐私配置不入库（.gitignore：.env、*.db、密钥、uploads）。
- D5 创建公开仓库 snow-sakura/aitest-hub 并推送，开启 GitHub Pages。

## 3. 技术方案

### 3.1 架构
```
frontend (Vue3+Vite)                backend (FastAPI + sqlite3)
┌─────────────────────┐   /api    ┌───────────────────────────────────┐
│ tool-test-cases      │──────────▶│ main.py  ├─ case-generator stream │
│  ├ 单条生成(SSE)      │           │          │  + idle watchdog       │
│  └ 序列生成(轮询)      │◀──────────│          └ config/roles...        │
│ tool-config-center   │           │ services/                         │
│  └ tier 档位编辑       │           │  ai.py(超时/max_tokens/重试)       │
│ demo/ 纯静态 Pages    │           │  ai_parse.py(结构化解析)  ← new    │
└─────────────────────┘           │  gen_queue.py(序列调度器) ← new    │
                                   │ api/gen_queue.py(REST)   ← new    │
                                   └───────────────────────────────────┘
```

### 3.2 序列调度器（gen_queue）
- 表 `gq_sequences(id TEXT PK, title, module, model_id, tier, mode, concurrency, status, total, done_cnt, fail_cnt, items TEXT, error, created_at, started_at, finished_at)`；
  `items` JSON：`[{idx,name,payload,status,cases,summary,error,started_at,finished_at}]`。
- 提交时按所选模型 `tier` 定档：free→mode=serial,concurrency=1；paid→mode=parallel,concurrency=min(N,任务数)。
- Worker：`asyncio.create_task(_run_sequence)`；自有 sqlite 连接；serial 顺序 for；parallel 用 Semaphore+gather；每个任务完成即回写 items JSON（前端轮询可见）。
- 取消：置 `status=已取消` + 任务间检查 + `task.cancel()` 兜底。
- 执行器注册表：本期仅 `case`（用例生成，prompt 与单条生成一致）；payload 预留 `module` 扩展。

### 3.3 流式看门狗
```python
async def _iter_idle_timeout(ait, idle_s):
    it = ait.__aiter__()
    while True:
        try:
            yield await asyncio.wait_for(it.__anext__(), timeout=idle_s)
        except StopAsyncIteration:
            return
        except asyncio.TimeoutError:
            yield _IDLE_MARK  # 上层 break → 进入截断修复
```

### 3.4 档位打通
- cfg_kv.ai_models 增 `tier`；`_sync_cfg_models_to_ai_configs` 同步至 ai_configs（`ALTER TABLE ADD COLUMN tier DEFAULT 'free'`）。
- `/case-generator/models` 与 `/gen-queue/scheduling-preview` 返回 tier 与生效调度。

### 3.5 Demo（纯 GitHub）
- 单文件 `demo/index.html`（无构建、无外部依赖）：配置中心（模型+档位）→ 序列生成（免费=串行模拟 1.2s/任务；付费=并行 3 路）→ 时间线渲染 → 数据记录 localStorage；`demo/data/seed.json` 通过 `https://raw.githubusercontent.com/snow-sakura/aitest-hub/main/demo/data/seed.json` 拉取种子记录 —— 数据读写全链路 GitHub（Pages + raw）。

## 4. 任务拆解与验收（Loop 清单）

| 序 | 任务 | 验收 | Loop 验证 |
|----|------|------|-----------|
| T1 | 后端流式修复（A1-A5） | 慢模型下 90s 内必有终止帧；中断可修复出用例 | curl SSE + 浏览器 |
| T2 | gen_queue 服务+API（B） | 提交 3×</b>免费→串行、付费→并发3；状态可查/可取消 | curl 轮询 |
| T3 | 前端序列页签+档位（C） | 时间线按序列渲染；免费/付费徽标正确 | Playwright 截图 |
| T4 | 全流程回归 | 9 大工具首页无报错；生成→载入→编辑闭环 | Playwright 逐页 |
| T5 | demo/ + Pages | 线上 URL 可交互记录数据 | 浏览器实测 |
| T6 | 文档 + README(截图) | 全流程步骤齐 | 人工核对 |
| T7 | 清理 + .gitignore + 建库推送 | 仓库无密钥/无产物；Pages 生效 | gh/SSH |

## 5. 风险与对策
- AMD 云免费模型限速(R1)：串行 + 重试已有；并行仅对 paid 放开。
- Worker 与 uvicorn --reload 交互：reload 会丢内存任务 → 重启置"已中断"（B5）。
- gh token 失效：推送走 SSH；建库需交互凭据时向用户申请 PAT。
- 隐私：ai_configs 表含真实 Key → *.db 全部 .gitignore；种子数据仅占位符。

---

## 6. 执行记录（2026-10-21 · Loop 验收完成）

### T1 流式修复 ✅
- 实测：AMD 真实模型全量 SSE（--max-time 150）正常结束，输出完整结构化用例 JSON（curl exit=0）；
  后端 75s 停滞看门狗 + max_tokens=4096 + 终止帧兜底全部生效。
- 前端补充：120s 客户端停滞看门狗（AbortController）；缺 done 帧时明示"未收到完成信号"并保留已生成内容。

### T2 序列调度 ✅（curl 实测）
- free → serial/1（时间窗严格串行）；paid → parallel/3（前 3 项同时启动）；取消/重试/预览/设置全部通过。

### T3 前端 ✅（Playwright 实测 + 截图 docs/images/seq-0*.png）
- 用例工作台新增「序列生成」页签：每行一任务、模型下拉带 🆓/💎 徽标、调度预览（➡️ 串行 / 🔀 并行 N 路）、
  付费并发步进器（1-8）、右侧实时时间线（序号 + 状态 chip + 进度条）、2s 轮询、取消 / 重试失败 / 载入用例表。
- 配置中心「计费档位」下拉（free=单任务序列 / paid=并行序列），保存即同步调度策略。
- 实测对照：免费序列（真实 AMD 模型）3/3 成功 → 45 条载入用例表（约 4 分钟，真实推理）；
  付费序列（演示模型）3 任务同时执行中 → 约 3 秒完成——并行加速肉眼可见。

### 执行中新发现并修复
- `ai.py::_sync_cfg_models_to_ai_configs`：原只同步默认模型一条 → 改为全部启用模型按 name upsert，
  修复非默认模型 tier/Key 不生效问题（通义 Qwen-Plus / GPT-4o 现为 💎 paid，可在序列中选择）。
- `main.py` SPA history fallback：/auth、/t/xxx 等前端路由刷新/直链 404 → 非 API 的浏览器导航请求
  回退 index.html 由前端路由接管；API 404 保留原 detail（实测 /auth 刷新 200、API 404 语义不变）。
- 登录页支持手机号或用户名；演示账号取 `DEMO_ACCOUNT` / `DEMO_PASSWORD`（默认 `13800000000` / `Demo@2026`），由 `GET /api/config/demo-account` 提供给登录页。

### 验收截图清单（docs/images/）
| 图 | 内容 |
|----|------|
| seq-01 | 单条生成模型下拉 tier 徽标（🆓/💎） |
| seq-02 | 序列面板免费串行预览（➡️ 单任务序列） |
| seq-03 | 免费序列执行中时间线（真实 AMD） |
| seq-04 | 免费序列完成 3/3（真实 AI 生成） |
| seq-05 | 序列结果载入用例表 |
| seq-06 | 💎 付费 3 路并行同时执行 |
| seq-07 | 付费并行完成（约 3s vs 串行 4min） |
| seq-08 | 配置中心「计费档位」下拉 |
