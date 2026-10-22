# -*- coding: utf-8 -*-
"""APP自动化路由:用例/套件/执行/定时任务/通知日志"""
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User
from app.app_automation.engine import mock_device
from app.app_automation.engine.test_executor import request_stop, run_suite, submit_execution
from app.app_automation.engine.scheduler import calculate_next_run
from app.app_automation.engine.notifier import send_task_notification
from app.app_automation.models import (
    AppDevice, AppNotificationLog, AppPackage, AppScheduledTask, AppTestCase,
    AppTestExecution, AppTestSuite, AppTestSuiteCase, ExecutionStatus,
)

router = APIRouter(prefix="/app-automation", tags=["app-automation"])


def _case_dict(c: AppTestCase) -> Dict[str, Any]:
    return {"id": c.id, "project_id": c.project_id, "name": c.name, "description": c.description,
            "app_package_id": c.app_package_id, "ui_flow": c.ui_flow or {}, "variables": c.variables or [],
            "timeout": c.timeout, "retry_count": c.retry_count,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None}


# ============ 用例 ============

class CaseBody(BaseModel):
    name: str
    description: str = ""
    project_id: Optional[int] = None
    app_package_id: Optional[int] = None
    ui_flow: Dict[str, Any] = {}
    variables: List[Dict[str, Any]] = []
    timeout: int = 300
    retry_count: int = 0


@router.get("/test-cases")
async def case_list(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AppTestCase).order_by(AppTestCase.updated_at.desc()))).scalars().all()
    return [_case_dict(c) for c in rows]


@router.get("/test-cases/{cid}")
async def case_get(cid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(AppTestCase).where(AppTestCase.id == cid))
    c = r.scalar_one_or_none()
    if not c:
        raise HTTPException(404, "用例不存在")
    return _case_dict(c)


@router.post("/test-cases")
async def case_create(body: CaseBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = AppTestCase(name=body.name, description=body.description, project_id=body.project_id,
                    app_package_id=body.app_package_id, ui_flow=body.ui_flow, variables=body.variables,
                    timeout=body.timeout, retry_count=body.retry_count, created_by_id=user.id)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return _case_dict(c)


@router.put("/test-cases/{cid}")
async def case_update(cid: int, body: CaseBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(AppTestCase).where(AppTestCase.id == cid))
    c = r.scalar_one_or_none()
    if not c:
        raise HTTPException(404, "用例不存在")
    c.name, c.description, c.ui_flow, c.variables = body.name, body.description, body.ui_flow, body.variables
    c.app_package_id, c.project_id = body.app_package_id, body.project_id
    c.timeout, c.retry_count = body.timeout, body.retry_count
    await db.commit()
    return _case_dict(c)


@router.delete("/test-cases/{cid}")
async def case_delete(cid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(AppTestCase).where(AppTestCase.id == cid))
    c = r.scalar_one_or_none()
    if not c:
        raise HTTPException(404, "用例不存在")
    await db.delete(c)
    await db.commit()
    return {"success": True}


class ExecuteBody(BaseModel):
    device_db_id: int


@router.post("/test-cases/{cid}/execute")
async def case_execute(cid: int, body: ExecuteBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(AppTestCase).where(AppTestCase.id == cid))
    case = r.scalar_one_or_none()
    if not case:
        raise HTTPException(404, "用例不存在")
    r2 = await db.execute(select(AppDevice).where(AppDevice.id == body.device_db_id))
    device = r2.scalar_one_or_none()
    if not device:
        raise HTTPException(404, "设备不存在,请先在设备管理中添加")
    ex = AppTestExecution(execution_type="case", test_case_id=case.id, device_db_id=device.id,
                          device_id=device.device_id, user_id=user.id, case_name=case.name,
                          status=ExecutionStatus.PENDING)
    db.add(ex)
    await db.commit()
    await db.refresh(ex)
    task_id = submit_execution(ex.id)
    return {"success": True, "message": "测试已提交执行", "execution": {"id": ex.id, "case_name": case.name,
            "device_id": device.device_id, "status": ex.status, "task_id": task_id}}


# ============ 套件 ============

class SuiteBody(BaseModel):
    name: str
    description: str = ""
    project_id: Optional[int] = None
    test_case_ids: List[int] = []


@router.get("/test-suites")
async def suite_list(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AppTestSuite).order_by(AppTestSuite.updated_at.desc()))).scalars().all()
    out = []
    for s in rows:
        members = (await db.execute(select(AppTestSuiteCase).where(AppTestSuiteCase.test_suite_id == s.id)
                                    .order_by(AppTestSuiteCase.order))).scalars().all()
        out.append({"id": s.id, "name": s.name, "description": s.description,
                    "test_case_ids": [m.test_case_id for m in members],
                    "case_count": len(members),
                    "execution_status": s.execution_status, "execution_result": s.execution_result,
                    "passed_count": s.passed_count, "failed_count": s.failed_count,
                    "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
                    "created_at": s.created_at.isoformat() if s.created_at else None})
    return out


