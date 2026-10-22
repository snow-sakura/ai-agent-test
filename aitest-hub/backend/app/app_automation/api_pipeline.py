# -*- coding: utf-8 -*-
"""控件画像流水线路由(新增能力):
dump 采集 → 画像生成 → 缺口检测+视觉补充 → 用例矩阵 → locator → 设备验证 → 固化代码
"""
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User
from app.app_automation.engine import mock_device
from app.app_automation.engine.adb_manager import AdbManager
from app.app_automation.pipeline.dump_session import DEFAULT_TRAVERSAL, DumpSessionRunner
from app.app_automation.pipeline.profile_builder import build_profiles
from app.app_automation.pipeline.gap_detector import detect_gaps
from app.app_automation.pipeline.vision_client import supplement_semantics
from app.app_automation.pipeline.matrix_generator import generate_matrix
from app.app_automation.pipeline.locator_generator import generate_locators
from app.app_automation.pipeline.verifier import verify_locator
from app.app_automation.pipeline.codegen import generate_code
from app.app_automation.models import (
    AppCaseMatrix, AppCodeArtifact, AppControlProfile, AppDevice, AppDumpSession,
    AppGapFinding, AppLocator, AppPageDump,
)

router = APIRouter(prefix="/app-automation/pipeline", tags=["app-automation-pipeline"])


# ============ 采集会话 ============

class DumpSessionBody(BaseModel):
    name: str = ""
    device_db_id: int
    pages: List[str] = []
    package_name: str = "com.testhub.demoapp"


@router.get("/dump-sessions")
async def session_list(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AppDumpSession).order_by(AppDumpSession.created_at.desc()))).scalars().all()
    return [{"id": s.id, "name": s.name, "device_db_id": s.device_db_id, "package_name": s.package_name,
             "status": s.status, "pages": s.pages or [], "collected_pages": s.collected_pages or [],
             "error_message": s.error_message,
             "created_at": s.created_at.isoformat() if s.created_at else None} for s in rows]


@router.post("/dump-sessions")
async def session_create(body: DumpSessionBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(AppDevice).where(AppDevice.id == body.device_db_id))
    device = r.scalar_one_or_none()
    if not device:
        raise HTTPException(404, "设备不存在")
    s = AppDumpSession(name=body.name or f"采集-{datetime.utcnow().strftime('%m%d-%H%M')}",
                       device_db_id=device.id, package_name=body.package_name,
                       pages=body.pages or DEFAULT_TRAVERSAL,
                       status="pending", created_by_id=user.id)
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return {"id": s.id, "name": s.name, "status": s.status}


@router.post("/dump-sessions/{sid}/run")
async def session_run(sid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(AppDumpSession).where(AppDumpSession.id == sid))
    s = r.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "采集会话不存在")
    r2 = await db.execute(select(AppDevice).where(AppDevice.id == s.device_db_id))
    device = r2.scalar_one_or_none()
    device_id = device.device_id if device else "mock-emulator-5554"
    is_mock = device.is_mock if device else True

    s.status = "running"
    await db.commit()
    try:
        runner = DumpSessionRunner(device_id, s.pages or DEFAULT_TRAVERSAL, s.package_name, is_mock)
        results = runner.run()
        # 清空旧 dump 重新写入
        old = (await db.execute(select(AppPageDump).where(AppPageDump.session_id == sid))).scalars().all()
        for d in old:
            await db.delete(d)
        collected = []
        for res in results:
            dump = AppPageDump(session_id=sid, page_name=res["page_name"], xml=res["xml"],
                               screenshot_path=res["screenshot_path"], fingerprint=res["fingerprint"],
                               action_context=res["action_context"])
            db.add(dump)
            await db.flush()
            collected.append({"dump_id": dump.id, "page_name": res["page_name"],
                              "title": res["title"], "fingerprint": res["fingerprint"],
                              "screenshot_path": res["screenshot_path"],
                              "screenshot_url": "/api/app-automation/media?path=" + res["screenshot_path"],
                              "action_context": res["action_context"]})
        s.status = "completed"
        s.collected_pages = collected
        await db.commit()
        return {"success": True, "session_id": sid, "collected": collected}
    except Exception as e:
        s.status = "error"
        s.error_message = str(e)
        await db.commit()
        raise HTTPException(500, f"采集失败: {e}")


