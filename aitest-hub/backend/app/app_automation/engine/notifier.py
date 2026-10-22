# -*- coding: utf-8 -*-
"""通知:邮件 + Webhook 机器人(企业微信/飞书通用),并落库通知日志"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select

from app.core.database import async_session
from app.app_automation.models import AppNotificationLog

logger = logging.getLogger(__name__)


def build_task_content(task: Any, success: bool, detail: str = "") -> str:
    status_text = "✅ 成功" if success else "❌ 失败"
    return (
        f"【AI Test Hub · APP自动化】{status_text}\n"
        f"任务: {task.name}\n"
        f"类型: {task.task_type}\n"
        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        + (f"详情: {detail}" if detail else "")
    )


async def _send_email(to_list: List[str], content: str) -> Dict[str, Any]:
    """模拟邮件发送(记录日志;真实 SMTP 可在 config 中扩展)"""
    logger.info(f"[模拟邮件] -> {to_list}: {content[:80]}")
    return {"channel": "email", "recipients": to_list, "simulated": True}


async def _send_webhook(url: str, content: str) -> Dict[str, Any]:
    payload = {"msgtype": "text", "text": {"content": content}}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
            return {"channel": "webhook", "status_code": resp.status_code, "body": resp.text[:200]}
    except Exception as e:
        return {"channel": "webhook", "error": str(e)}


async def send_task_notification(task: Any, success: bool, detail: str = "",
                                 webhook_url: str = "") -> None:
    """发送任务通知并写通知日志"""
    content = build_task_content(task, success, detail)
    status = "success" if success else "failed"
    notify_type = task.notification_type or "email"
    emails = task.notify_emails or []
    results: Dict[str, Any] = {}

    if notify_type in ("email", "both") and emails:
        results["email"] = await _send_email(emails, content)
    if notify_type in ("webhook", "both") and webhook_url:
        results["webhook"] = await _send_webhook(webhook_url, content)
    if not results:  # 无配置也落库,便于演示
        results["email"] = await _send_email(emails or ["demo@testhub.local"], content)

    log = AppNotificationLog(
        task_id=task.id, task_name=task.name, task_type=task.task_type,
        notification_type=notify_type or "email",
        recipient_info=[{"email": e} for e in (emails or ["demo@testhub.local"])],
        webhook_bot_info={"url": webhook_url} if webhook_url else {},
        notification_content=content,
        status="success",
        response_info=results,
        sent_at=datetime.utcnow(),
    )
    async with async_session() as db:
        db.add(log)
        await db.commit()
