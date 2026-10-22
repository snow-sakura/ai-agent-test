"""Agent 中心（Agents）— /api/agents/*。

表前缀 agt_：
- agt_agents(id,name,role,icon,model,status,tasksOk,tasksFail,last,desc,skills)
- agt_tasks(id,agentId,kind,title,status,progress,started,finished,result,logs)

seed 7 个 Agent（UI/tool-agent-center.html：需求分析/测试用例/接口/UI/数据生成/性能/APP）+ 若干任务。
列表不鉴权；写操作鉴权；run/stop 为演示执行不鉴权。
"""
import json
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

router = APIRouter(tags=["agents"])


class AgentCreate(BaseModel):
    name: str
    role: str = "测试用例"       # UI 的 cat
    icon: str = "🤖"
    model: str = "DeepSeek-V3"
    status: str = "在线"
    desc: str = ""
    skills: List[str] = []


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    icon: Optional[str] = None
    model: Optional[str] = None
    status: Optional[str] = None
    desc: Optional[str] = None
    skills: Optional[List[str]] = None


class RunReq(BaseModel):
    task: str
    kind: str = "深度"


_SEED_AGENTS = [
    {"id": "AT-12", "name": "需求解析师", "role": "需求分析", "icon": "📋",
     "model": "DeepSeek-V3", "status": "在线", "tasksOk": 123, "tasksFail": 5,
     "last": "2026-09-21 17:22", "desc": "解析需求文档输出结构化测试点与风险清单",
     "skills": ["用例补充生成"]},
    {"id": "AT-11", "name": "用例生成官", "role": "测试用例", "icon": "🧪",
     "model": "DeepSeek-V3", "status": "在线", "tasksOk": 321, "tasksFail": 21,
     "last": "今天 15:31", "desc": "按测试模式批量生成结构化用例并自动去 AI 味",
     "skills": ["用例补充生成", "接口异常场景补全"]},
    {"id": "AT-10", "name": "接口巡检员", "role": "接口测试", "icon": "🔗",
     "model": "通义千问-Max", "status": "在线", "tasksOk": 858, "tasksFail": 18,
     "last": "今天 15:00", "desc": "定时巡检核心接口可用性与断言回归",
     "skills": ["接口异常场景补全"]},
    {"id": "AT-09", "name": "UI 走查员", "role": "UI 测试", "icon": "🖥️",
     "model": "DeepSeek-V3", "status": "在线", "tasksOk": 195, "tasksFail": 19,
     "last": "2026-09-21 16:02", "desc": "主站核心页面走查 + 截图比对异常检测",
     "skills": ["UI 步骤脚本化"]},
    {"id": "AT-08", "name": "造数小工", "role": "数据生成", "icon": "🏭",
     "model": "硅基流动 · GLM-4", "status": "离线", "tasksOk": 95, "tasksFail": 0,
     "last": "2026-09-18 10:44", "desc": "按场景批量生成业务测试数据并入库",
     "skills": []},
    {"id": "AT-07", "name": "性能分析师", "role": "性能测试", "icon": "📈",
     "model": "DeepSeek-V3", "status": "在线", "tasksOk": 42, "tasksFail": 5,
     "last": "2026-09-20 18:45", "desc": "压测结果解读、瓶颈假设与调优建议",
     "skills": ["失败日志根因分析"]},
    {"id": "AT-06", "name": "APP 冒烟官", "role": "APP 自动化", "icon": "📱",
     "model": "通义千问-Max", "status": "在线", "tasksOk": 156, "tasksFail": 12,
     "last": "今天 03:00", "desc": "每日核心冒烟 + 崩溃日志归因上报",
     "skills": ["失败日志根因分析"]},
]

