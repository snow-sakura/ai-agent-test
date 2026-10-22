# 功能验证发现的页面缺陷

> 来源：`scripts/verify-features.mjs` 全量功能验证（35 模块 / 1053 项），
> 报告：`.playwright-mcp/features-verify.json` → `jsErrors` 字段。
> 记录时间：2026-09-28（第二轮全量复验：2026-09-29）
>
> **当前状态：BUG-01 ✅ / BUG-02 ✅（根因=BUG-01 次生）/ BUG-03 ✅ / BUG-04 ✅ / BUG-05 ✅（含第二轮加固）/ BUG-06 ✅ / BUG-07 ✅ / BUG-08 ✅ / BUG-09 ✅**
> 最终报告（两轮一致）：PASS 941 + PASS-EXIST 93 + SKIP 19 = 1053，**FAIL 0、MISSING 0、jsErrors {}**。

## BUG-01 tool-scheduler：`Cannot read properties of undefined (reading 'smtp')`

- **验证模块**：`tool-config-center`（早期报告曾误挂 `tool-scheduler`——按"当时正在
  验证的模块"归属；验证器已于 2026-09-29 改为按当前 URL 归属，见 BUG-02 实证段）
- **错误**：`TypeError: Cannot read properties of undefined (reading 'smtp')`
- **定位**：`frontend/src/views/tools/tool-config-center.vue:548`

```html
<input v-model="notifyChannel('email')!.smtp" class="input mono" />
```

- **根因**：`notifyChannel('email')` 在渠道数据未就绪/未匹配到 `email` 渠道时返回
  `undefined`，TypeScript 的 `!` 非空断言只在编译期生效，运行时仍读取
  `undefined.smtp` 抛错。
- **修复建议**：v-model 改为可选链 + 兜底，例如
  `v-model="(notifyChannel('email') ?? { smtp: '' }).smtp"`，或在模板外先
  `computed` 保证渠道对象存在。
- **修复状态**：✅ **已修复（2026-09-28）**——新增 `emailChannel()`
  （`tool-config-center.vue`）：真实渠道存在返回之，否则返回本地占位对象
  （不写入列表，`loadAll` 到达后自然替换）；4 处 v-model（smtp/port/from/auth）
  改用 `emailChannel()`。`vue-tsc -b` 通过，复验 config-center 43 项全绿且无 jsError。

## BUG-02 tool-scheduler：`Cannot destructure property 'type' of 'vnode' as it is null`

- **验证模块**：`tool-scheduler`
- **错误**：`TypeError: Cannot destructure property 'type' of 'vnode' as it is null.`
- **定位**：Vue 运行时 `patch` 对前一子树（`instance.subTree`）解构
  `type` 时该值为 null——**系 BUG-01 render 异常导致 subTree 未建立的次生
  崩溃**（详见下方修复状态的机制分析），并非 `<component :is>`/动态插槽
  类问题（已逐层排查排除：`ModuleShell → ToolLayout` 无动态组件/KeepAlive，
  scheduler 模板 v-for 均有 key）。
