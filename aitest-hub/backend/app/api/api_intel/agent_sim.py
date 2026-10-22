"""内置本机 Agent 模拟器（edge 模块的"执行引擎"）。

本平台就跑在用户本机，后端进程自身即一台 Edge Agent：
- 不依赖外部上报，dashboard 每次读取时按 last_seen_at 重算在线状态；
- Python 探测、任务执行全部是真实动作（subprocess），非假数据；
- 打包出的独立 agent 脚本（agent-pack.zip）是一个真实可运行的轮询骨架。

契约依据：spec/01 A13、B1-B6。
"""

import asyncio
import io
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import datetime

from app.core.database import (
    SyncDB,
    _get_conn,
    db_fetch_all,
    db_fetch_one,
    db_insert,
    db_update,
)

from .common import jdump, jload, now_str, parse_dt, get_profile, validate_profile

logger = logging.getLogger(__name__)

AGENT_VERSION = "edge-1.3.0"
OFFLINE_SECONDS = 90  # 距 last_seen_at 超过 90 秒视为离线（B2 灯文案一致）

# 正在执行的子进程 / 活跃任务 / 取消标记 / 定时器去重（进程内内存态）
RUNNING_PROCESSES: dict = {}  # job_id -> subprocess.Popen
ACTIVE_JOBS: set = set()  # 已进入 run_job_exec 的 job_id
CANCEL_FLAGS: set = set()  # 请求过取消的 job_id
_TIMER_FIRED: set = set()  # 定时器去重 key = ws|日期|HH:MM
_BG_TASKS: list = []


# =============================================================================
# 设备（内置模拟器注册自身）
# =============================================================================


def _platform_os_name() -> str:
    return f"{platform.system()} {platform.release()}".strip()


async def ensure_device(db: SyncDB, ws_id: int) -> dict | None:
    """确保该工作空间至少有 1 台设备（即本机内置 Agent），返回设备行。"""
    dev = await db_fetch_one(
        db,
        "SELECT * FROM ai_edge_devices WHERE ws_id=? ORDER BY last_seen_at DESC, id LIMIT 1",
        [ws_id],
    )
    if dev:
        return dev
    profile = await get_profile(db, ws_id)
    device_id = uuid.uuid4().hex
    now = now_str()
    await db_insert(
        db,
        "ai_edge_devices",
        {
            "id": device_id,
            "ws_id": ws_id,
            "hostname": platform.node(),
            "os_name": _platform_os_name(),
            "agent_version": AGENT_VERSION,
            "status": "online",
            "tests_root_hint": profile.get("project_root") or "",
            "capabilities_json": jdump({"builtin": True, "python_candidates": []}),
            "last_seen_at": now,
        },
    )
    dev = await db_fetch_one(
        db, "SELECT * FROM ai_edge_devices WHERE id=?", [device_id]
    )
    return dev


async def touch_heartbeat(db: SyncDB, device_id: str):
    """刷新设备心跳（置在线并更新 last_seen_at）。"""
    await db_update(
        db,
        "ai_edge_devices",
        {"status": "online", "last_seen_at": now_str()},
        "id=?",
        [device_id],
    )


def refresh_status(devices: list) -> list:
    """按 last_seen_at 重算在线状态（>90s → offline），就地修改并返回。"""
    now = datetime.now()
    for d in devices:
        seen = parse_dt(d.get("last_seen_at") or "")
        if seen is None or (now - seen).total_seconds() > OFFLINE_SECONDS:
            d["status"] = "offline"
        else:
            d["status"] = "online"
    return devices


def agent_version_ge(device: dict, major: int = 1, minor: int = 3) -> bool:
    """判断设备 agent_version（形如 edge-1.3.0）是否 >= major.minor。"""
    m = re.search(r"(\d+)\.(\d+)", device.get("agent_version") or "")
    if not m:
        return False
    got = (int(m.group(1)), int(m.group(2)))
    return got >= (major, minor)


