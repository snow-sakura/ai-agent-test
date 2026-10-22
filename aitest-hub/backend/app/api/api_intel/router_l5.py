"""L5 契约映射路由 —— 文档端点 ↔ 本机测试代码 真实对照（spec/01 A5-L5）。

对照算法（rebuild）：
1. 取该空间最新 spec 的端点集合（common.spec_endpoints_of）；
2. 读 run_profile 的 project_root，在其下递归扫描 pytest 风格测试文件；
3. 正则从测试源码提取「HTTP 方法 + URL」与常量路径，统一 norm_path 归一；
4. 方法+路径都命中 → covered；仅路径命中 → partial；文档有项目无 → missing；
   命中忽略清单（health/docs 等）→ ignored；
5. 全量覆盖写 ai_endpoint_map（先删后插，source=auto）。
"""

import asyncio
import json
import os
import re
from bisect import bisect_right

from fastapi import APIRouter, Body, Depends, Request, Response

from app.core.database import (
    SyncDB,
    db_commit,
    db_delete,
    db_fetch_all,
    db_fetch_one,
    db_insert,
    db_update,
    get_db,
)
from app.core.deps import get_current_user

from .common import (
    ApiError,
    audit,
    get_profile,
    get_ws_or_404,
    is_ignored_endpoint,
    jload,
    norm_path,
    now_str,
    require_member,
    spec_endpoints_of,
)
from .schemas import GateCheckBody, ManualMapBody, ReleaseEvidenceBody

router = APIRouter(tags=["api-intel-l5"])

# 覆盖状态枚举（与前端筛选下拉一致）
COVERAGE_STATES = ("covered", "partial", "missing", "ignored")
MAP_METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS")

# 扫描限制（防止大仓库拖死请求）
MAX_TEST_FILES = 400
MAX_FILE_BYTES = 512 * 1024
SKIP_DIRS = {".venv", "venv", "-env", "node_modules", "__pycache__", ".git", ".idea"}

# ---- 测试源码提取正则 ----
# requests/session/client/http .get( "post( ... —— 只定位方法，路径从参数里再抽
_RE_METHOD_CALL = re.compile(
    r"""\b([A-Za-z_][\w.]*)\s*\.\s*"""
    r"""(get|post|put|delete|patch|head|options)\s*\(""",
    re.IGNORECASE,
)
# session.request("GET", <url>) 形式
_RE_REQUEST_CALL = re.compile(
    r"""\.request\s*\(\s*["'](GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)["']\s*,""",
    re.IGNORECASE,
)
# 参数串里的所有字符串字面量（支持 '...' "..." `...` 与三引号）
_RE_LITERAL = re.compile(
    r"""('''[\s\S]*?'''|\"\"\"[\s\S]*?\"\"\"|'[^'\\\n]*'|"[^"\\\n]*"|`[^`]*`)"""
)
# 兜底：源码里的常量路径字符串（只看路径正确性，判 partial）
_RE_CONST_PATH = re.compile(r"""["'](/[A-Za-z0-9_\-{}/:.]{2,})["']""")
# 所在测试函数名定位用
_RE_DEF = re.compile(r"^[ \t]*(?:async[ \t]+)?def[ \t]+([A-Za-z_]\w*)", re.M)


# =============================================================================
# 内部工具：本机测试文件扫描与端点提取
# =============================================================================


def _is_test_file(name: str, rel_parts: list) -> bool:
    """tests/**/*.py、test_*.py、*_test.py 三类均视为测试文件。"""
    if not name.endswith(".py"):
        return False
    if "tests" in rel_parts[:-1]:
        return True
    return name.startswith("test_") or name.endswith("_test.py")


def _iter_test_files(root: str) -> list:
    """递归收集测试文件绝对路径（限量、限大小，目录跳过黑名单）。"""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")
        ]
        for fn in sorted(filenames):
            fp = os.path.join(dirpath, fn)
            try:
                rel = os.path.relpath(fp, root).replace(os.sep, "/")
            except ValueError:
                continue
            if not _is_test_file(fn, rel.split("/")):
                continue
            try:
                if os.path.getsize(fp) > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            out.append(fp)
            if len(out) >= MAX_TEST_FILES:
                return out
    return out


