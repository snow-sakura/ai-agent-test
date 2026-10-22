# 技术文档 · 架构 / 序列调度器 / 流式看门狗 / 档位打通

> 对应代码：`backend/app/`（FastAPI + SQLite）与 `frontend/src/views/tools/`（Vue 3）

## 1. 总体架构

```text
┌────────────────────────── Browser (Vue3 SPA, frontend/dist) ─────────────────────────┐
│  tool-test-cases.vue          tool-config-center.vue          其余 30+ 工具页          │
│  ├ SSE 流式生成 + 120s 看门狗   ├ 计费档位下拉(🆓/💎)            （ModuleShell 统一外壳）  │
│  └ 序列页签 + 时间线轮询(2s)    └ PUT /config/ai → 全量同步      │
└──────────────┬───────────────────────┬───────────────────────────────────────────────┘
               │ /api/case-generator/** │ /api/config/**  /api/gen-queue/**
┌──────────────▼───────────────────────▼──────────── FastAPI (app/main.py) ────────────┐
│  流式生成端点：_iter_idle_timeout(75s) + max_tokens=4096 + 终止帧兜底                    │
│  静态托管：mount("/") + exception_handler SPA history fallback                         │
├───────────────────────────────────────────────────────────────────────────────────────┤
│  api/gen_queue.py ──► services/gen_queue.py（进程内 asyncio Worker）                    │
│                        ├ decide_schedule：free→serial/1；paid→parallel/N(Semaphore)     │
│                        ├ _run_sequence：顺序 for / gather + Semaphore                   │
│                        └ _execute_item：独立 DB 连接 + ai.chat + parse + 演示兜底        │
│  services/ai.py：统一 AI 调用（cfg_kv 优先）+ _sync_cfg_models_to_ai_configs（全量 upsert）│
│  services/ai_parse.py：结构化解析 + 截断自动修复        core/database.py：SQLite 迁移     │
└───────────────────────────────────────────────────────────────────────────────────────┘
                                   SQLite：backend/app/aitest_hub.db（.gitignore）
```

单进程自托管：FastAPI 同源托管 `frontend/dist` 与 `/uploads`，无 Redis/消息队列依赖；
序列 Worker 为进程内 `asyncio.create_task`，状态持久化到 SQLite，进程重启自动置「已中断」。

## 2. 数据模型

### 2.1 gq_sequences（序列）
| 列 | 说明 |
|----|------|
| id | `SQ-YYYYMMDD-HHMMSS-xxx` |
| title / module | 序列标题 / 业务域（用例=case） |
| model_id / model_name / tier | 解析后的模型与计费档位（提交时定档，后续改配置不影响已提交序列） |
| mode / concurrency | `serial`/`parallel` 与生效并发数 |
| status | 排队中 / 执行中 / 已完成 / 部分失败 / 全部失败 / 已取消 / 已中断 |
| total / done_cnt / fail_cnt | 进度计数（持久回写，前端直接渲染） |
| items | JSON 数组：`{idx,name,payload,status,cases,summary,error,started_at,finished_at}` |
| created_by | 登录用户名或 guest |

### 2.2 ai_configs.tier 迁移
`init_db_sync` 与 `ensure_ready` 双保险执行
`ALTER TABLE ai_configs ADD COLUMN tier TEXT DEFAULT 'free'`（捕获重复列异常，幂等）。

### 2.3 cfg_kv.ai_models（配置中心为唯一编辑源）
每项含 `tier`；保存时 `_sync_cfg_models_to_ai_configs` **全量启用模型按 name upsert** 到
ai_configs（修复早期只同步默认模型导致非默认档位/Key 不生效的问题）。

## 3. 序列调度器（services/gen_queue.py）

### 3.1 调度决策（纯函数，便于测试）
```python
def decide_schedule(tier, task_count, settings):
    if tier == "paid":
        n = clamp(settings["paid_concurrency"], 1, 8)   # 默认 3
        return {"mode": "parallel", "concurrency": n, ...}
    return {"mode": "serial", "concurrency": 1, ...}     # 免费：串行保护额度
```

### 3.2 Worker 生命周期
1. `create_sequence`：`resolve_model`（ai_configs → cfg_kv 回退）定档 → 落库（items 初始「等待中」）。
2. `start_sequence(sid)`：`_RUNNING` 去重，单序列单 worker。
3. `_run_sequence`：
   - 置「执行中」，`Semaphore(concurrency)`；
   - serial：顺序 for；parallel：`gather(*[guarded(it)...])`；
   - `_execute_item` **自建独立 DB 连接**（SyncDB 单 cursor，并行共享会串号）；
   - 每任务完成即 `persist_lock` 下整包 items JSON + 计数回写（轮询可见增量进度）；
   - 每步检查取消标记；`演示模式` 文本 → 内置演示用例兜底；
   - 终态：done==total→已完成；部分→部分失败；0→全部失败。
