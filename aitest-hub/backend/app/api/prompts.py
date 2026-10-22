"""提示词库（Prompts）— /api/prompts

子能力：
- 列表 CRUD（创建/查询/更新/删除）+ 按用户收藏（pm_favorites）
- 投稿状态流：待评审 → 已发布/已驳回 → 重新提交
- 我的投稿 / 我的收藏 专用端点
字段对齐 UI/prompts.html：id,title,cat,tags,stars,uses,updated,content,visibility,status
扩展：owner_id,note,reject_reason
"""

import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.database import (
    SyncDB,
    db_commit,
    db_delete,
    db_execute,
    db_fetch_all,
    db_fetch_one,
    db_insert,
    db_update,
    get_db,
)
from app.core.deps import get_current_user, get_optional_user
from app.services.ai import simple

router = APIRouter(tags=["prompts"])

_SEED = [
    {
        "id": 1,
        "title": "测试用例设计专家",
        "cat": "测试设计",
        "tags": ["用例", "需求分析"],
        "stars": 98,
        "uses": 982,
        "updated": "2026-09-18",
        "visibility": "公开",
        "status": "已发布",
        "content": "你是一名资深测试工程师。请基于以下需求，使用等价类划分、边界值分析、判定表和场景法设计完整测试用例。输出表格：用例编号 / 标题 / 优先级 / 前置条件 / 步骤 / 预期结果。需求：\n{{需求文本}}",
    },
    {
        "id": 2,
        "title": "Bug 复现步骤分析",
        "cat": "缺陷分析",
        "tags": ["缺陷", "复现"],
        "stars": 87,
        "uses": 876,
        "updated": "2026-09-15",
        "visibility": "公开",
        "status": "已发布",
        "content": "你是一名缺陷分析专家。根据以下缺陷描述，分析最可能的根因，给出最小复现步骤、复现概率评估，并建议补充的日志埋点。缺陷描述：\n{{缺陷内容}}",
    },
    {
        "id": 3,
        "title": "接口断言设计专家",
        "cat": "接口测试",
        "tags": ["断言", "API"],
        "stars": 85,
        "uses": 851,
        "updated": "2026-09-20",
        "visibility": "公开",
        "status": "已发布",
        "content": "你是一名接口测试专家。针对以下接口文档，设计断言清单：状态码、响应结构 Schema、业务字段值、数据库落库校验、幂等性校验。接口文档：\n{{接口文档}}",
    },
    {
        "id": 4,
        "title": "Selenium 自动化脚本生成",
        "cat": "自动化",
        "tags": ["Selenium", "Python"],
        "stars": 79,
        "uses": 790,
        "updated": "2026-09-12",
        "visibility": "公开",
        "status": "已发布",
        "content": "你是一名自动化工程师。基于以下操作步骤生成 Python + Selenium 脚本，使用 Page Object 模式，显式等待，异常截图，并附带 pytest 用例骨架。步骤：\n{{操作步骤}}",
    },
    {
        "id": 5,
        "title": "JMeter 压测场景顾问",
        "cat": "性能测试",
        "tags": ["JMeter", "压测"],
        "stars": 73,
        "uses": 733,
        "updated": "2026-09-10",
        "visibility": "公开",
        "status": "已发布",
        "content": "你是一名性能测试专家。根据业务目标 QPS {{QPS}} 与接口清单，设计 JMeter 线程组参数（并发数 / Ramp-Up / 循环）、阶梯加压策略、监控指标与通过标准。",
    },
    {
        "id": 6,
        "title": "AI 需求转用例（结构化）",
        "cat": "AI 用例",
        "tags": ["AI", "用例"],
        "stars": 71,
        "uses": 712,
        "updated": "2026-09-21",
        "visibility": "公开",
        "status": "已发布",
        "content": "你是一名测试用例生成器。将以下需求转换为 Given-When-Then 格式的结构化用例，覆盖正常流、异常流与边界值，按 P0/P1/P2 标注优先级。需求：\n{{需求}}",
    },
    {
        "id": 7,
        "title": "日志错误聚类分析",
        "cat": "缺陷分析",
        "tags": ["日志", "定位"],
        "stars": 65,
        "uses": 655,
        "updated": "2026-09-08",
        "visibility": "公开",
        "status": "已发布",
        "content": "你是一名线上问题排查专家。分析以下错误日志，按根因聚类输出：错误类型 / 出现次数 / 可能模块 / 建议排查方向。日志：\n{{日志片段}}",
    },
    {
        "id": 8,
        "title": "Playwright E2E 用例生成",
        "cat": "自动化",
        "tags": ["Playwright", "E2E"],
        "stars": 62,
        "uses": 620,
        "updated": "2026-09-19",
        "visibility": "公开",
        "status": "已发布",
        "content": "你是一名 E2E 测试专家。基于以下用户旅程，生成 Playwright + TypeScript 测试代码，包含 fixture 封装、失败重试与截图录像配置。旅程：\n{{用户旅程}}",
    },
    {
        "id": 9,
        "title": "SQL 造数脚本生成",
        "cat": "接口测试",
        "tags": ["SQL", "造数"],
        "stars": 58,
        "uses": 588,
        "updated": "2026-09-05",
        "visibility": "公开",
        "status": "已发布",
        "content": "你是一名数据构造专家。根据表结构与造数规则，生成批量 INSERT 脚本，注意字段约束、唯一索引冲突规避与事务分批提交。表结构：\n{{DDL}}\n规则：{{规则}}",
    },
    {
        "id": 10,
        "title": "兼容性测试矩阵设计",
        "cat": "测试设计",
        "tags": ["兼容性", "矩阵"],
        "stars": 54,
        "uses": 540,
        "updated": "2026-09-02",
        "visibility": "公开",
        "status": "已发布",
        "content": "你是一名测试架构师。针对 {{产品类型}} 设计浏览器 / OS / 分辨率 / 弱网兼容性测试矩阵，标注优先级与覆盖策略，输出执行排期建议。",
    },
    {
        "id": 11,
        "title": "接口 Mock 数据策略",
        "cat": "接口测试",
        "tags": ["Mock", "数据"],
        "stars": 50,
        "uses": 501,
        "updated": "2026-08-30",
        "visibility": "公开",
        "status": "已发布",
        "content": "你是一名接口测试专家。为以下依赖接口设计 Mock 方案：字段规则、异常码模拟、延迟注入、有状态 Mock 序列。接口定义：\n{{接口定义}}",
    },
    {
        "id": 12,
        "title": "APP 崩溃日志归因",
        "cat": "缺陷分析",
        "tags": ["Android", "崩溃"],
        "stars": 47,
        "uses": 477,
        "updated": "2026-08-27",
        "visibility": "公开",
        "status": "已发布",
        "content": "你是一名移动端稳定性专家。分析以下 crash 堆栈，定位可疑代码路径，给出修复建议与回归验证用例。堆栈：\n{{堆栈}}",
    },
    {
        "id": 13,
        "title": "混沌工程演练方案",
        "cat": "性能测试",
        "tags": ["混沌", "高可用"],
        "stars": 44,
        "uses": 442,
        "updated": "2026-08-24",
        "visibility": "公开",
        "status": "已发布",
        "content": "你是一名高可用专家。为 {{系统名称}} 设计混沌演练方案：故障注入点、爆炸半径控制、观测指标、回滚预案与演练记录模板。",
    },
    {
        "id": 14,
        "title": "AI 缺陷报告润色",
        "cat": "AI 用例",
        "tags": ["AI", "缺陷"],
        "stars": 41,
        "uses": 410,
        "updated": "2026-08-20",
        "visibility": "公开",
        "status": "待评审",
        "content": "你是一名 QA 文档专家。将以下草稿润色为规范缺陷报告：标题（环境+模块+现象）、复现概率、严重等级建议、附件清单。草稿：\n{{草稿}}",
    },
    {
        "id": 15,
        "title": "CI 流水线质量门禁设计",
        "cat": "自动化",
        "tags": ["CI", "门禁"],
        "stars": 38,
        "uses": 388,
        "updated": "2026-08-16",
        "visibility": "公开",
        "status": "已发布",
        "content": "你是一名 DevOps 专家。为 {{项目}} 设计 CI 质量门禁：单测覆盖率阈值、静态扫描规则、接口回归范围、阻断策略与通知链路。",
    },
]