# =============================================================================
# Python 探测（真实 subprocess）
# =============================================================================

_PYTEST_RE = re.compile(r"(\d+) (passed|failed|skipped|error|errors)")


def _probe_version(cmd: str):
    """真实执行 `<cmd> -V`，返回版本字符串；不可用返回 None。"""
    try:
        r = subprocess.run([cmd, "-V"], capture_output=True, text=True, timeout=3)
        m = re.search(r"Python\s+(\d[\w.]*)", (r.stdout or "") + (r.stderr or ""))
        return m.group(1) if m else ""
    except Exception:  # noqa: BLE001
        return None


def probe_python_candidates(project_root) -> list:
    """依次探测 python3 / python / sys.executable / 项目 venv，返回候选列表。"""
    out, seen = [], set()

    def try_add(cmd: str, label: str):
        if not cmd or cmd in seen:
            return
        seen.add(cmd)
        ver = _probe_version(cmd)
        if ver is None:  # 命令不存在/执行失败
            return
        out.append({"cmd": cmd, "version": ver, "label": label})

    try_add("python3", "PATH")
    try_add("python", "PATH")
    try_add(sys.executable, "系统默认")
    root = str(project_root or "").strip()
    if root:
        root = os.path.expanduser(root)
        for venv_dir, label in (
            (".venv", "项目 venv (.venv)"),
            ("venv", "项目 venv (venv)"),
        ):
            for sub in (
                os.path.join("bin", "python"),
                os.path.join("bin", "python.exe"),
                os.path.join("Scripts", "python.exe"),
                os.path.join("Scripts", "python"),
            ):
                p = os.path.join(root, venv_dir, sub)
                if os.path.isfile(p):
                    try_add(p, label)
                    break
    return out


def _resolve_python_cmd(cmd: str):
    """解析实际 Python 命令；常见 PATH 别名缺失时回退到本机可用解释器。"""
    cmd = str(cmd or "").strip() or "python"
    expanded = os.path.expanduser(cmd)
    if os.path.isabs(expanded):
        return expanded, expanded != cmd
    resolved = shutil.which(cmd)
    if resolved:
        return resolved, False
    for alias in ("python3", "py"):
        fallback = shutil.which(alias)
        if fallback:
            return fallback, True
    return sys.executable, True


async def run_python_discover(ws_id: int, device_id: str, created_by=None):
    """后台任务：真实探测本机 Python 并把 capabilities 写回设备。"""
    conn = await asyncio.to_thread(_get_conn)
    db = SyncDB(conn)
    ok, count, err = True, 0, ""
    try:
        dev = await db_fetch_one(
            db, "SELECT * FROM ai_edge_devices WHERE id=?", [device_id]
        )
        if not dev:
            dev = await ensure_device(db, ws_id)
        profile = await get_profile(db, ws_id)
        candidates = await asyncio.to_thread(
            probe_python_candidates, profile.get("project_root")
        )
        count = len(candidates)
        cap = jload(dev.get("capabilities_json"), {}) or {}
        cap["python_candidates"] = candidates
        cap["discovered_at"] = now_str()
        await db_update(
            db,
            "ai_edge_devices",
            {
                "capabilities_json": jdump(cap),
                "status": "online",
                "last_seen_at": now_str(),
            },
            "id=?",
            [dev["id"]],
        )
    except Exception as e:  # noqa: BLE001
        ok, err = False, str(e)
        logger.exception("python-discover 失败 ws=%s", ws_id)
    finally:
        try:
            # 记一条 discover_python 任务供「运行记录」侧栏回看
            await db_insert(
                db,
                "ai_run_jobs",
                {
                    "id": str(uuid.uuid4()),
                    "ws_id": ws_id,
                    "device_id": device_id,
                    "job_type": "discover_python",
                    "status": "succeeded" if ok else "failed",
                    "created_by": created_by,
                    "created_at": now_str(),
                    "started_at": now_str(),
                    "finished_at": now_str(),
                    "summary_json": jdump({"python_count": count, "error": err}),
                    "exit_code": 0 if ok else 1,
                },
            )
        except Exception:  # noqa: BLE001
            pass
        await asyncio.to_thread(conn.close)


