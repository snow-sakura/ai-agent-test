"""生成序列调度器（Generation Sequence Scheduler）。

调度规则：
- 免费模型（tier=free）→ 单任务序列：并发固定 1，任务按提交顺序串行执行，
  避免免费额度被并发打爆（限流 → 失败 → 结果缺失）。
- 付费模型（tier=paid）→ 并行序列：同时开启 N 个并行任务（默认 3，可配），
  用 asyncio.Semaphore 控制。

实现要点：
- SQLite 表 gq_sequences 持久化序列与任务项（items JSON，保序）；
- Worker 为进程内 asyncio 任务，sqlite 单连接多线程共享 cursor 会串号，
  因此「状态回写」统一走调度器自有连接 + persist_lock，
  「模型调用」内部按需自建短连接（见 _execute_item）；
- 服务重启后遗留的执行中序列自动标记「已中断」，支持重试失败项。
"""

import asyncio
import json
import random
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.database import (
    SyncDB,
    db_commit,
    db_execute,
    db_fetch_all,
    db_fetch_one,
    db_update,
)
from app.services import ai as ai_service
from app.services.ai_parse import parse_generated_cases
from app.services.casegen_core import build_messages, demo_generated_cases

SCHED_KV_KEY = "gen_scheduler"
DEFAULT_SCHED = {"paid_concurrency": 3, "free_concurrency": 1}

# 运行中的序列任务：sid -> asyncio.Task（进程内）
_RUNNING: Dict[str, asyncio.Task] = {}
_READY = False


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _new_sid() -> str:
    return "SQ-%s-%03d" % (
        datetime.now().strftime("%Y%m%d-%H%M%S"),
        random.randint(0, 999),
    )


# 计入 fail_cnt / 可被「重试失败任务」重置的状态口径（前端按钮依赖 fail_cnt>0）
_FAIL_STATUSES = ("失败", "已取消", "已中断")


