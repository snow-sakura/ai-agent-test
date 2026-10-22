"""接口智能（api-intel）内部共享工具。

统一约定：
- 错误响应统一为 {"error": "中文提示"}（HTTPException 由 main.py 中注册的
  专用 exception handler 对 /api/api-intel 路径做转换）。
- 时间统一输出 "%Y-%m-%d %H:%M:%S" 字符串，前端直接展示。
- 工作空间按 owner/member 鉴权，非成员 403，不存在 404。
"""

import json
import re
from datetime import datetime
from typing import Any, Optional

from app.core.database import SyncDB, db_fetch_all, db_fetch_one, db_insert, db_update

# 统一时间格式（前端直接展示，不做二次解析）
TIME_FMT = "%Y-%m-%d %H:%M:%S"


def now_str() -> str:
    """当前时间字符串（本地时间）。"""
    return datetime.now().strftime(TIME_FMT)


def parse_dt(s: Optional[str]) -> Optional[datetime]:
    """解析 "%Y-%m-%d %H:%M:%S" 字符串，失败返回 None。"""
    if not s:
        return None
    try:
        return datetime.strptime(str(s), TIME_FMT)
    except (ValueError, TypeError):
        return None


class ApiError(Exception):
    """业务异常：状态码 + 中文错误提示。由 main.py 注册的 handler 统一转 {"error": msg}。"""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


def jload(s: Any, default: Any = None) -> Any:
    """安全解析 JSON 字符串字段（settings_json/summary_json 等）。"""
    if s is None or isinstance(s, (dict, list)):
        return s if s is not None else default
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError, ValueError):
        return default


def jdump(v: Any) -> str:
    return json.dumps(v if v is not None else {}, ensure_ascii=False)


# =============================================================================
# 工作空间鉴权
# =============================================================================


async def get_ws_or_404(ws_id: int, db: SyncDB) -> dict:
    ws = await db_fetch_one(db, "SELECT * FROM ai_ws WHERE id=?", [ws_id])
    if not ws:
        raise ApiError(404, "工作空间不存在")
    ws["settings"] = jload(ws.get("settings_json"), {}) or {}
    return ws


async def require_member(ws_id: int, user: dict, db: SyncDB) -> dict:
    """当前用户必须是该空间成员；返回带 role/settings 的空间行。"""
    ws = await get_ws_or_404(ws_id, db)
    if int(ws["owner_id"]) == int(user["id"]):
        ws["my_role"] = "owner"
        return ws
    m = await db_fetch_one(
        db,
        "SELECT * FROM ai_ws_members WHERE ws_id=? AND user_id=?",
        [ws_id, user["id"]],
    )
    if not m:
        raise ApiError(403, "无权访问该工作空间")
    ws["my_role"] = m["role"] or "member"
    return ws


async def require_owner(ws_id: int, user: dict, db: SyncDB) -> dict:
    """仅 owner 可操作（写审计/删除/成员管理前置校验用）。"""
    ws = await require_member(ws_id, user, db)
    if ws["my_role"] != "owner":
        raise ApiError(403, "仅工作空间所有者可执行此操作")
    return ws


async def audit(
    db: SyncDB, ws_id: int, user_id: Optional[int], action: str, detail: Any = None
):
    """写审计流水（所有写操作都要调用）。"""
    await db_insert(
        db,
        "ai_audit",
        {
            "ws_id": ws_id,
            "user_id": user_id,
            "action": action,
            "detail_json": jdump(detail or {}),
            "created_at": now_str(),
        },
    )


# =============================================================================
# 运行配置（run_profile）公共读写
# =============================================================================

DEFAULT_PROFILE = {"project_root": "", "entry_file": "run.py", "python_cmd": "python"}

_BAD_CMD_CHARS = re.compile(r"[;&|`$]|\$\(|&&")


async def get_profile(db: SyncDB, ws_id: int) -> dict:
    row = await db_fetch_one(db, "SELECT * FROM ai_run_profiles WHERE ws_id=?", [ws_id])
    if not row:
        return dict(DEFAULT_PROFILE)
    return {
        "project_root": row.get("project_root") or "",
        "entry_file": row.get("entry_file") or "run.py",
        "python_cmd": row.get("python_cmd") or "python",
    }


