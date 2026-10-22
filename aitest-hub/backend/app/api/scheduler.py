"""调度中心（Scheduler）— /api/scheduler/*

字段对齐 UI/tool-scheduler.html：
tasks: id,name,type,target,mode,cron,notify,status,last,next,onlyFail
logs:  id,task,time,dur,result,detail
表：sch_tasks / sch_execs；cron 表达式用 croniter 校验，非法 400。
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.database import (
    SyncDB,
    db_commit,
    db_delete,
    db_execute,
    db_fetch_all,
    db_fetch_one,
    db_insert,
    db_update,
    get_db,
)
from app.core.deps import get_current_user

router = APIRouter(tags=["scheduler"])

_TASK_SEED = [
    {
        "id": "ST-21",
        "name": "每夜接口回归",
        "type": "接口测试",
        "target": "支付核心链路回归（12 条）",
        "mode": "cron",
        "cron": "0 2 * * *",
        "notify": "邮件 + 企业微信",
        "status": "启用",
        "last": "2026-09-22 02:00 成功",
        "next": "2026-09-23 02:00",
        "onlyFail": 0,
    },
    {
        "id": "ST-20",
        "name": "主站 UI 冒烟·每 4 小时",
        "type": "UI 自动化",
        "target": "主站冒烟（5 个场景）",
        "mode": "interval",
        "cron": "每 240 分钟",
        "notify": "邮件",
        "status": "启用",
        "last": "2026-09-22 16:00 成功",
        "next": "2026-09-22 20:00",
        "onlyFail": 0,
    },
    {
        "id": "ST-19",
        "name": "App 核心冒烟·每夜",
        "type": "App 自动化",
        "target": "核心冒烟-小米12",
        "mode": "cron",
        "cron": "0 3 * * *",
        "notify": "企业微信（仅失败）",
        "status": "启用",
        "last": "2026-09-22 03:00 失败",
        "next": "2026-09-23 03:00",
        "onlyFail": 1,
    },
    {
        "id": "ST-18",
        "name": "支付模块安全基线·每周",
        "type": "安全扫描",
        "target": "支付模块基线",
        "mode": "cron",
        "cron": "0 4 * * 1",
        "notify": "邮件",
        "status": "停用",
        "last": "2026-09-15 04:00 成功",
        "next": "—",
        "onlyFail": 0,
    },
    {
        "id": "ST-17",
        "name": "大促前全量回归·单次",
        "type": "接口测试",
        "target": "全量回归套件（86 条）",
        "mode": "once",
        "cron": "2026-09-30 01:00",
        "notify": "邮件 + 企业微信",
        "status": "启用",
        "last": "尚未触发",
        "next": "2026-09-30 01:00",
        "onlyFail": 0,
    },
]

_EXEC_SEED = [
    (
        "EX-908",
        "ST-21",
        "每夜接口回归",
        "2026-09-22 02:00",
        "3m42s",
        "成功",
        "12/12 通过 · 通知已发送（邮件+企微）",
    ),
    (
        "EX-907",
        "ST-20",
        "主站 UI 冒烟",
        "2026-09-22 16:00",
        "2m08s",
        "成功",
        "5/5 场景通过",
    ),
    (
        "EX-906",
        "ST-19",
        "App 核心冒烟",
        "2026-09-22 03:00",
        "6m51s",
        "失败",
        "步骤 4 元素未找到 · 已通知企微（仅失败）",
    ),
    (
        "EX-905",
        "ST-20",
        "主站 UI 冒烟",
        "2026-09-22 12:00",
        "1m59s",
        "成功",
        "5/5 场景通过",
    ),
    (
        "EX-904",
        "ST-18",
        "安全基线",
        "2026-09-15 04:00",
        "8m30s",
        "成功",
        "基线通过率 92%，新发现 1 项",
    ),
]


class TaskCreate(BaseModel):
    name: str
    type: str = "接口测试"
    target: str = ""
    mode: str = "cron"  # cron / interval / once
    cron: str = "0 2 * * *"
    notify: str = "邮件"
    onlyFail: bool = False
    status: str = "启用"


class TaskUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    target: Optional[str] = None
    mode: Optional[str] = None
    cron: Optional[str] = None
    notify: Optional[str] = None
    onlyFail: Optional[bool] = None
    status: Optional[str] = None


def _validate_cron(expr: str) -> None:
    """cron 表达式校验；interval/once 文案不走此函数。"""
    try:
        from croniter import croniter
    except ImportError:
        # 兜底：5 段基础格式
        parts = (expr or "").split()
        if len(parts) not in (5, 6):
            raise HTTPException(status_code=400, detail="Cron 表达式格式不正确")
        return
    if not croniter.is_valid(expr or ""):
        raise HTTPException(status_code=400, detail="Cron 表达式格式不正确")


async def _ensure_schema(db: SyncDB):
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS sch_tasks (
        id TEXT PRIMARY KEY, name TEXT, type TEXT, target TEXT,
        mode TEXT, cron TEXT, notify TEXT, status TEXT,
        last TEXT, next TEXT, onlyFail INTEGER DEFAULT 0,
        created_at TEXT)""",
    )
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS sch_execs (
        id TEXT PRIMARY KEY, task_id TEXT, task_label TEXT,
        time TEXT, dur TEXT, result TEXT, detail TEXT)""",
    )
    await db_commit(db)


async def _seed_if_empty(db: SyncDB):
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM sch_tasks", [])
    if not (row and row.get("c")):
        now = datetime.now().strftime("%Y-%m-%d")
        for t in _TASK_SEED:
            await db_insert(
                db,
                "sch_tasks",
                {
                    "id": t["id"],
                    "name": t["name"],
                    "type": t["type"],
                    "target": t["target"],
                    "mode": t["mode"],
                    "cron": t["cron"],
                    "notify": t["notify"],
                    "status": t["status"],
                    "last": t["last"],
                    "next": t["next"],
                    "onlyFail": t["onlyFail"],
                    "created_at": now,
                },
            )
        await db_commit(db)
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM sch_execs", [])
    if not (row and row.get("c")):
        for e in _EXEC_SEED:
            await db_insert(
                db,
                "sch_execs",
                {
                    "id": e[0],
                    "task_id": e[1],
                    "task_label": f"{e[1]} {e[2]}",
                    "time": e[3],
                    "dur": e[4],
                    "result": e[5],
                    "detail": e[6],
                },
            )
        await db_commit(db)


async def _init(db: SyncDB):
    await _ensure_schema(db)
    await _seed_if_empty(db)


def _task_row(r: dict) -> dict:
    return {
        "id": r.get("id") or "",
        "name": r.get("name") or "",
        "type": r.get("type") or "",
        "target": r.get("target") or "",
        "mode": r.get("mode") or "cron",
        "cron": r.get("cron") or "",
        "notify": r.get("notify") or "",
        "status": r.get("status") or "启用",
        "last": r.get("last") or "尚未触发",
        "next": r.get("next") or "—",
        "onlyFail": bool(r.get("onlyFail")),
    }


def _exec_row(r: dict) -> dict:
    return {
        "id": r.get("id") or "",
        "task": r.get("task_label") or "",
        "taskId": r.get("task_id") or "",
        "time": r.get("time") or "",
        "dur": r.get("dur") or "",
        "result": r.get("result") or "成功",
        "detail": r.get("detail") or "",
    }


async def _load(db: SyncDB, tid: str) -> dict:
    row = await db_fetch_one(db, "SELECT * FROM sch_tasks WHERE id=?", [tid])
    if not row:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    return row


async def _next_exec_id(db: SyncDB) -> str:
    row = await db_fetch_one(
        db,
        "SELECT id FROM sch_execs ORDER BY CAST(SUBSTR(id, 4) AS INTEGER) DESC LIMIT 1",
        [],
    )
    n = 909
    if row and row.get("id"):
        try:
            n = int(str(row["id"]).replace("EX-", "")) + 1
        except ValueError:
            n = 909
    return f"EX-{n}"


@router.get("/scheduler/tasks")
async def list_tasks(
    q: str = Query("", description="任务名称关键词"),
    type: str = Query("", description="任务类型"),
    status: str = Query("", description="启用/停用"),
    db: SyncDB = Depends(get_db),
):
    """定时任务列表（只读）。"""
    await _init(db)
    rows = await db_fetch_all(db, "SELECT * FROM sch_tasks ORDER BY id DESC", [])
    ql = (q or "").lower()
    items = []
    for r in rows:
        item = _task_row(r)
        if type and item["type"] != type:
            continue
        if status and item["status"] != status:
            continue
        if ql and ql not in item["name"].lower():
            continue
        items.append(item)
    return items


@router.post("/scheduler/tasks")
async def create_task(
    body: TaskCreate,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """新建定时任务；mode=cron 时用 croniter 校验表达式。"""
    await _init(db)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="任务名称不能为空")
    if body.mode == "cron":
        _validate_cron(body.cron)
    tid = f"ST-{datetime.now().strftime('%m%d%H%M%S')[-6:]}"
    # 避免撞 ID
    while await db_fetch_one(db, "SELECT id FROM sch_tasks WHERE id=?", [tid]):
        tid = f"ST-{datetime.now().strftime('%H%M%S%f')[:6]}"
    await db_insert(
        db,
        "sch_tasks",
        {
            "id": tid,
            "name": body.name.strip(),
            "type": body.type,
            "target": body.target,
            "mode": body.mode,
            "cron": body.cron,
            "notify": body.notify,
            "status": body.status or "启用",
            "last": "尚未触发",
            "next": "按调度计算" if body.mode != "once" else body.cron,
            "onlyFail": 1 if body.onlyFail else 0,
            "created_at": datetime.now().strftime("%Y-%m-%d"),
        },
    )
    return _task_row(await _load(db, tid))


@router.put("/scheduler/tasks/{tid}")
async def update_task(
    tid: str,
    body: TaskUpdate,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _init(db)
    await _load(db, tid)
    data = {}
    if body.name is not None:
        data["name"] = body.name.strip()
    if body.type is not None:
        data["type"] = body.type
    if body.target is not None:
        data["target"] = body.target
    if body.mode is not None:
        data["mode"] = body.mode
    if body.cron is not None:
        # 当前或将要使用 cron 模式时校验
        mode = body.mode or "cron"
        if mode == "cron":
            _validate_cron(body.cron)
        data["cron"] = body.cron
    if body.notify is not None:
        data["notify"] = body.notify
    if body.onlyFail is not None:
        data["onlyFail"] = 1 if body.onlyFail else 0
    if body.status is not None:
        data["status"] = body.status
    if data:
        await db_update(db, "sch_tasks", data, "id=?", [tid])
    return _task_row(await _load(db, tid))


@router.delete("/scheduler/tasks/{tid}")
async def delete_task(
    tid: str,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """删除任务；历史执行日志保留（对齐 UI 提示）。"""
    await _init(db)
    await _load(db, tid)
    await db_delete(db, "sch_tasks", "id=?", [tid])
    return {"ok": True, "id": tid}


@router.post("/scheduler/tasks/{tid}/run")
async def run_task(
    tid: str,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """立即执行：任务须为「启用」；写入一条执行日志并回写 last。"""
    await _init(db)
    task = await _load(db, tid)
    if (task.get("status") or "") != "启用":
        raise HTTPException(status_code=400, detail="任务已停用，请先启用")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    # 演示：约 15% 失败，其余成功
    import random

    ok = random.random() > 0.15
    result = "成功" if ok else "失败"
    dur = f"{(1 + random.random() * 5):.1f}m"
    detail = "全部通过" if ok else "执行失败，已按通知策略推送"
    ex_id = await _next_exec_id(db)
    await db_insert(
        db,
        "sch_execs",
        {
            "id": ex_id,
            "task_id": tid,
            "task_label": f"{tid} {task.get('name', '')}",
            "time": now,
            "dur": dur,
            "result": result,
            "detail": detail,
        },
    )
    await db_update(
        db,
        "sch_tasks",
        {"last": f"刚刚 {result}"},
        "id=?",
        [tid],
    )
    return {"ok": True, "id": ex_id, "result": result, "dur": dur, "detail": detail}


@router.get("/scheduler/logs")
async def list_exec_logs(
    result: str = Query("", description="成功/失败"),
    task_id: str = Query("", description="任务 ID"),
    db: SyncDB = Depends(get_db),
):
    """执行日志列表（只读），按时间倒序。"""
    await _init(db)
    rows = await db_fetch_all(
        db, "SELECT * FROM sch_execs ORDER BY time DESC, id DESC", []
    )
    items = []
    for r in rows:
        item = _exec_row(r)
        if result and item["result"] != result:
            continue
        if task_id and item["taskId"] != task_id:
            continue
        items.append(item)
    return items


@router.get("/scheduler/stats")
async def scheduler_stats(db: SyncDB = Depends(get_db)):
    """统计：任务总数 / 启用中 / 今日触发 / 最近失败。"""
    await _init(db)
    tasks = await db_fetch_all(db, "SELECT * FROM sch_tasks", [])
    execs = await db_fetch_all(db, "SELECT * FROM sch_execs", [])
    today = datetime.now().strftime("%Y-%m-%d")
    total = len(tasks)
    on = sum(1 for t in tasks if (t.get("status") or "") == "启用")
    today_n = sum(1 for e in execs if (e.get("time") or "").startswith(today))
    fail = sum(1 for e in execs if (e.get("result") or "") == "失败")
    return {"total": total, "on": on, "today": today_n, "fail": fail}
