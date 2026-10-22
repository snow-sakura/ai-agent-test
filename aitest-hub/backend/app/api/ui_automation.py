"""UI 自动化（OmniFlow）— /api/ui-automation/*

- 场景 CRUD（steps 为 JSON 数组）
- 模拟无头执行 → 写入执行记录
- AI 生成步骤（chat_json 失败回退本地默认步骤）
"""

import json
import random
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.database import (
    SyncDB,
    db_commit,
    db_execute,
    db_fetch_all,
    db_fetch_one,
    db_insert,
    db_update,
    get_db,
)
from app.core.deps import get_current_user
from app.services import ai as ai_svc

router = APIRouter(tags=["ui-automation"])

R_OK = "成功"
R_FAIL = "失败"
R_RUN = "运行中"


# ---------------------------------------------------------------------------
# schema / seed
# ---------------------------------------------------------------------------


def _mk_steps(n: int, url: str) -> List[Dict[str, Any]]:
    """按目标 URL 生成 n 条演示步骤 [{action, selector, value}]。"""
    base = [
        {"action": "goto", "selector": "", "value": url},
        {"action": "fill", "selector": "#username", "value": "admin"},
        {"action": "fill", "selector": "#password", "value": "{{PASS}}"},
        {"action": "click", "selector": "button[type=submit]", "value": "登录"},
        {"action": "llm", "selector": "", "value": "AI 识别页面主入口并进入"},
        {"action": "click", "selector": ".nav-orders", "value": "订单"},
        {"action": "assert", "selector": "body", "value": "页面包含「订单」"},
        {"action": "wait", "selector": ".loading", "value": "2s"},
        {"action": "assert", "selector": ".result", "value": "包含「提交成功」"},
        {"action": "upload", "selector": "#file", "value": "~/data/avatar.png"},
        {"action": "click", "selector": "#coupon", "value": "领取优惠券"},
        {"action": "assert", "selector": ".toast", "value": "包含「领取成功」"},
    ]
    steps: List[Dict[str, Any]] = []
    for i in range(max(0, n)):
        s = dict(base[i % len(base)])
        steps.append(s)
    return steps


_SEED_SCENES = [
    {
        "id": "sc-001",
        "name": "登录-下单-支付主流程",
        "url": "https://shop.example.com",
        "status": "启用",
        "browser": "Chromium（无头）",
        "ssh": 0,
        "steps": _mk_steps(9, "https://shop.example.com"),
        "last_run": "2026-09-22 08:51",
        "last_result": R_OK,
    },
    {
        "id": "sc-002",
        "name": "首页搜索加购验证",
        "url": "https://shop.example.com/search",
        "status": "启用",
        "browser": "Chromium（无头）",
        "ssh": 0,
        "steps": _mk_steps(6, "https://shop.example.com/search"),
        "last_run": "2026-09-21 19:03",
        "last_result": R_OK,
    },
    {
        "id": "sc-003",
        "name": "优惠券领取边界",
        "url": "https://shop.example.com/coupon",
        "status": "停用",
        "browser": "Firefox",
        "ssh": 0,
        "steps": _mk_steps(5, "https://shop.example.com/coupon"),
        "last_run": "2026-09-18 14:20",
        "last_result": R_FAIL,
    },
    {
        "id": "sc-004",
        "name": "内网 OA 审批流冒烟",
        "url": "http://oa.intra.local/approve",
        "status": "启用",
        "browser": "Chrome",
        "ssh": 1,
        "steps": _mk_steps(12, "http://oa.intra.local/approve"),
        "last_run": "2026-09-20 10:11",
        "last_result": R_OK,
    },
    {
        "id": "sc-005",
        "name": "注册页表单校验",
        "url": "https://shop.example.com/register",
        "status": "启用",
        "browser": "Chromium（无头）",
        "ssh": 0,
        "steps": _mk_steps(7, "https://shop.example.com/register"),
        "last_run": "2026-09-17 16:45",
        "last_result": R_FAIL,
    },
    {
        "id": "sc-006",
        "name": "订单列表分页翻页",
        "url": "https://shop.example.com/orders",
        "status": "停用",
        "browser": "Chromium（无头）",
        "ssh": 0,
        "steps": _mk_steps(4, "https://shop.example.com/orders"),
        "last_run": "2026-09-15 09:30",
        "last_result": R_OK,
    },
]