@router.get("/dump-sessions/{sid}")
async def session_detail(sid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(AppDumpSession).where(AppDumpSession.id == sid))
    s = r.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "采集会话不存在")
    dumps = (await db.execute(select(AppPageDump).where(AppPageDump.session_id == sid))).scalars().all()
    return {"id": s.id, "name": s.name, "status": s.status, "pages": s.pages or [],
            "package_name": s.package_name,
            "dumps": [{"id": d.id, "page_name": d.page_name, "xml": d.xml,
                       "fingerprint": d.fingerprint or {}, "action_context": d.action_context or {},
                       "screenshot_url": "/api/app-automation/media?path=" + d.screenshot_path,
                       "profile_generated": d.profile_generated,
                       "created_at": d.created_at.isoformat() if d.created_at else None} for d in dumps]}


# ============ 控件画像 ============

@router.post("/profiles/generate/{sid}")
async def profiles_generate(sid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """对会话内所有 dump 离线生成控件画像(纯规则,不耗 Token)"""
    dumps = (await db.execute(select(AppPageDump).where(AppPageDump.session_id == sid))).scalars().all()
    if not dumps:
        raise HTTPException(400, "会话无采集数据,请先执行采集")
    old = (await db.execute(select(AppControlProfile).where(AppControlProfile.session_id == sid))).scalars().all()
    for p in old:
        await db.delete(p)
    total = 0
    for d in dumps:
        profiles = build_profiles(d.xml, d.page_name)
        for p in profiles:
            db.add(AppControlProfile(dump_id=d.id, session_id=sid, page=d.page_name,
                                     control_id=p["control_id"], role=p["role"], xml=p["xml"],
                                     context=p["context"], actions=p["actions"],
                                     locator_candidates=p["locator_candidates"],
                                     risk=p["risk"], verification=p["verification"],
                                     source=p["source"]))
            total += 1
        d.profile_generated = True
    await db.commit()
    return {"success": True, "profiles": total}


@router.get("/profiles")
async def profiles_list(session_id: Optional[int] = None, page: str = "",
                        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(AppControlProfile).order_by(AppControlProfile.page, AppControlProfile.id)
    if session_id:
        stmt = stmt.where(AppControlProfile.session_id == session_id)
    rows = (await db.execute(stmt)).scalars().all()
    if page:
        rows = [p for p in rows if p.page == page]
    return [{"id": p.id, "dump_id": p.dump_id, "session_id": p.session_id, "page": p.page,
             "control_id": p.control_id, "role": p.role, "xml": p.xml or {}, "context": p.context or {},
             "actions": p.actions or [], "locator_candidates": p.locator_candidates or [],
             "risk": p.risk, "verification": p.verification, "source": p.source or [],
             "visual": p.visual or {}} for p in rows]


class ProfileUpdateBody(BaseModel):
    role: Optional[str] = None
    risk: Optional[str] = None
    visual: Optional[Dict[str, Any]] = None


@router.put("/profiles/{pid}")
async def profile_update(pid: int, body: ProfileUpdateBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(AppControlProfile).where(AppControlProfile.id == pid))
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "画像不存在")
    if body.role is not None:
        p.role = body.role
    if body.risk is not None:
        p.risk = body.risk
    if body.visual is not None:
        p.visual = body.visual
        if "vision" not in (p.source or []):
            p.source = (p.source or []) + ["vision"]
    await db.commit()
    return {"id": p.id}


# ============ 视觉缺口 ============

class GapAnalyzeBody(BaseModel):
    session_id: int
    dump_id: Optional[int] = None
    use_vision: bool = True


@router.post("/gaps/analyze")
async def gaps_analyze(body: GapAnalyzeBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """检测视觉缺口,并按需调用视觉模型补充语义"""
    stmt = select(AppPageDump).where(AppPageDump.session_id == body.session_id)
    if body.dump_id:
        stmt = stmt.where(AppPageDump.id == body.dump_id)
    dumps = (await db.execute(stmt)).scalars().all()
    if not dumps:
        raise HTTPException(400, "无采集数据")
    all_gaps = []
    for d in dumps:
        profiles = build_profiles(d.xml, d.page_name)
        gaps = detect_gaps(profiles)
        old = (await db.execute(select(AppGapFinding).where(AppGapFinding.dump_id == d.id))).scalars().all()
        for g in old:
            await db.delete(g)
        vision_results = []
        if gaps and body.use_vision:
            vision_results = await supplement_semantics(db, d.screenshot_path, profiles, gaps)
        vision_by_id = {v.get("control_id"): v for v in vision_results}
        for g in gaps:
            vision = vision_by_id.get(g["control_id"], {})
            gf = AppGapFinding(dump_id=d.id, control_id=g["control_id"], gap_type=g["gap_type"],
                               detail=g["detail"], vision_result=vision,
                               status="filled" if vision else "open")
            db.add(gf)
            # 将视觉语义同步到画像
            if vision:
                pr = (await db.execute(select(AppControlProfile).where(
                    AppControlProfile.session_id == body.session_id,
                    AppControlProfile.control_id == g["control_id"]))).scalars().first()
                if pr:
                    pr.visual = vision
                    pr.source = list(set((pr.source or []) + ["vision"]))
                    if vision.get("visual_role"):
                        pr.role = vision["visual_role"]
            all_gaps.append({"dump_id": d.id, "page": d.page_name, "control_id": g["control_id"],
                             "gap_type": g["gap_type"], "detail": g["detail"],
                             "vision": vision, "status": "filled" if vision else "open"})
    await db.commit()
    return {"success": True, "gaps": all_gaps, "total": len(all_gaps)}


@router.get("/gaps")
async def gaps_list(session_id: Optional[int] = None, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(AppGapFinding).order_by(AppGapFinding.created_at.desc())
    if session_id:
        stmt = stmt.join(AppPageDump, AppPageDump.id == AppGapFinding.dump_id).where(AppPageDump.session_id == session_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [{"id": g.id, "dump_id": g.dump_id, "control_id": g.control_id, "gap_type": g.gap_type,
             "detail": g.detail, "vision_result": g.vision_result or {}, "status": g.status} for g in rows]


# ============ 用例矩阵 ============

class MatrixBody(BaseModel):
    name: str = ""
    requirement: str = ""
    session_id: int


@router.post("/gen-tests")
async def gen_tests(body: MatrixBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    profiles = (await db.execute(select(AppControlProfile).where(AppControlProfile.session_id == body.session_id))).scalars().all()
    if not profiles:
        raise HTTPException(400, "请先生成控件画像")
    profile_dicts = []
    for p in profiles:
        profile_dicts.append({"control_id": p.control_id, "role": p.role, "page": p.page,
                              "actions": p.actions or [], "risk": p.risk, "xml": p.xml or {}})
    cases = await generate_matrix(db, body.requirement, profile_dicts)
    m = AppCaseMatrix(name=body.name or f"矩阵-{datetime.utcnow().strftime('%m%d-%H%M')}",
                      requirement_text=body.requirement, cases=cases, session_id=body.session_id,
                      created_by_id=user.id)
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return {"id": m.id, "name": m.name, "cases": cases, "total": len(cases)}


@router.get("/matrices")
async def matrix_list(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AppCaseMatrix).order_by(AppCaseMatrix.created_at.desc()))).scalars().all()
    return [{"id": m.id, "name": m.name, "requirement_text": m.requirement_text,
             "cases": m.cases or [], "status": m.status, "session_id": m.session_id,
             "created_at": m.created_at.isoformat() if m.created_at else None} for m in rows]


@router.put("/matrices/{mid}/status")
async def matrix_status(mid: int, body: Dict[str, Any], user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(AppCaseMatrix).where(AppCaseMatrix.id == mid))
    m = r.scalar_one_or_none()
    if not m:
        raise HTTPException(404, "矩阵不存在")
    m.status = body.get("status", m.status)
    await db.commit()
    return {"id": m.id, "status": m.status}


# ============ locator 生成与验证 ============

class LocatorGenBody(BaseModel):
    session_id: int
    matrix_id: Optional[int] = None
    control_ids: List[str] = []


@router.post("/locators/generate")
async def locators_generate(body: LocatorGenBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    profiles = (await db.execute(select(AppControlProfile).where(AppControlProfile.session_id == body.session_id))).scalars().all()
    if not profiles:
        raise HTTPException(400, "请先生成控件画像")
    profile_dicts = []
    for p in profiles:
        profile_dicts.append({"_db_id": p.id, "control_id": p.control_id, "page": p.page,
                              "xml": p.xml or {}, "context": p.context or {}, "actions": p.actions or []})
    generated = generate_locators(profile_dicts, body.control_ids or None)
    # 落库
    for g in generated:
        exists = (await db.execute(select(AppLocator).where(
            AppLocator.profile_id == g["profile_id"],
            AppLocator.strategy == g["selected"]["strategy"],
            AppLocator.expression == g["selected"]["expression"]))).scalars().first()
        if not exists:
            db.add(AppLocator(profile_id=g["profile_id"], case_id=body.matrix_id and str(body.matrix_id) or "",
                              strategy=g["selected"]["strategy"], expression=g["selected"]["expression"]))
    await db.commit()
    return {"success": True, "locators": generated, "total": len(generated)}


class VerifyBody(BaseModel):
    device_db_id: int
    control_ids: List[str] = []


@router.post("/locators/verify")
async def locators_verify(body: VerifyBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """设备验证点击与页面指纹(视觉出假设,设备验证假设)"""
    r = await db.execute(select(AppDevice).where(AppDevice.id == body.device_db_id))
    device = r.scalar_one_or_none()
    if not device:
        raise HTTPException(404, "设备不存在")
    stmt = select(AppLocator)
    locs = (await db.execute(stmt)).scalars().all()
    if body.control_ids:
        profile_ids = {(await db.execute(select(AppControlProfile).where(
            AppControlProfile.control_id.in_(body.control_ids)))).scalars().all()}
        pid_set = {p.id for p in profile_ids.pop()} if isinstance(profile_ids, set) else set()
        locs = [l for l in locs if l.profile_id in pid_set or not body.control_ids]
    results = []
    from app.app_automation.pipeline.dump_session import DumpSessionRunner
    device_session = mock_device.get_mock_session(device.device_id)
    for loc in locs:
        # 每次验证前导航到控件所在页面,避免验证时页面漂移
        profile = None
        if loc.profile_id:
            pr = await db.execute(select(AppControlProfile).where(AppControlProfile.id == loc.profile_id))
            profile = pr.scalar_one_or_none()
        device_session.reset()
        if profile and profile.page:
            try:
                DumpSessionRunner(device.device_id, [profile.page])._navigate_to(profile.page)
            except Exception:
                pass
        v = verify_locator(device.device_id, {"strategy": loc.strategy, "expression": loc.expression})
        loc.status = "verified" if (v.get("success") and v.get("fingerprint_changed")) else (
            "failed" if not v.get("success") else "pending")
        loc.page_fingerprint = v.get("after", {})
        loc.verification_detail = v
        loc.verified_at = datetime.utcnow()
        results.append({"locator_id": loc.id, "profile_id": loc.profile_id, "strategy": loc.strategy,
                        "expression": loc.expression, **v})
    await db.commit()
    verified = len([x for x in results if x.get("success") and x.get("fingerprint_changed")])
    return {"success": True, "results": results, "verified": verified, "total": len(results)}


@router.get("/locators")
async def locators_list(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AppLocator).order_by(AppLocator.updated_at.desc()))).scalars().all()
    return [{"id": l.id, "profile_id": l.profile_id, "case_id": l.case_id, "strategy": l.strategy,
             "expression": l.expression, "status": l.status,
             "verification_detail": l.verification_detail or {}} for l in rows]


# ============ 固化代码 ============

class CodegenBody(BaseModel):
    name: str = ""
    matrix_id: int
    template_type: str = "appium"  # appium | u2


@router.post("/codegen")
async def codegen(body: CodegenBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(AppCaseMatrix).where(AppCaseMatrix.id == body.matrix_id))
    m = r.scalar_one_or_none()
    if not m:
        raise HTTPException(404, "用例矩阵不存在")
    locs = (await db.execute(select(AppLocator))).scalars().all()
    profiles = (await db.execute(select(AppControlProfile))).scalars().all()
    pid_to_cid = {p.id: p.control_id for p in profiles}
    locators = []
    for l in locs:
        if l.status == "verified" or True:  # 已验证优先;未验证的同样给出便于审查
            cid = pid_to_cid.get(l.profile_id, "")
            locators.append({"control_id": cid, "selected": {"strategy": l.strategy, "expression": l.expression},
                             "_verified": l.status == "verified"})
    code = generate_code(body.template_type, m.name or "testhub_app_tests", m.cases or [], locators)
    artifact = AppCodeArtifact(name=body.name or f"{m.name}-{body.template_type}",
                               template_type=body.template_type, code=code,
                               case_ids=[c.get("case_id") for c in (m.cases or [])], created_by_id=user.id)
    db.add(artifact)
    await db.commit()
    await db.refresh(artifact)
    # 写文件
    out_dir = os.path.join(mock_device.UPLOAD_BASE, "codegen")
    os.makedirs(out_dir, exist_ok=True)
    fpath = os.path.join(out_dir, f"{artifact.name.replace(' ', '_')}_test_{artifact.id}.py")
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(code)
    artifact.file_path = fpath
    await db.commit()
    return {"id": artifact.id, "name": artifact.name, "template_type": artifact.template_type,
            "code": code, "file_path": fpath}


@router.get("/codegen/artifacts")
async def codegen_list(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AppCodeArtifact).order_by(AppCodeArtifact.created_at.desc()))).scalars().all()
    return [{"id": a.id, "name": a.name, "template_type": a.template_type, "file_path": a.file_path,
             "case_ids": a.case_ids or [],
             "created_at": a.created_at.isoformat() if a.created_at else None} for a in rows]


@router.get("/codegen/{aid}/download", response_class=PlainTextResponse)
async def codegen_download(aid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(AppCodeArtifact).where(AppCodeArtifact.id == aid))
    a = r.scalar_one_or_none()
    if not a:
        raise HTTPException(404, "产物不存在")
    return a.code
