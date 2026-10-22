# CHANGELOG

## 2026-10-22

### 发布前去敏感化（公开仓库前置）
- **个人凭据出库**：`[REDACTED_PHONE] / [REDACTED_PASSWORD]` 这类真实手机号+口令原硬编码在 `README`、`UI/*`、`backend/app/main.py` 种子、登录页与 7 个验证脚本里（共 13 个文件）。现统一改为环境变量 `DEMO_ACCOUNT` / `DEMO_PASSWORD` / `ADMIN_PASSWORD`，默认中性演示账号 `13800000000 / Demo@2026`；个人账号写进 `backend/.env`（已 gitignore，新增 `.env.example` 模板，`config.py` 启动即 `load_dotenv`）。
- **前端不再内置账号口令**：新增公开接口 `GET /api/config/demo-account`（`DEMO_ACCOUNT_PUBLIC=0` 可关闭），Vue 登录页与静态原型 `UI/` 的「一键填充」改为运行时向后端索取，展示时掩码。
- **BUG-09** 登录页无法登录无手机号账号：表单校验 `/^1\d{10}$/` 比后端（`username OR phone`）更严，label 却写着「手机号 / 账号」——seed 出来的 `admin`（phone 为空）根本进不去。放开为「11 位手机号或 3-50 位账号」，注册页仍保持手机号唯一。
- 清理 `__pycache__` 内含旧凭据的字节码；`scripts/*.mjs` 凭据改为 `process.env` 回退，`node --check` 全通过。

### 缺陷修复（序列生成调度）
- **BUG-07** 取消序列后「重试失败任务」按钮永不出现：`cancel_sequence` 只改 `status/items/finished_at`，未回写 `fail_cnt`，而前端按钮渲染条件是 `fail_cnt > 0` → 已取消任务在 UI 上无法重试。修复：取消落库前按执行器同口径重算 `done_cnt/fail_cnt`；并给 `persist_items()` 加「已取消」终态保护，消除 worker 用内存旧状态把 `已取消` 覆盖回 `等待中` 的竞态。
- **BUG-08** 「已中断」序列实际无法重试（B5 只做了标记）：`ensure_ready()` 仅 `SET status='已中断'`，遗留 `等待中/执行中` 任务项未归一、计数未更新，且 `retry_failed()` 重置集合不含 `已中断` → 按钮隐藏且接口空操作。修复：收尾时任务项归一为 `已中断`（前端 `itemChip` 早已支持 ⚠️）并重算计数；抽出统一口径常量 `_FAIL_STATUSES = (失败, 已取消, 已中断)`，`retry_failed / persist_items / 终态判定 / cancel_sequence` 四处共用。
- **BUG-10** 刷新页面后序列时间线丢失：后端状态已持久化，但前端只在提交/取消/重试成功后设置 `seq.value`，刷新后无法重新打开执行中/已中断/已取消序列，导致刚修复的重试入口再次被 UI 隐藏。修复：序列生成页挂载时拉取最近 8 条序列，自动接回 `排队中/执行中` 序列；新增「最近序列」面板，终态序列可点击查看时间线并继续重试/载入。

### 验证（浏览器实测 + 接口实测）
- C2/C3 UI 实拍：免费串行时间线（🔄/⏳ chip + 总进度）、取消 → `⊘ 已取消` ×2 + 按钮出现 → 重试 → `执行中` 计数归零 → 完成 `2/2（✅2 ❌0）` → 「载入用例表（36 条）」跨任务合并（148 → 184，编号 TC-1149…TC-1184 无冲突）。截图 `docs/images/seq-10-cancel-retry.png`。
- B5：UI 提交后 `kill -9` 后端再重启 → 时间线自动转 `⚠️ 已中断` ×2、进度 `2/2（✅0 ❌2）`、按钮出现、点重试恢复执行。
- F1 看门狗：本地 SSE 桩「回 1 块后彻底停滞」注入 → **75.03s** 精确收敛，`reasoning` 提示截断修复 + **必有 `done` 终止帧**（不留悬挂流）；连接被拒场景 5s 内返回 `error` 终止帧。
- D1 纯静态演示（GitHub Pages 形态）本地实测：串行 3 任务 4.6s vs 付费 3 路并行 2s、并发步进器 1-8、模拟失败 → `部分失败` + 重试按钮、localStorage 记录持久化。截图 `docs/images/seq-11-demo-parallel.png`。
- 未闭环：D5 GitHub Pages 线上地址——远端仓库 `snow-sakura/aitest-hub` 尚不存在（推送受 token 权限限制），自托管后需复验一次。详见 `docs/verification-bugs.md` BUG-07 / BUG-08。

## 2026-09-29