async def ensure_ready(db: SyncDB) -> None:
    """建表 + ai_configs 补 tier 列 + 一次性修复重启遗留的执行中序列。

    仅进程首次执行：若每次请求都跑收尾 UPDATE，会把在跑的序列误标为已中断。
    """
    global _READY
    if _READY:
        return
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS gq_sequences (
            id TEXT PRIMARY KEY,
            title TEXT,
            module TEXT DEFAULT 'case',
            model_id INTEGER,
            model_name TEXT,
            tier TEXT DEFAULT 'free',
            mode TEXT DEFAULT 'serial',
            concurrency INTEGER DEFAULT 1,
            status TEXT DEFAULT '排队中',
            total INTEGER DEFAULT 0,
            done_cnt INTEGER DEFAULT 0,
            fail_cnt INTEGER DEFAULT 0,
            items TEXT DEFAULT '[]',
            created_by TEXT DEFAULT '',
            created_at TEXT,
            started_at TEXT,
            finished_at TEXT
        )""",
    )
    try:
        await db_execute(
            db, "ALTER TABLE ai_configs ADD COLUMN tier TEXT DEFAULT 'free'"
        )
    except Exception:  # noqa: BLE001 - 列已存在
        pass
    await db_execute(
        db,
        "UPDATE gq_sequences SET status='已中断', finished_at=? "
        "WHERE status IN ('排队中','执行中')",
        [_now()],
    )
    # 序列置为「已中断」后，遗留的等待中/执行中任务项也要归一：
    # 否则前端时间线一直显示 🔄 执行中，且 fail_cnt=0 会让「重试失败任务」按钮隐藏，
    # retry_failed 也认不出这些任务项，导致「已中断」序列实际无法重试。
    stale = await db_fetch_all(
        db,
        "SELECT id, items FROM gq_sequences WHERE status='已中断'",
        [],
    )
    for row in stale or []:
        try:
            items = json.loads(row["items"] or "[]")
        except Exception:  # noqa: BLE001
            continue
        changed = False
        for it in items:
            if it.get("status") in ("等待中", "执行中"):
                it["status"] = "已中断"
                changed = True
        if not changed:
            continue
        done = sum(1 for i in items if i.get("status") == "成功")
        fail = sum(1 for i in items if i.get("status") in _FAIL_STATUSES)
        await db_update(
            db,
            "gq_sequences",
            {
                "items": json.dumps(items, ensure_ascii=False),
                "done_cnt": done,
                "fail_cnt": fail,
            },
            "id=?",
            [row["id"]],
        )
    await db_commit(db)
    _READY = True


async def get_scheduler_settings(db: SyncDB) -> Dict[str, int]:
    raw = await ai_service._get_kv(db, SCHED_KV_KEY)
    out = dict(DEFAULT_SCHED)
    if isinstance(raw, dict):
        for k in DEFAULT_SCHED:
            try:
                v = int(raw.get(k))
                if 1 <= v <= 8:
                    out[k] = v
            except (TypeError, ValueError):
                pass
    return out


async def _put_kv(db: SyncDB, key: str, value: Any) -> None:
    """kv 写入（与 config_center 同构，避免跨 api 层导入）。"""
    await ai_service.ensure_config_kv(db)
    raw = json.dumps(value, ensure_ascii=False)
    exists = await db_fetch_one(db, "SELECT key FROM cfg_kv WHERE key=?", [key])
    if exists:
        await db_update(
            db, "cfg_kv", {"value": raw, "updated_at": _now()}, "key=?", [key]
        )
    else:
        await db_execute(
            db, "INSERT INTO cfg_kv (key, value, updated_at) VALUES (?,?,?)",
            [key, raw, _now()],
        )
    await db_commit(db)


async def resolve_model(db: SyncDB, model_id: Optional[int]) -> Dict[str, Any]:
    """按 model_id 解析模型及计费档位。

    tier: free|paid。未识别一律按 free（串行保护优先）。
    """
    row = None
    if model_id is not None and model_id >= 0:
        row = await db_fetch_one(
            db, "SELECT * FROM ai_configs WHERE id=?", [model_id]
        )
    if row is None:
        row = await db_fetch_one(
            db,
            """SELECT * FROM ai_configs
               ORDER BY CASE WHEN is_default=1 AND COALESCE(api_key,'')!='' THEN 0
                             WHEN COALESCE(api_key,'')!='' THEN 1 ELSE 2 END,
                        is_default DESC, id ASC LIMIT 1""",
        )
    tier = str((row or {}).get("tier") or "").lower()
    if tier not in ("free", "paid"):
        # 回落配置中心 cfg_kv.ai_models 按名称匹配
        tier = "free"
        try:
            models = await ai_service._models_from_cfg_kv(db)
            name = str((row or {}).get("name") or "")
            mn = str((row or {}).get("model_name") or "")
            for m in models:
                if str(m.get("name")) == name or str(m.get("model")) == mn:
                    t = str(m.get("tier") or "").lower()
                    if t in ("free", "paid"):
                        tier = t
                    break
        except Exception:  # noqa: BLE001
            pass
    return {
        "model_id": (row or {}).get("id"),
        "model_name": (row or {}).get("model_name") or "",
        "name": (row or {}).get("name") or "默认模型",
        "tier": tier,
        "configured": bool(
            (row or {}).get("api_key") and (row or {}).get("model_name")
        ),
    }


def decide_schedule(
    tier: str, task_count: int, settings: Dict[str, int]
) -> Dict[str, Any]:
    """调度决策：免费=单任务序列；付费=并行序列。"""
    if tier == "paid":
        concurrency = max(
            1, min(settings.get("paid_concurrency", 3), max(1, task_count))
        )
        if concurrency > 1:
            label = "付费模型 · %d 路并行序列" % concurrency
            mode = "parallel"
        else:
            label = "付费模型 · 单任务序列"
            mode = "serial"
        return {"mode": mode, "concurrency": concurrency, "label": label}
    return {
        "mode": "serial",
        "concurrency": max(1, settings.get("free_concurrency", 1)),
        "label": "免费模型 · 单任务序列（并发 1，串行保护额度）",
    }


# ---------------------------------------------------------------------------
# 序列 CRUD
# ---------------------------------------------------------------------------


def _row_out(r: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(r)
    try:
        out["items"] = json.loads(r.get("items") or "[]")
    except Exception:  # noqa: BLE001
        out["items"] = []
    return out


async def scheduling_preview(
    db: SyncDB, model_id: Optional[int], task_count: int = 2
) -> Dict[str, Any]:
    """提交前的调度预览：选定模型后实时返回 单任务序列/并行N路。"""
    settings = await get_scheduler_settings(db)
    model = await resolve_model(db, model_id)
    sched = decide_schedule(model["tier"], max(1, task_count), settings)
    return {
        **sched,
        "tier": model["tier"],
        "model_id": model["model_id"],
        "model_name": model["name"],
        "configured": model["configured"],
        "paid_concurrency": settings["paid_concurrency"],
        "free_concurrency": settings["free_concurrency"],
    }


async def save_scheduler_settings(
    db: SyncDB, paid_concurrency: Optional[int], free_concurrency: Optional[int]
) -> Dict[str, int]:
    cur = await get_scheduler_settings(db)
    try:
        if paid_concurrency is not None:
            v = int(paid_concurrency)
            if 1 <= v <= 8:
                cur["paid_concurrency"] = v
    except (TypeError, ValueError):
        pass
    try:
        if free_concurrency is not None:
            v = int(free_concurrency)
            if 1 <= v <= 4:
                cur["free_concurrency"] = v
    except (TypeError, ValueError):
        pass
    await _put_kv(db, SCHED_KV_KEY, cur)
    return cur


async def create_sequence(
    db: SyncDB,
    *,
    title: str,
    items: List[Dict[str, Any]],
    model_id: Optional[int],
    concurrency_override: Optional[int],
    user: str = "",
) -> Optional[Dict[str, Any]]:
    settings = await get_scheduler_settings(db)
    model = await resolve_model(db, model_id)
    sched = decide_schedule(model["tier"], len(items), settings)
    if (
        model["tier"] == "paid"
        and concurrency_override
        and 1 <= int(concurrency_override) <= 8
    ):
        sched["concurrency"] = max(1, min(int(concurrency_override), len(items) or 1))
        sched["mode"] = "parallel" if sched["concurrency"] > 1 else "serial"
        sched["label"] = (
            "付费模型 · %d 路并行序列" % sched["concurrency"]
            if sched["mode"] == "parallel"
            else "付费模型 · 单任务序列"
        )

    sid = _new_sid()
    stored_items = []
    for i, it in enumerate(items):
        stored_items.append(
            {
                "idx": i + 1,
                "name": str(it.get("name") or (it.get("requirement") or "任务")[:20])[:60],
                "payload": {
                    "requirement": str(it.get("requirement") or ""),
                    "project_type": str(it.get("project_type") or "web"),
                    "test_type": str(it.get("test_type") or "functional"),
                },
                "status": "等待中",
                "summary": "",
                "cases": [],
                "error": "",
                "started_at": None,
                "finished_at": None,
            }
        )
    await db_execute(
        db,
        """INSERT INTO gq_sequences
           (id,title,module,model_id,model_name,tier,mode,concurrency,status,
            total,done_cnt,fail_cnt,items,created_by,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            sid, title[:80] or "生成序列", "case", model["model_id"], model["name"],
            model["tier"], sched["mode"], sched["concurrency"], "排队中",
            len(stored_items), 0, 0, json.dumps(stored_items, ensure_ascii=False),
            user, _now(),
        ],
    )
    await db_commit(db)
    row = await get_sequence(db, sid)
    if row:
        row["schedule_label"] = sched["label"]
    return row


