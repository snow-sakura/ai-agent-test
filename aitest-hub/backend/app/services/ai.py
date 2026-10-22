"""统一 AI 服务。

- OpenAI-compatible chat/completions（httpx）
- 支持流式 / 非流式
- 角色温度（config_center cfg_kv role_bindings）
- 去AI味(deai) 后缀
- Token 计量 + 系统日志（telemetry）
- 无 API key 时返回确定性演示 mock，保证全站 AI 功能可点可用
"""

import asyncio
import json
import random
import time
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional, Union

import httpx

from app.core.config import DEFAULT_AI_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL
from app.core.database import (
    SyncDB,
    db_commit,
    db_execute,
    db_fetch_one,
    db_insert,
    db_update,
)
from app.services import telemetry

# ---------------------------------------------------------------------------
# 配置读取
# ---------------------------------------------------------------------------

_ROLE_KV_KEY = "role_bindings"
_DEAI_KV_KEY = "deai_policies"

# 429/5xx 可重试；4xx（除 429）视为客户端错误不重试
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 2  # 首次失败后最多再试 2 次
_RETRY_BASE_DELAY = 1.5  # 秒；指数退避 1.5s → 3.0s


def _is_retryable(exc: Exception) -> bool:
    """判断异常是否值得重试（限流 / 服务端临时错误）。"""
    if isinstance(exc, httpx.HTTPStatusError):
        resp = getattr(exc, "response", None)
        code = resp.status_code if resp is not None else 0
        return code in _RETRYABLE_STATUS
    # 连接超时/断开等网络层错误也可重试
    return isinstance(
        exc,
        (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout),
    )


async def _retry_delay(attempt: int) -> None:
    """指数退避等待。"""
    await asyncio.sleep(_RETRY_BASE_DELAY * (2**attempt))


def _retry_log(module: str, attempt: int, exc: Exception) -> None:
    """重试时打一行日志便于排查 AMD 云限流。"""
    code = ""
    if isinstance(exc, httpx.HTTPStatusError):
        resp = getattr(exc, "response", None)
        if resp is not None:
            code = f" HTTP {resp.status_code}"
    print(
        f"[{module}] AI 调用失败，{_RETRY_BASE_DELAY * (2**attempt):.1f}s 后重试（第 {attempt + 1}/{_MAX_RETRIES} 次）{code}: {type(exc).__name__}",
        flush=True,
    )


async def ensure_config_kv(db: SyncDB) -> None:
    await db_execute(
        db,
        """
    CREATE TABLE IF NOT EXISTS cfg_kv (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT
    )""",
    )
    await db_commit(db)


async def _get_kv(db: SyncDB, key: str) -> Any:
    await ensure_config_kv(db)
    row = await db_fetch_one(db, "SELECT value FROM cfg_kv WHERE key=?", [key])
    if not row or not row.get("value"):
        return None
    try:
        return json.loads(row["value"])
    except Exception:
        return None


async def _models_from_cfg_kv(db: SyncDB) -> List[Dict[str, Any]]:
    """读取配置中心（cfg_kv.ai_models）保存的模型列表。

    配置中心 UI 的「AI 模型」Tab 落库在 cfg_kv，而本服务历史上只读 ai_configs 表，
    导致用户在配置中心填了 Key 全站 AI 仍走 mock。这里做读侧打通。
    """
    raw = await _get_kv(db, "ai_models")
    if not isinstance(raw, list):
        return []
    return [m for m in raw if isinstance(m, dict)]


