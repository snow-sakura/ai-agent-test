"""AI测试平台 - 主路由

数据库层改为同步 sqlite3 + asyncio.to_thread 模式（SyncDB），
避免 Python 3.14 不支持 greenlet 的问题。
"""

import asyncio
import io
import json as _json
import os
import re
import sys
import base64 as _base64
import urllib.parse as _urlparse
from datetime import datetime, timedelta
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.core.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ADMIN_PASSWORD,
    APP_NAME,
    APP_VERSION,
    CORS_ORIGINS,
    DEMO_ACCOUNT,
    DEMO_ACCOUNT_PUBLIC,
    DEMO_PASSWORD,
)
from app.core.database import (
    SyncDB,
    db_commit,
    db_delete,
    db_fetch_all,
    db_fetch_one,
    db_insert,
    db_update,
    get_db,
    init_db,
)
from app.core.deps import get_current_user
from app.core.security import (
    create_access_token,
    get_password_hash,
    verify_password,
)

app = FastAPI(title=APP_NAME, version=APP_VERSION, description="AI驱动的智能测试平台")

# 接口智能(api-testing)遗留路由（仅 /api/api-testing/health）
from app.api.api_testing import router as api_testing_router  # noqa: E402

app.include_router(api_testing_router)

# 接口智能（api-intel）：完整复刻版路由，统一前缀 /api/api-intel
from app.api.api_intel import router as api_intel_router  # noqa: E402
from app.api.api_intel.common import ApiError  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402


@app.exception_handler(ApiError)
async def _api_intel_error_handler(_request, exc: ApiError):
    """接口智能业务异常统一出口：{"error": "中文提示"}，与案例站前端约定一致。"""
    return JSONResponse(status_code=exc.status_code, content={"error": exc.message})


app.include_router(api_intel_router)

# 用例/缺陷/需求（SyncDB，可用）
from app.api.case_management import router as case_management_router  # noqa: E402
from app.api.bug_management import router as bug_management_router  # noqa: E402
from app.api.requirement_management import router as requirement_management_router  # noqa: E402

app.include_router(case_management_router, prefix="/api")
app.include_router(bug_management_router, prefix="/api")
app.include_router(requirement_management_router, prefix="/api")

# 新域路由（骨架已建，各域并行实现；路径不含 /api 前缀）
from app.api.prompts import router as _r_prompts  # noqa: E402
from app.api.knowledge import router as _r_knowledge  # noqa: E402
from app.api.performance import router as _r_performance  # noqa: E402
from app.api.api_suite import router as _r_api_suite  # noqa: E402
from app.api.security_testing import router as _r_security  # noqa: E402
from app.api.pentest import router as _r_pentest  # noqa: E402
from app.api.ui_automation import router as _r_ui_auto  # noqa: E402
from app.api.app_automation_ui import router as _r_app_auto_ui  # noqa: E402
from app.api.data_factory import router as _r_data_factory  # noqa: E402
from app.api.skill_library import router as _r_skill_library  # noqa: E402
from app.api.skills_center import router as _r_skills_center  # noqa: E402
from app.api.assistant import router as _r_assistant  # noqa: E402
from app.api.agents import router as _r_agents  # noqa: E402
from app.api.workflows import router as _r_workflows  # noqa: E402
from app.api.reports import router as _r_reports  # noqa: E402
from app.api.root_cause import router as _r_root_cause  # noqa: E402
from app.api.token_usage import router as _r_token_usage  # noqa: E402
from app.api.deai import router as _r_deai  # noqa: E402
from app.api.config_center import router as _r_config_center  # noqa: E402
from app.api.scheduler import router as _r_scheduler  # noqa: E402
from app.api.logs import router as _r_logs  # noqa: E402
from app.api.mcp_center import router as _r_mcp_center  # noqa: E402
from app.api.scenario import router as _r_scenario  # noqa: E402
from app.api.gen_queue import router as _r_gen_queue  # noqa: E402

for _r in (
    _r_prompts,
    _r_knowledge,
    _r_performance,
    _r_api_suite,
    _r_security,
    _r_pentest,
    _r_ui_auto,
    _r_app_auto_ui,
    _r_data_factory,
    _r_skill_library,
    _r_skills_center,
    _r_assistant,
    _r_agents,
    _r_workflows,
    _r_reports,
    _r_root_cause,
    _r_token_usage,
    _r_deai,
    _r_config_center,
    _r_scheduler,
    _r_logs,
    _r_mcp_center,
    _r_scenario,
    _r_gen_queue,
):
    app.include_router(_r, prefix="/api")

# APP 自动化:仅挂载 api_core 中不依赖 async ORM 的文件系统路由
# (元素截图模板上传 / 图片分类 / 媒体文件)。
# api_core 其余路由基于 app.app_automation.models(async SQLAlchemy mapper),
# 而本项目 DB 层为纯 sqlite3 兼容占位(Base/AsyncSession 为空类),这些 ORM 路由
# 全部 500,故一律不挂载;elements 的增删查已由 app_automation_ui.py 以 SyncDB 实现。
from fastapi import APIRouter  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402

from app.app_automation.api_core import router as _r_app_auto_core  # noqa: E402

_CORE_FS_PATHS = {
    "/app-automation/media",
    "/app-automation/elements/upload",
    "/app-automation/elements/image-categories",
    "/app-automation/elements/image-categories/create",
    "/app-automation/elements/image-categories/{name}",
}
_r_app_auto_fs = APIRouter()
_r_app_auto_fs.routes.extend(
    _r
    for _r in _r_app_auto_core.routes
    if isinstance(_r, APIRoute) and _r.path in _CORE_FS_PATHS
)
app.include_router(_r_app_auto_fs, prefix="/api")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer()


# ============ Auth Routes ============


@app.post("/api/auth/register")
async def register(
    username: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    password: str = Form(...),
    db: SyncDB = Depends(get_db),
):
    account = (username or phone or "").strip()
    if not account:
        raise HTTPException(status_code=400, detail="用户名或手机号不能为空")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码至少需要 6 位")

    normalized_username = account
    normalized_phone = phone.strip() if phone else ""
    normalized_email = email.strip() if email else ""
    if not normalized_email:
        normalized_email = f"{normalized_phone or normalized_username}@local.testhub"

    if normalized_phone:
        existing = await db_fetch_one(
            db,
            "SELECT id FROM users WHERE username=? OR phone=?",
            [normalized_username, normalized_phone],
        )
    else:
        existing = await db_fetch_one(
            db,
            "SELECT id FROM users WHERE username=?",
            [normalized_username],
        )
    if existing:
        raise HTTPException(status_code=400, detail="用户名或手机号已存在")

    existing_email = await db_fetch_one(
        db,
        "SELECT id FROM users WHERE email=?",
        [normalized_email],
    )
    if existing_email:
        raise HTTPException(status_code=400, detail="邮箱已存在")

    # 查找或创建 tester 角色
    role = await db_fetch_one(db, "SELECT id FROM roles WHERE name=?", ["tester"])
    if not role:
        role_id = await db_insert(
            db,
            "roles",
            {
                "name": "tester",
                "description": "Tester role",
                "permissions": _json.dumps(["read", "write"]),
            },
        )
    else:
        role_id = role["id"]

    user_id = await db_insert(
        db,
        "users",
        {
            "username": normalized_username,
            "phone": normalized_phone or None,
            "email": normalized_email,
            "hashed_password": get_password_hash(password),
            "role_id": role_id,
        },
    )

    return {"message": "User created successfully", "user_id": user_id}


