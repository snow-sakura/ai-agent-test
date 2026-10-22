"""技能中心（Skills Center）— 原子技能 /api/skills-center/*。

表前缀 skc_：skc_atomic(id,name,kind,input,output,desc,status,version,uses[,prompt])
- GET  /skills-center 与 /skills-center/atomic 列表（含分类聚合）
- POST/PUT/DELETE /skills-center/atomic
- POST /skills-center/compose   {ids, input} 按序执行 pipeline
- POST /skills-center/ai-suggest {task} AI 推荐原子技能组合

seed 对齐 UI/tool-skills-center.html（AG-08..AG-03 等）。列表不鉴权；写操作鉴权。
"""
import json
import re
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
from app.services import ai

router = APIRouter(tags=["skills-center"])


class AtomicCreate(BaseModel):
    name: str
    kind: str = "分析"
    input: str = ""
    output: str = ""
    desc: str = ""
    status: str = "启用"
    version: str = "v0.1"
    uses: int = 0
    prompt: str = ""


class AtomicUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    input: Optional[str] = None
    output: Optional[str] = None
    desc: Optional[str] = None
    status: Optional[str] = None
    version: Optional[str] = None
    prompt: Optional[str] = None


class ComposeReq(BaseModel):
    ids: List[str]
    input: str = ""


class SuggestReq(BaseModel):
    task: str


