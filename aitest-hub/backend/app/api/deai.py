"""去AI味（DeAI Flavor）— /api/deai/*

策略 CRUD 落 `deai_policies` 表；每次变更同步镜像到 cfg_kv["deai_policies"]，
使 ai.get_deai_suffix 能在全站 AI 调用时读取启用策略的后缀。
"""

import json
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
from app.services.ai import ensure_config_kv, simple

router = APIRouter(tags=["deai"])

_KV_KEY = "deai_policies"

_SEED = [
    {
        "id": "DA-05",
        "name": "口语化人味",
        "desc": "消除排比与模板腔，贴近测试同学日常表达",
        "status": "启用",
        "scope": ["测试用例", "测试报告"],
        "created": "2026-09-20",
        "uses": 156,
        "trigger": "全部",
        "suffix": "避免排比句、总-分-总结构与「首先/其次/最后」模板词；用测试同学的口吻，短句为主，可直接说结果；不得出现「综上所述」。",
    },
    {
        "id": "DA-04",
        "name": "测试术语规范化",
        "desc": "统一用例措辞：验证/校验/预期结果表述",
        "status": "启用",
        "scope": ["测试用例"],
        "created": "2026-09-16",
        "uses": 203,
        "trigger": "生成后处理",
        "suffix": "统一动词为「验证/校验」；预期结果用「系统应…」句式；禁止模糊词（大概、基本上、可能）。",
    },
    {
        "id": "DA-03",
        "name": "简报压缩",
        "desc": "报告结论压缩至 3 句内，只留结论与风险",
        "status": "启用",
        "scope": ["测试报告"],
        "created": "2026-09-10",
        "uses": 88,
        "trigger": "全部",
        "suffix": "输出压缩为不超过 3 句：结论 → 关键数据 → 风险；删除过程性描述与重复修饰。",
    },
    {
        "id": "DA-02",
        "name": "缺陷描述客观化",
        "desc": "去除情绪化与推测性表述，只留事实",
        "status": "禁用",
        "scope": ["缺陷描述"],
        "created": "2026-09-05",
        "uses": 34,
        "trigger": "全部",
        "suffix": "只陈述观察到的现象、复现步骤与影响范围；禁止推测原因（除非有证据）；禁止主观形容。",
    },
    {
        "id": "DA-01",
        "name": "英文报告口吻",
        "desc": "面向海外团队的英文测试报告措辞",
        "status": "禁用",
        "scope": ["测试报告"],
        "created": "2026-08-28",
        "uses": 12,
        "trigger": "全部",
        "suffix": "Use concise QA report tone; state facts and impact; avoid hedging phrases.",
    },
]


class PolicyBody(BaseModel):
    name: str = ""
    desc: str = ""
    status: str = "启用"
    scope: List[str] = []
    suffix: str = ""
    trigger: str = "全部"
    uses: int = 0


class ApplyReq(BaseModel):
    text: str
    scope: str = "测试用例"
    policy: str = ""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


