"""知识库（Knowledge Base）— /api/knowledge/*

三类资产（对齐 UI/tool-knowledge-base.html）：
- 测试模式 kb_patterns: id,name,cat,uses,tags,desc,detail
- Bug 知识  kb_bugs:     id,title,cat,cause,solution,tags
- 知识条目  kb_entries:  id,title,cat,tags,created,body,summary
RAG 检索：LIKE 匹配 + score/snippet/source
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
from app.core.deps import get_current_user
from app.services.ai import simple

router = APIRouter(tags=["knowledge"])

# ---------------------------------------------------------------------------
# 种子数据（来自 UI 数组字面量）
# ---------------------------------------------------------------------------

_PATTERN_SEED = [
    {
        "id": "PT-12",
        "name": "登录认证测试模式",
        "cat": "登录",
        "uses": 86,
        "tags": ["安全", "P0"],
        "desc": "正常登录 / 错误密码 / 账号锁定 / 验证码 / 会话保持全覆盖",
        "detail": "1. 正常登录：合法账密 → 认证成功跳转\n2. 错误密码：连续 5 次失败 → 锁定 15min\n3. 验证码：过期 / 错误 / 刷新后旧码失效\n4. 会话：token 过期自动跳登录页\n5. 安全：密码不明文回显、错误提示不泄露具体字段",
    },
    {
        "id": "PT-11",
        "name": "支付金额边界模式",
        "cat": "支付",
        "uses": 64,
        "tags": ["边界", "P0"],
        "desc": "0 元 / 负数 / 超限 / 精度 / 退款金额大于支付",
        "detail": "1. 0 元支付拦截\n2. 金额上限（单笔 / 单日）\n3. 两位小数精度：0.1+0.2 ≠ 0.3 场景\n4. 退款金额 ≤ 支付金额\n5. 并发支付幂等",
    },
    {
        "id": "PT-10",
        "name": "表单校验模式",
        "cat": "表单",
        "uses": 102,
        "tags": ["常用"],
        "desc": "必填 / 长度 / 格式 / 唯一性 / XSS 转义",
        "detail": "1. 必填逐项置空提交\n2. 边界长度 min-1 / min / max / max+1\n3. 格式：手机 / 邮箱 / 身份证非法值\n4. 唯一性：重复提交\n5. 特殊字符 <script> 转义",
    },
    {
        "id": "PT-09",
        "name": "列表分页筛选模式",
        "cat": "列表",
        "uses": 77,
        "tags": ["常用"],
        "desc": "空态 / 翻页保持 / 组合筛选 / 排序稳定性",
        "detail": "1. 空数据态展示\n2. 筛选后翻页条件保持\n3. 清空筛选恢复全量\n4. 排序翻转稳定性\n5. 删除末页唯一条目后页码回退",
    },
    {
        "id": "PT-08",
        "name": "文件上传模式",
        "cat": "文件上传",
        "uses": 45,
        "tags": ["安全"],
        "desc": "类型 / 大小 / 重名 / 断点 / 恶意文件",
        "detail": "1. 非法扩展名拦截\n2. 超大小限制提示\n3. 同名覆盖策略\n4. 上传中断重试\n5. 双扩展名 .jpg.exe 拦截",
    },
    {
        "id": "PT-07",
        "name": "订单状态机模式",
        "cat": "支付",
        "uses": 39,
        "tags": ["状态流转"],
        "desc": "全状态迁移矩阵 + 非法迁移拒绝",
        "detail": "1. 合法链路：待支付→已支付→已完成\n2. 非法迁移：已取消→已支付 拒绝\n3. 超时未支付自动取消\n4. 退款后状态回写",
    },
]

_BUG_SEED = [
    {
        "id": "BK-23",
        "title": "重复提交订单产生双扣款",
        "cat": "并发缺陷",
        "cause": "支付按钮未防重，前端未禁用 + 后端无幂等键",
        "solution": "后端按 clientOrderId 幂等去重；前端提交后禁用按钮",
        "tags": ["支付", "P0"],
    },
    {
        "id": "BK-22",
        "title": "分页筛选条件丢失跳回第一页",
        "cat": "逻辑缺陷",
        "cause": "翻页组件未携带筛选参数",
        "solution": "将筛选条件并入分页请求 query；切筛选重置页码",
        "tags": ["列表"],
    },
    {
        "id": "BK-21",
        "title": "金额计算出现 0.30000000000000004",
        "cat": "边界缺陷",
        "cause": "浮点直接运算",
        "solution": "金额统一用分为单位整数运算，展示层再格式化",
        "tags": ["支付", "精度"],
    },
    {
        "id": "BK-20",
        "title": "XSS：昵称注入脚本可执行",
        "cat": "安全缺陷",
        "cause": "昵称渲染未转义",
        "solution": "统一 v-text / 转义渲染；输入侧过滤 <script>",
        "tags": ["安全"],
    },
    {
        "id": "BK-19",
        "title": "iOS 低电量模式上传图片失败无提示",
        "cat": "兼容缺陷",
        "cause": "低电量下网络策略变化未捕获异常",
        "solution": "捕获上传异常并给出弱网提示与重试入口",
        "tags": ["APP"],
    },
    {
        "id": "BK-18",
        "title": "优惠券叠加后金额为负",
        "cat": "逻辑缺陷",
        "cause": "优惠叠加未做下限校验",
        "solution": "优惠后金额下限 0.01 元；叠加规则服务端重算",
        "tags": ["支付", "营销"],
    },
]

_ENTRY_SEED = [
    {
        "id": "KB-31",
        "title": "接口测试环境变量规范",
        "cat": "测试规范",
        "tags": ["接口", "规范"],
        "created": "2026-09-20",
        "body": "环境变量命名：{{env.域名}}、{{df.测试数据}}、{{mcp.服务返回}}；禁止硬编码密码，敏感值走配置中心。",
        "summary": "接口测试环境变量命名与敏感值管理规范",
    },
    {
        "id": "KB-30",
        "title": "测试环境部署手册 v3",
        "cat": "环境手册",
        "tags": ["环境", "部署"],
        "created": "2026-09-14",
        "body": "前端 :3000 / 后端 :8000 / Redis :6379；数据库初始化与种子数据脚本见 docs/deploy.md。",
        "summary": "测试环境端口与部署说明",
    },
    {
        "id": "KB-29",
        "title": "Playwright 常用定位速查",
        "cat": "工具指南",
        "tags": ["UI 自动化"],
        "created": "2026-09-08",
        "body": "优先级：getByTestId > getByRole > getByText > css；避免绝对 XPath。",
        "summary": "Playwright 元素定位优先级速查",
    },
    {
        "id": "KB-28",
        "title": "缺陷提交流程与模板",
        "cat": "流程说明",
        "tags": ["缺陷", "流程"],
        "created": "2026-08-30",
        "body": "标题：[模块] 现象一句话；正文：前置条件 / 复现步骤 / 预期 vs 实际 / 截图日志；P0 级 15 分钟内同步企微。",
        "summary": "缺陷提交规范与升级流程",
    },
    {
        "id": "KB-27",
        "title": "AI 用例生成提示词编写规范",
        "cat": "测试规范",
        "tags": ["AI", "提示词"],
        "created": "2026-08-22",
        "body": "结构：角色 → 输入上下文 → 输出格式（表格列名固定）→ 约束（覆盖正常/边界/异常）；配合去 AI 味策略使用。",
        "summary": "AI 用例提示词结构规范",
    },
]


# ---------------------------------------------------------------------------
# Schema / Seed
# ---------------------------------------------------------------------------


async def _ensure_schema(db: SyncDB):
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS kb_patterns (
        id TEXT PRIMARY KEY, name TEXT, cat TEXT, uses INTEGER DEFAULT 0,
        tags TEXT, desc TEXT, detail TEXT, created_at TEXT)""",
    )
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS kb_bugs (
        id TEXT PRIMARY KEY, title TEXT, cat TEXT, cause TEXT,
        solution TEXT, tags TEXT, created_at TEXT)""",
    )
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS kb_entries (
        id TEXT PRIMARY KEY, title TEXT, cat TEXT, tags TEXT,
        created TEXT, body TEXT, summary TEXT, status TEXT DEFAULT '启用',
        stars INTEGER DEFAULT 0, size INTEGER DEFAULT 0, type TEXT DEFAULT '文档',
        up INTEGER DEFAULT 0, created_at TEXT)""",
    )
    await db_commit(db)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d")


