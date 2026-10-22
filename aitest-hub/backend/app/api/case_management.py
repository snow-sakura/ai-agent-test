"""用例管理（Case Management）后端路由。

字段与 UI 设计 (UI/tool-case-management.html) 一一对应：
- 用例: id, title, module, pri, type, status, owner, run, pass, defect, pre, steps, exp
- 模块: 模块名列表（模块树）
- 执行批次: id, name, scope, total, pass, fail, time, by, status

表以 cm_ 前缀，独立于历史 thin test_cases；首次访问自动建表，
空库时灌入 UI 设计稿中的演示数据（seed），保证页面开箱即用。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.database import (
    SyncDB,
    get_db,
    db_fetch_all,
    db_fetch_one,
    db_insert,
    db_update,
    db_execute,
    db_commit,
)
from app.core.deps import get_current_user

router = APIRouter(tags=["case-management"])

# 鉴权契约（与 UI 对齐）：GET 列表（用例/模块/批次）不鉴权，演示可读；
# 写操作（create/update/review/drop/batch）保持 get_current_user。


# ============================== 模型 ==============================


class CaseCreate(BaseModel):
    title: str
    module: str = ""
    pri: str = "P2"
    type: str = "功能"
    pre: str = "-"
    steps: str = "-"
    exp: str = "-"


class CaseUpdate(BaseModel):
    title: Optional[str] = None
    module: Optional[str] = None
    pri: Optional[str] = None
    type: Optional[str] = None
    pre: Optional[str] = None
    steps: Optional[str] = None
    exp: Optional[str] = None


class ReviewAction(BaseModel):
    action: str


class ModuleCreate(BaseModel):
    name: str


class BatchCreate(BaseModel):
    name: str
    scope: str = "全部已评审"


# ============================== 工具 ==============================


def _display_name(user: dict) -> str:
    profile = user.get("profile") or {}
    return (
        profile.get("nickname")
        or user.get("full_name")
        or user.get("username")
        or "匿名"
    )


def _row_to_case(r: dict) -> dict:
    return {
        "id": r["id"],
        "title": r.get("title", ""),
        "module": r.get("module", ""),
        "pri": r.get("pri", "P2"),
        "type": r.get("type", "功能"),
        "status": r.get("status", "待评审"),
        "owner": r.get("owner", ""),
        "run": int(r.get("run", 0) or 0),
        "pass": int(r.get("pass_count", 0) or 0),
        "defect": int(r.get("defect", 0) or 0),
        "pre": r.get("pre", "-"),
        "steps": r.get("steps", "-"),
        "exp": r.get("exp", "-"),
    }


def _row_to_batch(r: dict) -> dict:
    return {
        "id": r["id"],
        "name": r.get("name", ""),
        "scope": r.get("scope", ""),
        "total": int(r.get("total", 0) or 0),
        "pass": int(r.get("pass_count", 0) or 0),
        "fail": int(r.get("fail", 0) or 0),
        "time": r.get("time", ""),
        "by": r.get("by_user", ""),
        "status": r.get("status", "执行中"),
    }


_SEED_MODULES = ["订单模块", "支付模块", "用户模块", "库存模块"]

_SEED_CASES = [
    (
        "TC-1001",
        "正常提交退款申请",
        "订单模块",
        "P0",
        "功能",
        "已评审",
        "wxh",
        3,
        3,
        0,
        "用户已登录，存在可退款订单",
        "1. 进入订单详情\n2. 点击申请退款\n3. 提交",
        "生成待审核退款单",
    ),
    (
        "TC-1002",
        "退款原因不选直接提交",
        "订单模块",
        "P0",
        "异常流",
        "待评审",
        "wxh",
        0,
        0,
        0,
        "进入退款申请页",
        "1. 不选原因\n2. 点击提交",
        "提示「请选择退款原因」",
    ),
    (
        "TC-1003",
        "退款说明 200 字边界",
        "订单模块",
        "P1",
        "边界",
        "待评审",
        "韩梅",
        2,
        2,
        0,
        "进入退款申请页",
        "1. 输入200字\n2. 尝试输入第201字",
        "第201字无法输入",
    ),
    (
        "TC-1004",
        "支付金额与订单一致校验",
        "支付模块",
        "P0",
        "功能",
        "已评审",
        "李雷",
        4,
        3,
        1,
        "存在待支付订单",
        "1. 发起支付\n2. 校验金额",
        "支付金额=订单实付金额",
    ),
    (
        "TC-1005",
        "支付超时订单关闭",
        "支付模块",
        "P1",
        "异常流",
        "已评审",
        "李雷",
        2,
        2,
        0,
        "存在待支付订单",
        "1. 等待30分钟不支付",
        "订单自动关闭",
    ),
    (
        "TC-1006",
        "未登录访问个人中心",
        "用户模块",
        "P0",
        "异常流",
        "待评审",
        "wxh",
        1,
        1,
        0,
        "未登录状态",
        "1. 直接访问 /user",
        "跳转登录页",
    ),
    (
        "TC-1007",
        "库存为0时禁止下单",
        "库存模块",
        "P0",
        "边界",
        "已评审",
        "韩梅",
        5,
        5,
        0,
        "某SKU库存为0",
        "1. 尝试下单",
        "提示库存不足，禁止下单",
    ),
    (
        "TC-1008",
        "已废弃：老版退款页兼容",
        "订单模块",
        "P2",
        "功能",
        "已废弃",
        "wxh",
        0,
        0,
        0,
        "-",
        "-",
        "-",
    ),
]

_SEED_BATCHES = [
    ("BT-31", "9月第3周回归", "全部已评审", 6, 5, 1, "2026-09-18", "wxh", "已完成"),
    ("BT-30", "支付专项验证", "按模块·支付", 2, 2, 0, "2026-09-15", "李雷", "已完成"),
    ("BT-32", "9月第4周回归", "全部已评审", 6, 3, 1, "执行中", "wxh", "执行中"),
]


async def _ensure_schema(db):
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS cm_cases (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, module TEXT DEFAULT '',
            pri TEXT DEFAULT 'P2', type TEXT DEFAULT '功能', status TEXT DEFAULT '待评审',
            owner TEXT DEFAULT '', run INTEGER DEFAULT 0, pass_count INTEGER DEFAULT 0,
            defect INTEGER DEFAULT 0, pre TEXT DEFAULT '-', steps TEXT DEFAULT '-',
            exp TEXT DEFAULT '-', created_at TEXT DEFAULT (datetime('now')))""",
    )
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS cm_modules (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)""",
    )
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS cm_batches (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, scope TEXT DEFAULT '',
            total INTEGER DEFAULT 0, pass_count INTEGER DEFAULT 0, fail INTEGER DEFAULT 0,
            time TEXT DEFAULT '', by_user TEXT DEFAULT '', status TEXT DEFAULT '执行中')""",
    )
    await db_commit(db)
    await _seed_if_empty(db)


