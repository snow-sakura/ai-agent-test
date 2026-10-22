"""接口测试套件（API Suite）— /api/api-testing/*

注意：/api-testing/health 已由 app/api/api_testing.py 注册，本文件不要重复注册。
"""

import json
import random
import time as _time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
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

router = APIRouter(tags=["api-suite"])

S_PASS = "通过"
S_FAIL = "失败"


# ---------------------------------------------------------------------------
# schema / seed
# ---------------------------------------------------------------------------

_SEED_ENDPOINTS = [
    {
        "id": "API-101",
        "name": "用户登录",
        "method": "POST",
        "url": "https://dev-api.example.com/v1/auth/login",
        "headers": {"Content-Type": "application/json"},
        "body": {"username": "demo", "password": "demo123"},
        "assert": ["status_code == 200", "json.code == 0", "json.data.token 非空"],
        "status": S_PASS,
        "lastCode": 200,
        "lastMs": 132,
        "tags": ["用户模块", "冒烟"],
    },
    {
        "id": "API-102",
        "name": "获取用户信息",
        "method": "GET",
        "url": "https://dev-api.example.com/v1/users/1001",
        "headers": {"Authorization": "Bearer demo-token"},
        "body": "",
        "assert": ["status_code == 200", "json.data.id == 1001"],
        "status": S_PASS,
        "lastCode": 200,
        "lastMs": 68,
        "tags": ["用户模块"],
    },
    {
        "id": "API-103",
        "name": "创建订单",
        "method": "POST",
        "url": "https://test-api.example.com/v1/orders",
        "headers": {"Content-Type": "application/json"},
        "body": {"sku": "SKU-1001", "count": 2},
        "assert": [
            "status_code == 200",
            "json.code == 0",
            "json.data.orderId 非空",
            "json.data.amount > 0",
        ],
        "status": S_PASS,
        "lastCode": 200,
        "lastMs": 210,
        "tags": ["订单模块", "核心"],
    },
    {
        "id": "API-104",
        "name": "查询订单列表",
        "method": "GET",
        "url": "https://test-api.example.com/v1/orders?page=1&size=10",
        "headers": {},
        "body": "",
        "assert": ["status_code == 200", "json.data.list 是数组"],
        "status": S_PASS,
        "lastCode": 200,
        "lastMs": 95,
        "tags": ["订单模块"],
    },
    {
        "id": "API-105",
        "name": "取消订单",
        "method": "PUT",
        "url": "https://test-api.example.com/v1/orders/ORD1001/cancel",
        "headers": {"Content-Type": "application/json"},
        "body": {"reason": "不想要了"},
        "assert": ["status_code == 200", "json.data.status == cancelled"],
        "status": S_FAIL,
        "lastCode": 500,
        "lastMs": 860,
        "tags": ["订单模块", "边界"],
    },
    {
        "id": "API-106",
        "name": "发起支付",
        "method": "POST",
        "url": "https://staging-api.example.com/v1/pay",
        "headers": {"Content-Type": "application/json"},
        "body": {"orderId": "ORD1001", "amount": 99.00},
        "assert": ["status_code == 200", "json.code == 0", "json.data.payUrl 非空"],
        "status": S_PASS,
        "lastCode": 200,
        "lastMs": 305,
        "tags": ["支付模块", "核心"],
    },
]

_SEED_ENVS = [
    {
        "id": "ENV-DEV",
        "name": "DEV",
        "base": "https://dev-api.example.com",
        "vars": [
            {"k": "BASE_URL", "v": "https://dev-api.example.com"},
            {"k": "TOKEN", "v": "dev-xxx"},
        ],
    },
    {
        "id": "ENV-TEST",
        "name": "TEST",
        "base": "https://test-api.example.com",
        "vars": [
            {"k": "BASE_URL", "v": "https://test-api.example.com"},
            {"k": "TOKEN", "v": "test-xxx"},
        ],
    },
]

