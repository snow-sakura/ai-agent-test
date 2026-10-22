"""技能库（Skill Library）— /api/skills/*。

表前缀 skl_：skl_skills(id,name,icon,cat,desc,uses,stars,status,version,author,updated,content,params)
首次访问自动建表 + 空库 seed ≥8 条 UI 演示技能（UI/tool-skill-library.html）。
列表/查询不鉴权；写操作鉴权；run/star 演示可用不鉴权。
"""
import json
import random
from datetime import datetime
from typing import List, Optional

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
from app.services import ai, telemetry

router = APIRouter(tags=["skill-library"])


class SkillCreate(BaseModel):
    name: str
    icon: str = "🧩"
    cat: str = "用例设计"
    desc: str = ""
    status: str = "草稿"
    version: str = "v0.1"
    author: str = "demo"
    content: str = ""
    params: dict = {}
    stars: int = 0
    uses: int = 0


class SkillUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    cat: Optional[str] = None
    desc: Optional[str] = None
    status: Optional[str] = None
    version: Optional[str] = None
    content: Optional[str] = None
    params: Optional[dict] = None


class RunReq(BaseModel):
    input: str = ""


# 关键词 → 技能匹配（assistant 复用）
_MATCH_RULES = [
    {"kw": ["用例", "测试点", "设计", "case"], "id": "SK-01"},
    {"kw": ["断言", "接口", "schema", "assert"], "id": "SK-02"},
    {"kw": ["安全", "漏洞", "注入", "越权", "owasp"], "id": "SK-03"},
    {"kw": ["压测", "qps", "性能", "并发", "瓶颈"], "id": "SK-04"},
    {"kw": ["崩溃", "堆栈", "npe", "异常", "日志", "归因"], "id": "SK-05"},
    {"kw": ["自动化", "脚本", "selenium", "appium", "playwright"], "id": "SK-06"},
    {"kw": ["回归", "影响面", "变更"], "id": "SK-07"},
    {"kw": ["报告", "周报", "质量"], "id": "SK-08"},
]