async def list_sequences(db: SyncDB, limit: int = 30) -> List[Dict[str, Any]]:
    rows = await db_fetch_all(
        db,
        "SELECT id,title,model_name,tier,mode,concurrency,status,total,done_cnt,"
        "fail_cnt,created_by,created_at,started_at,finished_at "
        "FROM gq_sequences ORDER BY created_at DESC, id DESC LIMIT ?",
        [limit],
    )
    return rows or []


async def get_sequence(db: SyncDB, sid: str) -> Optional[Dict[str, Any]]:
    row = await db_fetch_one(db, "SELECT * FROM gq_sequences WHERE id=?", [sid])
    return _row_out(row) if row else None


async def cancel_sequence(db: SyncDB, sid: str) -> Optional[Dict[str, Any]]:
    row = await get_sequence(db, sid)
    if not row:
        return None
    if row["status"] in ("排队中", "执行中"):
        items = row["items"]
        for it in items:
            if it["status"] in ("等待中", "执行中"):
                it["status"] = "已取消"
        # 计数口径与执行器 persist_items 一致（统一用 _FAIL_STATUSES），否则前端
        # 「重试失败任务」按钮依赖 fail_cnt>0，取消后永远不显示，已取消任务无法重试。
        done = sum(1 for i in items if i["status"] == "成功")
        fail = sum(1 for i in items if i["status"] in _FAIL_STATUSES)
        await db_update(
            db,
            "gq_sequences",
            {
                "status": "已取消",
                "items": json.dumps(items, ensure_ascii=False),
                "done_cnt": done,
                "fail_cnt": fail,
                "finished_at": _now(),
            },
            "id=?",
            [sid],
        )
        await db_commit(db)
        task = _RUNNING.pop(sid, None)
        if task and not task.done():
            task.cancel()
        row = await get_sequence(db, sid)
    return row