@router.post("/test-suites")
async def suite_create(body: SuiteBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    s = AppTestSuite(name=body.name, description=body.description, project_id=body.project_id, created_by_id=user.id)
    db.add(s)
    await db.commit()
    await db.refresh(s)
    for i, cid in enumerate(body.test_case_ids):
        db.add(AppTestSuiteCase(test_suite_id=s.id, test_case_id=cid, order=i))
    await db.commit()
    return {"id": s.id, "name": s.name}


@router.put("/test-suites/{sid}")
async def suite_update(sid: int, body: SuiteBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(AppTestSuite).where(AppTestSuite.id == sid))
    s = r.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "套件不存在")
    s.name, s.description = body.name, body.description
    old = (await db.execute(select(AppTestSuiteCase).where(AppTestSuiteCase.test_suite_id == sid))).scalars().all()
    for m in old:
        await db.delete(m)
    for i, cid in enumerate(body.test_case_ids):
        db.add(AppTestSuiteCase(test_suite_id=sid, test_case_id=cid, order=i))
    await db.commit()
    return {"id": s.id, "name": s.name}


@router.delete("/test-suites/{sid}")
async def suite_delete(sid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(AppTestSuite).where(AppTestSuite.id == sid))
    s = r.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "套件不存在")
    members = (await db.execute(select(AppTestSuiteCase).where(AppTestSuiteCase.test_suite_id == sid))).scalars().all()
    for m in members:
        await db.delete(m)
    await db.delete(s)
    await db.commit()
    return {"success": True}


class SuiteExecuteBody(BaseModel):
    device_db_id: int


@router.post("/test-suites/{sid}/execute")
async def suite_execute(sid: int, body: SuiteExecuteBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await run_suite(sid, body.device_db_id, user.id)
    return result


# ============ 执行记录 ============

@router.get("/executions")
async def execution_list(status: str = "", execution_type: str = "",
                         user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AppTestExecution).order_by(AppTestExecution.created_at.desc()).limit(200))).scalars().all()
    if status:
        rows = [e for e in rows if e.status == status]
    if execution_type:
        rows = [e for e in rows if e.execution_type == execution_type]
    return [{"id": e.id, "execution_type": e.execution_type, "case_name": e.case_name,
             "test_case_id": e.test_case_id, "test_suite_id": e.test_suite_id,
             "device_id": e.device_id or (e.device_db_id and str(e.device_db_id)) or "",
             "status": e.status, "result": e.result, "progress": e.progress,
             "current_step": e.current_step,
             "total_steps": e.total_steps, "passed_steps": e.passed_steps, "failed_steps": e.failed_steps,
             "error_message": e.error_message, "logs": (e.logs or [])[-50:],
             "duration": e.duration,
             "started_at": e.started_at.isoformat() if e.started_at else None,
             "finished_at": e.finished_at.isoformat() if e.finished_at else None,
             "created_at": e.created_at.isoformat() if e.created_at else None} for e in rows]