- **修复状态**：✅ **已定位并根治（2026-09-29）——本错误是 BUG-01 的确定性次生崩溃，
  非独立缺陷**。
  - **证据**：全部 19 份历史日志中 vnode 与 smtp **100% 成对出现**，无一例孤立；
    `/tmp/vf-run19.log`（唯一带本轮增量标记 `jsErr=2` 的日志）证明两错误在
    **同一轮 scheduler 运行内成对新增**（performance `jsErr=1` 对应 BUG-03，
    归属互不混淆）。
  - **机制解释**：BUG-01 的 v-model getter `notifyChannel('email').smtp` 在
    **render 期间**抛错（notify 数据未返回且直开 `?tab=notify` 时触发）→
    首次 render 失败后组件 vdom 状态不完整，后续响应式更新/路由导航触发
    重渲染时 patch 前一子树为 null → 对其解构 `type` →
    "Cannot destructure property 'type' of 'vnode' as it is null"。
    故 smtp 存在时 vnode 为**确定性次生**——已由下方回退实验证实。
  - **验证（2026-09-29 实证复现，因果闭环）**：
    1. **正向**：BUG-01 修复在位时，两轮全量验证 + scheduler/config-center
       多次单模块重跑，**jsErrors 均为 `{}`，vnode 零复现**；
    2. **反向（回退实验）**：临时把 `tool-config-center.vue:565` 回退为
       `v-model="notifyChannel('email')!.smtp"`，跑原始触发路径
       `node scripts/verify-features.mjs --only tool-scheduler` →
       **`jsErr=2`：smtp 与 vnode 成对复现**，且指标模式
       （`PASS=24 EXIST=3 SKIP=5`）与历史 `/tmp/vf-run19.log` 完全一致；
    3. 还原修复后复跑 scheduler+config-center 共 75 项全绿、jsErrors `{}`。
    复现工具保留于 `scripts/repro-bug02.mjs`（冷加载直跳 `?tab=notify` +
    notify API 延迟 800ms，可独立复现 smtp 半边）。
  - **验证器归属修复（2026-09-29，同轮完成）**：`pageerror` 原按"创建页时的
    modId 闭包"归属——SPA 导航后过期，config-center 的 render 错误被误挂
    scheduler。已改为**按当前 URL pathname 归属**（`routeToMod` 唯一路由映射，
    `(shell)` 共享路由退回 modId），并把 jsErrors 增量基线从单模块改为全
    map 快照（否则跨模块错误被汇总丢弃）。A/B 检验（回退态重跑）：
    `{"tool-config-center":[smtp], "tool-scheduler":[vnode]}` 归属正确、
    `jsErr=2` 无丢失；还原后复跑两模块 jsErrors 归零 `{}`。
  - **保留的额外保险**（无害）：`tool-scheduler.vue` 卸载守卫 `disposed`——
    初版（09-28）检查误置于 `Promise.all` 之后（拦截不到赋值，无效）；
    09-29 已修正为各 `loadXxx` 与 `saveTask/runTask/toggleTask/delTask`
    的 `await` 之后、**赋值之前**检查。

## BUG-03 tool-performance-testing：`Error: 报告不存在`（HTTP 404）

- **验证模块**：`tool-performance-testing`
- **错误**：`Error: 报告不存在`
- **来源**：`backend/app/api/performance.py:438 / :457`
  （`raise HTTPException(status_code=404, detail="报告不存在")`）
- **性质**：前端点击「查看/下载报告」类入口时，目标报告记录不存在
  （数据依赖：报告需先跑压测生成）。
- **修复建议**：
  1. 前端对 404 做兜底 toast（「报告尚未生成，请先执行压测」），避免未捕获异常；
  2. 无报告时禁用/隐藏入口按钮（与 conditional-data 渲染策略一致）。
- **修复状态**：✅ **已修复（2026-09-28）**——`tool-performance-testing.vue`：
  1. `runAi` 增加空报告守卫（无报告不发请求，直接提示先执行压测）；
  2. `runAi` 增加 `catch`（404 等错误 toast 兜底，不再成为未捕获异常）；
  3. 顺手为「删除场景」的 `http.delete` 补 catch 防御。
  复验 performance 34 项全绿、jsError 未再现。

## BUG-04 tool-defect-management：`case` 字段恒空（列名读错），关联用例链接永不渲染

- **验证模块**：`tool-defect-management`（`#29 详情弹窗「🔗 {case}」`、列表「关联用例」列、编辑表单 fdCase 预填）
- **现象**：`GET /api/bugs` 返回的每条记录 `case` 恒为 `""`，
  即使 DB 中 `dm_defects.case_id` 已有值（如 `BUG-2044 → TC-1009`）→
  前端 `view.case` 恒空 → 详情弹窗「🔗 关联用例」链接（`v-if="view.case"`）永不渲染
  → 功能验证项 `tool-defect-management#29` 恒 MISSING（已排除数据/定位原因）。
