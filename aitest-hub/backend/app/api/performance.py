"""性能测试（Performance）— /api/perf/*

- 场景 CRUD + 模拟压测执行（生成报告）
- 报告列表/详情
- AI 分析结论（app.services.ai，module=性能分析）
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

router = APIRouter(tags=["performance"])

S_OK = "达标"
S_FAIL = "未达标"
S_IDLE = "未执行"


# ---------------------------------------------------------------------------
# schema / seed
# ---------------------------------------------------------------------------

_SEED_SCENES = [
    {
        "id": "PF-31",
        "name": "秒杀下单链路·尖峰",
        "users": 2000,
        "ramp": 60,
        "dur": 300,
        "url": "https://api.example.com/v1/orders",
        "method": "POST",
        "status": S_FAIL,
        "last": "2026-09-22 10:30",
        "qps": 4210,
        "p99": 1240,
        "err": 2.31,
    },
    {
        "id": "PF-30",
        "name": "交易核心链路·大促预演",
        "users": 800,
        "ramp": 120,
        "dur": 600,
        "url": "https://api.example.com/v1/trade/submit",
        "method": "POST",
        "status": S_OK,
        "last": "2026-09-22 08:00",
        "qps": 1943,
        "p99": 420,
        "err": 0.34,
    },
    {
        "id": "PF-29",
        "name": "登录接口·基准",
        "users": 200,
        "ramp": 30,
        "dur": 120,
        "url": "https://api.example.com/v1/auth/login",
        "method": "POST",
        "status": S_IDLE,
        "last": "",
        "qps": 0,
        "p99": 0,
        "err": 0,
    },
]

_SEED_REPORTS = [
    {
        "id": "RPT-102",
        "scene_id": "PF-31",
        "scene": "秒杀下单链路·尖峰",
        "qps": 4210,
        "p99": 1240,
        "err": 2.31,
        "users": 2000,
        "verdict": S_FAIL,
        "time": "2026-09-22 10:30",
        "note": "峰值吞吐不足，P99 超阈值，错误率偏高",
    },
    {
        "id": "RPT-101",
        "scene_id": "PF-30",
        "scene": "交易核心链路·大促预演",
        "qps": 1943,
        "p99": 420,
        "err": 0.34,
        "users": 800,
        "verdict": S_OK,
        "time": "2026-09-22 08:00",
        "note": "整体达标，建议保留基线用于回归对比",
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
        """CREATE TABLE IF NOT EXISTS perf_scenes (
        id TEXT PRIMARY KEY, name TEXT, users INTEGER, ramp INTEGER, dur INTEGER,
        url TEXT, method TEXT, status TEXT, last TEXT,
        qps INTEGER, p99 INTEGER, err REAL)""",
    )
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS perf_reports (
        id TEXT PRIMARY KEY, scene_id TEXT, scene TEXT, qps INTEGER, p99 INTEGER,
        err REAL, users INTEGER, verdict TEXT, time TEXT, note TEXT, metrics TEXT)""",
    )
    await db_commit(db)


async def _seed_if_empty(db: SyncDB) -> None:
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM perf_scenes", [])
    if not (row and row["c"]):
        for r in _SEED_SCENES:
            await db_insert(db, "perf_scenes", dict(r))
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM perf_reports", [])
    if not (row and row["c"]):
        for r in _SEED_REPORTS:
            item = dict(r)
            item["metrics"] = json.dumps(
                {
                    "qps": r["qps"],
                    "p99": r["p99"],
                    "err": r["err"],
                    "users": r["users"],
                },
                ensure_ascii=False,
            )
            await db_insert(db, "perf_reports", item)
    await db_commit(db)


async def _ready(db: SyncDB) -> None:
    await _ensure_schema(db)
    await _seed_if_empty(db)


def _scene_row(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "name": r.get("name") or "",
        "users": r.get("users") or 0,
        "ramp": r.get("ramp") or 0,
        "dur": r.get("dur") or 0,
        "url": r.get("url") or "",
        "method": r.get("method") or "GET",
        "status": r.get("status") or S_IDLE,
        "last": r.get("last") or "",
        "qps": r.get("qps") or 0,
        "p99": r.get("p99") or 0,
        "err": r.get("err") or 0,
    }


