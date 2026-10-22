"""AI 问答助手（Assistant）— /api/assistant/*（含 SSE 流式）。

表前缀 asst_：
- asst_sessions(id, title, created_at, updated_at, model)
- asst_messages(id, sid, role, content, created_at)

首次访问自动建表 + 空库 seed 演示会话；AI 全部走 app.services.ai。
列表/查询不鉴权；chat / chat/stream / match-skill 不鉴权（SSE 与演示友好）。
"""

import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.database import (
    SyncDB,
    get_db,
    db_commit,
    db_execute,
    db_fetch_all,
    db_fetch_one,
    db_insert,
    db_update,
)
from app.core.deps import get_current_user
from app.services import ai, telemetry

router = APIRouter(tags=["assistant"])

# ---------------------------------------------------------------------------
# 内置知识来源（演示 RAG：knowledge 域未就绪时兜底）
# ---------------------------------------------------------------------------
_SOURCES = [
    {
        "title": "《退款功能 PRD v2.1》3.2 退款说明",
        "snippet": "退款原因 7 项枚举必填；说明选填、限 200 字；提交后生成待审核退款单，审核通过 1-3 工作日原路退回。",
        "kws": ["退款", "需求", "prd", "用例", "说明", "审核"],
    },
    {
        "title": "知识库 PT-12 · 登录认证测试模式",
        "snippet": "正常登录 / 错误密码 / 账号锁定 / 验证码 / 会话保持全覆盖；连续 5 次失败锁定 15min。",
        "kws": ["登录", "认证", "密码", "验证码", "会话", "锁定"],
    },
    {
        "title": "性能测试规范 · 秒杀压测 QPS 定标",
        "snippet": "阶梯加压 500→6000 QPS，每档稳定 5min；观察错误率 <0.5%、P99 ≤800ms 拐点即为容量上限。",
        "kws": ["压测", "qps", "性能", "秒杀", "并发", "p99", "容量"],
    },
    {
        "title": "OWASP 基线核查清单（支付模块）",
        "snippet": "访问控制 / 注入 / 配置错误 / 敏感数据 逐项核查；重点：水平越权、回调签名、限流。",
        "kws": ["安全", "漏洞", "越权", "注入", "owasp", "基线"],
    },
    {
        "title": "历史缺陷 BUG-2042 · 说明 200 字截断",
        "snippet": "前端 maxlength 按 UTF-16 计数，emoji 占 2 位导致入库截断；修复：Array.from(str).length 计数。",
        "kws": ["缺陷", "截断", "bug", "字符", "emoji"],
    },
    {
        "title": "崩溃日志分析手册 · NPE 归因",
        "snippet": "NPE 优先查生命周期回调（isDestroyed）与空指针；结合崩溃聚类占比排序可疑帧。",
        "kws": ["崩溃", "堆栈", "npe", "异常", "日志", "归因"],
    },
]


class ChatReq(BaseModel):
    sessionId: Optional[str] = None
    content: str
    model: Optional[str] = None
    skill: Optional[str] = None


class MatchReq(BaseModel):
    content: str


class SessionCreate(BaseModel):
    title: str = ""
    model: str = ""


# ---------------------------------------------------------------------------
# schema / seed
# ---------------------------------------------------------------------------


async def ensure_schema(db: SyncDB) -> None:
    await db_execute(
        db,
        """
    CREATE TABLE IF NOT EXISTS asst_sessions (
        id TEXT PRIMARY KEY, title TEXT, created_at TEXT, updated_at TEXT, model TEXT
    )""",
    )
    await db_execute(
        db,
        """
    CREATE TABLE IF NOT EXISTS asst_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sid TEXT, role TEXT, content TEXT, created_at TEXT
    )""",
    )
    await db_commit(db)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


