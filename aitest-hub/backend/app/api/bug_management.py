"""缺陷管理（UI 版）后端路由，字段与 UI/tool-defect-management.html 一一对应。

- 缺陷: id(BUG-####), title, module, sev, pri, env, status, reporter, assignee,
        case, time, steps, actual, expected, attachments(文件名数组)
- 独立于既有项目作用域的 ORM 缺陷子系统；为避免路由冲突，挂载于 /api/bugs。
表以 dm_ 前缀，空库自动灌入 UI 设计稿缺陷（seed）。
"""

import json
import re
import uuid
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from pydantic import BaseModel

from app.core.database import (
    SyncDB,
    get_db,
    db_fetch_all,
    db_fetch_one,
    db_insert,
    db_update,
    db_delete,
    db_execute,
    db_commit,
)
from app.core.deps import get_current_user
from app.services import ai as ai_service

router = APIRouter(tags=["bug-management"])

# 鉴权契约（与 UI 对齐）：GET 列表/详情与 AI 查重（dup-check）不鉴权，演示可读；
# 写操作（create/patch/delete/comments）保持 get_current_user。

STATUSES = ["新建", "处理中", "待验证", "已关闭", "已拒绝"]


class BugCreate(BaseModel):
    title: str
    module: str = ""
    sev: str = "S2 一般"
    pri: str = "P2"
    env: str = "TEST"
    case: str = ""
    assignee: str = "未分配"
    steps: str = ""
    actual: str = ""
    expected: str = ""
    attachments: List[str] = []


class BugUpdate(BaseModel):
    title: Optional[str] = None
    module: Optional[str] = None
    sev: Optional[str] = None
    pri: Optional[str] = None
    env: Optional[str] = None
    status: Optional[str] = None
    assignee: Optional[str] = None
    case: Optional[str] = None
    steps: Optional[str] = None
    actual: Optional[str] = None
    expected: Optional[str] = None
    attachments: Optional[List[str]] = None


class DupCheck(BaseModel):
    title: str = ""
    module: str = ""


class CommentReq(BaseModel):
    text: str


def _display_name(user: dict) -> str:
    profile = user.get("profile") or {}
    return (
        profile.get("nickname")
        or user.get("full_name")
        or user.get("username")
        or "匿名"
    )


def _row_to_bug(r: dict) -> dict:
    att = r.get("attachments") or "[]"
    try:
        att = json.loads(att)
    except Exception:
        att = []
    return {
        "id": r["id"],
        "title": r.get("title", ""),
        "module": r.get("module", ""),
        "sev": r.get("sev", ""),
        "pri": r.get("pri", ""),
        "env": r.get("env", ""),
        "status": r.get("status", "新建"),
        "reporter": r.get("reporter", ""),
        "assignee": r.get("assignee", "未分配"),
        "case": r.get("case_id", ""),  # 表列名为 case_id（BUG-04：原读 "case" 恒为空）
        "time": r.get("time", ""),
        "steps": r.get("steps", ""),
        "actual": r.get("actual", ""),
        "expected": r.get("expected", ""),
        "attachments": att,
    }


import re as _re
from datetime import datetime

_SEED = [
    (
        "BUG-2043",
        "TEST·支付·支付成功但订单状态未更新",
        "支付模块",
        "S1 严重",
        "P1",
        "TEST",
        "处理中",
        "wxh",
        "李雷",
        "TC-1004",
        "2026-09-22 09:30",
        "1. 下单并支付成功\n2. 返回订单列表",
        "订单仍显示待支付",
        "订单状态更新为已支付",
    ),
    (
        "BUG-2042",
        "TEST·退款·200字说明提交后截断为199字",
        "订单模块",
        "S2 一般",
        "P2",
        "TEST",
        "待验证",
        "韩梅",
        "王强",
        "TC-1003",
        "2026-09-21 15:12",
        "1. 退款说明输入200字\n2. 提交\n3. 查看详情",
        "详情页显示199字",
        "完整保存200字",
    ),
    (
        "BUG-2041",
        "STAGING·库存·并发下单超卖1件",
        "库存模块",
        "S0 致命",
        "P0",
        "STAGING",
        "新建",
        "李雷",
        "未分配",
        "TC-1007",
        "2026-09-21 11:48",
        "1. 库存设为1\n2. 两个账号并发下单",
        "两单均成功，库存-2",
        "仅一单成功",
    ),
    (
        "BUG-2040",
        "TEST·用户·未登录访问/user未跳转登录页",
        "用户模块",
        "S2 一般",
        "P2",
        "TEST",
        "已关闭",
        "wxh",
        "赵敏",
        "TC-1006",
        "2026-09-19 10:05",
        "1. 退出登录\n2. 访问/user",
        "空白页",
        "跳转登录页",
    ),
    (
        "BUG-2039",
        "DEV·订单·取消已发货订单无提示",
        "订单模块",
        "S3 轻微",
        "P3",
        "DEV",
        "已拒绝",
        "韩梅",
        "王强",
        "",
        "2026-09-18 14:30",
        "1. 对已发货订单点取消",
        "无二次确认弹窗",
        "设计如此，已发货不可取消属预期",
    ),
    (
        "BUG-2038",
        "TEST·支付·退款回调重复通知",
        "支付模块",
        "S1 严重",
        "P1",
        "TEST",
        "新建",
        "wxh",
        "未分配",
        "TC-1001",
        "2026-09-22 08:20",
        "1. 退款成功\n2. 观察回调日志",
        "同一退款单收到2次回调",
        "回调幂等，仅1次",
    ),
]