def _report_row(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "sceneId": r.get("scene_id") or "",
        "scene": r.get("scene") or "",
        "qps": r.get("qps") or 0,
        "p99": r.get("p99") or 0,
        "err": r.get("err") or 0,
        "users": r.get("users") or 0,
        "verdict": r.get("verdict") or "",
        "time": r.get("time") or "",
        "note": r.get("note") or "",
        "metrics": _j(r.get("metrics"), {}),
    }


async def _load_scene(db: SyncDB, sid: str) -> dict:
    row = await db_fetch_one(db, "SELECT * FROM perf_scenes WHERE id=?", [sid])
    if not row:
        raise HTTPException(status_code=404, detail="场景不存在")
    return row


async def _next_scene_id(db: SyncDB) -> str:
    rows = await db_fetch_all(db, "SELECT id FROM perf_scenes WHERE id LIKE 'PF-%'", [])
    best = 0
    for r in rows:
        try:
            best = max(best, int(str(r["id"]).split("-")[-1]))
        except Exception:
            pass
    return "PF-%d" % (best + 1)


async def _next_report_id(db: SyncDB) -> str:
    rows = await db_fetch_all(
        db, "SELECT id FROM perf_reports WHERE id LIKE 'RPT-%'", []
    )
    best = 100
    for r in rows:
        try:
            best = max(best, int(str(r["id"]).split("-")[-1]))
        except Exception:
            pass
    return "RPT-%d" % (best + 1)


# ---------------------------------------------------------------------------
# pydantic
# ---------------------------------------------------------------------------


class SceneCreate(BaseModel):
    id: str = ""
    name: str
    users: int = 100
    ramp: int = 30
    dur: int = 120
    url: str = ""
    method: str = "GET"
    status: str = S_IDLE


class SceneUpdate(BaseModel):
    name: Optional[str] = None
    users: Optional[int] = None
    ramp: Optional[int] = None
    dur: Optional[int] = None
    url: Optional[str] = None
    method: Optional[str] = None
    status: Optional[str] = None


class AnalyzeReq(BaseModel):
    reportId: str = ""
    metrics: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# scenes
# ---------------------------------------------------------------------------


@router.get("/perf/scenes")
async def list_scenes(db: SyncDB = Depends(get_db)):
    await _ready(db)
    rows = await db_fetch_all(db, "SELECT * FROM perf_scenes ORDER BY id DESC", [])
    return [_scene_row(r) for r in rows]


@router.get("/perf/scenes/{sid}")
async def get_scene(sid: str, db: SyncDB = Depends(get_db)):
    await _ready(db)
    return _scene_row(await _load_scene(db, sid))


@router.post("/perf/scenes")
async def create_scene(
    body: SceneCreate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="场景名称不能为空")
    sid = body.id.strip() or await _next_scene_id(db)
    if await db_fetch_one(db, "SELECT id FROM perf_scenes WHERE id=?", [sid]):
        raise HTTPException(status_code=409, detail="场景 ID 已存在")
    await db_insert(
        db,
        "perf_scenes",
        {
            "id": sid,
            "name": body.name.strip(),
            "users": body.users,
            "ramp": body.ramp,
            "dur": body.dur,
            "url": body.url,
            "method": (body.method or "GET").upper(),
            "status": body.status or S_IDLE,
            "last": "",
            "qps": 0,
            "p99": 0,
            "err": 0,
        },
    )
    return _scene_row(await _load_scene(db, sid))