### 验证器（scripts/verify-features.mjs）
- **jsErrors 按 URL 归属**：`pageerror` 原按"创建页时的 modId 闭包"归属，SPA 导航后过期（config-center 的 render 错误被误挂 scheduler）；改为按当前 URL pathname 归属（`routeToMod` 唯一路由映射，`(shell)` 共享路由退回 modId），增量基线同步改为全 map 快照（否则跨模块错误被汇总丢弃）。A/B 实证：回退态 `{"tool-config-center":[smtp],"tool-scheduler":[vnode]}` 归属正确、无丢失。
- **前置竞态扫描**：全量（无 `--only`）时自动先跑 `scan-race.mjs`（32 路由冷启动 + API 延迟），有 pageerror 只警告不阻断；`--no-scan` 可跳过，`--only` 分批时自动跳过。
- **单项 90s 超时**：Phase1/Phase2 特征循环体包 `Promise.race(..., 90000)`，超时记 `FAIL feature-timeout(90s)` 并继续——根治未知 await 悬挂拖死整轮。
- **`recoverBrowser` 加固**：`browser.close()` 竞速 8s 超时 + `finally` 复位 `_recovering`——根治 close 悬挂导致整轮永久卡死。
- **`VERIFY_OK` 后 `process.exit(0)`**：根治验证完成后进程挂起、shell 超时丢日志。
- **pentest#9 PRE 动态化**：硬编码 `id='PTC-139'` 随数据增长掉出第一页（`ORDER BY id DESC` + pageSize=10）→ 改 `id=(SELECT id ... ORDER BY id DESC LIMIT 1)`。

### 缺陷修复
- **BUG-01**（config-center smtp 非空断言运行时失效）：新增 `emailChannel()` 兜底，4 处 v-model 改用；根因实证——回退即复现。
- **BUG-02**（vnode null）：**定案为 BUG-01 的确定性次生崩溃**，回退实验 smtp+vnode 成对复现（与历史 run19 指标完全一致），修复后零复现；附加卸载守卫 `disposed` 检查位置修正（原在 `Promise.all` 之后无效 → 移至各 `loadXxx`/CRUD await 后赋值前）。
- **BUG-05 加固**（browser 中途退出）：根因确认为 **swap 90%+ 触发内核回收杀 chromium**，除自愈 recover 外补齐上述四道防线。
- **BUG-06**（新记录）：验证器 PRE 硬编码主键数据依赖，动态子查询修复。
- 全仓扫描：模板 `)!.` 反模式 0 处；v-model 绑函数调用仅 4 处且均为加固后的 `emailChannel()`。

### 工具
- `scripts/repro-bug02.mjs`：BUG-01/02 复现工具（冷加载直跳 `?tab=notify` + notify API 延迟）。
- `scripts/scan-race.mjs`：全路由冷启动竞态扫描（API 延迟放大未就绪窗口，收集 pageerror）；**新增 console 盲区收集**（error/warning，过滤静态资源 404 等噪音）——32 路由实测 pageerror 0 / console 0，报告增 `consoleIssues` 字段。
- `scripts/check-links.mjs`：内部死链静态扫描（manifest link 目标 vs 路由表 + TOOL_CATALOG slug；本项目 catch-all 静默重定向 `/app`，死链不报 404 故静态查更可靠）——实测 145 有效 / **死链 0** / 10 提取噪音（`#` 锚点、对象绑定、动态 `c.href`，已回源确认目标有效），报告落库 `.playwright-mcp/link-scan-report.json`。
- `.playwright-mcp/features-verify.snapshot-20260929.json`：全量报告快照。

### 环境
- 清理 AgnesCode 未纳管的 agent-lab 孤儿实例（vite 5191/5192×2、重复 serve_dist、旧 uvicorn 壳）；其自管服务 8011/5193 由 agnesd 守护自动重建，不与之拔河。load 18.8 → 7.7。

## 2026-09-28

### 验证
- 第二轮全量提取（`extract-features.mjs`）：35 模块 1053 项，与上版 diff = 0。
- 第二轮 9 批浏览器全量验证完成，与第一轮一致：**PASS 941 / PASS-EXIST 93 / SKIP 19 / FAIL 0 / MISSING 0 / jsErrors {}**。
- **BUG-01~05** 修复落库（详见 `docs/verification-bugs.md`）。
- 第一轮全量验证通过：FAIL 0 / MISSING 0。

## 2026-09-26

### 验证体系
- `scripts/extract-features.mjs`：清单驱动的功能点提取（35 模块 1053 项最小功能点）。
- `scripts/verify-features.mjs`：清单驱动的在线验证器（触发反馈 + 验证断言 + 结果落库报告），状态语义 PASS / PASS-EXIST / FAIL / MISSING / SKIP。