async def _ensure_schema(db):
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS dm_defects (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, module TEXT DEFAULT '',
        sev TEXT DEFAULT 'S2 一般', pri TEXT DEFAULT 'P2', env TEXT DEFAULT 'TEST',
        status TEXT DEFAULT '新建', reporter TEXT DEFAULT '', assignee TEXT DEFAULT '未分配',
        case_id TEXT DEFAULT '', time TEXT DEFAULT '', steps TEXT DEFAULT '',
        actual TEXT DEFAULT '', expected TEXT DEFAULT '', attachments TEXT DEFAULT '[]',
        created_at TEXT DEFAULT (datetime('now')))""",
    )
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS dm_defect_comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, defect_id TEXT NOT NULL,
        by_user TEXT DEFAULT '', text TEXT DEFAULT '',
        time TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now')))""",
    )
    await db_commit(db)
    if (await db_fetch_one(db, "SELECT COUNT(*) AS c FROM dm_defects", []) or {}).get(
        "c", 0
    ) == 0:
        for b in _SEED:
            await db_execute(
                db,
                """INSERT OR IGNORE INTO dm_defects
                (id,title,module,sev,pri,env,status,reporter,assignee,case_id,time,steps,actual,expected)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                list(b),
            )
        await db_commit(db)


async def _next_bug_id(db):
    rows = await db_fetch_all(db, "SELECT id FROM dm_defects WHERE id LIKE 'BUG-%'", [])
    nums = []
    for r in rows:
        try:
            nums.append(int(r["id"].split("-")[1]))
        except (ValueError, IndexError):
            pass
    return "BUG-%d" % ((max(nums) if nums else 2037) + 1)


def _bigrams(s):
    s = _re.sub(r"\s+", "", s or "")
    return (
        set(s[i : i + 2] for i in range(len(s)))
        if len(s) > 1
        else ({s} if s else set())
    )


def _similarity(a, b):
    A, B = _bigrams(a), _bigrams(b)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


BUG_NEW = "\u65b0\u5efa"  # xin jian
BUG_UNASSIGNED = "\u672a\u5206\u914d"  # wei fen pei
ERR_NO_TITLE = "\u7f3a\u9677\u6807\u9898\u4e0d\u80fd\u4e3a\u7a7a"
ERR_NOT_FOUND = "\u7f3a\u9677\u4e0d\u5b58\u5728"
ERR_NO_COMMENT = "\u8bc4\u8bba\u5185\u5bb9\u4e0d\u80fd\u4e3a\u7a7a"


@router.get("/bugs")
async def list_bugs(
    q: str = "",
    status: str = "",
    sev: str = "",
    env: str = "",
    db: SyncDB = Depends(get_db),
):
    await _ensure_schema(db)
    rows = await db_fetch_all(db, "SELECT * FROM dm_defects ORDER BY id DESC", [])
    out = []
    for r in rows:
        if status and r.get("status") != status:
            continue
        if sev and r.get("sev") != sev:
            continue
        if env and r.get("env") != env:
            continue
        if q and q not in (r.get("title", "") + r.get("module", "") + r.get("id", "")):
            continue
        out.append(_row_to_bug(r))
    return out


def _local_dup(body: DupCheck, rows):
    """本地 bigram 相似度基线，返回 (best_row, percent)。"""
    best, best_s = None, 0.0
    for r in rows:
        s = _similarity(body.title, r.get("title", ""))
        if body.module and r.get("module") == body.module:
            s = min(1.0, s + 0.15)
        if s > best_s:
            best, best_s = r, s
    return best, round(best_s * 100)


@router.post("/bugs/dup-check")
async def dup_check(body: DupCheck, db: SyncDB = Depends(get_db)):
    """缺陷查重：统一 AI 服务（module=缺陷查重）优先，无 Key/失败降级本地相似度。"""
    await _ensure_schema(db)
    rows = await db_fetch_all(db, "SELECT id, title, module FROM dm_defects", [])
    local_row, local_pct = _local_dup(body, rows)

    ai_row, ai_pct = None, 0
    if body.title.strip():
        cand = "\n".join(
            "%s | %s | %s" % (r["id"], r.get("module", ""), r.get("title", ""))
            for r in rows[:50]
        )
        try:
            data = await ai_service.chat_json(
                db,
                [
                    {
                        "role": "system",
                        "content": (
                            "你是缺陷查重助手。在候选缺陷中找出与新缺陷标题最相似的一条（可能没有）。"
                            '只输出 JSON：{"dup_id": "BUG-xxxx 或 none", "percent": 0-100 的整数, '
                            '"reason": "一句话依据"}'
                        ),
                    },
                    {
                        "role": "user",
                        "content": "新缺陷标题：%s\n模块：%s\n\n候选缺陷：\n%s"
                        % (body.title, body.module or "未指定", cand or "（暂无）"),
                    },
                ],
                module="缺陷查重",
            )
            if isinstance(data, dict):
                did = str(data.get("dup_id") or "").strip()
                try:
                    pct = int(float(str(data.get("percent") or 0)))
                except (TypeError, ValueError):
                    pct = 0
                pct = max(0, min(100, pct))
                hit = next((r for r in rows if r["id"] == did), None)
                if hit is not None:
                    ai_row, ai_pct = hit, pct
        except Exception:
            ai_row = None

    # 取相似度更高的一方（AI 结果无效/无 Key 时自然落到本地基线）
    if ai_row is not None and ai_pct >= local_pct:
        best, pct = ai_row, ai_pct
    else:
        best, pct = local_row, local_pct
    if best is not None and pct >= 25:
        return {
            "found": True,
            "id": best["id"],
            "title": best.get("title", ""),
            "percent": pct,
        }
    return {"found": False, "percent": pct}


# ============ 附件真实上传：文件落盘到 backend/uploads/bug_attachments ============
# attachments 字段保持 List[str]（存附件 URL），旧的纯文件名数据向下兼容可显示。
ATTACH_DIR = Path(__file__).resolve().parents[2] / "uploads" / "bug_attachments"
MAX_ATTACH_FILES = 5
MAX_ATTACH_SIZE = 5 * 1024 * 1024  # 单文件 5MB
ALLOWED_ATTACH_EXT = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".log",
    ".txt",
    ".zip",
    ".json",
    ".csv",
}


def _safe_filename(name: str) -> str:
    """清洗上传文件名：去除路径分隔符与控制字符，仅保留基础名。"""
    base = (name or "").replace("\\", "/").split("/")[-1].strip()
    base = re.sub(r"[\x00-\x1f\x7f]", "", base)
    base = re.sub(r"[\\/:*?\"<>|]", "_", base)
    return base[:120] or "unnamed"


@router.post("/bugs/attachments/upload")
async def upload_bug_attachments(
    files: List[UploadFile] = File(...),
    current_user: dict = Depends(get_current_user),
):
    """上传缺陷附件（截图 / 日志），返回 [{name, url}]，url 可直接访问。

    校验：数量 ≤ 5、单文件 ≤ 5MB、扩展名白名单；全部通过才落盘（原子语义）。
    """
    uploads = [f for f in (files or []) if f is not None]
    if not uploads:
        raise HTTPException(status_code=400, detail="未接收到任何附件文件")
    if len(uploads) > MAX_ATTACH_FILES:
        raise HTTPException(status_code=400, detail=f"附件最多 {MAX_ATTACH_FILES} 个")

    # 先全量校验，再统一落盘，避免半成功状态
    checked = []
    for f in uploads:
        fname = _safe_filename(f.filename or "")
        ext = Path(fname).suffix.lower()
        if ext not in ALLOWED_ATTACH_EXT:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的附件类型: {fname}（支持图片/日志/文本等常见格式）",
            )
        data = await f.read()
        if len(data) > MAX_ATTACH_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"{fname} 超过 5MB 大小限制",
            )
        if not data:
            raise HTTPException(status_code=400, detail=f"{fname} 文件内容为空")
        checked.append((fname, data))

    ATTACH_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for fname, data in checked:
        # 唯一化文件名，避免同名覆盖
        stem = Path(fname).stem
        ext = Path(fname).suffix
        safe_stem = re.sub(r"\s+", "-", stem)[:60]
        unique = f"{safe_stem}-{uuid.uuid4().hex[:8]}{ext}"
        target = ATTACH_DIR / unique
        target.write_bytes(data)
        results.append({"name": fname, "url": f"/uploads/bug_attachments/{unique}"})
    return {"files": results}


@router.post("/bugs")
async def create_bug(
    body: BugCreate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ensure_schema(db)
    if not body.title.strip():
        raise HTTPException(status_code=400, detail=ERR_NO_TITLE)
    bid = await _next_bug_id(db)
    await db_insert(
        db,
        "dm_defects",
        {
            "id": bid,
            "title": body.title.strip(),
            "module": body.module,
            "sev": body.sev,
            "pri": body.pri,
            "env": body.env,
            "status": BUG_NEW,
            "reporter": _display_name(current_user),
            "assignee": body.assignee or BUG_UNASSIGNED,
            "case_id": body.case,
            "time": _now(),
            "steps": body.steps,
            "actual": body.actual,
            "expected": body.expected,
            "attachments": json.dumps(body.attachments[:5], ensure_ascii=False),
        },
    )
    row = await db_fetch_one(db, "SELECT * FROM dm_defects WHERE id=?", [bid])
    return _row_to_bug(row)


@router.get("/bugs/{bid}")
async def get_bug(
    bid: str,
    db: SyncDB = Depends(get_db),
):
    await _ensure_schema(db)
    row = await db_fetch_one(db, "SELECT * FROM dm_defects WHERE id=?", [bid])
    if not row:
        raise HTTPException(status_code=404, detail=ERR_NOT_FOUND)
    cms = await db_fetch_all(
        db,
        "SELECT by_user, text, time FROM dm_defect_comments WHERE defect_id=? ORDER BY id ASC",
        [bid],
    )
    comments = [{"by": c["by_user"], "text": c["text"], "time": c["time"]} for c in cms]
    return {"bug": _row_to_bug(row), "comments": comments}


@router.patch("/bugs/{bid}")
async def patch_bug(
    bid: str,
    body: BugUpdate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ensure_schema(db)
    if not await db_fetch_one(db, "SELECT id FROM dm_defects WHERE id=?", [bid]):
        raise HTTPException(status_code=404, detail=ERR_NOT_FOUND)
    mapped = {
        "title": "title",
        "module": "module",
        "sev": "sev",
        "pri": "pri",
        "env": "env",
        "status": "status",
        "assignee": "assignee",
        "case": "case_id",
        "steps": "steps",
        "actual": "actual",
        "expected": "expected",
    }
    data = {}
    for k, col in mapped.items():
        v = getattr(body, k, None)
        if v is not None:
            data[col] = v
    if body.attachments is not None:
        data["attachments"] = json.dumps(body.attachments[:5], ensure_ascii=False)
    if data:
        await db_update(db, "dm_defects", data, "id=?", [bid])
    row = await db_fetch_one(db, "SELECT * FROM dm_defects WHERE id=?", [bid])
    return _row_to_bug(row)


@router.delete("/bugs/{bid}")
async def delete_bug(
    bid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ensure_schema(db)
    if not await db_fetch_one(db, "SELECT id FROM dm_defects WHERE id=?", [bid]):
        raise HTTPException(status_code=404, detail=ERR_NOT_FOUND)
    await db_delete(db, "dm_defects", "id=?", [bid])
    return {"deleted": bid}


@router.post("/bugs/{bid}/comments")
async def add_comment(
    bid: str,
    body: CommentReq,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ensure_schema(db)
    if not await db_fetch_one(db, "SELECT id FROM dm_defects WHERE id=?", [bid]):
        raise HTTPException(status_code=404, detail=ERR_NOT_FOUND)
    if not body.text.strip():
        raise HTTPException(status_code=400, detail=ERR_NO_COMMENT)
    await db_execute(
        db,
        "INSERT INTO dm_defect_comments (defect_id, by_user, text, time) VALUES (?,?,?,?)",
        [bid, _display_name(current_user), body.text.strip(), _now()],
    )
    await db_commit(db)
    return {"ok": True}