_SEED_RUNS = [
    {
        "id": "R-2043",
        "scene_id": "sc-001",
        "scene": "登录-下单-支付主流程",
        "time": "2026-09-22 08:51",
        "dur": "42s",
        "result": R_OK,
        "steps": 9,
    },
    {
        "id": "R-2042",
        "scene_id": "sc-002",
        "scene": "首页搜索加购验证",
        "time": "2026-09-21 19:03",
        "dur": "28s",
        "result": R_OK,
        "steps": 6,
    },
    {
        "id": "R-2041",
        "scene_id": "sc-003",
        "scene": "优惠券领取边界",
        "time": "2026-09-18 14:20",
        "dur": "35s",
        "result": R_FAIL,
        "steps": 5,
    },
    {
        "id": "R-2040",
        "scene_id": "sc-004",
        "scene": "内网 OA 审批流冒烟",
        "time": "2026-09-20 10:11",
        "dur": "66s",
        "result": R_OK,
        "steps": 12,
    },
    {
        "id": "R-2039",
        "scene_id": "sc-005",
        "scene": "注册页表单校验",
        "time": "2026-09-17 16:45",
        "dur": "31s",
        "result": R_FAIL,
        "steps": 7,
    },
    {
        "id": "R-2038",
        "scene_id": "sc-006",
        "scene": "订单列表分页翻页",
        "time": "2026-09-15 09:30",
        "dur": "22s",
        "result": R_OK,
        "steps": 4,
    },
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _j(v: Any, default=None):
    if v is None or v == "":
        return default if default is not None else None
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return default if default is not None else v


async def _ensure_schema(db: SyncDB) -> None:
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS uia_scenes (
        id TEXT PRIMARY KEY, name TEXT, url TEXT, status TEXT, browser TEXT,
        ssh INTEGER DEFAULT 0, steps TEXT, last_run TEXT, last_result TEXT,
        created_at TEXT)""",
    )
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS uia_runs (
        id TEXT PRIMARY KEY, scene_id TEXT, scene TEXT, time TEXT, dur TEXT,
        result TEXT, steps INTEGER, created_at TEXT)""",
    )
    await db_commit(db)


async def _seed_if_empty(db: SyncDB) -> None:
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM uia_scenes", [])
    if not (row and row["c"]):
        for r in _SEED_SCENES:
            item = dict(r)
            item["steps"] = json.dumps(r["steps"], ensure_ascii=False)
            item["created_at"] = _now()
            await db_insert(db, "uia_scenes", item)
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM uia_runs", [])
    if not (row and row["c"]):
        for r in _SEED_RUNS:
            item = dict(r)
            item["created_at"] = item.get("time") or _now()
            await db_insert(db, "uia_runs", item)
    await db_commit(db)


async def _ready(db: SyncDB) -> None:
    await _ensure_schema(db)
    await _seed_if_empty(db)


def _scene_row(r: dict) -> dict:
    steps = _j(r.get("steps"), [])
    if not isinstance(steps, list):
        steps = []
    return {
        "id": r.get("id"),
        "name": r.get("name") or "",
        "url": r.get("url") or "",
        "status": r.get("status") or "启用",
        "browser": r.get("browser") or "Chromium（无头）",
        "ssh": bool(r.get("ssh")),
        "steps": steps,
        "stepCount": len(steps),
        "lastRun": r.get("last_run") or "—",
        "lastResult": r.get("last_result") or "",
        "createdAt": r.get("created_at") or "",
    }


def _run_row(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "scene": r.get("scene") or "",
        "sceneId": r.get("scene_id") or "",
        "time": r.get("time") or "",
        "dur": r.get("dur") or "",
        "result": r.get("result") or "",
        "steps": int(r.get("steps") or 0),
    }


async def _next_id(db: SyncDB, table: str, prefix: str) -> str:
    rows = await db_fetch_all(
        db, f"SELECT id FROM {table} WHERE id LIKE ?", [f"{prefix}%"]
    )
    best = 0
    for r in rows:
        try:
            tail = str(r["id"]).split("-")[-1]
            best = max(best, int(tail))
        except Exception:
            pass
    return f"{prefix}{best + 1}"


# ---------------------------------------------------------------------------
# pydantic
# ---------------------------------------------------------------------------


class StepIn(BaseModel):
    action: str = "click"
    selector: str = ""
    value: str = ""


class SceneCreate(BaseModel):
    id: str = ""
    name: str
    url: str
    status: str = "启用"
    browser: str = "Chromium（无头）"
    ssh: bool = False
    steps: List[StepIn] = []


class SceneUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    status: Optional[str] = None
    browser: Optional[str] = None
    ssh: Optional[bool] = None
    steps: Optional[List[StepIn]] = None


