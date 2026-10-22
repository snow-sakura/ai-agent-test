"""AI 报告中心（Reports）— /api/reports/*。

表前缀 rep_：rep_reports(id,name,type,model,passRate,total,blocked,high,mid,low,
risk,summary,created_by,created_at,detail)

- GET  /reports?type=&q=   列表（detail 存 desc/status/dur 等 UI 扩展字段 JSON）
- GET  /reports/{id}       详情（/reports/stats 先注册避免被 {id} 吞掉）
- POST /reports/generate   AI 生成 summary + 随机合理指标入库
- DELETE /reports/{id}
- GET  /reports/stats      总数 / 平均通过率 / 风险分布

seed 4 条（功能/性能/安全/回归，取自 UI/tool-ai-reports.html）。列表不鉴权；写操作鉴权。
"""
import json
import random
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.database import (
    SyncDB,
    get_db,
    db_commit,
    db_delete,
    db_execute,
    db_fetch_all,
    db_fetch_one,
    db_insert,
    db_update,
)
from app.core.deps import get_current_user
from app.services import ai

router = APIRouter(tags=["reports"])


class GenerateReq(BaseModel):
    type: str = "功能测试报告"
    scope: str = ""
    model: str = ""


_SEED = [
    {
        "id": "AR-21", "name": "9 月第 3 周回归测试报告", "type": "回归测试报告",
        "model": "DeepSeek-V3", "passRate": 100.0, "total": 12, "blocked": 0,
        "high": 0, "mid": 0, "low": 0, "risk": "低",
        "summary": "本轮回归 12/12 通过，P99 320ms。无新增缺陷。风险提示：验证码接口弱网超时率 2.1%，建议纳入下轮专项。",
        "created_by": "li-qa", "created_at": "2026-09-22 02:35",
        "detail": {"desc": "支付核心链路回归（12 条）", "status": "已生成", "dur": "35s"},
    },
    {
        "id": "AR-19", "name": "秒杀链路压测报告", "type": "性能测试报告",
        "model": "DeepSeek-V3", "passRate": 75.0, "total": 40, "blocked": 1,
        "high": 2, "mid": 1, "low": 0, "risk": "高",
        "summary": "目标 6000 QPS 实测 4500 后错误率 3.2%。瓶颈：DB 连接池打满。建议扩容连接池至 200 并开启读写分离。",
        "created_by": "perf-qa", "created_at": "2026-09-20 18:12",
        "detail": {"desc": "阶梯压测 500→6000 QPS", "status": "已生成", "dur": "41s"},
    },
    {
        "id": "AR-18", "name": "支付模块安全周报", "type": "安全测试报告",
        "model": "DeepSeek-V3", "passRate": 92.0, "total": 48, "blocked": 0,
        "high": 0, "mid": 1, "low": 2, "risk": "中",
        "summary": "基线通过率 92%，新增 1 项中危：接口限流缺失。AI 修复建议已生成，复验用例已创建。",
        "created_by": "sec-qa", "created_at": "2026-09-19 04:10",
        "detail": {"desc": "OWASP 基线扫描", "status": "已生成", "dur": "38s"},
    },
    {
        "id": "AR-20", "name": "主站冒烟日报 0921", "type": "功能测试报告",
        "model": "通义千问-Max", "passRate": 80.0, "total": 5, "blocked": 0,
        "high": 1, "mid": 0, "low": 0, "risk": "中",
        "summary": "5 场景通过 4 个，场景 3 支付按钮元素未找到。已提缺陷 BUG-2049（P1），疑似前端改版未同步定位脚本。",
        "created_by": "auto-qa", "created_at": "2026-09-21 16:30",
        "detail": {"desc": "UI 冒烟 5 场景", "status": "已生成", "dur": "28s"},
    },
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


async def ensure_schema(db: SyncDB) -> None:
    await db_execute(
        db,
        """
    CREATE TABLE IF NOT EXISTS rep_reports (
        id TEXT PRIMARY KEY, name TEXT, type TEXT, model TEXT,
        passRate REAL, total INTEGER, blocked INTEGER,
        high INTEGER, mid INTEGER, low INTEGER, risk TEXT,
        summary TEXT, created_by TEXT, created_at TEXT, detail TEXT
    )""",
    )
    await db_commit(db)


async def seed_if_empty(db: SyncDB) -> None:
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM rep_reports", [])
    if row and row["c"]:
        return
    for r in _SEED:
        data = dict(r)
        detail = data.pop("detail")
        data["detail"] = json.dumps(
            {**detail, "defects": (r["high"] + r["mid"] + r["low"])},
            ensure_ascii=False,
        )
        await db_insert(db, "rep_reports", data)
    await db_commit(db)


async def _prepare(db: SyncDB) -> None:
    await ensure_schema(db)
    await seed_if_empty(db)


def _row(r: dict) -> dict:
    detail = r.get("detail") or "{}"
    try:
        detail = json.loads(detail) if isinstance(detail, str) else detail
    except Exception:
        detail = {}
    pass_rate = r.get("passRate")
    return {
        "id": r.get("id"), "name": r.get("name") or "", "type": r.get("type") or "",
        "model": r.get("model") or "", "passRate": pass_rate,
        "pass": ("—" if pass_rate is None else f"{pass_rate:g}%"),
        "total": r.get("total") or 0, "blocked": r.get("blocked") or 0,
        "high": r.get("high") or 0, "mid": r.get("mid") or 0, "low": r.get("low") or 0,
        "defects": (r.get("high") or 0) + (r.get("mid") or 0) + (r.get("low") or 0),
        "risk": r.get("risk") or "低", "summary": r.get("summary") or "",
        "createdBy": r.get("created_by") or "", "createdAt": r.get("created_at") or "",
        "created": r.get("created_at") or "",
        "desc": detail.get("desc") or "", "status": detail.get("status") or "已生成",
        "dur": detail.get("dur") or "—", "detail": detail,
    }


async def _load(db: SyncDB, rid: str) -> dict:
    row = await db_fetch_one(db, "SELECT * FROM rep_reports WHERE id=?", [rid])
    if not row:
        raise HTTPException(status_code=404, detail="report not found")
    return row


async def _next_id(db: SyncDB) -> str:
    rows = await db_fetch_all(db, "SELECT id FROM rep_reports WHERE id LIKE 'AR-%'", [])
    best = 0
    for r in rows:
        try:
            best = max(best, int(str(r["id"]).split("-")[-1]))
        except Exception:
            pass
    return "AR-%02d" % (best + 1)


@router.get("/reports")
async def list_reports(type: str = "", q: str = "", db: SyncDB = Depends(get_db)):
    await _prepare(db)
    rows = await db_fetch_all(db, "SELECT * FROM rep_reports ORDER BY id DESC", [])
    items = [_row(r) for r in rows]
    if type:
        items = [x for x in items if x["type"] == type]
    if q:
        ql = q.lower()
        items = [x for x in items
                 if ql in (x["name"] + x["summary"] + x["desc"]).lower()]
    return {"items": items, "total": len(items)}


# 注意：/reports/stats 必须注册在 /reports/{rid} 之前
@router.get("/reports/stats")
async def report_stats(db: SyncDB = Depends(get_db)):
    await _prepare(db)
    rows = await db_fetch_all(db, "SELECT * FROM rep_reports", [])
    items = [_row(r) for r in rows]
    total = len(items)
    rates = [x["passRate"] for x in items if isinstance(x["passRate"], (int, float))]
    risk_dist = {"高": 0, "中": 0, "低": 0}
    type_dist = {}
    for x in items:
        risk_dist[x["risk"]] = risk_dist.get(x["risk"], 0) + 1
        type_dist[x["type"]] = type_dist.get(x["type"], 0) + 1
    return {
        "total": total,
        "avgPassRate": round(sum(rates) / len(rates), 1) if rates else 0,
        "riskDist": [{"risk": k, "count": risk_dist[k]} for k in ("高", "中", "低")],
        "typeDist": [{"type": k, "count": v} for k, v in type_dist.items()],
        "totalCases": sum(x["total"] for x in items),
        "totalDefects": sum(x["defects"] for x in items),
        "highRisk": risk_dist["高"],
    }


@router.get("/reports/{rid}")
async def get_report(rid: str, db: SyncDB = Depends(get_db)):
    await _prepare(db)
    return _row(await _load(db, rid))


@router.post("/reports/generate")
async def generate_report(body: GenerateReq, db: SyncDB = Depends(get_db),
                          current_user: dict = Depends(get_current_user)):
    await _prepare(db)
    rtype = (body.type or "功能测试报告").strip()
    scope = (body.scope or "").strip() or f"{rtype}范围（演示）"

    total = random.randint(24, 120)
    blocked = random.randint(0, 3)
    high = random.randint(0, 2)
    mid = random.randint(0, 3)
    low = random.randint(0, 4)
    passed = max(0, total - blocked - random.randint(0, high + mid + 2))
    pass_rate = round(passed * 100.0 / total, 1)
    if high >= 2 or pass_rate < 80:
        risk = "高"
    elif high >= 1 or mid >= 2 or pass_rate < 92:
        risk = "中"
    else:
        risk = "低"

    prompt = (
        f"请为以下测试范围生成一段 120 字以内的测试报告摘要（结论 → 关键数据 → 风险 → 建议，"
        f"不要标题与 markdown 符号）：\n"
        f"报告类型：{rtype}\n范围：{scope}\n"
        f"执行 {total} 条，通过率 {pass_rate}%，阻塞 {blocked}，"
        f"缺陷 高{high}/中{mid}/低{low}，整体风险：{risk}。"
    )
    try:
        summary = await ai.simple(db, prompt, module="AI报告",
                                  model=body.model or None)
    except Exception as exc:  # noqa: BLE001
        summary = f"执行 {total} 条，通过率 {pass_rate}%，风险 {risk}（AI 降级：{exc}）"
    summary = (summary or "").strip()[:1000]

    rid = await _next_id(db)
    name = f"{scope[:18]} · {rtype}"
    detail = {"desc": scope, "status": "已生成", "dur": f"{random.randint(18, 60)}s"}
    await db_insert(db, "rep_reports", {
        "id": rid, "name": name, "type": rtype,
        "model": body.model or "默认", "passRate": pass_rate, "total": total,
        "blocked": blocked, "high": high, "mid": mid, "low": low, "risk": risk,
        "summary": summary, "created_by": (current_user or {}).get("username") or "demo",
        "created_at": _now(),
        "detail": json.dumps(detail, ensure_ascii=False),
    })
    return _row(await _load(db, rid))


@router.delete("/reports/{rid}")
async def delete_report(rid: str, db: SyncDB = Depends(get_db),
                        current_user: dict = Depends(get_current_user)):
    await _prepare(db)
    await _load(db, rid)
    await db_delete(db, "rep_reports", "id=?", [rid])
    return {"ok": True, "id": rid}