_SEED = [
    {"id": "AG-08", "name": "用例补充生成", "kind": "测试用例", "input": "已有用例/需求上下文",
     "output": "补充用例列表", "desc": "对已有用例集补充边界与异常场景", "status": "启用",
     "version": "v1.2", "uses": 96,
     "prompt": "基于 {{context}} 已有用例，补充遗漏的边界/异常场景用例，输出表格：标题/优先级/前置/步骤/预期。"},
    {"id": "AG-07", "name": "接口异常场景补全", "kind": "测试用例", "input": "接口定义/参数",
     "output": "异常组合用例", "desc": "按参数枚举生成异常组合用例", "status": "启用",
     "version": "v1.0", "uses": 74,
     "prompt": "对接口 {{input}} 的每个参数生成异常取值组合（缺失/类型错/越界/注入），输出可执行用例。"},
    {"id": "AG-06", "name": "失败日志根因分析", "kind": "分析", "input": "失败日志/错误堆栈",
     "output": "根因假设+修复建议", "desc": "聚类失败日志输出根因假设", "status": "启用",
     "version": "v1.1", "uses": 58,
     "prompt": "分析以下失败记录 {{input}}，按可能性输出根因假设、证据与修复建议（3 条内）。"},
    {"id": "AG-05", "name": "质量周报生成", "kind": "分析", "input": "执行/缺陷统计数据",
     "output": "质量周报", "desc": "汇总执行/缺陷数据生成周报", "status": "启用",
     "version": "v1.0", "uses": 41,
     "prompt": "根据 {{context}} 数据生成测试质量周报：结论 → 关键数据 → 风险 → 下周计划，不超过 8 句。"},
    {"id": "AG-04", "name": "UI 步骤脚本化", "kind": "自动化", "input": "自然语言操作步骤",
     "output": "Playwright 脚本", "desc": "自然语言步骤转 Playwright 脚本", "status": "启用",
     "version": "v0.9", "uses": 37,
     "prompt": "将 {{input}} 步骤转为 Playwright 脚本，优先 getByTestId 定位，含等待与断言。"},
    {"id": "AG-03", "name": "回归集智能筛选", "kind": "分析", "input": "代码变更/diff",
     "output": "回归用例子集", "desc": "按代码变更圈定回归范围", "status": "禁用",
     "version": "v0.6", "uses": 12,
     "prompt": "根据变更 {{input}} 圈定需回归的用例，输出必跑/可选/豁免三组。"},
    {"id": "AG-02", "name": "接口断言生成", "kind": "测试用例", "input": "接口文档/响应示例",
     "output": "断言脚本", "desc": "按接口文档自动生成状态码/Schema/业务断言", "status": "启用",
     "version": "v2.0", "uses": 142,
     "prompt": "按接口文档 {{input}} 生成断言：状态码、JSON Schema、业务 code、性能阈值。"},
    {"id": "AG-01", "name": "结果格式化", "kind": "自动化", "input": "任意上游输出",
     "output": "结构化 JSON", "desc": "本地原子：把上游输出规整为标准 JSON 结果（无 AI 调用）",
     "status": "启用", "version": "v1.0", "uses": 210, "prompt": ""},
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


async def ensure_schema(db: SyncDB) -> None:
    await db_execute(
        db,
        """
    CREATE TABLE IF NOT EXISTS skc_atomic (
        id TEXT PRIMARY KEY, name TEXT, kind TEXT, input_t TEXT, output_t TEXT,
        descr TEXT, status TEXT, version TEXT, uses INTEGER DEFAULT 0, prompt TEXT
    )""",
    )
    await db_commit(db)


async def seed_if_empty(db: SyncDB) -> None:
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM skc_atomic", [])
    if row and row["c"]:
        return
    for a in _SEED:
        await db_insert(db, "skc_atomic", {
            "id": a["id"], "name": a["name"], "kind": a["kind"],
            "input_t": a["input"], "output_t": a["output"], "descr": a["desc"],
            "status": a["status"], "version": a["version"], "uses": a["uses"],
            "prompt": a["prompt"],
        })
    await db_commit(db)


async def _prepare(db: SyncDB) -> None:
    await ensure_schema(db)
    await seed_if_empty(db)


def _row(r: dict) -> dict:
    return {
        "id": r.get("id"), "name": r.get("name"), "kind": r.get("kind"),
        "input": r.get("input_t") or "", "output": r.get("output_t") or "",
        "desc": r.get("descr") or "", "status": r.get("status") or "启用",
        "version": r.get("version") or "v0.1", "uses": r.get("uses") or 0,
        "prompt": r.get("prompt") or "",
    }


async def _load(db: SyncDB, aid: str) -> dict:
    row = await db_fetch_one(db, "SELECT * FROM skc_atomic WHERE id=?", [aid])
    if not row:
        raise HTTPException(status_code=404, detail="atomic skill not found")
    return row


async def _next_id(db: SyncDB) -> str:
    rows = await db_fetch_all(db, "SELECT id FROM skc_atomic WHERE id LIKE 'AG-%'", [])
    best = 0
    for r in rows:
        try:
            best = max(best, int(str(r["id"]).split("-")[-1]))
        except Exception:
            pass
    return "AG-%02d" % (best + 1)


@router.get("/skills-center")
async def list_atomic_alias(db: SyncDB = Depends(get_db)):
    return await _list_atomic(db)


@router.get("/skills-center/atomic")
async def list_atomic(db: SyncDB = Depends(get_db)):
    return await _list_atomic(db)


async def _list_atomic(db: SyncDB) -> dict:
    await _prepare(db)
    rows = await db_fetch_all(db, "SELECT * FROM skc_atomic ORDER BY id DESC", [])
    items = [_row(r) for r in rows]
    kinds = {}
    for it in items:
        kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
    return {
        "items": items,
        "total": len(items),
        "enabled": sum(1 for i in items if i["status"] == "启用"),
        "kinds": [{"kind": k, "count": v} for k, v in sorted(kinds.items(), key=lambda x: -x[1])],
        "totalUses": sum(i["uses"] for i in items),
    }


@router.post("/skills-center/atomic")
async def create_atomic(body: AtomicCreate, db: SyncDB = Depends(get_db),
                        current_user: dict = Depends(get_current_user)):
    await _prepare(db)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="name required")
    aid = await _next_id(db)
    await db_insert(db, "skc_atomic", {
        "id": aid, "name": body.name.strip(), "kind": body.kind,
        "input_t": body.input, "output_t": body.output, "descr": body.desc,
        "status": body.status, "version": body.version, "uses": body.uses,
        "prompt": body.prompt,
    })
    return _row(await _load(db, aid))


@router.put("/skills-center/atomic/{aid}")
async def update_atomic(aid: str, body: AtomicUpdate, db: SyncDB = Depends(get_db),
                        current_user: dict = Depends(get_current_user)):
    await _prepare(db)
    await _load(db, aid)
    data = {}
    for k, v in (("name", body.name), ("kind", body.kind),
                 ("input_t", body.input), ("output_t", body.output),
                 ("status", body.status), ("version", body.version),
                 ("prompt", body.prompt)):
        if v is not None:
            data[k] = v
    if body.desc is not None:
        data["descr"] = body.desc
    if data:
        await db_update(db, "skc_atomic", data, "id=?", [aid])
    return _row(await _load(db, aid))


@router.delete("/skills-center/atomic/{aid}")
async def delete_atomic(aid: str, db: SyncDB = Depends(get_db),
                        current_user: dict = Depends(get_current_user)):
    await _prepare(db)
    await _load(db, aid)
    await db_delete(db, "skc_atomic", "id=?", [aid])
    return {"ok": True, "id": aid}


# ---------------------------------------------------------------------------
# 组合执行 pipeline
# ---------------------------------------------------------------------------

_LOCAL_KIND = "本地"


