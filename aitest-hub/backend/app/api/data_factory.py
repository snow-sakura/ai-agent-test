"""数据工厂（Data Factory）— /api/data-factory/*"""

import json
import random
import re
import string
from datetime import datetime
from typing import Any, Dict, List, Optional

from croniter import croniter
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

router = APIRouter(tags=["data-factory"])

_SURNAMES = list("张王李赵刘陈杨黄周吴徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭")
_GIVEN = [
    "伟",
    "芳",
    "娜",
    "敏",
    "静",
    "磊",
    "军",
    "洋",
    "勇",
    "艳",
    "杰",
    "涛",
    "明",
    "超",
    "秀英",
]
_CITIES = [
    "北京市朝阳区",
    "上海市浦东新区",
    "广州市天河区",
    "深圳市南山区",
    "杭州市西湖区",
    "成都市高新区",
]

_SEED_PRESETS = [
    {
        "id": "DFP-1",
        "name": "用户注册",
        "desc": "姓名/手机/邮箱/地址",
        "fields": ["name", "phone", "email", "addr"],
    },
    {
        "id": "DFP-2",
        "name": "订单造数",
        "desc": "订单号/用户/金额/时间",
        "fields": ["orderId", "name", "amount", "date"],
    },
    {
        "id": "DFP-3",
        "name": "退款申请",
        "desc": "订单/原因/金额/状态",
        "fields": ["orderId", "reason", "amount", "status"],
    },
    {
        "id": "DFP-4",
        "name": "身份核验",
        "desc": "姓名/身份证/手机",
        "fields": ["name", "idcard", "phone"],
    },
]


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
        """CREATE TABLE IF NOT EXISTS df_presets (
        id TEXT PRIMARY KEY, name TEXT, desc TEXT, fields TEXT, created_at TEXT)""",
    )
    await db_commit(db)