- **定位**：`backend/app/api/bug_management.py:101`
  ```python
  "case": r.get("case", ""),      # ← 表列名是 case_id，这里读 "case" 恒 miss
  ```
  建表 DDL 为 `case_id TEXT DEFAULT ''`（同文件 `CREATE TABLE dm_defects`），
  POST 创建时也写入 `case_id`（`"case_id": body.case`，约 :404），
  仅 list/dto 映射处读错了键名。
- **影响面**：
  1. 详情弹窗「🔗 关联用例」（`tool-defect-management#29`）恒不渲染；
  2. 列表「关联用例」列 `v-if="(row as Bug).case"` 恒空；
  3. 编辑表单 `fdCase = x.case`（:257）回显恒空 → 编辑保存会把已有 case_id 冲掉（次生风险）。
- **修复建议**（一行）：
  ```python
  "case": r.get("case_id", ""),
  ```
  同时建议检查其它 dto 复用处（`GET /bugs/{id}` 若复用同一映射则一并生效）。
- **修复状态**：✅ **已修复（2026-09-28）**
  - `backend/app/api/bug_management.py:101` 已改为 `r.get("case_id", "")`；
  - 后端已重启（uvicorn PID 10486，改 py 必须重启才生效）；
  - `curl GET /api/bugs` 确认 `case:'TC-1009'` 等 6 行非空；
  - `node scripts/verify-features.mjs --only tool-defect-management` 复验
    **#29 PASS**，defect 模块 FAIL/MISSING 归零。
- **验证方式**：
  ```bash
  curl -s localhost:8000/api/bugs -H "Authorization: Bearer $TOKEN" \
    | python3 -c "import sys,json;r=json.load(sys.stdin)[0];print(r['case'])"   # 修复前恒为空
  node scripts/verify-features.mjs --only tool-defect-management               # #29 修复后应 PASS
  ```

## BUG-05 verify-features（验证器基础设施）：headless browser 中途退出导致整批 FAIL

- **验证模块**：无（验证器自身缺陷，非被测页面问题）
- **错误**：`browserContext.newPage: Target page, context or browser has been closed`
- **现象**：全量回归途中 headless Chromium 进程无预兆退出，此后**同批全部特征项
  连锁 FAIL**（一次波及 176 项，报告被大面积污染）。
- **根因**：8GB 内存机器高内存压力下 headless 进程被终止（无 macOS 崩溃报告，
  非确定性——同一模块单独重跑即正常）；验证器 `browser` 为顶层单例且**无
  disconnected 监听/重建逻辑**，一次退出即全批失效。
- **修复（自愈机制）**：
  1. `browser` / `authedCtx` / `guestCtx` 由 `const` 改 `let`；
  2. 新增 `recoverBrowser()`：检测到断开 → 关旧实例 → 重 launch + 重建双
     context（重放 token initScript）→ 清空 `pageCache`；
  3. `getPage` 改为收 `isGuest` 布尔（每次用最新全局 ctx），入口先
     `if (!browser.isConnected()) await recoverBrowser()`；
  4. 崩溃后**下一个特征项自动恢复**，损失收敛为崩溃当项（可通过重跑该模块补齐）。
- **操作要求**：大批次（≥4 重模块）回归受 8GB 内存压力影响，建议**每批 ≤2-3 个
  重模块**或分模块串行跑；崩溃发生后无需人工干预，直接重跑受影响模块即可。
- **验证方式**：`grep recover /tmp/vf-run*.log`（自愈触发时打印
  `[recover] browser disconnected → relaunch`）。