async def _sync_cfg_models_to_ai_configs(db: SyncDB) -> None:
    """把配置中心全部启用模型写入 ai_configs 表（写侧打通，按 name 幂等 upsert）。

    早期只同步默认模型一条，导致非默认模型的 tier/Key 无法影响调度与生成；
    现全量同步，保证「配置中心改档位/填 Key → 序列调度与用例生成立即生效」。
    """
    models = await _models_from_cfg_kv(db)
    default_model = next(
        (m for m in models if m.get("default") and m.get("enabled", True)), None
    ) or next((m for m in models if m.get("enabled", True)), None)
    targets = [
        m
        for m in models
        if isinstance(m, dict)
        and m.get("enabled", True)
        and str(m.get("name") or "").strip()
        and str(m.get("model") or "").strip()
    ]
    if not targets:
        return
    await db_execute(
        db,
        "CREATE TABLE IF NOT EXISTS ai_configs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, supplier TEXT, "
        "model_name TEXT, api_key TEXT, base_url TEXT, is_default INTEGER DEFAULT 1)",
    )
    try:
        await db_execute(
            db, "ALTER TABLE ai_configs ADD COLUMN tier TEXT DEFAULT 'free'"
        )
    except Exception:  # noqa: BLE001 - 列已存在
        pass
    for m in targets:
        tier_v = str(m.get("tier") or "free").lower()
        if tier_v not in ("free", "paid"):
            tier_v = "free"
        payload = {
            "name": str(m.get("name") or "").strip(),
            "supplier": str(m.get("supplier") or ""),
            "model_name": str(m.get("model") or "").strip(),
            "api_key": str(m.get("key") or "").strip(),
            "base_url": str(m.get("base") or "").strip() or "https://api.openai.com/v1",
            "is_default": 1 if (default_model is not None and m is default_model) else 0,
            "tier": tier_v,
        }
        row = await db_fetch_one(
            db, "SELECT id FROM ai_configs WHERE name=?", [payload["name"]]
        )
        if row:
            await db_update(db, "ai_configs", payload, "id=?", [row["id"]])
        else:
            await db_insert(db, "ai_configs", payload)
    await db_commit(db)


async def get_ai_config(db: SyncDB, model: Optional[str] = None) -> Dict[str, str]:
    """从 ai_configs 取默认（或指定名）配置；缺失字段回落到环境变量。

    当 ai_configs 无可用 Key 时，回退读取配置中心 cfg_kv.ai_models，
    保证「配置中心填 Key → 全站 AI 真调」链路打通。
    """
    cfg = {
        "api_key": OPENAI_API_KEY or "",
        "base_url": OPENAI_BASE_URL or "https://api.openai.com/v1",
        "model": model or DEFAULT_AI_MODEL,
        "name": "默认",
    }
    try:
        if model:
            row = await db_fetch_one(
                db,
                "SELECT * FROM ai_configs WHERE name=? OR model_name=? LIMIT 1",
                [model, model],
            )
        else:
            row = await db_fetch_one(
                db, "SELECT * FROM ai_configs WHERE is_default=1 LIMIT 1"
            )
            if not row:
                row = await db_fetch_one(
                    db, "SELECT * FROM ai_configs ORDER BY id LIMIT 1"
                )
        if row:
            if row.get("api_key"):
                cfg["api_key"] = row["api_key"]
            if row.get("base_url"):
                cfg["base_url"] = row["base_url"]
            if row.get("model_name"):
                cfg["model"] = row["model_name"]
            if row.get("name"):
                cfg["name"] = row["name"]
    except Exception:
        pass

    # ai_configs 没有 Key（或指定模型未命中）→ 回落配置中心
    if not cfg.get("api_key"):
        try:
            models = await _models_from_cfg_kv(db)
            picked = None
            if model:
                picked = next(
                    (
                        m
                        for m in models
                        if str(m.get("name")) == model or str(m.get("model")) == model
                    ),
                    None,
                )
            if picked is None:
                picked = next(
                    (m for m in models if m.get("default") and m.get("enabled", True)),
                    None,
                ) or next((m for m in models if m.get("enabled", True)), None)
            if picked and picked.get("key"):
                cfg["api_key"] = str(picked["key"]).strip()
                if picked.get("base"):
                    cfg["base_url"] = str(picked["base"]).strip()
                if picked.get("model"):
                    cfg["model"] = str(picked["model"]).strip()
                if picked.get("name"):
                    cfg["name"] = str(picked["name"]).strip()
                if not model:
                    # 同步落库，后续请求直读 ai_configs
                    try:
                        await _sync_cfg_models_to_ai_configs(db)
                    except Exception:  # noqa: BLE001 - 同步失败不影响本次调用
                        pass
        except Exception:
            pass
    return cfg