_SEED = [
    {"id": "SK-01", "name": "退款需求→用例技能包", "icon": "🧾", "cat": "用例设计",
     "desc": "解析退款类需求，输出功能+边界+异常用例集", "uses": 86, "stars": 12,
     "status": "已发布", "version": "v1.3", "author": "li-qa", "updated": "2026-09-18",
     "content": "你是一名资深测试工程师。解析输入的退款类需求，输出结构化测试用例：\n1. 主流程（正常退款）\n2. 边界（金额/字数/超时）\n3. 异常（未选原因、审核拒绝、重复提交）\n每条含：标题/优先级/前置条件/步骤/预期结果。表格输出。",
     "params": {"tools": ["用例生成", "数据工厂"], "maxCases": 20}},
    {"id": "SK-02", "name": "接口断言生成技能", "icon": "🔗", "cat": "接口测试",
     "desc": "按接口文档自动生成状态码/Schema/业务断言", "uses": 142, "stars": 20,
     "status": "已发布", "version": "v2.0", "author": "api-qa", "updated": "2026-09-20",
     "content": "根据接口文档/示例响应生成断言：\n1. 状态码断言\n2. JSON Schema（必填字段与类型）\n3. 业务断言（code、分页、金额一致性）\n4. 性能断言（P99 阈值）\n输出可直接粘贴到接口测试的断言脚本。",
     "params": {"tools": ["接口测试"]}},
    {"id": "SK-03", "name": "安全基线核查技能", "icon": "🛡️", "cat": "安全测试",
     "desc": "按 OWASP Top 10 逐项核查并输出修复建议", "uses": 57, "stars": 9,
     "status": "已发布", "version": "v1.1", "author": "sec-qa", "updated": "2026-09-15",
     "content": "按 OWASP Top 10 对目标模块做基线核查：访问控制、加密、注入、配置错误、认证等。输出：检查项/结论（通过|不通过|建议）/风险等级/修复建议。",
     "params": {"tools": ["安全基线", "缺陷查重"]}},
    {"id": "SK-04", "name": "性能瓶颈定位技能", "icon": "📈", "cat": "性能测试",
     "desc": "结合压测曲线与慢日志给出瓶颈假设与调优建议", "uses": 34, "stars": 7,
     "status": "已发布", "version": "v1.0", "author": "perf-qa", "updated": "2026-09-12",
     "content": "输入压测指标（QPS/P99/错误率）与慢日志摘要，输出：\n1. 瓶颈假设（按可能性排序）\n2. 证据引用\n3. 调优建议（连接池/缓存/索引/扩容）\n4. 复测方案。",
     "params": {"tools": ["性能分析"]}},
    {"id": "SK-05", "name": "崩溃日志归因技能", "icon": "🩺", "cat": "缺陷分析",
     "desc": "聚类崩溃堆栈，定位可疑模块并建议排查方向", "uses": 12, "stars": 5,
     "status": "草稿", "version": "v0.4", "author": "app-qa", "updated": "2026-09-10",
     "content": "对崩溃堆栈/错误日志聚类分析：按异常类型与关键帧分组，输出占比、可疑模块、根因假设与排查步骤。",
     "params": {"tools": ["缺陷查重"]}},
    {"id": "SK-06", "name": "自动化脚本生成技能", "icon": "🤖", "cat": "自动化",
     "desc": "按操作步骤生成 Selenium / Appium 脚本骨架", "uses": 5, "stars": 3,
     "status": "草稿", "version": "v0.2", "author": "auto-qa", "updated": "2026-09-05",
     "content": "把自然语言操作步骤转为 Selenium/Appium/Playwright 脚本骨架，优先 data-testid 定位，含等待与断言。",
     "params": {"tools": ["用例生成"]}},
    {"id": "SK-07", "name": "回归影响面圈定技能", "icon": "🎯", "cat": "用例设计",
     "desc": "按代码变更 diff 圈定需回归的用例范围", "uses": 48, "stars": 8,
     "status": "已发布", "version": "v1.2", "author": "li-qa", "updated": "2026-09-16",
     "content": "输入变更模块/diff 摘要，映射到模块-用例矩阵，输出：必跑用例、可选用例、风险豁免项，控制回归成本。",
     "params": {"tools": ["用例生成"]}},
    {"id": "SK-08", "name": "测试周报生成技能", "icon": "📊", "cat": "缺陷分析",
     "desc": "汇总执行/缺陷数据生成质量周报摘要", "uses": 63, "stars": 6,
     "status": "已发布", "version": "v1.0", "author": "li-qa", "updated": "2026-09-19",
     "content": "输入本周执行数/通过率/缺陷分布，输出周报：总体结论、关键数据、Top 风险、下周建议（3 句内可直接粘贴）。",
     "params": {"tools": ["用例生成"]}},
]