async def _seed_if_empty(db):
    if (await db_fetch_one(db, "SELECT COUNT(*) AS c FROM cm_cases", []) or {}).get(
        "c", 0
    ) == 0:
        for c in _SEED_CASES:
            await db_execute(
                db,
                """INSERT OR IGNORE INTO cm_cases
                   (id,title,module,pri,type,status,owner,run,pass_count,defect,pre,steps,exp)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                list(c),
            )
    if (await db_fetch_one(db, "SELECT COUNT(*) AS c FROM cm_modules", []) or {}).get(
        "c", 0
    ) == 0:
        for name in _SEED_MODULES:
            await db_execute(
                db, "INSERT OR IGNORE INTO cm_modules (name) VALUES (?)", [name]
            )
    if (await db_fetch_one(db, "SELECT COUNT(*) AS c FROM cm_batches", []) or {}).get(
        "c", 0
    ) == 0:
        for b in _SEED_BATCHES:
            await db_execute(
                db,
                """INSERT OR IGNORE INTO cm_batches
                   (id,name,scope,total,pass_count,fail,time,by_user,status)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                list(b),
            )
    await db_commit(db)


async def _next_id(db, table, prefix, pad, floor):
    rows = await db_fetch_all(
        db, "SELECT id FROM " + table + " WHERE id LIKE ?", [prefix + "-%"]
    )
    nums = []
    for r in rows:
        try:
            nums.append(int(r["id"].split("-")[1]))
        except (ValueError, IndexError):
            pass
    nxt = (max(nums) if nums else floor) + 1
    if pad:
        return "%s-%04d" % (prefix, nxt)
    return "%s-%d" % (prefix, nxt)


# ============================== 用例 ==============================


@router.get("/cases")
async def list_cases(db: SyncDB = Depends(get_db)):
    await _ensure_schema(db)
    rows = await db_fetch_all(db, "SELECT * FROM cm_cases ORDER BY id ASC", [])
    return [_row_to_case(r) for r in rows]


@router.post("/cases")
async def create_case(
    body: CaseCreate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ensure_schema(db)
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="用例标题不能为空")
    cid = await _next_id(db, "cm_cases", "TC", True, 1000)
    await db_insert(
        db,
        "cm_cases",
        {
            "id": cid,
            "title": body.title.strip(),
            "module": body.module,
            "pri": body.pri,
            "type": body.type,
            "status": "待评审",
            "owner": _display_name(current_user),
            "run": 0,
            "pass_count": 0,
            "defect": 0,
            "pre": body.pre or "-",
            "steps": body.steps or "-",
            "exp": body.exp or "-",
        },
    )
    row = await db_fetch_one(db, "SELECT * FROM cm_cases WHERE id=?", [cid])
    return _row_to_case(row)