async def seed_if_empty(db: SyncDB) -> None:
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM asst_sessions", [])
    if row and row["c"]:
        return
    await db_insert(
        db,
        "asst_sessions",
        {
            "id": "SS-01",
            "title": "秒杀压测 QPS 方案",
            "created_at": "2026-09-22 09:12",
            "updated_at": "2026-09-22 09:18",
            "model": "DeepSeek-V3",
        },
    )
    await db_insert(
        db,
        "asst_sessions",
        {
            "id": "SS-02",
            "title": "崩溃堆栈 NPE 分析",
            "created_at": "2026-09-21 17:40",
            "updated_at": "2026-09-21 17:46",
            "model": "通义千问-Max",
        },
    )
    msgs = [
        ("SS-01", "user", "秒杀场景压测方案怎么定 QPS？", "2026-09-22 09:12"),
        (
            "SS-01",
            "assistant",
            "建议阶梯加压：500→1500→3000→6000，每档稳定 5 分钟；以错误率 <0.5% 且 P99 ≤800ms 的最大档位作为容量上限。首档先摸基线，拐点前加密采样。（演示数据）",
            "2026-09-22 09:13",
        ),
        ("SS-01", "user", "错误率多少算通过？", "2026-09-22 09:17"),
        (
            "SS-01",
            "assistant",
            "常规业务线：错误率 <0.5%、超时率 <0.2%；支付链路建议更严：错误率 <0.1%。需同时盯 DB 连接池与慢查询，避免“指标达标但池打满”。（演示数据）",
            "2026-09-22 09:18",
        ),
        (
            "SS-02",
            "user",
            "这个崩溃堆栈怎么分析？NPE 在 OrderPresenter.onLoad",
            "2026-09-21 17:40",
        ),
        (
            "SS-02",
            "assistant",
            "先确认 Activity/Fragment 销毁后回调是否仍触发：onLoad 异步回来时判 isDestroyed()；再查传入 data 为 null 的路径。建议回调统一切主线程 + 空值兜底，并聚类近 7 日同类堆栈看占比。（演示数据）",
            "2026-09-21 17:46",
        ),
    ]
    for sid, role, content, ts in msgs:
        await db_insert(
            db,
            "asst_messages",
            {
                "sid": sid,
                "role": role,
                "content": content,
                "created_at": ts,
            },
        )
    await db_commit(db)


async def _prepare(db: SyncDB) -> None:
    await ensure_schema(db)
    await seed_if_empty(db)


# ---------------------------------------------------------------------------
# 工具：sources / skill 匹配
# ---------------------------------------------------------------------------


def _score_sources(content: str) -> List[dict]:
    c = (content or "").lower()
    scored = []
    for s in _SOURCES:
        sc = 0
        for kw in s["kws"]:
            if kw in c:
                sc += 2
        if s["title"][:6] and s["title"][:6].lower() in c:
            sc += 1
        scored.append((sc, s))
    scored.sort(key=lambda x: -x[0])
    picked = [x for x in scored if x[0] > 0][:3]
    if len(picked) < 2:
        picked = scored[:3]
    out = []
    for i, (sc, s) in enumerate(picked):
        out.append(
            {
                "title": s["title"],
                "snippet": s["snippet"],
                "score": round(min(0.99, 0.55 + sc * 0.12 - i * 0.05), 2),
            }
        )
    return out


async def _match_skill(db: SyncDB, content: str):
    """对技能库简单打分，返回最匹配技能行（或 None）。"""
    from app.api import skill_library

    await skill_library.ensure_schema(db)
    await skill_library.seed_if_empty(db)
    return await skill_library.match_skill(db, content)


async def _load_history(db: SyncDB, sid: str, limit: int = 8) -> List[dict]:
    rows = await db_fetch_all(
        db,
        "SELECT role, content FROM asst_messages WHERE sid=? ORDER BY id DESC LIMIT ?",
        [sid, limit],
    )
    rows.reverse()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


async def _new_session(db: SyncDB, content: str, model: str = "") -> str:
    rows = await db_fetch_all(db, "SELECT id FROM asst_sessions", [])
    best = 0
    for r in rows:
        try:
            best = max(best, int(str(r["id"]).split("-")[-1]))
        except Exception:
            pass
    sid = "SS-%02d" % (best + 1)
    title = (content or "新会话").strip()[:24]
    await db_insert(
        db,
        "asst_sessions",
        {
            "id": sid,
            "title": title,
            "created_at": _now(),
            "updated_at": _now(),
            "model": model or "默认",
        },
    )
    return sid