class AiStepsReq(BaseModel):
    desc: str
    url: str = ""


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------


@router.get("/ui-automation/scenes")
async def list_scenes(
    kw: str = "",
    status: str = "",
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    rows = await db_fetch_all(db, "SELECT * FROM uia_scenes ORDER BY id", [])
    out = [_scene_row(r) for r in rows]
    if kw:
        k = kw.lower()
        out = [s for s in out if k in (s["name"] + s["url"]).lower()]
    if status:
        out = [s for s in out if s["status"] == status]
    return out


@router.get("/ui-automation/scenes/{sid}")
async def get_scene(sid: str, db: SyncDB = Depends(get_db)):
    await _ready(db)
    row = await db_fetch_one(db, "SELECT * FROM uia_scenes WHERE id=?", [sid])
    if not row:
        raise HTTPException(status_code=404, detail="场景不存在")
    return _scene_row(row)


@router.post("/ui-automation/scenes")
async def create_scene(
    body: SceneCreate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="场景名称不能为空")
    if not body.url.strip().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="目标 URL 必须以 http(s):// 开头")
    sid = body.id.strip() or await _next_id(db, "uia_scenes", "sc-")
    if await db_fetch_one(db, "SELECT id FROM uia_scenes WHERE id=?", [sid]):
        raise HTTPException(status_code=409, detail="场景 ID 已存在")
    steps = [s.model_dump() for s in body.steps]
    await db_insert(
        db,
        "uia_scenes",
        {
            "id": sid,
            "name": body.name.strip(),
            "url": body.url.strip(),
            "status": body.status or "启用",
            "browser": body.browser or "Chromium（无头）",
            "ssh": 1 if body.ssh else 0,
            "steps": json.dumps(steps, ensure_ascii=False),
            "last_run": "—",
            "last_result": R_OK,
            "created_at": _now(),
        },
    )
    row = await db_fetch_one(db, "SELECT * FROM uia_scenes WHERE id=?", [sid])
    if not row:
        raise HTTPException(status_code=500, detail="场景写入失败")
    return _scene_row(row)