async def _seed_if_empty(db: SyncDB):
    for table, seed, mapper in (
        (
            "kb_patterns",
            _PATTERN_SEED,
            lambda p: {
                "id": p["id"],
                "name": p["name"],
                "cat": p["cat"],
                "uses": p["uses"],
                "tags": json.dumps(p["tags"], ensure_ascii=False),
                "desc": p["desc"],
                "detail": p["detail"],
                "created_at": _now(),
            },
        ),
        (
            "kb_bugs",
            _BUG_SEED,
            lambda b: {
                "id": b["id"],
                "title": b["title"],
                "cat": b["cat"],
                "cause": b["cause"],
                "solution": b["solution"],
                "tags": json.dumps(b["tags"], ensure_ascii=False),
                "created_at": _now(),
            },
        ),
        (
            "kb_entries",
            _ENTRY_SEED,
            lambda e: {
                "id": e["id"],
                "title": e["title"],
                "cat": e["cat"],
                "tags": json.dumps(e["tags"], ensure_ascii=False),
                "created": e["created"],
                "body": e["body"],
                "summary": e.get("summary", ""),
                "status": "启用",
                "stars": 0,
                "size": len(e["body"]),
                "type": e["cat"],
                "up": 0,
                "created_at": e["created"],
            },
        ),
    ):
        row = await db_fetch_one(db, f"SELECT COUNT(*) AS c FROM {table}", [])
        if row and row["c"]:
            continue
        for item in seed:
            await db_insert(db, table, mapper(item))
    await db_commit(db)