def validate_profile(profile: dict) -> dict:
    """服务端二次校验（前端已校验一遍，防御直连调用）。"""
    root = str(profile.get("project_root") or "").strip()
    entry = str(profile.get("entry_file") or "run.py").strip()
    py = str(profile.get("python_cmd") or "python").strip() or "python"

    if len(root) > 1024:
        raise ApiError(400, "项目路径过长")
    if root and not (
        root.startswith("/")
        or root.startswith("~")
        or re.match(r"^[A-Za-z]:[\\/]", root)
        or re.match(r"^\\\\", root)
    ):
        raise ApiError(400, "项目路径须为本机绝对路径")

    if not entry:
        raise ApiError(400, "请填写入口文件，例如 run.py")
    if len(entry) > 256:
        raise ApiError(400, "入口文件路径过长")
    if entry.startswith("/") or entry.startswith("\\") or entry.startswith("//"):
        raise ApiError(400, "入口文件须为相对项目根的路径")
    if ".." in entry.replace("\\", "/").split("/"):
        raise ApiError(400, "入口文件路径非法")
    if not entry.lower().endswith(".py"):
        raise ApiError(400, "入口文件须为 .py")
    if _BAD_CMD_CHARS.search(entry):
        raise ApiError(400, "入口文件含非法字符")

    if len(py) > 512:
        raise ApiError(400, "Python 路径过长")
    if _BAD_CMD_CHARS.search(py):
        raise ApiError(400, "Python 路径含非法字符")

    return {"project_root": root, "entry_file": entry, "python_cmd": py}


async def save_profile(db: SyncDB, ws_id: int, profile: dict):
    payload = validate_profile(profile)
    now = now_str()
    exists = await db_fetch_one(
        db, "SELECT ws_id FROM ai_run_profiles WHERE ws_id=?", [ws_id]
    )
    if exists:
        await db_update(
            db,
            "ai_run_profiles",
            {
                "project_root": payload["project_root"],
                "entry_file": payload["entry_file"],
                "python_cmd": payload["python_cmd"],
                "updated_at": now,
            },
            "ws_id=?",
            [ws_id],
        )
    else:
        await db_insert(
            db,
            "ai_run_profiles",
            {
                "ws_id": ws_id,
                "project_root": payload["project_root"],
                "entry_file": payload["entry_file"],
                "python_cmd": payload["python_cmd"],
                "updated_at": now,
            },
        )
    return payload


# =============================================================================
# OpenAPI / Swagger 解析（服务端解析，前端零解析）
# =============================================================================

HTTP_METHODS = ("get", "post", "put", "delete", "patch", "head", "options", "trace")

# 对照时视为「忽略」的公共/健康检查类前缀
IGNORE_PATH_PREFIXES = (
    "/health",
    "/healthz",
    "/metrics",
    "/ping",
    "/docs",
    "/redoc",
    "/openapi",
    "/swagger",
    "/static",
    "/favicon",
    "/version",
)


class DocParseError(Exception):
    """OpenAPI 文档解析失败（由调用方转 400）。"""


def parse_doc_text(content: str) -> dict:
    """解析 OpenAPI/Swagger 文本（JSON 或 YAML），返回原始 dict。"""
    if not content or not content.strip():
        raise DocParseError("文档内容为空")
    if len(content) > 8 * 1024 * 1024:
        raise DocParseError("文档过大（超过 8MB），请拆分后上传")
    text = content.strip()
    doc = None
    try:
        doc = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        try:
            import yaml  # venv 已带 PyYAML

            doc = yaml.safe_load(text)
        except Exception as e:  # noqa: BLE001
            raise DocParseError(f"无法解析为 JSON/YAML：{e}")
    if not isinstance(doc, dict):
        raise DocParseError("文档根节点必须是对象")
    return doc


def norm_path(p: str) -> str:
    """路径归一化：去查询串/域名；占位符 {x}/:x/数字段 → *；合并多余斜杠。"""
    p = (p or "").split("?")[0].split("#")[0].strip()
    # 完整 URL → 取 path 部分
    m = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://[^/]+(/.*)?$", p)
    if m:
        # 完整 URL 只取 path 部分；无 path 时归为 "/"
        p = m.group(1) or "/"
    p = re.sub(r"\{[^{}]*\}", "*", p)
    p = re.sub(r"/:[A-Za-z_][A-Za-z0-9_]*", "/*", p)
    p = re.sub(r"/\d+(?=/|$)", "/*", p)
    p = re.sub(r"/{2,}", "/", p)
    while len(p) > 1 and p.endswith("/"):
        p = p[:-1]
    if not p:
        p = "/"
    if not p.startswith("/"):
        p = "/" + p
    return p


def extract_summary(doc: dict, fallback_title: str = "") -> dict:
    """从 OpenAPI/Swagger 文档抽取 {title, version, openapi, endpoint_count, endpoints[]}。"""
    paths = doc.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise DocParseError(
            "缺少 paths 字段或接口列表为空，请确认为 OpenAPI/Swagger 文档"
        )
    info = doc.get("info")
    if not isinstance(info, dict):
        info = {}
    endpoints = []
    for p, ops in paths.items():
        if not isinstance(ops, dict):
            continue
        for m in HTTP_METHODS:
            op = ops.get(m)
            if not isinstance(op, dict):
                continue
            endpoints.append(
                {
                    "method": m.upper(),
                    "path": str(p),
                    "path_norm": norm_path(str(p)),
                    "summary": str(op.get("summary") or op.get("description") or "")[
                        :200
                    ],
                    "key": f"{m.upper()} {norm_path(str(p))}",
                }
            )
    return {
        "title": str(info.get("title") or fallback_title or "")[:200],
        "version": str(info.get("version") or "")[:60],
        "openapi": str(doc.get("openapi") or doc.get("swagger") or ""),
        "endpoint_count": len(endpoints),
        "endpoints": endpoints[:3000],
    }