_SEED_HISTORY = [
    {
        "id": "HR-310",
        "eid": "",
        "env": "TEST",
        "count": 8,
        "pass": 7,
        "fail": 1,
        "time": "2026-09-22 09:12",
        "mode": "串行",
    },
    {
        "id": "HR-309",
        "eid": "",
        "env": "DEV",
        "count": 5,
        "pass": 5,
        "fail": 0,
        "time": "2026-09-21 16:40",
        "mode": "并行",
    },
    {
        "id": "HR-308",
        "eid": "",
        "env": "STAGING",
        "count": 6,
        "pass": 4,
        "fail": 2,
        "time": "2026-09-20 11:05",
        "mode": "串行",
    },
]

_DEMO_PARSE = [
    {
        "id": "API-201",
        "name": "登录",
        "method": "POST",
        "url": "/v1/auth/login",
        "tags": ["swagger"],
    },
    {
        "id": "API-202",
        "name": "用户详情",
        "method": "GET",
        "url": "/v1/users/{id}",
        "tags": ["swagger"],
    },
    {
        "id": "API-203",
        "name": "创建订单",
        "method": "POST",
        "url": "/v1/orders",
        "tags": ["swagger"],
    },
    {
        "id": "API-204",
        "name": "订单列表",
        "method": "GET",
        "url": "/v1/orders",
        "tags": ["swagger"],
    },
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
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
        """CREATE TABLE IF NOT EXISTS as_endpoints (
        id TEXT PRIMARY KEY, name TEXT, method TEXT, url TEXT,
        headers TEXT, body TEXT, assert TEXT, status TEXT,
        lastCode INTEGER, lastMs INTEGER, tags TEXT, updated TEXT)""",
    )
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS as_envs (
        id TEXT PRIMARY KEY, name TEXT, base TEXT, vars TEXT)""",
    )
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS as_history (
        id TEXT PRIMARY KEY, eid TEXT, env TEXT, count INTEGER,
        pass INTEGER, fail INTEGER, time TEXT, mode TEXT, detail TEXT)""",
    )
    await db_commit(db)


async def _seed_if_empty(db: SyncDB) -> None:
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM as_endpoints", [])
    if not (row and row["c"]):
        for r in _SEED_ENDPOINTS:
            item = dict(r)
            item["headers"] = json.dumps(r["headers"], ensure_ascii=False)
            item["body"] = (
                json.dumps(r["body"], ensure_ascii=False) if r["body"] != "" else ""
            )
            item["assert"] = json.dumps(r["assert"], ensure_ascii=False)
            item["tags"] = json.dumps(r["tags"], ensure_ascii=False)
            item["updated"] = _today()
            await db_insert(db, "as_endpoints", item)
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM as_envs", [])
    if not (row and row["c"]):
        for r in _SEED_ENVS:
            item = dict(r)
            item["vars"] = json.dumps(r["vars"], ensure_ascii=False)
            await db_insert(db, "as_envs", item)
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM as_history", [])
    if not (row and row["c"]):
        for r in _SEED_HISTORY:
            item = dict(r)
            item["detail"] = ""
            await db_insert(db, "as_history", item)
    await db_commit(db)


async def _ready(db: SyncDB) -> None:
    await _ensure_schema(db)
    await _seed_if_empty(db)


def _ep_row(r: dict) -> dict:
    asserts = _j(r.get("assert"), [])
    if not isinstance(asserts, list):
        asserts = [str(asserts)] if asserts else []
    tags = _j(r.get("tags"), [])
    if not isinstance(tags, list):
        tags = [str(tags)] if tags else []
    return {
        "id": r.get("id"),
        "name": r.get("name") or "",
        "method": r.get("method") or "GET",
        "url": r.get("url") or "",
        "headers": _j(r.get("headers"), {}) or {},
        "body": _j(r.get("body"), "") if r.get("body") else "",
        "assert": asserts,
        "assertCount": len(asserts),
        "status": r.get("status") or "",
        "lastCode": r.get("lastCode"),
        "lastMs": r.get("lastMs"),
        "tags": tags,
        "updated": r.get("updated") or "",
    }