def _func_at(def_starts: list, def_names: list, pos: int) -> str:
    """二分定位匹配偏移所在的测试函数名（找不到归为 <module>）。"""
    idx = bisect_right(def_starts, pos) - 1
    return def_names[idx] if idx >= 0 else "<module>"


def _arg_span(text: str, open_paren: int) -> str:
    """取左括号之后第一个顶层逗号之前的参数片段（支持嵌套括号与字符串）。"""
    depth = 0
    i = open_paren
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return text[open_paren + 1 : i]
        elif ch == "\n" and depth == 0:
            return text[open_paren + 1 : i]
        i += 1
    return text[open_paren + 1 : open_paren + 240]


def _url_from_args(arg: str) -> str:
    """从调用参数片段里拼出 URL：拼接所有字符串字面量，忽略变量片段。

    BASE + "/orders"        → /orders
    f"{base}/orders"        → */orders → /orders（剥掉开头的占位段）
    f"{base}/orders/{oid}"  → /orders/*
    """
    parts = [m.group(0) for m in _RE_LITERAL.finditer(arg)]
    if not parts:
        return ""
    raw = "".join(p[1:-1] for p in parts)
    p = norm_path(raw)
    if not p:
        return ""
    # 前缀是变量（base url）时归一成了 * ，去掉这个占位首段
    while p.startswith("*/"):
        p = p[1:]
    if not p.startswith("/"):
        return ""
    # 排除 dict.get("a") 这类误命中：有效接口路径要么多级，要么单级且不太短
    segs = [s for s in p.split("/") if s]
    if not segs:
        return ""
    if len(segs) == 1 and len(segs[0]) < 3 and segs[0] != "*":
        return ""
    return p


def _extract_endpoints_from_source(text: str, rel: str):
    """从单个测试源码提取 {method|None → [(path_norm, node_id)]}。"""
    def_starts = [m.start() for m in _RE_DEF.finditer(text)]
    def_names = [m.group(1) for m in _RE_DEF.finditer(text)]
    hits = []  # [(method|None, path_norm, node_id)]

    def _node(pos):
        return f"{rel}::{_func_at(def_starts, def_names, pos)}"

    # 1) requests.get(...) / session.post(...) —— 方法直接来自调用名
    for m in _RE_METHOD_CALL.finditer(text):
        p = _url_from_args(_arg_span(text, m.end() - 1))
        if p:
            hits.append((m.group(2).upper(), p, _node(m.start())))
    # 2) session.request("GET", ...) —— 方法在首参，路径在次参
    for m in _RE_REQUEST_CALL.finditer(text):
        rest = text[m.end() :]
        span = _arg_span("(" + rest, 0)
        p = _url_from_args(span)
        if p:
            hits.append((m.group(1).upper(), p, _node(m.start())))
    # 3) 兜底：裸常量路径（方法未知，只判路径）
    for m in _RE_CONST_PATH.finditer(text):
        p = norm_path(m.group(1))
        if p and p != "/":
            hits.append((None, p, ""))
    return hits


def _scan_project(root: str) -> tuple:
    """扫描项目根，返回 (方法+路径命中 {(m,p): node_id}, 仅路径命中集合 {p})。"""
    method_paths: dict = {}
    only_paths: set = set()
    for fp in _iter_test_files(root):
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except OSError:
            continue
        rel = os.path.relpath(fp, root).replace(os.sep, "/")
        for method, p, node in _extract_endpoints_from_source(text, rel):
            only_paths.add(p)
            if method and (method, p) not in method_paths and node:
                method_paths[(method, p)] = node
    return method_paths, only_paths


async def _latest_spec(db: SyncDB, ws_id: int):
    """取该空间最新一份文档快照行。"""
    return await db_fetch_one(
        db, "SELECT * FROM ai_specs WHERE ws_id=? ORDER BY id DESC LIMIT 1", [ws_id]
    )


def _stats_of(rows: list) -> dict:
    """由映射行聚合四态计数。"""
    stats = {"covered": 0, "partial": 0, "missing": 0, "ignored": 0}
    for r in rows:
        st = r.get("coverage_state") or ""
        if st in stats:
            stats[st] += 1
    return stats


# =============================================================================
# 1. 映射列表
# =============================================================================