@app.post("/api/auth/login")
async def login(
    username: str = Form(""),
    phone: str = Form(""),
    password: str = Form(...),
    db: SyncDB = Depends(get_db),
):
    account = (username or phone or "").strip()
    if not account:
        raise HTTPException(status_code=400, detail="请输入账号")

    token_user = await db_fetch_one(
        db,
        "SELECT * FROM users WHERE username=? OR phone=?",
        [account, account],
    )

    if not token_user or not verify_password(password, token_user["hashed_password"]):
        raise HTTPException(status_code=401, detail="账号或密码不正确")

    access_token = create_access_token(
        data={"sub": str(token_user["id"])},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": token_user["id"],
            "username": token_user["username"],
            "email": token_user.get("email"),
            "full_name": token_user.get("full_name"),
        },
    }


@app.get("/api/config/demo-account")
async def demo_account():
    """登录页「一键填充」用：回显服务端种子的演示账号（无需登录）。

    仓库源码不含任何真实个人信息：演示账号默认 demo_tester / Demo@2026，
    真实（或个人）账号通过 backend/.env 的 DEMO_ACCOUNT / DEMO_PASSWORD 注入，
    生产部署把 DEMO_ACCOUNT_PUBLIC 置 0 直接关闭本接口。
    """
    if not DEMO_ACCOUNT_PUBLIC:
        raise HTTPException(status_code=404, detail="演示账号未开放")
    return {"account": DEMO_ACCOUNT, "password": DEMO_PASSWORD}


@app.get("/api/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "id": current_user["id"],
        "username": current_user["username"],
        "email": current_user["email"],
        "full_name": current_user.get("full_name"),
    }


# ============ Project Routes ============