@router.get("/executions/{eid}")
async def execution_get(eid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(AppTestExecution).where(AppTestExecution.id == eid))
    e = r.scalar_one_or_none()
    if not e:
        raise HTTPException(404, "执行记录不存在")
    pass_rate = round(e.passed_steps / e.total_steps * 100, 2) if e.total_steps else 0
    return {"id": e.id, "execution_type": e.execution_type, "case_name": e.case_name,
            "status": e.status, "result": e.result, "progress": e.progress, "current_step": e.current_step,
            "total_steps": e.total_steps, "passed_steps": e.passed_steps, "failed_steps": e.failed_steps,
            "pass_rate": pass_rate, "logs": e.logs or [], "error_message": e.error_message,
            "duration": e.duration,
            "started_at": e.started_at.isoformat() if e.started_at else None,
            "finished_at": e.finished_at.isoformat() if e.finished_at else None}


@router.post("/executions/{eid}/stop")
async def execution_stop(eid: int, user: User = Depends(get_current_user)):
    ok = request_stop(eid)
    return {"success": ok, "message": "停止信号已发送" if ok else "执行不在运行中"}


@router.get("/executions/{eid}/report")
async def execution_report(eid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """生成/返回执行报告(JSON 形式的步骤报告)"""
    r = await db.execute(select(AppTestExecution).where(AppTestExecution.id == eid))
    e = r.scalar_one_or_none()
    if not e:
        raise HTTPException(404, "执行记录不存在")
    return {
        "execution_id": e.id, "case_name": e.case_name, "status": e.status, "result": e.result,
        "pass_rate": round(e.passed_steps / e.total_steps * 100, 2) if e.total_steps else 0,
        "total_steps": e.total_steps, "passed_steps": e.passed_steps, "failed_steps": e.failed_steps,
        "duration": e.duration, "logs": e.logs or [], "error_message": e.error_message,
        "generated_at": datetime.utcnow().isoformat(),
    }


# ============ 定时任务 ============

class TaskBody(BaseModel):
    name: str
    description: str = ""
    project_id: Optional[int] = None
    task_type: str = "TEST_CASE"
    trigger_type: str = "CRON"
    cron_expression: str = ""
    interval_seconds: Optional[int] = None
    execute_at: Optional[str] = None
    device_db_id: Optional[int] = None
    app_package_id: Optional[int] = None
    test_suite_id: Optional[int] = None
    test_case_id: Optional[int] = None
    notify_on_success: bool = False
    notify_on_failure: bool = False
    notification_type: str = ""
    notify_emails: List[str] = []


def _task_dict(t: AppScheduledTask) -> Dict[str, Any]:
    return {"id": t.id, "name": t.name, "description": t.description, "task_type": t.task_type,
            "trigger_type": t.trigger_type, "cron_expression": t.cron_expression,
            "interval_seconds": t.interval_seconds,
            "execute_at": t.execute_at.isoformat() if t.execute_at else None,
            "device_db_id": t.device_db_id, "app_package_id": t.app_package_id,
            "test_suite_id": t.test_suite_id, "test_case_id": t.test_case_id,
            "notify_on_success": t.notify_on_success, "notify_on_failure": t.notify_on_failure,
            "notification_type": t.notification_type, "notify_emails": t.notify_emails or [],
            "status": t.status,
            "last_run_time": t.last_run_time.isoformat() if t.last_run_time else None,
            "next_run_time": t.next_run_time.isoformat() if t.next_run_time else None,
            "total_runs": t.total_runs, "successful_runs": t.successful_runs, "failed_runs": t.failed_runs,
            "error_message": t.error_message}


@router.get("/scheduled-tasks")
async def task_list(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AppScheduledTask).order_by(AppScheduledTask.created_at.desc()))).scalars().all()
    return [_task_dict(t) for t in rows]


