"""配置中心（Config Center）— /api/config/*

统一使用 cfg_kv 表（ai.ensure_config_kv 已建表，本模块兜底再 ensure）。
key 约定：
- ai_models      模型列表 JSON
- role_bindings  角色绑定 JSON（ai.get_role_temperature 读取，list[{role,...}]）
- env_config     环境/接口前缀/超时/重试
- dify_config    Dify 助手配置
- notify_channels 通知渠道（钉钉/企微/飞书/邮件 webhook）
"""

import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.database import (
    SyncDB,
    db_commit,
    db_execute,
    db_fetch_one,
    db_insert,
    db_update,
    get_db,
)
from app.core.deps import get_current_user
from app.services.ai import ensure_config_kv, simple

router = APIRouter(tags=["config-center"])


# ---------------------------------------------------------------------------
# 默认种子（对齐 UI/tool-config-center.html）
# ---------------------------------------------------------------------------

_AI_MODELS = [
    {
        "id": 1,
        "name": "DeepSeek-V3",
        "supplier": "DeepSeek",
        "model": "deepseek-chat",
        "base": "https://api.deepseek.com/v1",
        "key": "sk-demo-xxxx",
        "enabled": True,
        "default": True,
        "temperature": 0.7,
        "tier": "free",
    },
    {
        "id": 2,
        "name": "通义千问-Max",
        "supplier": "通义千问",
        "model": "qwen-max",
        "base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "key": "",
        "enabled": True,
        "default": False,
        "temperature": 0.7,
        "tier": "paid",
    },
    {
        "id": 3,
        "name": "硅基流动 · GLM-4",
        "supplier": "硅基流动",
        "model": "THUDM/glm-4-9b-chat",
        "base": "https://api.siliconflow.cn/v1",
        "key": "",
        "enabled": False,
        "default": False,
        "temperature": 0.7,
        "tier": "free",
    },
    {
        "id": 4,
        "name": "GPT-4o",
        "supplier": "OpenAI",
        "model": "gpt-4o",
        "base": "https://api.openai.com/v1",
        "key": "",
        "enabled": False,
        "default": False,
        "temperature": 0.7,
        "tier": "paid",
    },
]

_ROLE_BINDINGS = [
    {
        "role": "AI 需求分析",
        "key": "requirement-analysis",
        "model": "DeepSeek-V3",
        "temperature": 0.3,
        "style": "严谨结构化",
        "desc": "低温度保证解析稳定",
    },
    {
        "role": "用例编写",
        "key": "testcases",
        "model": "DeepSeek-V3",
        "temperature": 0.7,
        "style": "覆盖全面",
        "desc": "适中温度平衡质量与多样性",
    },
    {
        "role": "用例评审",
        "key": "reviews",
        "model": "通义千问-Max",
        "temperature": 0.2,
        "style": "严格比对",
        "desc": "低温度严格比对检查清单",
    },
    {
        "role": "AI 问答助手",
        "key": "assistant",
        "model": "DeepSeek-V3",
        "temperature": 0.7,
        "style": "自然对话",
        "desc": "对话咨询",
    },
    {
        "role": "智能模式",
        "key": "ui-automation",
        "model": "",
        "temperature": 0.5,
        "style": "视觉理解",
        "desc": "文本/视觉双模式",
    },
]

_ENV_CONFIG = {
    "engine": "Playwright",
    "browser": "Chromium",
    "headless": True,
    "apiPrefix": "http://localhost:8000/api",
    "timeout": 30,
    "retry": 2,
    "env": "testing",
}

_DIFY_CONFIG = {
    "baseUrl": "https://api.dify.ai/v1",
    "apiKey": "",
    "appType": "聊天助手（Chatflow）",
    "sessionMode": "按用户隔离（conversation_id）",
    "enabled": False,
}

