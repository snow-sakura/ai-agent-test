"""缺陷管理(defect-management)后端路由
对齐前端 defectApi 与案例 testhubkit 缺陷管理:
- 项目列表 / 成员(角色 owner/admin/member/viewer) / 邀请与取消邀请
- 缺陷 CRUD + 过滤(状态/严重度/处理人/我的/未关闭/搜索) + 分页
- 关联用例绑定 / 评论 / (评论兼作活动流)
"""
import json as _json
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, JSON

from app.core.database import Base, get_db
from app.models.models import User, Project
from app.core.deps import get_current_user

router = APIRouter(prefix="/defect-management", tags=["defect-management"])

ROLES = {"owner": "负责人", "admin": "管理员", "member": "成员", "viewer": "只读"}


# ============ 模型 ============

class DefectItem(Base):
    __tablename__ = "dm_defects"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    display_id = Column(String(30), nullable=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    severity = Column(String(20), default="normal")  # blocker/major/normal/minor/trivial
    status = Column(String(20), default="open")  # open/in_progress/resolved/closed/rejected
    reporter_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    handlers = Column(JSON, default=list)  # [{id,label}]
    linked_case_ids = Column(JSON, default=list)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DefectComment(Base):
    __tablename__ = "dm_defect_comments"
    id = Column(Integer, primary_key=True, index=True)
    defect_id = Column(Integer, ForeignKey("dm_defects.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    body = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class DefectMember(Base):
    __tablename__ = "dm_project_members"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String(20), default="member")
    created_at = Column(DateTime, default=datetime.utcnow)


class DefectInvite(Base):
    __tablename__ = "dm_project_invites"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String(20), default="member")
    status = Column(String(20), default="pending")  # pending / accepted / cancelled
    invited_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)


# ============ 辅助 ============

def _user_label(u: Optional[User]) -> Optional[dict]:
    if not u:
        return None
    return {"id": u.id, "label": u.full_name or u.username or f"用户{u.id}"}


async def _my_role(db: AsyncSession, project_id: int, user: User) -> str:
    p = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if p and p.owner_id == user.id:
        return "owner"
    m = (await db.execute(select(DefectMember).where(
        DefectMember.project_id == project_id, DefectMember.user_id == user.id))).scalar_one_or_none()
    return m.role if m else ""


async def _require_role(db: AsyncSession, project_id: int, user: User, allowed=("owner", "admin", "member")):
    role = await _my_role(db, project_id, user)
    if role not in allowed:
        raise HTTPException(status_code=403, detail="无权限执行该操作")
    return role


