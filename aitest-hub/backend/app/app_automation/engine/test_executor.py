# -*- coding: utf-8 -*-
"""APP 测试执行器:线程池异步执行 UI Flow,实时更新执行记录,支持停止。"""
import asyncio
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select

from app.core.database import async_session
from app.app_automation.engine.ui_flow_runner import UiFlowRunner
from app.app_automation.models import (
    AppDevice,
    AppElement,
    AppNotificationLog,
    AppPackage,
    AppScheduledTask,
    AppTestCase,
    AppTestExecution,
    AppTestSuite,
    AppTestSuiteCase,
    DeviceStatus,
    ExecutionResult,
    ExecutionStatus,
)
from app.app_automation.engine.notifier import send_task_notification

logger = logging.getLogger(__name__)

# 全局停止标志: execution_id -> threading.Event
_stop_flags: Dict[int, threading.Event] = {}

_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="app-exec")


def request_stop(execution_id: int) -> bool:
    flag = _stop_flags.get(execution_id)
    if flag:
        flag.set()
        return True
    return False


def _run_sync(execution_id: int, loop: asyncio.AbstractEventLoop):
    """线程内同步执行,通过 run_coroutine_threadsafe 更新进度"""
    flag = _stop_flags.get(execution_id)

    async def _load_ctx():
        async with async_session() as db:
            result = await db.execute(select(AppTestExecution).where(AppTestExecution.id == execution_id))
            execution = result.scalar_one_or_none()
            if not execution:
                return None
            case = None
            if execution.test_case_id:
                r2 = await db.execute(select(AppTestCase).where(AppTestCase.id == execution.test_case_id))
                case = r2.scalar_one_or_none()
            device = None
            if execution.device_db_id:
                r3 = await db.execute(select(AppDevice).where(AppDevice.id == execution.device_db_id))
                device = r3.scalar_one_or_none()
            els = (await db.execute(select(AppElement).where(AppElement.is_active == True))).scalars().all()  # noqa: E712
            return execution, case, device, {e.name: {"element_type": e.element_type, "config": e.config} for e in els}

    future = asyncio.run_coroutine_threadsafe(_load_ctx(), loop)
    ctx = future.result(timeout=30)
    if not ctx:
        return
    execution, case, device, element_map = ctx
    if not case:
        _finalize(execution_id, loop, ExecutionStatus.ERROR, None, "找不到测试用例")
        return

    device_id = (device.device_id if device else None) or "mock-emulator-5554"
    mock_mode = (device.is_mock if device else True) or True
    ui_flow = case.ui_flow or {}
    steps = ui_flow.get("steps", []) if isinstance(ui_flow, dict) else ui_flow

    runner = UiFlowRunner(device_id=device_id, mock_mode=mock_mode,
                          screenshot_dir=None, username="platform")

    def progress(current, total, step_name, status):
        async def _up():
            async with async_session() as db:
                r = await db.execute(select(AppTestExecution).where(AppTestExecution.id == execution_id))
                ex = r.scalar_one_or_none()
                if ex:
                    ex.status = ExecutionStatus.RUNNING
                    ex.total_steps = total
                    ex.current_step = f"[{current}/{total}] {step_name}"
                    ex.progress = int((current - 1) / total * 100) if total else 0
                    if status == "passed":
                        ex.passed_steps = (ex.passed_steps or 0) + 1
                    elif status == "failed":
                        ex.failed_steps = (ex.failed_steps or 0) + 1
                    ex.logs = (ex.logs or []) + [{
                        "time": datetime.utcnow().isoformat(), "step": step_name,
                        "status": status, "index": current,
                    }]
                    await db.commit()
        asyncio.run_coroutine_threadsafe(_up(), loop).result(timeout=30)

    result = runner.run(steps, variables=case.variables, element_map=element_map,
                        progress_callback=progress)
    stopped = result.get("stopped") or (flag and flag.is_set())
    if stopped:
        _finalize(execution_id, loop, ExecutionStatus.STOPPED, None, "用户手动停止")
    elif result["failed_steps"] > 0:
        _finalize(execution_id, loop, ExecutionStatus.COMPLETED, ExecutionResult.FAILED,
                  f"{result['failed_steps']} 个步骤失败")
    else:
        _finalize(execution_id, loop, ExecutionStatus.COMPLETED, ExecutionResult.PASSED, "")


def _finalize(execution_id: int, loop: asyncio.AbstractEventLoop, status: str,
              result: Optional[str], message: str):
    async def _fin():
        async with async_session() as db:
            r = await db.execute(select(AppTestExecution).where(AppTestExecution.id == execution_id))
            ex = r.scalar_one_or_none()
            if not ex:
                return
            ex.status = status
            ex.result = result
            ex.error_message = message
            ex.progress = 100 if status != ExecutionStatus.ERROR else ex.progress
            ex.finished_at = datetime.utcnow()
            ex.duration = (ex.finished_at - ex.started_at).total_seconds() if ex.started_at else 0
            await db.commit()
            _stop_flags.pop(execution_id, None)
    asyncio.run_coroutine_threadsafe(_fin(), loop).result(timeout=30)


def submit_execution(execution_id: int) -> str:
    """提交线程执行,返回 task_id"""
    task_id = uuid.uuid4().hex
    _stop_flags[execution_id] = threading.Event()
    loop = asyncio.get_event_loop()

    def _wrap():
        try:
            _run_sync(execution_id, loop)
        except Exception as e:  # noqa
            logger.exception(f"执行 {execution_id} 异常")
            try:
                _finalize(execution_id, loop, ExecutionStatus.ERROR, ExecutionResult.FAILED, str(e))
            except Exception:
                pass

    _executor.submit(_wrap)
    return task_id


async def run_suite(suite_id: int, device_db_id: int, user_id: int,
                    package_name: str = "") -> Dict[str, Any]:
    """套件执行:按顺序为每个用例创建执行记录并依次提交"""
    async with async_session() as db:
        r = await db.execute(select(AppTestSuiteCase).where(AppTestSuiteCase.test_suite_id == suite_id)
                             .order_by(AppTestSuiteCase.order))
        members = r.scalars().all()
        suite_result = await db.execute(select(AppTestSuite).where(AppTestSuite.id == suite_id))
        suite = suite_result.scalar_one_or_none()
        if not suite:
            return {"success": False, "message": "套件不存在"}
        created = []
        for m in members:
            r2 = await db.execute(select(AppTestCase).where(AppTestCase.id == m.test_case_id))
            case = r2.scalar_one_or_none()
            if not case:
                continue
            ex = AppTestExecution(
                execution_type="suite", test_case_id=case.id, test_suite_id=suite_id,
                device_db_id=device_db_id, user_id=user_id,
                case_name=case.name, status=ExecutionStatus.PENDING,
            )
            db.add(ex)
            await db.commit()
            await db.refresh(ex)
            created.append(ex.id)
        suite.execution_status = "running"
        suite.last_run_at = datetime.utcnow()
        await db.commit()
    task_ids = []
    for eid in created:
        task_ids.append(submit_execution(eid))
    return {"success": True, "execution_ids": created, "task_ids": task_ids}
