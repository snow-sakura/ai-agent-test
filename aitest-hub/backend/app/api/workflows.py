"""工作流编辑器（Workflows）— /api/workflows/*。

复用 core.database 已有 `workflows` 表（id, project_id, name, description,
canvas, nodes, created_at, updated_at），并按需兼容补充 status / runs 列：
- canvas / nodes 列均存 JSON {"nodes":[...],"edges":[...]}（nodes 列为主）
- GET  /workflows            列表（name, desc, updated, nodes count, status）
- GET  /workflows/{id}       详情（nodes 数组 + edges）
- POST/PUT/DELETE /workflows
- POST /workflows/{id}/run   模拟执行各节点
- POST /workflows/ai-layout  AI 建议布局/连线

seed 2 条 UI 演示工作流（UI/tool-workflow-editor.html）。列表不鉴权；写操作鉴权。
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
from app.services import ai

router = APIRouter(tags=["workflows"])


class Canvas(BaseModel):
    nodes: List[dict] = []
    edges: List[dict] = []


class WfCreate(BaseModel):
    name: str
    description: str = ""
    canvas: Canvas = Canvas()
    status: str = "草稿"


class WfUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    canvas: Optional[Canvas] = None
    status: Optional[str] = None


class AiLayoutReq(BaseModel):
    nodes: List[dict] = []
    task: str = ""


_SEED = [
    {
        "name": "退款回归全链路",
        "description": "解析需求 → 生成用例 → 执行接口回归 → 结果通知",
        "status": "已发布",
        "created_at": "2026-09-19 10:20",
        "updated_at": "2026-09-22 02:35",
        "nodes": [
            {"key": "n1", "type": "start", "name": "开始", "cfg": {}, "x": 40, "y": 160},
            {"key": "n2", "type": "mcp", "name": "解析需求文档", "cfg": {"mcp": "需求文档解析"}, "x": 200, "y": 160},
            {"key": "n3", "type": "skill", "name": "生成回归用例", "cfg": {"skill": "AG-08"}, "x": 380, "y": 80},
            {"key": "n4", "type": "skill", "name": "执行接口回归", "cfg": {"skill": "AG-02"}, "x": 380, "y": 240},
            {"key": "n5", "type": "judge", "name": "全部通过?", "cfg": {"expr": "pass_rate == 1"}, "x": 560, "y": 160},
            {"key": "n6", "type": "end", "name": "推送结果", "cfg": {"notify": "wecom"}, "x": 740, "y": 160},
        ],
        "edges": [
            {"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"},
            {"from": "n3", "to": "n4"}, {"from": "n4", "to": "n5"},
            {"from": "n5", "to": "n6"},
        ],
    },
    {
        "name": "夜间安全扫描流水",
        "description": "安全基线扫描 → 高危过滤 → 企微告警",
        "status": "已发布",
        "created_at": "2026-09-12 21:00",
        "updated_at": "2026-09-21 04:10",
        "nodes": [
            {"key": "n1", "type": "start", "name": "开始", "cfg": {}, "x": 40, "y": 160},
            {"key": "n2", "type": "skill", "name": "安全基线扫描", "cfg": {"skill": "SK-03"}, "x": 220, "y": 160},
            {"key": "n3", "type": "judge", "name": "存在高危?", "cfg": {"expr": "high > 0"}, "x": 420, "y": 160},
            {"key": "n4", "type": "end", "name": "企微告警", "cfg": {"notify": "wecom"}, "x": 620, "y": 80},
        ],
        "edges": [
            {"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"},
            {"from": "n3", "to": "n4"},
        ],
    },
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


async def _ensure_schema(db: SyncDB) -> None:
    """复用已有 workflows 表；缺列则兼容补充（status / runs）。"""
    await db_execute(
        db,
        """
    CREATE TABLE IF NOT EXISTS workflows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER, name VARCHAR(200) NOT NULL,
        description TEXT, canvas TEXT, nodes TEXT,
        created_at TIMESTAMP, updated_at TIMESTAMP
    )""",
    )
    cols = await db_fetch_all(db, "PRAGMA table_info(workflows)", [])
    names = {c.get("name") for c in cols}
    if "status" not in names:
        await db_execute(db, "ALTER TABLE workflows ADD COLUMN status TEXT DEFAULT '草稿'")
    if "runs" not in names:
        await db_execute(db, "ALTER TABLE workflows ADD COLUMN runs INTEGER DEFAULT 0")
    await db_commit(db)


async def _seed_if_empty(db: SyncDB) -> None:
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM workflows", [])
    if row and row["c"]:
        return
    for w in _SEED:
        canvas_json = json.dumps(
            {"nodes": w["nodes"], "edges": w["edges"]}, ensure_ascii=False
        )
        await db_insert(db, "workflows", {
            "project_id": None, "name": w["name"], "description": w["description"],
            "canvas": canvas_json, "nodes": canvas_json,
            "status": w["status"], "runs": random.randint(5, 25),
            "created_at": w["created_at"], "updated_at": w["updated_at"],
        })
    await db_commit(db)


async def _prepare(db: SyncDB) -> None:
    await _ensure_schema(db)
    await _seed_if_empty(db)


def _parse_canvas(r: dict) -> dict:
    raw = r.get("nodes") or r.get("canvas") or "{}"
    if isinstance(raw, (dict, list)):
        data = raw if isinstance(raw, dict) else {"nodes": raw, "edges": []}
    else:
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
    if isinstance(data, list):
        data = {"nodes": data, "edges": []}
    nodes = data.get("nodes") or []
    edges = data.get("edges") or []
    # 兼容 UI 旧格式 edges 为 {from: [to,...]}
    if isinstance(edges, dict):
        flat = []
        for src, dsts in edges.items():
            for d in (dsts if isinstance(dsts, list) else [dsts]):
                flat.append({"from": src, "to": d})
        edges = flat
    return {"nodes": nodes, "edges": edges}


def _row(r: dict) -> dict:
    canvas = _parse_canvas(r)
    return {
        "id": r.get("id"),
        "name": r.get("name") or "",
        "desc": r.get("description") or "",
        "description": r.get("description") or "",
        "status": r.get("status") or "草稿",
        "nodes": len(canvas["nodes"]),
        "runs": r.get("runs") or 0,
        "created": r.get("created_at") or "",
        "updated": r.get("updated_at") or "",
        "createdAt": r.get("created_at") or "",
        "updatedAt": r.get("updated_at") or "",
    }


def _detail(r: dict) -> dict:
    canvas = _parse_canvas(r)
    out = _row(r)
    out["canvas"] = canvas
    out["edges"] = canvas["edges"]
    out["nodeList"] = canvas["nodes"]
    return out


async def _load(db: SyncDB, wid) -> dict:
    row = await db_fetch_one(db, "SELECT * FROM workflows WHERE id=?", [wid])
    if not row:
        raise HTTPException(status_code=404, detail="workflow not found")
    return row


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.get("/workflows")
async def list_workflows(db: SyncDB = Depends(get_db)):
    await _prepare(db)
    rows = await db_fetch_all(db, "SELECT * FROM workflows ORDER BY id DESC", [])
    return [_row(r) for r in rows]


@router.get("/workflows/{wid}")
async def get_workflow(wid: int, db: SyncDB = Depends(get_db)):
    await _prepare(db)
    return _detail(await _load(db, wid))


@router.post("/workflows")
async def create_workflow(body: WfCreate, db: SyncDB = Depends(get_db),
                          current_user: dict = Depends(get_current_user)):
    await _prepare(db)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="name required")
    canvas_json = json.dumps(
        {"nodes": body.canvas.nodes, "edges": body.canvas.edges}, ensure_ascii=False
    )
    wid = await db_insert(db, "workflows", {
        "project_id": None, "name": body.name.strip(),
        "description": body.description, "canvas": canvas_json, "nodes": canvas_json,
        "status": body.status, "runs": 0,
        "created_at": _now(), "updated_at": _now(),
    })
    return _detail(await _load(db, wid))


@router.put("/workflows/{wid}")
async def update_workflow(wid: int, body: WfUpdate, db: SyncDB = Depends(get_db),
                          current_user: dict = Depends(get_current_user)):
    await _prepare(db)
    await _load(db, wid)
    data = {"updated_at": _now()}
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(status_code=400, detail="name required")
        data["name"] = body.name.strip()
    if body.description is not None:
        data["description"] = body.description
    if body.status is not None:
        data["status"] = body.status
    if body.canvas is not None:
        canvas_json = json.dumps(
            {"nodes": body.canvas.nodes, "edges": body.canvas.edges},
            ensure_ascii=False,
        )
        data["canvas"] = canvas_json
        data["nodes"] = canvas_json
    await db_update(db, "workflows", data, "id=?", [wid])
    return _detail(await _load(db, wid))


@router.delete("/workflows/{wid}")
async def delete_workflow(wid: int, db: SyncDB = Depends(get_db),
                          current_user: dict = Depends(get_current_user)):
    await _prepare(db)
    await _load(db, wid)
    await db_delete(db, "workflows", "id=?", [wid])
    return {"ok": True, "id": wid}


# ---------------------------------------------------------------------------
# 执行 / AI 布局
# ---------------------------------------------------------------------------

_RUN_TEMPLATE = {
    "start": ("开始节点触发，载入运行上下文", "ctx 已初始化"),
    "mcp": ("调用 MCP 工具解析输入", "解析完成，产出结构化输入 12 项"),
    "skill": ("执行绑定技能", "技能执行成功，产出 20 条用例 / 断言集"),
    "judge": ("评估判断条件", "条件表达式求值完成"),
    "loop": ("循环迭代", "循环 1/1 完成"),
    "end": ("结束并分发结果", "结果已推送 wecom 通知"),
}


@router.post("/workflows/{wid}/run")
async def run_workflow(wid: int, db: SyncDB = Depends(get_db)):
    await _prepare(db)
    wf = await _load(db, wid)
    canvas = _parse_canvas(wf)
    results = []
    for i, node in enumerate(canvas["nodes"]):
        ntype = str(node.get("type") or "skill")
        desc, out = _RUN_TEMPLATE.get(ntype, _RUN_TEMPLATE["skill"])
        dur = random.randint(80, 2400)
        results.append({
            "key": node.get("key") or f"n{i + 1}",
            "name": node.get("name") or ntype,
            "type": ntype,
            "status": "成功",
            "dur": f"{dur}ms",
            "output": out,
            "logs": f"[node {i + 1}/{len(canvas['nodes'])}] {desc} → {out}",
        })
    await db_update(db, "workflows",
                    {"runs": (wf.get("runs") or 0) + 1, "updated_at": _now()},
                    "id=?", [wid])
    return {
        "ok": True, "id": wid, "name": wf.get("name"),
        "total": len(results), "passed": len(results),
        "results": results,
        "summary": f"共 {len(results)} 个节点全部执行成功",
    }


@router.post("/workflows/ai-layout")
async def ai_layout(body: AiLayoutReq, db: SyncDB = Depends(get_db)):
    await _prepare(db)
    nodes = body.nodes or []
    if not nodes:
        # 默认示例链：输入 → AI 生成 → 校验 → 导出
        nodes = [
            {"key": "n1", "type": "input", "name": "输入"},
            {"key": "n2", "type": "ai", "name": "AI 生成"},
            {"key": "n3", "type": "validate", "name": "校验"},
            {"key": "n4", "type": "export", "name": "导出"},
        ]

    # 本地兜底布局：按类型排层级，同层纵向排布
    _LAYER = {"input": 0, "start": 0, "mcp": 1, "skill": 1, "ai": 1,
              "llm": 1, "loop": 2, "judge": 2, "validate": 2, "export": 3, "end": 3}

    def _local_layout(items: List[dict]) -> dict:
        layers: dict = {}
        for i, n in enumerate(items):
            key = str(n.get("key") or f"n{i + 1}")
            layer = _LAYER.get(str(n.get("type") or ""), 1)
            layers.setdefault(layer, []).append((key, n))
        laid, order = [], []
        for layer in sorted(layers.keys()):
            for idx, (key, n) in enumerate(layers[layer]):
                laid.append({
                    "key": key, "type": n.get("type") or "skill",
                    "name": n.get("name") or key, "cfg": n.get("cfg") or {},
                    "x": 60 + layer * 180, "y": 60 + idx * 110,
                })
                order.append(key)
        edges = [{"from": order[i], "to": order[i + 1]}
                 for i in range(len(order) - 1)]
        return {"nodes": laid, "edges": edges}

    local = _local_layout(nodes)
    reason = "按节点类型分层布局（本地规则）"
    try:
        catalog = "\n".join(
            f"{n.get('key') or i}: type={n.get('type')} name={n.get('name')}"
            for i, n in enumerate(nodes)
        )
        data = await ai.chat_json(
            db,
            [
                {"role": "system", "content":
                    "你是工作流画布布局助手。根据节点列表给出分层布局建议，"
                    "输出 JSON：{\"nodes\":[{\"key\",\"x\",\"y\"}],"
                    "\"edges\":[{\"from\",\"to\"}],\"reason\":\"一句话\"}。"
                    "x 为 0..900 层级坐标，y 为 0..400 纵向坐标；edges 必须只连接给定 key。"},
                {"role": "user", "content":
                    (body.task or "自动分层布局") + "\n\n节点：\n" + catalog},
            ],
            module="工作流",
        )
        keys = {str(n.get("key") or f"i{i}") for i, n in enumerate(nodes)}
        ai_nodes = [n for n in (data.get("nodes") or [])
                    if str(n.get("key")) in keys]
        ai_edges = [e for e in (data.get("edges") or [])
                    if str(e.get("from")) in keys and str(e.get("to")) in keys]
        if ai_nodes:
            by_key = {str(n.get("key")): n for n in local["nodes"]}
            for an in ai_nodes:
                base = by_key.get(str(an.get("key")))
                if base is None:
                    continue
                base["x"] = int(an.get("x") or base["x"])
                base["y"] = int(an.get("y") or base["y"])
            local["nodes"] = [by_key[str(n.get("key") or f"i{i}")]
                              for i, n in enumerate(nodes)]
            if ai_edges:
                local["edges"] = [{"from": str(e["from"]), "to": str(e["to"])}
                                  for e in ai_edges]
            reason = str(data.get("reason") or "AI 布局建议")
    except Exception:
        reason += "（AI 不可用，已使用本地规则）"

    return {"nodes": local["nodes"], "edges": local["edges"], "reason": reason}