@router.post("/scheduled-tasks")
async def task_create(body: TaskBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    t = AppScheduledTask(name=body.name, description=body.description, project_id=body.project_id,
                         task_type=body.task_type, trigger_type=body.trigger_type,
                         cron_expression=body.cron_expression, interval_seconds=body.interval_seconds,
                         device_db_id=body.device_db_id, app_package_id=body.app_package_id,
                         test_suite_id=body.test_suite_id, test_case_id=body.test_case_id,
                         notify_on_success=body.notify_on_success, notify_on_failure=body.notify_on_failure,
                         notification_type=body.notification_type, notify_emails=body.notify_emails,
                         created_by_id=user.id)
    if body.execute_at:
        t.execute_at = datetime.fromisoformat(body.execute_at)
    t.next_run_time = calculate_next_run(t)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return _task_dict(t)


@router.put("/scheduled-tasks/{tid}")
async def task_update(tid: int, body: TaskBody, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(AppScheduledTask).where(AppScheduledTask.id == tid))
    t = r.scalar_one_or_none()
    if not t:
        raise HTTPException(404, "任务不存在")
    for k in ("name", "description", "task_type", "trigger_type", "cron_expression",
              "interval_seconds", "device_db_id", "app_package_id", "test_suite_id",
              "test_case_id", "notify_on_success", "notify_on_failure", "notification_type", "notify_emails"):
        setattr(t, k, getattr(body, k))
    if body.execute_at:
        t.execute_at = datetime.fromisoformat(body.execute_at)
    t.next_run_time = calculate_next_run(t)
    await db.commit()
    return _task_dict(t)


@router.post("/scheduled-tasks/{tid}/pause")
async def task_pause(tid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(AppScheduledTask).where(AppScheduledTask.id == tid))
    t = r.scalar_one_or_none()
    if not t:
        raise HTTPException(404, "任务不存在")
    t.status = "PAUSED" if t.status == "ACTIVE" else "ACTIVE"
    await db.commit()
    return _task_dict(t)


@router.post("/scheduled-tasks/{tid}/trigger")
async def task_trigger(tid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """手动立即触发一次"""
    r = await db.execute(select(AppScheduledTask).where(AppScheduledTask.id == tid))
    t = r.scalar_one_or_none()
    if not t:
        raise HTTPException(404, "任务不存在")
    if t.task_type == "TEST_CASE" and t.test_case_id:
        r2 = await db.execute(select(AppTestCase).where(AppTestCase.id == t.test_case_id))
        case = r2.scalar_one_or_none()
        if not case:
            raise HTTPException(400, "关联用例不存在")
        device_id = t.device_db_id or 1
        ex = AppTestExecution(execution_type="case", test_case_id=case.id, device_db_id=device_id,
                              user_id=user.id, case_name=case.name, status=ExecutionStatus.PENDING)
        db.add(ex)
        await db.commit()
        await db.refresh(ex)
        submit_execution(ex.id)
        return {"success": True, "execution_id": ex.id}
    if t.task_type == "TEST_SUITE" and t.test_suite_id:
        result = await run_suite(t.test_suite_id, t.device_db_id or 1, user.id)
        return result
    raise HTTPException(400, "任务未配置执行目标")


@router.delete("/scheduled-tasks/{tid}")
async def task_delete(tid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(AppScheduledTask).where(AppScheduledTask.id == tid))
    t = r.scalar_one_or_none()
    if not t:
        raise HTTPException(404, "任务不存在")
    await db.delete(t)
    await db.commit()
    return {"success": True}


# ============ 通知日志 ============

@router.get("/notification-logs")
async def notification_logs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AppNotificationLog).order_by(AppNotificationLog.created_at.desc()).limit(200))).scalars().all()
    return [{"id": n.id, "task_id": n.task_id, "task_name": n.task_name, "task_type": n.task_type,
             "notification_type": n.notification_type, "sender_name": n.sender_name,
             "sender_email": n.sender_email, "recipient_info": n.recipient_info or [],
             "notification_content": n.notification_content, "status": n.status,
             "error_message": n.error_message, "response_info": n.response_info or {},
             "created_at": n.created_at.isoformat() if n.created_at else None,
             "sent_at": n.sent_at.isoformat() if n.sent_at else None,
             "retry_count": n.retry_count, "is_retried": n.is_retried} for n in rows]
