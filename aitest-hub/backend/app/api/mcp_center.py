"""MCP 服务中心（MCP Center）— /api/mcp/*

字段对齐 UI/tool-mcp-center.html：
市场 market: id,name,cat,desc,tags,conn,proto,url,calls
我的 mine:   id,name,url,proto,status,created,health
表：mcp_market（市场）/ mcp_services（我的服务）。
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

router = APIRouter(tags=["mcp-center"])

_MARKET_SEED = [
    (
        "MC-01",
        "TestHub 数据工厂",
        "测试数据",
        "生成姓名 / 手机号 / 身份证 / 银行卡等测试数据",
        ["数据", "造数"],
        "已连接",
        "HTTP",
        "https://mcp.testhubkit.com/data-factory",
        1284,
    ),
    (
        "MC-02",
        "需求文档解析",
        "文档解析",
        "PDF / Word / TXT 需求文档结构化提取",
        ["需求", "解析"],
        "已连接",
        "HTTP",
        "https://mcp.testhubkit.com/doc-parser",
        862,
    ),
    (
        "MC-03",
        "MySQL 查询",
        "数据库",
        "只读查询业务库，辅助数据校验与断言",
        ["数据库", "SQL"],
        "未连接",
        "HTTP",
        "https://mcp.testhubkit.com/mysql",
        0,
    ),
    (
        "MC-04",
        "企业微信通知",
        "通知推送",
        "向企业微信群推送任务结果与告警",
        ["通知", "企微"],
        "已连接",
        "HTTP",
        "https://mcp.testhubkit.com/wecom",
        341,
    ),
    (
        "MC-05",
        "Jira 同步",
        "开发工具",
        "缺陷双向同步 Jira，状态变更实时回传",
        ["缺陷", "Jira"],
        "未连接",
        "WebSocket",
        "wss://mcp.testhubkit.com/jira",
        0,
    ),
    (
        "MC-06",
        "本地命令执行",
        "开发工具",
        "Stdio 协议本地命令行工具，构建 / 脚本执行",
        ["命令行", "本地"],
        "未连接",
        "Stdio",
        "npx @testhub/mcp-cli",
        0,
    ),
    # 扩展至约 12 条
    (
        "MC-07",
        "Allure 报告服务",
        "测试数据",
        "生成与托管 Allure 测试报告链接",
        ["报告", "Allure"],
        "未连接",
        "HTTP",
        "https://mcp.testhubkit.com/allure",
        0,
    ),
    (
        "MC-08",
        "Redis 缓存查询",
        "数据库",
        "只读查看缓存键值，辅助会话类断言",
        ["缓存", "Redis"],
        "未连接",
        "HTTP",
        "https://mcp.testhubkit.com/redis",
        0,
    ),
    (
        "MC-09",
        "OpenAPI 解析",
        "文档解析",
        "Swagger/OpenAPI 端点与 Schema 提取",
        ["API", "文档"],
        "已连接",
        "HTTP",
        "https://mcp.testhubkit.com/openapi",
        512,
    ),
    (
        "MC-10",
        "钉钉机器人",
        "通知推送",
        "钉钉群机器人消息推送与卡片通知",
        ["通知", "钉钉"],
        "未连接",
        "HTTP",
        "https://mcp.testhubkit.com/dingtalk",
        0,
    ),
    (
        "MC-11",
        "Git 提交查询",
        "开发工具",
        "查询提交/分支/变更文件，辅助变更影响分析",
        ["Git", "变更"],
        "未连接",
        "HTTP",
        "https://mcp.testhubkit.com/git",
        0,
    ),
    (
        "MC-12",
        "Mock 平台",
        "测试数据",
        "管理接口 Mock 规则与延迟/故障注入",
        ["Mock", "造数"],
        "未连接",
        "WebSocket",
        "wss://mcp.testhubkit.com/mock",
        0,
    ),
]

_SERVICE_SEED = [
    (
        "MS-11",
        "内部知识库 MCP",
        "http://10.0.0.8:3000/mcp",
        "HTTP",
        "启用",
        "2026-09-18",
        "正常",
    ),
    (
        "MS-10",
        "Allure 报告服务",
        "http://10.0.0.9:8081/mcp",
        "HTTP",
        "启用",
        "2026-09-12",
        "正常",
    ),
    (
        "MS-09",
        "旧版造数服务",
        "ws://10.0.0.5:9090",
        "WebSocket",
        "禁用",
        "2026-08-30",
        "—",
    ),
]


class ServiceCreate(BaseModel):
    name: str
    url: str
    proto: str = "HTTP"  # HTTP / WebSocket / Stdio
    desc: str = ""
    status: str = "启用"
    token: str = ""


class ServiceUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    proto: Optional[str] = None
    desc: Optional[str] = None
    status: Optional[str] = None


async def _ensure_schema(db: SyncDB):
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS mcp_market (
        id TEXT PRIMARY KEY, name TEXT, cat TEXT, desc TEXT,
        tags TEXT, conn TEXT, proto TEXT, url TEXT,
        calls INTEGER DEFAULT 0, installed INTEGER DEFAULT 0)""",
    )
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS mcp_services (
        id TEXT PRIMARY KEY, name TEXT, url TEXT, proto TEXT,
        status TEXT, created TEXT, health TEXT, desc TEXT,
        token TEXT, config TEXT)""",
    )
    await db_commit(db)


async def _seed_if_empty(db: SyncDB):
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM mcp_market", [])
    if not (row and row.get("c")):
        for m in _MARKET_SEED:
            await db_insert(
                db,
                "mcp_market",
                {
                    "id": m[0],
                    "name": m[1],
                    "cat": m[2],
                    "desc": m[3],
                    "tags": json.dumps(m[4], ensure_ascii=False),
                    "conn": m[5],
                    "proto": m[6],
                    "url": m[7],
                    "calls": m[8],
                    "installed": 1 if m[5] == "已连接" else 0,
                },
            )
        await db_commit(db)
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM mcp_services", [])
    if not (row and row.get("c")):
        for s in _SERVICE_SEED:
            await db_insert(
                db,
                "mcp_services",
                {
                    "id": s[0],
                    "name": s[1],
                    "url": s[2],
                    "proto": s[3],
                    "status": s[4],
                    "created": s[5],
                    "health": s[6],
                    "desc": "",
                    "token": "",
                    "config": "{}",
                },
            )
        await db_commit(db)


async def _init(db: SyncDB):
    await _ensure_schema(db)
    await _seed_if_empty(db)


def _market_row(r: dict) -> dict:
    tags = r.get("tags") or "[]"
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = [t for t in tags.split(",") if t]
    return {
        "id": r.get("id") or "",
        "name": r.get("name") or "",
        "cat": r.get("cat") or "",
        "desc": r.get("desc") or "",
        "tags": tags,
        "conn": r.get("conn") or "未连接",
        "proto": r.get("proto") or "HTTP",
        "url": r.get("url") or "",
        "calls": int(r.get("calls") or 0),
        "installed": bool(r.get("installed")),
    }


def _service_row(r: dict) -> dict:
    return {
        "id": r.get("id") or "",
        "name": r.get("name") or "",
        "url": r.get("url") or "",
        "proto": r.get("proto") or "HTTP",
        "status": r.get("status") or "启用",
        "created": r.get("created") or "",
        "health": r.get("health") or "—",
        "desc": r.get("desc") or "",
    }


async def _load_market(db: SyncDB, mid: str) -> dict:
    row = await db_fetch_one(db, "SELECT * FROM mcp_market WHERE id=?", [mid])
    if not row:
        raise HTTPException(status_code=404, detail="市场服务不存在")
    return row


async def _load_service(db: SyncDB, sid: str) -> dict:
    row = await db_fetch_one(db, "SELECT * FROM mcp_services WHERE id=?", [sid])
    if not row:
        raise HTTPException(status_code=404, detail="服务不存在")
    return row


async def _next_service_id(db: SyncDB) -> str:
    row = await db_fetch_one(
        db,
        "SELECT id FROM mcp_services ORDER BY CAST(SUBSTR(id, 4) AS INTEGER) DESC LIMIT 1",
        [],
    )
    n = 12
    if row and row.get("id"):
        try:
            n = int(str(row["id"]).replace("MS-", "")) + 1
        except ValueError:
            n = 12
    return f"MS-{n:02d}"


@router.get("/mcp/market")
async def list_market(
    q: str = Query("", description="名称/描述/标签关键词"),
    cat: str = Query("", description="分类"),
    conn: str = Query("", description="已连接/未连接"),
    db: SyncDB = Depends(get_db),
):
    """服务市场列表（只读）。"""
    await _init(db)
    rows = await db_fetch_all(db, "SELECT * FROM mcp_market ORDER BY id", [])
    ql = (q or "").lower()
    items = []
    for r in rows:
        item = _market_row(r)
        if cat and item["cat"] != cat:
            continue
        if conn and item["conn"] != conn:
            continue
        hay = (item["name"] + item["desc"] + "".join(item["tags"])).lower()
        if ql and ql not in hay:
            continue
        items.append(item)
    return items


@router.get("/mcp/mine")
async def list_mine(db: SyncDB = Depends(get_db)):
    """已注册的自有服务列表（只读）。"""
    await _init(db)
    rows = await db_fetch_all(db, "SELECT * FROM mcp_services ORDER BY id DESC", [])
    return [_service_row(r) for r in rows]


@router.post("/mcp/market/{mid}/install")
async def install_market(
    mid: str,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """接入市场服务：conn→已连接，并在「我的服务」生成对应条目。"""
    await _init(db)
    m = await _load_market(db, mid)
    if (m.get("conn") or "") == "已连接":
        return {**_market_row(m), "already": True}
    await db_update(
        db,
        "mcp_market",
        {"conn": "已连接", "installed": 1, "calls": int(m.get("calls") or 0) + 1},
        "id=?",
        [mid],
    )
    # 若尚未在我的服务中，注册一条
    existing = await db_fetch_one(
        db, "SELECT id FROM mcp_services WHERE name=?", [m.get("name")]
    )
    sid = None
    if not existing:
        sid = await _next_service_id(db)
        await db_insert(
            db,
            "mcp_services",
            {
                "id": sid,
                "name": m.get("name") or mid,
                "url": m.get("url") or "",
                "proto": m.get("proto") or "HTTP",
                "status": "启用",
                "created": datetime.now().strftime("%Y-%m-%d"),
                "health": "正常",
                "desc": m.get("desc") or "",
                "token": "",
                "config": json.dumps(
                    {"source": "market", "marketId": mid}, ensure_ascii=False
                ),
            },
        )
    else:
        sid = existing.get("id")
    await db_commit(db)
    updated = await _load_market(db, mid)
    return {**_market_row(updated), "serviceId": sid}


@router.post("/mcp/market/{mid}/uninstall")
async def uninstall_market(
    mid: str,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """断开市场服务：conn→未连接（我的服务条目保留，供手动清理）。"""
    await _init(db)
    m = await _load_market(db, mid)
    await db_update(db, "mcp_market", {"conn": "未连接", "installed": 0}, "id=?", [mid])
    await db_commit(db)
    return _market_row(await _load_market(db, mid))


@router.get("/mcp/services")
async def list_services(db: SyncDB = Depends(get_db)):
    """自有 MCP 服务列表（只读，含 desc 等详情字段）。"""
    await _init(db)
    rows = await db_fetch_all(db, "SELECT * FROM mcp_services ORDER BY id DESC", [])
    return [_service_row(r) for r in rows]


@router.post("/mcp/services")
async def create_service(
    body: ServiceCreate,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """注册自有 MCP 服务。"""
    await _init(db)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="服务名称不能为空")
    if not body.url.strip():
        raise HTTPException(status_code=400, detail="服务地址不能为空")
    sid = await _next_service_id(db)
    await db_insert(
        db,
        "mcp_services",
        {
            "id": sid,
            "name": body.name.strip(),
            "url": body.url.strip(),
            "proto": body.proto,
            "status": body.status or "启用",
            "created": datetime.now().strftime("%Y-%m-%d"),
            "health": "待测试",
            "desc": body.desc,
            "token": body.token,
            "config": "{}",
        },
    )
    return _service_row(await _load_service(db, sid))


@router.put("/mcp/services/{sid}")
async def update_service(
    sid: str,
    body: ServiceUpdate,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _init(db)
    await _load_service(db, sid)
    data = {}
    if body.name is not None:
        data["name"] = body.name.strip()
    if body.url is not None:
        data["url"] = body.url.strip()
    if body.proto is not None:
        data["proto"] = body.proto
    if body.desc is not None:
        data["desc"] = body.desc
    if body.status is not None:
        data["status"] = body.status
    if data:
        await db_update(db, "mcp_services", data, "id=?", [sid])
    return _service_row(await _load_service(db, sid))


@router.delete("/mcp/services/{sid}")
async def delete_service(
    sid: str,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _init(db)
    await _load_service(db, sid)
    await db_delete(db, "mcp_services", "id=?", [sid])
    return {"ok": True, "id": sid}


@router.post("/mcp/services/{sid}/test")
async def test_service(
    sid: str,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """连通测试（演示：启用→正常，禁用→保持 —）。"""
    await _init(db)
    svc = await _load_service(db, sid)
    if (svc.get("status") or "") != "启用":
        raise HTTPException(status_code=400, detail="服务已禁用，请先启用")
    await db_update(db, "mcp_services", {"health": "正常"}, "id=?", [sid])
    return {"ok": True, "id": sid, "health": "正常", "latencyMs": 45}
