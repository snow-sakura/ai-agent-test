"""压测编排工作台（Scenario Studio）— /api/scenario/*

表：sc_plans / sc_groups / sc_nodes
- 计划树形 CRUD
- JMX 导出、curl 导入、HTTP 批量造数、节点顺序重排
"""

import json
import random
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from xml.sax.saxutils import escape

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

router = APIRouter(tags=["scenario"])

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


# ---------------------------------------------------------------------------
# schema / seed
# ---------------------------------------------------------------------------


async def _ensure_schema(db: SyncDB) -> None:
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS sc_plans (
        id TEXT PRIMARY KEY, name TEXT, threads INTEGER, loops INTEGER,
        status TEXT, updated TEXT)""",
    )
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS sc_groups (
        id TEXT PRIMARY KEY, plan_id TEXT, name TEXT, threads INTEGER, ord INTEGER)""",
    )
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS sc_nodes (
        id TEXT PRIMARY KEY, group_id TEXT, method TEXT, url TEXT,
        headers TEXT, body TEXT, delay INTEGER, ord INTEGER, name TEXT)""",
    )
    await db_commit(db)


async def _seed_if_empty(db: SyncDB) -> None:
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM sc_plans", [])
    if row and row["c"]:
        return
    # 计划 1
    await db_insert(
        db,
        "sc_plans",
        {
            "id": "SC-1",
            "name": "交易核心链路压测",
            "threads": 50,
            "loops": 10,
            "status": "草稿",
            "updated": _now(),
        },
    )
    await db_insert(
        db,
        "sc_groups",
        {
            "id": "SCG-1",
            "plan_id": "SC-1",
            "name": "下单线程组",
            "threads": 30,
            "ord": 0,
        },
    )
    await db_insert(
        db,
        "sc_nodes",
        {
            "id": "SCN-1",
            "group_id": "SCG-1",
            "method": "GET",
            "url": "https://api.example.com/v1/skus",
            "headers": json.dumps({"Content-Type": "application/json"}),
            "body": "",
            "delay": 0,
            "ord": 0,
            "name": "查询商品",
        },
    )
    await db_insert(
        db,
        "sc_nodes",
        {
            "id": "SCN-2",
            "group_id": "SCG-1",
            "method": "POST",
            "url": "https://api.example.com/v1/orders",
            "headers": json.dumps({"Content-Type": "application/json"}),
            "body": json.dumps({"sku": "{{sku}}", "count": 1}, ensure_ascii=False),
            "delay": 200,
            "ord": 1,
            "name": "创建订单",
        },
    )
    await db_insert(
        db,
        "sc_groups",
        {
            "id": "SCG-2",
            "plan_id": "SC-1",
            "name": "支付线程组",
            "threads": 20,
            "ord": 1,
        },
    )
    await db_insert(
        db,
        "sc_nodes",
        {
            "id": "SCN-3",
            "group_id": "SCG-2",
            "method": "POST",
            "url": "https://api.example.com/v1/pay",
            "headers": json.dumps({"Content-Type": "application/json"}),
            "body": json.dumps({"orderId": "{{orderId}}"}, ensure_ascii=False),
            "delay": 100,
            "ord": 0,
            "name": "发起支付",
        },
    )
    # 计划 2
    await db_insert(
        db,
        "sc_plans",
        {
            "id": "SC-2",
            "name": "登录接口阶梯加压",
            "threads": 20,
            "loops": 5,
            "status": "已发布",
            "updated": _now(),
        },
    )
    await db_insert(
        db,
        "sc_groups",
        {
            "id": "SCG-3",
            "plan_id": "SC-2",
            "name": "登录",
            "threads": 20,
            "ord": 0,
        },
    )
    await db_insert(
        db,
        "sc_nodes",
        {
            "id": "SCN-4",
            "group_id": "SCG-3",
            "method": "POST",
            "url": "https://api.example.com/v1/auth/login",
            "headers": json.dumps({"Content-Type": "application/json"}),
            "body": json.dumps(
                {"username": "demo", "password": "demo123"}, ensure_ascii=False
            ),
            "delay": 0,
            "ord": 0,
            "name": "用户登录",
        },
    )
    await db_commit(db)


async def _ready(db: SyncDB) -> None:
    await _ensure_schema(db)
    await _seed_if_empty(db)


async def _next_plan_id(db: SyncDB) -> str:
    rows = await db_fetch_all(db, "SELECT id FROM sc_plans WHERE id LIKE 'SC-%'", [])
    best = 0
    for r in rows:
        try:
            best = max(best, int(str(r["id"]).split("-")[-1]))
        except Exception:
            pass
    return "SC-%d" % (best + 1)


async def _next_id(db: SyncDB, table: str, prefix: str) -> str:
    rows = await db_fetch_all(
        db, f"SELECT id FROM {table} WHERE id LIKE ?", [prefix + "%"]
    )
    best = 0
    for r in rows:
        try:
            best = max(best, int(str(r["id"]).split("-")[-1]))
        except Exception:
            pass
    return "%s%d" % (prefix, best + 1)


def _node_row(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "groupId": r.get("group_id") or "",
        "name": r.get("name") or "",
        "method": r.get("method") or "GET",
        "url": r.get("url") or "",
        "headers": _j(r.get("headers"), {}) or {},
        "body": _j(r.get("body"), "") if r.get("body") else "",
        "delay": r.get("delay") or 0,
        "order": r.get("ord") or 0,
    }


def _group_row(r: dict, nodes: List[dict]) -> dict:
    return {
        "id": r.get("id"),
        "planId": r.get("plan_id") or "",
        "name": r.get("name") or "",
        "threads": r.get("threads") or 1,
        "order": r.get("ord") or 0,
        "nodes": nodes,
    }


def _plan_row(r: dict, groups: List[dict]) -> dict:
    threads = r.get("threads") or 0
    node_count = sum(len(g.get("nodes") or []) for g in groups)
    return {
        "id": r.get("id"),
        "name": r.get("name") or "",
        "threads": threads,
        "loops": r.get("loops") or 1,
        "status": r.get("status") or "草稿",
        "updated": r.get("updated") or "",
        "groups": groups,
        "nodeCount": node_count,
    }


async def _load_plan_tree(db: SyncDB, pid: str) -> dict:
    plan = await db_fetch_one(db, "SELECT * FROM sc_plans WHERE id=?", [pid])
    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在")
    groups = await db_fetch_all(
        db, "SELECT * FROM sc_groups WHERE plan_id=? ORDER BY ord, id", [pid]
    )
    tree_groups: List[dict] = []
    for g in groups:
        nodes = await db_fetch_all(
            db, "SELECT * FROM sc_nodes WHERE group_id=? ORDER BY ord, id", [g["id"]]
        )
        tree_groups.append(_group_row(g, [_node_row(n) for n in nodes]))
    return _plan_row(plan, tree_groups)


async def _load_plan(db: SyncDB, pid: str) -> dict:
    row = await db_fetch_one(db, "SELECT * FROM sc_plans WHERE id=?", [pid])
    if not row:
        raise HTTPException(status_code=404, detail="计划不存在")
    return row


async def _ensure_default_group(db: SyncDB, pid: str) -> str:
    g = await db_fetch_one(
        db, "SELECT id FROM sc_groups WHERE plan_id=? ORDER BY ord LIMIT 1", [pid]
    )
    if g:
        return g["id"]
    gid = await _next_id(db, "sc_groups", "SCG-")
    await db_insert(
        db,
        "sc_groups",
        {
            "id": gid,
            "plan_id": pid,
            "name": "默认线程组",
            "threads": 10,
            "ord": 0,
        },
    )
    return gid


# ---------------------------------------------------------------------------
# pydantic
# ---------------------------------------------------------------------------


class NodeIn(BaseModel):
    method: str = "GET"
    url: str = ""
    headers: Dict[str, str] = {}
    body: Any = ""
    delay: int = 0
    name: str = ""


class GroupIn(BaseModel):
    name: str = "线程组"
    threads: int = 10
    nodes: List[NodeIn] = []


class PlanCreate(BaseModel):
    id: str = ""
    name: str
    threads: int = 10
    loops: int = 1
    status: str = "草稿"
    groups: List[GroupIn] = []


class PlanUpdate(BaseModel):
    name: Optional[str] = None
    threads: Optional[int] = None
    loops: Optional[int] = None
    status: Optional[str] = None


class NodeUpdate(BaseModel):
    order: Optional[int] = None
    method: Optional[str] = None
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    body: Optional[Any] = None
    delay: Optional[int] = None
    name: Optional[str] = None


class CurlReq(BaseModel):
    curl: str
    planId: str = ""


class DataGenReq(BaseModel):
    rows: int = 10
    fields: List[str] = ["name", "phone", "email", "addr"]
    template: str = ""


# ---------------------------------------------------------------------------
# plans tree CRUD
# ---------------------------------------------------------------------------


@router.get("/scenario/plans")
async def list_plans(db: SyncDB = Depends(get_db)):
    await _ready(db)
    rows = await db_fetch_all(db, "SELECT * FROM sc_plans ORDER BY id", [])
    out = []
    for r in rows:
        out.append(await _load_plan_tree(db, r["id"]))
    return out


@router.get("/scenario/plans/{pid}")
async def get_plan(pid: str, db: SyncDB = Depends(get_db)):
    await _ready(db)
    return await _load_plan_tree(db, pid)


@router.post("/scenario/plans")
async def create_plan(
    body: PlanCreate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="计划名称不能为空")
    pid = body.id.strip() or await _next_plan_id(db)
    if await db_fetch_one(db, "SELECT id FROM sc_plans WHERE id=?", [pid]):
        raise HTTPException(status_code=409, detail="计划 ID 已存在")
    await db_insert(
        db,
        "sc_plans",
        {
            "id": pid,
            "name": body.name.strip(),
            "threads": body.threads,
            "loops": body.loops,
            "status": body.status,
            "updated": _now(),
        },
    )
    groups = body.groups or [GroupIn(name="默认线程组", threads=body.threads)]
    for gi, g in enumerate(groups):
        gid = await _next_id(db, "sc_groups", "SCG-")
        await db_insert(
            db,
            "sc_groups",
            {
                "id": gid,
                "plan_id": pid,
                "name": g.name,
                "threads": g.threads,
                "ord": gi,
            },
        )
        for ni, n in enumerate(g.nodes):
            nid = await _next_id(db, "sc_nodes", "SCN-")
            await db_insert(
                db,
                "sc_nodes",
                {
                    "id": nid,
                    "group_id": gid,
                    "method": (n.method or "GET").upper(),
                    "url": n.url,
                    "headers": json.dumps(n.headers or {}, ensure_ascii=False),
                    "body": json.dumps(n.body, ensure_ascii=False)
                    if n.body not in (None, "")
                    else "",
                    "delay": n.delay,
                    "ord": ni,
                    "name": n.name or n.url,
                },
            )
    await db_commit(db)
    return await _load_plan_tree(db, pid)


@router.put("/scenario/plans/{pid}")
async def update_plan(
    pid: str,
    body: PlanUpdate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    await _load_plan(db, pid)
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    data["updated"] = _now()
    await db_update(db, "sc_plans", data, "id=?", [pid])
    return await _load_plan_tree(db, pid)


@router.delete("/scenario/plans/{pid}")
async def delete_plan(
    pid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    await _load_plan(db, pid)
    groups = await db_fetch_all(db, "SELECT id FROM sc_groups WHERE plan_id=?", [pid])
    for g in groups:
        await db_execute(db, "DELETE FROM sc_nodes WHERE group_id=?", [g["id"]])
    await db_execute(db, "DELETE FROM sc_groups WHERE plan_id=?", [pid])
    await db_execute(db, "DELETE FROM sc_plans WHERE id=?", [pid])
    await db_commit(db)
    return {"ok": True, "id": pid}


# ---------------------------------------------------------------------------
# groups / nodes
# ---------------------------------------------------------------------------


@router.post("/scenario/plans/{pid}/groups")
async def add_group(
    pid: str,
    body: GroupIn,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    await _load_plan(db, pid)
    gid = await _next_id(db, "sc_groups", "SCG-")
    max_ord = await db_fetch_one(
        db, "SELECT COALESCE(MAX(ord), -1) AS m FROM sc_groups WHERE plan_id=?", [pid]
    )
    await db_insert(
        db,
        "sc_groups",
        {
            "id": gid,
            "plan_id": pid,
            "name": body.name,
            "threads": body.threads,
            "ord": (max_ord["m"] if max_ord else -1) + 1,
        },
    )
    await db_update(db, "sc_plans", {"updated": _now()}, "id=?", [pid])
    return await _load_plan_tree(db, pid)


@router.put("/scenario/nodes/{nid}")
async def update_node(
    nid: str,
    body: NodeUpdate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """更新节点字段；带 order 时在同组内重排（drag 顺序）。"""
    await _ready(db)
    node = await db_fetch_one(db, "SELECT * FROM sc_nodes WHERE id=?", [nid])
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")
    gid = node["group_id"]
    data: Dict[str, Any] = {}
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
    if body.delay is not None:
        data["delay"] = body.delay
    if body.name is not None:
        data["name"] = body.name
    if data:
        await db_update(db, "sc_nodes", data, "id=?", [nid])

    if body.order is not None:
        siblings = await db_fetch_all(
            db, "SELECT id FROM sc_nodes WHERE group_id=? ORDER BY ord, id", [gid]
        )
        ids = [s["id"] for s in siblings]
        if nid in ids:
            ids.remove(nid)
        target = max(0, min(int(body.order), len(ids)))
        ids.insert(target, nid)
        for i, xid in enumerate(ids):
            await db_update(db, "sc_nodes", {"ord": i}, "id=?", [xid])

    plan_id = await db_fetch_one(db, "SELECT plan_id FROM sc_groups WHERE id=?", [gid])
    if plan_id:
        await db_update(
            db, "sc_plans", {"updated": _now()}, "id=?", [plan_id["plan_id"]]
        )
    row = await db_fetch_one(db, "SELECT * FROM sc_nodes WHERE id=?", [nid])
    if not row:
        raise HTTPException(status_code=404, detail="节点不存在")
    return _node_row(row)


@router.delete("/scenario/nodes/{nid}")
async def delete_node(
    nid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    node = await db_fetch_one(db, "SELECT * FROM sc_nodes WHERE id=?", [nid])
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")
    await db_execute(db, "DELETE FROM sc_nodes WHERE id=?", [nid])
    await db_commit(db)
    return {"ok": True, "id": nid}


# ---------------------------------------------------------------------------
# JMX / curl / data-gen
# ---------------------------------------------------------------------------


def _build_jmx(plan: dict) -> str:
    groups = plan.get("groups") or []
    tg_blocks = []
    for gi, g in enumerate(groups):
        nodes = g.get("nodes") or []
        samplers = []
        for n in nodes:
            url = n.get("url") or ""
            try:
                p = urlparse(url)
                domain, path, protocol = p.netloc, p.path or "/", p.scheme or "http"
            except Exception:
                domain, path, protocol = "example.com", "/", "http"
            body = n.get("body")
            if isinstance(body, (dict, list)):
                body_text = json.dumps(body, ensure_ascii=False)
            else:
                body_text = str(body or "")
            headers = n.get("headers") or {}
            header_xml = ""
            if headers:
                coll = "".join(
                    f'<elementProp name="{escape(str(k))}" StringProp="Argument.value">{escape(str(v))}</elementProp>'
                    for k, v in headers.items()
                )
                header_xml = (
                    f'<HeaderManager guiclass="HeaderPanel" testclass="HeaderManager" '
                    f'testname="HTTP 请求头" enabled="true"><collectionProp name="HeaderManager.headers">{coll}'
                    f"</collectionProp></HeaderManager>"
                )
            delay = int(n.get("delay") or 0)
            timer_xml = ""
            if delay > 0:
                timer_xml = (
                    f'<ConstantTimer guiclass="ConstantTimerGui" testclass="ConstantTimer" '
                    f'testname="固定定时器" enabled="true">'
                    f'<stringProp name="ConstantTimer.delay">{delay}</stringProp></ConstantTimer>'
                )
            samplers.append(
                f'<HTTPSamplerProxy guiclass="HttpTestSampleGui" testclass="HTTPSamplerProxy" '
                f'testname="{escape(n.get("name") or n.get("url") or "HTTP 请求")}" enabled="true">'
                f'<stringProp name="HTTPSampler.domain">{escape(domain)}</stringProp>'
                f'<stringProp name="HTTPSampler.port"></stringProp>'
                f'<stringProp name="HTTPSampler.protocol">{escape(protocol)}</stringProp>'
                f'<stringProp name="HTTPSampler.path">{escape(path)}</stringProp>'
                f'<stringProp name="HTTPSampler.method">{escape(n.get("method") or "GET")}</stringProp>'
                f'<boolProp name="HTTPSampler.postBodyRaw">{"true" if (n.get("method") or "GET").upper() != "GET" and body_text else "false"}</boolProp>'
                f'<boolProp name="HTTPSampler.follow_redirects">true</boolProp>'
                f'<boolProp name="HTTPSampler.use_keepalive">true</boolProp>'
                + (
                    f'<elementProp name="HTTPsampler.Arguments" HTTPArgumentsProp="HTTPArgumentProp">'
                    f'<collectionProp name="HTTPArguments.arguments">'
                    f'<elementProp name="" HTTPArgumentProp="">'
                    f'<stringProp name="Argument.value">{escape(body_text)}</stringProp>'
                    f'<boolProp name="Argument.metadata">true</boolProp>'
                    f"</elementProp></collectionProp></elementProp>"
                    if body_text and (n.get("method") or "GET").upper() != "GET"
                    else ""
                )
                + "</HTTPSamplerProxy>"
            )
        children = "".join(samplers)
        # 定时器/请求头挂在 hash tree 的兄弟位置（简化结构）
        extra = ""
        for n in nodes:
            headers = n.get("headers") or {}
            if headers:
                coll = "".join(
                    f'<elementProp name="{escape(str(k))}" StringProp="Argument.value">{escape(str(v))}</elementProp>'
                    for k, v in headers.items()
                )
                extra += (
                    f'<HeaderManager guiclass="HeaderPanel" testclass="HeaderManager" '
                    f'testname="HTTP 请求头" enabled="true">'
                    f'<collectionProp name="HeaderManager.headers">{coll}</collectionProp></HeaderManager>'
                )
            delay = int(n.get("delay") or 0)
            if delay > 0:
                extra += (
                    f'<ConstantTimer guiclass="ConstantTimerGui" testclass="ConstantTimer" '
                    f'testname="固定定时器" enabled="true">'
                    f'<stringProp name="ConstantTimer.delay">{delay}</stringProp></ConstantTimer>'
                )
        tg_blocks.append(
            f"<hashTree>"
            f'<ThreadGroup guiclass="ThreadGroupGui" testclass="ThreadGroup" '
            f'testname="{escape(g.get("name") or f"线程组 {gi + 1}")}" enabled="true">'
            f'<intProp name="ThreadGroup.num_threads">{int(g.get("threads") or 1)}</intProp>'
            f'<intProp name="ThreadGroup.ramp_time">5</intProp>'
            f'<boolProp name="ThreadGroup.scheduler">false</boolProp>'
            f'<stringProp name="ThreadGroup.on_sample_error">continue</stringProp>'
            f'<elementProp name="ThreadGroup.main_controller" LoopControllerProp="LoopController">'
            f'<stringProp name="LoopController.loops">{int(plan.get("loops") or 1)}</stringProp>'
            f'<boolProp name="LoopController.continue_forever">false</boolProp>'
            f"</elementProp></ThreadGroup>"
            f"<hashTree>{children}{extra}</hashTree>"
            f"</hashTree>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<jmeterTestPlan version="1.2" properties="5.0" jmeter="5.6">\n'
        "<hashTree>\n"
        '<TestPlan guiclass="TestPlanGui" testclass="TestPlan" '
        f'testname="{escape(plan.get("name") or "测试计划")}" enabled="true">'
        '<boolProp name="TestPlan.functional_mode">false</boolProp>'
        '<boolProp name="TestPlan.serialize_threadgroups">false</boolProp>'
        "</TestPlan>\n<hashTree>\n"
        + "".join(tg_blocks)
        + "\n</hashTree>\n</hashTree>\n</jmeterTestPlan>\n"
    )


@router.post("/scenario/plans/{pid}/jmx")
async def export_jmx(
    pid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    plan = await _load_plan_tree(db, pid)
    jmx = _build_jmx(plan)
    return {"jmx": jmx, "name": plan["name"], "filename": f"{pid}.jmx"}


def _parse_curl(curl: str) -> dict:
    text = curl.strip()
    text = re.sub(r"^\s*curl\s+", "", text, flags=re.I)
    method = "GET"
    headers: Dict[str, str] = {}
    body = ""
    url = ""
    # -X METHOD
    m = re.search(r"-X\s+([A-Za-z]+)", text)
    if m:
        method = m.group(1).upper()
    # -H
    for hm in re.finditer(r"-H\s+['\"]([^'\"]+)['\"]", text):
        kv = hm.group(1)
        if ":" in kv:
            k, v = kv.split(":", 1)
            headers[k.strip()] = v.strip()
    # -d / --data / --data-raw
    dm = re.search(r"(?:-d|--data(?:-raw|-binary)?)\s+['\"](.*?)['\"]", text, re.S)
    if dm:
        body = (
            dm.group(1).encode().decode("unicode_escape")
            if "\\n" in dm.group(1)
            else dm.group(1)
        )
        body = body.replace('\\"', '"').replace("\\'", "'")
        if method == "GET":
            method = "POST"
    # URL: first quoted or bare http(s) token
    um = re.search(r"https?://[^\s'\"]+", text)
    if um:
        url = um.group(0).rstrip("\\")
    else:
        qm = re.search(r"['\"](https?://[^'\"]+)['\"]", text)
        if qm:
            url = qm.group(1)
    return {"method": method, "url": url, "headers": headers, "body": body}


@router.post("/scenario/import-curl")
async def import_curl(
    body: CurlReq,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    if not body.curl.strip():
        raise HTTPException(status_code=400, detail="curl 不能为空")
    parsed = _parse_curl(body.curl)
    if not parsed["url"]:
        raise HTTPException(status_code=400, detail="无法从 curl 中解析 URL")

    pid = body.planId.strip()
    if pid:
        await _load_plan(db, pid)
    else:
        pid = await _next_plan_id(db)
        await db_insert(
            db,
            "sc_plans",
            {
                "id": pid,
                "name": "curl 导入计划",
                "threads": 10,
                "loops": 1,
                "status": "草稿",
                "updated": _now(),
            },
        )
    gid = await _ensure_default_group(db, pid)
    max_ord = await db_fetch_one(
        db, "SELECT COALESCE(MAX(ord), -1) AS m FROM sc_nodes WHERE group_id=?", [gid]
    )
    nid = await _next_id(db, "sc_nodes", "SCN-")
    await db_insert(
        db,
        "sc_nodes",
        {
            "id": nid,
            "group_id": gid,
            "method": parsed["method"],
            "url": parsed["url"],
            "headers": json.dumps(parsed["headers"], ensure_ascii=False),
            "body": parsed["body"],
            "delay": 0,
            "ord": (max_ord["m"] if max_ord else -1) + 1,
            "name": "curl 导入请求",
        },
    )
    await db_update(db, "sc_plans", {"updated": _now()}, "id=?", [pid])
    row = await db_fetch_one(db, "SELECT * FROM sc_nodes WHERE id=?", [nid])
    if not row:
        raise HTTPException(status_code=500, detail="节点写入失败")
    return {"planId": pid, "node": _node_row(row), "parsed": parsed}


def _gen_field(field: str, i: int) -> str:
    f = (field or "").lower()
    if f in ("name", "姓名"):
        return random.choice(_SURNAMES) + random.choice(_GIVEN)
    if f in ("phone", "mobile", "手机"):
        return "1" + random.choice("35789") + "".join(random.choices("0123456789", k=9))
    if f in ("email", "邮箱"):
        return f"test_{1000 + i}@{random.choice(['qq.com', '163.com', 'gmail.com'])}"
    if f in ("addr", "address", "地址"):
        return (
            random.choice(_CITIES)
            + random.choice(["幸福路", "望江道", "科技园"])
            + str(random.randint(1, 999))
            + "号"
        )
    if f in ("id", "seq", "序号"):
        return str(i + 1)
    if f in ("amount", "金额"):
        return f"{random.randint(10, 990) / 10:.2f}"
    if f in ("city", "城市"):
        return random.choice(_CITIES)[:3]
    if f in ("uuid",):
        import uuid as _uuid

        return str(_uuid.uuid4())
    if f in ("date", "日期"):
        return datetime.now().strftime("%Y-%m-%d")
    return f"{field}-{i + 1}"


@router.post("/scenario/data-gen")
async def data_gen(
    body: DataGenReq,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """HTTP 批量造数：返回 csv 文本 + rows。"""
    await _ready(db)
    n = max(1, min(int(body.rows or 10), 2000))
    fields = body.fields or ["name", "phone", "email", "addr"]
    rows: List[Dict[str, Any]] = []
    for i in range(n):
        row = {f: _gen_field(f, i) for f in fields}
        rows.append(row)
    header = ",".join(fields)
    lines = [header]
    for r in rows:
        lines.append(",".join(str(r.get(f, "")) for f in fields))
    csv = "\n".join(lines)
    return {"csv": csv, "rows": rows, "count": n, "fields": fields}