async def _save_msg(db: SyncDB, sid: str, role: str, content: str) -> None:
    await db_insert(
        db,
        "asst_messages",
        {
            "sid": sid,
            "role": role,
            "content": content,
            "created_at": _now(),
        },
    )
    await db_update(db, "asst_sessions", {"updated_at": _now()}, "id=?", [sid])


def _build_messages(
    history: List[dict], content: str, skill_row: Optional[dict]
) -> List[dict]:
    system = (
        "你是 AITest Hub 智能测试助手，精通用例设计、接口/UI/APP 自动化、"
        "性能与安全测试、缺陷根因分析。回答专业简洁，可引用知识来源，"
        "涉及步骤时用编号列表。内容由 AI 生成，关键结论给出可执行建议。"
    )
    if skill_row and skill_row.get("content"):
        system += (
            "\n\n【已匹配技能："
            + str(skill_row.get("name") or "")
            + "】\n"
            + str(skill_row.get("content") or "")[:1500]
        )
    messages = [{"role": "system", "content": system}]
    for m in history[-8:]:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": content})
    return messages


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------


@router.get("/assistant/sessions")
async def list_sessions(db: SyncDB = Depends(get_db)):
    await _prepare(db)
    rows = await db_fetch_all(
        db, "SELECT * FROM asst_sessions ORDER BY updated_at DESC", []
    )
    out = []
    for r in rows:
        cnt = await db_fetch_one(
            db, "SELECT COUNT(*) AS c FROM asst_messages WHERE sid=?", [r["id"]]
        )
        out.append(
            {
                "id": r["id"],
                "title": r.get("title") or "未命名会话",
                "createdAt": r.get("created_at"),
                "updatedAt": r.get("updated_at"),
                "model": r.get("model") or "默认",
                "messages": (cnt or {}).get("c", 0) or 0,
            }
        )
    return out


@router.post("/assistant/sessions")
async def create_session(body: SessionCreate, db: SyncDB = Depends(get_db)):
    await _prepare(db)
    sid = await _new_session(db, body.title or "新会话", body.model)
    row = await db_fetch_one(db, "SELECT * FROM asst_sessions WHERE id=?", [sid])
    return {
        "id": row["id"],
        "title": row.get("title"),
        "createdAt": row.get("created_at"),
        "updatedAt": row.get("updated_at"),
        "model": row.get("model"),
        "messages": 0,
    }