async def get_role_temperature(db: SyncDB, role: Optional[str]) -> Optional[float]:
    if not role:
        return None
    bindings = await _get_kv(db, _ROLE_KV_KEY)
    if not bindings:
        return None
    if isinstance(bindings, dict):
        v = bindings.get(role)
        if isinstance(v, dict):
            v = v.get("temperature")
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None
    if isinstance(bindings, list):
        for item in bindings:
            if isinstance(item, dict) and item.get("role") == role:
                try:
                    return float(item.get("temperature"))
                except (TypeError, ValueError):
                    return None
    return None


async def get_deai_suffix(db: SyncDB, scope: Optional[str]) -> str:
    """命中 scope 的已启用去AI味策略则返回追加后缀，否则空串。"""
    if not scope:
        return ""
    policies = await _get_kv(db, _DEAI_KV_KEY)
    if not policies:
        return ""
    items = policies if isinstance(policies, list) else [policies]
    for p in items:
        if not isinstance(p, dict):
            continue
        if p.get("status") not in (None, "启用", "enabled", "on", True, 1):
            continue
        p_scope = str(p.get("scope") or "全部")
        if p_scope in ("全部", "*", "all") or scope in p_scope or p_scope in scope:
            suffix = str(p.get("suffix") or p.get("content") or "").strip()
            if suffix:
                return "\n" + suffix
    return ""


# ---------------------------------------------------------------------------
# Mock（无 key 兜底）
# ---------------------------------------------------------------------------

_MOCK_TEMPLATES = {
    "requirement": [
        "已解析需求文档，识别出 {n} 条功能点、2 条非功能约束。",
        "派生建议：P0 主流程用例 {n} 条，边界与异常各 2 条。",
    ],
    "case": [
        "已根据输入生成 {n} 条测试用例，覆盖主流程、边界与异常路径。",
        "用例评审意见：补充前置条件与预期结果，优先级建议含 1 条 P0。",
    ],
    "assert": [
        "建议断言：status_code == 200；json.code == 0；响应时间 < 800ms。",
        "参数化断言：data.total 为非负整数；data.list 为数组。",
    ],
    "perf": [
        "性能结论：峰值 QPS 486，P99 287ms，错误率 0.12%，整体达标。",
        "瓶颈推测：订单查询接口 DB 连接池接近饱和，建议扩容并加缓存。",
    ],
    "security": [
        "发现中危风险 2 项：水平越权（订单详情）、信息泄露（错误堆栈）。",
        "安全建议：补充对象级鉴权；生产环境关闭调试输出。",
    ],
    "rootcause": [
        "根因假设：支付回调重试未做幂等，导致重复入账。",
        "证据链：错误日志时间戳与重复流水一致；建议加唯一键去重。",
    ],
    "report": [
        "测试报告摘要：执行 {n} 条，通过率 94.3%，阻塞 1，建议回归支付链路。",
        "风险结论：大促峰值下库存扣减存在竞态，需压测复核。",
    ],
    "generic": [
        "已处理你的请求：结合知识库与当前上下文，给出可执行建议。",
        "分析完成：共识别 3 个关键点，优先修复高优先级项。",
        "生成完毕：内容已去AI味处理，可直接用于测试文档。",
    ],
}


def _mock_reply(
    module: str, prompt: str, n: int = 8, error: Optional[str] = None
) -> str:
    key = module if module in _MOCK_TEMPLATES else "generic"
    tpl = random.choice(_MOCK_TEMPLATES[key])
    body = tpl.format(n=max(3, min(n, 20)))
    if error:
        # 区分「没配 Key」与「配了 Key 但调用失败」，避免误导排障
        return f"{body}（演示模式：模型调用失败 → {error[:120]}）"
    return f"{body}（演示模式：未配置 AI API Key，返回本地模拟结果）"


