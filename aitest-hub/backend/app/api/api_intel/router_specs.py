"""接口智能：文档 spec / 数据源(sources) / 命中(hits) / 覆盖率(coverage)。

契约要点：
- 响应字段名严格对齐前端案例站；时间统一 "%Y-%m-%d %H:%M:%S" 字符串。
- 解析、鉴权、审计、同步任务全部复用 common.py，不重复实现。
- 错误统一 ApiError(status, "中文提示")，写法照 router_workspaces.py。
"""

import json
import re

import httpx
from fastapi import APIRouter, Body, Depends

from app.core.database import (
    SyncDB,
    db_commit,
    db_delete,
    db_fetch_all,
    db_fetch_one,
    db_insert,
    get_db,
)
from app.core.deps import get_current_user

from .common import (
    DocParseError,
    HTTP_METHODS,
    ApiError,
    audit,
    extract_summary,
    is_ignored_endpoint,
    jdump,
    jload,
    list_sync_jobs,
    norm_path,
    now_str,
    parse_doc_text,
    record_sync_job,
    require_member,
    spec_endpoints_of,
)
from .schemas import (
    CoverageAnalyzeBody,
    HitsCreateBody,
    SpecCreateBody,
    SpecFromUrlBody,
    SyncUrlL5Body,
    YapiImportBody,
)

router = APIRouter(tags=["api-intel-specs"])

# 文档大小上限（与前端一致：5MB）
MAX_DOC_BYTES = 5 * 1024 * 1024
# 服务端抓取超时（秒）
FETCH_TIMEOUT = 15.0
_FETCH_HEADERS = {"User-Agent": "aitest-hub-api-intel/1.0 (+openapi-fetch)"}


# =============================================================================
# 文档解析（JSON / YAML；PyYAML 缺失时使用极简 YAML 兜底解析）
# =============================================================================