async def retry_failed(db: SyncDB, sid: str) -> Optional[Dict[str, Any]]:
    """把失败/已取消的任务项重置并重新入队执行。"""
    row = await get_sequence(db, sid)
    if not row:
        return None
    items = row["items"]
    reset = 0
    for it in items:
        if it["status"] in _FAIL_STATUSES:
            it["status"] = "等待中"
            it["error"] = ""
            it["cases"] = []
            it["started_at"] = None
            it["finished_at"] = None
            reset += 1
    if not reset:
        return row
    await db_update(
        db,
        "gq_sequences",
        {
            "status": "排队中",
            "items": json.dumps(items, ensure_ascii=False),
            "finished_at": None,
        },
        "id=?",
        [sid],
    )
    await db_commit(db)
    start_sequence(sid)
    return await get_sequence(db, sid)


# ---------------------------------------------------------------------------
# Worker（进程内 asyncio）
# ---------------------------------------------------------------------------


def _spawn(sid: str) -> None:
    task = asyncio.create_task(_run_sequence(sid))
    _RUNNING[sid] = task
    task.add_done_callback(lambda _t, s=sid: _RUNNING.pop(s, None))


def start_sequence(sid: str) -> None:
    """同一序列只允许一个 worker（重试/重启入队同样走这里）。"""
    task = _RUNNING.get(sid)
    if task and not task.done():
        return
    _spawn(sid)


async def _execute_item(item: Dict[str, Any], model_name: Optional[str]) -> None:
    """执行单个任务项（结果原地写回 item）。

    自建独立 DB 连接：SyncDB 包装为单 cursor，并行任务共享会串号。
    """
    import os

    from app.core.database import SyncDB as _SyncDB
    from app.core.database import _get_conn

    # 演示/联调用：GQ_ITEM_DELAY=2 时每任务固定耗时 2s，便于观察序列推进
    try:
        delay = float(os.getenv("GQ_ITEM_DELAY", "0") or 0)
    except ValueError:
        delay = 0.0
    if delay > 0:
        await asyncio.sleep(delay)

    payload = item.get("payload") or {}
    requirement = payload.get("requirement") or ""
    messages = build_messages(
        requirement,
        project_type=payload.get("project_type", "web"),
        test_type=payload.get("test_type", "functional"),
    )
    conn = _get_conn()
    try:
        text = await ai_service.chat(
            _SyncDB(conn),
            messages,
            module="序列生成",
            model=model_name or None,
            temperature=0.4,
            stream=False,
            max_tokens=4096,
        )
        assert isinstance(text, str)
        parsed = parse_generated_cases(text)
        if parsed and parsed.get("cases"):
            item["cases"] = parsed["cases"]
            item["summary"] = parsed.get("summary") or "生成成功"
            item["status"] = "成功"
        elif "演示模式" in text:
            demo = demo_generated_cases(requirement)
            item["cases"] = demo["cases"]
            item["summary"] = demo["summary"]
            item["status"] = "成功"
        else:
            item["status"] = "失败"
            item["cases"] = []
            item["error"] = ("AI 返回未能解析出结构化用例｜raw:%s" % text[:200])[:300]
    except Exception as exc:  # noqa: BLE001
        item["status"] = "失败"
        item["cases"] = []
        item["error"] = ("%s: %s" % (type(exc).__name__, exc))[:300]
    finally:
        conn.close()


