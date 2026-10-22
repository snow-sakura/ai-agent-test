"""安全测试（Security Testing）— /api/security/*"""

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

router = APIRouter(tags=["security"])

S_TODO = "待处理"
S_FIXING = "修复中"
S_FIXED = "已修复"
S_IGNORE = "已忽略"


# ---------------------------------------------------------------------------
# schema / seed
# ---------------------------------------------------------------------------

_SEED_FINDINGS = [
    {
        "id": "SEC-2026-011",
        "title": "支付接口金额可被客户端篡改",
        "sev": "高危",
        "url": "/v1/pay",
        "param": "amount",
        "poc": "请求体中 amount 字段由客户端传入，可构造 0.01 元支付大额订单",
        "status": S_TODO,
        "fix": "金额由服务端按订单实付计算，客户端仅传 orderId；加签名校验。",
        "owasp": "A01 失效的访问控制",
        "req": "REQ-2026-0125",
        "time": "2026-09-22",
    },
    {
        "id": "SEC-2026-009",
        "title": "登录接口用户枚举风险",
        "sev": "中危",
        "url": "/v1/auth/login",
        "param": "username",
        "poc": "账号存在与密码错误的提示语不同，可批量枚举注册手机号",
        "status": S_FIXING,
        "fix": "统一返回「用户名或密码错误」，失败响应保持一致耗时。",
        "owasp": "A07 身份认证失效",
        "req": "",
        "time": "2026-09-21",
    },
    {
        "id": "SEC-2026-007",
        "title": "上传接口文件类型校验缺失",
        "sev": "高危",
        "url": "/v1/attachments",
        "param": "file",
        "poc": "仅校验 Content-Type，未校验文件魔数，可上传 webshell",
        "status": S_TODO,
        "fix": "校验文件魔数与白名单扩展名，存储随机文件名并隔离目录。",
        "owasp": "A04 不安全的设计",
        "req": "",
        "time": "2026-09-20",
    },
    {
        "id": "SEC-2026-005",
        "title": "退款回调未校验签名",
        "sev": "高危",
        "url": "/v1/refunds/notify",
        "param": "sign",
        "poc": "回调接口未验证来源签名，可伪造退款成功通知",
        "status": S_FIXED,
        "fix": "增加 HMAC 签名校验 + 时间戳防重放，失败返回 401。",
        "owasp": "A08 软件与数据完整性失效",
        "req": "REQ-2026-0125",
        "time": "2026-09-18",
    },
    {
        "id": "SEC-2026-004",
        "title": "响应头缺失安全配置",
        "sev": "低危",
        "url": "全站",
        "param": "—",
        "poc": "缺失 CSP / X-Frame-Options / HSTS 响应头",
        "status": S_FIXED,
        "fix": "网关统一注入安全响应头。",
        "owasp": "A05 安全配置错误",
        "req": "",
        "time": "2026-09-16",
    },
]

_SEED_BASELINES = [
    {
        "id": "A01",
        "item": "失效的访问控制",
        "level": "高",
        "required": True,
        "status": "通过",
        "note": "水平/垂直越权、未授权访问",
    },
    {
        "id": "A02",
        "item": "失效的加密机制",
        "level": "高",
        "required": True,
        "status": "通过",
        "note": "明文传输、弱加密算法",
    },
    {
        "id": "A03",
        "item": "注入（SQL/XSS/命令）",
        "level": "高",
        "required": True,
        "status": "不通过",
        "note": "参数化查询、输出编码",
    },
    {
        "id": "A04",
        "item": "不安全的设计",
        "level": "中",
        "required": True,
        "status": "不通过",
        "note": "限流、业务逻辑校验",
    },
    {
        "id": "A05",
        "item": "安全配置错误",
        "level": "中",
        "required": True,
        "status": "通过",
        "note": "默认配置、响应头、报错信息",
    },
    {
        "id": "A07",
        "item": "身份认证失效",
        "level": "高",
        "required": True,
        "status": "不通过",
        "note": "弱口令策略、会话管理",
    },
    {
        "id": "A08",
        "item": "软件与数据完整性失效",
        "level": "中",
        "required": True,
        "status": "通过",
        "note": "回调签名、依赖完整性",
    },
    {
        "id": "A09",
        "item": "安全日志与监控失效",
        "level": "低",
        "required": False,
        "status": "不通过",
        "note": "日志脱敏、告警接入",
    },
]