@app.get("/api/projects")
async def list_projects(
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    rows = await db_fetch_all(
        db,
        "SELECT id, name, description FROM projects WHERE owner_id=?",
        [current_user["id"]],
    )
    return rows


@app.post("/api/projects")
async def create_project(
    name: str = Form(...),
    description: str = Form(""),
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    project_id = await db_insert(
        db,
        "projects",
        {
            "name": name,
            "description": description,
            "owner_id": current_user["id"],
        },
    )
    return {"id": project_id, "name": name}


@app.get("/api/projects/{project_id}")
async def get_project(
    project_id: int,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    project = await db_fetch_one(
        db,
        "SELECT id, name, description FROM projects WHERE id=? AND owner_id=?",
        [project_id, current_user["id"]],
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.put("/api/projects/{project_id}")
async def update_project(
    project_id: int,
    name: str = Form(...),
    description: str = Form(""),
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    project = await db_fetch_one(
        db,
        "SELECT id FROM projects WHERE id=? AND owner_id=?",
        [project_id, current_user["id"]],
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await db_update(
        db,
        "projects",
        {"name": name, "description": description},
        "id=?",
        [project_id],
    )
    return {"id": project_id, "name": name, "description": description}


@app.delete("/api/projects/{project_id}")
async def delete_project(
    project_id: int,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    project = await db_fetch_one(
        db,
        "SELECT id FROM projects WHERE id=? AND owner_id=?",
        [project_id, current_user["id"]],
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await db_delete(db, "projects", "id=?", [project_id])
    return {"message": "Project deleted"}


# ============ Test Case Routes ============


@app.get("/api/projects/{project_id}/test-cases")
async def list_test_cases(
    project_id: int,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    rows = await db_fetch_all(
        db,
        "SELECT id, title, type, priority, status FROM test_cases WHERE project_id=?",
        [project_id],
    )
    return rows


@app.post("/api/projects/{project_id}/test-cases")
async def create_test_case(
    project_id: int,
    title: str = Form(...),
    description: str = Form(""),
    type: str = Form("functional"),
    priority: str = Form("P1"),
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    case_id = await db_insert(
        db,
        "test_cases",
        {
            "project_id": project_id,
            "title": title,
            "description": description,
            "type": type,
            "priority": priority,
            "status": "draft",
            "steps": _json.dumps([]),
        },
    )
    return {"id": case_id, "title": title}


# ============ AI Config Routes ============


@app.get("/api/ai-configs")
async def list_ai_configs(
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    rows = await db_fetch_all(
        db,
        "SELECT id, name, supplier, model_name, is_default FROM ai_configs ORDER BY id",
    )
    return rows


@app.post("/api/ai-configs")
async def create_ai_config(
    name: str = Form(...),
    supplier: str = Form(...),
    model_name: str = Form(...),
    api_key: str = Form(...),
    base_url: str = Form(""),
    is_default: bool = Form(False),
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    if is_default:
        # 清除其它默认标记
        all_configs = await db_fetch_all(db, "SELECT id FROM ai_configs")
        for c in all_configs:
            await db_update(db, "ai_configs", {"is_default": 0}, "id=?", [c["id"]])

    config_id = await db_insert(
        db,
        "ai_configs",
        {
            "name": name,
            "supplier": supplier,
            "model_name": model_name,
            "api_key": api_key,
            "base_url": base_url,
            "is_default": 1 if is_default else 0,
        },
    )
    return {"id": config_id, "name": name}


@app.put("/api/ai-configs/{config_id}")
async def update_ai_config(
    config_id: int,
    name: str = Form(...),
    supplier: str = Form(...),
    model_name: str = Form(...),
    api_key: str = Form(""),
    base_url: str = Form(""),
    is_default: bool = Form(False),
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    config = await db_fetch_one(db, "SELECT id FROM ai_configs WHERE id=?", [config_id])
    if not config:
        raise HTTPException(status_code=404, detail="AI 配置不存在")

    update_data = {
        "name": name,
        "supplier": supplier,
        "model_name": model_name,
        "base_url": base_url,
        "is_default": 1 if is_default else 0,
    }
    if api_key:  # 留空表示不修改密钥
        update_data["api_key"] = api_key

    if is_default:
        others = await db_fetch_all(
            db, "SELECT id FROM ai_configs WHERE id!=?", [config_id]
        )
        for o in others:
            await db_update(db, "ai_configs", {"is_default": 0}, "id=?", [o["id"]])

    await db_update(db, "ai_configs", update_data, "id=?", [config_id])
    return {"id": config_id, "name": name}


@app.delete("/api/ai-configs/{config_id}")
async def delete_ai_config(
    config_id: int,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    config = await db_fetch_one(
        db, "SELECT id, is_default FROM ai_configs WHERE id=?", [config_id]
    )
    if not config:
        raise HTTPException(status_code=404, detail="AI 配置不存在")
    was_default = bool(config["is_default"])
    await db_delete(db, "ai_configs", "id=?", [config_id])
    # 删除默认配置后，顺延第一个为默认
    if was_default:
        first = await db_fetch_one(
            db, "SELECT id FROM ai_configs ORDER BY id ASC LIMIT 1"
        )
        if first:
            await db_update(db, "ai_configs", {"is_default": 1}, "id=?", [first["id"]])
    return {"ok": True}


@app.post("/api/ai-configs/{config_id}/set-default")
async def set_default_ai_config(
    config_id: int,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    config = await db_fetch_one(db, "SELECT id FROM ai_configs WHERE id=?", [config_id])
    if not config:
        raise HTTPException(status_code=404, detail="AI 配置不存在")
    others = await db_fetch_all(
        db, "SELECT id FROM ai_configs WHERE id!=?", [config_id]
    )
    for o in others:
        await db_update(db, "ai_configs", {"is_default": 0}, "id=?", [o["id"]])
    await db_update(db, "ai_configs", {"is_default": 1}, "id=?", [config_id])
    return {"ok": True}


@app.post("/api/ai-configs/{config_id}/test")
async def test_ai_config(
    config_id: int,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """连通性测试：向该配置的模型发送一次最小补全请求。"""
    config = await db_fetch_one(db, "SELECT * FROM ai_configs WHERE id=?", [config_id])
    if not config:
        raise HTTPException(status_code=404, detail="AI 配置不存在")
    base_url = (config.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    url = (
        base_url
        if base_url.endswith("/chat/completions")
        else base_url + "/chat/completions"
    )
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                url,
                json={
                    "model": config["model_name"],
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 5,
                },
                headers={"Authorization": f"Bearer {config['api_key']}"},
            )
        if resp.status_code == 200:
            data = resp.json()
            reply = ""
            try:
                reply = (data["choices"][0]["message"].get("content") or "")[:50]
            except Exception:
                pass
            return {
                "ok": True,
                "message": f"连接成功{('，模型回复：' + reply) if reply else ''}",
            }
        return {"ok": False, "message": f"HTTP {resp.status_code}：{resp.text[:160]}"}
    except Exception as err:  # noqa: BLE001
        return {"ok": False, "message": f"连接失败：{err}"}


# ============ Health Check ============


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "version": APP_VERSION}


# ============ Doc Tools · AI 编辑助手（SSE 流式） ============


class DocToolsChatMessage(BaseModel):
    role: str
    text: str


class DocToolsChatRequest(BaseModel):
    message: str
    table_matrix: List[List[str]] = []
    conversation_history: List[DocToolsChatMessage] = []


DOC_TOOLS_SYSTEM_PROMPT = (
    "你是智能编辑工具中的 AI 表格编辑助手。用户会上传一个表格（以矩阵形式提供，第一行通常是表头），"
    "并通过自然语言描述希望进行的编辑操作。\n"
    "你的任务：根据用户指令处理表格矩阵，并按以下 JSON 格式返回结果（不要输出多余说明文字）：\n"
    '{"summary": "一句话描述你做了什么", "matrix": [["A1", "B1"], ["A2", "B2"]]}\n'
    "要求：\n"
    "1. matrix 必须是二维数组，每行列数必须一致，且与处理后的表格对应。\n"
    "2. 若用户只是提问而非要求修改表格，可只返回 summary（此时 matrix 可省略或为空数组）。\n"
    "3. 保持未被编辑的单元格内容不变。日期、数字按原样保留为字符串。"
)


def _matrix_preview(matrix, max_rows=30, max_cols=20):
    rows = matrix[:max_rows]
    lines = []
    for row in rows:
        cells = [str(c if c is not None else "")[:80] for c in row[:max_cols]]
        lines.append(" | ".join(cells))
    if len(matrix) > max_rows:
        lines.append(f"...（共 {len(matrix)} 行，已截断）")
    return "\n".join(lines)


async def _pick_ai_config(db: SyncDB) -> Optional[dict]:
    """获取 AI 配置：优先默认且已配置 Key 的，其次任意有 Key 的，最后才回退无 Key。
    （避免多个 is_default=1 时按 id 选中无 Key 配置导致 400。）"""
    return await db_fetch_one(
        db,
        """
        SELECT * FROM ai_configs
        ORDER BY
          CASE WHEN is_default=1 AND COALESCE(api_key,'')!='' THEN 0
               WHEN COALESCE(api_key,'')!='' THEN 1
               ELSE 2 END,
          is_default DESC, id ASC
        LIMIT 1
        """,
    )


def _sse_block(payload: dict) -> str:
    return "data: " + _json.dumps(payload, ensure_ascii=False) + "\n\n"


async def _sse_log_ai(
    *,
    module: str,
    model: str,
    prompt: str,
    assistant_text: str,
    started: float,
    in_tokens: int,
    status: str = "成功",
    body: str = "",
) -> None:
    """SSE 流式端点的用量埋点。

    注意：StreamingResponse 场景下 Depends(get_db) 会在流开始前
    teardown（连接已关闭），这里必须自建独立连接写库。
    """
    from app.core.database import SyncDB as _SyncDB
    from app.core.database import _get_conn as _get_conn_local
    from app.services import telemetry as _telemetry

    _conn = _get_conn_local()
    try:
        await _telemetry.log_ai(
            _SyncDB(_conn),
            module=module,
            model=model,
            prompt_content=(prompt or "")[:200],
            input_tokens=in_tokens,
            output_tokens=_telemetry.estimate_tokens(assistant_text),
            duration_ms=_telemetry.elapsed_ms(started),
            status=status,
            body=body or assistant_text[:500],
        )
    except Exception as _err:  # noqa: BLE001
        print(f"[{module}] 埋点写入失败: {type(_err).__name__}: {_err}", flush=True)
    finally:
        _conn.close()


# ---------------------------------------------------------------------------
# SSE 裸 httpx 直连的 429/5xx 自动重试（与 services/ai.py 保持一致策略）
# ---------------------------------------------------------------------------

_SSE_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_SSE_MAX_RETRIES = 2
_SSE_RETRY_BASE_DELAY = 1.5


class _AIStreamError(Exception):
    """裸 httpx 流式请求失败（已耗尽重试）。"""

    def __init__(self, status_code: int, detail: str, body: str = ""):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.body = body


async def _open_ai_stream(
    url: str,
    payload: dict,
    headers: dict,
    *,
    module: str,
    timeout: float = 300,
):
    """带重试打开 AI 流式连接；返回 (client, resp)，调用方负责 close。

    429/500/502/503/504 与网络错误自动重试（指数退避 1.5s→3s，最多 2 次）；
    其他非 200 或重试耗尽时抛 _AIStreamError（含可读 detail 与原始 body）。
    """
    last_exc: Optional[_AIStreamError] = None
    for attempt in range(_SSE_MAX_RETRIES + 1):
        client = httpx.AsyncClient(timeout=timeout)
        try:
            req = client.build_request("POST", url, json=payload, headers=headers)
            resp = await client.send(req, stream=True)
            if resp.status_code == 200:
                return client, resp
            body_bytes = await resp.aread()
            body_text = body_bytes.decode("utf-8", errors="replace")
            detail = f"AI 请求失败: HTTP {resp.status_code}"
            try:
                err = _json.loads(body_text)
                detail = "AI 请求失败: " + str(
                    err.get("error", {}).get("message") or err.get("detail") or detail
                )
            except Exception:
                pass
            last_exc = _AIStreamError(resp.status_code, detail, body_text[:500])
            retryable = resp.status_code in _SSE_RETRYABLE_STATUS
            await resp.aclose()
            await client.aclose()
            if retryable and attempt < _SSE_MAX_RETRIES:
                delay = _SSE_RETRY_BASE_DELAY * (2**attempt)
                print(
                    f"[{module}] AI 流式 HTTP {resp.status_code}，{delay:.1f}s 后重试"
                    f"（第 {attempt + 1}/{_SSE_MAX_RETRIES} 次）",
                    flush=True,
                )
                await asyncio.sleep(delay)
                continue
            raise last_exc
        except _AIStreamError:
            raise
        except Exception as exc:  # noqa: BLE001 — 网络层错误
            await client.aclose()
            if attempt < _SSE_MAX_RETRIES:
                delay = _SSE_RETRY_BASE_DELAY * (2**attempt)
                print(
                    f"[{module}] AI 流式连接失败，{delay:.1f}s 后重试"
                    f"（第 {attempt + 1}/{_SSE_MAX_RETRIES} 次）: {type(exc).__name__}",
                    flush=True,
                )
                await asyncio.sleep(delay)
                continue
            raise _AIStreamError(
                0, f"AI 请求失败: {type(exc).__name__}: {exc}"
            ) from exc
    if last_exc is not None:
        raise last_exc
    raise _AIStreamError(0, "AI 请求失败: 未知错误")


# ---------------------------------------------------------------------------
# 流式停滞看门狗：慢模型(免费额度限速)可能中途无数据挂死，导致前端永远等不到终止帧。
# 连续 idle_s 秒无任何 SSE 行 → 返回 _IDLE_MARK 哨兵，上层收敛流并按已收内容做截断修复。
# ---------------------------------------------------------------------------

_STREAM_IDLE_SECONDS = 75.0
# 唯一对象哨兵：不可能与模型输出的字符串内容冲突
_IDLE_MARK = object()


async def _iter_idle_timeout(lines, idle_s: float = _STREAM_IDLE_SECONDS):
    """包一层「空闲超时」的异步行迭代器；超时空闲 yield _IDLE_MARK 后结束。"""
    it = lines.__aiter__()
    while True:
        try:
            item = await asyncio.wait_for(it.__anext__(), timeout=idle_s)
        except StopAsyncIteration:
            return
        except (asyncio.TimeoutError, TimeoutError):
            yield _IDLE_MARK
            return
        yield item


def _extract_json_matrix(text: str):
    """从 AI 回复中提取 {"summary": ..., "matrix": [[...]]}。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = _json.loads(cleaned[start : end + 1])
    except Exception:
        return None
    matrix = data.get("matrix")
    if matrix is not None and not (
        isinstance(matrix, list) and all(isinstance(r, list) for r in matrix)
    ):
        return None
    return data


@app.post("/api/doc-tools/chat/stream")
async def doc_tools_chat_stream(
    req: DocToolsChatRequest,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    config = await _pick_ai_config(db)
    if config is None or not config.get("api_key") or not config.get("model_name"):
        raise HTTPException(
            status_code=400,
            detail="请先在账户菜单中配置个人文本 AI 模型（Base URL、API Key、Model）",
        )

    base_url = (config["base_url"] or "https://api.openai.com/v1").rstrip("/")
    if not base_url.endswith("/chat/completions"):
        url = base_url + "/chat/completions"
    else:
        url = base_url

    messages = [{"role": "system", "content": DOC_TOOLS_SYSTEM_PROMPT}]
    for h in req.conversation_history[-10:]:
        role = "assistant" if h.role == "assistant" else "user"
        messages.append({"role": role, "content": h.text})
    messages.append(
        {
            "role": "user",
            "content": (
                f"当前表格矩阵（{len(req.table_matrix)} 行）：\n"
                f"{_matrix_preview(req.table_matrix)}\n\n"
                f"请执行以下编辑操作：{req.message}"
            ),
        }
    )

    payload = {
        "model": config["model_name"],
        "messages": messages,
        "stream": True,
        "temperature": 0.3,
    }
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }

    async def event_stream():
        from app.services import telemetry as _telemetry

        assistant_text = ""
        started = _telemetry.time.monotonic()
        in_tokens = _telemetry.estimate_tokens(
            _json.dumps(messages, ensure_ascii=False)
        )

        async def _log(status: str, body: str = "") -> None:
            await _sse_log_ai(
                module="文档编辑",
                model=str(config.get("model_name") or ""),
                prompt=req.message or "",
                assistant_text=assistant_text,
                started=started,
                in_tokens=in_tokens,
                status=status,
                body=body,
            )

        try:
            client, resp = await _open_ai_stream(
                url, payload, headers, module="文档编辑", timeout=300
            )
            try:
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        data = _json.loads(chunk)
                    except Exception:
                        continue
                    choices = data.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    reasoning = delta.get("reasoning_content")
                    if reasoning:
                        yield _sse_block(
                            {"type": "reasoning", "content": str(reasoning)}
                        )
                    if content:
                        assistant_text += str(content)
                        yield _sse_block({"type": "content", "delta": str(content)})
            finally:
                await resp.aclose()
                await client.aclose()

            parsed = _extract_json_matrix(assistant_text)
            if parsed and parsed.get("matrix"):
                matrix = [
                    [str(c if c is not None else "") for c in row]
                    for row in parsed["matrix"]
                ]
                await _log("成功")
                yield _sse_block(
                    {
                        "type": "done",
                        "success": True,
                        "summary": str(parsed.get("summary") or "已完成智能编辑"),
                        "matrix": matrix,
                    }
                )
            else:
                await _log("成功", assistant_text[:500])
                yield _sse_block(
                    {
                        "type": "done",
                        "success": True,
                        "summary": assistant_text.strip() or "AI 未返回有效表格数据",
                    }
                )
        except Exception as err:  # noqa: BLE001
            await _log("失败", str(err)[:300])
            yield _sse_block({"type": "error", "error": str(err) or "AI 请求失败"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ============ JMeter 压测工作台 · AI 助手（SSE 流式） ============


class JmStudioChatMessage(BaseModel):
    role: str
    text: str


class JmStudioChatRequest(BaseModel):
    message: str
    current_yaml: str = ""
    conversation_history: List[JmStudioChatMessage] = []


JM_STUDIO_SYSTEM_PROMPT = (
    "你是压测造数工作台中的 AI 助手。工作台当前的场景 YAML(可能为空)会提供给你,"
    "用户通过自然语言描述压测需求(接口、方法、参数、并发、时长、断言等)。\n"
    "你的任务:输出完整的场景 YAML。格式要求(严格遵守):\n"
    "name: 场景名\n"
    "env: staging\n"
    "layout: scenario\n"
    "execution_mode: visual\n"
    "serialize_threadgroups: true\n"
    "thread_groups:\n"
    "  - name: 线程组名\n"
    "    load:\n"
    "      users: 2\n"
    "      spawn_rate: 1\n"
    "      duration_sec: 60\n"
    "      loops: -1\n"
    "    steps:\n"
    "      - type: catalog_element\n"
    "        name: HTTP 请求\n"
    "        enabled: true\n"
    "        alias: HTTPSamplerProxy\n"
    "        testclass: HTTPSamplerProxy\n"
    "        guiclass: HttpTestSampleGui\n"
    "        category: sampler\n"
    "        label_zh: HTTP 请求\n"
    "        container: false\n"
    "        scope: unified\n"
    "        catalog_props:\n"
    "          method: GET\n"
    "          protocol: https\n"
    "          domain: api.example.com\n"
    "          path: /v1/users\n"
    "可用 alias:ConfigTestElement(HTTP请求默认值,category=config)、HeaderManager(config)、"
    "CookieManager(config)、CacheManager(config)、CSVDataSet(config)、CounterConfig(config)、"
    "HTTPSamplerProxy(sampler)、JSR223PreProcessor(pre)、BeanShellPreProcessor(pre)、"
    "JSR223PostProcessor(post)、DebugPostProcessor(post)、JSONPostProcessor(post)、RegexExtractor(post)、"
    "ResponseAssertion(assertion)、DurationAssertion(assertion)、JSONPathAssertion(assertion)、"
    "ConstantTimer(timer)、UniformRandomTimer(timer)、ConstantThroughputTimer(timer)、"
    "IfController(controller,container=true)、LoopController(controller,container=true)、"
    "TransactionController(controller,container=true)、ResultCollector(listener)、Summariser(listener)、"
    "BackendListener(listener)。\n"
    "仅回答问题不需要修改场景时,直接用文字回答,不要输出 YAML。"
)


@app.post("/api/jm-studio/chat/stream")
async def jm_studio_chat_stream(
    req: JmStudioChatRequest,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    config = await _pick_ai_config(db)
    if config is None or not config.get("api_key") or not config.get("model_name"):
        raise HTTPException(
            status_code=400,
            detail="请先在账户菜单中配置个人文本 AI 模型（Base URL、API Key、Model）",
        )

    base_url = (config["base_url"] or "https://api.openai.com/v1").rstrip("/")
    url = (
        base_url
        if base_url.endswith("/chat/completions")
        else base_url + "/chat/completions"
    )

    messages = [{"role": "system", "content": JM_STUDIO_SYSTEM_PROMPT}]
    for h in req.conversation_history[-10:]:
        role = "assistant" if h.role == "assistant" else "user"
        messages.append({"role": role, "content": h.text})
    current = req.current_yaml.strip() or "(当前场景为空)"
    messages.append(
        {
            "role": "user",
            "content": f"当前场景 YAML:\n```yaml\n{current[:6000]}\n```\n\n需求:{req.message}",
        }
    )

    payload = {
        "model": config["model_name"],
        "messages": messages,
        "stream": True,
        "temperature": 0.3,
    }
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }

    async def jm_event_stream():
        from app.services import telemetry as _telemetry

        assistant_text = ""
        started = _telemetry.time.monotonic()
        in_tokens = _telemetry.estimate_tokens(
            _json.dumps(messages, ensure_ascii=False)
        )

        async def _log(status: str, body: str = "") -> None:
            await _sse_log_ai(
                module="JMeter助手",
                model=str(config.get("model_name") or ""),
                prompt=req.message or "",
                assistant_text=assistant_text,
                started=started,
                in_tokens=in_tokens,
                status=status,
                body=body,
            )

        try:
            client, resp = await _open_ai_stream(
                url, payload, headers, module="JMeter助手", timeout=300
            )
            try:
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        data = _json.loads(chunk)
                    except Exception:
                        continue
                    choices = data.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    if delta.get("reasoning_content"):
                        yield _sse_block(
                            {
                                "type": "reasoning",
                                "content": str(delta["reasoning_content"]),
                            }
                        )
                    if delta.get("content"):
                        assistant_text += str(delta["content"])
                        yield _sse_block(
                            {"type": "content", "delta": str(delta["content"])}
                        )
            finally:
                await resp.aclose()
                await client.aclose()

            yaml_text = _extract_yaml_block(assistant_text)
            if yaml_text and "thread_groups" in yaml_text:
                await _log("成功")
                yield _sse_block(
                    {
                        "type": "done",
                        "success": True,
                        "summary": _extract_yaml_summary(assistant_text)
                        or "已生成场景 YAML",
                        "yaml": yaml_text,
                    }
                )
            else:
                await _log("成功", assistant_text[:500])
                yield _sse_block(
                    {
                        "type": "done",
                        "success": False,
                        "summary": assistant_text.strip() or "AI 未返回有效 YAML",
                    }
                )
        except Exception as err:  # noqa: BLE001
            await _log("失败", str(err)[:300])
            yield _sse_block({"type": "error", "error": str(err) or "AI 请求失败"})

    return StreamingResponse(
        jm_event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _extract_yaml_block(text: str) -> str:
    """从 AI 回复中提取 ```yaml 代码块或裸 YAML。"""
    m = re.search(r"```(?:ya?ml)?\s*\n([\s\S]*?)```", text)
    if m:
        return m.group(1).strip()
    if "thread_groups" in text:
        lines = text.strip().split("\n")
        start = next(
            (
                i
                for i, l in enumerate(lines)
                if l.strip().startswith(("name:", "env:", "layout:", "thread_groups:"))
            ),
            -1,
        )
        if start >= 0:
            return "\n".join(lines[start:]).strip()
    return ""


def _extract_yaml_summary(text: str) -> str:
    m = re.search(r"(?:摘要|说明|总结)[::]\s*(.+)", text)
    return m.group(1).strip()[:120] if m else ""


# Init DB on startup
@app.on_event("startup")
async def startup():
    await init_db()
    # 遥测表 + 演示账号种子
    try:
        from app.core.security import get_password_hash as _gph
        from app.services.telemetry import ensure_schema_sync
        from app.core.database import _get_conn as _gconn

        _conn = _gconn()
        try:
            ensure_schema_sync(_conn)
            cur = _conn.cursor()
            # 平台管理员（口令取 ADMIN_PASSWORD，默认 admin123）
            cur.execute("SELECT id FROM users WHERE username=?", ["admin"])
            if not cur.fetchone():
                role_row = cur.execute(
                    "SELECT id FROM roles WHERE name=?", ["admin"]
                ).fetchone()
                if not role_row:
                    cur.execute(
                        "INSERT INTO roles (name, description, permissions, created_at) VALUES (?,?,?,?)",
                        (
                            "admin",
                            "Administrator",
                            '["read","write","admin"]',
                            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        ),
                    )
                    role_id = cur.lastrowid
                else:
                    role_id = role_row[0]
                cur.execute(
                    "INSERT INTO users (username, email, hashed_password, full_name, is_active, role_id, created_at) VALUES (?,?,?,?,1,?,?)",
                    (
                        "admin",
                        "admin@local.testhub",
                        _gph(ADMIN_PASSWORD),
                        "平台管理员",
                        role_id,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
            # 演示账号（登录页一键填充，账号/口令取 DEMO_ACCOUNT / DEMO_PASSWORD）
            cur.execute(
                "SELECT id FROM users WHERE username=? OR phone=?",
                [DEMO_ACCOUNT, DEMO_ACCOUNT],
            )
            if not cur.fetchone():
                role_row = cur.execute(
                    "SELECT id FROM roles WHERE name=?", ["tester"]
                ).fetchone()
                if not role_row:
                    cur.execute(
                        "INSERT INTO roles (name, description, permissions, created_at) VALUES (?,?,?,?)",
                        (
                            "tester",
                            "Tester",
                            '["read","write"]',
                            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        ),
                    )
                    role_id = cur.lastrowid
                else:
                    role_id = role_row[0]
                # 账号形如手机号时同时写入 phone 列（支持手机号登录），否则留 NULL
                _demo_phone = DEMO_ACCOUNT if DEMO_ACCOUNT.isdigit() else None
                cur.execute(
                    "INSERT INTO users (username, phone, email, hashed_password, full_name, is_active, role_id, created_at) VALUES (?,?,?,?,?,1,?,?)",
                    (
                        DEMO_ACCOUNT,
                        _demo_phone,
                        "demo@local.testhub",
                        _gph(DEMO_PASSWORD),
                        "演示用户",
                        role_id,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
            _conn.commit()
        finally:
            _conn.close()
        print(
            "[auth] 种子账号就绪: admin, %s（口令见 ADMIN_PASSWORD / DEMO_PASSWORD，"
            "可用 backend/.env 覆盖；演示填充见 GET /api/config/demo-account）"
            % DEMO_ACCOUNT
        )
    except Exception as e:
        print(f"⚠️ 遥测/种子账号初始化失败: {e}")
    # 启动 APP 自动化定时任务调度器（旧 async 实现已卸载，保留兼容）
    try:
        from app.app_automation.engine.scheduler import scheduler

        await scheduler.start()
    except Exception as e:
        print(f"⚠️ APP定时调度器启动失败: {e}")

    # 启动「接口智能」内置本机 Agent 模拟器：设备心跳 + 定时运行巡检
    try:
        from app.api.api_intel.agent_sim import start_background_loops

        start_background_loops()
    except Exception as e:
        print(f"⚠️ 接口智能 Agent 后台循环启动失败: {e}")


# ============ 媒体与数据工具箱 · 工具接口 ============


from fastapi.responses import Response  # noqa: E402, F811


class SimpleConvertRequest(BaseModel):
    action: str = "encode"
    text: str = ""
    plus: Optional[bool] = None
    json: Optional[str] = None


@app.post("/api/base64-converter")
async def base64_converter(req: SimpleConvertRequest):
    text = req.text or ""
    try:
        if req.action == "decode":
            if not text.strip():
                return {"error": "请输入要解码的 Base64"}
            result = _base64.b64decode(text.replace("\n", "").replace(" ", "")).decode(
                "utf-8"
            )
        else:
            if not text:
                return {"error": "请输入要编码的文本"}
            result = _base64.b64encode(text.encode("utf-8")).decode("ascii")
        return {"result": result}
    except Exception:
        return {"error": "Base64 解码失败,请检查输入是否有效"}


@app.post("/api/url-converter")
async def url_converter(req: SimpleConvertRequest):
    text = req.text or ""
    if not text:
        return {"error": "请输入内容"}
    try:
        if req.action == "decode":
            t = text.replace("+", "%20") if req.plus else text
            result = _urlparse.unquote(t, errors="strict")
        else:
            if req.plus:
                result = _urlparse.quote_plus(text, safe="")
            else:
                result = _urlparse.quote(text, safe="/:?&=%#+-._~!$'()*,;@")
        return {"result": result}
    except Exception:
        return {"error": "URL 解码失败,请检查输入是否为有效的编码文本"}


@app.post("/api/json-formatter")
async def json_formatter(req: SimpleConvertRequest):
    raw = req.json if req.json is not None else req.text
    if not raw or not raw.strip():
        return {"error": "请输入 JSON 内容"}
    try:
        obj = _json.loads(raw)
        return {"result": _json.dumps(obj, ensure_ascii=False, indent=2)}
    except Exception as e:
        return {"error": f"JSON 语法错误: {e}"}


def _quality_param(quality: Optional[int]) -> int:
    try:
        q = int(quality) if quality is not None else 85
    except (TypeError, ValueError):
        q = 85
    return max(10, min(100, q))


def _save_image(img, fmt: str, quality: Optional[int]) -> bytes:
    buf = io.BytesIO()
    fmt_l = fmt.lower()
    if fmt_l in ("jpg", "jpeg"):
        img.convert("RGB").save(
            buf, format="JPEG", quality=_quality_param(quality), optimize=True
        )
    elif fmt_l == "webp-lossless":
        img.save(buf, format="WEBP", lossless=True)
    elif fmt_l == "webp-lossy":
        img.save(buf, format="WEBP", quality=_quality_param(quality))
    elif fmt_l == "webp":
        img.save(buf, format="WEBP", quality=_quality_param(quality))
    elif fmt_l == "png":
        # PNG 无损,体积靠压缩级别控制:quality 越低 → compress_level 越高 → 体积越小
        level = 9 if quality is None else max(0, min(9, int((100 - quality) * 9 / 95)))
        img.save(buf, format="PNG", optimize=True, compress_level=level)
    elif fmt_l == "bmp":
        img.convert("RGB").save(buf, format="BMP")
    elif fmt_l == "tiff":
        img.save(buf, format="TIFF")
    elif fmt_l == "heic":
        # Pillow 原生不支持 HEIC 输出,退化为高质量 WebP 并在文件名中保留请求扩展名
        img.save(buf, format="WEBP", quality=_quality_param(quality))
    else:
        img.save(buf, format="PNG")
    return buf.getvalue()


def _image_response(data: bytes, ext: str):
    media = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "bmp": "image/bmp",
        "tiff": "image/tiff",
        "webp": "image/webp",
    }.get(ext.lower(), "application/octet-stream")
    return Response(content=data, media_type=media)


@app.post("/api/image-sizer")
async def image_sizer(file: UploadFile = File(...), target_size: str = Form(...)):
    try:
        target_mb = float(target_size)
    except ValueError:
        raise HTTPException(status_code=400, detail="target_size 必须为数字(MB)")
    if target_mb <= 0:
        raise HTTPException(status_code=400, detail="target_size 必须大于 0")
    from PIL import Image

    raw = await file.read()
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:
        raise HTTPException(status_code=400, detail="无法解析图片文件")
    ext = (file.filename or "image.png").rsplit(".", 1)[-1].lower() or "png"
    fmt_map = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}
    pil_fmt = fmt_map.get(ext, "PNG")
    # 二分质量找到不超过目标大小的最大质量;过低则缩尺寸
    # 注意:1) 每轮必须重置 lo/hi,否则缩尺寸后的重试轮次会直接跳过
    #     2) PNG 等无损格式质量二分无效(同尺寸输出体积几乎恒定),直接最高压缩按轮缩尺寸
    out_ext = ext if ext in ("jpg", "jpeg", "png", "webp") else "jpg"
    best = None
    scale = 1.0
    for _ in range(10):
        lo, hi = 5, 95
        trial = img
        if scale < 1.0:
            trial = img.resize(
                (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
            )
        if out_ext in ("jpg", "jpeg", "webp"):
            while lo <= hi:
                mid = (lo + hi) // 2
                data = _save_image(trial, out_ext, mid)
                if len(data) <= target_mb * 1024 * 1024:
                    best = data
                    lo = mid + 1
                else:
                    hi = mid - 1
        else:
            data = _save_image(trial, "png", None)
            if len(data) <= target_mb * 1024 * 1024:
                best = data
        if best is not None:
            break
        scale *= 0.75  # 仍超限则缩小分辨率重试
    if best is None:
        raise HTTPException(status_code=500, detail="压缩失败,请调整目标大小")
    return _image_response(best, out_ext)


@app.post("/api/image-format-converter")
async def image_format_converter(
    file: UploadFile = File(...),
    target_format: str = Form(...),
    quality: Optional[str] = Form(None),
):
    from PIL import Image

    raw = await file.read()
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:
        raise HTTPException(status_code=400, detail="无法解析图片文件")
    target = (target_format or "png").lower()
    try:
        data = _save_image(img, target, int(quality) if quality else 85)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"转换失败: {e}")
    out_ext = target.replace("webp-lossless", "webp").replace("webp-lossy", "webp")
    return _image_response(data, out_ext)


class AudioGenRequest(BaseModel):
    text: str
    voice: str = "alloy"
    format: str = "mp3"
    speed: float = 1.0


@app.post("/api/audio-generator")
async def audio_generator(
    req: AudioGenRequest,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """语音合成:转发到用户配置的 OpenAI 兼容 TTS 接口。"""
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="请输入要转换的文本")
    if len(text) > 3000:
        raise HTTPException(status_code=400, detail="文本长度不能超过 3000 字")
    config = await _pick_ai_config(db)
    if config is None or not config.get("api_key"):
        raise HTTPException(
            status_code=400,
            detail="请先在账户菜单中配置个人文本 AI 模型(Base URL、API Key)",
        )
    base_url = (config["base_url"] or "https://api.openai.com/v1").rstrip("/")
    url = base_url if base_url.endswith("/audio/speech") else base_url + "/audio/speech"
    payload = {
        "model": "tts-1",
        "input": text,
        "voice": req.voice or "alloy",
        "response_format": req.format or "mp3",
        "speed": max(0.25, min(4.0, req.speed or 1.0)),
    }
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {config['api_key']}"},
            )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"TTS 服务连接失败: {e}")
    if resp.status_code != 200:
        try:
            err = resp.json().get("error", {})
            detail = err.get("message", "") if isinstance(err, dict) else str(err)
        except Exception:
            detail = ""
        raise HTTPException(
            status_code=502, detail=detail or f"TTS 服务返回 HTTP {resp.status_code}"
        )
    media = {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "opus": "audio/opus",
        "aac": "audio/aac",
    }.get(req.format, "audio/mpeg")
    return Response(content=resp.content, media_type=media)


class AudioScriptRequest(BaseModel):
    text: str = ""
    prompt: str = ""


@app.post("/api/builtin-ai/audio-script")
async def builtin_ai_audio_script(
    req: AudioScriptRequest,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """AI 润色朗读稿(复用 AIConfig,OpenAI 兼容)。"""
    config = await _pick_ai_config(db)
    if config is None or not config.get("api_key") or not config.get("model_name"):
        raise HTTPException(
            status_code=400,
            detail="请先在账户菜单中配置个人文本 AI 模型(Base URL、API Key、Model)",
        )
    base_url = (config["base_url"] or "https://api.openai.com/v1").rstrip("/")
    url = (
        base_url
        if base_url.endswith("/chat/completions")
        else base_url + "/chat/completions"
    )
    sys_prompt = (
        "你是语音播报文稿助手。根据用户的润色要求,把原文改写成适合语音合成的播报稿:"
        "口语化、节奏清晰、无多余符号。直接输出改写后的文稿,不要解释。"
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {
            "role": "user",
            "content": f"润色要求:{req.prompt or '口语化润色'}\n\n原文:\n{req.text or '(空)'}",
        },
    ]
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                url,
                json={
                    "model": config["model_name"],
                    "messages": messages,
                    "temperature": 0.5,
                },
                headers={"Authorization": f"Bearer {config['api_key']}"},
            )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"AI 服务连接失败: {e}")
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502, detail=f"AI 服务返回 HTTP {resp.status_code}"
        )
    try:
        result = resp.json()["choices"][0]["message"]["content"]
    except Exception:
        raise HTTPException(status_code=502, detail="AI 返回格式异常")
    return {"result": result}


# ============ 直接运行入口: python app/main.py ============
if __name__ == "__main__":
    # 直接以脚本方式运行时,sys.path[0] 是 app/ 目录,
    # 需要把 backend 目录加入 sys.path 才能完成 `from app...` 导入
    _backend_dir = Path(__file__).resolve().parent.parent
    if str(_backend_dir) not in sys.path:
        sys.path.insert(0, str(_backend_dir))

    # 数据库 / 上传目录等都是相对路径,统一切换到 backend 目录
    os.chdir(_backend_dir)

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)


# ============ AI 测试用例生成器 · 模型列表 + 生成 SSE ============

# 统一 AI 服务:有 Key 走真实模型,无 Key/失败自动返回流式 mock(演示可用)
from app.services import ai as _ai_service  # noqa: E402


class CaseGenRequest(BaseModel):
    requirement: str
    project_type: str = "web"  # web / api / app
    test_type: str = "functional"  # functional / boundary / exception / comprehensive
    model_id: Optional[int] = None  # 指定 AIConfig;空则默认优先
    temperature: float = 0.7
    max_tokens: int = 4000
    system_prompt: Optional[str] = None


# 内置模型目录：ai_configs 未配置任何 Key 时，前端模型下拉仍能看到可选项，
# 并通过 configured=false 标明「需在配置中心填 Key 后才能真调」。
# id 取负数以区别于 ai_configs 的自增主键。
_BUILTIN_CASE_GEN_MODELS = [
    {
        "id": -1,
        "name": "DeepSeek-V3",
        "supplier": "DeepSeek",
        "model_name": "deepseek-chat",
        "base_url": "https://api.deepseek.com/v1",
    },
    {
        "id": -2,
        "name": "通义千问 Qwen-Plus",
        "supplier": "阿里云百炼",
        "model_name": "qwen-plus",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    {
        "id": -3,
        "name": "智谱 GLM-4-Plus",
        "supplier": "智谱 AI",
        "model_name": "glm-4-plus",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
    },
    {
        "id": -4,
        "name": "月之暗面 Kimi",
        "supplier": "Moonshot",
        "model_name": "moonshot-v1-32k",
        "base_url": "https://api.moonshot.cn/v1",
    },
    {
        "id": -5,
        "name": "OpenAI GPT-4o-mini",
        "supplier": "OpenAI",
        "model_name": "gpt-4o-mini",
        "base_url": "https://api.openai.com/v1",
    },
    {
        "id": -6,
        "name": "本地 Ollama",
        "supplier": "Ollama",
        "model_name": "qwen2.5:14b",
        "base_url": "http://127.0.0.1:11434/v1",
    },
]


async def _case_gen_model_list(db: SyncDB) -> list:
    rows = await db_fetch_all(
        db,
        "SELECT * FROM ai_configs ORDER BY is_default DESC, id ASC",
    )
    out = [
        {
            "id": c["id"],
            "name": c["name"],
            "supplier": c["supplier"],
            "model_name": c["model_name"],
            "base_url": c["base_url"],
            "is_default": bool(c["is_default"]),
            "configured": bool(c.get("api_key") and c.get("model_name")),
            "tier": str(c.get("tier") or "free"),
            "builtin": False,
        }
        for c in rows
    ]
    used_models = {c.get("model_name") for c in rows}
    for b in _BUILTIN_CASE_GEN_MODELS:
        if b["model_name"] in used_models:
            continue
        out.append(
            {
                **b,
                "is_default": False,
                "configured": False,
                "builtin": True,
                "tier": "free",
            }
        )
    return out


@app.get("/api/case-generator/models")
async def case_generator_models(
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """可用 AI 大模型列表。

    优先返回配置中心已配置的 AIConfig；未配置时补充内置模型目录
    （configured=false），保证前端下拉始终有可选项。
    """
    return await _case_gen_model_list(db)


from app.services.casegen_core import TC_CASE_GEN_PROMPT, build_messages as _casegen_build_messages, demo_generated_cases as _demo_generated_cases  # noqa: E402


@app.post("/api/case-generator/generate/stream")
async def case_generator_stream(
    req: CaseGenRequest,
    db: SyncDB = Depends(get_db),
):
    """AI 生成测试用例:SSE 流式,思考/正文阶段推送,结束回传结构化 cases。

    演示可读:不强制登录;未配置 API Key 时不返回 400,
    改走统一 AI 服务流式(有环境 Key 真调,否则本地 mock 演示)。
    """
    if not req.requirement.strip():
        raise HTTPException(status_code=400, detail="请输入需求描述")
    config = None
    if req.model_id:
        if req.model_id < 0:
            # 内置模型目录（未配置 Key）：构造只含 base_url/model 的伪配置，
            # 由统一 AI 服务决定真调（环境 Key）或降级演示。
            preset = next(
                (m for m in _BUILTIN_CASE_GEN_MODELS if m["id"] == req.model_id),
                None,
            )
            if not preset:
                raise HTTPException(status_code=404, detail="所选 AI 模型不存在")
            config = {
                "id": preset["id"],
                "name": preset["name"],
                "supplier": preset["supplier"],
                "model_name": preset["model_name"],
                "base_url": preset["base_url"],
                "api_key": "",
            }
        else:
            config = await db_fetch_one(
                db, "SELECT * FROM ai_configs WHERE id=?", [req.model_id]
            )
            if not config:
                raise HTTPException(status_code=404, detail="所选 AI 模型不存在")
    if config is None:
        config = await _pick_ai_config(db)

    messages = _casegen_build_messages(
        req.requirement,
        project_type=req.project_type,
        test_type=req.test_type,
        system_prompt=req.system_prompt,
    )

    if config is None or not config.get("api_key") or not config.get("model_name"):
        # 无可用模型配置:统一 AI 服务流式(无 Key 自动 mock,前端帧格式不变)
        return StreamingResponse(
            _case_gen_unified_stream(db, messages, req, config),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    base_url = (config["base_url"] or "https://api.openai.com/v1").rstrip("/")
    url = (
        base_url
        if base_url.endswith("/chat/completions")
        else base_url + "/chat/completions"
    )
    payload = {
        "model": config["model_name"],
        "messages": messages,
        "stream": True,
        "temperature": max(0.0, min(2.0, req.temperature)),
        # 修复 R1：必须有输出上限，慢模型否则会无限生成拖死整条流
        "max_tokens": max(500, min(16000, req.max_tokens or 4096)),
    }
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }

    async def case_event_stream():
        from app.services import telemetry as _telemetry

        assistant_text = ""
        started = _telemetry.time.monotonic()
        in_tokens = _telemetry.estimate_tokens(
            _json.dumps(messages, ensure_ascii=False)
        )

        async def _log(status: str, body: str = "") -> None:
            await _sse_log_ai(
                module="用例生成",
                model=str(config.get("model_name") or ""),
                prompt=req.requirement or "",
                assistant_text=assistant_text,
                started=started,
                in_tokens=in_tokens,
                status=status,
                body=body,
            )

        try:
            client, resp = await _open_ai_stream(
                url, payload, headers, module="用例生成", timeout=300
            )
            stalled = False  # 流停滞（慢模型无新块）标记
            hit_limit = False  # finish_reason=length：达 max_tokens 上限
            try:
                async for line in _iter_idle_timeout(resp.aiter_lines()):
                    if line is _IDLE_MARK:
                        stalled = True
                        break
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        data = _json.loads(chunk)
                    except Exception:
                        continue
                    choices = data.get("choices") or []
                    if not choices:
                        continue
                    if choices[0].get("finish_reason") == "length":
                        hit_limit = True
                    delta = choices[0].get("delta") or {}
                    if delta.get("reasoning_content"):
                        yield _sse_block(
                            {
                                "type": "reasoning",
                                "content": str(delta["reasoning_content"]),
                            }
                        )
                    if delta.get("content"):
                        assistant_text += str(delta["content"])
                        yield _sse_block(
                            {"type": "content", "delta": str(delta["content"])}
                        )
            finally:
                await resp.aclose()
                await client.aclose()
            if stalled:
                yield _sse_block(
                    {
                        "type": "reasoning",
                        "content": (
                            "模型响应中断（超过 "
                            f"{int(_STREAM_IDLE_SECONDS)}s 无新内容），"
                            "已按已生成内容做截断修复…"
                        ),
                    }
                )
            if not assistant_text.strip():
                # 终止帧兜底：一个字都没收到也必须有明确终态，前端不再空转
                await _log("失败", "empty_stream")
                yield _sse_block(
                    {"type": "error", "error": "模型未返回任何内容（连接停滞或额度限流），请稍后重试或更换模型"}
                )
                return
            parsed = _parse_generated_cases(assistant_text)
            if parsed:
                await _log("成功")
                summary = parsed.get("summary") or "已生成测试用例"
                if hit_limit or stalled:
                    summary += f"（输出达到长度/时间上限，已自动截断修复，保留 {len(parsed['cases'])} 条完整用例）"
                yield _sse_block(
                    {
                        "type": "done",
                        "success": True,
                        "summary": summary,
                        "cases": parsed["cases"],
                    }
                )
            else:
                await _log("成功", assistant_text[:500])
                yield _sse_block(
                    {
                        "type": "done",
                        "success": False,
                        "summary": "AI 返回内容未能解析出结构化用例"
                        + ("（流被截断且无法修复）" if (stalled or hit_limit) else ""),
                        "raw": assistant_text[:2000],
                    }
                )
        except Exception as err:  # noqa: BLE001
            await _log("失败", str(err)[:300])
            yield _sse_block({"type": "error", "error": str(err) or "AI 请求失败"})

    return StreamingResponse(
        case_event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _case_gen_unified_stream(db, messages, req, config):
    """无可用模型配置时：统一 AI 服务流式输出，帧格式与前端约定一致。

    reasoning → content(delta)* → done(success+cases) | error。
    有环境 Key 时 chat(stream=True) 透传真实 chunk；无 Key/失败降级为
    逐段 mock 文本 + 本地演示用例，保证前端可渲染。
    """
    yield _sse_block(
        {
            "type": "reasoning",
            "content": "正在通过统一 AI 服务生成测试用例（当前配置：%s）..."
            % ("mock 演示" if not config or not config.get("api_key") else "真实模型"),
        }
    )
    model = (config or {}).get("model_name") or None
    assistant_text = ""
    # StreamingResponse 场景下 Depends(get_db) 已 teardown，统一 AI 服务
    # 内部 get_ai_config/telemetry 都需要可用连接，这里自建独立连接。
    from app.core.database import SyncDB as _SyncDB
    from app.core.database import _get_conn as _get_conn_local

    _conn = _get_conn_local()
    _stream_db = _SyncDB(_conn)
    try:
        try:
            stream = await _ai_service.chat(
                _stream_db,
                messages,
                module="用例生成",
                model=model,
                temperature=max(0.0, min(2.0, req.temperature)),
                stream=True,
                max_tokens=max(500, min(16000, req.max_tokens or 4096)),
            )
            if isinstance(stream, str):
                # stream=True 理论不返回 str，兜底按整段内容处理
                assistant_text = stream
                if stream:
                    yield _sse_block({"type": "content", "delta": stream})
            else:
                stalled = False
                async for chunk in _iter_idle_timeout(stream):
                    if chunk is _IDLE_MARK:
                        stalled = True
                        break
                    if not chunk:
                        continue
                    assistant_text += str(chunk)
                    yield _sse_block({"type": "content", "delta": str(chunk)})
                if stalled:
                    yield _sse_block(
                        {
                            "type": "reasoning",
                            "content": "模型响应中断，已按已生成内容做截断修复…",
                        }
                    )
        except Exception as err:  # noqa: BLE001
            yield _sse_block({"type": "error", "error": str(err) or "AI 请求失败"})
            return
    finally:
        _conn.close()

    parsed = _parse_generated_cases(assistant_text)
    if parsed and parsed.get("cases"):
        yield _sse_block(
            {
                "type": "done",
                "success": True,
                "summary": parsed.get("summary") or "已生成测试用例",
                "cases": parsed["cases"],
            }
        )
    else:
        # mock 文本无法解析出结构化 JSON 时，回退演示用例，保证表格可填充
        demo = _demo_generated_cases(req.requirement)
        yield _sse_block(
            {
                "type": "done",
                "success": True,
                "summary": demo["summary"],
                "cases": demo["cases"],
            }
        )


from app.services.ai_parse import parse_generated_cases as _parse_generated_cases  # noqa: E402


# ============ 前端静态托管：优先 frontend/dist（SPA），回落 UI 设计稿 ============
from pathlib import Path as _UIPath  # noqa: E402
from fastapi.staticfiles import StaticFiles as _StaticFiles  # noqa: E402

_ROOT = _UIPath(__file__).resolve().parents[2]
_DIST = _ROOT / "frontend" / "dist"
_UI_DIR = _ROOT / "UI"

# 附件等上传文件的静态访问（必须早于 SPA catch-all 挂载，否则会被 index.html 兜底）
_UPLOADS_DIR = _ROOT / "backend" / "uploads"
if _UPLOADS_DIR.exists():
    app.mount("/uploads", _StaticFiles(directory=str(_UPLOADS_DIR)), name="uploads")
    print(f"[uploads] 已挂载上传目录: {_UPLOADS_DIR}")

if (_DIST / "index.html").exists():
    app.mount("/", _StaticFiles(directory=str(_DIST), html=True), name="spa")
    print(f"[ui] 已挂载前端构建目录: {_DIST}")

    # SPA history fallback：/auth、/t/xxx 等前端路由刷新/直链时，
    # StaticFiles 只会回 404；对非 API 的浏览器导航请求回退 index.html，由前端路由接管。
    from fastapi.responses import FileResponse as _FileResponse  # noqa: E402
    from fastapi.responses import JSONResponse as _JSONResponse  # noqa: E402
    from starlette.exceptions import HTTPException as _StarletteHTTPException  # noqa: E402

    _SPA_INDEX = _DIST / "index.html"

    @app.exception_handler(_StarletteHTTPException)
    async def _spa_history_fallback(request, exc):  # type: ignore[no-redef]
        path = request.url.path
        if (
            exc.status_code == 404
            and request.method in ("GET", "HEAD")
            and not path.startswith(("/api", "/uploads"))
            and "text/html" in request.headers.get("accept", "")
        ):
            return _FileResponse(str(_SPA_INDEX))
        return _JSONResponse(
            {"detail": getattr(exc, "detail", "Not Found")},
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

elif _UI_DIR.exists():
    app.mount("/", _StaticFiles(directory=str(_UI_DIR), html=True), name="ui")
    print(f"[ui] 已挂载前端静态目录: {_UI_DIR}")
else:
    print("[ui] 未找到 dist/UI 目录（跳过静态托管）")