async def _init(db: SyncDB):
    await _ensure_schema(db)
    await _seed_if_empty(db)


def _tags(v) -> list:
    if isinstance(v, list):
        return v
    if not v:
        return []
    try:
        return json.loads(v)
    except Exception:
        return [t for t in str(v).split(",") if t]


def _pattern_row(r: dict) -> dict:
    return {
        "id": r["id"],
        "name": r.get("name", ""),
        "title": r.get("name", ""),
        "cat": r.get("cat", ""),
        "uses": r.get("uses", 0) or 0,
        "times": r.get("uses", 0) or 0,
        "tags": _tags(r.get("tags")),
        "desc": r.get("desc", ""),
        "detail": r.get("detail", ""),
        "fix": r.get("detail", ""),
        "sev": r.get("cat", ""),
    }


def _bug_row(r: dict) -> dict:
    return {
        "id": r["id"],
        "title": r.get("title", ""),
        "cat": r.get("cat", ""),
        "cause": r.get("cause", ""),
        "solution": r.get("solution", ""),
        "tags": _tags(r.get("tags")),
        "desc": r.get("cause", ""),
        "fix": r.get("solution", ""),
        "sev": r.get("cat", ""),
        "times": 1,
    }


def _entry_row(r: dict) -> dict:
    return {
        "id": r["id"],
        "name": r.get("title", ""),
        "title": r.get("title", ""),
        "cat": r.get("cat", ""),
        "type": r.get("type") or r.get("cat", ""),
        "size": r.get("size", 0) or 0,
        "up": r.get("up", 0) or 0,
        "stars": r.get("stars", 0) or 0,
        "status": r.get("status") or "启用",
        "summary": r.get("summary") or "",
        "tags": _tags(r.get("tags")),
        "created": r.get("created") or "",
        "body": r.get("body") or "",
    }


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class PatternBody(BaseModel):
    name: str = ""
    title: str = ""
    cat: str = "通用"
    tags: List[str] = []
    desc: str = ""
    detail: str = ""
    uses: int = 0


class BugBody(BaseModel):
    title: str
    cat: str = "逻辑缺陷"
    cause: str = ""
    solution: str = ""
    tags: List[str] = []
    desc: str = ""
    fix: str = ""


class EntryBody(BaseModel):
    title: str = ""
    name: str = ""
    cat: str = "测试规范"
    tags: List[str] = []
    body: str = ""
    summary: str = ""
    content: str = ""


class AiIngestReq(BaseModel):
    name: str
    text: str


# ---------------------------------------------------------------------------
# 测试模式
# ---------------------------------------------------------------------------