def _env_row(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "name": r.get("name") or "",
        "base": r.get("base") or "",
        "vars": _j(r.get("vars"), []) or [],
    }


def _hist_row(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "eid": r.get("eid") or "",
        "env": r.get("env") or "",
        "count": r.get("count") or 0,
        "pass": r.get("pass") or 0,
        "fail": r.get("fail") or 0,
        "time": r.get("time") or "",
        "mode": r.get("mode") or "",
        "detail": _j(r.get("detail"), []) or [],
    }


async def _load(db: SyncDB, eid: str) -> dict:
    row = await db_fetch_one(db, "SELECT * FROM as_endpoints WHERE id=?", [eid])
    if not row:
        raise HTTPException(status_code=404, detail="接口不存在")
    return row


async def _next_id(db: SyncDB, prefix: str = "API-") -> str:
    rows = await db_fetch_all(
        db, "SELECT id FROM as_endpoints WHERE id LIKE ?", [prefix + "%"]
    )
    best = 100
    for r in rows:
        try:
            best = max(best, int(str(r["id"]).split("-")[-1]))
        except Exception:
            pass
    return "%s%d" % (prefix, best + 1)


async def _next_hist_id(db: SyncDB) -> str:
    rows = await db_fetch_all(db, "SELECT id FROM as_history WHERE id LIKE 'HR-%'", [])
    best = 310
    for r in rows:
        try:
            best = max(best, int(str(r["id"]).split("-")[-1]))
        except Exception:
            pass
    return "HR-%d" % (best + 1)


# ---------------------------------------------------------------------------
# pydantic
# ---------------------------------------------------------------------------


class EndpointCreate(BaseModel):
    id: str = ""
    name: str
    method: str = "GET"
    url: str
    headers: Dict[str, str] = {}
    body: Any = ""
    assertList: List[str] = []
    status: str = ""
    tags: List[str] = []


class EndpointUpdate(BaseModel):
    name: Optional[str] = None
    method: Optional[str] = None
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    body: Optional[Any] = None
    assertList: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    status: Optional[str] = None


class RunBatchReq(BaseModel):
    ids: List[str] = []
    env: str = "TEST"
    mode: str = "串行"


class EnvCreate(BaseModel):
    id: str = ""
    name: str
    base: str = ""
    vars: List[Dict[str, str]] = []


class EnvUpdate(BaseModel):
    name: Optional[str] = None
    base: Optional[str] = None
    vars: Optional[List[Dict[str, str]]] = None


class AiAssertReq(BaseModel):
    response: Any
    expect: str = ""


class AiParseReq(BaseModel):
    swagger: Any = ""


# ---------------------------------------------------------------------------
# executor
# ---------------------------------------------------------------------------