@router.put("/perf/scenes/{sid}")
async def update_scene(
    sid: str,
    body: SceneUpdate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    await _load_scene(db, sid)
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    if "method" in data:
        data["method"] = (data["method"] or "GET").upper()
    if "name" in data and not str(data["name"]).strip():
        raise HTTPException(status_code=400, detail="场景名称不能为空")
    if data:
        await db_update(db, "perf_scenes", data, "id=?", [sid])
    return _scene_row(await _load_scene(db, sid))


@router.delete("/perf/scenes/{sid}")
async def delete_scene(
    sid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    await _load_scene(db, sid)
    await db_execute(db, "DELETE FROM perf_scenes WHERE id=?", [sid])
    await db_commit(db)
    return {"ok": True, "id": sid}


# ---------------------------------------------------------------------------
# run / reports / analyze
# ---------------------------------------------------------------------------


@router.post("/perf/scenes/{sid}/run")
async def run_scene(
    sid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """模拟执行压测：按场景目标生成合理随机指标，写入报告并回写场景。"""
    await _ready(db)
    scene = await _load_scene(db, sid)
    base = int(scene.get("users") or 200)
    target_qps = max(50, base * 2 + random.randint(-20, 40))
    qps = int(target_qps * random.uniform(0.78, 1.05))
    p99 = random.randint(160, 980)
    err = round(random.uniform(0.02, 2.6), 2)
    ok = err < 0.5 and p99 <= 800
    verdict = S_OK if ok else S_FAIL
    now = _now()
    rid = await _next_report_id(db)
    metrics = {
        "qps": qps,
        "p99": p99,
        "err": err,
        "users": base,
        "ramp": scene.get("ramp") or 0,
        "dur": scene.get("dur") or 0,
        "avg": max(20, int(p99 * 0.42)),
        "throughputKBps": int(qps * 1.8),
    }
    note = (
        "吞吐与延迟均在阈值内，整体达标"
        if ok
        else "P99/错误率超出阈值，建议排查慢查询与限流配置"
    )
    await db_insert(
        db,
        "perf_reports",
        {
            "id": rid,
            "scene_id": sid,
            "scene": scene.get("name") or "",
            "qps": qps,
            "p99": p99,
            "err": err,
            "users": base,
            "verdict": verdict,
            "time": now,
            "note": note,
            "metrics": json.dumps(metrics, ensure_ascii=False),
        },
    )
    await db_update(
        db,
        "perf_scenes",
        {
            "status": verdict,
            "last": now,
            "qps": qps,
            "p99": p99,
            "err": err,
        },
        "id=?",
        [sid],
    )
    row = await db_fetch_one(db, "SELECT * FROM perf_reports WHERE id=?", [rid])
    if not row:
        raise HTTPException(status_code=500, detail="报告写入失败")
    return _report_row(row)


@router.get("/perf/reports")
async def list_reports(db: SyncDB = Depends(get_db)):
    await _ready(db)
    rows = await db_fetch_all(
        db, "SELECT * FROM perf_reports ORDER BY time DESC, id DESC", []
    )
    return [_report_row(r) for r in rows]


@router.get("/perf/reports/{rid}")
async def get_report(rid: str, db: SyncDB = Depends(get_db)):
    await _ready(db)
    row = await db_fetch_one(db, "SELECT * FROM perf_reports WHERE id=?", [rid])
    if not row:
        raise HTTPException(status_code=404, detail="报告不存在")
    return _report_row(row)


@router.post("/perf/analyze")
async def analyze(
    body: AnalyzeReq,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """AI 分析报告指标（无 key 时自动 mock）。"""
    await _ready(db)
    metrics: Dict[str, Any] = {}
    report = None
    if body.reportId:
        report = await db_fetch_one(
            db, "SELECT * FROM perf_reports WHERE id=?", [body.reportId]
        )
        if not report:
            raise HTTPException(status_code=404, detail="报告不存在")
        loaded = _j(report.get("metrics"), {})
        if isinstance(loaded, dict):
            metrics.update(loaded)
        metrics.update(
            {
                "qps": report.get("qps"),
                "p99": report.get("p99"),
                "err": report.get("err"),
            }
        )
    if body.metrics:
        metrics.update(body.metrics)
    if not metrics:
        raise HTTPException(status_code=400, detail="需要 reportId 或 metrics")
    prompt = "请分析以下压测指标，给出结论、瓶颈推测与改进建议：\n" + json.dumps(
        metrics, ensure_ascii=False
    )
    if report:
        prompt += f"\n来源报告：{report.get('id')} 场景：{report.get('scene')}"
    text = await ai_svc.simple(db, prompt, module="性能分析")
    return {"reportId": body.reportId or "", "metrics": metrics, "analysis": text}