_SEED_TASKS = [
    {"id": "TJ-771", "agentId": "AT-11", "kind": "深度", "title": "为退款功能生成 20 条测试用例",
     "status": "成功", "progress": 100, "started": "今天 15:31", "finished": "今天 15:31",
     "result": "生成 20 条 · 导入用例管理", "logs": "加载技能「用例补充生成」→ 去AI味 → 输出 20 条"},
    {"id": "TJ-770", "agentId": "AT-10", "kind": "快速", "title": "核心接口巡检（12 个）",
     "status": "成功", "progress": 100, "started": "今天 15:00", "finished": "今天 15:01",
     "result": "12/12 通过", "logs": "健康检查 12/12 OK，平均 RT 182ms"},
    {"id": "TJ-769", "agentId": "AT-06", "kind": "深度", "title": "夜间核心冒烟",
     "status": "失败", "progress": 100, "started": "今天 03:00", "finished": "今天 03:06",
     "result": "步骤 4 元素未找到 · 已归因上报", "logs": "locator 'button.pay' not found → 归因 AG-06"},
    {"id": "TJ-768", "agentId": "AT-12", "kind": "深度", "title": "解析 PRD 退款模块 v2.1",
     "status": "成功", "progress": 100, "started": "昨天 17:22", "finished": "昨天 17:23",
     "result": "提取 34 个测试点 · 3 处风险", "logs": "文档切片 12 → 测试点 34 → 风险 3"},
    {"id": "TJ-767", "agentId": "AT-07", "kind": "深度", "title": "秒杀链路 4500 QPS 结果解读",
     "status": "成功", "progress": 100, "started": "2026-09-20 18:40",
     "finished": "2026-09-20 18:41", "result": "瓶颈=DB 连接池，建议扩容 200",
     "logs": "读取压测报告 PF-31 → 关联慢日志 → 输出调优建议"},
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


async def ensure_schema(db: SyncDB) -> None:
    await db_execute(
        db,
        """
    CREATE TABLE IF NOT EXISTS agt_agents (
        id TEXT PRIMARY KEY, name TEXT, role TEXT, icon TEXT, model TEXT,
        status TEXT, tasksOk INTEGER DEFAULT 0, tasksFail INTEGER DEFAULT 0,
        last TEXT, descr TEXT, skills TEXT
    )""",
    )
    await db_execute(
        db,
        """
    CREATE TABLE IF NOT EXISTS agt_tasks (
        id TEXT PRIMARY KEY, agentId TEXT, kind TEXT, title TEXT, status TEXT,
        progress INTEGER DEFAULT 0, started TEXT, finished TEXT, result TEXT, logs TEXT
    )""",
    )
    await db_commit(db)


async def seed_if_empty(db: SyncDB) -> None:
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM agt_agents", [])
    if not (row and row["c"]):
        for a in _SEED_AGENTS:
            await db_insert(db, "agt_agents", {
                "id": a["id"], "name": a["name"], "role": a["role"], "icon": a["icon"],
                "model": a["model"], "status": a["status"], "tasksOk": a["tasksOk"],
                "tasksFail": a["tasksFail"], "last": a["last"], "descr": a["desc"],
                "skills": json.dumps(a["skills"], ensure_ascii=False),
            })
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM agt_tasks", [])
    if not (row and row["c"]):
        for t in _SEED_TASKS:
            await db_insert(db, "agt_tasks", {
                "id": t["id"], "agentId": t["agentId"], "kind": t["kind"],
                "title": t["title"], "status": t["status"], "progress": t["progress"],
                "started": t["started"], "finished": t["finished"],
                "result": t["result"], "logs": t["logs"],
            })
    await db_commit(db)


async def _prepare(db: SyncDB) -> None:
    await ensure_schema(db)
    await seed_if_empty(db)


def _loads(v, default):
    if v is None or v == "":
        return default
    if isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return default


def _agent_row(r: dict) -> dict:
    skills = _loads(r.get("skills"), [])
    ok = r.get("tasksOk") or 0
    fail = r.get("tasksFail") or 0
    total = ok + fail
    return {
        "id": r.get("id"), "name": r.get("name"), "role": r.get("role"),
        "cat": r.get("role"),          # UI 别名
        "icon": r.get("icon") or "🤖", "model": r.get("model"),
        "status": r.get("status") or "在线", "tasksOk": ok, "tasksFail": fail,
        "last": r.get("last") or "", "desc": r.get("descr") or "",
        "skills": skills,
        "runs": total,
        "succ": round(ok * 100.0 / total, 1) if total else 100,
    }


def _task_row(r: dict) -> dict:
    return {
        "id": r.get("id"), "agentId": r.get("agentId"), "kind": r.get("kind"),
        "title": r.get("title"), "status": r.get("status"),
        "progress": r.get("progress") or 0, "started": r.get("started") or "",
        "finished": r.get("finished") or "", "result": r.get("result") or "",
        "logs": r.get("logs") or "",
    }


async def _load_agent(db: SyncDB, aid: str) -> dict:
    row = await db_fetch_one(db, "SELECT * FROM agt_agents WHERE id=?", [aid])
    if not row:
        raise HTTPException(status_code=404, detail="agent not found")
    return row


async def _next_agent_id(db: SyncDB) -> str:
    rows = await db_fetch_all(db, "SELECT id FROM agt_agents WHERE id LIKE 'AT-%'", [])
    best = 0
    for r in rows:
        try:
            best = max(best, int(str(r["id"]).split("-")[-1]))
        except Exception:
            pass
    return "AT-%02d" % (best + 1)


async def _next_task_id(db: SyncDB) -> str:
    rows = await db_fetch_all(db, "SELECT id FROM agt_tasks WHERE id LIKE 'TJ-%'", [])
    best = 0
    for r in rows:
        try:
            best = max(best, int(str(r["id"]).split("-")[-1]))
        except Exception:
            pass
    return "TJ-%03d" % (best + 1)


# ---------------------------------------------------------------------------
# Agent CRUD
# ---------------------------------------------------------------------------

@router.get("/agents")
async def list_agents(db: SyncDB = Depends(get_db)):
    await _prepare(db)
    rows = await db_fetch_all(db, "SELECT * FROM agt_agents ORDER BY id DESC", [])
    return [_agent_row(r) for r in rows]


@router.post("/agents")
async def create_agent(body: AgentCreate, db: SyncDB = Depends(get_db),
                       current_user: dict = Depends(get_current_user)):
    await _prepare(db)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="name required")
    aid = await _next_agent_id(db)
    await db_insert(db, "agt_agents", {
        "id": aid, "name": body.name.strip(), "role": body.role, "icon": body.icon,
        "model": body.model, "status": body.status, "tasksOk": 0, "tasksFail": 0,
        "last": "", "descr": body.desc,
        "skills": json.dumps(body.skills, ensure_ascii=False),
    })
    return _agent_row(await _load_agent(db, aid))