@router.delete("/assistant/sessions/{sid}")
async def delete_session(
    sid: str,
    db: SyncDB = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    await _prepare(db)
    row = await db_fetch_one(db, "SELECT id FROM asst_sessions WHERE id=?", [sid])
    if not row:
        raise HTTPException(status_code=404, detail="session not found")
    await db_execute(db, "DELETE FROM asst_messages WHERE sid=?", [sid])
    await db_execute(db, "DELETE FROM asst_sessions WHERE id=?", [sid])
    await db_commit(db)
    return {"ok": True, "id": sid}


@router.get("/assistant/sessions/{sid}/messages")
async def list_messages(sid: str, db: SyncDB = Depends(get_db)):
    await _prepare(db)
    sess = await db_fetch_one(db, "SELECT id FROM asst_sessions WHERE id=?", [sid])
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")
    rows = await db_fetch_all(
        db, "SELECT * FROM asst_messages WHERE sid=? ORDER BY id ASC", [sid]
    )
    return [
        {
            "id": r["id"],
            "sid": r["sid"],
            "role": r["role"],
            "content": r["content"],
            "createdAt": r.get("created_at"),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# 技能匹配
# ---------------------------------------------------------------------------


@router.post("/assistant/match-skill")
async def match_skill_endpoint(body: MatchReq, db: SyncDB = Depends(get_db)):
    await _prepare(db)
    skill = await _match_skill(db, body.content)
    if not skill:
        return {"skill": None}
    return {
        "skill": {
            "id": skill.get("id"),
            "name": skill.get("name"),
            "cat": skill.get("cat"),
            "desc": skill.get("descr") or skill.get("desc"),
            "score": skill.get("_score", 0),
        }
    }


# ---------------------------------------------------------------------------
# 非流式问答
# ---------------------------------------------------------------------------


@router.post("/assistant/chat")
async def chat(body: ChatReq, db: SyncDB = Depends(get_db)):
    await _prepare(db)
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content required")

    # 会话
    sid = body.sessionId
    if sid:
        sess = await db_fetch_one(db, "SELECT id FROM asst_sessions WHERE id=?", [sid])
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
    else:
        sid = await _new_session(db, content, body.model or "")

    # 技能匹配
    skill_row = None
    if body.skill:
        skill_row = await db_fetch_one(
            db, "SELECT * FROM skl_skills WHERE id=?", [body.skill]
        )
    if skill_row is None:
        skill_row = await _match_skill(db, content)

    history = await _load_history(db, sid)
    messages = _build_messages(history, content, skill_row)
    reply = await ai.chat(
        db,
        messages,
        module="AI问答",
        model=body.model,
        scope="AI问答",
        stream=False,
    )
    assert isinstance(reply, str)

    await _save_msg(db, sid, "user", content)
    await _save_msg(db, sid, "assistant", reply)

    skill_matched = None
    if skill_row:
        skill_matched = {
            "id": skill_row.get("id"),
            "name": skill_row.get("name"),
            "cat": skill_row.get("cat"),
            "score": skill_row.get("_score", 0),
        }
        try:
            await db_update(
                db,
                "skl_skills",
                {"uses": (skill_row.get("uses") or 0) + 1},
                "id=?",
                [skill_row.get("id")],
            )
        except Exception:
            pass

    return {
        "sessionId": sid,
        "reply": reply,
        "sources": _score_sources(content),
        "skillMatched": skill_matched,
        "usage": {
            "input": telemetry.estimate_tokens(
                json.dumps(messages, ensure_ascii=False)
            ),
            "output": telemetry.estimate_tokens(reply),
        },
    }


# ---------------------------------------------------------------------------
# SSE 流式问答
# ---------------------------------------------------------------------------


@router.post("/assistant/chat/stream")
async def chat_stream(body: ChatReq, db: SyncDB = Depends(get_db)):
    await _prepare(db)
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content required")

    sid = body.sessionId
    if sid:
        sess = await db_fetch_one(db, "SELECT id FROM asst_sessions WHERE id=?", [sid])
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
    else:
        sid = await _new_session(db, content, body.model or "")

    skill_row = None
    if body.skill:
        skill_row = await db_fetch_one(
            db, "SELECT * FROM skl_skills WHERE id=?", [body.skill]
        )
    if skill_row is None:
        skill_row = await _match_skill(db, content)

    history = await _load_history(db, sid)
    messages = _build_messages(history, content, skill_row)
    in_tokens = telemetry.estimate_tokens(json.dumps(messages, ensure_ascii=False))
    await _save_msg(db, sid, "user", content)

    # StreamingResponse 场景下 Depends(get_db) 会在流开始前 teardown，
    # 统一 AI 服务的 telemetry 与会话落库都需要可用连接，自建独立连接。
    from app.core.database import _get_conn as _get_stream_conn

    _stream_conn = _get_stream_conn()
    stream_db = SyncDB(_stream_conn)

    gen = await ai.chat(
        stream_db,
        messages,
        module="AI问答",
        model=body.model,
        scope="AI问答",
        stream=True,
    )

    async def event_stream():
        parts: List[str] = []
        try:
            async for chunk in gen:  # type: ignore[union-attr]
                if not chunk:
                    continue
                parts.append(chunk)
                yield (
                    "data: " + json.dumps({"delta": chunk}, ensure_ascii=False) + "\n\n"
                )
        except Exception as exc:  # noqa: BLE001
            yield (
                "data: "
                + json.dumps({"delta": "\n[流式中断] " + str(exc)}, ensure_ascii=False)
                + "\n\n"
            )
        full = "".join(parts)
        try:
            await _save_msg(stream_db, sid, "assistant", full or "（空回复）")
        except Exception:
            pass
        finally:
            _stream_conn.close()
        usage = {"input": in_tokens, "output": telemetry.estimate_tokens(full)}
        yield (
            "data: "
            + json.dumps(
                {"done": True, "usage": usage, "sessionId": sid}, ensure_ascii=False
            )
            + "\n\n"
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