async def _run_sequence(sid: str) -> None:
    """序列 worker：按档位串行/并行执行全部等待中任务并回写状态。"""
    from app.core.database import _get_conn

    conn = _get_conn()
    db = SyncDB(conn)  # 调度器专用连接（状态回写），与模型调用连接分离
    try:
        row = await get_sequence(db, sid)
        if not row or row["status"] not in ("排队中", "执行中"):
            return
        items: List[Dict[str, Any]] = row["items"]
        concurrency = max(1, int(row.get("concurrency") or 1))

        await db_update(
            db,
            "gq_sequences",
            {"status": "执行中", "started_at": row.get("started_at") or _now()},
            "id=?",
            [sid],
        )

        model_name = None
        if row.get("model_id") is not None and int(row["model_id"]) >= 0:
            mrow = await db_fetch_one(
                db, "SELECT name FROM ai_configs WHERE id=?", [int(row["model_id"])]
            )
            model_name = (mrow or {}).get("name")

        persist_lock = asyncio.Lock()

        async def persist_items() -> None:
            done = sum(1 for i in items if i["status"] == "成功")
            fail = sum(1 for i in items if i["status"] in _FAIL_STATUSES)
            async with persist_lock:
                # 序列已被「取消」接口落库终态时不再回写，
                # 否则会用 worker 内存里的旧状态把「已取消」覆盖回「等待中」。
                cur = await db_fetch_one(
                    db, "SELECT status FROM gq_sequences WHERE id=?", [sid]
                )
                if str((cur or {}).get("status") or "") == "已取消":
                    return
                await db_update(
                    db,
                    "gq_sequences",
                    {
                        "items": json.dumps(items, ensure_ascii=False),
                        "done_cnt": done,
                        "fail_cnt": fail,
                    },
                    "id=?",
                    [sid],
                )

        async def seq_status() -> str:
            async with persist_lock:
                cur = await db_fetch_one(
                    db, "SELECT status FROM gq_sequences WHERE id=?", [sid]
                )
            return str((cur or {}).get("status") or "")

        async def run_one(item: Dict[str, Any]) -> None:
            if item["status"] != "等待中":
                return
            if await seq_status() == "已取消":
                return
            item["status"] = "执行中"
            item["started_at"] = _now()
            await persist_items()
            await _execute_item(item, model_name)
            item["finished_at"] = _now()
            await persist_items()

        if concurrency <= 1:
            for it in items:
                await run_one(it)
        else:
            sem = asyncio.Semaphore(concurrency)

            async def guarded(it: Dict[str, Any]) -> None:
                async with sem:
                    await run_one(it)

            results = await asyncio.gather(
                *(guarded(it) for it in items), return_exceptions=True
            )
            for r in results:
                if isinstance(r, Exception):
                    print("[gen_queue] 并行任务异常: %s" % r, flush=True)

        if await seq_status() == "已取消":
            return
        fail = sum(1 for i in items if i["status"] in _FAIL_STATUSES)
        done = sum(1 for i in items if i["status"] == "成功")
        status = "已完成"
        if fail and done:
            status = "部分失败"
        elif fail and not done:
            status = "全部失败"
        await db_update(
            db,
            "gq_sequences",
            {"status": status, "finished_at": _now()},
            "id=?",
            [sid],
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        print("[gen_queue] %s 执行异常: %s" % (sid, exc), flush=True)
        try:
            await db_update(
                db,
                "gq_sequences",
                {"status": "执行异常", "finished_at": _now()},
                "id=?",
                [sid],
            )
        except Exception:  # noqa: BLE001
            pass
    finally:
        conn.close()