@router.put("/agents/{aid}")
async def update_agent(aid: str, body: AgentUpdate, db: SyncDB = Depends(get_db),
                       current_user: dict = Depends(get_current_user)):
    await _prepare(db)
    await _load_agent(db, aid)
    data = {}
    for k, v in (("name", body.name), ("role", body.role), ("icon", body.icon),
                 ("model", body.model), ("status", body.status)):
        if v is not None:
            data[k] = v
    if body.desc is not None:
        data["descr"] = body.desc
    if body.skills is not None:
        data["skills"] = json.dumps(body.skills, ensure_ascii=False)
    if data:
        await db_update(db, "agt_agents", data, "id=?", [aid])
    return _agent_row(await _load_agent(db, aid))


@router.delete("/agents/{aid}")
async def delete_agent(aid: str, db: SyncDB = Depends(get_db),
                       current_user: dict = Depends(get_current_user)):
    await _prepare(db)
    await _load_agent(db, aid)
    await db_execute(db, "DELETE FROM agt_tasks WHERE agentId=?", [aid])
    await db_delete(db, "agt_agents", "id=?", [aid])
    await db_commit(db)
    return {"ok": True, "id": aid}


# ---------------------------------------------------------------------------
# 执行任务（模拟推进 + AI 简报）
# ---------------------------------------------------------------------------

@router.post("/agents/{aid}/run")
async def run_agent(aid: str, body: RunReq, db: SyncDB = Depends(get_db)):
    await _prepare(db)
    agent = await _load_agent(db, aid)
    if not body.task.strip():
        raise HTTPException(status_code=400, detail="task required")

    tid = await _next_task_id(db)
    started = _now()
    await db_insert(db, "agt_tasks", {
        "id": tid, "agentId": aid, "kind": body.kind, "title": body.task.strip(),
        "status": "执行中", "progress": 10, "started": started,
        "finished": "", "result": "", "logs": f"[{started}] 任务创建，Agent「{agent.get('name')}」接单",
    })

    # 两步推进：生成中 → 完成
    await db_update(db, "agt_tasks",
                    {"progress": 60, "logs": (await db_fetch_one(
                        db, "SELECT logs FROM agt_tasks WHERE id=?", [tid]))["logs"]
                     + f"\n[{_now()}] 调度技能 {agent.get('skills') or '（无）'} 执行中"},
                    "id=?", [tid])

    system = (
        f"你是测试平台 Agent「{agent.get('name')}」，角色：{agent.get('role')}。"
        f"擅长：{agent.get('descr') or '测试执行与分析'}。"
        "请针对给定任务输出简明执行简报：结论（1 行）+ 关键产出（要点 3-5 条）+ 后续建议（1-2 条）。"
        "不要编造真实系统数据之外的承诺。"
    )
    try:
        result = await ai.simple(
            db, body.task.strip(), system=system,
            module="Agent中心", model=agent.get("model") or None,
        )
    except Exception as exc:  # noqa: BLE001
        result = f"任务已执行（AI 降级）：{body.task[:80]}；错误：{exc}"

    finished = _now()
    logs_extra = f"\n[{finished}] 执行完成，状态=成功"
    row = await db_fetch_one(db, "SELECT logs FROM agt_tasks WHERE id=?", [tid])
    await db_update(db, "agt_tasks", {
        "status": "成功", "progress": 100, "finished": finished,
        "result": result[:2000], "logs": (row.get("logs") or "") + logs_extra,
    }, "id=?", [tid])

    await db_update(db, "agt_agents", {
        "tasksOk": (agent.get("tasksOk") or 0) + 1, "last": finished,
    }, "id=?", [aid])

    task = await db_fetch_one(db, "SELECT * FROM agt_tasks WHERE id=?", [tid])
    return {"task": _task_row(task), "agent": _agent_row(await _load_agent(db, aid))}