class PromptCreate(BaseModel):
    title: str
    cat: str = "测试设计"
    tags: List[str] = []
    content: str = ""
    visibility: str = "公开"
    status: str = "已发布"
    note: str = ""


class PromptUpdate(BaseModel):
    title: Optional[str] = None
    cat: Optional[str] = None
    tags: Optional[List[str]] = None
    content: Optional[str] = None
    visibility: Optional[str] = None
    status: Optional[str] = None
    note: Optional[str] = None


class RejectReq(BaseModel):
    reason: str = ""


class AiOptimizeReq(BaseModel):
    content: str


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d")


async def _ensure_schema(db: SyncDB):
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS pm_prompts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL, cat TEXT, tags TEXT, stars INTEGER DEFAULT 0,
        uses INTEGER DEFAULT 0, updated TEXT, content TEXT,
        visibility TEXT DEFAULT '公开', status TEXT DEFAULT '已发布',
        starred INTEGER DEFAULT 0, created_at TEXT)""",
    )
    # 增量列：owner_id / note / reject_reason（老库无这些列时补上）
    cols = await db_fetch_all(db, "PRAGMA table_info(pm_prompts)", [])
    names = {c["name"] for c in (cols or [])}
    if "owner_id" not in names:
        await db_execute(db, "ALTER TABLE pm_prompts ADD COLUMN owner_id INTEGER")
    if "note" not in names:
        await db_execute(db, "ALTER TABLE pm_prompts ADD COLUMN note TEXT DEFAULT ''")
    if "reject_reason" not in names:
        await db_execute(
            db, "ALTER TABLE pm_prompts ADD COLUMN reject_reason TEXT DEFAULT ''"
        )
    # 按用户收藏（行级 starred 仅兼容保留，真实收藏在此表）
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS pm_favorites (
        user_id INTEGER NOT NULL,
        prompt_id INTEGER NOT NULL,
        created_at TEXT,
        PRIMARY KEY (user_id, prompt_id))""",
    )
    await db_commit(db)