# 规则库：扫描 target 时命中的演示规则
_RULES = [
    (
        "金额参数可被篡改",
        "高危",
        "amount",
        "A01 失效的访问控制",
        "建议服务端重算金额并签名",
    ),
    ("登录接口无限流", "中危", "password", "A07 身份认证失效", "接入网关限流与验证码"),
    ("缺少对象级鉴权", "高危", "id", "A01 失效的访问控制", "校验资源归属当前用户"),
    ("错误堆栈信息泄露", "低危", "—", "A05 安全配置错误", "生产环境关闭调试输出"),
    (
        "敏感信息日志明文",
        "低危",
        "—",
        "A09 安全日志与监控失效",
        "日志脱敏手机号/身份证",
    ),
    ("SQL 拼接风险", "高危", "keyword", "A03 注入", "改用参数化查询"),
]


def _now_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


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
        """CREATE TABLE IF NOT EXISTS sec_findings (
        id TEXT PRIMARY KEY, title TEXT, sev TEXT, url TEXT, param TEXT,
        poc TEXT, status TEXT, fix TEXT, owasp TEXT, req TEXT, time TEXT)""",
    )
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS sec_baselines (
        id TEXT PRIMARY KEY, item TEXT, level TEXT, required INTEGER,
        status TEXT, note TEXT)""",
    )
    await db_commit(db)


async def _seed_if_empty(db: SyncDB) -> None:
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM sec_findings", [])
    if not (row and row["c"]):
        for r in _SEED_FINDINGS:
            await db_insert(db, "sec_findings", dict(r))
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM sec_baselines", [])
    if not (row and row["c"]):
        for r in _SEED_BASELINES:
            item = dict(r)
            item["required"] = 1 if r["required"] else 0
            await db_insert(db, "sec_baselines", item)
    await db_commit(db)


async def _ready(db: SyncDB) -> None:
    await _ensure_schema(db)
    await _seed_if_empty(db)


def _finding_row(r: dict) -> dict:
    sev = r.get("sev") or "提示"
    url = r.get("url") or ""
    poc = r.get("poc") or ""
    return {
        "id": r.get("id"),
        "title": r.get("title") or "",
        "sev": sev,
        "level": sev,  # UI 别名
        "url": url,
        "target": url,  # UI 别名
        "param": r.get("param") or "",
        "poc": poc,
        "detail": poc,  # UI 别名
        "status": r.get("status") or S_TODO,
        "fix": r.get("fix") or "",
        "owasp": r.get("owasp") or "",
        "req": r.get("req") or "",
        "time": r.get("time") or "",
    }


def _baseline_row(r: dict) -> dict:
    item = r.get("item") or ""
    note = r.get("note") or ""
    return {
        "id": r.get("id"),
        "item": item,
        "name": item,  # UI 别名
        "level": r.get("level") or "中",
        "required": bool(r.get("required")),
        "status": r.get("status") or "未检",
        "note": note,
        "desc": note,  # UI 别名
    }


async def _load(db: SyncDB, fid: str) -> dict:
    row = await db_fetch_one(db, "SELECT * FROM sec_findings WHERE id=?", [fid])
    if not row:
        raise HTTPException(status_code=404, detail="安全发现不存在")
    return row


async def _next_finding_id(db: SyncDB) -> str:
    rows = await db_fetch_all(
        db, "SELECT id FROM sec_findings WHERE id LIKE 'SEC-%'", []
    )
    best = 11
    for r in rows:
        try:
            best = max(best, int(str(r["id"]).split("-")[-1]))
        except Exception:
            pass
    return "SEC-2026-%03d" % (best + 1)


# ---------------------------------------------------------------------------
# pydantic
# ---------------------------------------------------------------------------


class FindingCreate(BaseModel):
    id: str = ""
    title: str
    sev: str = "中危"
    url: str = ""
    param: str = ""
    poc: str = ""
    status: str = S_TODO
    fix: str = ""
    owasp: str = ""
    req: str = ""


class FindingUpdate(BaseModel):
    """部分更新：仅提交需要变更的字段。"""

    title: Optional[str] = None
    sev: Optional[str] = None
    level: Optional[str] = None  # UI 别名 → sev
    url: Optional[str] = None
    target: Optional[str] = None  # UI 别名 → url
    param: Optional[str] = None
    poc: Optional[str] = None
    detail: Optional[str] = None  # UI 别名 → poc
    status: Optional[str] = None
    fix: Optional[str] = None
    owasp: Optional[str] = None
    req: Optional[str] = None


class ScanReq(BaseModel):
    target: str
    count: int = 3


class BaselineCreate(BaseModel):
    id: str = ""
    item: str
    level: str = "中"
    required: bool = True
    status: str = "未检"
    note: str = ""


class BaselineUpdate(BaseModel):
    item: Optional[str] = None
    level: Optional[str] = None
    required: Optional[bool] = None
    status: Optional[str] = None
    note: Optional[str] = None


class AiReviewReq(BaseModel):
    text: str


# ---------------------------------------------------------------------------
# findings
# ---------------------------------------------------------------------------


@router.get("/security/findings")
async def list_findings(db: SyncDB = Depends(get_db)):
    await _ready(db)
    rows = await db_fetch_all(db, "SELECT * FROM sec_findings ORDER BY id DESC", [])
    return [_finding_row(r) for r in rows]


@router.post("/security/findings")
async def create_finding(
    body: FindingCreate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="标题不能为空")
    fid = body.id.strip() or await _next_finding_id(db)
    if await db_fetch_one(db, "SELECT id FROM sec_findings WHERE id=?", [fid]):
        raise HTTPException(status_code=409, detail="发现 ID 已存在")
    await db_insert(
        db,
        "sec_findings",
        {
            "id": fid,
            "title": body.title.strip(),
            "sev": body.sev,
            "url": body.url,
            "param": body.param,
            "poc": body.poc,
            "status": body.status or S_TODO,
            "fix": body.fix,
            "owasp": body.owasp,
            "req": body.req,
            "time": _now_date(),
        },
    )
    return _finding_row(await _load(db, fid))


@router.put("/security/findings/{fid}")
async def update_finding(
    fid: str,
    body: FindingUpdate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    await _load(db, fid)
    data = body.model_dump(exclude_unset=True)
    # UI 别名映射
    if "level" in data and data["level"] is not None:
        data["sev"] = data.pop("level")
    if "target" in data and data["target"] is not None:
        data["url"] = data.pop("target")
    if "detail" in data and data["detail"] is not None:
        data["poc"] = data.pop("detail")
    data = {k: v for k, v in data.items() if v is not None}
    if data:
        await db_update(db, "sec_findings", data, "id=?", [fid])
        await db_commit(db)
    return _finding_row(await _load(db, fid))


@router.delete("/security/findings/{fid}")
async def delete_finding(
    fid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    await _load(db, fid)
    await db_execute(db, "DELETE FROM sec_findings WHERE id=?", [fid])
    await db_commit(db)
    return {"ok": True, "id": fid}


# ---------------------------------------------------------------------------
# scan / baselines / ai-review
# ---------------------------------------------------------------------------


@router.post("/security/scan")
async def scan(
    body: ScanReq,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """规则 + AI 生成若干安全发现并入库。"""
    await _ready(db)
    target = (body.target or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="target 不能为空")
    n = max(1, min(int(body.count or 3), len(_RULES)))
    picked = random.sample(_RULES, n)
    created: List[dict] = []
    for title, sev, param, owasp, fix in picked:
        fid = await _next_finding_id(db)
        if await db_fetch_one(db, "SELECT id FROM sec_findings WHERE id=?", [fid]):
            continue
        # 可选：AI 补充一句描述（无 key 自动 mock，失败不影响入库）
        detail = ""
        try:
            detail = await ai_svc.simple(
                db,
                f"针对目标 {target} 的安全问题「{title}」，用一句话描述风险与 PoC 要点。",
                module="安全测试",
            )
        except Exception:
            detail = f"自动扫描在 {target} 发现：{title}"
        await db_insert(
            db,
            "sec_findings",
            {
                "id": fid,
                "title": f"{title}（{target}）",
                "sev": sev,
                "url": target,
                "param": param,
                "poc": detail,
                "status": S_TODO,
                "fix": fix,
                "owasp": owasp,
                "req": "",
                "time": _now_date(),
            },
        )
        row = await db_fetch_one(db, "SELECT * FROM sec_findings WHERE id=?", [fid])
        if row:
            created.append(_finding_row(row))
    return {"target": target, "count": len(created), "findings": created}


@router.get("/security/baselines")
async def list_baselines(db: SyncDB = Depends(get_db)):
    await _ready(db)
    rows = await db_fetch_all(db, "SELECT * FROM sec_baselines ORDER BY id", [])
    return [_baseline_row(r) for r in rows]


@router.post("/security/baselines")
async def create_baseline(
    body: BaselineCreate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    if not body.item.strip():
        raise HTTPException(status_code=400, detail="基线项不能为空")
    bid = body.id.strip() or ("A" + str(random.randint(10, 99)))
    if await db_fetch_one(db, "SELECT id FROM sec_baselines WHERE id=?", [bid]):
        raise HTTPException(status_code=409, detail="基线 ID 已存在")
    await db_insert(
        db,
        "sec_baselines",
        {
            "id": bid,
            "item": body.item.strip(),
            "level": body.level,
            "required": 1 if body.required else 0,
            "status": body.status,
            "note": body.note,
        },
    )
    row = await db_fetch_one(db, "SELECT * FROM sec_baselines WHERE id=?", [bid])
    if not row:
        raise HTTPException(status_code=500, detail="基线写入失败")
    return _baseline_row(row)


@router.put("/security/baselines/{bid}")
async def update_baseline(
    bid: str,
    body: BaselineUpdate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    row = await db_fetch_one(db, "SELECT * FROM sec_baselines WHERE id=?", [bid])
    if not row:
        raise HTTPException(status_code=404, detail="基线不存在")
    data: Dict[str, Any] = {}
    if body.item is not None:
        data["item"] = body.item
    if body.level is not None:
        data["level"] = body.level
    if body.required is not None:
        data["required"] = 1 if body.required else 0
    if body.status is not None:
        data["status"] = body.status
    if body.note is not None:
        data["note"] = body.note
    if data:
        await db_update(db, "sec_baselines", data, "id=?", [bid])
        row = await db_fetch_one(db, "SELECT * FROM sec_baselines WHERE id=?", [bid])
    return _baseline_row(row) if row else {}


@router.delete("/security/baselines/{bid}")
async def delete_baseline(
    bid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    row = await db_fetch_one(db, "SELECT id FROM sec_baselines WHERE id=?", [bid])
    if not row:
        raise HTTPException(status_code=404, detail="基线不存在")
    await db_execute(db, "DELETE FROM sec_baselines WHERE id=?", [bid])
    await db_commit(db)
    return {"ok": True, "id": bid}


@router.post("/security/ai-review")
async def ai_review(
    body: AiReviewReq,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text 不能为空")
    prompt = (
        "请从 OWASP Top 10 视角评审以下内容/配置/代码片段，指出安全风险并给出修复建议：\n"
        + body.text[:4000]
    )
    text = await ai_svc.simple(db, prompt, module="安全测试")
    return {"text": text, "module": "安全测试"}