@router.get("/knowledge/patterns")
async def list_patterns(
    q: str = Query(""), cat: str = Query(""), db: SyncDB = Depends(get_db)
):
    await _init(db)
    rows = await db_fetch_all(db, "SELECT * FROM kb_patterns ORDER BY uses DESC", [])
    out = [_pattern_row(r) for r in rows]
    if cat:
        out = [p for p in out if p["cat"] == cat]
    if q:
        ql = q.lower()
        out = [p for p in out if ql in (p["name"] + p["desc"]).lower()]
    return out


@router.post("/knowledge/patterns")
async def create_pattern(
    body: PatternBody,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _init(db)
    name = (body.name or body.title).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name 不能为空")
    pid = "PT-%02d" % (
        (await db_fetch_one(db, "SELECT COUNT(*) AS c FROM kb_patterns", []))["c"] + 13
    )
    await db_insert(
        db,
        "kb_patterns",
        {
            "id": pid,
            "name": name,
            "cat": body.cat,
            "uses": body.uses,
            "tags": json.dumps(body.tags, ensure_ascii=False),
            "desc": body.desc,
            "detail": body.detail,
            "created_at": _now(),
        },
    )
    return _pattern_row(
        await db_fetch_one(db, "SELECT * FROM kb_patterns WHERE id=?", [pid])
    )


@router.put("/knowledge/patterns/{pid}")
async def update_pattern(
    pid: str,
    body: PatternBody,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _init(db)
    if not await db_fetch_one(db, "SELECT id FROM kb_patterns WHERE id=?", [pid]):
        raise HTTPException(status_code=404, detail="pattern not found")
    name = (body.name or body.title).strip()
    await db_update(
        db,
        "kb_patterns",
        {
            "name": name,
            "cat": body.cat,
            "uses": body.uses,
            "tags": json.dumps(body.tags, ensure_ascii=False),
            "desc": body.desc,
            "detail": body.detail,
        },
        "id=?",
        [pid],
    )
    return _pattern_row(
        await db_fetch_one(db, "SELECT * FROM kb_patterns WHERE id=?", [pid])
    )


@router.delete("/knowledge/patterns/{pid}")
async def delete_pattern(
    pid: str, user: dict = Depends(get_current_user), db: SyncDB = Depends(get_db)
):
    await _init(db)
    if not await db_fetch_one(db, "SELECT id FROM kb_patterns WHERE id=?", [pid]):
        raise HTTPException(status_code=404, detail="pattern not found")
    await db_delete(db, "kb_patterns", "id=?", [pid])
    return {"ok": True, "id": pid}


# ---------------------------------------------------------------------------
# Bug 知识
# ---------------------------------------------------------------------------


@router.get("/knowledge/bugs")
async def list_bugs(
    q: str = Query(""), cat: str = Query(""), db: SyncDB = Depends(get_db)
):
    await _init(db)
    rows = await db_fetch_all(db, "SELECT * FROM kb_bugs ORDER BY id DESC", [])
    out = [_bug_row(r) for r in rows]
    if cat:
        out = [b for b in out if b["cat"] == cat]
    if q:
        ql = q.lower()
        out = [b for b in out if ql in (b["title"] + b["cause"]).lower()]
    return out


@router.post("/knowledge/bugs")
async def create_bug(
    body: BugBody, user: dict = Depends(get_current_user), db: SyncDB = Depends(get_db)
):
    await _init(db)
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="title 不能为空")
    bid = "BK-%02d" % (
        (await db_fetch_one(db, "SELECT COUNT(*) AS c FROM kb_bugs", []))["c"] + 24
    )
    await db_insert(
        db,
        "kb_bugs",
        {
            "id": bid,
            "title": body.title,
            "cat": body.cat,
            "cause": body.cause or body.desc,
            "solution": body.solution or body.fix,
            "tags": json.dumps(body.tags, ensure_ascii=False),
            "created_at": _now(),
        },
    )
    return _bug_row(await db_fetch_one(db, "SELECT * FROM kb_bugs WHERE id=?", [bid]))


@router.put("/knowledge/bugs/{bid}")
async def update_bug(
    bid: str,
    body: BugBody,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _init(db)
    if not await db_fetch_one(db, "SELECT id FROM kb_bugs WHERE id=?", [bid]):
        raise HTTPException(status_code=404, detail="bug not found")
    await db_update(
        db,
        "kb_bugs",
        {
            "title": body.title,
            "cat": body.cat,
            "cause": body.cause or body.desc,
            "solution": body.solution or body.fix,
            "tags": json.dumps(body.tags, ensure_ascii=False),
        },
        "id=?",
        [bid],
    )
    return _bug_row(await db_fetch_one(db, "SELECT * FROM kb_bugs WHERE id=?", [bid]))


@router.delete("/knowledge/bugs/{bid}")
async def delete_bug(
    bid: str, user: dict = Depends(get_current_user), db: SyncDB = Depends(get_db)
):
    await _init(db)
    if not await db_fetch_one(db, "SELECT id FROM kb_bugs WHERE id=?", [bid]):
        raise HTTPException(status_code=404, detail="bug not found")
    await db_delete(db, "kb_bugs", "id=?", [bid])
    return {"ok": True, "id": bid}


# ---------------------------------------------------------------------------
# 知识条目
# ---------------------------------------------------------------------------


@router.get("/knowledge/entries")
async def list_entries(
    q: str = Query(""), cat: str = Query(""), db: SyncDB = Depends(get_db)
):
    await _init(db)
    rows = await db_fetch_all(db, "SELECT * FROM kb_entries ORDER BY id DESC", [])
    out = [_entry_row(r) for r in rows]
    if cat:
        out = [e for e in out if e["cat"] == cat]
    if q:
        ql = q.lower()
        out = [e for e in out if ql in (e["title"] + e["body"]).lower()]
    return out


@router.post("/knowledge/entries")
async def create_entry(
    body: EntryBody,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _init(db)
    title = (body.title or body.name).strip()
    content = body.body or body.content
    if not title:
        raise HTTPException(status_code=400, detail="title 不能为空")
    eid = "KB-%02d" % (
        (await db_fetch_one(db, "SELECT COUNT(*) AS c FROM kb_entries", []))["c"] + 32
    )
    await db_insert(
        db,
        "kb_entries",
        {
            "id": eid,
            "title": title,
            "cat": body.cat,
            "tags": json.dumps(body.tags, ensure_ascii=False),
            "created": _now(),
            "body": content,
            "summary": body.summary,
            "status": "启用",
            "stars": 0,
            "size": len(content),
            "type": body.cat,
            "up": 0,
            "created_at": _now(),
        },
    )
    return _entry_row(
        await db_fetch_one(db, "SELECT * FROM kb_entries WHERE id=?", [eid])
    )


@router.put("/knowledge/entries/{eid}")
async def update_entry(
    eid: str,
    body: EntryBody,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _init(db)
    if not await db_fetch_one(db, "SELECT id FROM kb_entries WHERE id=?", [eid]):
        raise HTTPException(status_code=404, detail="entry not found")
    content = body.body or body.content
    await db_update(
        db,
        "kb_entries",
        {
            "title": (body.title or body.name),
            "cat": body.cat,
            "tags": json.dumps(body.tags, ensure_ascii=False),
            "body": content,
            "summary": body.summary,
            "size": len(content),
        },
        "id=?",
        [eid],
    )
    return _entry_row(
        await db_fetch_one(db, "SELECT * FROM kb_entries WHERE id=?", [eid])
    )


@router.delete("/knowledge/entries/{eid}")
async def delete_entry(
    eid: str, user: dict = Depends(get_current_user), db: SyncDB = Depends(get_db)
):
    await _init(db)
    if not await db_fetch_one(db, "SELECT id FROM kb_entries WHERE id=?", [eid]):
        raise HTTPException(status_code=404, detail="entry not found")
    await db_delete(db, "kb_entries", "id=?", [eid])
    return {"ok": True, "id": eid}


@router.post("/knowledge/entries/ai-ingest")
async def ai_ingest(
    body: AiIngestReq,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """AI 抽取摘要后入库知识条目。"""
    await _init(db)
    if not body.name.strip() or not body.text.strip():
        raise HTTPException(status_code=400, detail="name/text 不能为空")
    prompt = (
        "你是知识库整理助手。请从以下文档中抽取一条简洁摘要（不超过 80 字），"
        "并给出 3 个逗号分隔的标签。严格按 JSON 输出："
        '{"summary": "...", "tags": "标签1,标签2,标签3"}\n\n'
        f"文档标题：{body.name}\n文档内容：\n{body.text[:3000]}"
    )
    summary = ""
    tags: List[str] = []
    try:
        raw = await simple(db, prompt, module="知识库")
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            import json as _json

            data = _json.loads(text[start : end + 1])
            summary = str(data.get("summary") or "")
            tags = [t for t in str(data.get("tags") or "").split(",") if t]
    except Exception:
        summary = body.text[:80]
    if not summary:
        summary = body.text[:80]
    eid = "KB-%02d" % (
        (await db_fetch_one(db, "SELECT COUNT(*) AS c FROM kb_entries", []))["c"] + 32
    )
    await db_insert(
        db,
        "kb_entries",
        {
            "id": eid,
            "title": body.name,
            "cat": "流程说明",
            "tags": json.dumps(tags or ["AI 入库"], ensure_ascii=False),
            "created": _now(),
            "body": body.text,
            "summary": summary,
            "status": "启用",
            "stars": 0,
            "size": len(body.text),
            "type": "文档",
            "up": 0,
            "created_at": _now(),
        },
    )
    return _entry_row(
        await db_fetch_one(db, "SELECT * FROM kb_entries WHERE id=?", [eid])
    )


# ---------------------------------------------------------------------------
# RAG 检索
# ---------------------------------------------------------------------------


@router.get("/knowledge/rag")
async def rag_search(q: str = Query(""), db: SyncDB = Depends(get_db)):
    """LIKE 检索三类资产，返回 score/snippet/source。"""
    await _init(db)
    if not q.strip():
        return {"q": q, "hits": [], "total": 0}
    ql = q.strip().lower()
    hits = []
    like = f"%{q.strip()}%"

    for r in await db_fetch_all(
        db,
        "SELECT * FROM kb_patterns WHERE name LIKE ? OR desc LIKE ? OR detail LIKE ? OR tags LIKE ?",
        [like, like, like, like],
    ):
        item = _pattern_row(r)
        score = 0.9 if ql in item["name"].lower() else 0.7
        hits.append(
            {
                "type": "测试模式",
                "id": item["id"],
                "title": item["name"],
                "snippet": item["desc"],
                "source": f"kb_patterns/{item['id']}",
                "score": score,
            }
        )
    for r in await db_fetch_all(
        db,
        "SELECT * FROM kb_bugs WHERE title LIKE ? OR cause LIKE ? OR solution LIKE ? OR tags LIKE ?",
        [like, like, like, like],
    ):
        item = _bug_row(r)
        score = 0.9 if ql in item["title"].lower() else 0.7
        hits.append(
            {
                "type": "Bug 知识",
                "id": item["id"],
                "title": item["title"],
                "snippet": "根因：" + item["cause"],
                "source": f"kb_bugs/{item['id']}",
                "score": score,
            }
        )
    for r in await db_fetch_all(
        db,
        "SELECT * FROM kb_entries WHERE title LIKE ? OR body LIKE ? OR summary LIKE ? OR tags LIKE ?",
        [like, like, like, like],
    ):
        item = _entry_row(r)
        score = 0.9 if ql in item["title"].lower() else 0.7
        hits.append(
            {
                "type": "知识条目",
                "id": item["id"],
                "title": item["title"],
                "snippet": (item["summary"] or item["body"])[:80],
                "source": f"kb_entries/{item['id']}",
                "score": score,
            }
        )

    hits.sort(key=lambda h: -h["score"])
    if not hits:
        # 无命中时回退演示：返回前两条，保持页面可用
        pats = await db_fetch_all(db, "SELECT * FROM kb_patterns LIMIT 1", [])
        ents = await db_fetch_all(db, "SELECT * FROM kb_entries LIMIT 1", [])
        for r in pats:
            item = _pattern_row(r)
            hits.append(
                {
                    "type": "测试模式",
                    "id": item["id"],
                    "title": item["name"],
                    "snippet": item["desc"],
                    "source": f"kb_patterns/{item['id']}",
                    "score": 0.5,
                }
            )
        for r in ents:
            item = _entry_row(r)
            hits.append(
                {
                    "type": "知识条目",
                    "id": item["id"],
                    "title": item["title"],
                    "snippet": item["body"][:80],
                    "source": f"kb_entries/{item['id']}",
                    "score": 0.5,
                }
            )
    return {"q": q, "hits": hits[:8], "total": len(hits)}
