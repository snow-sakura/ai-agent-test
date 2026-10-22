"""日志中心（Log Center）— /api/logs/*

字段对齐 UI/tool-log-center.html 的 logs 字面量：
id,time,type,mod,content,user,ip,dur,status,body
落 telemetry 的 system_logs 表；只读列表 + 统计。
"""

from typing import List

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.core.database import (
    SyncDB,
    db_commit,
    db_fetch_all,
    db_fetch_one,
    db_insert,
    get_db,
)
from app.services.telemetry import ensure_schema

router = APIRouter(tags=["log-center"])

# UI 内联种子（id 为自增整数，展示时格式化为 OP-xxxx）
_SEED = [
    # time, type, module, content, user, ip, dur(秒), status, body
    (
        "2026-09-22 16:42:18",
        "AI 调用",
        "技能中心",
        "调用技能「失败日志根因分析」生成分析结论",
        "wxh",
        "192.168.1.24",
        4,
        "成功",
        "[AI] model=DeepSeek-V3  skill=AG-06\n[AI] tokens: in=1240 out=868\n[AI] result=成功 cost=¥0.012",
    ),
    (
        "2026-09-22 15:31:07",
        "修改",
        "配置中心",
        "修改「用例评审」角色模型：DeepSeek-V3 → 通义千问-Max",
        "admin",
        "192.168.1.10",
        0,
        "成功",
        'PUT /api/config/roles/reviews\n{ "model": "qwen-max", "temperature": 0.2 }\n→ 200 OK',
    ),
    (
        "2026-09-22 14:20:55",
        "新增",
        "MCP 服务中心",
        "注册服务「内部知识库 MCP」（HTTP · 10.0.0.8:3000）",
        "wxh",
        "192.168.1.24",
        0,
        "成功",
        'POST /api/mcp/services\n{ "name": "内部知识库 MCP", "proto": "HTTP", "url": "http://10.0.0.8:3000/mcp" }\n→ 201 Created id=MS-11',
    ),
    (
        "2026-09-22 11:08:33",
        "删除",
        "用例管理",
        "删除用例「退款-超时未审核自动取消」（含 2 条关联执行记录归档）",
        "li-qa",
        "192.168.1.31",
        0,
        "成功",
        'DELETE /api/cases/342\n{ "archive_executions": true }\n→ 200 OK',
    ),
    (
        "2026-09-22 09:12:40",
        "登录",
        "系统",
        "用户登录成功（演示账号）",
        "wxh",
        "192.168.1.24",
        0,
        "成功",
        'POST /api/auth/login\n{ "account": "180****2234" }\n→ 200 OK  jwt issued',
    ),
    (
        "2026-09-22 02:00:05",
        "执行",
        "接口测试",
        "定时任务「每夜接口回归」自动触发（12 条用例）",
        "system",
        "10.0.0.2",
        222,
        "成功",
        "[SCHEDULER] task=ST-21 trigger=cron(0 2 * * *)\n[EXEC] 12/12 passed\n[NOTIFY] 邮件+企业微信 已推送",
    ),
    (
        "2026-09-21 17:45:12",
        "执行",
        "UI 自动化",
        "执行 UI 套件「主站冒烟」失败：场景 3 元素未找到",
        "system",
        "10.0.0.2",
        128,
        "失败",
        "[EXEC] suite=主站冒烟 scene=3/5\n[ERROR] locator 'button.pay' not found (timeout 30s)\n[NOTIFY] 失败通知已推送（仅失败策略）",
    ),
    (
        "2026-09-21 16:02:19",
        "AI 调用",
        "用例管理",
        "AI 批量生成用例 10 条（需求 REQ-2026-0125）",
        "li-qa",
        "192.168.1.31",
        8,
        "成功",
        "[AI] model=DeepSeek-V3  req=REQ-2026-0125\n[AI] generated=10  tokens: in=3120 out=2410\n[AI] result=成功 cost=¥0.038",
    ),
    (
        "2026-09-20 10:15:47",
        "导出",
        "缺陷管理",
        "导出缺陷列表 CSV（23 条）",
        "wxh",
        "192.168.1.24",
        0,
        "成功",
        "GET /api/defects/export?format=csv&count=23\n→ 200 OK  file=defects-20260920.csv",
    ),
    (
        "2026-09-18 09:30:02",
        "登录",
        "系统",
        "登录失败：密码错误（连续第 1 次）",
        "admin",
        "203.0.113.7",
        0,
        "失败",
        'POST /api/auth/login\n{ "account": "admin" }\n→ 401 Unauthorized  reason=bad_password',
    ),
    (
        "2026-09-17 14:22:36",
        "修改",
        "技能中心",
        "禁用技能「回归集智能筛选」",
        "admin",
        "192.168.1.10",
        0,
        "成功",
        'PATCH /api/skills/AG-03\n{ "status": "disabled" }\n→ 200 OK',
    ),
    (
        "2026-09-16 11:05:14",
        "新增",
        "配置中心",
        "新增 Webhook 通知渠道「企业微信」（key=demo…）",
        "admin",
        "192.168.1.10",
        0,
        "成功",
        'POST /api/notify/channels\n{ "type": "wecom", "enabled": true }\n→ 201 Created',
    ),
]