# ---------------------------------------------------------------------------
# 任务列表 / 停止 / 统计
# ---------------------------------------------------------------------------

@router.get("/agents/tasks")
async def list_tasks(status: str = "", agentId: str = "",
                     db: SyncDB = Depends(get_db)):
    await _prepare(db)
    sql = "SELECT * FROM agt_tasks"
    conds, params = [], []
    if status:
        conds.append("status=?")
        params.append(status)
    if agentId:
        conds.append("agentId=?")
        params.append(agentId)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY id DESC"
    rows = await db_fetch_all(db, sql, params)
    return [_task_row(r) for r in rows]


@router.post("/agents/tasks/{tid}/stop")
async def stop_task(tid: str, db: SyncDB = Depends(get_db)):
    await _prepare(db)
    row = await db_fetch_one(db, "SELECT * FROM agt_tasks WHERE id=?", [tid])
    if not row:
        raise HTTPException(status_code=404, detail="task not found")
    if row.get("status") in ("成功", "失败"):
        return _task_row(row)
    await db_update(db, "agt_tasks", {
        "status": "已停止", "finished": _now(),
        "logs": (row.get("logs") or "") + f"\n[{_now()}] 人工停止",
    }, "id=?", [tid])
    agent = await db_fetch_one(db, "SELECT * FROM agt_agents WHERE id=?",
                               [row.get("agentId")])
    if agent:
        await db_update(db, "agt_agents",
                        {"tasksFail": (agent.get("tasksFail") or 0) + 1},
                        "id=?", [row.get("agentId")])
    return _task_row(await db_fetch_one(db, "SELECT * FROM agt_tasks WHERE id=?", [tid]))


@router.get("/agents/stats")
async def agent_stats(db: SyncDB = Depends(get_db)):
    await _prepare(db)
    agents = await db_fetch_all(db, "SELECT * FROM agt_agents", [])
    tasks = await db_fetch_all(db, "SELECT * FROM agt_tasks", [])
    ok = sum(1 for t in tasks if t.get("status") == "成功")
    fail = sum(1 for t in tasks if t.get("status") == "失败")
    running = sum(1 for t in tasks if t.get("status") == "执行中")
    stopped = sum(1 for t in tasks if t.get("status") == "已停止")
    online = sum(1 for a in agents if a.get("status") == "在线")
    tasks_ok = sum(a.get("tasksOk") or 0 for a in agents)
    tasks_fail = sum(a.get("tasksFail") or 0 for a in agents)
    total_hist = tasks_ok + tasks_fail
    by_role = {}
    for a in agents:
        by_role[a.get("role") or "其他"] = by_role.get(a.get("role") or "其他", 0) + 1
    return {
        "agentTotal": len(agents),
        "online": online,
        "offline": len(agents) - online,
        "taskTotal": len(tasks),
        "taskOk": ok,
        "taskFail": fail,
        "taskRunning": running,
        "taskStopped": stopped,
        "successRate": round(ok * 100.0 / len(tasks), 1) if tasks else 0,
        "historyOk": tasks_ok,
        "historyFail": tasks_fail,
        "historySuccessRate": round(tasks_ok * 100.0 / total_hist, 1) if total_hist else 100,
        "byRole": [{"role": k, "count": v} for k, v in by_role.items()],
    }