_USAGE_SEED = [
    {"time": "2026-09-22 09:12", "skill": "接口断言生成技能", "by": "AI 问答助手", "scene": "接口测试 · /v1/pay", "dur": "3.2s", "result": "成功"},
    {"time": "2026-09-22 08:40", "skill": "退款需求→用例技能包", "by": "AI 用例工作台", "scene": "REQ-2026-0125", "dur": "8.6s", "result": "成功"},
    {"time": "2026-09-21 17:22", "skill": "安全基线核查技能", "by": "AI 问答助手", "scene": "支付模块扫描", "dur": "12.4s", "result": "成功"},
    {"time": "2026-09-21 15:03", "skill": "性能瓶颈定位技能", "by": "AI 问答助手", "scene": "秒杀下单链路", "dur": "15.1s", "result": "成功"},
    {"time": "2026-09-20 11:48", "skill": "崩溃日志归因技能", "by": "AI 问答助手", "scene": "APP 崩溃聚类", "dur": "9.8s", "result": "失败"},
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


async def ensure_schema(db: SyncDB) -> None:
    await db_execute(
        db,
        """
    CREATE TABLE IF NOT EXISTS skl_skills (
        id TEXT PRIMARY KEY, name TEXT, icon TEXT, cat TEXT, descr TEXT,
        uses INTEGER DEFAULT 0, stars INTEGER DEFAULT 0, status TEXT,
        version TEXT, author TEXT, updated TEXT, content TEXT, params TEXT
    )""",
    )
    await db_execute(
        db,
        """
    CREATE TABLE IF NOT EXISTS skl_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time TEXT, skill TEXT, by_user TEXT, scene TEXT, dur TEXT, result TEXT
    )""",
    )
    await db_commit(db)


async def seed_if_empty(db: SyncDB) -> None:
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM skl_skills", [])
    if row and row["c"]:
        return
    for s in _SEED:
        await db_insert(db, "skl_skills", {
            "id": s["id"], "name": s["name"], "icon": s["icon"], "cat": s["cat"],
            "descr": s["desc"], "uses": s["uses"], "stars": s["stars"],
            "status": s["status"], "version": s["version"], "author": s["author"],
            "updated": s["updated"], "content": s["content"],
            "params": json.dumps(s["params"], ensure_ascii=False),
        })
    for u in _USAGE_SEED:
        await db_insert(db, "skl_usage", {
            "time": u["time"], "skill": u["skill"], "by_user": u["by"],
            "scene": u["scene"], "dur": u["dur"], "result": u["result"],
        })
    await db_commit(db)


async def _prepare(db: SyncDB) -> None:
    await ensure_schema(db)
    await seed_if_empty(db)


def _row(r: dict) -> dict:
    params = r.get("params") or "{}"
    try:
        params = json.loads(params) if isinstance(params, str) else params
    except Exception:
        params = {}
    return {
        "id": r.get("id"), "name": r.get("name"), "icon": r.get("icon") or "🧩",
        "cat": r.get("cat"), "desc": r.get("descr") or "", "uses": r.get("uses") or 0,
        "stars": r.get("stars") or 0, "status": r.get("status") or "草稿",
        "version": r.get("version") or "v0.1", "author": r.get("author") or "",
        "updated": r.get("updated") or "", "content": r.get("content") or "",
        "params": params,
    }


async def _load(db: SyncDB, skill_id: str) -> dict:
    row = await db_fetch_one(db, "SELECT * FROM skl_skills WHERE id=?", [skill_id])
    if not row:
        raise HTTPException(status_code=404, detail="skill not found")
    return row


async def match_skill(db: SyncDB, content: str) -> Optional[dict]:
    """简单关键词打分，返回最匹配技能行（带 _score）。"""
    c = (content or "").lower()
    best, best_sc = None, 0
    for rule in _MATCH_RULES:
        sc = sum(2 for k in rule["kw"] if k in c)
        if sc > best_sc:
            best, best_sc = rule, sc
    if not best:
        return None
    row = await db_fetch_one(db, "SELECT * FROM skl_skills WHERE id=?", [best["id"]])
    if not row:
        return None
    row = dict(row)
    row["_score"] = round(min(0.99, 0.6 + best_sc * 0.1), 2)
    return row


@router.get("/skills")
async def list_skills(cat: str = "", q: str = "", db: SyncDB = Depends(get_db)):
    await _prepare(db)
    rows = await db_fetch_all(db, "SELECT * FROM skl_skills ORDER BY uses DESC", [])
    items = [_row(r) for r in rows]
    if cat:
        items = [x for x in items if x["cat"] == cat]
    if q:
        ql = q.lower()
        items = [x for x in items if ql in (x["name"] + x["desc"]).lower()]
    cats = {}
    for r in rows:
        cats[r.get("cat") or "其他"] = cats.get(r.get("cat") or "其他", 0) + 1
    return {
        "items": items,
        "total": len(items),
        "cats": [{"cat": k, "count": v} for k, v in sorted(cats.items(), key=lambda x: -x[1])],
    }


@router.get("/skills/usage/stats")
async def usage_stats(db: SyncDB = Depends(get_db)):
    await _prepare(db)
    rows = await db_fetch_all(db, "SELECT * FROM skl_skills ORDER BY uses DESC", [])
    total_uses = sum((r.get("uses") or 0) for r in rows)
    total_stars = sum((r.get("stars") or 0) for r in rows)
    cats = {}
    for r in rows:
        cats[r.get("cat") or "其他"] = cats.get(r.get("cat") or "其他", 0) + 1
    usages = await db_fetch_all(db, "SELECT * FROM skl_usage ORDER BY id DESC LIMIT 20", [])
    ok = sum(1 for u in usages if (u.get("result") or "") == "成功")
    return {
        "totalSkills": len(rows),
        "totalUses": total_uses,
        "totalStars": total_stars,
        "byCat": [{"cat": k, "count": v} for k, v in sorted(cats.items(), key=lambda x: -x[1])],
        "top": [{"id": r.get("id"), "name": r.get("name"), "uses": r.get("uses") or 0,
                 "cat": r.get("cat")} for r in rows[:5]],
        "recent": [{"time": u.get("time"), "skill": u.get("skill"), "by": u.get("by_user"),
                    "scene": u.get("scene"), "dur": u.get("dur"), "result": u.get("result")}
                   for u in usages],
        "successRate": round(ok * 100.0 / len(usages), 1) if usages else 0,
    }


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str, db: SyncDB = Depends(get_db)):
    await _prepare(db)
    return _row(await _load(db, skill_id))