# ---------------------------------------------------------------------------
# 非流式
# ---------------------------------------------------------------------------


async def chat(
    db: SyncDB,
    messages: List[Dict[str, str]],
    *,
    module: str = "通用",
    role: Optional[str] = None,
    scope: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    stream: bool = False,
    user: str = "",
    max_tokens: int = 2048,
) -> Union[str, AsyncIterator[str]]:
    """统一对话入口。

    stream=False 返回 str；stream=True 返回异步生成器（yield 文本块）。
    最终写 telemetry（日志 + token 用量）。
    """
    cfg = await get_ai_config(db, model)
    temp = temperature
    if temp is None:
        temp = await get_role_temperature(db, role)
    if temp is None:
        temp = 0.7
    suffix = await get_deai_suffix(db, scope)
    final_messages = [dict(m) for m in messages]
    if suffix and final_messages:
        last = final_messages[-1]
        last["content"] = str(last.get("content") or "") + suffix

    prompt_preview = ""
    for m in reversed(final_messages):
        if m.get("role") == "user":
            prompt_preview = str(m.get("content") or "")[:200]
            break
    if not prompt_preview and final_messages:
        prompt_preview = str(final_messages[-1].get("content") or "")[:200]

    in_tokens = telemetry.estimate_tokens(
        json.dumps(final_messages, ensure_ascii=False)
    )
    started = time.monotonic()

    if stream:
        return _stream_chat(
            db,
            cfg,
            final_messages,
            temp=temp,
            module=module,
            prompt_preview=prompt_preview,
            in_tokens=in_tokens,
            started=started,
            user=user,
            max_tokens=max_tokens,
        )

    try:
        if not cfg.get("api_key"):
            raise RuntimeError("no_api_key")
        # 带重试的非流式请求（429/5xx/网络错误，指数退避）
        data = None
        last_exc: Optional[Exception] = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=180.0) as client:
                    resp = await client.post(
                        cfg["base_url"].rstrip("/") + "/chat/completions",
                        headers={
                            "Authorization": f"Bearer {cfg['api_key']}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": cfg["model"],
                            "messages": final_messages,
                            "temperature": temp,
                            "max_tokens": max_tokens,
                            "stream": False,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                break
            except Exception as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES and _is_retryable(exc):
                    _retry_log(module, attempt, exc)
                    await _retry_delay(attempt)
                    continue
                raise
        if data is None:
            raise last_exc or RuntimeError("empty_response")
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
        usage = data.get("usage") or {}
        out_tokens = int(
            usage.get("completion_tokens") or telemetry.estimate_tokens(text)
        )
        total_in = int(usage.get("prompt_tokens") or in_tokens)
        await telemetry.log_ai(
            db,
            module=module,
            model=cfg["model"],
            prompt_content=prompt_preview,
            input_tokens=total_in,
            output_tokens=out_tokens,
            duration_ms=telemetry.elapsed_ms(started),
            user=user,
            status="成功",
            body=text[:500],
        )
        return text
    except Exception as exc:
        text = _mock_reply(module, prompt_preview, error=str(exc))
        await telemetry.log_ai(
            db,
            module=module,
            model=cfg["model"] + "(mock)",
            prompt_content=prompt_preview,
            input_tokens=in_tokens,
            output_tokens=telemetry.estimate_tokens(text),
            duration_ms=telemetry.elapsed_ms(started),
            user=user,
            status="降级模拟",
            body=str(exc)[:300],
        )
        return text


async def _stream_chat(
    db: SyncDB,
    cfg: Dict[str, str],
    messages: List[Dict[str, str]],
    *,
    temp: float,
    module: str,
    prompt_preview: str,
    in_tokens: int,
    started: float,
    user: str,
    max_tokens: int,
) -> AsyncIterator[str]:
    if not cfg.get("api_key"):
        text = _mock_reply(module, prompt_preview)
        for i in range(0, len(text), 12):
            yield text[i : i + 12]
            await asyncio.sleep(0.02)
        await telemetry.log_ai(
            db,
            module=module,
            model=cfg["model"] + "(mock)",
            prompt_content=prompt_preview,
            input_tokens=in_tokens,
            output_tokens=telemetry.estimate_tokens(text),
            duration_ms=telemetry.elapsed_ms(started),
            user=user,
            status="降级模拟",
            body="no_api_key",
        )
        return

    parts: List[str] = []

    async def _do_stream() -> None:
        """发起一次流式请求并 yield 内容块。"""
        async with httpx.AsyncClient(timeout=180.0) as client:
            async with client.stream(
                "POST",
                cfg["base_url"].rstrip("/") + "/chat/completions",
                headers={
                    "Authorization": f"Bearer {cfg['api_key']}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": cfg["model"],
                    "messages": messages,
                    "temperature": temp,
                    "max_tokens": max_tokens,
                    "stream": True,
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        delta = (
                            json.loads(payload)
                            .get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content")
                        )
                    except Exception:
                        delta = None
                    if delta:
                        parts.append(delta)
                        yield delta

    try:
        # 仅在未产出任何内容前可重试（避免重复输出）；一旦已 yield 就不再重试
        last_exc: Optional[Exception] = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                async for chunk in _do_stream():
                    yield chunk
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                if parts:
                    # 已输出部分内容，无法安全重试
                    raise
                if attempt < _MAX_RETRIES and _is_retryable(exc):
                    _retry_log(module, attempt, exc)
                    await _retry_delay(attempt)
                    continue
                raise
        full = "".join(parts)
        await telemetry.log_ai(
            db,
            module=module,
            model=cfg["model"],
            prompt_content=prompt_preview,
            input_tokens=in_tokens,
            output_tokens=telemetry.estimate_tokens(full),
            duration_ms=telemetry.elapsed_ms(started),
            user=user,
            status="成功",
            body=full[:500],
        )
    except Exception as exc:
        text = _mock_reply(module, prompt_preview, error=str(exc))
        for i in range(0, len(text), 12):
            yield text[i : i + 12]
            await asyncio.sleep(0.02)
        await telemetry.log_ai(
            db,
            module=module,
            model=cfg["model"] + "(mock)",
            prompt_content=prompt_preview,
            input_tokens=in_tokens,
            output_tokens=telemetry.estimate_tokens(text),
            duration_ms=telemetry.elapsed_ms(started),
            user=user,
            status="降级模拟",
            body=str(exc)[:300],
        )


async def chat_json(
    db: SyncDB,
    messages: List[Dict[str, str]],
    **kwargs,
) -> Any:
    """要求模型返回 JSON（失败时抛 ValueError）。"""
    kwargs.setdefault("module", "JSON")
    raw = await chat(db, messages, stream=False, **kwargs)
    assert isinstance(raw, str)
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    # 优先按顶层结构提取：先看是数组还是对象
    if text.startswith("["):
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    elif text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    else:
        # 尝试在文本中查找 JSON 对象或数组
        obj_start = text.find("{")
        arr_start = text.find("[")
        if arr_start >= 0 and (obj_start < 0 or arr_start < obj_start):
            # 数组在前，优先提取数组
            end = text.rfind("]")
            if end > arr_start:
                text = text[arr_start : end + 1]
        elif obj_start >= 0:
            end = text.rfind("}")
            if end > obj_start:
                text = text[obj_start : end + 1]
    return json.loads(text)


async def simple(db: SyncDB, prompt: str, system: str = "", **kwargs) -> str:
    """便捷：单轮 user prompt。"""
    messages: List[Dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    result = await chat(db, messages, **kwargs)
    assert isinstance(result, str)
    return result