- **第二轮加固（2026-09-29）**——第二轮全量验证中 browser 中途退出高频复现，
  补测确认系统根因为 **swap 90%+ 打满（4646/5120MB）触发内核回收杀
  chromium**（`sysctl vm.swapusage`），自愈基础上再加四道防线：
  1. `recoverBrowser()`：`browser.close()` 竞速 8s 超时 + `finally` 复位
     `_recovering`——根治 close 悬挂导致整轮永久卡死（曾致单批 300s+ 无输出）；
  2. **单项 90s 超时**：Phase1/Phase2 特征循环体分别包
     `Promise.race(featureBody, 90000ms)`，超时记
     `FAIL feature-timeout(90s)` 并继续下一项——根治未知 await 悬挂拖死整轮；
  3. `VERIFY_OK` 后 `process.exit(0)`——根治验证完成后进程挂起、shell 超时
     丢日志（表现为"有报告无 VERIFY_OK"）；
  4. 大批次改用 `nohup ... &` 后台跑 + 轮询日志，规避 shell 超时截断。
  加固后 9 批全量验证中 browser 死亡均被 recover 收敛为当项损失，重跑即全绿。

## BUG-06 verify-features（验证器数据依赖）：PRE 硬编码主键随数据增长掉出首页

- **验证模块**：`tool-pentest-testing#9`（首轮曾 MISSING）
- **错误**：`MISSING`——PRE 后目标元素不在当前页，条件断言无法触发。
- **根因**：PRE SQL 硬编码 `WHERE id='PTC-139'`，而列表 `ORDER BY id DESC` +
  `pageSize=10`，新增用例（现首页为 PTC-164~155）把目标行挤出第一页；
  隐患相同：`requirement-management#10` 等硬编码 RM-* 亦然。
- **修复状态**：✅ **已修复（2026-09-29）**——PRE/restore 改为动态子查询：
  ```sql
  UPDATE pt_cases SET ... WHERE id=(SELECT id FROM pt_cases ORDER BY id DESC LIMIT 1)
  ```
  即"最新一条"语义，与页面默认排序一致，数据增长不再失效。
- **验证方式**：`node scripts/verify-features.mjs --only tool-pentest-testing`
  → 32 项全绿（31 PASS + 1 EXIST），无 MISSING。

## BUG-07 序列生成：取消序列后「重试失败任务」按钮永不出现（`fail_cnt` 未回写）

- **验证模块**：`tool-test-cases` · 序列生成时间线（需求 B3「支持取消、只重试失败任务」）
- **现象**：执行中点「⏹ 取消序列」→ 时间线任务项变为 `⊘ 已取消`，但底部只有状态标签，
  **「🔁 重试失败任务」按钮不渲染**，已取消任务在 UI 上无法重试（后端 `retry-failed` 其实是认「已取消」的）。
- **定位**：`backend/app/services/gen_queue.py: cancel_sequence()` 只更新
  `status / items / finished_at`，未更新 `fail_cnt`；前端
  `tool-test-cases.vue:416` 用 `fail_cnt > 0`作為按钮渲染条件。
- **根因**：`fail_cnt` 只有执行器 `persist_items()` 会写，取消路径绕过了它 →
  计数口径分叉（取消写状态、执行器写计数），取消后 `fail_cnt` 恒为 0。
- **修复状态**：✅ **已修复（2026-10-22）**——`cancel_sequence` 落库前按执行器同一口径
  重算并写入 `done_cnt / fail_cnt`；同时给 `persist_items()` 加终态保护：序列已是「已取消」时
  不再回写，避免 worker 用内存里的旧状态把 `已取消` 覆盖回 `等待中`（取消与回写的竞态）。
- **验证方式**：3 任务序列执行中取消 → `fail_cnt=3`、按钮出现在 UI；
  点重试 → `排队中 → 执行中`，计数自动归零重新累计；取消后静置 4s 复核状态未被覆盖。

## BUG-08 序列生成：「已中断」序列实际无法重试（B5 只做了标记、没做可重试）

- **验证模块**：`tool-test-cases` · 序列生成（需求 B5「重启后遗留执行中自动置已中断，可重试」）
- **现象**：`kill -9` 后端再重启 → 序列状态变「已中断」，但任务项仍显示 `🔄 执行中 / ⏳ 等待中`，
  进度停在 `0/2（✅0 ❌0）`，「重试失败任务」按钮不显示；即便直接调接口也是空操作。