_NOTIFY_CHANNELS = [
    {
        "name": "企业微信",
        "type": "wecom",
        "webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=demo",
        "enabled": True,
    },
    {"name": "钉钉", "type": "dingtalk", "webhook": "", "enabled": False},
    {"name": "飞书", "type": "feishu", "webhook": "", "enabled": False},
    {
        "name": "邮件",
        "type": "email",
        "webhook": "",
        "enabled": True,
        "smtp": "smtp.example.com",
        "port": "465",
        "from": "testhub@example.com",
        "auth": "demo-auth-code",
        "events": ["定时任务结果", "测试完成"],
    },
]


class Envelope(BaseModel):
    """任意 JSON 配置体。"""

    data: Optional[dict] = None
    items: Optional[list] = None
    # 允许直接平铺字段
    model_config = {"extra": "allow"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def _ensure_schema(db: SyncDB):
    await ensure_config_kv(db)
    # 兜底（ensure_config_kv 内部已 CREATE，这里幂等再执行一次）
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS cfg_kv (
        key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)""",
    )
    await db_commit(db)


async def _get(db: SyncDB, key: str, default):
    row = await db_fetch_one(db, "SELECT value FROM cfg_kv WHERE key=?", [key])
    if not row or not row.get("value"):
        return default
    try:
        return json.loads(row["value"])
    except Exception:
        return default


async def _put(db: SyncDB, key: str, value):
    await _ensure_schema(db)
    now = _now()
    raw = json.dumps(value, ensure_ascii=False)
    exists = await db_fetch_one(db, "SELECT key FROM cfg_kv WHERE key=?", [key])
    if exists:
        await db_update(db, "cfg_kv", {"value": raw, "updated_at": now}, "key=?", [key])
    else:
        await db_insert(db, "cfg_kv", {"key": key, "value": raw, "updated_at": now})
    await db_commit(db)
    return value


async def _seed_if_empty(db: SyncDB):
    await _ensure_schema(db)
    for key, default in (
        ("ai_models", _AI_MODELS),
        ("role_bindings", _ROLE_BINDINGS),
        ("env_config", _ENV_CONFIG),
        ("dify_config", _DIFY_CONFIG),
        ("notify_channels", _NOTIFY_CHANNELS),
    ):
        row = await db_fetch_one(db, "SELECT value FROM cfg_kv WHERE key=?", [key])
        if not row or not row.get("value"):
            await _put(db, key, default)


async def _init(db: SyncDB):
    await _ensure_schema(db)
    await _seed_if_empty(db)


def _payload(body) -> object:
    """兼容 {data:...}/{items:...}/平铺 三种请求体。"""
    if getattr(body, "items", None) is not None:
        return body.items
    if getattr(body, "data", None) is not None:
        return body.data
    raw = body.model_dump(exclude_none=True)
    raw.pop("data", None)
    raw.pop("items", None)
    return raw


# ---------------------------------------------------------------------------
# AI 模型
# ---------------------------------------------------------------------------


@router.get("/config/ai")
async def get_ai(db: SyncDB = Depends(get_db)):
    await _init(db)
    return await _get(db, "ai_models", _AI_MODELS)


@router.put("/config/ai")
async def put_ai(
    body: Envelope, user: dict = Depends(get_current_user), db: SyncDB = Depends(get_db)
):
    await _init(db)
    value = _payload(body)
    if isinstance(value, dict):
        # 单对象也包装成列表
        value = [value]
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail="模型配置须为数组")
    # 规范化 default 唯一
    default_seen = False
    for m in value:
        if isinstance(m, dict) and m.get("default"):
            if default_seen:
                m["default"] = False
            else:
                default_seen = True
    saved = await _put(db, "ai_models", value)
    # 写侧打通：同步默认模型到 ai_configs，使全站 AI 服务立即用上新 Key
    try:
        from app.services.ai import _sync_cfg_models_to_ai_configs

        await _sync_cfg_models_to_ai_configs(db)
    except Exception:  # noqa: BLE001 - 同步失败不阻塞保存
        pass
    return saved


@router.post("/config/ai/test")
async def test_ai(user: dict = Depends(get_current_user), db: SyncDB = Depends(get_db)):
    """连通性测试：调 ai.simple 一句（无 key 自动 mock，返回 ok）。"""
    await _init(db)
    try:
        reply = await simple(db, "请回复：连接测试成功", module="配置中心")
        return {"ok": True, "msg": f"连接成功：{(reply or '')[:80]}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "msg": f"连接失败：{exc}"}


# ---------------------------------------------------------------------------
# 角色绑定
# ---------------------------------------------------------------------------


@router.get("/config/roles")
async def get_roles(db: SyncDB = Depends(get_db)):
    await _init(db)
    return await _get(db, "role_bindings", _ROLE_BINDINGS)


@router.put("/config/roles")
async def put_roles(
    body: Envelope, user: dict = Depends(get_current_user), db: SyncDB = Depends(get_db)
):
    await _init(db)
    value = _payload(body)
    if isinstance(value, dict):
        # 允许单角色更新：按 role 合并
        bindings = await _get(db, "role_bindings", _ROLE_BINDINGS)
        role = value.get("role")
        merged = False
        for i, b in enumerate(bindings):
            if b.get("role") == role or b.get("key") == value.get("key"):
                bindings[i] = {**b, **value}
                merged = True
                break
        if not merged:
            bindings.append(value)
        value = bindings
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail="角色配置须为数组")
    return await _put(db, "role_bindings", value)


@router.get("/config/roles/reviews")
async def get_review_roles(db: SyncDB = Depends(get_db)):
    """评审角色列表（UI defect 页使用）。"""
    await _init(db)
    bindings = await _get(db, "role_bindings", _ROLE_BINDINGS)
    reviews = [
        b
        for b in bindings
        if isinstance(b, dict)
        and ("评审" in str(b.get("role", "")) or b.get("key") == "reviews")
    ]
    if not reviews:
        reviews = [
            {
                "role": "用例评审",
                "key": "reviews",
                "model": "通义千问-Max",
                "temperature": 0.2,
                "style": "严格比对",
            }
        ]
    return reviews


# ---------------------------------------------------------------------------
# 环境配置
# ---------------------------------------------------------------------------


@router.get("/config/env")
async def get_env(db: SyncDB = Depends(get_db)):
    await _init(db)
    return await _get(db, "env_config", _ENV_CONFIG)


@router.put("/config/env")
async def put_env(
    body: Envelope, user: dict = Depends(get_current_user), db: SyncDB = Depends(get_db)
):
    await _init(db)
    value = _payload(body)
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="环境配置须为对象")
    return await _put(db, "env_config", value)


# ---------------------------------------------------------------------------
# Dify
# ---------------------------------------------------------------------------


@router.get("/config/dify")
async def get_dify(db: SyncDB = Depends(get_db)):
    await _init(db)
    return await _get(db, "dify_config", _DIFY_CONFIG)


@router.put("/config/dify")
async def put_dify(
    body: Envelope, user: dict = Depends(get_current_user), db: SyncDB = Depends(get_db)
):
    await _init(db)
    value = _payload(body)
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="Dify 配置须为对象")
    return await _put(db, "dify_config", value)


# ---------------------------------------------------------------------------
# 通知渠道
# ---------------------------------------------------------------------------


@router.get("/config/notify")
async def get_notify(db: SyncDB = Depends(get_db)):
    await _init(db)
    return await _get(db, "notify_channels", _NOTIFY_CHANNELS)


@router.put("/config/notify")
async def put_notify(
    body: Envelope, user: dict = Depends(get_current_user), db: SyncDB = Depends(get_db)
):
    await _init(db)
    value = _payload(body)
    if isinstance(value, dict):
        # 单渠道按 type/name 合并
        channels = await _get(db, "notify_channels", _NOTIFY_CHANNELS)
        merged = False
        for i, c in enumerate(channels):
            if c.get("type") == value.get("type") or c.get("name") == value.get("name"):
                channels[i] = {**c, **value}
                merged = True
                break
        if not merged:
            channels.append(value)
        value = channels
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail="通知渠道须为数组")
    return await _put(db, "notify_channels", value)
