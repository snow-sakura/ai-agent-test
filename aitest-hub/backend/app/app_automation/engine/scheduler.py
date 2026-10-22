# -*- coding: utf-8 -*-
"""定时任务调度器(asyncio 常驻循环,替代 Celery Beat)

注：database.py 已迁移为纯 sqlite3 模式（async_session 为 None 占位），
这里直接走 sqlite3 + asyncio.to_thread，保持原有 30 秒扫描语义。
"""

import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from app.core.database import DB_PATH

logger = logging.getLogger(__name__)


def _parse_dt(v) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v
    if isinstance(v, str) and v:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(v[: len(fmt) + 4].strip(), fmt)
            except ValueError:
                continue
    return None


def _calc_next(
    trigger_type: Optional[str],
    cron_expression: Optional[str],
    interval_seconds: Optional[int],
    execute_at: Optional[datetime],
) -> Optional[datetime]:
    now = datetime.utcnow()
    try:
        if trigger_type == "CRON" and cron_expression:
            from croniter import croniter

            cron = croniter(cron_expression, now)
            return cron.get_next(datetime)
        if trigger_type == "INTERVAL" and interval_seconds:
            return now + timedelta(seconds=interval_seconds)
        if trigger_type == "ONCE" and execute_at:
            return execute_at if execute_at > now else None
    except Exception as e:
        logger.warning(f"计算下次运行时间失败: {e}")
    return None


class _TaskLike:
    """兼容 calculate_next_run(task) 的轻量任务对象"""

    def __init__(self, row: dict):
        self.trigger_type = row.get("trigger_type")
        self.cron_expression = row.get("cron_expression")
        self.interval_seconds = row.get("interval_seconds")
        self.execute_at = _parse_dt(row.get("execute_at"))


def calculate_next_run(task) -> Optional[datetime]:
    """兼容旧调用方（api_cases）：接受 dict 或带属性的任务对象"""
    if isinstance(task, dict):
        t = _TaskLike(task)
    elif isinstance(task, _TaskLike):
        t = task
    else:
        t = _TaskLike(
            {
                "trigger_type": getattr(task, "trigger_type", None),
                "cron_expression": getattr(task, "cron_expression", None),
                "interval_seconds": getattr(task, "interval_seconds", None),
                "execute_at": getattr(task, "execute_at", None),
            }
        )
    return _calc_next(
        t.trigger_type, t.cron_expression, t.interval_seconds, t.execute_at
    )


class AppScheduler:
    """每 30 秒扫描一次到期任务并触发"""

    def __init__(self, on_trigger=None):
        self.on_trigger = on_trigger  # async fn(task_id) -> None
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("⏰ APP定时任务调度器已启动(每30秒扫描)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def _loop(self):
        while self._running:
            try:
                alive = await self.scan_once()
                if not alive:
                    # 调度表不存在（APP自动化模块未建表），退出循环避免刷屏
                    logger.info(
                        "APP定时调度表 app_scheduled_tasks 不存在，调度循环退出"
                    )
                    break
            except Exception as e:
                logger.error(f"定时任务扫描异常: {e}")
            await asyncio.sleep(30)

    async def scan_once(self) -> bool:
        """返回 False 表示调度表不存在，循环应退出"""
        return await asyncio.to_thread(self._scan_sync)

    def _scan_sync(self) -> bool:
        now = datetime.utcnow()
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='app_scheduled_tasks'"
            )
            if not cur.fetchone():
                return False
            cur.execute(
                "SELECT id, trigger_type, cron_expression, interval_seconds, execute_at "
                "FROM app_scheduled_tasks "
                "WHERE status='ACTIVE' AND next_run_time IS NOT NULL AND next_run_time <= ?",
                (now.strftime("%Y-%m-%d %H:%M:%S"),),
            )
            rows = cur.fetchall()
            loop = asyncio.get_running_loop() if self.on_trigger else None
            for row in rows:
                task_id, trigger_type, cron_expr, interval_seconds, execute_at = row
                nxt = _calc_next(
                    trigger_type, cron_expr, interval_seconds, _parse_dt(execute_at)
                )
                cur.execute(
                    "UPDATE app_scheduled_tasks SET next_run_time=?, total_runs=total_runs+1 WHERE id=?",
                    (nxt.strftime("%Y-%m-%d %H:%M:%S") if nxt else None, task_id),
                )
                conn.commit()
                if self.on_trigger and loop is not None:
                    loop.create_task(self.on_trigger(task_id))
            return True
        finally:
            conn.close()


scheduler = AppScheduler()