@router.put("/cases/{case_id}")
async def update_case(
    case_id: str,
    body: CaseUpdate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ensure_schema(db)
    row = await db_fetch_one(db, "SELECT * FROM cm_cases WHERE id=?", [case_id])
    if not row:
        raise HTTPException(status_code=404, detail="用例不存在")
    data = {}
    for key in ("title", "module", "pri", "type", "pre", "steps", "exp"):
        val = getattr(body, key, None)
        if val is not None:
            data[key] = val
    if data:
        await db_update(db, "cm_cases", data, "id=?", [case_id])
    row = await db_fetch_one(db, "SELECT * FROM cm_cases WHERE id=?", [case_id])
    return _row_to_case(row)


@router.post("/cases/{case_id}/review")
async def review_case(
    case_id: str,
    body: ReviewAction,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ensure_schema(db)
    row = await db_fetch_one(db, "SELECT * FROM cm_cases WHERE id=?", [case_id])
    if not row:
        raise HTTPException(status_code=404, detail="用例不存在")
    if body.action == "approve":
        await db_update(db, "cm_cases", {"status": "已评审"}, "id=?", [case_id])
    row = await db_fetch_one(db, "SELECT * FROM cm_cases WHERE id=?", [case_id])
    return _row_to_case(row)


@router.post("/cases/{case_id}/drop")
async def drop_case(
    case_id: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ensure_schema(db)
    row = await db_fetch_one(db, "SELECT * FROM cm_cases WHERE id=?", [case_id])
    if not row:
        raise HTTPException(status_code=404, detail="用例不存在")
    await db_update(db, "cm_cases", {"status": "已废弃"}, "id=?", [case_id])
    row = await db_fetch_one(db, "SELECT * FROM cm_cases WHERE id=?", [case_id])
    return _row_to_case(row)


# ============================== 模块 ==============================


@router.get("/case-modules")
async def list_modules(db: SyncDB = Depends(get_db)):
    await _ensure_schema(db)
    rows = await db_fetch_all(db, "SELECT name FROM cm_modules ORDER BY id ASC", [])
    return [r["name"] for r in rows]


@router.post("/case-modules")
async def create_module(
    body: ModuleCreate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ensure_schema(db)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="模块名称不能为空")
    if await db_fetch_one(db, "SELECT id FROM cm_modules WHERE name=?", [name]):
        raise HTTPException(status_code=409, detail="模块已存在")
    await db_execute(db, "INSERT INTO cm_modules (name) VALUES (?)", [name])
    await db_commit(db)
    rows = await db_fetch_all(db, "SELECT name FROM cm_modules ORDER BY id ASC", [])
    return [r["name"] for r in rows]


# ============================== 执行批次 ==============================


@router.get("/case-batches")
async def list_batches(db: SyncDB = Depends(get_db)):
    await _ensure_schema(db)
    rows = await db_fetch_all(db, "SELECT * FROM cm_batches ORDER BY id DESC", [])
    return [_row_to_batch(r) for r in rows]


@router.post("/case-batches")
async def create_batch(
    body: BatchCreate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ensure_schema(db)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="批次名称不能为空")
    bid = await _next_id(db, "cm_batches", "BT", False, 30)
    total = await db_fetch_one(
        db, "SELECT COUNT(*) AS c FROM cm_cases WHERE status='已评审'", []
    )
    await db_insert(
        db,
        "cm_batches",
        {
            "id": bid,
            "name": body.name.strip(),
            "scope": body.scope,
            "total": (total or {}).get("c", 0) or 0,
            "pass_count": 0,
            "fail": 0,
            "time": "刚刚",
            "by_user": _display_name(current_user),
            "status": "执行中",
        },
    )
    row = await db_fetch_one(db, "SELECT * FROM cm_batches WHERE id=?", [bid])
    return _row_to_batch(row)


@router.post("/case-batches/{batch_id}/stop")
async def stop_batch(
    batch_id: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ensure_schema(db)
    row = await db_fetch_one(db, "SELECT * FROM cm_batches WHERE id=?", [batch_id])
    if not row:
        raise HTTPException(status_code=404, detail="批次不存在")
    await db_update(db, "cm_batches", {"status": "已完成"}, "id=?", [batch_id])
    row = await db_fetch_one(db, "SELECT * FROM cm_batches WHERE id=?", [batch_id])
    return _row_to_batch(row)