# =============================================================================
# 运行任务执行（真实子进程 + 逐行日志）
# =============================================================================


def _append_log_sync(conn, job_id: str, text: str):
    """追加一行日志，seq 由 SQL 自增（UNIQUE(job_id,seq) 下天然无冲突）。"""
    conn.execute(
        "INSERT INTO ai_run_job_logs (job_id, seq, text, created_at) "
        "SELECT ?, COALESCE(MAX(seq), -1) + 1, ?, ? FROM ai_run_job_logs WHERE job_id=?",
        [job_id, text, now_str(), job_id],
    )
    conn.commit()


def _exec_blocking(job_id: str, cmd: str, entry_abs: str, cwd: str) -> dict:
    """worker 线程：启动子进程，stdout/stderr 逐行落库。返回执行结果。"""
    conn = _get_conn()
    counts = {}
    try:
        try:
            proc = subprocess.Popen(
                [cmd, "-u", entry_abs],
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
        except FileNotFoundError:
            _append_log_sync(
                conn, job_id, f"[platform-agent] 未找到 Python 解释器：{cmd}\n"
            )
            return {"rc": None, "counts": {}, "missing_python": True}
        RUNNING_PROCESSES[job_id] = proc
        try:
            for line in proc.stdout or []:  # stdout+stderr 已合并
                _append_log_sync(
                    conn, job_id, line if line.endswith("\n") else line + "\n"
                )
                # 持续记录 pytest 汇总行（取最后一次出现的分项计数）
                if " passed" in line or " failed" in line or "skipped" in line:
                    # findall 返回 [(数字, 关键词), ...]，映射为 {关键词: 数字}
                    g = {word: int(num) for num, word in _PYTEST_RE.findall(line)}
                    if g:
                        counts = {
                            "passed": g.get("passed", 0),
                            "failed": g.get("failed", 0)
                            + g.get("error", 0)
                            + g.get("errors", 0),
                            "skipped": g.get("skipped", 0),
                        }
        finally:
            rc = proc.wait()
        return {"rc": rc, "counts": counts, "missing_python": False}
    finally:
        RUNNING_PROCESSES.pop(job_id, None)
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def request_cancel(job_id: str) -> bool:
    """请求取消：活跃任务置取消标记并 terminate→kill；返回是否由执行器接管。"""
    if job_id not in ACTIVE_JOBS:
        return False
    CANCEL_FLAGS.add(job_id)
    proc = RUNNING_PROCESSES.get(job_id)
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception:  # noqa: BLE001
            pass
    return True


async def run_job_exec(job_id: str, ws_id: int, device_id: str, profile: dict):
    """后台任务：queued → running → 终态；进程输出逐行写入 ai_run_job_logs。"""
    ACTIVE_JOBS.add(job_id)
    conn = await asyncio.to_thread(_get_conn)
    db = SyncDB(conn)
    try:
        job = await db_fetch_one(db, "SELECT * FROM ai_run_jobs WHERE id=?", [job_id])
        if not job or job["status"] in ("cancelled", "failed", "succeeded"):
            return
        root = os.path.expanduser(str(profile.get("project_root") or "").strip())
        entry = str(profile.get("entry_file") or "run.py").strip().replace("\\", "/")
        requested_py = str(profile.get("python_cmd") or "python").strip()
        py, python_fallback = _resolve_python_cmd(requested_py)

        # ---- 真实预检：路径必须存在 ----
        if not root or not os.path.isdir(root):
            _append_log_sync(
                conn,
                job_id,
                f"[platform-agent] 项目路径不存在：{root or '(未填写)'}\n",
            )
            await db_update(
                db,
                "ai_run_jobs",
                {
                    "status": "failed",
                    "started_at": job.get("started_at") or now_str(),
                    "finished_at": now_str(),
                    "exit_code": -1,
                },
                "id=?",
                [job_id],
            )
            return
        entry_abs = os.path.normpath(os.path.join(root, *entry.split("/")))
        if not os.path.isfile(entry_abs):
            _append_log_sync(
                conn, job_id, f"[platform-agent] 入口文件未找到：{entry_abs}\n"
            )
            await db_update(
                db,
                "ai_run_jobs",
                {
                    "status": "failed",
                    "started_at": now_str(),
                    "finished_at": now_str(),
                    "exit_code": -1,
                },
                "id=?",
                [job_id],
            )
            return
        if job_id in CANCEL_FLAGS:
            _append_log_sync(conn, job_id, "[platform-agent] 任务在启动前已被取消\n")
            await db_update(
                db,
                "ai_run_jobs",
                {"status": "cancelled", "finished_at": now_str()},
                "id=?",
                [job_id],
            )
            return

        if python_fallback and requested_py and py != requested_py:
            _append_log_sync(
                conn,
                job_id,
                f"[platform-agent] Python 解释器回退：{requested_py} -> {py}\n",
            )
        _append_log_sync(
            conn,
            job_id,
            f"[platform-agent] 开始执行：{py} -u {entry}（cwd={root}）\n",
        )
        await db_update(
            db,
            "ai_run_jobs",
            {"status": "running", "started_at": now_str()},
            "id=?",
            [job_id],
        )
        # ---- 真实执行（worker 线程，逐行 append 日志） ----
        result = await asyncio.to_thread(_exec_blocking, job_id, py, entry_abs, root)
        if result["missing_python"]:
            await db_update(
                db,
                "ai_run_jobs",
                {"status": "failed", "finished_at": now_str(), "exit_code": -1},
                "id=?",
                [job_id],
            )
            return
        rc = result["rc"]
        counts = result["counts"]
        summary = (
            {
                "passed": counts["passed"],
                "failed": counts["failed"],
                "skipped": counts["skipped"],
            }
            if counts
            else {
                "passed": 1 if (rc == 0) else 0,
                "failed": 0 if (rc == 0) else 1,
                "skipped": 0,
            }
        )
        # 取消优先判定（cancel_requested → cancelled）
        cur = await db_fetch_one(
            db, "SELECT status FROM ai_run_jobs WHERE id=?", [job_id]
        )
        if (cur or {}).get("status") == "cancel_requested" or job_id in CANCEL_FLAGS:
            final = "cancelled"
        else:
            final = "succeeded" if rc == 0 else "failed"
        await db_update(
            db,
            "ai_run_jobs",
            {
                "status": final,
                "finished_at": now_str(),
                "exit_code": rc,
                "summary_json": jdump(summary),
            },
            "id=?",
            [job_id],
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("run_job_exec 异常 job=%s", job_id)
        try:
            _append_log_sync(conn, job_id, f"[platform-agent] 执行异常：{e}\n")
            await db_update(
                db,
                "ai_run_jobs",
                {"status": "failed", "finished_at": now_str(), "exit_code": -1},
                "id=?",
                [job_id],
            )
        except Exception:  # noqa: BLE001
            pass
    finally:
        ACTIVE_JOBS.discard(job_id)
        CANCEL_FLAGS.discard(job_id)
        try:
            await asyncio.to_thread(conn.close)
        except Exception:  # noqa: BLE001
            pass


# =============================================================================
# Agent 启动包（真实可运行的独立轮询脚本）
# =============================================================================

_AGENT_PY = """#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# TestHub 接口智能 · 本机 Edge Agent（独立启动包版，真实可运行轮询骨架）
import json
import platform
import sys
import time
import urllib.error
import urllib.request

_PACK_BASE = ""
_PACK_WS = ""
_PACK_TOKEN = ""

BASE = _PACK_BASE or "http://127.0.0.1:8000"
API = BASE + "/api/api-intel/workspaces/" + str(_PACK_WS) + "/edge"


def _request(path, payload=None):
    url = API + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Agent-Token", _PACK_TOKEN)
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode("utf-8", "replace")
    return json.loads(body) if body else {}


def heartbeat():
    return _request("/heartbeat", {
        "hostname": platform.node(),
        "os_name": platform.system() + " " + platform.release(),
        "agent_version": "edge-1.3.0-pack",
        "tests_root_hint": "",
        "capabilities": {},
    })


print("[edge-agent] 已启动：平台 " + BASE + "，工作区 " + str(_PACK_WS))
print("[edge-agent] 每 5 秒上报心跳；Ctrl+C 退出。")
tick = 0
while True:
    try:
        r = heartbeat()
        print("[edge-agent] 心跳成功:", r.get("ok"), r.get("server_time", ""))
    except urllib.error.HTTPError as e:
        print("[edge-agent] 心跳失败 HTTP %s（401 表示令牌失效，请回平台重新下载启动包）" % e.code)
    except Exception as e:  # noqa: BLE001
        print("[edge-agent] 网络异常:", e)
    tick += 1
    if tick % 6 == 0:  # 约 30 秒尝试拉取一次运行任务并回传状态
        try:
            jobs = _request("/run-jobs?page=1&page_size=5")
            for j in (jobs.get("items") or []):
                if j.get("status") in ("queued", "running"):
                    print("[edge-agent] 发现进行中任务:", j.get("id")[:8], j.get("status"))
        except Exception as e:  # noqa: BLE001
            print("[edge-agent] 拉取任务列表失败（若为 401：Web 端已使用内置 Agent 执行，可忽略）")
    time.sleep(5)
"""

_BAT = """@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
    python api_intel_edge_agent.py
) else (
    py -3 api_intel_edge_agent.py
)
pause
"""

_COMMAND = """#!/bin/bash
cd "$(dirname "$0")"
python3 api_intel_edge_agent.py
"""

_README = """TestHub 接口智能 · 本机 Edge Agent 启动包
================================================

用途：让平台连接你本机的测试项目，实现「文档 ↔ 本机测试」对照与定时运行。
你的测试代码与执行过程始终留在本机，平台不上传源码。

使用步骤：
1. 保持 TestHub 平台（aitest-hub 后端）在本机运行；
2. Windows 双击 start_edge.bat；macOS 双击 start_edge.command
   （首次如被拦截：系统设置 → 隐私与安全性 → 仍要打开）；
3. 窗口每 5 秒打印一次心跳，回到平台「执行台」页面，状态灯应变绿；
4. 在平台执行台填写项目根目录与入口文件（如 run.py），点击「运行」即可；
5. 关闭窗口即断开连接，平台约 90 秒后显示设备离线。

常见问题：
- 心跳一直 401：令牌已失效，请回平台重新点「下载启动包」获取新包；
- 需 Python 3.8+（仅用标准库，无需 pip 安装任何依赖）；
- 高级配置：可直接编辑 api_intel_edge_agent.py 顶部 _PACK_* 变量。
"""

AGENT_PACK_FILES = {
    "api_intel_edge_agent.py": _AGENT_PY,
    "start_edge.bat": _BAT,
    "start_edge.command": _COMMAND,
    "README.txt": _README,
}


def build_agent_pack_zip(
    ws_id,
    token: str,
    base_url: str = "",
    contract_context_json: str = "",
) -> bytes:
    """真实构造 zip 启动包：.py 模板注入平台地址/工作空间/一次性令牌。

    contract_context_json 非空时附带 contract-context.json（L5 Agent 上下文补丁）。
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in AGENT_PACK_FILES.items():
            if name.endswith(".py"):
                text = (
                    text.replace(
                        '_PACK_BASE = ""', "_PACK_BASE = " + json.dumps(base_url or "")
                    )
                    .replace('_PACK_WS = ""', "_PACK_WS = " + json.dumps(str(ws_id)))
                    .replace(
                        '_PACK_TOKEN = ""', "_PACK_TOKEN = " + json.dumps(token or "")
                    )
                )
            zf.writestr(name, text)
        if contract_context_json:
            zf.writestr("contract-context.json", contract_context_json)
    return buf.getvalue()


# =============================================================================
# 后台循环（main.py 启动时调用 start_background_loops()）
# =============================================================================


async def _heartbeat_loop():
    """每 30 秒把内置 Agent 设备刷新为在线（平台进程活着 = 本机 Agent 活着）。"""
    while True:
        try:
            conn = await asyncio.to_thread(_get_conn)
            try:
                db = SyncDB(conn)
                await db_execute_all(
                    db,
                    "UPDATE ai_edge_devices SET status='online', last_seen_at=? "
                    "WHERE capabilities_json LIKE '%\"builtin\"%'",
                    [now_str()],
                )
            finally:
                await asyncio.to_thread(conn.close)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("edge 心跳循环异常")
        await asyncio.sleep(30)


async def db_execute_all(db: SyncDB, sql: str, params=None):
    """内部小工具：执行写 SQL 并提交（供后台循环复用）。"""
    import asyncio as _a

    await _a.to_thread(db.execute, sql, params or [])
    await _a.to_thread(db.commit)


async def _timer_loop():
    """每 20 秒检查各工作空间定时器：命中当天 HH:MM（5 分钟粒度）自动创建并执行 run 任务。"""
    while True:
        try:
            conn = await asyncio.to_thread(_get_conn)
            db = SyncDB(conn)
            try:
                rows = await db_fetch_all(
                    db, "SELECT * FROM ai_edge_timer WHERE enabled=1"
                )
                now = datetime.now()
                today = now.strftime("%Y-%m-%d")
                if len(_TIMER_FIRED) > 2000:  # 简单清理过期 key
                    _TIMER_FIRED.clear()
                for row in rows:
                    for slot in jload(row.get("slots_json"), []) or []:
                        if (
                            int(slot.get("hour", -1)) != now.hour
                            or int(slot.get("minute", -1)) != now.minute
                        ):
                            continue
                        key = f"{row['ws_id']}|{today}|{now.hour:02d}:{now.minute:02d}"
                        if key in _TIMER_FIRED:
                            continue
                        _TIMER_FIRED.add(key)
                        await _fire_timer_job(db, int(row["ws_id"]))
            finally:
                await asyncio.to_thread(conn.close)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("edge 定时器循环异常")
        await asyncio.sleep(20)


async def _fire_timer_job(db: SyncDB, ws_id: int):
    """定时器到点：profile 有效则创建 run 任务并立即执行。"""
    try:
        profile = await get_profile(db, ws_id)
        try:
            profile = validate_profile(profile)
        except Exception:  # noqa: BLE001
            return  # 未配置/非法：静默跳过本次
        if not profile["project_root"]:
            return
        dev = await ensure_device(db, ws_id)
        job_id = str(uuid.uuid4())
        await db_insert(
            db,
            "ai_run_jobs",
            {
                "id": job_id,
                "ws_id": ws_id,
                "device_id": dev["id"],
                "job_type": "run",
                "status": "queued",
                "created_by": None,
                "created_at": now_str(),
            },
        )
        asyncio.create_task(run_job_exec(job_id, ws_id, dev["id"], profile))
    except Exception:  # noqa: BLE001
        logger.exception("定时器触发失败 ws=%s", ws_id)


def start_background_loops():
    """供 main.py 启动：拉起心跳与定时器协程循环。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("start_background_loops 需在运行中的事件循环内调用")
        return
    for coro in (_heartbeat_loop(), _timer_loop()):
        _BG_TASKS.append(loop.create_task(coro))