async def _seed_if_empty(db: SyncDB):
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM pm_prompts", [])
    if row and row["c"]:
        return
    for p in _SEED:
        await db_insert(
            db,
            "pm_prompts",
            {
                "id": p["id"],
                "title": p["title"],
                "cat": p["cat"],
                "tags": json.dumps(p["tags"], ensure_ascii=False),
                "stars": p["stars"],
                "uses": p["uses"],
                "updated": p["updated"],
                "content": p["content"],
                "visibility": p["visibility"],
                "status": p["status"],
                "starred": 0,
                "created_at": p["updated"],
            },
        )
    await db_commit(db)


def _parse_tags(raw) -> list:
    tags = raw or "[]"
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = [t for t in tags.split(",") if t]
    if not isinstance(tags, list):
        tags = []
    return tags


def _row(r: dict, starred: bool = False) -> dict:
    return {
        "id": r["id"],
        "title": r.get("title", ""),
        "cat": r.get("cat", ""),
        "tags": _parse_tags(r.get("tags")),
        "stars": r.get("stars", 0) or 0,
        "uses": r.get("uses", 0) or 0,
        "updated": r.get("updated") or r.get("created_at") or "",
        "content": r.get("content") or "",
        "visibility": r.get("visibility") or "公开",
        "status": r.get("status") or "已发布",
        "starred": bool(starred),
        "owner_id": r.get("owner_id"),
        "note": r.get("note") or "",
        "reject_reason": r.get("reject_reason") or "",
    }


async def _fav_ids(db: SyncDB, user_id: int) -> set:
    rows = await db_fetch_all(
        db, "SELECT prompt_id FROM pm_favorites WHERE user_id=?", [user_id]
    )
    return {r["prompt_id"] for r in (rows or [])}