def parse_openapi_content(content: str, fallback_title: str = "") -> dict:
    """解析 + 抽取一步到位；DocParseError 转 ApiError(400)。"""
    try:
        doc = parse_doc_text(content)
        return extract_summary(doc, fallback_title)
    except DocParseError as e:
        raise ApiError(400, f"文档解析失败：{e}")


def is_ignored_endpoint(method: str, path_norm: str) -> bool:
    if (method or "").upper() in ("HEAD", "OPTIONS"):
        return True
    lp = (path_norm or "/").lower()
    return any(
        lp == pre or lp.startswith(pre + "/") or lp.startswith(pre)
        for pre in IGNORE_PATH_PREFIXES
    )


# =============================================================================
# 运行任务公共读取
# =============================================================================


async def load_job_or_404(db: SyncDB, ws_id: int, job_id: str) -> dict:
    job = await db_fetch_one(
        db, "SELECT * FROM ai_run_jobs WHERE id=? AND ws_id=?", [job_id, ws_id]
    )
    if not job:
        raise ApiError(404, "运行任务不存在")
    job["summary"] = jload(job.get("summary_json"), {}) or {}
    return job


def job_public(job: dict, created_by_label: str = "") -> dict:
    """任务对外形状（列表/详情共用）。"""
    return {
        "id": job["id"],
        "ws_id": job["ws_id"],
        "device_id": job.get("device_id") or "",
        "job_type": job.get("job_type") or "run",
        "status": job.get("status") or "queued",
        "created_by": job.get("created_by"),
        "created_by_label": created_by_label,
        "created_at": job.get("created_at") or "",
        "started_at": job.get("started_at") or "",
        "finished_at": job.get("finished_at") or "",
        "finished": (job.get("status") or "") in ("succeeded", "failed", "cancelled"),
        "summary": jload(job.get("summary_json"), {}) or {},
        "exit_code": job.get("exit_code"),
    }


async def job_label_map(db: SyncDB, jobs: list) -> dict:
    """批量取创建人展示名 {user_id: label}。"""
    ids = sorted(
        {int(j["created_by"]) for j in jobs if j.get("created_by") is not None}
    )
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = await db_fetch_all(
        db,
        f"SELECT id, username, full_name, email FROM users WHERE id IN ({marks})",
        ids,
    )
    out = {}
    for r in rows:
        out[int(r["id"])] = (
            r.get("full_name")
            or r.get("username")
            or (r.get("email") or "").split("@")[0]
        )
    return out


async def list_sync_jobs(db: SyncDB, ws_id: int, limit: int = 20) -> list:
    """近期中/文档同步任务（job_type=sync）。"""
    rows = await db_fetch_all(
        db,
        "SELECT * FROM ai_run_jobs WHERE ws_id=? AND job_type='sync' ORDER BY id DESC LIMIT ?",
        [ws_id, limit],
    )
    items = []
    for r in rows:
        s = jload(r.get("summary_json"), {}) or {}
        items.append(
            {
                "id": r["id"],
                "status": r.get("status") or "",
                "created_at": r.get("created_at") or "",
                "patch_fingerprint": s.get("patch_fingerprint") or "",
                "label": s.get("label") or "",
                "source": s.get("source") or "",
                "endpoint_count": s.get("endpoint_count"),
            }
        )
    return items


async def record_sync_job(
    db: SyncDB,
    ws_id: int,
    user_id: Optional[int],
    source: str,
    label: str,
    content: str,
    endpoint_count: int,
    status: str = "succeeded",
):
    """文档同步成功后落一条 sync 任务（供 dashboard.recent_syncs 消费）。"""
    import hashlib
    import uuid as _uuid

    fp = hashlib.sha1((content or "").encode("utf-8", "ignore")).hexdigest()[:16]
    await db_insert(
        db,
        "ai_run_jobs",
        {
            "id": str(_uuid.uuid4()),
            "ws_id": ws_id,
            "device_id": None,
            "job_type": "sync",
            "status": status,
            "created_by": user_id,
            "created_at": now_str(),
            "started_at": now_str(),
            "finished_at": now_str(),
            "summary_json": jdump(
                {
                    "patch_fingerprint": fp,
                    "label": label,
                    "source": source,
                    "endpoint_count": endpoint_count,
                }
            ),
            "exit_code": 0,
        },
    )
    return fp


async def spec_endpoints_of(db: SyncDB, spec_id: int, ws_id: int) -> list:
    """读取某个 spec 的端点列表（对照/覆盖共用）。"""
    row = await db_fetch_one(
        db, "SELECT * FROM ai_specs WHERE id=? AND ws_id=?", [spec_id, ws_id]
    )
    if not row:
        return []
    summary = jload(row.get("summary_json"), {}) or {}
    return summary.get("endpoints") or []