@router.put("/ui-automation/scenes/{sid}")
async def update_scene(
    sid: str,
    body: SceneUpdate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    row = await db_fetch_one(db, "SELECT * FROM uia_scenes WHERE id=?", [sid])
    if not row:
        raise HTTPException(status_code=404, detail="场景不存在")
    data: Dict[str, Any] = {}
    if body.name is not None:
        data["name"] = body.name.strip()
    if body.url is not None:
        if not body.url.strip().startswith(("http://", "https://")):
            raise HTTPException(
                status_code=400, detail="目标 URL 必须以 http(s):// 开头"
            )
        data["url"] = body.url.strip()
    if body.status is not None:
        data["status"] = body.status
    if body.browser is not None:
        data["browser"] = body.browser
    if body.ssh is not None:
        data["ssh"] = 1 if body.ssh else 0
    if body.steps is not None:
        data["steps"] = json.dumps(
            [s.model_dump() for s in body.steps], ensure_ascii=False
        )
    if data:
        await db_update(db, "uia_scenes", data, "id=?", [sid])
    row = await db_fetch_one(db, "SELECT * FROM uia_scenes WHERE id=?", [sid])
    return _scene_row(row)


@router.delete("/ui-automation/scenes/{sid}")
async def delete_scene(
    sid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    row = await db_fetch_one(db, "SELECT id FROM uia_scenes WHERE id=?", [sid])
    if not row:
        raise HTTPException(status_code=404, detail="场景不存在")
    await db_execute(db, "DELETE FROM uia_scenes WHERE id=?", [sid])
    await db_commit(db)
    return {"ok": True, "id": sid}


@router.post("/ui-automation/scenes/{sid}/run")
async def run_scene(
    sid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """模拟无头执行：逐步通过 → 写执行记录 → 回写场景最近结果。"""
    await _ready(db)
    scene = await db_fetch_one(db, "SELECT * FROM uia_scenes WHERE id=?", [sid])
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    steps = _j(scene.get("steps"), []) or []
    n = len(steps)
    ok = random.random() > 0.25
    dur = f"{random.randint(max(8, n * 2), max(20, n * 8))}s"
    rid = await _next_id(db, "uia_runs", "R-")
    now = _now()
    result = R_OK if ok else R_FAIL
    await db_insert(
        db,
        "uia_runs",
        {
            "id": rid,
            "scene_id": sid,
            "scene": scene.get("name") or "",
            "time": now,
            "dur": dur,
            "result": result,
            "steps": n,
            "created_at": now,
        },
    )
    await db_update(
        db,
        "uia_scenes",
        {"last_run": now, "last_result": result},
        "id=?",
        [sid],
    )
    log = [
        {
            "i": i + 1,
            "ok": True,
            "action": (s or {}).get("action", ""),
            "text": (s or {}).get("value") or (s or {}).get("selector", ""),
        }
        for i, s in enumerate(steps)
    ]
    if not ok and log:
        log[-1]["ok"] = False
        log[-1]["text"] = "验证失败：断言未通过"
    run = await db_fetch_one(db, "SELECT * FROM uia_runs WHERE id=?", [rid])
    return {
        "run": _run_row(run),
        "log": log,
        "screenshots": ["01-登录页", "02-商品详情", "03-确认订单", "04-支付结果"],
        "recording": f"run-{rid}.webm",
        "message": "执行成功 🎉" if ok else "执行失败：步骤验证未通过",
    }


@router.get("/ui-automation/runs")
async def list_runs(
    scene_id: str = "",
    result: str = "",
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    rows = await db_fetch_all(db, "SELECT * FROM uia_runs ORDER BY time DESC", [])
    out = [_run_row(r) for r in rows]
    if scene_id:
        out = [r for r in out if r["sceneId"] == scene_id]
    if result:
        out = [r for r in out if r["result"] == result]
    return out


@router.get("/ui-automation/runs/{rid}")
async def get_run(rid: str, db: SyncDB = Depends(get_db)):
    """执行详情：返回与前端 RunDetail 一致的 {run, log, screenshots, recording, message}。"""
    await _ready(db)
    row = await db_fetch_one(db, "SELECT * FROM uia_runs WHERE id=?", [rid])
    if not row:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    run = _run_row(row)
    scene = await db_fetch_one(
        db, "SELECT * FROM uia_scenes WHERE id=?", [run.get("sceneId") or ""]
    )
    steps = _j(scene.get("steps"), []) if scene else []
    if not isinstance(steps, list):
        steps = []
    ok = run.get("result") == R_OK
    log = [
        {
            "i": i + 1,
            "ok": True,
            "action": (s or {}).get("action", ""),
            "text": (s or {}).get("value") or (s or {}).get("selector", ""),
        }
        for i, s in enumerate(steps)
    ]
    if not ok and log:
        log[-1]["ok"] = False
        log[-1]["text"] = "验证失败：断言未通过"
    if not log:
        # 场景已删除或无步骤：按步骤数占位
        log = [
            {"i": i + 1, "ok": ok, "action": "step", "text": ""}
            for i in range(int(run.get("steps") or 0))
        ]
    return {
        "run": run,
        "log": log,
        "screenshots": [
            "01-登录页",
            "02-商品详情",
            "03-确认订单",
            "04-支付结果",
        ],
        "recording": f"run-{rid}.webm",
        "message": "执行成功 🎉" if ok else "执行失败：步骤验证未通过",
    }


@router.post("/ui-automation/ai-steps")
async def ai_steps(
    body: AiStepsReq,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """AI 根据自然语言描述生成 UI 步骤；失败回退本地默认。"""
    await _ready(db)
    desc = (body.desc or "").strip()
    if not desc:
        raise HTTPException(status_code=400, detail="desc 不能为空")
    fallback = _mk_steps(6, body.url or "https://example.com")
    try:
        data = await ai_svc.chat_json(
            db,
            [
                {
                    "role": "user",
                    "content": (
                        "你是 UI 自动化助手。根据描述生成浏览器操作步骤，"
                        "只输出 JSON 数组（不要解释），每项格式："
                        '{"action":"goto|fill|click|llm|assert|wait|upload",'
                        '"selector":"css或空","value":"内容"}\n'
                        f"描述：{desc}\n目标URL：{body.url or '(未提供)'}"
                    ),
                }
            ],
            module="UI自动化",
        )
        if isinstance(data, dict):
            data = data.get("steps") or data.get("items") or []
        if isinstance(data, list) and data and isinstance(data[0], dict):
            steps = []
            for item in data[:30]:
                steps.append(
                    {
                        "action": str(
                            item.get("action") or item.get("type") or "click"
                        ),
                        "selector": str(item.get("selector") or ""),
                        "value": str(item.get("value") or item.get("text") or ""),
                    }
                )
            return {"steps": steps, "count": len(steps), "source": "ai"}
    except Exception:
        pass
    return {"steps": fallback, "count": len(fallback), "source": "local"}