def _defect_dto(d: DefectItem, users: Dict[int, User]) -> dict:
    handlers = []
    for h in (d.handlers or []):
        uid = h.get("id") if isinstance(h, dict) else h
        u = users.get(uid)
        handlers.append({"id": uid, "label": (h.get("label") if isinstance(h, dict) else None) or _user_label(u) and _user_label(u)["label"] or f"用户{uid}"})
    reporter = users.get(d.reporter_id)
    return {
        "id": d.id,
        "display_id": d.display_id or f"DM-{d.id}",
        "project_id": d.project_id,
        "title": d.title,
        "description": d.description or "",
        "severity": d.severity,
        "status": d.status,
        "reporter": {"id": d.reporter_id, "label": _user_label(reporter)["label"] if reporter else "未知"},
        "handlers": handlers,
        "linked_case_ids": d.linked_case_ids or [],
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


async def _load_users(db: AsyncSession, ids) -> Dict[int, User]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    return {u.id: u for u in rows}


async def _next_display_id(db: AsyncSession, project_id: int) -> str:
    n = (await db.execute(select(func.count(DefectItem.id)).where(DefectItem.project_id == project_id))).scalar() or 0
    return f"DM-{project_id}-{n + 1:04d}"


# ============ 项目 / 成员 ============

@router.get("/projects")
async def list_projects(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    owned_ids = select(Project.id).where(Project.owner_id == user.id)
    member_rows = (await db.execute(select(DefectMember).where(DefectMember.user_id == user.id))).scalars().all()
    member_ids = [m.project_id for m in member_rows]
    ids = set((await db.execute(select(Project.id).where(Project.id.in_(owned_ids)))).scalars().all()) | set(member_ids)
    rows = (await db.execute(select(Project).where(Project.id.in_(ids)).order_by(Project.created_at.desc()))).scalars().all() if ids else []
    out = []
    for p in rows:
        cnt = (await db.execute(select(func.count(DefectItem.id)).where(DefectItem.project_id == p.id))).scalar() or 0
        members = (await db.execute(select(DefectMember).where(DefectMember.project_id == p.id))).scalars().all()
        # 门控已移除:项目存在即可进入工作台
        team_ready = True
        out.append({
            "id": p.id, "name": p.name, "description": p.description,
            "is_owner": p.owner_id == user.id,
            "my_role": "owner" if p.owner_id == user.id else next((m.role for m in members if m.user_id == user.id), ""),
            "user_id": p.owner_id,
            "team_ready": team_ready,
            "defect_count": cnt,
        })
    return out


@router.get("/projects/{project_id}/members")
async def get_members(project_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _require_role(db, project_id, user, allowed=("owner", "admin", "member", "viewer"))
    members = (await db.execute(select(DefectMember).where(DefectMember.project_id == project_id))).scalars().all()
    invites = (await db.execute(select(DefectInvite).where(
        DefectInvite.project_id == project_id, DefectInvite.status == "pending"))).scalars().all()
    users = await _load_users(db, [m.user_id for m in members] + [i.user_id for i in invites] + [i.invited_by for i in invites])
    p = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    out_members = []
    seen_ids = set()
    if p and p.owner_id:
        ou = users.get(p.owner_id)
        out_members.append({"user_id": p.owner_id, "label": _user_label(ou)["label"] if ou else "负责人", "role": "owner"})
        seen_ids.add(p.owner_id)
    for m in members:
        if m.user_id in seen_ids:
            continue
        u = users.get(m.user_id)
        out_members.append({"user_id": m.user_id, "label": _user_label(u)["label"] if u else f"用户{m.user_id}", "role": m.role})
        seen_ids.add(m.user_id)
    out_invites = [{
        "id": i.id,
        "user_id": i.user_id,
        "label": _user_label(users.get(i.user_id))["label"] if users.get(i.user_id) else f"用户{i.user_id}",
        "role": i.role,
        "invited_by_label": _user_label(users.get(i.invited_by))["label"] if users.get(i.invited_by) else "",
    } for i in invites]
    my_role = await _my_role(db, project_id, user)
    return {
        "members": out_members,
        "invites": out_invites,
        "my_role": my_role,
        "is_owner": my_role == "owner",
        "team_ready": True,
        "can_manage": my_role in ("owner", "admin"),
    }


@router.get("/users/search")
async def search_users(q: str = "", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    q = (q or "").strip()
    stmt = select(User).limit(20)
    if q:
        stmt = stmt.where(or_(User.username.ilike(f"%{q}%"), User.email.ilike(f"%{q}%"), User.full_name.ilike(f"%{q}%")))
    rows = (await db.execute(stmt)).scalars().all()
    return [{"id": u.id, "label": u.full_name or u.username, "username": u.username, "email": u.email} for u in rows]


class InviteBody(BaseModel):
    user_id: int
    role: str = "member"


@router.post("/projects/{project_id}/members")
async def invite_member(project_id: int, body: InviteBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _require_role(db, project_id, user, allowed=("owner", "admin"))
    existing = (await db.execute(select(DefectMember).where(
        DefectMember.project_id == project_id, DefectMember.user_id == body.user_id))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="该用户已是项目成员")
    pending = (await db.execute(select(DefectInvite).where(
        DefectInvite.project_id == project_id, DefectInvite.user_id == body.user_id,
        DefectInvite.status == "pending"))).scalar_one_or_none()
    if pending:
        raise HTTPException(status_code=400, detail="已存在待处理邀请")
    role = body.role if body.role in ("admin", "member", "viewer") else "member"
    inv = DefectInvite(project_id=project_id, user_id=body.user_id, role=role, invited_by=user.id)
    db.add(inv)
    await db.commit()
    await db.refresh(inv)
    return {"id": inv.id, "user_id": inv.user_id, "role": inv.role, "status": inv.status}


class RoleBody(BaseModel):
    role: str


@router.patch("/projects/{project_id}/members/{user_id}")
async def update_member_role(project_id: int, user_id: int, body: RoleBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _require_role(db, project_id, user, allowed=("owner", "admin"))
    if body.role not in ("admin", "member", "viewer"):
        raise HTTPException(status_code=400, detail="无效角色")
    m = (await db.execute(select(DefectMember).where(
        DefectMember.project_id == project_id, DefectMember.user_id == user_id))).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="成员不存在")
    m.role = body.role
    await db.commit()
    return {"ok": True}


@router.delete("/projects/{project_id}/members/{user_id}")
async def remove_member(project_id: int, user_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _require_role(db, project_id, user, allowed=("owner", "admin"))
    m = (await db.execute(select(DefectMember).where(
        DefectMember.project_id == project_id, DefectMember.user_id == user_id))).scalar_one_or_none()
    if m:
        await db.delete(m)
        await db.commit()
    return {"ok": True}


@router.delete("/projects/{project_id}/invites/{invite_id}")
async def cancel_invite(project_id: int, invite_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _require_role(db, project_id, user, allowed=("owner", "admin"))
    inv = (await db.execute(select(DefectInvite).where(
        DefectInvite.id == invite_id, DefectInvite.project_id == project_id))).scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="邀请不存在")
    inv.status = "cancelled"
    await db.commit()
    return {"ok": True}


# ============ 缺陷 CRUD ============

@router.get("/projects/{project_id}/defects")
async def list_defects(
    project_id: int,
    page: int = 1,
    page_size: int = 10,
    status: Optional[str] = None,
    severity: Optional[str] = None,
    assignee_id: Optional[int] = None,
    q: Optional[str] = None,
    assigned_to_me: Optional[str] = None,
    unclosed: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conds = [DefectItem.project_id == project_id]
    if status:
        conds.append(DefectItem.status == status)
    if severity:
        conds.append(DefectItem.severity == severity)
    if assignee_id:
        conds.append(DefectItem.handlers.contains([{"id": assignee_id}]) | DefectItem.handlers.contains([{"id": str(assignee_id)}]))
    if assigned_to_me:
        conds.append(or_(DefectItem.handlers.contains([{"id": user.id}]), DefectItem.handlers.contains([{"id": str(user.id)}])))
    if unclosed:
        conds.append(DefectItem.status != "closed")
    if q:
        like = f"%{q}%"
        conds.append(or_(DefectItem.title.ilike(like), DefectItem.description.ilike(like), DefectItem.display_id.ilike(like)))
    where = and_(*conds)
    total = (await db.execute(select(func.count(DefectItem.id)).where(where))).scalar() or 0
    rows = (await db.execute(
        select(DefectItem).where(where).order_by(DefectItem.updated_at.desc())
        .offset((page - 1) * page_size).limit(page_size))).scalars().all()
    user_ids = set()
    for d in rows:
        user_ids.add(d.reporter_id)
        for h in (d.handlers or []):
            uid = h.get("id") if isinstance(h, dict) else h
            user_ids.add(uid)
    users = await _load_users(db, user_ids)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_defect_dto(d, users) for d in rows],
        "my_role": await _my_role(db, project_id, user),
    }


@router.get("/defects/{defect_id}")
async def get_defect(defect_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    d = (await db.execute(select(DefectItem).where(DefectItem.id == defect_id))).scalar_one_or_none()
    if not d:
        raise HTTPException(status_code=404, detail="缺陷不存在")
    users = await _load_users(db, [d.reporter_id] + [h.get("id") if isinstance(h, dict) else h for h in (d.handlers or [])])
    dto = _defect_dto(d, users)
    comments = (await db.execute(select(DefectComment).where(DefectComment.defect_id == defect_id).order_by(DefectComment.created_at))).scalars().all()
    cusers = await _load_users(db, [c.user_id for c in comments])
    dto["comments"] = [{
        "id": c.id, "body": c.body, "user": _user_label(cusers.get(c.user_id)),
        "created_at": c.created_at.isoformat() if c.created_at else None,
    } for c in comments]
    return dto


class DefectBody(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    handlers: Optional[List[Dict[str, Any]]] = None
    linked_case_ids: Optional[List[Any]] = None


@router.post("/projects/{project_id}/defects")
async def create_defect(project_id: int, body: DefectBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _require_role(db, project_id, user)
    if not (body.title or "").strip():
        raise HTTPException(status_code=400, detail="缺陷标题不能为空")
    d = DefectItem(
        project_id=project_id,
        display_id=await _next_display_id(db, project_id),
        title=body.title.strip(),
        description=body.description or "",
        severity=body.severity or "normal",
        status=body.status or "open",
        reporter_id=user.id,
        handlers=body.handlers or [],
        linked_case_ids=body.linked_case_ids or [],
        created_by=user.id,
    )
    db.add(d)
    await db.commit()
    await db.refresh(d)
    users = await _load_users(db, [d.reporter_id] + [h.get("id") if isinstance(h, dict) else h for h in (d.handlers or [])])
    return _defect_dto(d, users)


@router.patch("/defects/{defect_id}")
async def update_defect(defect_id: int, body: DefectBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    d = (await db.execute(select(DefectItem).where(DefectItem.id == defect_id))).scalar_one_or_none()
    if not d:
        raise HTTPException(status_code=404, detail="缺陷不存在")
    await _require_role(db, d.project_id, user)
    for k in ("title", "description", "severity", "status", "handlers", "linked_case_ids"):
        v = getattr(body, k)
        if v is not None:
            setattr(d, k, v)
    d.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(d)
    users = await _load_users(db, [d.reporter_id] + [h.get("id") if isinstance(h, dict) else h for h in (d.handlers or [])])
    return _defect_dto(d, users)


@router.delete("/defects/{defect_id}")
async def delete_defect(defect_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    d = (await db.execute(select(DefectItem).where(DefectItem.id == defect_id))).scalar_one_or_none()
    if not d:
        raise HTTPException(status_code=404, detail="缺陷不存在")
    role = await _my_role(db, d.project_id, user)
    if role not in ("owner", "admin") and d.created_by != user.id:
        raise HTTPException(status_code=403, detail="仅负责人/管理员或创建人可删除")
    await db.execute(DefectComment.__table__.delete().where(DefectComment.defect_id == defect_id))
    await db.delete(d)
    await db.commit()
    return {"ok": True}


class CasesBody(BaseModel):
    case_ids: List[Any] = []


@router.put("/defects/{defect_id}/cases")
async def update_defect_cases(defect_id: int, body: CasesBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    d = (await db.execute(select(DefectItem).where(DefectItem.id == defect_id))).scalar_one_or_none()
    if not d:
        raise HTTPException(status_code=404, detail="缺陷不存在")
    await _require_role(db, d.project_id, user)
    d.linked_case_ids = body.case_ids
    d.updated_at = datetime.utcnow()
    await db.commit()
    return {"ok": True, "case_ids": d.linked_case_ids}


# ============ 评论 / 活动 ============

class CommentBody(BaseModel):
    body: str


@router.get("/defects/{defect_id}/comments")
async def get_comments(defect_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(DefectComment).where(DefectComment.defect_id == defect_id).order_by(DefectComment.created_at))).scalars().all()
    users = await _load_users(db, [c.user_id for c in rows])
    return [{"id": c.id, "body": c.body, "user": _user_label(users.get(c.user_id)),
             "created_at": c.created_at.isoformat() if c.created_at else None} for c in rows]


@router.post("/defects/{defect_id}/comments")
async def add_comment(defect_id: int, body: CommentBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    d = (await db.execute(select(DefectItem).where(DefectItem.id == defect_id))).scalar_one_or_none()
    if not d:
        raise HTTPException(status_code=404, detail="缺陷不存在")
    await _require_role(db, d.project_id, user)
    if not (body.body or "").strip():
        raise HTTPException(status_code=400, detail="评论内容不能为空")
    c = DefectComment(defect_id=defect_id, user_id=user.id, body=body.body.strip())
    db.add(c)
    d.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(c)
    return {"id": c.id, "body": c.body, "user": _user_label(user), "created_at": c.created_at.isoformat()}
