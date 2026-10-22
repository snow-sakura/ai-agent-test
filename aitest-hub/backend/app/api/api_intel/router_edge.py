"""Edge（本机 Agent）路由全套 —— 契约 spec/01 A13 全表 + B 节行为。

路径均相对 /api/api-intel（由聚合处统一加前缀）。
鉴权：全部登录用户 + 空间成员；run/cancel/timer/agent-pack/agent-token 仅 owner。
"""

import asyncio
import json
import logging
import os
import uuid

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse, Response

from app.core.database import (
    SyncDB,
    db_fetch_all,
    db_fetch_one,
    db_insert,
    db_update,
    get_db,
)
from app.core.deps import get_current_user
from app.core.security import decode_token

from . import agent_sim
from .router_l5 import build_contract_context
from .common import (
    ApiError,
    audit,
    get_profile,
    jdump,
    jload,
    job_label_map,
    job_public,
    list_sync_jobs,
    load_job_or_404,
    now_str,
    require_member,
    require_owner,
    save_profile,
)
from .schemas import (
    AgentHeartbeatBody,
    AgentPackBody,
    RunJobCreateBody,
    RunProfileBody,
    TimerBody,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["api-intel-edge"])

PACK_FILENAME = "testhub-edge-agent-pack.zip"


# =============================================================================
# 内部小工具
# =============================================================================


def _device_public(d: dict) -> dict:
    """设备对外形状（B1/B2 渲染所需字段）。"""
    cap = jload(d.get("capabilities_json"), {}) or {}
    return {
        "id": d["id"],
        "hostname": d.get("hostname") or "",
        "status": d.get("status") or "offline",
        "os_name": d.get("os_name") or "",
        "agent_version": d.get("agent_version") or "",
        "tests_root_hint": d.get("tests_root_hint") or "",
        "capabilities": {"python_candidates": cap.get("python_candidates") or []},
    }


async def _issue_agent_token(db: SyncDB, ws_id: int) -> str:
    """生成一次性 Agent 令牌并写入设备 capabilities（供心跳回调校验）。"""
    dev = await agent_sim.ensure_device(db, ws_id)
    token = uuid.uuid4().hex
    cap = jload(dev.get("capabilities_json"), {}) or {}
    cap["agent_token"] = token
    cap["token_created_at"] = now_str()
    await db_update(
        db, "ai_edge_devices", {"capabilities_json": jdump(cap)}, "id=?", [dev["id"]]
    )
    return token


async def _device_by_token(db: SyncDB, ws_id: int, token: str):
    """按回调令牌查找设备（打包 agent 无 JWT，凭 capabilities.agent_token 鉴权）。"""
    if not token:
        return None
    rows = await db_fetch_all(
        db, "SELECT * FROM ai_edge_devices WHERE ws_id=?", [ws_id]
    )
    for r in rows:
        cap = jload(r.get("capabilities_json"), {}) or {}
        if cap.get("agent_token") and cap["agent_token"] == token:
            return r
    return None


async def _try_user(request: Request, db: SyncDB):
    """尝试从 Bearer JWT 解析当前用户（内置模拟器直连场景），失败返回 None。"""
    h = request.headers.get("authorization") or ""
    if not h.lower().startswith("bearer "):
        return None
    payload = decode_token(h.split(" ", 1)[1].strip())
    if not payload or payload.get("sub") is None:
        return None
    try:
        return await db_fetch_one(
            db, "SELECT * FROM users WHERE id=?", [int(payload["sub"])]
        )
    except (ValueError, TypeError):
        return None


def _norm_slots(slots: list) -> list:
    """slot 规范化：分钟吸附 5（round(m/5)*5%60）、去重、按时刻排序。"""
    out = set()
    for s in slots:
        try:
            h, m = int(s.get("hour")), int(s.get("minute"))
        except (AttributeError, TypeError, ValueError):
            continue
        h = max(0, min(23, h))
        m = max(0, min(59, m))
        m = int(m / 5 + 0.5) * 5 % 60  # 与前端 MINUTE_STEP=5 吸附一致
        out.add((h, m))
    return [{"hour": h, "minute": m} for h, m in sorted(out)]


