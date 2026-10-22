"""工作空间 / 成员 / 邀请 / 审计 / 核心接口标记。

契约依据：spec/01 A2、A7(audit)、A9、A5(27 endpoints/core)。
"""

from fastapi import APIRouter, Body, Depends

from app.core.database import (
    SyncDB,
    db_delete,
    db_fetch_all,
    db_fetch_one,
    db_insert,
    db_update,
    get_db,
)
from app.core.deps import get_current_user

from .common import (
    ApiError,
    audit,
    jdump,
    jload,
    now_str,
    require_member,
    require_owner,
)
from .schemas import CoreMarkBody, InviteBody, WorkspaceCreateBody, WorkspacePatchBody

router = APIRouter(tags=["api-intel-workspaces"])


# =============================================================================
# A2 工作空间
# =============================================================================


@router.get("/workspaces")
async def list_workspaces(
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """我拥有或参与的全部工作空间（含我在其中的角色）。"""
    rows = await db_fetch_all(
        db,
        """
        SELECT w.*, m.role AS my_role FROM ai_ws w
        JOIN ai_ws_members m ON m.ws_id = w.id
        WHERE m.user_id=?
        ORDER BY w.updated_at DESC, w.id DESC
        """,
        [user["id"]],
    )
    items = []
    for r in rows:
        items.append(
            {
                "id": r["id"],
                "name": r["name"],
                "role": r["my_role"]
                or ("owner" if int(r["owner_id"]) == int(user["id"]) else "member"),
                "settings": jload(r.get("settings_json"), {}) or {},
                "created_at": r.get("created_at") or "",
                "updated_at": r.get("updated_at") or "",
            }
        )
    return {"items": items}


@router.post("/workspaces")
async def create_workspace(
    body: WorkspaceCreateBody = Body(default=WorkspaceCreateBody()),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    name = (body.name or "").strip()
    if not name:
        raise ApiError(400, "请输入项目名称")
    if len(name) > 120:
        raise ApiError(400, "项目名称过长（最多 120 字）")
    now = now_str()
    ws_id = await db_insert(
        db,
        "ai_ws",
        {
            "owner_id": user["id"],
            "name": name,
            "settings_json": jdump(body.settings or {}),
            "created_at": now,
            "updated_at": now,
        },
    )
    await db_insert(
        db,
        "ai_ws_members",
        {"ws_id": ws_id, "user_id": user["id"], "role": "owner", "created_at": now},
    )
    await audit(db, ws_id, user["id"], "创建工作空间", {"name": name})
    return {
        "item": {
            "id": ws_id,
            "name": name,
            "role": "owner",
            "settings": body.settings or {},
            "created_at": now,
            "updated_at": now,
        }
    }


@router.patch("/workspaces/{ws_id}")
async def patch_workspace(
    ws_id: int,
    body: WorkspacePatchBody = Body(default=WorkspacePatchBody()),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """重命名 {name} 与保存设置 {settings} 共用（可同传）。"""
    ws = await require_member(ws_id, user, db)
    if body.name is None and body.settings is None:
        raise ApiError(400, "没有需要更新的字段")
    data: dict = {}
    item: dict = {"id": ws_id}
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise ApiError(400, "名称不能为空")
        if len(name) > 120:
            raise ApiError(400, "项目名称过长（最多 120 字）")
        data["name"] = name
        item["name"] = name
        await audit(
            db, ws_id, user["id"], "重命名工作空间", {"from": ws["name"], "to": name}
        )
    if body.settings is not None:
        data["settings_json"] = jdump(body.settings)
        item["settings"] = body.settings
        await audit(db, ws_id, user["id"], "更新工作空间设置", {})
    now = now_str()
    data["updated_at"] = now
    await db_update(db, "ai_ws", data, "id=?", [ws_id])
    item["updated_at"] = now
    return {"item": item}


@router.delete("/workspaces/{ws_id}")
async def delete_workspace(
    ws_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await require_owner(ws_id, user, db)
    await audit(db, ws_id, user["id"], "删除工作空间", {})
    # 级联清理（审计保留，便于跨空间追溯）
    for table in (
        "ai_ws_members",
        "ai_ws_invites",
        "ai_specs",
        "ai_hits",
        "ai_coverage_reports",
        "ai_changes_reports",
        "ai_endpoint_map",
        "ai_edge_devices",
        "ai_edge_timer",
        "ai_notify_config",
        "ai_notify_logs",
    ):
        await db_delete(db, table, "ws_id=?", [ws_id])
    # 运行任务日志先删（无 ws_id 列）
    jobs = await db_fetch_all(db, "SELECT id FROM ai_run_jobs WHERE ws_id=?", [ws_id])
    for j in jobs:
        await db_delete(db, "ai_run_job_logs", "job_id=?", [j["id"]])
    await db_delete(db, "ai_run_jobs", "ws_id=?", [ws_id])
    await db_delete(db, "ai_run_profiles", "ws_id=?", [ws_id])
    await db_delete(db, "ai_ws", "id=?", [ws_id])
    return {"ok": True}


# =============================================================================
# A9 成员与邀请
# =============================================================================


@router.get("/workspaces/{ws_id}/members")
async def list_members(
    ws_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    ws = await require_member(ws_id, user, db)
    rows = await db_fetch_all(
        db,
        """
        SELECT m.user_id, m.role, u.username, u.full_name, u.email, u.phone
        FROM ai_ws_members m JOIN users u ON u.id = m.user_id
        WHERE m.ws_id=? ORDER BY CASE m.role WHEN 'owner' THEN 0 ELSE 1 END, m.created_at
        """,
        [ws_id],
    )
    items = []
    for r in rows:
        label = (
            r.get("full_name")
            or r.get("username")
            or (r.get("email") or "").split("@")[0]
        )
        items.append(
            {"user_id": r["user_id"], "label": label, "role": r["role"] or "member"}
        )
    # 当前用户角色（owner_id 兜底）
    role = ws.get("my_role") or "member"
    # 待处理邀请（仅 owner 可见明细）
    pending = []
    if role == "owner":
        inv_rows = await db_fetch_all(
            db,
            """
            SELECT i.id, i.invitee_user_id, u.username, u.full_name, u.email
            FROM ai_ws_invites i JOIN users u ON u.id = i.invitee_user_id
            WHERE i.ws_id=? AND i.status='pending' ORDER BY i.id DESC
            """,
            [ws_id],
        )
        for r in inv_rows:
            label = (
                r.get("full_name")
                or r.get("username")
                or (r.get("email") or "").split("@")[0]
            )
            pending.append(
                {"id": r["id"], "label": label, "invitee_user_id": r["invitee_user_id"]}
            )
    return {"items": items, "role": role, "pending_invites": pending}


async def _find_user_by_identifier(db: SyncDB, identifier: str):
    """按手机号/邮箱/用户名精确查找用户。"""
    return await db_fetch_one(
        db,
        "SELECT * FROM users WHERE phone=? OR email=? OR username=? LIMIT 1",
        [identifier, identifier, identifier],
    )


@router.post("/workspaces/{ws_id}/invites")
async def create_invite(
    ws_id: int,
    body: InviteBody = Body(default=InviteBody()),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """按手机号或邮箱邀请成员（生成 pending 邀请，等待对方确认）。"""
    await require_owner(ws_id, user, db)
    identifier = (body.identifier or "").strip()
    if not identifier:
        raise ApiError(400, "请填写对方手机号或邮箱")
    target = await _find_user_by_identifier(db, identifier)
    if not target:
        raise ApiError(400, "未找到该用户")
    if int(target["id"]) == int(user["id"]):
        raise ApiError(400, "不能邀请自己")
    existed = await db_fetch_one(
        db,
        "SELECT id FROM ai_ws_members WHERE ws_id=? AND user_id=?",
        [ws_id, target["id"]],
    )
    if existed:
        raise ApiError(400, "该用户已是工作空间成员")
    dup = await db_fetch_one(
        db,
        "SELECT id FROM ai_ws_invites WHERE ws_id=? AND invitee_user_id=? AND status='pending'",
        [ws_id, target["id"]],
    )
    if dup:
        raise ApiError(400, "已发送过邀请，等待对方确认")
    inv_id = await db_insert(
        db,
        "ai_ws_invites",
        {
            "ws_id": ws_id,
            "inviter_id": user["id"],
            "invitee_user_id": target["id"],
            "status": "pending",
            "created_at": now_str(),
        },
    )
    await audit(db, ws_id, user["id"], "邀请成员", {"identifier": identifier})
    label = target.get("full_name") or target.get("username")
    return {"ok": True, "item": {"id": inv_id, "label": label, "status": "pending"}}


@router.delete("/workspaces/{ws_id}/members/{member_id}")
async def remove_member(
    ws_id: int,
    member_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """移除成员（仅 owner；member_id 是 user_id）。"""
    await require_owner(ws_id, user, db)
    if int(member_id) == int(user["id"]):
        raise ApiError(400, "所有者不可移除自己")
    row = await db_fetch_one(
        db,
        "SELECT * FROM ai_ws_members WHERE ws_id=? AND user_id=?",
        [ws_id, member_id],
    )
    if not row:
        raise ApiError(404, "该成员不在此工作空间")
    if (row["role"] or "") == "owner":
        raise ApiError(400, "所有者不可被移除")
    await db_delete(db, "ai_ws_members", "ws_id=? AND user_id=?", [ws_id, member_id])
    await audit(db, ws_id, user["id"], "移除成员", {"user_id": member_id})
    return {"ok": True}


@router.post("/invites/{invite_id}/accept")
async def accept_invite(
    invite_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    inv = await db_fetch_one(db, "SELECT * FROM ai_ws_invites WHERE id=?", [invite_id])
    if not inv:
        raise ApiError(404, "邀请不存在")
    if int(inv["invitee_user_id"]) != int(user["id"]):
        raise ApiError(403, "只能处理发给自己的邀请")
    if inv["status"] != "pending":
        raise ApiError(400, "该邀请已处理")
    await db_update(db, "ai_ws_invites", {"status": "accepted"}, "id=?", [invite_id])
    existed = await db_fetch_one(
        db,
        "SELECT id FROM ai_ws_members WHERE ws_id=? AND user_id=?",
        [inv["ws_id"], user["id"]],
    )
    if not existed:
        await db_insert(
            db,
            "ai_ws_members",
            {
                "ws_id": inv["ws_id"],
                "user_id": user["id"],
                "role": "member",
                "created_at": now_str(),
            },
        )
    await audit(db, inv["ws_id"], user["id"], "接受邀请", {"invite_id": invite_id})
    return {"ok": True, "ws_id": inv["ws_id"]}


@router.post("/invites/{invite_id}/reject")
async def reject_invite(
    invite_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    inv = await db_fetch_one(db, "SELECT * FROM ai_ws_invites WHERE id=?", [invite_id])
    if not inv:
        raise ApiError(404, "邀请不存在")
    if int(inv["invitee_user_id"]) != int(user["id"]):
        raise ApiError(403, "只能处理发给自己的邀请")
    if inv["status"] != "pending":
        raise ApiError(400, "该邀请已处理")
    await db_update(db, "ai_ws_invites", {"status": "rejected"}, "id=?", [invite_id])
    await audit(db, inv["ws_id"], user["id"], "拒绝邀请", {"invite_id": invite_id})
    return {"ok": True}


# =============================================================================
# A5(27) 核心接口标记（存 settings.endpoint_core = {key: bool}）
# =============================================================================


@router.post("/workspaces/{ws_id}/endpoints/core")
async def mark_core(
    ws_id: int,
    body: CoreMarkBody = Body(default=CoreMarkBody()),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    ws = await require_member(ws_id, user, db)
    if not body.keys:
        raise ApiError(400, "请选择要标记的接口")
    settings = dict(ws.get("settings") or {})
    core_map = dict(settings.get("endpoint_core") or {})
    for k in body.keys:
        key = str(k or "").strip()
        if not key:
            continue
        if body.core:
            core_map[key] = True
        else:
            core_map.pop(key, None)
    settings["endpoint_core"] = core_map
    await db_update(
        db,
        "ai_ws",
        {"settings_json": jdump(settings), "updated_at": now_str()},
        "id=?",
        [ws_id],
    )
    await audit(
        db,
        ws_id,
        user["id"],
        "标记核心接口" if body.core else "取消核心标记",
        {"keys": body.keys},
    )
    return {"ok": True, "core": bool(body.core), "count": len(body.keys)}


# =============================================================================
# A7(35) 审计流水
# =============================================================================


@router.get("/workspaces/{ws_id}/audit")
async def list_audit(
    ws_id: int,
    limit: int = 30,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await require_member(ws_id, user, db)
    limit = max(1, min(int(limit or 30), 200))
    rows = await db_fetch_all(
        db,
        """
        SELECT a.*, u.username, u.full_name FROM ai_audit a
        LEFT JOIN users u ON u.id = a.user_id
        WHERE a.ws_id=? ORDER BY a.id DESC LIMIT ?
        """,
        [ws_id, limit],
    )
    items = []
    for r in rows:
        label = r.get("full_name") or r.get("username") or ""
        items.append(
            {
                "id": r["id"],
                "created_at": r.get("created_at") or "",
                "action": r.get("action") or "",
                "user_id": r.get("user_id"),
                "user_label": label,
                "detail": jload(r.get("detail_json"), {}) or {},
            }
        )
    return {"items": items}