def _can_modify(row: dict, user: dict) -> bool:
    """演示环境：seed（owner 空）或本人可改；否则 403。"""
    oid = row.get("owner_id")
    if oid is None:
        return True
    return int(oid) == int(user.get("id") or 0)


async def _load(db: SyncDB, pid: int) -> dict:
    row = await db_fetch_one(db, "SELECT * FROM pm_prompts WHERE id=?", [pid])
    if not row:
        raise HTTPException(status_code=404, detail="提示词不存在")
    return row


async def _init(db: SyncDB):
    await _ensure_schema(db)
    await _seed_if_empty(db)


@router.get("/prompts")
async def list_prompts(
    cat: str = Query("", description="分类筛选"),
    q: str = Query("", description="关键词"),
    status: str = Query("", description="状态筛选"),
    db: SyncDB = Depends(get_db),
    user: Optional[dict] = Depends(get_optional_user),
):
    """提示词列表（可匿名读；登录时附带 starred）。"""
    await _init(db)
    rows = await db_fetch_all(
        db, "SELECT * FROM pm_prompts ORDER BY stars DESC, id DESC", []
    )
    favs = await _fav_ids(db, user["id"]) if user else set()
    out = []
    ql = (q or "").lower()
    for r in rows:
        item = _row(r, starred=(r["id"] in favs))
        if cat and item["cat"] != cat:
            continue
        if status and item["status"] != status:
            continue
        if (
            ql
            and ql
            not in (item["title"] + item["content"] + "".join(item["tags"])).lower()
        ):
            continue
        out.append(item)
    return out