- **定位**：`gen_queue.py: ensure_ready()` 只对序列表做
  `SET status='已中断'`，未处理 `items` JSON；`retry_failed()` 的重置集合只有
  `("失败", "已取消")`。前端 `itemChip()` 早已支持 `已中断 → ⚠️`，但该状态从不产生。
- **根因**：收尾逻辑漏了任务项与计数：`fail_cnt=0` → 按钮隐藏；`reset=0` → `retry_failed`
  直接 return，「可重试」这半边从未生效。
- **修复状态**：✅ **已修复（2026-10-22）**——抽取统一口径常量
  `_FAIL_STATUSES = ("失败", "已取消", "已中断")`，`ensure_ready` 收尾时把遗留的
  `等待中/执行中` 任务项归一为 `已中断` 并重算 `done_cnt/fail_cnt`；
  `retry_failed`、`persist_items`、终态判定、取消序列四处统一改用该常量，杜绝再次分叉。
- **验证方式**：UI 提交 2 任务序列 → 执行中 `kill -9` → 重启 → 时间线自动变
  `⚠️ 已中断` ×2、进度 `2/2（✅0 ❌2）`、按钮出现 → 点重试 → `执行中` 且计数归零。

## BUG-09 登录页：无手机号的账号（seed `admin`）永远无法登录

- **验证模块**：`/auth` 登录页（发布前去敏感化复查时连带发现）
- **现象**：以种子管理员 `admin`（`phone` 为 NULL）登录时，前端直接判为格式错误、
  请求根本不发出；而同账号直接打 `POST /api/auth/login` 返回 200。
- **定位**：`frontend/src/views/AuthView.vue:70` 校验 `/^1\d{10}$/`（仅 11 位手机号），
  后端是 `SELECT * FROM users WHERE username=? OR phone=?`——前端比后端严，
  且字段 label 写的是「手机号 / 账号」，三者互相矛盾。
- **根因**：产品按手机号优先设计，登录校验照抄注册页的手机号规则，
  没有为「用户名账号」（seed 管理员、脚本账号）留出口。
- **修复状态**：✅ **已修复（2026-10-22）**——登录校验放开为
  `/^1\d{10}$/` 或 `/^[A-Za-z0-9_.-]{3,50}$/`，错误文案同步为
  「请输入 11 位手机号或 3-50 位账号」；注册页保持手机号唯一（未改）。
- **验证方式**：`admin/admin123` 与演示账号 `13800000000` 均 HTTP 200；
  UI「一键填充 → 登录」实测落到 `/app` 且 `/api/auth/me` 返回演示用户。

## BUG-10 序列生成：刷新页面后执行中/已中断序列时间线丢失

- **验证模块**：`tool-test-cases` · 序列生成时间线（需求 B3/B5「取消、中断后可重试」）
- **现象**：后端已能正确把序列置为 `已中断` / `已取消`，但刷新页面后右侧时间线消失，
  「重试失败任务」按钮也随之丢失；用户只能重新提交任务，无法找回刚才的执行序列。
- **定位**：前端只在 `startSeq()` / `cancelSeq()` / `retrySeq()` 成功后设置 `seq.value`，
  页面 `onMounted()` 不会从 `GET /api/gen-queue/sequences` 接回当前/历史序列。
- **根因**：序列状态持久化在后端 SQLite，但 UI 时间线仅保存在内存中，缺少历史入口。
- **修复状态**：✅ **已修复（2026-10-22）**——`tool-test-cases.vue` 新增「最近序列」面板；
  进入页面拉取最近 8 条序列；若存在 `排队中/执行中` 序列自动接回并继续 polling；
  终态序列可通过「查看」重新打开时间线，并显示取消/重试/载入按钮。
- **验证方式**：Vue 构建通过；浏览器访问 `/t/tool-test-cases` → 序列生成页显示历史列表；
  点击进入 `已中断` 序列 → 时间线恢复 `2/2（✅0 ❌2）`，「🔁 重试失败任务」按钮出现。

## 复现方式

```bash
node scripts/verify-features.mjs --only tool-scheduler,tool-performance-testing
# 查看 .playwright-mcp/features-verify.json → jsErrors
```
