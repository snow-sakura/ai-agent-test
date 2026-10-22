"""遥测：系统日志(system_logs) + Token 用量(token_usage)。"""

import time
import uuid
from datetime import datetime
from typing import Optional

from app.core.database import SyncDB, db_commit, db_execute, db_insert

_ensured = False


def ensure_schema_sync(conn) -> None:
    """启动时同步建表（startup 直接调用，避免依赖 async）。"""
    cur = conn.cursor()
    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS system_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time TEXT, type TEXT, module TEXT, content TEXT,
        user TEXT, ip TEXT, dur INTEGER, status TEXT, body TEXT
    )"""
    )
    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS token_usage (
        id TEXT PRIMARY KEY,
        time TEXT, module TEXT, model TEXT, content TEXT,
        input INTEGER, output INTEGER, hit INTEGER, dur INTEGER,
        log_id INTEGER
    )"""
    )
    conn.commit()


async def ensure_schema(db: SyncDB) -> None:
    global _ensured
    if _ensured:
        return
    await db_execute(
        db,
        """
    CREATE TABLE IF NOT EXISTS system_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time TEXT, type TEXT, module TEXT, content TEXT,
        user TEXT, ip TEXT, dur INTEGER, status TEXT, body TEXT
    )""",
    )
    await db_execute(
        db,
        """
    CREATE TABLE IF NOT EXISTS token_usage (
        id TEXT PRIMARY KEY,
        time TEXT, module TEXT, model TEXT, content TEXT,
        input INTEGER, output INTEGER, hit INTEGER, dur INTEGER,
        log_id INTEGER
    )""",
    )
    await db_commit(db)
    _ensured = True


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def log(
    db: SyncDB,
    type_: str = "请求",
    module: str = "",
    content: str = "",
    user: str = "",
    ip: str = "",
    dur: int = 0,
    status: str = "成功",
    body: str = "",
) -> int:
    """写一条系统日志，返回自增 id。"""
    try:
        await ensure_schema(db)
        return await db_insert(
            db,
            "system_logs",
            {
                "time": _now(),
                "type": type_,
                "module": module,
                "content": content[:500],
                "user": user,
                "ip": ip,
                "dur": dur,
                "status": status,
                "body": body[:2000] if body else "",
            },
        )
    except Exception:
        return 0


async def meter(
    db: SyncDB,
    module: str,
    model: str,
    content: str,
    input_tokens: int,
    output_tokens: int,
    hit: int = 0,
    dur: int = 0,
    log_id: Optional[int] = None,
) -> str:
    """写一条 token 用量记录，返回 TU-xxxx id。"""
    try:
        await ensure_schema(db)
        tu_id = "TU-" + uuid.uuid4().hex[:8].upper()
        await db_insert(
            db,
            "token_usage",
            {
                "id": tu_id,
                "time": _now(),
                "module": module,
                "model": model,
                "content": (content or "")[:200],
                "input": int(input_tokens or 0),
                "output": int(output_tokens or 0),
                "hit": int(hit or 0),
                "dur": int(dur or 0),
                "log_id": log_id,
            },
        )
        return tu_id
    except Exception:
        return ""


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：中文约 1 字≈1 token，英文约 4 字符≈1 token。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    other = len(text) - cjk
    return max(1, cjk + (other + 3) // 4)


async def log_ai(
    db: SyncDB,
    module: str,
    model: str,
    prompt_content: str,
    input_tokens: int,
    output_tokens: int,
    duration_ms: int,
    user: str = "",
    status: str = "成功",
    body: str = "",
) -> None:
    """AI 调用一站式：先记日志再记用量。"""
    log_id = await log(
        db,
        type_="AI",
        module=module,
        content=prompt_content,
        user=user,
        dur=duration_ms,
        status=status,
        body=body,
    )
    await meter(
        db,
        module=module,
        model=model,
        content=prompt_content,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        dur=duration_ms,
        log_id=log_id or None,
    )


def elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