async def _ensure_schema(db: SyncDB):
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS deai_policies (
        id TEXT PRIMARY KEY, name TEXT, desc TEXT, scope TEXT,
        trigger TEXT, status TEXT, suffix TEXT, uses INTEGER DEFAULT 0,
        created TEXT, updated_at TEXT)""",
    )
    await db_commit(db)


async def _seed_if_empty(db: SyncDB):
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM deai_policies", [])
    if row and row["c"]:
        return
    for p in _SEED:
        await db_insert(
            db,
            "deai_policies",
            {
                "id": p["id"],
                "name": p["name"],
                "desc": p["desc"],
                "scope": json.dumps(p["scope"], ensure_ascii=False),
                "trigger": p["trigger"],
                "status": p["status"],
                "suffix": p["suffix"],
                "uses": p["uses"],
                "created": p["created"],
                "updated_at": p["created"],
            },
        )
    await db_commit(db)


def _scope(v) -> list:
    if isinstance(v, list):
        return v
    if not v:
        return []
    try:
        data = json.loads(v)
        return data if isinstance(data, list) else [str(data)]
    except Exception:
        return [t for t in str(v).split(",") if t]


def _row(r: dict) -> dict:
    return {
        "id": r["id"],
        "name": r.get("name", ""),
        "desc": r.get("desc", ""),
        "status": r.get("status") or "禁用",
        "scope": _scope(r.get("scope")),
        "created": r.get("created") or "",
        "uses": r.get("uses", 0) or 0,
        "trigger": r.get("trigger") or "全部",
        "suffix": r.get("suffix") or "",
        "updated_at": r.get("updated_at") or "",
    }


async def _sync_kv(db: SyncDB):
    """把表内策略镜像到 cfg_kv，供 ai.get_deai_suffix 读取。"""
    rows = await db_fetch_all(db, "SELECT * FROM deai_policies ORDER BY id DESC", [])
    payload = []
    for r in rows:
        item = _row(r)
        # ai.get_deai_suffix 兼容的最小字段集
        payload.append(
            {
                "id": item["id"],
                "name": item["name"],
                "desc": item["desc"],
                "status": item["status"],
                "scope": "、".join(item["scope"]) or "全部",
                "suffix": item["suffix"],
                "trigger": item["trigger"],
                "uses": item["uses"],
            }
        )
    await ensure_config_kv(db)
    now = _now()
    exists = await db_fetch_one(db, "SELECT key FROM cfg_kv WHERE key=?", [_KV_KEY])
    value = json.dumps(payload, ensure_ascii=False)
    if exists:
        await db_update(
            db, "cfg_kv", {"value": value, "updated_at": now}, "key=?", [_KV_KEY]
        )
    else:
        await db_insert(
            db, "cfg_kv", {"key": _KV_KEY, "value": value, "updated_at": now}
        )
    await db_commit(db)


async def _init(db: SyncDB):
    await _ensure_schema(db)
    await _seed_if_empty(db)
    await _sync_kv(db)


async def _load(db: SyncDB, pid: str) -> dict:
    row = await db_fetch_one(db, "SELECT * FROM deai_policies WHERE id=?", [pid])
    if not row:
        raise HTTPException(status_code=404, detail="策略不存在")
    return row


async def _next_id(db: SyncDB) -> str:
    rows = await db_fetch_all(db, "SELECT id FROM deai_policies", [])
    best = 0
    for r in rows:
        try:
            best = max(best, int(str(r["id"]).split("-")[-1]))
        except Exception:
            pass
    return "DA-%02d" % (best + 1)


@router.get("/deai/policies")
async def list_policies(
    q: str = Query(""),
    status: str = Query(""),
    db: SyncDB = Depends(get_db),
):
    await _init(db)
    rows = await db_fetch_all(db, "SELECT * FROM deai_policies ORDER BY id DESC", [])
    out = [_row(r) for r in rows]
    if status:
        out = [p for p in out if p["status"] == status]
    if q:
        ql = q.lower()
        out = [p for p in out if ql in (p["name"] + p["desc"]).lower()]
    return out


@router.post("/deai/policies")
async def create_policy(
    body: PolicyBody,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _init(db)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="策略名称不能为空")
    if not body.suffix.strip():
        raise HTTPException(status_code=400, detail="提示词后缀不能为空")
    pid = await _next_id(db)
    await db_insert(
        db,
        "deai_policies",
        {
            "id": pid,
            "name": body.name.strip(),
            "desc": body.desc,
            "scope": json.dumps(body.scope or ["测试用例"], ensure_ascii=False),
            "trigger": body.trigger,
            "status": body.status if body.status in ("启用", "禁用") else "启用",
            "suffix": body.suffix,
            "uses": body.uses,
            "created": _now(),
            "updated_at": _now(),
        },
    )
    await db_commit(db)
    await _sync_kv(db)
    return _row(await _load(db, pid))


@router.put("/deai/policies/{pid}")
async def update_policy(
    pid: str,
    body: PolicyBody,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _init(db)
    await _load(db, pid)
    await db_update(
        db,
        "deai_policies",
        {
            "name": body.name,
            "desc": body.desc,
            "scope": json.dumps(body.scope or ["测试用例"], ensure_ascii=False),
            "trigger": body.trigger,
            "status": body.status if body.status in ("启用", "禁用") else "启用",
            "suffix": body.suffix,
            "uses": body.uses,
            "updated_at": _now(),
        },
        "id=?",
        [pid],
    )
    await _sync_kv(db)
    return _row(await _load(db, pid))


@router.delete("/deai/policies/{pid}")
async def delete_policy(
    pid: str,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _init(db)
    await _load(db, pid)
    await db_delete(db, "deai_policies", "id=?", [pid])
    await _sync_kv(db)
    return {"ok": True, "id": pid}


@router.post("/deai/apply")
async def deai_apply(
    body: ApplyReq,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """试运行润色：调 ai.simple(module=去AI味, scope=...) 返回改写结果。"""
    await _init(db)
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text 不能为空")
    # 累计使用次数
    rows = await db_fetch_all(
        db, "SELECT id FROM deai_policies WHERE status=?", ["启用"]
    )
    for r in rows:
        await db_update(
            db,
            "deai_policies",
            {
                "uses": (
                    await db_fetch_one(
                        db, "SELECT uses FROM deai_policies WHERE id=?", [r["id"]]
                    )
                ).get("uses", 0)
                + 1
            },
            "id=?",
            [r["id"]],
        )
    await _sync_kv(db)

    prompt = (
        f"你负责对以下 AI 生成文本做「去 AI 味」润色，作用范围：{body.scope}。"
        "要求：去掉模板腔与排比，改为自然、简洁、可执行的测试同学口吻，保留事实与数据，"
        "不要解释，只输出润色后的文本。\n\n"
        f"原文：\n{body.text}"
    )
    result = await simple(db, prompt, module="去AI味", scope=body.scope)
    return {"text": result, "scope": body.scope, "ok": True}