@router.get("/prompts/favorites")
async def list_favorites(
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """我的收藏（按用户）。"""
    await _init(db)
    rows = await db_fetch_all(
        db,
        """SELECT p.* FROM pm_prompts p
           JOIN pm_favorites f ON f.prompt_id = p.id
           WHERE f.user_id = ?
           ORDER BY f.created_at DESC, p.id DESC""",
        [user["id"]],
    )
    return [_row(r, starred=True) for r in (rows or [])]


@router.get("/prompts/mine")
async def list_mine(
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """我的投稿（owner_id = 当前用户），含全部状态。"""
    await _init(db)
    favs = await _fav_ids(db, user["id"])
    rows = await db_fetch_all(
        db,
        "SELECT * FROM pm_prompts WHERE owner_id=? ORDER BY updated DESC, id DESC",
        [user["id"]],
    )
    return [_row(r, starred=r["id"] in favs) for r in (rows or [])]


@router.post("/prompts")
async def create_prompt(
    body: PromptCreate,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """创建提示词；列表新建默认已发布，投稿入口传 status=待评审。"""
    await _init(db)
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="标题不能为空")
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="提示词内容不能为空")
    status = (
        body.status
        if body.status in ("已发布", "待评审", "已驳回", "草稿")
        else "已发布"
    )
    pid = await db_insert(
        db,
        "pm_prompts",
        {
            "title": body.title.strip(),
            "cat": body.cat,
            "tags": json.dumps(body.tags or [], ensure_ascii=False),
            "stars": 0,
            "uses": 1,
            "updated": _now(),
            "content": body.content,
            "visibility": body.visibility,
            "status": status,
            "starred": 0,
            "created_at": _now(),
            "owner_id": user["id"],
            "note": body.note or "",
            "reject_reason": "",
        },
    )
    row = await _load(db, pid)
    return _row(row)


@router.put("/prompts/{pid}")
async def update_prompt(
    pid: int,
    body: PromptUpdate,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _init(db)
    row = await _load(db, pid)
    if not _can_modify(row, user):
        raise HTTPException(status_code=403, detail="无权修改该提示词")
    data = {}
    if body.title is not None:
        data["title"] = body.title.strip()
    if body.cat is not None:
        data["cat"] = body.cat
    if body.tags is not None:
        data["tags"] = json.dumps(body.tags, ensure_ascii=False)
    if body.content is not None:
        data["content"] = body.content
    if body.visibility is not None:
        data["visibility"] = body.visibility
    if body.status is not None:
        data["status"] = body.status
    if body.note is not None:
        data["note"] = body.note
    if data:
        data["updated"] = _now()
        await db_update(db, "pm_prompts", data, "id=?", [pid])
    favs = await _fav_ids(db, user["id"])
    return _row(await _load(db, pid), starred=pid in favs)


@router.delete("/prompts/{pid}")
async def delete_prompt(
    pid: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _init(db)
    row = await _load(db, pid)
    if not _can_modify(row, user):
        raise HTTPException(status_code=403, detail="无权删除该提示词")
    await db_delete(db, "pm_favorites", "prompt_id=?", [pid])
    await db_delete(db, "pm_prompts", "id=?", [pid])
    return {"ok": True, "id": pid}


@router.post("/prompts/{pid}/star")
async def star_prompt(
    pid: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """按用户收藏切换：写 pm_favorites，stars 计数同步 ±1。"""
    await _init(db)
    await _load(db, pid)
    exists = await db_fetch_one(
        db,
        "SELECT 1 AS x FROM pm_favorites WHERE user_id=? AND prompt_id=?",
        [user["id"], pid],
    )
    if exists:
        await db_delete(
            db, "pm_favorites", "user_id=? AND prompt_id=?", [user["id"], pid]
        )
        starred = False
    else:
        await db_insert(
            db,
            "pm_favorites",
            {
                "user_id": user["id"],
                "prompt_id": pid,
                "created_at": _now(),
            },
        )
        starred = True
    row = await _load(db, pid)
    stars = max(0, (row.get("stars") or 0) + (1 if starred else -1))
    await db_update(db, "pm_prompts", {"stars": stars}, "id=?", [pid])
    result = _row(await _load(db, pid), starred=starred)
    return result


@router.post("/prompts/{pid}/review")
async def review_prompt(
    pid: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """提交评审：状态改为「待评审」。"""
    await _init(db)
    row = await _load(db, pid)
    if not _can_modify(row, user):
        raise HTTPException(status_code=403, detail="无权操作该提示词")
    await db_update(
        db,
        "pm_prompts",
        {"status": "待评审", "reject_reason": "", "updated": _now()},
        "id=?",
        [pid],
    )
    favs = await _fav_ids(db, user["id"])
    return _row(await _load(db, pid), starred=pid in favs)


@router.post("/prompts/{pid}/approve")
async def approve_prompt(
    pid: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """审核通过：待评审 → 已发布（演示环境登录即可审核）。"""
    await _init(db)
    await _load(db, pid)
    await db_update(
        db,
        "pm_prompts",
        {"status": "已发布", "reject_reason": "", "updated": _now()},
        "id=?",
        [pid],
    )
    favs = await _fav_ids(db, user["id"])
    return _row(await _load(db, pid), starred=pid in favs)


@router.post("/prompts/{pid}/reject")
async def reject_prompt(
    pid: int,
    body: RejectReq,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """审核驳回：待评审 → 已驳回，记录原因。"""
    await _init(db)
    await _load(db, pid)
    await db_update(
        db,
        "pm_prompts",
        {
            "status": "已驳回",
            "reject_reason": (body.reason or "").strip() or "内容需完善后重新提交",
            "updated": _now(),
        },
        "id=?",
        [pid],
    )
    favs = await _fav_ids(db, user["id"])
    return _row(await _load(db, pid), starred=pid in favs)


@router.post("/prompts/ai-optimize")
async def ai_optimize(
    body: AiOptimizeReq,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """AI 优化提示词文案（module=提示词）。"""
    await _init(db)
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="content 不能为空")
    prompt = (
        "你是提示词工程专家。请优化以下测试提示词，使其角色更清晰、指令更具体、"
        "输出格式更结构化、约束更完整。只输出优化后的提示词正文，不要解释。\n\n"
        f"原文：\n{body.content}"
    )
    optimized = await simple(db, prompt, module="提示词")
    return {"content": optimized, "optimized": True}
