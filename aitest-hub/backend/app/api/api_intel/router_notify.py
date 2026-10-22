"""通知配置与发送日志路由 —— 契约 spec/01 A14。

通道说明：
- desktop_system_notify：经本机 Edge Agent 弹系统通知（>90s 未心跳视为离线）；
- email / extra_emails：本后端不直发真邮件，测试时写 simulated 日志；
- sms：平台暂未接入短信，恒 skipped（capabilities.sms=false）；
- webhook：开启且填了 URL 时真实 httpx POST（5s 超时，失败只记日志不整体报错）。
"""

from datetime import datetime

import httpx
from fastapi import APIRouter, Body, Depends

from app.core.database import (
    SyncDB,
    db_commit,
    db_fetch_all,
    db_fetch_one,
    db_insert,
    db_update,
    get_db,
)
from app.core.deps import get_current_user

from .common import ApiError, audit, jdump, jload, now_str, parse_dt, require_member
from .schemas import NotifyConfigBody

router = APIRouter(tags=["api-intel-notify"])

# 设备离线判定窗口（秒）：last_seen_at 超过该时长未刷新 = 离线
DEVICE_ONLINE_WINDOW = 90
WEBHOOK_TIMEOUT = 5.0


# =============================================================================
# 内部工具
# =============================================================================


def _norm_channels(raw: dict) -> dict:
    """规范化通道配置：补默认值、强制 sms=false、清洗列表与长度。"""
    raw = raw if isinstance(raw, dict) else {}
    emails = [str(x).strip() for x in (raw.get("extra_emails") or []) if str(x).strip()]
    phones = [str(x).strip() for x in (raw.get("extra_phones") or []) if str(x).strip()]
    uids = []
    for x in raw.get("notify_extra_user_ids") or []:
        try:
            uids.append(int(x))
        except (ValueError, TypeError):
            continue
    return {
        # 桌面与邮件默认开启，短信/回调默认关闭
        "desktop_system_notify": bool(raw.get("desktop_system_notify", True)),
        "email": bool(raw.get("email", True)),
        "sms": False,  # 短信通道未接入，强制关闭
        "webhook": bool(raw.get("webhook", False)),
        "webhook_url": str(raw.get("webhook_url") or "").strip()[:500],
        "extra_emails": emails[:20],
        "extra_phones": phones[:20],
        "notify_extra_user_ids": uids[:20],
    }


def _user_label(user: dict) -> str:
    return user.get("full_name") or user.get("username") or ""


async def _load_channels(db: SyncDB, ws_id: int) -> dict:
    """读库中通道配置；未配置过返回默认值（不落库）。"""
    row = await db_fetch_one(
        db, "SELECT channels_json FROM ai_notify_config WHERE ws_id=?", [ws_id]
    )
    if not row:
        return _norm_channels({})
    return _norm_channels(jload(row.get("channels_json"), {}) or {})


def _config_payload(user: dict, channels: dict) -> dict:
    """配置对外统一形状。"""
    return {
        "config": {
            "self_user_id": user["id"],
            "self_label": _user_label(user),
            "channels": channels,
            "capabilities": {"sms": False},
        }
    }


# =============================================================================
# 6/7. 通知配置 读 / 写
# =============================================================================