async def _seed_if_empty(db: SyncDB) -> None:
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM df_presets", [])
    if not (row and row["c"]):
        for r in _SEED_PRESETS:
            item = dict(r)
            item["fields"] = json.dumps(r["fields"], ensure_ascii=False)
            item["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            await db_insert(db, "df_presets", item)
        await db_commit(db)


async def _ready(db: SyncDB) -> None:
    await _ensure_schema(db)
    await _seed_if_empty(db)


def _preset_row(r: dict) -> dict:
    fields = _j(r.get("fields"), [])
    if not isinstance(fields, list):
        fields = []
    return {
        "id": r.get("id"),
        "name": r.get("name") or "",
        "desc": r.get("desc") or "",
        "fields": fields,
        "createdAt": r.get("created_at") or "",
    }


# ---------------------------------------------------------------------------
# generators
# ---------------------------------------------------------------------------

_FIELD_PATTERNS = {
    "name": r"姓名|名字|用户|username|name",
    "phone": r"手机|电话|手机号|phone|mobile",
    "email": r"邮箱|邮件|email|mail",
    "addr": r"地址|住址|address|addr",
    "idcard": r"身份证|idcard|identity",
    "bank": r"银行卡|卡号|bank",
    "amount": r"金额|价格|amount|price|money",
    "orderId": r"订单|order",
    "date": r"时间|日期|date|time",
    "city": r"城市|city",
    "reason": r"原因|reason",
    "status": r"状态|status",
    "credit": r"统一社会信用|credit",
    "uuid": r"uuid|guid",
}


def _infer_fields(desc: str) -> List[str]:
    fields: List[str] = []
    for key, pat in _FIELD_PATTERNS.items():
        if re.search(pat, desc or "", re.I):
            fields.append(key)
    return fields or ["name", "phone", "email", "addr"]


def _gen_value(field: str, i: int, desc: str = "") -> Any:
    f = field
    if f in ("name",) or re.search(_FIELD_PATTERNS["name"], f, re.I):
        if f.lower() in ("name", "姓名", "用户名", "username") or f == "name":
            return random.choice(_SURNAMES) + random.choice(_GIVEN)
    if re.search(_FIELD_PATTERNS["phone"], f, re.I) or f == "phone":
        return "1" + random.choice("35789") + "".join(random.choices("0123456789", k=9))
    if re.search(_FIELD_PATTERNS["email"], f, re.I) or f == "email":
        return f"test_{1000 + i}@{random.choice(['qq.com', '163.com', 'gmail.com'])}"
    if re.search(_FIELD_PATTERNS["addr"], f, re.I) or f == "addr":
        return (
            random.choice(_CITIES)
            + random.choice(["幸福路", "望江道", "科技园"])
            + str(random.randint(1, 999))
            + "号"
        )
    if re.search(_FIELD_PATTERNS["idcard"], f, re.I) or f == "idcard":
        return "1101011990%02d%02d%04d" % (
            random.randint(1, 12),
            random.randint(1, 28),
            random.randint(1000, 9999),
        )
    if re.search(_FIELD_PATTERNS["bank"], f, re.I) or f == "bank":
        return "62" + "".join(random.choices("0123456789", k=17))
    if re.search(_FIELD_PATTERNS["amount"], f, re.I) or f == "amount":
        return f"{random.randint(10, 990) / 10:.2f}"
    if re.search(_FIELD_PATTERNS["orderId"], f, re.I) or f in ("orderId", "order"):
        return "ORD2026%05d" % random.randint(10000, 99999)
    if re.search(_FIELD_PATTERNS["date"], f, re.I) or f == "date":
        return datetime.now().strftime("%Y-%m-%d %H:%M")
    if re.search(_FIELD_PATTERNS["city"], f, re.I) or f == "city":
        return random.choice(_CITIES)[:3]
    if re.search(_FIELD_PATTERNS["reason"], f, re.I) or f == "reason":
        return random.choice(["不想要了", "拍错了", "质量问题", "与描述不符"])
    if re.search(_FIELD_PATTERNS["status"], f, re.I) or f == "status":
        return random.choice(["pending", "done", "cancelled"])
    if re.search(_FIELD_PATTERNS["credit"], f, re.I) or f == "credit":
        return "91310000MA%06dX%02d" % (
            random.randint(100000, 999999),
            random.randint(10, 99),
        )
    if re.search(_FIELD_PATTERNS["uuid"], f, re.I) or f == "uuid":
        import uuid as _uuid

        return str(_uuid.uuid4())
    return f"{f}-{i + 1}"


def _local_rows(desc: str, n: int, fields: List[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for i in range(n):
        rows.append({f: _gen_value(f, i, desc) for f in fields})
    return rows


# ---------------------------------------------------------------------------
# pydantic
# ---------------------------------------------------------------------------


class AiTestDataReq(BaseModel):
    desc: str
    n: int = 5
    fields: List[str] = []


class CronParseReq(BaseModel):
    expr: str


class PresetCreate(BaseModel):
    id: str = ""
    name: str
    desc: str = ""
    fields: List[str] = []


class TransformRule(BaseModel):
    field: str
    op: str  # trim / upper / lower / digit / prefix


class TransformReq(BaseModel):
    rows: List[Dict[str, Any]] = []
    rules: List[TransformRule] = []
    # 也接受 dict 形式 {"field": "op"}，在处理器中兼容


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------


@router.post("/data-factory/ai-testdata")
async def ai_testdata(
    body: AiTestDataReq,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """AI/本地生成表格 rows（JSON 数组）。"""
    await _ready(db)
    desc = (body.desc or "").strip()
    if not desc:
        raise HTTPException(status_code=400, detail="desc 不能为空")
    n = max(1, min(int(body.n or 5), 500))
    fields = body.fields or _infer_fields(desc)

    # 优先 AI JSON；无 key mock 会返回非 JSON → 回退本地生成
    try:
        prompt = (
            "根据描述生成测试数据，只输出 JSON 数组（不要解释）：\n"
            f"描述：{desc}\n字段：{','.join(fields)}\n条数：{n}"
        )
        data = await ai_svc.chat_json(
            db, [{"role": "user", "content": prompt}], module="数据工厂"
        )
        if isinstance(data, list) and data and isinstance(data[0], dict):
            rows = data[:n]
            # 补齐缺失字段
            for r in rows:
                for f in fields:
                    r.setdefault(f, "")
            return {"rows": rows, "fields": fields, "source": "ai", "count": len(rows)}
    except Exception:
        pass
    rows = _local_rows(desc, n, fields)
    return {"rows": rows, "fields": fields, "source": "local", "count": len(rows)}


@router.post("/data-factory/crontab-parse")
async def crontab_parse(
    body: CronParseReq,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """croniter 解析 cron 表达式，返回接下来 5 次执行时间。"""
    await _ready(db)
    expr = (body.expr or "").strip()
    if not expr:
        raise HTTPException(status_code=400, detail="expr 不能为空")
    try:
        base = datetime.now()
        cron = croniter(expr, base)
        nexts = [
            cron.get_next(datetime).strftime("%Y-%m-%d %H:%M:%S") for _ in range(5)
        ]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"表达式无效: {exc}")
    return {"expr": expr, "ok": True, "next": nexts, "next5": nexts}


@router.get("/data-factory/presets")
async def list_presets(db: SyncDB = Depends(get_db)):
    await _ready(db)
    rows = await db_fetch_all(db, "SELECT * FROM df_presets ORDER BY id", [])
    return [_preset_row(r) for r in rows]


@router.post("/data-factory/presets")
async def create_preset(
    body: PresetCreate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="预设名称不能为空")
    pid = body.id.strip()
    if not pid:
        rows = await db_fetch_all(
            db, "SELECT id FROM df_presets WHERE id LIKE 'DFP-%'", []
        )
        best = 0
        for r in rows:
            try:
                best = max(best, int(str(r["id"]).split("-")[-1]))
            except Exception:
                pass
        pid = "DFP-%d" % (best + 1)
    if await db_fetch_one(db, "SELECT id FROM df_presets WHERE id=?", [pid]):
        raise HTTPException(status_code=409, detail="预设 ID 已存在")
    await db_insert(
        db,
        "df_presets",
        {
            "id": pid,
            "name": body.name.strip(),
            "desc": body.desc,
            "fields": json.dumps(body.fields or [], ensure_ascii=False),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
    )
    row = await db_fetch_one(db, "SELECT * FROM df_presets WHERE id=?", [pid])
    if not row:
        raise HTTPException(status_code=500, detail="预设写入失败")
    return _preset_row(row)


@router.delete("/data-factory/presets/{pid}")
async def delete_preset(
    pid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    row = await db_fetch_one(db, "SELECT id FROM df_presets WHERE id=?", [pid])
    if not row:
        raise HTTPException(status_code=404, detail="预设不存在")
    await db_execute(db, "DELETE FROM df_presets WHERE id=?", [pid])
    await db_commit(db)
    return {"ok": True, "id": pid}


def _apply_op(value: Any, op: str) -> Any:
    s = "" if value is None else str(value)
    op = (op or "").lower().strip()
    if op == "trim":
        return s.strip()
    if op == "upper":
        return s.upper()
    if op == "lower":
        return s.lower()
    if op == "digit":
        return re.sub(r"\D", "", s)
    if op == "nodigit":
        return re.sub(r"\d", "", s)
    if op.startswith("prefix:"):
        return op.split(":", 1)[1] + s
    if op.startswith("pad:"):
        # pad:10 → 左补零到 10 位
        try:
            width = int(op.split(":", 1)[1])
            return s.zfill(width)
        except Exception:
            return s
    if op == "empty_if_none":
        return s
    return s


@router.post("/data-factory/transform")
async def transform(
    body: TransformReq,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """简单变换：rules 支持 [{field,op}] 或 {field: op}。"""
    await _ready(db)
    raw_rules: Any = body.rules
    pairs: List[tuple] = []
    if isinstance(raw_rules, list):
        for item in raw_rules:
            if isinstance(item, TransformRule):
                pairs.append((item.field, item.op))
            elif isinstance(item, dict):
                f = item.get("field") or item.get("k") or ""
                op = item.get("op") or item.get("rule") or item.get("v") or ""
                if f:
                    pairs.append((str(f), str(op)))
    elif isinstance(raw_rules, dict):
        for f, op in raw_rules.items():
            pairs.append((str(f), str(op)))

    rows = body.rows or []
    if not pairs:
        # 无规则：原样返回
        return {"rows": rows, "count": len(rows)}
    out: List[Dict[str, Any]] = []
    for r in rows:
        nr = dict(r)
        for f, op in pairs:
            if f in nr:
                nr[f] = _apply_op(nr[f], op)
        out.append(nr)
    return {
        "rows": out,
        "count": len(out),
        "rules": [{"field": f, "op": o} for f, o in pairs],
    }