def _local_exec(name: str, prompt: str, data: str) -> str:
    """无 prompt 的本地原子：确定性处理，保证 pipeline 全离线可跑。"""
    if "格式化" in name or "JSON" in (name or "").upper():
        try:
            obj = json.loads(data)
            return json.dumps(obj, ensure_ascii=False, indent=2)
        except Exception:
            return json.dumps(
                {"ok": True, "data": data, "formattedAt": _now()},
                ensure_ascii=False, indent=2,
            )
    return f"[本地:{name}] " + (data or "")[:500]


@router.post("/skills-center/compose")
async def compose(body: ComposeReq, db: SyncDB = Depends(get_db)):
    await _prepare(db)
    if not body.ids:
        raise HTTPException(status_code=400, detail="ids required")
    steps = []
    current = body.input or ""
    for aid in body.ids:
        row = await db_fetch_one(db, "SELECT * FROM skc_atomic WHERE id=?", [aid])
        if not row:
            raise HTTPException(status_code=404, detail=f"atomic skill not found: {aid}")
        name = row.get("name") or ""
        prompt = row.get("prompt") or ""
        if not prompt:
            out = _local_exec(name, prompt, current)
        else:
            sys_prompt = prompt.replace("{{input}}", current or "").replace(
                "{{context}}", current or "")
            out = await ai.simple(
                db,
                f"上游输入：\n{(current or '（空）')[:4000]}\n\n请按技能「{name}」规则处理并输出。",
                system=sys_prompt[:2000],
                module="技能中心",
            )
        await db_update(db, "skc_atomic", {"uses": (row.get("uses") or 0) + 1},
                        "id=?", [aid])
        steps.append({
            "id": aid, "name": name, "kind": row.get("kind"),
            "output": out,
        })
        current = out
    return {
        "ok": True,
        "pipeline": [{"id": s["id"], "name": s["name"], "kind": s["kind"]} for s in steps],
        "steps": steps,
        "output": current,
    }


# ---------------------------------------------------------------------------
# AI 推荐组合
# ---------------------------------------------------------------------------

_KB_HINTS = [
    (["用例", "补充", "边界", "异常"], ["AG-08", "AG-07"]),
    (["接口", "断言", "schema"], ["AG-02", "AG-07"]),
    (["日志", "失败", "根因", "崩溃", "归因"], ["AG-06", "AG-05"]),
    (["周报", "报告", "汇总"], ["AG-05"]),
    (["ui", "脚本", "playwright", "自动化", "步骤"], ["AG-04"]),
    (["回归", "变更", "影响"], ["AG-03", "AG-08"]),
]


def _local_suggest(task: str) -> List[str]:
    t = (task or "").lower()
    hits: List[str] = []
    for kws, ids in _KB_HINTS:
        if any(k in t for k in kws):
            for i in ids:
                if i not in hits:
                    hits.append(i)
    if not hits:
        hits = ["AG-08", "AG-05"]
    if "格式" in task or "json" in t:
        hits.append("AG-01")
    return hits[:5]


@router.post("/skills-center/ai-suggest")
async def ai_suggest(body: SuggestReq, db: SyncDB = Depends(get_db)):
    await _prepare(db)
    task = (body.task or "").strip()
    if not task:
        raise HTTPException(status_code=400, detail="task required")
    rows = await db_fetch_all(db, "SELECT * FROM skc_atomic", [])
    catalog = "\n".join(
        f"- {r['id']} {r['name']}（{r['kind']}）：{r.get('descr') or ''}" for r in rows
    )
    fallback = _local_suggest(task)
    try:
        data = await ai.chat_json(
            db,
            [
                {"role": "system", "content":
                    "你是测试平台技能编排助手。从给定原子技能目录中挑选 2-5 个组成执行链，"
                    "按执行顺序输出 JSON：{\"ids\":[\"AG-xx\",...],\"reason\":\"一句话\"}。"
                    "只能使用目录中存在的 id。"},
                {"role": "user", "content": f"任务：{task}\n\n原子技能目录：\n{catalog}"},
            ],
            module="技能中心",
        )
        ids = [str(i) for i in (data.get("ids") or []) if i]
        valid = {r["id"] for r in rows}
        ids = [i for i in ids if i in valid] or fallback
        reason = str(data.get("reason") or "")
    except Exception:
        ids = fallback
        reason = "（本地关键词匹配，AI 服务不可用）"
    named = []
    by_id = {r["id"]: r for r in rows}
    for i in ids:
        r = by_id.get(i)
        if r:
            named.append({"id": i, "name": r.get("name"), "kind": r.get("kind")})
    return {"ids": ids, "steps": named, "reason": reason, "task": task}