class _ListResp(BaseModel):
    items: List[dict]
    total: int
    page: int
    size: int


def _fmt_dur(sec: int) -> str:
    """秒 → UI 展示串（4.2s / 3m42s）。"""
    sec = int(sec or 0)
    if sec < 60:
        return f"{sec}s" if sec else "0.2s"
    m, s = divmod(sec, 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


def _row(r: dict) -> dict:
    rid = r.get("id")
    return {
        "id": f"OP-{rid}" if rid is not None else "",
        "rowId": rid,
        "time": r.get("time") or "",
        "type": r.get("type") or "",
        "mod": r.get("module") or "",
        "module": r.get("module") or "",  # 别名
        "content": r.get("content") or "",
        "user": r.get("user") or "",
        "ip": r.get("ip") or "",
        "dur": _fmt_dur(r.get("dur") or 0),
        "status": r.get("status") or "成功",
        "body": r.get("body") or "",
    }


async def _init(db: SyncDB):
    await ensure_schema(db)
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM system_logs", [])
    if row and row.get("c"):
        return
    for s in _SEED:
        await db_insert(
            db,
            "system_logs",
            {
                "time": s[0],
                "type": s[1],
                "module": s[2],
                "content": s[3],
                "user": s[4],
                "ip": s[5],
                "dur": s[6],
                "status": s[7],
                "body": s[8],
            },
        )
    await db_commit(db)


def _in_range(t: str, start: str, end: str) -> bool:
    d = (t or "")[:10]
    if start and d and d < start:
        return False
    if end and d and d > end:
        return False
    return True


@router.get("/logs")
async def list_logs(
    q: str = Query("", description="操作内容关键词"),
    type: str = Query(
        "", description="操作类型：登录/新增/修改/删除/执行/AI 调用/导出"
    ),
    module: str = Query("", description="操作模块"),
    user: str = Query("", description="操作人"),
    status: str = Query("", description="状态：成功/失败"),
    start: str = Query("", description="起始日期"),
    end: str = Query("", description="结束日期"),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: SyncDB = Depends(get_db),
):
    """操作日志列表（只读），按时间倒序分页。"""
    await _init(db)
    rows = await db_fetch_all(db, "SELECT * FROM system_logs ORDER BY id DESC", [])
    ql = (q or "").lower()
    items = []
    for r in rows:
        item = _row(r)
        if type and item["type"] != type:
            continue
        if module and item["mod"] != module:
            continue
        if user and item["user"] != user:
            continue
        if status and item["status"] != status:
            continue
        if not _in_range(item["time"], start, end):
            continue
        if ql and ql not in item["content"].lower():
            continue
        items.append(item)
    total = len(items)
    page = max(1, page)
    start_i = (page - 1) * size
    return {
        "items": items[start_i : start_i + size],
        "total": total,
        "page": page,
        "size": size,
    }


@router.get("/logs/stats")
async def logs_stats(
    start: str = Query("", description="起始日期"),
    end: str = Query("", description="结束日期"),
    db: SyncDB = Depends(get_db),
):
    """统计概览：今日操作、失败数、各类型计数、本周操作人。"""
    await _init(db)
    rows = await db_fetch_all(db, "SELECT * FROM system_logs", [])
    from datetime import datetime, timedelta

    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    today_n = fail_n = 0
    by_type: dict = {}
    by_module: dict = {}
    users = set()
    for r in rows:
        t = r.get("time") or ""
        if not _in_range(t, start, end):
            continue
        if t[:10] == today:
            today_n += 1
        if (r.get("status") or "") == "失败":
            fail_n += 1
        tp = r.get("type") or ""
        by_type[tp] = by_type.get(tp, 0) + 1
        md = r.get("module") or ""
        by_module[md] = by_module.get(md, 0) + 1
        if t[:10] >= week_ago and r.get("user"):
            users.add(r["user"])
    return {
        "today": today_n,
        "fail": fail_n,
        "total": len(rows),
        "weekUsers": len(users),
        "byType": [
            {"type": k, "count": v}
            for k, v in sorted(by_type.items(), key=lambda x: -x[1])
        ],
        "byModule": [
            {"module": k, "count": v}
            for k, v in sorted(by_module.items(), key=lambda x: -x[1])
        ],
    }