@router.post("/skills")
async def create_skill(body: SkillCreate, db: SyncDB = Depends(get_db),
                       current_user: dict = Depends(get_current_user)):
    await _prepare(db)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="name required")
    rows = await db_fetch_all(db, "SELECT id FROM skl_skills WHERE id LIKE 'SK-%'", [])
    best = 0
    for r in rows:
        try:
            best = max(best, int(str(r["id"]).split("-")[-1]))
        except Exception:
            pass
    sid = "SK-%02d" % (best + 1)
    await db_insert(db, "skl_skills", {
        "id": sid, "name": body.name.strip(), "icon": body.icon, "cat": body.cat,
        "descr": body.desc, "uses": body.uses, "stars": body.stars,
        "status": body.status, "version": body.version, "author": body.author,
        "updated": _now(), "content": body.content,
        "params": json.dumps(body.params, ensure_ascii=False),
    })
    return _row(await _load(db, sid))


@router.put("/skills/{skill_id}")
async def update_skill(skill_id: str, body: SkillUpdate, db: SyncDB = Depends(get_db),
                       current_user: dict = Depends(get_current_user)):
    await _prepare(db)
    await _load(db, skill_id)
    data = {}
    mapping = {"name": body.name, "icon": body.icon, "cat": body.cat,
               "status": body.status, "version": body.version, "content": body.content}
    for k, v in mapping.items():
        if v is not None:
            data[k] = v
    if body.desc is not None:
        data["descr"] = body.desc
    if body.params is not None:
        data["params"] = json.dumps(body.params, ensure_ascii=False)
    data["updated"] = _now()
    await db_update(db, "skl_skills", data, "id=?", [skill_id])
    return _row(await _load(db, skill_id))


@router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str, db: SyncDB = Depends(get_db),
                       current_user: dict = Depends(get_current_user)):
    await _prepare(db)
    await _load(db, skill_id)
    await db_delete(db, "skl_skills", "id=?", [skill_id])
    return {"ok": True, "id": skill_id}


@router.post("/skills/{skill_id}/run")
async def run_skill(skill_id: str, body: RunReq, db: SyncDB = Depends(get_db)):
    await _prepare(db)
    skill = await _load(db, skill_id)
    input_text = (body.input or "").strip() or f"请演示技能「{skill.get('name')}」的输出。"
    system = str(skill.get("content") or "") or (
        f"你是测试技能「{skill.get('name')}」，按描述执行任务并输出结构化结果。"
    )
    params = skill.get("params") or "{}"
    try:
        params = json.loads(params) if isinstance(params, str) else {}
    except Exception:
        params = {}
    prompt = f"【技能参数】{json.dumps(params, ensure_ascii=False)}\n\n【输入】{input_text}"
    started = datetime.now()
    output = await ai.simple(db, prompt, system=system, module="技能库")
    dur = max(1, int((datetime.now() - started).total_seconds() * 1000))
    tokens = telemetry.estimate_tokens(output)
    await db_update(db, "skl_skills", {"uses": (skill.get("uses") or 0) + 1,
                                       "updated": _now()}, "id=?", [skill_id])
    await db_insert(db, "skl_usage", {
        "time": _now(), "skill": skill.get("name"), "by_user": "手动调用",
        "scene": str(skill.get("cat") or ""), "dur": f"{dur / 1000:.1f}s",
        "result": "成功",
    })
    return {"output": output, "tokens": tokens, "skillId": skill_id,
            "skillName": skill.get("name")}


@router.post("/skills/{skill_id}/star")
async def star_skill(skill_id: str, db: SyncDB = Depends(get_db)):
    await _prepare(db)
    skill = await _load(db, skill_id)
    stars = (skill.get("stars") or 0) + 1
    await db_update(db, "skl_skills", {"stars": stars}, "id=?", [skill_id])
    return {"ok": True, "id": skill_id, "stars": stars}