@router.get("/workspaces/{ws_id}/notify/config")
async def get_notify_config(
    ws_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await require_member(ws_id, user, db)
    channels = await _load_channels(db, ws_id)
    return _config_payload(user, channels)


@router.post("/workspaces/{ws_id}/notify/config")
async def save_notify_config(
    ws_id: int,
    body: NotifyConfigBody = Body(default=NotifyConfigBody()),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """保存通道配置（sms 强制 false；未配置过时插入，配置过则更新）。"""
    await require_member(ws_id, user, db)
    channels = _norm_channels(body.channels or {})
    # 与案例站一致：开启 Webhook 但未填地址时直接拒绝，避免存下不可用配置
    if channels.get("webhook") and not (channels.get("webhook_url") or "").strip():
        raise ApiError(400, "请填写 Webhook URL")
    now = now_str()
    exists = await db_fetch_one(
        db, "SELECT ws_id FROM ai_notify_config WHERE ws_id=?", [ws_id]
    )
    if exists:
        await db_update(
            db,
            "ai_notify_config",
            {"channels_json": jdump(channels), "updated_at": now},
            "ws_id=?",
            [ws_id],
        )
    else:
        await db_insert(
            db,
            "ai_notify_config",
            {"ws_id": ws_id, "channels_json": jdump(channels), "updated_at": now},
        )
    await db_commit(db)
    await audit(db, ws_id, user["id"], "保存通知配置", {"channels": channels})
    return _config_payload(user, channels)


# =============================================================================
# 8. 通知发送日志
# =============================================================================


@router.get("/workspaces/{ws_id}/notify/logs")
async def list_notify_logs(
    ws_id: int,
    limit: int = 10,
    offset: int = 0,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await require_member(ws_id, user, db)
    limit = max(1, min(int(limit or 10), 100))
    offset = max(0, int(offset or 0))
    rows = await db_fetch_all(
        db,
        """
        SELECT event_type, channel, status, created_at
        FROM ai_notify_logs WHERE ws_id=? ORDER BY id DESC LIMIT ? OFFSET ?
        """,
        [ws_id, limit + 1, offset],
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        {
            "event_type": r.get("event_type") or "",
            "channel": r.get("channel") or "",
            "status": r.get("status") or "",
            "created_at": r.get("created_at") or "",
        }
        for r in rows
    ]
    return {"items": items, "next_offset": offset + len(items), "has_more": has_more}


# =============================================================================
# 9. 通知测试（逐通道模拟/真实发送）
# =============================================================================


def _device_online(last_seen_at: str, now: datetime) -> bool:
    """last_seen_at 距今 ≤90s 视为在线。"""
    ts = parse_dt(last_seen_at)
    if not ts:
        return False
    return abs((now - ts).total_seconds()) <= DEVICE_ONLINE_WINDOW


async def _log_notify(
    db: SyncDB, ws_id: int, event_type: str, channel: str, status: str, detail: dict
):
    await db_insert(
        db,
        "ai_notify_logs",
        {
            "ws_id": ws_id,
            "event_type": event_type,
            "channel": channel,
            "status": status,
            "detail_json": jdump(detail),
            "created_at": now_str(),
        },
    )


@router.post("/workspaces/{ws_id}/notify/test")
async def test_notify(
    ws_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """按当前配置逐通道触发一次通知测试，结果写 ai_notify_logs。"""
    await require_member(ws_id, user, db)
    channels = await _load_channels(db, ws_id)
    sent: list = []

    # ---- desktop：依赖在线 Edge Agent ----
    devices = await db_fetch_all(
        db,
        "SELECT id, last_seen_at FROM ai_edge_devices WHERE ws_id=?",
        [ws_id],
    )
    now = datetime.now()
    online = [d for d in devices if _device_online(d.get("last_seen_at") or "", now)]
    if not online:
        desktop = {
            "job_id": None,
            "ok": False,
            "skipped": True,
            "need_agent_upgrade": False,
            "offline": True,
            "code": "AGENT_OFFLINE",
        }
    else:
        await _log_notify(
            db,
            ws_id,
            "run_finished",
            "desktop_system_notify",
            "sent",
            {"mode": "test", "device_id": online[0]["id"], "operator": user["id"]},
        )
        desktop = {"job_id": None, "ok": True, "skipped": False, "offline": False}
        sent.append("desktop_system_notify")

    # ---- email：本机不发真邮件，模拟成功并标 simulated ----
    email_targets = [user.get("email") or ""] + list(channels["extra_emails"])
    email_targets = [e for e in email_targets if e]
    if channels["email"] and email_targets:
        await _log_notify(
            db,
            ws_id,
            "run_finished",
            "email",
            "sent",
            {"mode": "test", "simulated": True, "targets": email_targets[:10]},
        )
        email = {"ok": True, "skipped": False, "simulated": True}
        sent.append("email")
    else:
        email = {
            "ok": False,
            "skipped": True,
            "code": "NO_EMAIL" if channels["email"] else "CHANNEL_DISABLED",
        }

    # ---- sms：恒跳过（未接入短信网关）----
    sms = {"ok": False, "skipped": True, "code": "SMS_UNSUPPORTED"}

    # ---- webhook：真实 POST，失败仅记日志 ----
    if channels["webhook"]:
        if not channels["webhook_url"]:
            raise ApiError(400, "请填写 Webhook URL")
        payload = {
            "event": "notify_test",
            "ws_id": ws_id,
            "operator": _user_label(user),
            "time": now_str(),
        }
        try:
            async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT) as client:
                resp = await client.post(channels["webhook_url"], json=payload)
            ok = 200 <= resp.status_code < 300
            await _log_notify(
                db,
                ws_id,
                "notify_test",
                "webhook",
                "sent" if ok else "failed",
                {"status_code": resp.status_code, "url": channels["webhook_url"]},
            )
            webhook = {"ok": ok, "skipped": False, "status_code": resp.status_code}
            if ok:
                sent.append("webhook")
        except Exception as e:  # noqa: BLE001 网络异常不外抛，仅记失败日志
            await _log_notify(
                db,
                ws_id,
                "notify_test",
                "webhook",
                "failed",
                {"error": str(e)[:200], "url": channels["webhook_url"]},
            )
            webhook = {"ok": False, "skipped": False, "error": str(e)[:200]}
    else:
        webhook = {"ok": False, "skipped": True, "code": "CHANNEL_DISABLED"}

    await db_commit(db)
    await audit(
        db,
        ws_id,
        user["id"],
        "测试通知通道",
        {"sent": sent, "channels": list(channels)},
    )
    return {
        "result": {
            "ok": len(sent) > 0,
            "sent": sent,
            "desktop": desktop,
            "email": email,
            "sms": sms,
            "webhook": webhook,
        }
    }