def _yaml_strip_comment(line: str) -> str:
    """去掉行尾注释（引号内的 # 不生效）。"""
    out, quote = [], ""
    for idx, ch in enumerate(line):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            continue
        if ch == "#" and (idx == 0 or line[idx - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out)


def _yaml_split_commas(s: str) -> list:
    """按顶层逗号切分 flow 序列/映射（忽略引号与括号内的逗号）。"""
    parts, buf, depth, quote = [], [], 0, ""
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            continue
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _yaml_split_key(content: str):
    """把 `key: value` 行拆成 (key, 余下文本)；非映射行返回 (None, "")。"""
    quote = ""
    for idx, ch in enumerate(content):
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in ("'", '"'):
            quote = ch
            continue
        if ch == ":" and (idx + 1 == len(content) or content[idx + 1] in " \t"):
            return content[:idx].strip().strip("\"'"), content[idx + 1 :].strip()
    return None, ""


def _yaml_scalar(tok: str):
    """解析标量：引号串/flow 集合/布尔/数字/空值，其余按原样字符串。"""
    t = tok.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"'):
        return t[1:-1]
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        return [_yaml_scalar(p) for p in _yaml_split_commas(inner)] if inner else []
    if t.startswith("{") and t.endswith("}"):
        out = {}
        for part in _yaml_split_commas(t[1:-1].strip()):
            k, rest = _yaml_split_key(part)
            if k is None:
                continue
            out[str(k)] = _yaml_scalar(rest) if rest else None
        return out
    low = t.lower()
    if low in ("", "~", "null"):
        return None
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    return t


def _yaml_block(lines: list, i: int, indent: int):
    """递归下降解析一个缩进块，返回 (value, 下一个行号)。"""
    if i >= len(lines):
        return None, i
    if lines[i][1].startswith("- ") or lines[i][1] == "-":
        return _yaml_list(lines, i, indent)
    return _yaml_map(lines, i, indent)


def _yaml_map(lines: list, i: int, indent: int):
    out = {}
    while i < len(lines):
        ind, content = lines[i]
        # 缩进变浅/变深或遇到同级序列：当前映射块结束
        if ind != indent or content.startswith("-"):
            break
        key, rest = _yaml_split_key(content)
        if key is None:
            raise ValueError(f"无法解析的 YAML 行：{content}")
        i += 1
        # 块标量 | 与 >：收集更深缩进的后续行
        if rest in ("|", "|-", "|+", ">", ">-", ">+"):
            parts = []
            while i < len(lines) and lines[i][0] > indent:
                parts.append(lines[i][1])
                i += 1
            out[key] = ("\n" if rest.startswith("|") else " ").join(parts)
            continue
        if rest:
            out[key] = _yaml_scalar(rest)
        elif i < len(lines) and lines[i][0] > indent:
            out[key], i = _yaml_block(lines, i, lines[i][0])
        elif i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
            # 与 key 同缩进的序列（YAML 允许 items 顶格挂在 key 下）
            out[key], i = _yaml_list(lines, i, indent)
        else:
            out[key] = None
    return out, i


def _yaml_list(lines: list, i: int, indent: int):
    """解析序列：`- 标量`、`- key: value`（含同项续行键）与悬挂块。"""
    out = []
    while i < len(lines):
        ind, content = lines[i]
        if ind != indent or not (content == "-" or content.startswith("- ")):
            break
        rest = content[1:].strip()
        i += 1
        # 属于本条目的后续更深缩进行范围 [i, j)
        j = i
        while j < len(lines) and lines[j][0] > indent:
            j += 1
        if not rest:
            # `-` 悬挂块（下挂映射/序列）
            item, _ = _yaml_block(lines, i, lines[i][0]) if i < j else (None, i)
            out.append(item)
            i = j
            continue
        key, kv_rest = _yaml_split_key(rest)
        if key is None:
            out.append(_yaml_scalar(rest))
            i = j
            continue
        # `- key: value` 开头的映射项：续行键的虚拟缩进 = indent + 2
        col = indent + 2
        item = {}
        if kv_rest:
            item[key] = _yaml_scalar(kv_rest)
            i += 1
        elif i < j and lines[i][0] > col:
            item[key], i = _yaml_block(lines, i, lines[i][0])
        elif i < j and lines[i][0] == col and lines[i][1].startswith("- "):
            item[key], i = _yaml_list(lines, i, col)
        else:
            item[key] = None
            i += 1 if i < j and lines[i][0] == col else 0
        # 同项其余键（缩进回到 col）
        while i < j and lines[i][0] == col and not lines[i][1].startswith("-"):
            k2, r2 = _yaml_split_key(lines[i][1])
            if k2 is None:
                break
            i += 1
            if r2:
                item[k2] = _yaml_scalar(r2)
            elif i < j and lines[i][0] > col:
                item[k2], i = _yaml_block(lines, i, lines[i][0])
            elif i < j and lines[i][0] == col and lines[i][1].startswith("- "):
                item[k2], i = _yaml_list(lines, i, col)
            else:
                item[k2] = None
        out.append(item)
        i = j
    return out, i


def _yaml_mini_load(text: str) -> dict:
    """极简 YAML 解析兜底（仅支持 OpenAPI 文档常见子集：嵌套映射/序列/标量）。"""
    lines = []
    for raw in text.splitlines():
        line = _yaml_strip_comment(raw)
        if not line.strip() or line.strip() in ("---", "..."):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if "\t" in line[:indent]:
            raise ValueError("YAML 不支持 Tab 缩进")
        lines.append((indent, line.strip()))
    if not lines:
        raise ValueError("空文档")
    if lines[0][0] != 0:
        raise ValueError("YAML 缩进异常")
    value, pos = _yaml_block(lines, 0, 0)
    if pos < len(lines):
        raise ValueError("YAML 缩进不一致，无法完整解析")
    if not isinstance(value, dict):
        raise ValueError("根节点必须是对象")
    return value


def _load_doc(content: str) -> dict:
    """文本 → dict（JSON 优先，其次 PyYAML，最后极简 YAML 兜底）。"""
    if not content or not content.strip():
        raise ApiError(400, "文件内容为空")
    if len(content.encode("utf-8", "ignore")) > MAX_DOC_BYTES:
        raise ApiError(400, "文档超过 5MB 上限")
    text = content.strip()
    try:
        return parse_doc_text(content)
    except DocParseError:
        # JSON 失败且（通常）无 PyYAML：走兜底解析
        try:
            return _yaml_mini_load(text)
        except Exception as exc:  # noqa: BLE001
            raise ApiError(
                400, "无法解析接口文档，请确认是 OpenAPI/Swagger JSON 或 YAML"
            ) from exc


_BAD_DOC_MSG = "无法解析接口文档，请确认是 OpenAPI/Swagger JSON 或 YAML"


def _parse_and_summarize(content: str, fallback_title: str) -> dict:
    """解析 + 抽取 summary；任何解析失败统一抛中文 400。"""
    doc = _load_doc(content)
    try:
        return extract_summary(doc, fallback_title=fallback_title)
    except DocParseError as exc:
        raise ApiError(400, _BAD_DOC_MSG) from exc


def _brief_summary(summary: dict) -> dict:
    """对外精简 summary（列表/详情共用）。"""
    return {
        "endpoint_count": int(summary.get("endpoint_count") or 0),
        "title": summary.get("title") or "",
        "openapi": summary.get("openapi") or "",
        "version": summary.get("version") or "",
    }


def _clean_label(label: str) -> str:
    label = str(label or "").strip() or "current"
    if len(label) > 120:
        raise ApiError(400, "标签过长（最多 120 字）")
    return label


async def _store_spec(
    db: SyncDB,
    ws_id: int,
    label: str,
    content: str,
    source_type: str,
    summary: dict,
    source_url: str = "",
) -> dict:
    """统一入库函数（paste / from-url / sync-url-l5 / yapi 共用），返回对外 item。"""
    meta = dict(summary)
    if source_url:
        meta["source_url"] = source_url
    created = now_str()
    spec_id = await db_insert(
        db,
        "ai_specs",
        {
            "ws_id": ws_id,
            "label": label,
            "source_type": source_type,
            "content_raw": content,
            "summary_json": jdump(meta),
            "created_at": created,
        },
    )
    return {
        "id": spec_id,
        "label": label,
        "created_at": created,
        "summary": _brief_summary(summary),
    }


# =============================================================================
# A3 文档 spec
# =============================================================================


@router.get("/workspaces/{ws}/specs")
async def list_specs(
    ws: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """文档快照列表（按时间倒序，仅回显精简 summary）。"""
    await require_member(ws, user, db)
    rows = await db_fetch_all(
        db,
        "SELECT id, label, created_at, summary_json FROM ai_specs"
        " WHERE ws_id=? ORDER BY id DESC",
        [ws],
    )
    items = []
    for r in rows:
        summary = jload(r.get("summary_json"), {}) or {}
        items.append(
            {
                "id": r["id"],
                "label": r.get("label") or "current",
                "created_at": r.get("created_at") or "",
                "summary": _brief_summary(summary),
            }
        )
    return {"items": items}


@router.post("/workspaces/{ws}/specs")
async def create_spec(
    ws: int,
    body: SpecCreateBody = Body(default=SpecCreateBody()),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """粘贴文本导入 OpenAPI/Swagger 文档（JSON + YAML）。"""
    await require_member(ws, user, db)
    label = _clean_label(body.label)
    content = body.content or ""
    if not content.strip():
        raise ApiError(400, "文件内容为空")
    if len(content.encode("utf-8", "ignore")) > MAX_DOC_BYTES:
        raise ApiError(400, "文档超过 5MB 上限")
    summary = _parse_and_summarize(content, fallback_title=label)
    item = await _store_spec(
        db, ws, label, content, body.source_type or "paste", summary
    )
    await audit(
        db,
        ws,
        user["id"],
        "导入接口文档",
        {"label": label, "endpoint_count": summary.get("endpoint_count")},
    )
    await db_commit(db)
    return {"item": item}


async def _fetch_text(url: str) -> str:
    """服务端抓取远端文档文本（15s 超时 / 跟随重定向 / 自定义 UA）。"""
    url = str(url or "").strip()
    if not re.match(r"^https?://", url, re.I):
        raise ApiError(400, "URL 拉取失败：仅支持 http/https 地址")
    try:
        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT, follow_redirects=True, headers=_FETCH_HEADERS
        ) as client:
            resp = await client.get(url)
    except httpx.TimeoutException as exc:
        raise ApiError(
            400, f"URL 拉取失败：请求超时（{int(FETCH_TIMEOUT)} 秒）"
        ) from exc
    except httpx.HTTPError as exc:
        raise ApiError(400, f"URL 拉取失败：{exc.__class__.__name__}") from exc
    if resp.status_code >= 400:
        raise ApiError(400, f"URL 拉取失败：HTTP {resp.status_code}")
    if len(resp.content or b"") > MAX_DOC_BYTES:
        raise ApiError(400, "文档超过 5MB 上限")
    return resp.text


@router.post("/workspaces/{ws}/specs/from-url")
async def create_spec_from_url(
    ws: int,
    body: SpecFromUrlBody = Body(default=SpecFromUrlBody()),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """从 URL 服务端抓取 OpenAPI/Swagger 文档并入库。"""
    await require_member(ws, user, db)
    label = _clean_label(body.label)
    url = str(body.url or "").strip()
    if not url:
        raise ApiError(400, "请填写文档 URL")
    content = await _fetch_text(url)
    summary = _parse_and_summarize(content, fallback_title=label)
    item = await _store_spec(db, ws, label, content, "url", summary, source_url=url)
    await audit(
        db,
        ws,
        user["id"],
        "从 URL 导入接口文档",
        {"label": label, "url": url, "endpoint_count": summary.get("endpoint_count")},
    )
    await db_commit(db)
    return {"item": item}


@router.delete("/workspaces/{ws}/specs/{snapshot_id}", status_code=204)
async def delete_spec(
    ws: int,
    snapshot_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """删除文档快照（不存在 404；成功 204）。"""
    await require_member(ws, user, db)
    row = await db_fetch_one(
        db, "SELECT id FROM ai_specs WHERE id=? AND ws_id=?", [snapshot_id, ws]
    )
    if not row:
        raise ApiError(404, "文档快照不存在")
    await db_delete(db, "ai_specs", "id=? AND ws_id=?", [snapshot_id, ws])
    await audit(db, ws, user["id"], "删除文档快照", {"snapshot_id": snapshot_id})
    await db_commit(db)
    return None


# =============================================================================
# A4 数据源（URL 同步 / YApi 导入 / 数据源列表 / 同步任务）
# =============================================================================


def _try_json(v):
    """宽容解析 JSON 文本（YApi 的 body 字段常为字符串），失败返回 None。"""
    if isinstance(v, (dict, list)):
        return v
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        return json.loads(v)
    except (json.JSONDecodeError, ValueError):
        return None


def _schema_of(val, depth: int = 0) -> dict:
    """由示例值推导极简 JSON Schema（限深，防恶意深嵌套）。"""
    if depth > 6:
        return {}
    if isinstance(val, dict):
        return {
            "type": "object",
            "properties": {
                str(k): _schema_of(v, depth + 1) for k, v in list(val.items())[:80]
            },
        }
    if isinstance(val, list):
        return {
            "type": "array",
            "items": _schema_of(val[0], depth + 1) if val else {"type": "string"},
        }
    if isinstance(val, bool):
        return {"type": "boolean"}
    if isinstance(val, int):
        return {"type": "integer"}
    if isinstance(val, float):
        return {"type": "number"}
    return {"type": "string"}


def _yapi_to_openapi(project_name: str, items: list) -> dict:
    """YApi 接口列表 → OpenAPI 3.0 dict（后续走同一个解析/入库管线）。"""
    paths: dict = {}
    for it in items:
        method = str(it.get("method") or "GET").split(",")[0].strip().lower()
        if method not in HTTP_METHODS:
            continue
        path = str(it.get("path") or "").strip()
        if not path:
            continue
        if not path.startswith("/"):
            path = "/" + path
        op: dict = {"summary": str(it.get("title") or "")[:200]}
        # query / header 参数
        params = []
        for q in it.get("req_query") or []:
            if not isinstance(q, dict) or not q.get("name"):
                continue
            entry: dict = {
                "name": str(q["name"]),
                "in": "query",
                "required": str(q.get("required")) == "1",
                "schema": {"type": "string"},
            }
            if q.get("desc"):
                entry["description"] = str(q["desc"])[:200]
            if q.get("example"):
                entry["schema"]["example"] = q["example"]
            params.append(entry)
        for h in it.get("req_headers") or []:
            if not isinstance(h, dict) or not h.get("name"):
                continue
            name = str(h["name"])
            if name.lower() == "content-type":
                continue
            entry = {
                "name": name,
                "in": "header",
                "required": str(h.get("required")) == "1",
                "schema": {"type": "string"},
            }
            if h.get("value"):
                entry["schema"]["example"] = h["value"]
            params.append(entry)
        if params:
            op["parameters"] = params
        # 请求体：表单优先，其次 JSON 文本
        form = [
            f
            for f in (it.get("req_body_form") or [])
            if isinstance(f, dict) and f.get("name")
        ]
        if form:
            schema = {
                "type": "object",
                "properties": {str(f["name"]): {"type": "string"} for f in form},
            }
            req = [str(f["name"]) for f in form if str(f.get("required")) == "1"]
            if req:
                schema["required"] = req
            op["requestBody"] = {
                "content": {"application/x-www-form-urlencoded": {"schema": schema}}
            }
        else:
            raw = it.get("req_body_json") or it.get("req_body_other") or ""
            parsed = _try_json(raw)
            if isinstance(parsed, (dict, list)):
                op["requestBody"] = {
                    "content": {
                        "application/json": {
                            "schema": _schema_of(parsed),
                            "example": parsed,
                        }
                    }
                }
        # 响应体（YApi res_body 本身就是 JSON Schema 文本）
        res = _try_json(it.get("res_body"))
        resp: dict = {"description": "成功"}
        if isinstance(res, dict):
            resp["content"] = {"application/json": {"schema": res}}
        op["responses"] = {"200": resp}
        paths.setdefault(path, {})[method] = op
    return {
        "openapi": "3.0.1",
        "info": {"title": (project_name or "YApi 导入接口")[:200], "version": "1.0.0"},
        "paths": paths,
    }


async def _yapi_get(client, base: str, path: str, params: dict) -> dict:
    """调用 YApi 接口；网络/非 JSON 一律视为地址不可达。"""
    try:
        resp = await client.get(base + path, params=params)
    except httpx.HTTPError as exc:
        raise ApiError(400, "YApi 地址无法访问") from exc
    try:
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise ApiError(400, "YApi 地址无法访问") from exc
    if not isinstance(data, dict):
        raise ApiError(400, "YApi 地址无法访问")
    if resp.status_code in (401, 403):
        raise ApiError(400, "Token 无效或无权限")
    return data


def _yapi_unwrap(data: dict, fail_msg: str):
    """errcode → data；失败按 errmsg 语义映射为精确中文错误。"""
    errcode = data.get("errcode")
    if errcode in (0, "0", None) and data.get("data") is not None:
        return data["data"]
    errmsg = str(data.get("errmsg") or "")
    low = errmsg.lower()
    # token 类：无效 / 不合法 / 无权限 / 未登录
    if (
        errcode in (4001, 40011, 40012, 40021, 40022)
        or "token" in low
        or "权限" in errmsg
        or "未登录" in errmsg
        or "unauthorized" in low
    ):
        raise ApiError(400, "Token 无效或无权限")
    # 项目类：不存在 / 未找到
    if (
        errcode in (4004, 404, 40041, -1, "-1")
        or "不存在" in errmsg
        or "not found" in low
    ):
        raise ApiError(400, "项目 ID 不存在")
    raise ApiError(400, fail_msg)


@router.post("/workspaces/{ws}/sources/sync-url-l5")
async def sync_url_l5(
    ws: int,
    body: SyncUrlL5Body = Body(default=SyncUrlL5Body()),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """L5 一键 URL 同步：抓取→解析入库→记同步任务→审计。"""
    await require_member(ws, user, db)
    label = _clean_label(body.label)
    url = str(body.url or "").strip()
    if not url:
        raise ApiError(400, "请填写文档 URL")
    try:
        content = await _fetch_text(url)
        summary = _parse_and_summarize(content, fallback_title=label)
    except ApiError:
        # 失败也记一条同步任务，供 dashboard 展示
        await record_sync_job(db, ws, user["id"], "url", label, "", 0, status="failed")
        await db_commit(db)
        raise
    snapshot = await _store_spec(db, ws, label, content, "url", summary, source_url=url)
    await record_sync_job(
        db,
        ws,
        user["id"],
        "url",
        label,
        content,
        summary.get("endpoint_count") or 0,
    )
    await audit(
        db,
        ws,
        user["id"],
        "URL 同步文档（L5）",
        {
            "url": url,
            "label": label,
            "run_change": bool(body.run_change),
            "endpoint_count": summary.get("endpoint_count"),
        },
    )
    await db_commit(db)
    return {"snapshot": snapshot}


@router.post("/workspaces/{ws}/sources/yapi/import")
async def import_yapi(
    ws: int,
    body: YapiImportBody = Body(default=YapiImportBody()),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """YApi 项目导入：project/get → list_menu → interface/get，组装 OpenAPI 后入库。"""
    await require_member(ws, user, db)
    label = _clean_label(body.label)
    base = str(body.base_url or "").strip().rstrip("/")
    if not re.match(r"^https?://", base, re.I):
        raise ApiError(400, "YApi 地址无法访问")
    project_id = str(body.project_id or "").strip()
    if not project_id:
        raise ApiError(400, "请填写 YApi 项目 ID")
    token = str(body.token or "").strip()
    if not token:
        raise ApiError(400, "请填写 YApi 项目 Token")

    async with httpx.AsyncClient(
        timeout=FETCH_TIMEOUT, follow_redirects=True, headers=_FETCH_HEADERS
    ) as client:
        # 1) 项目信息：验证地址可达与 token 有效
        proj = await _yapi_get(
            client, base, "/api/project/get", {"id": project_id, "token": token}
        )
        pdata = _yapi_unwrap(proj, "项目 ID 不存在")
        project_name = ""
        if isinstance(pdata, dict):
            inner = pdata.get("project")
            project_name = str(
                (inner or {}).get("name")
                if isinstance(inner, dict)
                else pdata.get("name") or ""
            )
        # 2) 接口菜单（分类树）
        menu = await _yapi_get(
            client,
            base,
            "/api/interface/list_menu",
            {"project_id": project_id, "token": token},
        )
        menu_data = _yapi_unwrap(menu, "该项目下没有可用接口")
        ids: list = []

        def _collect(nodes) -> None:
            for node in nodes if isinstance(nodes, list) else []:
                if not isinstance(node, dict):
                    continue
                children = node.get("list") or node.get("children")
                if isinstance(children, list) and children:
                    _collect(children)
                else:
                    iid = node.get("id") or node.get("_id")
                    if iid:
                        ids.append(iid)

        _collect(menu_data)
        ids = ids[:200]  # 服务端逐个拉取，单次最多导入 200 个接口
        if not ids:
            raise ApiError(400, "该项目下没有可用接口")
        # 3) 逐个拉取接口详情（单个失败跳过，不影响整体）
        details: list = []
        for iid in ids:
            try:
                one = await _yapi_get(
                    client, base, "/api/interface/get", {"id": iid, "token": token}
                )
                if one.get("errcode") in (0, "0", None) and isinstance(
                    one.get("data"), dict
                ):
                    details.append(one["data"])
            except ApiError:
                continue
    if not details:
        raise ApiError(400, "该项目下没有可用接口")
    doc = _yapi_to_openapi(project_name, details)
    content = jdump(doc)
    summary = _parse_and_summarize(content, fallback_title=project_name or label)
    item = await _store_spec(
        db,
        ws,
        label,
        content,
        "url",
        summary,
        source_url=f"{base}/project/{project_id}",
    )
    await record_sync_job(
        db,
        ws,
        user["id"],
        "yapi",
        label,
        content,
        summary.get("endpoint_count") or 0,
    )
    await audit(
        db,
        ws,
        user["id"],
        "导入 YApi 项目",
        {
            "project_id": project_id,
            "interface_count": len(details),
            "endpoint_count": summary.get("endpoint_count"),
        },
    )
    await db_commit(db)
    return {"item": item}


@router.get("/workspaces/{ws}/sources")
async def list_sources(
    ws: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """数据源列表：由 source_type=url 的文档快照派生（无独立表）。"""
    await require_member(ws, user, db)
    rows = await db_fetch_all(
        db,
        "SELECT id, label, created_at, summary_json FROM ai_specs"
        " WHERE ws_id=? AND source_type='url' ORDER BY id DESC",
        [ws],
    )
    items = []
    for r in rows:
        s = jload(r.get("summary_json"), {}) or {}
        items.append(
            {
                "id": r["id"],
                "label": r.get("label") or "current",
                "url": s.get("source_url") or "",
                "endpoint_count": int(s.get("endpoint_count") or 0),
                "created_at": r.get("created_at") or "",
            }
        )
    return {"items": items}


@router.get("/workspaces/{ws}/sources/sync-jobs")
async def list_sources_sync_jobs(
    ws: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """近期文档同步任务（common.list_sync_jobs，job_type=sync）。"""
    await require_member(ws, user, db)
    jobs = await list_sync_jobs(db, ws)
    return {
        "items": [
            {
                "status": j.get("status") or "",
                "created_at": j.get("created_at") or "",
                "patch_fingerprint": j.get("patch_fingerprint") or "",
            }
            for j in jobs
        ]
    }


# =============================================================================
# A5 命中记录（hits）
# =============================================================================

# `METHOD /path`：支持日志、表格、pytest 参数化（分隔符含 _ / -），可带域名前缀
_RE_METHOD_PATH = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS|TRACE)"
    r"[\s_:/+\-]+"
    r"(?:https?://[^/\s]+)?"
    r"(/[^\s\"'|<>)\],;]*)",
    re.I,
)
# pytest 节点 id：tests/test_a.py::test_b[param]
_RE_PYTEST = re.compile(r"[\w\-./\\]+\.py(?:::[\w\-\[\]<>=%@,.()]+)+")
# coverage 报告路径：coverage.xml / htmlcov/... 等
_RE_COV_FILE = re.compile(
    r"[\w\-./\\]*(?:htmlcov[\w\-./\\]*|\.coverage[\w\-./\\]*|coverage\.(?:xml|json|txt))",
    re.I,
)


def _parse_hits_text(content: str) -> dict:
    """从文本提取命中：METHOD /path 行、pytest 节点 id、coverage 报告路径。

    hit_count = 命中条目总数（method+path 按归一化 key 聚合计数，
    pytest 节点与报告文件各计一条）。
    """
    key_counts: dict = {}
    order: list = []
    node_count = 0
    file_count = 0
    for line in content.splitlines():
        if not line.strip():
            continue
        found = False
        for m in _RE_METHOD_PATH.finditer(line):
            method = m.group(1).upper()
            path = norm_path(m.group(2).rstrip(".,;:)]'\""))
            key = f"{method} {path}"
            if key not in key_counts:
                key_counts[key] = 0
                order.append(key)
            key_counts[key] += 1
            found = True
        if found:
            continue
        if _RE_PYTEST.search(line):
            node_count += 1
            continue
        if _RE_COV_FILE.search(line):
            file_count += 1
    hit_count = sum(key_counts.values()) + node_count + file_count
    return {
        "hit_count": hit_count,
        "unique": len(order),
        "keys": order[:3000],
        "node_count": node_count,
        "file_count": file_count,
    }


@router.get("/workspaces/{ws}/hits")
async def list_hits(
    ws: int,
    limit: int = 50,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """命中导入记录列表（倒序）。"""
    await require_member(ws, user, db)
    limit = max(1, min(int(limit or 50), 200))
    rows = await db_fetch_all(
        db,
        "SELECT id, summary_json, created_at FROM ai_hits"
        " WHERE ws_id=? ORDER BY id DESC LIMIT ?",
        [ws, limit],
    )
    items = []
    for r in rows:
        s = jload(r.get("summary_json"), {}) or {}
        items.append(
            {
                "id": r["id"],
                "hit_count": int(s.get("hit_count") or 0),
                "created_at": r.get("created_at") or "",
            }
        )
    return {"items": items}


@router.post("/workspaces/{ws}/hits")
async def create_hits(
    ws: int,
    body: HitsCreateBody = Body(default=HitsCreateBody()),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """粘贴命中文本（访问日志 / pytest 输出 / 覆盖率报告），解析后入库。"""
    await require_member(ws, user, db)
    content = body.content or ""
    if not content.strip():
        raise ApiError(400, "命中内容为空")
    if len(content.encode("utf-8", "ignore")) > MAX_DOC_BYTES:
        raise ApiError(400, "内容超过 5MB 上限")
    summary = _parse_hits_text(content)
    if (
        not summary["keys"]
        and not summary["node_count"]
        and not summary["file_count"]
    ):
        raise ApiError(
            400,
            "未解析到任何命中记录（支持 METHOD /path 行、pytest 节点 id、coverage 报告路径）",
        )
    created = now_str()
    hit_id = await db_insert(
        db,
        "ai_hits",
        {
            "ws_id": ws,
            "content_raw": content,
            "summary_json": jdump(summary),
            "created_at": created,
        },
    )
    await audit(
        db,
        ws,
        user["id"],
        "导入命中记录",
        {"hit_count": summary["hit_count"], "unique": summary["unique"]},
    )
    await db_commit(db)
    return {
        "item": {
            "id": hit_id,
            "hit_count": summary["hit_count"],
            "created_at": created,
        }
    }


@router.delete("/workspaces/{ws}/hits/{hit_id}", status_code=204)
async def delete_hit(
    ws: int,
    hit_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """删除命中记录（不存在 404；成功 204）。"""
    await require_member(ws, user, db)
    row = await db_fetch_one(
        db, "SELECT id FROM ai_hits WHERE id=? AND ws_id=?", [hit_id, ws]
    )
    if not row:
        raise ApiError(404, "命中记录不存在")
    await db_delete(db, "ai_hits", "id=? AND ws_id=?", [hit_id, ws])
    await audit(db, ws, user["id"], "删除命中记录", {"hit_id": hit_id})
    await db_commit(db)
    return None


# =============================================================================
# A6 覆盖率对照（文档端点集 vs 命中路径集）
# =============================================================================


def _path_match(hit_path: str, spec_path: str) -> bool:
    """段级通配匹配：{id}/:id/数字段已归一为 *，* 匹配任意单段。"""
    hs = [s for s in (hit_path or "").split("/") if s]
    ss = [s for s in (spec_path or "").split("/") if s]
    if len(hs) != len(ss):
        return False
    return all(a == b or a == "*" or b == "*" for a, b in zip(hs, ss))


def _report_public(row: dict) -> dict:
    """覆盖率报告对外形状（列表/详情共用）。"""
    return {
        "id": row["id"],
        "spec_id": row.get("spec_id"),
        "hit_id": row.get("hit_id"),
        "created_at": row.get("created_at") or "",
        "summary": jload(row.get("summary_json"), {}) or {},
        "gaps": jload(row.get("gaps_json"), {}) or {"missing": [], "ghost": []},
    }


@router.post("/workspaces/{ws}/coverage/analyze")
async def coverage_analyze(
    ws: int,
    body: CoverageAnalyzeBody = Body(default=CoverageAnalyzeBody()),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """真实对照：文档端点集合 vs 命中路径集合，产出缺口报告并入库。"""
    ws_row = await require_member(ws, user, db)
    spec_id = int(body.spec_id or 0)
    hit_id = int(body.hit_id or 0)
    if spec_id <= 0 or hit_id <= 0:
        raise ApiError(400, "请先选择文档快照与命中记录")
    spec_row = await db_fetch_one(
        db, "SELECT * FROM ai_specs WHERE id=? AND ws_id=?", [spec_id, ws]
    )
    if not spec_row:
        raise ApiError(400, "文档快照不存在，请重新选择")
    hit_row = await db_fetch_one(
        db, "SELECT * FROM ai_hits WHERE id=? AND ws_id=?", [hit_id, ws]
    )
    if not hit_row:
        raise ApiError(400, "命中记录不存在，请重新选择")

    # 文档端点集（去重 + 过滤健康检查类噪声）
    endpoints = await spec_endpoints_of(db, spec_id, ws)
    core_map = (ws_row.get("settings") or {}).get("endpoint_core") or {}
    spec_eps: list = []
    seen: set = set()
    for ep in endpoints:
        method = str(ep.get("method") or "").upper()
        p = str(ep.get("path_norm") or "") or norm_path(str(ep.get("path") or ""))
        if not method or not p:
            continue
        key = f"{method} {p}"
        if key in seen:
            continue
        seen.add(key)
        if is_ignored_endpoint(method, p):
            continue
        spec_eps.append((method, p, key))

    # 命中路径集（norm 归一后的 METHOD path）
    hit_summary = jload(hit_row.get("summary_json"), {}) or {}
    hit_eps: list = []
    for k in hit_summary.get("keys") or []:
        m, _, p = str(k).strip().partition(" ")
        if not m or not p:
            continue
        hit_eps.append((m.upper(), norm_path(p)))

    covered = 0
    missing: list = []
    for method, p, key in spec_eps:
        if any(hm == method and _path_match(hp, p) for hm, hp in hit_eps):
            covered += 1
        else:
            missing.append({"key": key, "core": bool(core_map.get(key))})
    ghost: list = []
    for hm, hp in hit_eps:
        if is_ignored_endpoint(hm, hp):
            continue
        if not any(sm == hm and _path_match(hp, sp) for sm, sp, _ in spec_eps):
            ghost.append({"key": f"{hm} {hp}"})

    spec_count = len(spec_eps)
    summary = {
        "spec_count": spec_count,
        "hit_unique": len(set(hit_eps)),
        "covered": covered,
        "coverage_rate": round(covered / spec_count, 4) if spec_count else 0.0,
        "missing": len(missing),
        "ghost": len(ghost),
        "core_missing": sum(1 for x in missing if x["core"]),
        "label": str(spec_row.get("label") or "current"),
    }
    gaps = {"missing": missing[:500], "ghost": ghost[:500]}
    created = now_str()
    report_id = await db_insert(
        db,
        "ai_coverage_reports",
        {
            "ws_id": ws,
            "spec_id": spec_id,
            "hit_id": hit_id,
            "summary_json": jdump(summary),
            "gaps_json": jdump(gaps),
            "created_at": created,
        },
    )
    await audit(
        db,
        ws,
        user["id"],
        "生成覆盖率报告",
        {"spec_id": spec_id, "hit_id": hit_id, "coverage_rate": summary["coverage_rate"]},
    )
    await db_commit(db)
    return {
        "report": {
            "id": report_id,
            "created_at": created,
            "summary": summary,
            "gaps": gaps,
        }
    }


@router.get("/workspaces/{ws}/coverage/latest")
async def coverage_latest(
    ws: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """最新一份覆盖率报告；无则 {report: null}。"""
    await require_member(ws, user, db)
    row = await db_fetch_one(
        db,
        "SELECT * FROM ai_coverage_reports WHERE ws_id=? ORDER BY id DESC LIMIT 1",
        [ws],
    )
    return {"report": _report_public(row) if row else None}


@router.get("/workspaces/{ws}/coverage")
async def list_coverage(
    ws: int,
    limit: int = 20,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """覆盖率报告历史列表（倒序）。"""
    await require_member(ws, user, db)
    limit = max(1, min(int(limit or 20), 100))
    rows = await db_fetch_all(
        db,
        "SELECT id, summary_json, created_at FROM ai_coverage_reports"
        " WHERE ws_id=? ORDER BY id DESC LIMIT ?",
        [ws, limit],
    )
    items = []
    for r in rows:
        s = jload(r.get("summary_json"), {}) or {}
        items.append(
            {
                "id": r["id"],
                "label": s.get("label") or "覆盖率报告",
                "created_at": r.get("created_at") or "",
            }
        )
    return {"items": items}


@router.get("/workspaces/{ws}/coverage/{report_id}")
async def get_coverage(
    ws: int,
    report_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """单份覆盖率报告详情。"""
    await require_member(ws, user, db)
    row = await db_fetch_one(
        db,
        "SELECT * FROM ai_coverage_reports WHERE id=? AND ws_id=?",
        [report_id, ws],
    )
    if not row:
        raise ApiError(404, "覆盖率报告不存在")
    return {"report": _report_public(row)}


# =============================================================================
# A8 新旧快照变更（前端 UI 已下线，仅保留 API 面）
# =============================================================================


@router.get("/workspaces/{ws}/changes/latest")
async def changes_latest(
    ws: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """最新变更报告：功能已下线，恒返回 null。"""
    await require_member(ws, user, db)
    return {"report": None}


@router.get("/workspaces/{ws}/changes")
async def list_changes(
    ws: int,
    limit: int = 20,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """变更报告列表：功能已下线，恒返回空列表。"""
    await require_member(ws, user, db)
    return {"items": []}


# =============================================================================
# 代码体检 / 门禁 / 业务流 / 导出 / 平台
# 这些能力在当前版 UI 中已下线（DOM 位于 .api-intel-compat-hidden 兼容块），
# 但案例前端首屏仍会并发调用，因此必须存在且返回结构正确的空数据，避免 404 噪音。
# =============================================================================


@router.get("/workspaces/{ws}/code-review/latest")
async def code_review_latest(
    ws: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """最新代码体检报告：功能未启用，恒返回 null。"""
    await require_member(ws, user, db)
    return {"report": None}


@router.get("/workspaces/{ws}/code-reviews")
async def list_code_reviews(
    ws: int,
    limit: int = 20,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """代码体检历史列表：功能未启用，恒返回空列表。"""
    await require_member(ws, user, db)
    return {"items": []}


@router.get("/workspaces/{ws}/code-reviews/{report_id}")
async def get_code_review(
    ws: int,
    report_id: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """单个代码体检报告：功能未启用。"""
    await require_member(ws, user, db)
    raise ApiError(404, "代码体检功能当前未启用")


@router.post("/workspaces/{ws}/code-review")
async def run_code_review(
    ws: int,
    body: dict = Body(default={}),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """提交代码体检：功能未启用。"""
    await require_member(ws, user, db)
    raise ApiError(400, "代码体检功能当前未启用，请使用本机 Agent 在执行台验证")


@router.post("/workspaces/{ws}/code-review/zip")
async def run_code_review_zip(
    ws: int,
    body: dict = Body(default={}),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """上传 zip 体检：功能未启用。"""
    await require_member(ws, user, db)
    raise ApiError(400, "zip 体检当前未启用；企业场景请使用本机 Agent")


@router.get("/workspaces/{ws}/gate")
async def get_gate(
    ws: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """质量门禁结论：暂无变更报告与覆盖报告时给出中性结论。"""
    await require_member(ws, user, db)
    return {
        "gate": {
            "verdict": "unknown",
            "label": "暂无门禁结论",
            "reasons": [],
            "reason_items": [],
            "change_report_id": None,
            "change_report_at": None,
            "coverage_report_id": None,
            "coverage_report_at": None,
            "code_review_id": None,
            "code_review_at": None,
            "coverage_note": "",
        }
    }


@router.get("/workspaces/{ws}/flows/latest")
async def flows_latest(
    ws: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """最新业务流报告：功能未启用，恒返回 null。"""
    await require_member(ws, user, db)
    return {"report": None}


@router.post("/workspaces/{ws}/flows/analyze")
async def flows_analyze(
    ws: int,
    body: dict = Body(default={}),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """业务流分析：功能未启用。"""
    await require_member(ws, user, db)
    raise ApiError(400, "业务流分析当前未启用")


@router.get("/workspaces/{ws}/code-index/latest")
async def code_index_latest(
    ws: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """代码索引：由本机 Agent 侧维护，云端不存源码。"""
    await require_member(ws, user, db)
    return {"index": None}


@router.get("/workspaces/{ws}/runs")
async def list_runs(
    ws: int,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """历史运行汇总：直接复用 edge 运行任务列表。"""
    await require_member(ws, user, db)
    rows = await db_fetch_all(
        db,
        "SELECT id, status, created_at, summary_json FROM ai_run_jobs "
        "WHERE ws_id=? AND job_type='run' ORDER BY id DESC LIMIT 20",
        [ws],
    )
    return {
        "items": [
            {
                "id": r["id"],
                "status": r["status"],
                "created_at": r["created_at"],
                "summary": jload(r["summary_json"], {}),
            }
            for r in rows
        ]
    }


@router.get("/workspaces/{ws}/exports/{kind}")
async def export_report(
    ws: int,
    kind: str,
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """报告导出：按 kind 输出 csv / json / markdown，数据源为最新覆盖率与对照结果。"""
    import csv as _csv
    import io as _io

    from fastapi.responses import PlainTextResponse

    await require_member(ws, user, db)
    maps = await db_fetch_all(
        db,
        "SELECT method, path_norm, coverage_state, test_node_id, test_file, source "
        "FROM ai_endpoint_map WHERE ws_id=? ORDER BY path_norm",
        [ws],
    )
    rows = [
        {
            "方法": m["method"],
            "路径": m["path_norm"],
            "状态": m["coverage_state"],
            "测试": m["test_node_id"] or m["test_file"] or "",
            "来源": m["source"] or "",
        }
        for m in maps
    ]

    if kind.endswith(".csv"):
        buf = _io.StringIO()
        writer = _csv.DictWriter(buf, fieldnames=["方法", "路径", "状态", "测试", "来源"])
        writer.writeheader()
        writer.writerows(rows)
        return PlainTextResponse(
            "\ufeff" + buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{kind}.csv"'},
        )
    if kind.endswith(".md"):
        lines = ["# 接口对照导出", "", "| 方法 | 路径 | 状态 | 测试 | 来源 |", "| --- | --- | --- | --- | --- |"]
        lines += [
            f"| {r['方法']} | `{r['路径']}` | {r['状态']} | {r['测试']} | {r['来源']} |" for r in rows
        ]
        return PlainTextResponse(
            "\n".join(lines),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{kind}.md"'},
        )
    return {"workspace_id": ws, "kind": kind, "exported_at": now_str(), "items": rows}


@router.post("/workspaces/{ws}/changes/{report_id}/ack")
async def ack_change(
    ws: int,
    report_id: int,
    body: dict = Body(default={}),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """确认高风险变更：功能未启用，返回中性门禁。"""
    await require_member(ws, user, db)
    return {"gate": {"verdict": "unknown", "label": "暂无门禁结论", "reasons": []}}


@router.post("/workspaces/{ws}/changes/{report_id}/unack")
async def unack_change(
    ws: int,
    report_id: int,
    body: dict = Body(default={}),
    user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """取消确认变更：功能未启用，返回中性门禁。"""
    await require_member(ws, user, db)
    return {"gate": {"verdict": "unknown", "label": "暂无门禁结论", "reasons": []}}