@router.get("/workspaces/{ws_id}/endpoint-map-l5")
async def list_endpoint_map(
    ws_id: int,
    state: str = "",
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """契约映射列表；state 可选按 covered/partial/missing/ignored 过滤。"""
    await require_member(ws_id, user, db)
    state = (state or "").strip().lower()
    if state and state not in COVERAGE_STATES:
        raise ApiError(400, "无效的覆盖状态，须为 covered/partial/missing/ignored")
    rows = await db_fetch_all(
        db,
        "SELECT * FROM ai_endpoint_map WHERE ws_id=? ORDER BY path_norm, method",
        [ws_id],
    )
    full_stats = _stats_of(rows)
    items = []
    for r in rows:
        if state and (r.get("coverage_state") or "") != state:
            continue
        items.append(
            {
                "id": r["id"],
                "method": r.get("method") or "",
                "path_norm": r.get("path_norm") or "",
                "coverage_state": r.get("coverage_state") or "missing",
                "test_node_id": r.get("test_node_id") or "",
                "test_file": r.get("test_file") or "",
                "source": r.get("source") or "auto",
            }
        )
    return {"items": items, "stats": full_stats}


# =============================================================================
# 2. 真实对照重建
# =============================================================================


@router.post("/workspaces/{ws_id}/endpoint-map-l5/rebuild")
async def rebuild_endpoint_map(
    ws_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """文档端点 × 本机测试代码 全量对照，覆盖写映射表。"""
    await require_member(ws_id, user, db)

    # 1) 最新文档端点集合
    spec = await _latest_spec(db, ws_id)
    endpoints = await spec_endpoints_of(db, int(spec["id"]), ws_id) if spec else []
    if not spec or not endpoints:
        raise ApiError(400, "请先导入接口文档")
    spec_id = int(spec["id"])

    # 2) 本机项目路径
    profile = await get_profile(db, ws_id)
    root = os.path.expanduser(str(profile.get("project_root") or "").strip())
    if not root or not os.path.isdir(root):
        raise ApiError(400, "请先在执行台保存本机项目路径")

    # 3) 扫描测试代码
    method_paths, only_paths = _scan_project(root)

    # 4) 逐端点判定（按 方法+归一路径 去重）
    now = now_str()
    seen: set = set()
    rows = []
    for ep in endpoints:
        method = str(ep.get("method") or "GET").upper()
        p = norm_path(str(ep.get("path_norm") or ep.get("path") or ""))
        key = (method, p)
        if key in seen:
            continue
        seen.add(key)
        if is_ignored_endpoint(method, p):
            state, node, tfile, source = "ignored", "", "", "auto"
        elif key in method_paths:
            node = method_paths[key]
            state, tfile, source = "covered", node.split("::")[0], "auto"
        elif p in only_paths:
            state, node, tfile, source = "partial", "", "", "auto"
        else:
            state, node, tfile, source = "missing", "", "", "auto"
        rows.append(
            {
                "ws_id": ws_id,
                "method": method,
                "path_norm": p[:500],
                "test_node_id": node[:500],
                "test_file": tfile[:500],
                "coverage_state": state,
                "source": source,
                "created_at": now,
            }
        )

    # 5) 先删后插，覆盖写
    await db_delete(db, "ai_endpoint_map", "ws_id=?", [ws_id])
    for r in rows:
        await db_insert(db, "ai_endpoint_map", r)
    await db_commit(db)
    await audit(
        db,
        ws_id,
        user["id"],
        "重建契约映射",
        {"spec_id": int(spec["id"]), "total": len(rows)},
    )

    stats = _stats_of([{"coverage_state": r["coverage_state"]} for r in rows])
    return {"stats": stats, "total": len(rows)}


# =============================================================================
# 3. 缺口建议（中文摘要）
# =============================================================================


def _group_prefix(gaps: list) -> list:
    """按缺失路径的一级前缀分组 → 「/orders 相关 3 个接口无对应测试」。"""
    groups: dict = {}
    for g in gaps:
        seg = (g.get("path_norm") or "/").strip("/").split("/")[0] or "/"
        groups[seg] = groups.get(seg, 0) + 1
    ordered = sorted(groups.items(), key=lambda kv: (-kv[1], kv[0]))
    return [f"/{seg} 相关 {n} 个接口无对应测试" for seg, n in ordered if seg != "/"]


@router.get("/workspaces/{ws_id}/endpoint-map-l5/suggestions")
async def endpoint_map_suggestions(
    ws_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """基于最新对照结果生成缺口列表 + 中文建议（无对照结果时全空）。"""
    await require_member(ws_id, user, db)
    rows = await db_fetch_all(
        db, "SELECT * FROM ai_endpoint_map WHERE ws_id=?", [ws_id]
    )
    stats = _stats_of(rows)
    total = sum(stats.values())
    if total == 0:
        return {"stats": stats, "gaps": [], "suggestions": [], "ai_blurb": ""}

    gaps = [
        {
            "method": r.get("method") or "",
            "path_norm": r.get("path_norm") or "",
            "state": r.get("coverage_state") or "",
        }
        for r in rows
        if (r.get("coverage_state") or "") in ("missing", "partial")
    ][:200]

    missing_gaps = [g for g in gaps if g["state"] == "missing"]
    suggestions = _group_prefix(missing_gaps)[:3]
    if stats["partial"] > 0:
        suggestions.append(
            f"另有 {stats['partial']} 个接口路径命中但请求方法不一致，请核对测试中的 HTTP 方法"
        )
    if not suggestions:
        suggestions.append("所有文档接口均有测试覆盖，可在执行台运行一次回归验证")
    suggestions = suggestions[:4]

    ai_blurb = (
        f"共 {total} 个接口，已覆盖 {stats['covered']} 个，"
        f"文档有但项目缺 {stats['missing']} 个，建议优先补齐缺失链路，再到执行台验证。"
    )
    if stats["partial"] > 0:
        ai_blurb += f"另有 {stats['partial']} 个仅路径匹配，待人工确认。"
    return {
        "stats": stats,
        "gaps": gaps,
        "suggestions": suggestions,
        "ai_blurb": ai_blurb,
    }


# =============================================================================
# 4. 人工标注 upsert
# =============================================================================


@router.post("/workspaces/{ws_id}/endpoint-map-l5/manual")
async def manual_map(
    ws_id: int,
    body: ManualMapBody = Body(default=ManualMapBody()),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """人工标注某端点覆盖状态（source=manual，同键覆盖 auto 结果）。"""
    await require_member(ws_id, user, db)
    method = (body.method or "GET").strip().upper()
    if method not in MAP_METHODS:
        raise ApiError(400, "不支持的请求方法")
    if not (body.path_norm or "").strip():
        raise ApiError(400, "请填写接口路径")
    p = norm_path(body.path_norm)
    state = (body.coverage_state or "covered").strip().lower()
    if state not in COVERAGE_STATES:
        raise ApiError(400, "覆盖状态须为 covered/partial/missing/ignored")
    test_file = (body.test_file or "").strip()
    node = (body.test_node_id or "").strip()
    if state == "covered" and not test_file and not node:
        raise ApiError(400, "标记为已覆盖时请填写测试文件路径")
    if not node and test_file:
        node = f"{test_file}::manual"

    now = now_str()
    path_norm = p[:500]
    data: dict = {
        "test_node_id": node[:500],
        "test_file": test_file[:500],
        "coverage_state": state,
        "source": "manual",
        "created_at": now,
    }
    existing = await db_fetch_one(
        db,
        "SELECT id FROM ai_endpoint_map WHERE ws_id=? AND method=? AND path_norm=?",
        [ws_id, method, path_norm],
    )
    if existing:
        map_id = int(existing["id"])
        await db_update(db, "ai_endpoint_map", data, "id=?", [map_id])
    else:
        map_id = int(
            await db_insert(
                db,
                "ai_endpoint_map",
                {
                    **data,
                    "ws_id": ws_id,
                    "method": method,
                    "path_norm": path_norm,
                },
            )
        )
    await db_commit(db)
    await audit(
        db,
        ws_id,
        user["id"],
        "人工标注契约映射",
        {"method": method, "path": p, "state": state},
    )
    return {
        "item": {
            "id": map_id,
            "method": method,
            "path_norm": path_norm,
            "coverage_state": state,
            "test_node_id": node,
            "test_file": test_file,
            "source": "manual",
        }
    }


# =============================================================================
# 5. 删除单条映射
# =============================================================================


@router.delete("/workspaces/{ws_id}/endpoint-map-l5/{map_id}", status_code=204)
async def delete_endpoint_map(
    ws_id: int,
    map_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await require_member(ws_id, user, db)
    row = await db_fetch_one(
        db, "SELECT id FROM ai_endpoint_map WHERE ws_id=? AND id=?", [ws_id, map_id]
    )
    if not row:
        raise ApiError(404, "映射记录不存在")
    await db_delete(db, "ai_endpoint_map", "ws_id=? AND id=?", [ws_id, map_id])
    await db_commit(db)
    await audit(db, ws_id, user["id"], "删除契约映射", {"map_id": map_id})
    return Response(status_code=204)


@router.get("/platform/private-deploy")
async def platform_private_deploy():
    """是否私有化部署：云端版恒 false（页面「私有化？」说明文案据此展示）。"""
    return {"private_deploy": False}


# =============================================================================
# 6. Agent 契约上下文补丁（L5-1）
# =============================================================================


def _coverage_pct(stats: dict) -> float:
    """覆盖率 = covered / (covered+partial+missing)，ignored 不参与。"""
    judged = stats["covered"] + stats["partial"] + stats["missing"]
    return round(stats["covered"] * 100.0 / judged, 1) if judged else 100.0


async def _map_rows(db: SyncDB, ws_id: int) -> list:
    return await db_fetch_all(
        db,
        "SELECT * FROM ai_endpoint_map WHERE ws_id=? ORDER BY path_norm, method",
        [ws_id],
    )


async def build_contract_context(db: SyncDB, ws_id: int) -> dict:
    """contract-context.json 内容：Agent 写用例时直接注入的契约上下文补丁。"""
    ws = await get_ws_or_404(ws_id, db)
    rows = await _map_rows(db, ws_id)
    stats = _stats_of(rows)
    pct = _coverage_pct(stats)
    endpoints, gaps = [], []
    for r in rows:
        st = r.get("coverage_state") or "missing"
        ep = {
            "method": r.get("method") or "",
            "path": r.get("path_norm") or "",
            "coverage_state": st,
            "test_node_id": r.get("test_node_id") or "",
            "test_file": r.get("test_file") or "",
            "source": r.get("source") or "auto",
        }
        endpoints.append(ep)
        if st in ("missing", "partial"):
            gaps.append(ep)
    suggestions = _group_prefix(
        [{"path_norm": g["path"]} for g in gaps if g["coverage_state"] == "missing"]
    )[:3]
    return {
        "schema": "testhub.contract-context/v1",
        "generated_at": now_str(),
        "workspace": {"id": ws_id, "name": ws.get("name") or ""},
        "stats": {**stats, "total": len(rows), "coverage_pct": pct},
        "endpoints": endpoints,
        "gap_count": len(gaps),
        "gaps": gaps[:300],
        "suggestions": suggestions,
        "agent_instructions": [
            "写新测试优先覆盖 gaps 中 missing 的接口（测试代码里完全没有其请求调用）。",
            "pytest 风格用例放在 tests/ 目录；断言里请求的 HTTP 方法与路径必须与 method/path 一致，才会被下一轮对照识别为 covered。",
            "路径参数写成任意值即可（对照时已归一为 *），如 /orders/{oid} 与 /orders/12 视为同一路径。",
            "covered 的接口回归可直接跑 pytest，或在平台执行台触发真实运行并留档。",
        ],
    }


@router.get("/workspaces/{ws_id}/endpoint-map-l5/context-patch")
async def context_patch(
    ws_id: int,
    download: int = 0,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """Agent 上下文补丁 contract-context.json（download=1 时作为附件下载）。"""
    await require_member(ws_id, user, db)
    payload = await build_contract_context(db, ws_id)
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    headers = {}
    if download:
        headers["Content-Disposition"] = 'attachment; filename="contract-context.json"'
    return Response(content=body, media_type="application/json", headers=headers)


# =============================================================================
# 7. 发版门禁 gate-check（L5-3）
# =============================================================================


def _gate_result(threshold: float, stats: dict, rows: list) -> dict:
    pct = _coverage_pct(stats)
    blocked = [
        {
            "method": r.get("method") or "",
            "path_norm": r.get("path_norm") or "",
            "state": r.get("coverage_state") or "missing",
        }
        for r in rows
        if (r.get("coverage_state") or "") in ("missing", "partial")
    ]
    return {
        "threshold": threshold,
        "coverage_pct": pct,
        "passed": pct >= threshold,
        "stats": {**stats, "total": len(rows)},
        "blocked_count": len(blocked),
        "blocked": blocked[:50],
    }


@router.post("/workspaces/{ws_id}/endpoint-map-l5/gate-check")
async def gate_check(
    ws_id: int,
    body: GateCheckBody = Body(default=GateCheckBody()),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """按覆盖率阈值做发版门禁判定，结果落 ai_gate_checks 留档。"""
    await require_member(ws_id, user, db)
    threshold = max(0.0, min(100.0, float(body.threshold or 80.0)))
    rows = await _map_rows(db, ws_id)
    if not rows:
        raise ApiError(400, "尚未生成契约映射：请先在「接口文档」页开始对照")
    result = _gate_result(threshold, _stats_of(rows), rows)
    run_job = None
    if body.run_job_id:
        job = await db_fetch_one(
            db,
            "SELECT id, status, created_at FROM ai_run_jobs WHERE ws_id=? AND id=?",
            [ws_id, str(body.run_job_id)],
        )
        if job:
            run_job = dict(job)
    else:
        job = await db_fetch_one(
            db,
            "SELECT id, status, created_at FROM ai_run_jobs WHERE ws_id=? "
            "AND status='success' ORDER BY id DESC LIMIT 1",
            [ws_id],
        )
        if job:
            run_job = dict(job)
    now = now_str()
    detail = {**result, "run_job": run_job}
    gc_id = int(
        await db_insert(
            db,
            "ai_gate_checks",
            {
                "ws_id": ws_id,
                "threshold": threshold,
                "passed": 1 if result["passed"] else 0,
                "covered": result["stats"]["covered"],
                "total": result["stats"]["total"],
                "coverage_pct": result["coverage_pct"],
                "run_job_id": str((run_job or {}).get("id") or ""),
                "detail_json": json.dumps(detail, ensure_ascii=False),
                "created_by": user["id"],
                "created_at": now,
            },
        )
    )
    await db_commit(db)
    await audit(
        db,
        ws_id,
        user["id"],
        "发版门禁检查",
        {
            "threshold": threshold,
            "passed": result["passed"],
            "pct": result["coverage_pct"],
        },
    )
    return {"gate_check_id": gc_id, "created_at": now, **result, "run_job": run_job}


@router.get("/workspaces/{ws_id}/endpoint-map-l5/gate-checks")
async def list_gate_checks(
    ws_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """门禁检查历史（最近 20 条）。"""
    await require_member(ws_id, user, db)
    rows = await db_fetch_all(
        db,
        "SELECT * FROM ai_gate_checks WHERE ws_id=? ORDER BY id DESC LIMIT 20",
        [ws_id],
    )
    items = [
        {
            "id": r["id"],
            "threshold": r.get("threshold"),
            "passed": bool(r.get("passed")),
            "covered": r.get("covered"),
            "total": r.get("total"),
            "coverage_pct": r.get("coverage_pct"),
            "run_job_id": r.get("run_job_id") or "",
            "created_at": r.get("created_at") or "",
        }
        for r in rows
    ]
    return {"items": items}


# =============================================================================
# 8. 发版证据 release-evidence（L5-3）
# =============================================================================


@router.post("/workspaces/{ws_id}/endpoint-map-l5/release-evidence")
async def create_release_evidence(
    ws_id: int,
    body: ReleaseEvidenceBody = Body(default=ReleaseEvidenceBody()),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """把门禁结果 + 契约/映射/运行快照固化为一条发版证据存档。"""
    await require_member(ws_id, user, db)
    ws = await get_ws_or_404(ws_id, db)
    rows = await _map_rows(db, ws_id)
    if not rows:
        raise ApiError(400, "尚未生成契约映射：请先在「接口文档」页开始对照")

    gate = None
    if body.gate_check_id:
        gate = await db_fetch_one(
            db,
            "SELECT * FROM ai_gate_checks WHERE ws_id=? AND id=?",
            [ws_id, int(body.gate_check_id)],
        )
    if gate is None:
        gate = await db_fetch_one(
            db,
            "SELECT * FROM ai_gate_checks WHERE ws_id=? ORDER BY id DESC LIMIT 1",
            [ws_id],
        )
    if gate is not None:
        detail = jload(gate.get("detail_json"), {}) or {}
        gate_view = {
            "gate_check_id": gate["id"],
            "threshold": gate.get("threshold"),
            "coverage_pct": gate.get("coverage_pct"),
            "passed": bool(gate.get("passed")),
            "created_at": gate.get("created_at") or "",
            "run_job": detail.get("run_job"),
        }
    else:
        result = _gate_result(
            max(0.0, min(100.0, float(body.threshold or 80.0))), _stats_of(rows), rows
        )
        gate_view = {
            "gate_check_id": None,
            "threshold": result["threshold"],
            "coverage_pct": result["coverage_pct"],
            "passed": result["passed"],
            "created_at": "",
            "run_job": None,
        }

    spec = await _latest_spec(db, ws_id)
    spec_summary = jload((spec or {}).get("summary_json"), {}) or {}
    job = await db_fetch_one(
        db,
        "SELECT id, status, created_at FROM ai_run_jobs WHERE ws_id=? "
        "AND status='success' ORDER BY id DESC LIMIT 1",
        [ws_id],
    )
    title = (body.title or "").strip()[:200] or (
        f"{ws.get('name') or 'ws-' + str(ws_id)} 发版证据"
    )
    payload = {
        "schema": "testhub.release-evidence/v1",
        "generated_at": now_str(),
        "workspace": {"id": ws_id, "name": ws.get("name") or ""},
        "gate": gate_view,
        "map_stats": dict(_stats_of(rows), total=len(rows)),
        "blocked": [
            {
                "method": r.get("method") or "",
                "path_norm": r.get("path_norm") or "",
                "state": r.get("coverage_state") or "",
            }
            for r in rows
            if (r.get("coverage_state") or "") in ("missing", "partial")
        ][:100],
        "spec": {
            "id": (spec or {}).get("id"),
            "title": spec_summary.get("title") or "",
            "version": spec_summary.get("version") or "",
            "endpoint_count": spec_summary.get("endpoint_count"),
        },
        "latest_run_job": dict(job) if job else None,
        "created_by": user.get("username") or user.get("phone") or str(user["id"]),
    }
    now = now_str()
    ev_id = int(
        await db_insert(
            db,
            "ai_release_evidence",
            {
                "ws_id": ws_id,
                "gate_check_id": gate_view["gate_check_id"],
                "title": title,
                "payload_json": json.dumps(payload, ensure_ascii=False),
                "created_by": user["id"],
                "created_at": now,
            },
        )
    )
    await db_commit(db)
    await audit(
        db,
        ws_id,
        user["id"],
        "生成发版证据",
        {"evidence_id": ev_id, "passed": gate_view["passed"]},
    )
    return {
        "item": _evidence_item(
            {"id": ev_id, "title": title, **payload, "created_at": now}
        )
    }


def _evidence_item(row: dict) -> dict:
    payload = jload(row.get("payload_json"), None) or row
    gate = payload.get("gate") or {}
    return {
        "id": row["id"],
        "title": row.get("title") or "",
        "passed": bool(gate.get("passed")),
        "coverage_pct": gate.get("coverage_pct"),
        "threshold": gate.get("threshold"),
        "gate_check_id": gate.get("gate_check_id"),
        "created_at": row.get("created_at") or payload.get("generated_at") or "",
    }


@router.get("/workspaces/{ws_id}/endpoint-map-l5/release-evidence")
async def list_release_evidence(
    ws_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await require_member(ws_id, user, db)
    rows = await db_fetch_all(
        db,
        "SELECT id, title, payload_json, created_at FROM ai_release_evidence "
        "WHERE ws_id=? ORDER BY id DESC LIMIT 20",
        [ws_id],
    )
    return {"items": [_evidence_item(r) for r in rows]}


@router.get("/workspaces/{ws_id}/endpoint-map-l5/release-evidence/{eid}/download")
async def download_release_evidence(
    ws_id: int,
    eid: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await require_member(ws_id, user, db)
    row = await db_fetch_one(
        db, "SELECT * FROM ai_release_evidence WHERE ws_id=? AND id=?", [ws_id, eid]
    )
    if not row:
        raise ApiError(404, "证据记录不存在")
    body = json.dumps(
        jload(row.get("payload_json"), {}) or {}, ensure_ascii=False, indent=2
    )
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="release-evidence-{eid}.json"'
        },
    )


# =============================================================================
# 9. CI 集成片段（L5-2）———————————————— github / gitlab / jenkins 三种流水线
# =============================================================================


@router.get("/workspaces/{ws_id}/endpoint-map-l5/ci-snippets")
async def ci_snippets(
    ws_id: int,
    request: Request,
    gate_check_id: int = 0,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """生成可直接粘贴进客户 CI 的门禁片段（含平台地址 / 空间 ID 占位注入）。"""
    await require_member(ws_id, user, db)
    base = str(request.base_url).rstrip("/")
    gc_path = f"/api/api-intel/workspaces/{ws_id}/endpoint-map-l5/gate-check"
    ev_path = f"/api/api-intel/workspaces/{ws_id}/endpoint-map-l5/release-evidence"
    gh = (
        "name: API contract gate (TestHub L5)\n"
        "on:\n  pull_request:\n  push:\n    branches: [main]\n"
        "jobs:\n  gate:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - uses: actions/checkout@v4\n"
        "      - name: TestHub L5 gate check\n"
        "        env:\n          TESTHUB_BASE: " + base + "\n"
        "          TESTHUB_TOKEN: ${{ secrets.TESTHUB_TOKEN }}\n"
        "        run: |\n"
        '          RESULT=$(curl -sf -X POST "$TESTHUB_BASE' + gc_path + '" \\\n'
        '            -H "Authorization: Bearer $TESTHUB_TOKEN" -H "Content-Type: application/json" \\\n'
        "            -d '{\"threshold\": 80}')\n"
        '          echo "$RESULT"\n'
        '          echo "$RESULT" | grep -q \'"passed": *true\' || {\n'
        '            echo "::error::接口契约门禁未通过"; exit 1; }\n'
        '          curl -sf -X POST "$TESTHUB_BASE' + ev_path + '" \\\n'
        '            -H "Authorization: Bearer $TESTHUB_TOKEN" -H "Content-Type: application/json" -d \'{}\'\n'
    )
    gl = (
        "contract-gate:\n  stage: test\n  image: curlimages/curl:latest\n"
        "  variables:\n    TESTHUB_BASE: " + base + "\n"
        "  script:\n"
        '    - RESULT=$(curl -sf -X POST "$TESTHUB_BASE' + gc_path + '" \\\n'
        '        -H "Authorization: Bearer $TESTHUB_TOKEN" -H "Content-Type: application/json" \\\n'
        "        -d '{\"threshold\": 80}')\n"
        '    - echo "$RESULT"\n'
        '    - echo "$RESULT" | grep -q \'"passed": *true\' || exit 1\n'
        '    - curl -sf -X POST "$TESTHUB_BASE' + ev_path + '" \\\n'
        '        -H "Authorization: Bearer $TESTHUB_TOKEN" -H "Content-Type: application/json" -d \'{}\'\n'
        "  rules:\n    - if: $CI_PIPELINE_SOURCE == 'merge_request_event'\n"
    )
    jk = (
        "pipeline {\n  agent any\n  environment {\n    TESTHUB_BASE = '" + base + "'\n"
        "    TESTHUB_TOKEN = credentials('testhub-token')\n  }\n  stages {\n"
        "    stage('L5 contract gate') {\n      steps {\n        sh '''\n"
        '          RESULT=$(curl -sf -X POST "$TESTHUB_BASE' + gc_path + '" \\\n'
        '            -H "Authorization: Bearer $TESTHUB_TOKEN" -H "Content-Type: application/json" \\\n'
        "            -d '{\"threshold\": 80}')\n"
        '          echo "$RESULT"\n'
        '          echo "$RESULT" | grep -q \'"passed": *true\' || exit 1\n'
        '          curl -sf -X POST "$TESTHUB_BASE' + ev_path + '" \\\n'
        '            -H "Authorization: Bearer $TESTHUB_TOKEN" -H "Content-Type: application/json" -d \'{}\'\n'
        "        '''\n      }\n    }\n  }\n}\n"
    )
    return {
        "base_url": base,
        "workspace_id": ws_id,
        "gate_check_path": gc_path,
        "release_evidence_path": ev_path,
        "snippets": {"github": gh, "gitlab": gl, "jenkins": jk},
    }