4. `cancel_sequence`：未开始/执行中 → items 置「已取消」+ 运行中 task.cancel()。
5. `retry_failed`：失败/已取消项重置「等待中」重新入队（复用原 worker 入口）。
6. `ensure_ready` 一次性修复：进程重启把遗留「执行中」置「已中断」（仅启动时一次，
   避免每请求误伤正在跑的序列）。

### 3.3 API（api/gen_queue.py，/api/gen-queue/*）
预览 / 设置 / 提交 / 列表 / 详情 / 取消 / 重试（见 README 速览）。
写操作与 case-generator 一致：允许匿名，`created_by` 记 guest。

## 4. 流式可靠性（main.py + ai.py）

### 4.1 服务端停滞看门狗
```python
async def _iter_idle_timeout(aiter, seconds=75.0):   # 包任意异步迭代器
    # 每次 __anext__ 用 asyncio.wait_for 包裹；超时 yield _IDLE_MARK
```
- SSE 生成用例：`reasoning/content` 透传；收到 `_IDLE_MARK` → 用已累积内容做
  `parse_generated_cases` 截断修复，发 `done`（成功，标注自动修复）或 `error` 终止帧。
- 统一服务流（/ai/stream）：同一看门狗。
- 请求默认 `max_tokens=4096`；`finish_reason=length` 记录截断日志。
- 空流（模型只回思维链）→ error 终止帧，绝不静默挂死。

### 4.2 客户端（tool-test-cases.vue）
- `AbortController` + 120s 静默计时（每 chunk 重置）：底层连接假死时前端自救，
  报错并保留已生成内容。
- 缺 `done` 帧的流被明确提示「未收到完成信号」，引导改用序列生成。

### 4.3 截断修复（services/ai_parse.py）
- 尝试 ```json 块 → 裸数组 → 逐对象括号配对扫描；
- 不闭合尾对象丢弃/尽力收敛，成功项照常入库，summary 标注「已自动修复」。

## 5. 档位打通链路

```text
配置中心下拉 ⇄ cfg_kv.ai_models[i].tier
     │ PUT /config/ai（config_center 调 sync）
     ▼
ai_configs(name UNIQUE, tier)          ← ensure_ready 亦会补列
     │ resolve_model(model_id|默认)     ← 生成与调度唯一入口
     ▼
gen_queue.decide_schedule → serial/1 或 parallel/N
case-generator/models → 前端 🆓/💎 徽标
```

## 6. SPA 静态托管与 history 回退

- `mount("/uploads")` 先于 `mount("/")`（防被兜底吞掉）。
- `exception_handler(StarletteHTTPException)`：404 + GET/HEAD + 非 `/api|/uploads` +
  `Accept: text/html` → `FileResponse(index.html)`；其余保持 JSON detail
  （API 404 语义如「序列不存在」不受影响）。

## 7. 前端实现要点（tool-test-cases.vue）

- 页签：`genTab single|seq` 复用 ModuleShell；序列面板与单条面板互斥渲染。
- 调度预览：`watch(seqModelId, 任务数)` 300ms 防抖 GET `scheduling-preview`；
  paid 自动把并发步进器同步为默认值。
- 轮询：提交后 800ms 首查、2s 递归 setTimeout；终态自动停止并 toast；
  `onUnmounted` 清理，防路由切换泄漏。
- 载入用例表：`items.flatMap(cases)` 续接现有编号 TC-xxxx 合并进表，
  与单条生成/会话精修共享同一编辑/导出链路。

## 8. 部署与运行

```bash
# 后端（首次自动建库+种子）
cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010
# 前端同源托管
cd frontend && npm run build          # dist/ 由 FastAPI "/" 挂载
# 开发
VITE_API_TARGET=http://127.0.0.1:8010 npm run dev
# 演示辅助：每序列任务加固定延迟，便于观察时间线推进
GQ_ITEM_DELAY=1.5 uvicorn app.main:app ...
```

测试钩子：`GQ_ITEM_DELAY`（秒）；校验脚本 `scripts/`（check-api、e2e-interaction 等）。

## 9. 已知边界

- Worker 在单进程内存：多副本部署需改外置队列（当前定位单机自托管）。
- `--reload` 重启会丢执行中任务 → 已用「已中断 + retry-failed」兜底。
- 并行只对 paid 放开；免费并发保护额度是产品策略而非技术上限。