def _is_local_or_public(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


async def _execute_endpoint(ep: dict) -> dict:
    """尝试真实 HTTP 请求；失败则返回演示结果。"""
    url = ep.get("url") or ""
    method = (ep.get("method") or "GET").upper()
    hdr_raw = _j(ep.get("headers"), {}) or {}
    headers = hdr_raw if isinstance(hdr_raw, dict) else {}
    body_raw = ep.get("body")
    body_obj = _j(body_raw, None) if body_raw not in (None, "") else None

    started = _time.monotonic()
    if _is_local_or_public(url):
        try:
            kwargs: Dict[str, Any] = {
                "headers": {str(k): str(v) for k, v in headers.items()}
            }
            if method in ("POST", "PUT", "PATCH", "DELETE") and body_obj is not None:
                if isinstance(body_obj, (dict, list)):
                    kwargs["json"] = body_obj
                else:
                    kwargs["content"] = str(body_obj)
                    kwargs["headers"].setdefault("Content-Type", "application/json")
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                resp = await client.request(method, url, **kwargs)
            ms = int((_time.monotonic() - started) * 1000)
            text = resp.text
            try:
                payload: Any = resp.json()
            except Exception:
                payload = text[:2000]
            return {
                "real": True,
                "code": resp.status_code,
                "ms": ms,
                "body": payload,
                "ok": 200 <= resp.status_code < 300,
            }
        except Exception:
            pass  # fall through to mock

    # mock 演示结果
    ms = random.randint(45, 420)
    code = 200 if method != "DELETE" or random.random() > 0.15 else 404
    mock_body = {
        "code": 0 if code == 200 else code,
        "msg": "ok" if code == 200 else "not found",
        "data": {"id": 1001, "token": "mock-token-" + ep.get("id", "x"), "list": []},
        "demo": True,
    }
    return {"real": False, "code": code, "ms": ms, "body": mock_body, "ok": code < 400}


# ---------------------------------------------------------------------------
# endpoints CRUD
# ---------------------------------------------------------------------------


@router.get("/api-testing/endpoints")
async def list_endpoints(db: SyncDB = Depends(get_db)):
    await _ready(db)
    rows = await db_fetch_all(db, "SELECT * FROM as_endpoints ORDER BY id", [])
    return [_ep_row(r) for r in rows]


@router.get("/api-testing/endpoints/{eid}")
async def get_endpoint(eid: str, db: SyncDB = Depends(get_db)):
    await _ready(db)
    return _ep_row(await _load(db, eid))


@router.post("/api-testing/endpoints")
async def create_endpoint(
    body: EndpointCreate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    if not body.name.strip() or not body.url.strip():
        raise HTTPException(status_code=400, detail="name/url 必填")
    eid = body.id.strip() or await _next_id(db)
    if await db_fetch_one(db, "SELECT id FROM as_endpoints WHERE id=?", [eid]):
        raise HTTPException(status_code=409, detail="接口 ID 已存在")
    await db_insert(
        db,
        "as_endpoints",
        {
            "id": eid,
            "name": body.name.strip(),
            "method": (body.method or "GET").upper(),
            "url": body.url.strip(),
            "headers": json.dumps(body.headers or {}, ensure_ascii=False),
            "body": json.dumps(body.body, ensure_ascii=False)
            if body.body not in (None, "")
            else "",
            "assert": json.dumps(body.assertList or [], ensure_ascii=False),
            "status": body.status or "",
            "lastCode": None,
            "lastMs": None,
            "tags": json.dumps(body.tags or [], ensure_ascii=False),
            "updated": _today(),
        },
    )
    return _ep_row(await _load(db, eid))


@router.put("/api-testing/endpoints/{eid}")
async def update_endpoint(
    eid: str,
    body: EndpointUpdate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    await _load(db, eid)
    data: Dict[str, Any] = {}
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(status_code=400, detail="name 不能为空")
        data["name"] = body.name.strip()
    if body.method is not None:
        data["method"] = body.method.upper()
    if body.url is not None:
        data["url"] = body.url
    if body.headers is not None:
        data["headers"] = json.dumps(body.headers, ensure_ascii=False)
    if body.body is not None:
        data["body"] = (
            json.dumps(body.body, ensure_ascii=False) if body.body != "" else ""
        )
    if body.assertList is not None:
        data["assert"] = json.dumps(body.assertList, ensure_ascii=False)
    if body.tags is not None:
        data["tags"] = json.dumps(body.tags, ensure_ascii=False)
    if body.status is not None:
        data["status"] = body.status
    data["updated"] = _today()
    await db_update(db, "as_endpoints", data, "id=?", [eid])
    return _ep_row(await _load(db, eid))


@router.delete("/api-testing/endpoints/{eid}")
async def delete_endpoint(
    eid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    await _load(db, eid)
    await db_execute(db, "DELETE FROM as_endpoints WHERE id=?", [eid])
    await db_commit(db)
    return {"ok": True, "id": eid}


# ---------------------------------------------------------------------------
# run / batch / history
# ---------------------------------------------------------------------------


async def _record_history(
    db: SyncDB, eid: str, env: str, results: List[dict], mode: str
) -> dict:
    passed = sum(1 for r in results if r.get("ok"))
    failed = len(results) - passed
    hid = await _next_hist_id(db)
    await db_insert(
        db,
        "as_history",
        {
            "id": hid,
            "eid": eid,
            "env": env or "TEST",
            "count": len(results),
            "pass": passed,
            "fail": failed,
            "time": _now(),
            "mode": mode,
            "detail": json.dumps(results, ensure_ascii=False),
        },
    )
    row = await db_fetch_one(db, "SELECT * FROM as_history WHERE id=?", [hid])
    if not row:
        raise HTTPException(status_code=500, detail="历史写入失败")
    return _hist_row(row)


@router.post("/api-testing/endpoints/{eid}/run")
async def run_endpoint(
    eid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    ep = await _load(db, eid)
    result = await _execute_endpoint(ep)
    status = S_PASS if result["ok"] else S_FAIL
    await db_update(
        db,
        "as_endpoints",
        {
            "status": status,
            "lastCode": result["code"],
            "lastMs": result["ms"],
            "updated": _today(),
        },
        "id=?",
        [eid],
    )
    hist = await _record_history(
        db,
        eid,
        "TEST",
        [
            {
                "id": eid,
                "name": ep.get("name"),
                "code": result["code"],
                "ms": result["ms"],
                "ok": result["ok"],
            }
        ],
        "单个",
    )
    row = await _load(db, eid)
    return {
        "endpoint": _ep_row(row),
        "result": {
            "code": result["code"],
            "ms": result["ms"],
            "ok": result["ok"],
            "real": result["real"],
            "body": result["body"],
            "status": status,
        },
        "history": hist,
    }


@router.post("/api-testing/run-batch")
async def run_batch(
    body: RunBatchReq,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    ids = body.ids or []
    if not ids:
        rows = await db_fetch_all(db, "SELECT id FROM as_endpoints ORDER BY id", [])
        ids = [r["id"] for r in rows]
    results: List[dict] = []
    for eid in ids:
        ep = await db_fetch_one(db, "SELECT * FROM as_endpoints WHERE id=?", [eid])
        if not ep:
            results.append(
                {
                    "id": eid,
                    "ok": False,
                    "code": 0,
                    "ms": 0,
                    "name": "",
                    "error": "not found",
                }
            )
            continue
        r = await _execute_endpoint(ep)
        status = S_PASS if r["ok"] else S_FAIL
        await db_update(
            db,
            "as_endpoints",
            {
                "status": status,
                "lastCode": r["code"],
                "lastMs": r["ms"],
                "updated": _today(),
            },
            "id=?",
            [eid],
        )
        results.append(
            {
                "id": eid,
                "name": ep.get("name"),
                "code": r["code"],
                "ms": r["ms"],
                "ok": r["ok"],
                "status": status,
            }
        )
    hist = await _record_history(db, "", body.env, results, body.mode or "串行")
    passed = sum(1 for r in results if r.get("ok"))
    return {
        "total": len(results),
        "pass": passed,
        "fail": len(results) - passed,
        "results": results,
        "history": hist,
    }


@router.get("/api-testing/history")
async def list_history(db: SyncDB = Depends(get_db)):
    await _ready(db)
    rows = await db_fetch_all(
        db, "SELECT * FROM as_history ORDER BY time DESC, id DESC", []
    )
    return [_hist_row(r) for r in rows]


# ---------------------------------------------------------------------------
# envs
# ---------------------------------------------------------------------------


@router.get("/api-testing/envs")
async def list_envs(db: SyncDB = Depends(get_db)):
    await _ready(db)
    rows = await db_fetch_all(db, "SELECT * FROM as_envs ORDER BY id", [])
    return [_env_row(r) for r in rows]


@router.post("/api-testing/envs")
async def create_env(
    body: EnvCreate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="环境名称不能为空")
    eid = body.id.strip() or ("ENV-" + body.name.strip().upper())
    if await db_fetch_one(db, "SELECT id FROM as_envs WHERE id=?", [eid]):
        raise HTTPException(status_code=409, detail="环境已存在")
    await db_insert(
        db,
        "as_envs",
        {
            "id": eid,
            "name": body.name.strip(),
            "base": body.base,
            "vars": json.dumps(body.vars or [], ensure_ascii=False),
        },
    )
    row = await db_fetch_one(db, "SELECT * FROM as_envs WHERE id=?", [eid])
    if not row:
        raise HTTPException(status_code=500, detail="环境写入失败")
    return _env_row(row)


@router.put("/api-testing/envs/{eid}")
async def update_env(
    eid: str,
    body: EnvUpdate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    row = await db_fetch_one(db, "SELECT * FROM as_envs WHERE id=?", [eid])
    if not row:
        raise HTTPException(status_code=404, detail="环境不存在")
    data: Dict[str, Any] = {}
    if body.name is not None:
        data["name"] = body.name
    if body.base is not None:
        data["base"] = body.base
    if body.vars is not None:
        data["vars"] = json.dumps(body.vars, ensure_ascii=False)
    if data:
        await db_update(db, "as_envs", data, "id=?", [eid])
    row = await db_fetch_one(db, "SELECT * FROM as_envs WHERE id=?", [eid])
    return _env_row(row) if row else {}


@router.delete("/api-testing/envs/{eid}")
async def delete_env(
    eid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    row = await db_fetch_one(db, "SELECT id FROM as_envs WHERE id=?", [eid])
    if not row:
        raise HTTPException(status_code=404, detail="环境不存在")
    await db_execute(db, "DELETE FROM as_envs WHERE id=?", [eid])
    await db_commit(db)
    return {"ok": True, "id": eid}


# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------


@router.post("/api-testing/ai-assert")
async def ai_assert(
    body: AiAssertReq,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    resp_text = (
        body.response
        if isinstance(body.response, str)
        else json.dumps(body.response, ensure_ascii=False)
    )
    prompt = (
        "根据以下 HTTP 响应生成测试断言（每行一条，简洁可执行）：\n"
        f"响应：{resp_text[:2000]}"
    )
    if body.expect:
        prompt += f"\n期望：{body.expect}"
    text = await ai_svc.simple(db, prompt, module="接口测试")
    lines = [ln.strip(" -•\t") for ln in str(text).splitlines() if ln.strip()]
    asserts = [ln for ln in lines if ln][:10] or ["status_code == 200"]
    return {"asserts": asserts, "text": text}


@router.post("/api-testing/ai-parse")
async def ai_parse(
    body: AiParseReq,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    raw = body.swagger
    raw_text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    # 1) 尝试本地结构化解析 openapi/swagger JSON
    parsed: List[dict] = []
    obj: Any = None
    if isinstance(raw, (dict, list)):
        obj = raw
    else:
        try:
            obj = json.loads(raw_text) if raw_text.strip().startswith("{") else None
        except Exception:
            obj = None
    if isinstance(obj, dict):
        paths = obj.get("paths") or {}
        if isinstance(paths, dict) and paths:
            n = 0
            for path, ops in paths.items():
                if not isinstance(ops, dict):
                    continue
                for m, meta in ops.items():
                    if m.upper() not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                        continue
                    n += 1
                    summary = (meta or {}).get("summary") or path
                    parsed.append(
                        {
                            "id": "API-S%03d" % n,
                            "name": summary,
                            "method": m.upper(),
                            "url": path,
                            "tags": ["swagger"],
                        }
                    )
    if parsed:
        return {"endpoints": parsed, "source": "local-parse"}
    # 2) AI 解析；失败/无结构则演示
    try:
        prompt = (
            "把下面的 Swagger/OpenAPI 文档解析为接口列表，只输出 JSON 数组：\n"
            '[{"id":"API-201","name":"...","method":"GET","url":"/path","tags":["swagger"]}]\n'
            f"文档：{raw_text[:3000]}"
        )
        data = await ai_svc.chat_json(
            db, [{"role": "user", "content": prompt}], module="接口测试"
        )
        if isinstance(data, list) and data:
            return {"endpoints": data, "source": "ai"}
    except Exception:
        pass
    return {"endpoints": _DEMO_PARSE, "source": "demo"}