# =============================================================================
# A13(61) dashboard：设备 + 在线数 + 近期同步 + 运行配置（每次调用刷新心跳）
# =============================================================================


@router.get("/workspaces/{ws_id}/edge/dashboard")
async def edge_dashboard(
    ws_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await require_member(ws_id, user, db)
    await agent_sim.ensure_device(db, ws_id)
    devices = await db_fetch_all(
        db,
        "SELECT * FROM ai_edge_devices WHERE ws_id=? ORDER BY last_seen_at DESC, id",
        [ws_id],
    )
    agent_sim.refresh_status(devices)  # 读取时重算在线，不依赖外部上报
    # 内置 Agent 随平台进程常活：读到即视为心跳
    for d in devices:
        cap = jload(d.get("capabilities_json"), {}) or {}
        if cap.get("builtin"):
            await agent_sim.touch_heartbeat(db, d["id"])
            d["status"] = "online"
    online = [d for d in devices if d["status"] == "online"]
    syncs = await list_sync_jobs(db, ws_id, 10)
    profile = await get_profile(db, ws_id)
    return {
        "dashboard": {
            "devices": [_device_public(d) for d in devices],
            "online_count": len(online),
            "recent_syncs": [
                {
                    "status": s["status"],
                    "created_at": s["created_at"],
                    "patch_fingerprint": s["patch_fingerprint"],
                }
                for s in syncs
            ],
            "run_profile": {"profile": profile},
        }
    }


# =============================================================================
# A13(62) 设备列表
# =============================================================================


@router.get("/workspaces/{ws_id}/edge/devices")
async def edge_devices(
    ws_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await require_member(ws_id, user, db)
    await agent_sim.ensure_device(db, ws_id)
    devices = await db_fetch_all(
        db,
        "SELECT * FROM ai_edge_devices WHERE ws_id=? ORDER BY last_seen_at DESC, id",
        [ws_id],
    )
    agent_sim.refresh_status(devices)
    return {"items": [_device_public(d) for d in devices]}


# =============================================================================
# A13(63/64) 运行配置 run-profile
# =============================================================================


@router.get("/workspaces/{ws_id}/edge/run-profile")
async def get_run_profile(
    ws_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await require_member(ws_id, user, db)
    return {"profile": await get_profile(db, ws_id)}


@router.post("/workspaces/{ws_id}/edge/run-profile")
async def post_run_profile(
    ws_id: int,
    body: RunProfileBody = Body(default=RunProfileBody()),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """保存项目根/入口文件/Python 命令（非法时 400 + 中文提示，校验在 validate_profile）。"""
    await require_member(ws_id, user, db)
    saved = await save_profile(db, ws_id, body.profile or {})
    await audit(db, ws_id, user["id"], "保存本机运行配置", saved)
    return {"profile": saved}


# =============================================================================
# A13(65) Python 探测
# =============================================================================


@router.post("/workspaces/{ws_id}/edge/python-discover")
async def python_discover(
    ws_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await require_member(ws_id, user, db)
    dev = await agent_sim.ensure_device(db, ws_id)
    profile = await get_profile(db, ws_id)
    # profile 未填/非法 → 静默跳过（前端提示"请先填写本机项目路径"）
    if not (profile.get("project_root") or "").strip():
        return {"skipped": True}
    try:
        from .common import validate_profile

        validate_profile(profile)
    except ApiError:
        return {"skipped": True}
    # 外置旧版 Agent 无法做项目级探测
    if not agent_sim.agent_version_ge(dev, 1, 3):
        return {"need_agent_upgrade": True}
    asyncio.create_task(agent_sim.run_python_discover(ws_id, dev["id"], user["id"]))
    return {}


# =============================================================================
# A13(66/67/68/69/70) 运行任务
# =============================================================================


@router.post("/workspaces/{ws_id}/edge/run-jobs")
async def create_run_job(
    ws_id: int,
    body: RunJobCreateBody = Body(default=RunJobCreateBody()),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await require_owner(ws_id, user, db)
    if (body.job_type or "run") != "run":
        raise ApiError(400, "当前仅支持 job_type=run 的本机运行任务")
    profile = await get_profile(db, ws_id)
    if not (profile.get("project_root") or "").strip():
        raise ApiError(400, "请先在执行台填写并保存本机项目路径（项目根目录）")
    from .common import validate_profile

    profile = validate_profile(profile)  # 非法直接 400 中文
    dev = await agent_sim.ensure_device(db, ws_id)
    job_id = str(uuid.uuid4())
    await db_insert(
        db,
        "ai_run_jobs",
        {
            "id": job_id,
            "ws_id": ws_id,
            "device_id": dev["id"],
            "job_type": "run",
            "status": "queued",
            "created_by": user["id"],
            "created_at": now_str(),
        },
    )
    await audit(db, ws_id, user["id"], "创建本机运行任务", {"job_id": job_id})
    asyncio.create_task(agent_sim.run_job_exec(job_id, ws_id, dev["id"], profile))
    return {"job": {"id": job_id}}


@router.get("/workspaces/{ws_id}/edge/run-jobs")
async def list_run_jobs(
    ws_id: int,
    page: int = 0,
    page_size: int = 10,
    limit: int = 0,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """运行记录分页（created_at desc；页码越界回落最后一页；无 page 时兼容 limit）。"""
    await require_member(ws_id, user, db)
    if page_size <= 0:
        page_size = limit if limit and limit > 0 else 10
    page_size = max(1, min(page_size, 100))
    total = (
        await db_fetch_one(
            db, "SELECT COUNT(*) AS c FROM ai_run_jobs WHERE ws_id=?", [ws_id]
        )
        or {"c": 0}
    )["c"]
    total_pages = max(1, (int(total) + page_size - 1) // page_size)
    page = max(1, min(int(page or 1), total_pages))
    rows = await db_fetch_all(
        db,
        "SELECT * FROM ai_run_jobs WHERE ws_id=? ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        [ws_id, page_size, (page - 1) * page_size],
    )
    labels = await job_label_map(db, rows)
    items = []
    for r in rows:
        pub = job_public(
            r,
            labels.get(int(r["created_by"]), "")
            if r.get("created_by") is not None
            else "",
        )
        items.append(
            {
                "id": pub["id"],
                "job_type": pub["job_type"],
                "status": pub["status"],
                "created_by_label": pub["created_by_label"],
                "created_at": pub["created_at"],
                "summary": pub["summary"],
            }
        )
    return {
        "items": items,
        "page": page,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
    }


@router.get("/workspaces/{ws_id}/edge/run-jobs/{job_id}")
async def get_run_job(
    ws_id: int,
    job_id: str,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await require_member(ws_id, user, db)
    job = await load_job_or_404(db, ws_id, job_id)
    labels = await job_label_map(db, [job])
    label = (
        labels.get(int(job["created_by"]), "")
        if job.get("created_by") is not None
        else ""
    )
    return {"job": job_public(job, label)}


@router.post("/workspaces/{ws_id}/edge/run-jobs/{job_id}/cancel")
async def cancel_run_job(
    ws_id: int,
    job_id: str,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await require_owner(ws_id, user, db)
    job = await load_job_or_404(db, ws_id, job_id)
    status = job.get("status") or ""
    if status in ("succeeded", "failed", "cancelled"):
        raise ApiError(400, "任务已结束，无法取消")
    taken = agent_sim.request_cancel(job_id)
    if status != "cancel_requested":
        await db_update(
            db, "ai_run_jobs", {"status": "cancel_requested"}, "id=?", [job_id]
        )
    if not taken:
        # 执行器不接管（如后端重启导致孤儿任务）：直接落终态
        await db_update(
            db,
            "ai_run_jobs",
            {"status": "cancelled", "finished_at": now_str()},
            "id=?",
            [job_id],
        )
    await audit(db, ws_id, user["id"], "取消运行任务", {"job_id": job_id})
    job = await load_job_or_404(db, ws_id, job_id)
    labels = await job_label_map(db, [job])
    label = (
        labels.get(int(job["created_by"]), "")
        if job.get("created_by") is not None
        else ""
    )
    return {"job": job_public(job, label)}


@router.get("/workspaces/{ws_id}/edge/run-jobs/{job_id}/logs")
async def get_run_job_logs(
    ws_id: int,
    job_id: str,
    after_seq: int = -1,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """增量日志（协议：批 <500 判尾；前端循环 ≤40 次拉全量）。"""
    await require_member(ws_id, user, db)
    await load_job_or_404(db, ws_id, job_id)
    rows = await db_fetch_all(
        db,
        "SELECT seq, text FROM ai_run_job_logs WHERE job_id=? AND seq>? ORDER BY seq LIMIT 500",
        [job_id, after_seq],
    )
    chunks = [{"seq": r["seq"], "text": r.get("text") or ""} for r in rows]
    next_seq = chunks[-1]["seq"] if chunks else int(after_seq)
    return {"chunks": chunks, "next_seq": next_seq}


# =============================================================================
# A13(71) 同步任务（dashboard 已内嵌，独立端点补齐契约）
# =============================================================================


@router.get("/workspaces/{ws_id}/edge/sync-jobs")
async def list_edge_sync_jobs(
    ws_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await require_member(ws_id, user, db)
    syncs = await list_sync_jobs(db, ws_id, 20)
    return {
        "items": [
            {
                "status": s["status"],
                "created_at": s["created_at"],
                "patch_fingerprint": s["patch_fingerprint"],
            }
            for s in syncs
        ]
    }


# =============================================================================
# A13(72/73) 定时器
# =============================================================================


@router.get("/workspaces/{ws_id}/edge/timer")
async def get_timer(
    ws_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await require_member(ws_id, user, db)
    row = await db_fetch_one(db, "SELECT * FROM ai_edge_timer WHERE ws_id=?", [ws_id])
    if not row:
        return {"timer": {"enabled": False, "slots": []}}
    return {
        "timer": {
            "enabled": bool(row.get("enabled")),
            "slots": jload(row.get("slots_json"), []) or [],
        }
    }


@router.put("/workspaces/{ws_id}/edge/timer")
async def put_timer(
    ws_id: int,
    body: TimerBody = Body(default=TimerBody()),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await require_owner(ws_id, user, db)
    raw = [s.model_dump() for s in (body.slots or [])]
    if not raw:
        raise ApiError(400, "请至少添加一个定时时段")
    if len(raw) > 10:
        raise ApiError(400, "最多 10 个时段")
    slots = _norm_slots(raw)
    if not slots:
        raise ApiError(400, "请至少添加一个定时时段")
    if len(slots) > 10:
        raise ApiError(400, "最多 10 个时段")
    payload = {
        "enabled": bool(body.enabled),
        "slots_json": jdump(slots),
        "updated_at": now_str(),
    }
    exists = await db_fetch_one(
        db, "SELECT ws_id FROM ai_edge_timer WHERE ws_id=?", [ws_id]
    )
    if exists:
        await db_update(db, "ai_edge_timer", payload, "ws_id=?", [ws_id])
    else:
        await db_insert(db, "ai_edge_timer", {"ws_id": ws_id, **payload})
    await audit(
        db,
        ws_id,
        user["id"],
        "更新定时运行配置",
        {"enabled": body.enabled, "slots": slots},
    )
    return {"timer": {"enabled": bool(body.enabled), "slots": slots}}


# =============================================================================
# A13(74) Agent 启动包 + 心跳回调 + 一次性令牌
# =============================================================================


@router.post("/workspaces/{ws_id}/edge/agent-pack.zip")
async def download_agent_pack(
    ws_id: int,
    request: Request,
    body: AgentPackBody = Body(default=AgentPackBody()),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await require_owner(ws_id, user, db)
    device_name = (body.device_name or "desktop").strip()[:64] or "desktop"
    token = await _issue_agent_token(db, ws_id)
    base_url = str(request.base_url).rstrip("/")
    ctx_json = ""
    try:
        # L5：附带契约上下文补丁；无文档/映射时不阻断打包
        ctx = await build_contract_context(db, ws_id)
        ctx_json = json.dumps(ctx, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        ctx_json = ""
    try:
        data = await asyncio.to_thread(
            agent_sim.build_agent_pack_zip, ws_id, token, base_url, ctx_json
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("生成启动包失败 ws=%s", ws_id)
        return JSONResponse(status_code=500, content={"error": f"生成启动包失败：{e}"})
    dev = await agent_sim.ensure_device(db, ws_id)
    cap = jload(dev.get("capabilities_json"), {}) or {}
    cap["pack_device_name"] = device_name
    await db_update(
        db, "ai_edge_devices", {"capabilities_json": jdump(cap)}, "id=?", [dev["id"]]
    )
    await audit(db, ws_id, user["id"], "下载 Edge 启动包", {"device_name": device_name})
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{PACK_FILENAME}"'},
    )


@router.get("/workspaces/{ws_id}/edge/agent-token")
async def get_agent_token(
    ws_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """生成一次性 Agent 回调令牌（存 ai_edge_devices.capabilities，供打包/心跳使用）。"""
    await require_owner(ws_id, user, db)
    token = await _issue_agent_token(db, ws_id)
    return {"agent_token": token}


@router.post("/workspaces/{ws_id}/edge/heartbeat")
async def edge_heartbeat(
    ws_id: int,
    body: AgentHeartbeatBody = Body(default=AgentHeartbeatBody()),
    request: Request = None,  # noqa: RUF013
    db: SyncDB = Depends(get_db),
):
    """心跳回调：平台内置 Agent 走 JWT；打包 agent 走 X-Agent-Token。"""
    user = await _try_user(request, db)
    if user is not None:
        await require_member(ws_id, user, db)
        dev = await agent_sim.ensure_device(db, ws_id)
        await agent_sim.touch_heartbeat(db, dev["id"])
        return {"ok": True, "device_id": dev["id"], "server_time": now_str()}
    # 无 JWT：凭打包令牌鉴权（令牌在启动包下载 / agent-token 时写入设备 capabilities）
    token = request.headers.get("x-agent-token") or ""
    dev = await _device_by_token(db, ws_id, token)
    if dev is None:
        raise ApiError(401, "心跳鉴权失败：Agent 令牌无效，请重新下载启动包")
    cap = jload(dev.get("capabilities_json"), {}) or {}
    if isinstance(body.capabilities, dict) and body.capabilities:
        cap.update(body.capabilities)
    cap["agent_token"] = token  # 保留令牌
    fields = {
        "capabilities_json": jdump(cap),
        "status": "online",
        "last_seen_at": now_str(),
    }
    for col, val in (
        ("hostname", body.hostname),
        ("os_name", body.os_name),
        ("agent_version", body.agent_version),
        ("tests_root_hint", body.tests_root_hint),
    ):
        if val:
            fields[col] = str(val)[:200] if col != "tests_root_hint" else str(val)
    await db_update(db, "ai_edge_devices", fields, "id=?", [dev["id"]])
    return {"ok": True, "device_id": dev["id"], "server_time": now_str()}
