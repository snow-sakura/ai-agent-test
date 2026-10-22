"""APP 自动化 UI 路由（SyncDB 版）— /api/app-automation/*

自建 appa_* 表；不 import app.app_automation.models（async SQLAlchemy）。
覆盖：设备 / 应用包 / 脚本 / 流水线 / 执行 / 定时任务 / AI 生成脚本步骤。
"""

import io
import json
import random
import re
import struct
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.database import (
    SyncDB,
    db_commit,
    db_execute,
    db_fetch_all,
    db_fetch_one,
    db_insert,
    db_update,
    get_db,
)
from app.core.deps import get_current_user
from app.services import ai as ai_svc

router = APIRouter(tags=["app-automation"])


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _j(v: Any, default=None):
    if v is None or v == "":
        return default if default is not None else None
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return default if default is not None else v


# ---------------------------------------------------------------------------
# seed
# ---------------------------------------------------------------------------

_SEED_DEVICES = [
    {
        "id": "emulator-5554",
        "name": "Xiaomi 12",
        "model": "Xiaomi 12",
        "os": "Android 13",
        "res": "2400×1080",
        "status": "在线",
        "ver": "",
    },
    {
        "id": "TP1A221",
        "name": "Pixel 7",
        "model": "Pixel 7",
        "os": "Android 14",
        "res": "2400×1080",
        "status": "执行中",
        "ver": "运行「登录冒烟」",
    },
    {
        "id": "8XV7N18",
        "name": "HUAWEI P40",
        "model": "HUAWEI P40",
        "os": "Android 12",
        "res": "2340×1080",
        "status": "离线",
        "ver": "",
    },
    {
        "id": "edge-node-01",
        "name": "边缘设备·实验室A",
        "model": "边缘设备",
        "os": "Android 11",
        "res": "1920×1080",
        "status": "在线",
        "ver": "Agent v1.4",
    },
]

_SEED_PACKAGES = [
    {
        "id": "com.example.shop@3.2.1",
        "pkg": "com.example.shop",
        "ver": "3.2.1",
        "size": "48.2MB",
        "note": "大促预发布版本",
        "time": "2026-09-21",
        "by": "wxh",
    },
    {
        "id": "com.example.shop@3.1.0",
        "pkg": "com.example.shop",
        "ver": "3.1.0",
        "size": "47.6MB",
        "note": "线上稳定版（基线）",
        "time": "2026-09-10",
        "by": "李雷",
    },
    {
        "id": "com.example.vendor@1.8.0",
        "pkg": "com.example.vendor",
        "ver": "1.8.0",
        "size": "12.4MB",
        "note": "商家端",
        "time": "2026-09-05",
        "by": "韩梅",
    },
]

_DEFAULT_SCRIPT_STEPS = [
    "启动应用",
    "等待 2 秒",
    "点击 #login_btn",
    "输入 username={{USER}}",
    "输入 password={{PASS}}",
    "点击「登录」",
    "等待 3 秒",
    "断言页面包含「首页」",
]

_SEED_SCRIPTS = [
    {
        "id": "AS-21",
        "name": "登录-浏览-下单冒烟",
        "fw": "Appium",
        "pkg": "com.example.shop",
        "steps": _DEFAULT_SCRIPT_STEPS,
        "last": "成功",
        "upd": "2026-09-22",
    },
    {
        "id": "AS-20",
        "name": "优惠券领取验证",
        "fw": "Appium",
        "pkg": "com.example.shop",
        "steps": [
            "启动应用",
            "等待 2 秒",
            "点击 #coupon_entry",
            "点击「立即领取」",
            "断言页面包含「领取成功」",
        ],
        "last": "失败",
        "upd": "2026-09-19",
    },
    {
        "id": "AS-19",
        "name": "首页启动性能采集",
        "fw": "ADB 原生",
        "pkg": "com.example.shop",
        "steps": [
            "adb shell am force-stop com.example.shop",
            "adb shell am start -W com.example.shop/.MainActivity",
            "解析 TotalTime 并上报",
        ],
        "last": "成功",
        "upd": "2026-09-15",
    },
    {
        "id": "AS-18",
        "name": "商家端登录回归",
        "fw": "Python 脚本",
        "pkg": "com.example.vendor",
        "steps": [
            "启动商家端",
            "输入账号 admin",
            "输入密码",
            "点击登录",
            "等待首页加载",
            "断言包含「工作台」",
        ],
        "last": "成功",
        "upd": "2026-09-12",
    },
]

_SEED_PIPELINES = [
    {
        "id": "PJ-88",
        "name": "核心冒烟-小米12",
        "script_ids": ["AS-21", "AS-19"],
        "device": "Xiaomi 12",
        "fail_policy": "失败即中止",
        "created_at": "2026-09-22",
    },
    {
        "id": "PJ-87",
        "name": "全量回归-Pixel7",
        "script_ids": ["AS-21", "AS-20", "AS-19"],
        "device": "Pixel 7",
        "fail_policy": "失败继续",
        "created_at": "2026-09-21",
    },
    {
        "id": "PJ-86",
        "name": "优惠券专项",
        "script_ids": ["AS-20"],
        "device": "Pixel 7",
        "fail_policy": "失败即中止",
        "created_at": "2026-09-19",
    },
]

_SEED_JOBS = [
    {
        "id": "PJ-88",
        "name": "核心冒烟-小米12",
        "scripts": "登录冒烟 ×2",
        "device": "Xiaomi 12",
        "status": "运行中",
        "cur": 1,
        "total": 2,
        "time": "刚刚",
        "by": "wxh",
    },
    {
        "id": "PJ-87",
        "name": "全量回归-Pixel7",
        "scripts": "登录冒烟 ×3",
        "device": "Pixel 7",
        "status": "成功",
        "cur": 3,
        "total": 3,
        "time": "2026-09-21 20:15",
        "by": "wxh",
    },
    {
        "id": "PJ-86",
        "name": "优惠券专项",
        "scripts": "优惠券验证",
        "device": "Pixel 7",
        "status": "失败",
        "cur": 1,
        "total": 1,
        "time": "2026-09-19 15:40",
        "by": "韩梅",
    },
]

_SEED_TIMERS = [
    {
        "id": "TM-5",
        "name": "每夜回归冒烟",
        "cron": "0 2 * * *",
        "pipeline": "全量回归-Pixel7",
        "last": "2026-09-22 02:00 成功",
        "status": "启用",
    },
    {
        "id": "TM-4",
        "name": "每周全量兼容",
        "cron": "0 3 * * 1",
        "pipeline": "核心冒烟-小米12",
        "last": "2026-09-15 03:00 成功",
        "status": "启用",
    },
]


# ---------------------------------------------------------------------------
# schema / helpers
# ---------------------------------------------------------------------------


async def _ensure_schema(db: SyncDB) -> None:
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS appa_devices (
        id TEXT PRIMARY KEY, name TEXT, model TEXT, os TEXT, res TEXT,
        status TEXT, ver TEXT, created_at TEXT)""",
    )
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS appa_packages (
        id TEXT PRIMARY KEY, pkg TEXT, ver TEXT, size TEXT, note TEXT,
        time TEXT, by TEXT, created_at TEXT)""",
    )
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS appa_scripts (
        id TEXT PRIMARY KEY, name TEXT, fw TEXT, pkg TEXT, steps TEXT,
        last TEXT, upd TEXT, created_at TEXT)""",
    )
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS appa_pipelines (
        id TEXT PRIMARY KEY, name TEXT, script_ids TEXT, device TEXT,
        fail_policy TEXT, created_at TEXT)""",
    )
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS appa_jobs (
        id TEXT PRIMARY KEY, name TEXT, scripts TEXT, device TEXT,
        status TEXT, cur INTEGER, total INTEGER, time TEXT, by TEXT,
        created_at TEXT)""",
    )
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS appa_timers (
        id TEXT PRIMARY KEY, name TEXT, cron TEXT, pipeline TEXT,
        last TEXT, status TEXT, created_at TEXT)""",
    )
    await db_execute(
        db,
        """CREATE TABLE IF NOT EXISTS appa_elements (
        id TEXT PRIMARY KEY, name TEXT, element_type TEXT, tags TEXT,
        config TEXT, is_active INTEGER DEFAULT 1, created_at TEXT, updated_at TEXT)""",
    )
    await db_commit(db)


async def _seed_if_empty(db: SyncDB) -> None:
    for table, seed in (
        ("appa_devices", _SEED_DEVICES),
        ("appa_packages", _SEED_PACKAGES),
        ("appa_scripts", _SEED_SCRIPTS),
        ("appa_pipelines", _SEED_PIPELINES),
        ("appa_jobs", _SEED_JOBS),
        ("appa_timers", _SEED_TIMERS),
    ):
        row = await db_fetch_one(db, f"SELECT COUNT(*) AS c FROM {table}", [])
        if not (row and row["c"]):
            for r in seed:
                item = dict(r)
                if table == "appa_scripts":
                    item["steps"] = json.dumps(r["steps"], ensure_ascii=False)
                if table == "appa_pipelines":
                    item["script_ids"] = json.dumps(r["script_ids"], ensure_ascii=False)
                item.setdefault("created_at", _today())
                await db_insert(db, table, item)
    await db_commit(db)


async def _ready(db: SyncDB) -> None:
    await _ensure_schema(db)
    await _seed_if_empty(db)


async def _next_id(db: SyncDB, table: str, prefix: str) -> str:
    rows = await db_fetch_all(
        db, f"SELECT id FROM {table} WHERE id LIKE ?", [f"{prefix}%"]
    )
    best = 0
    for r in rows:
        try:
            best = max(best, int(str(r["id"]).split("-")[-1]))
        except Exception:
            pass
    return f"{prefix}{best + 1}"


def _device_row(r: dict) -> dict:
    name = r.get("name") or ""
    os_name = r.get("os") or ""
    return {
        "id": r.get("id"),
        "udid": r.get("id"),
        "name": name,
        "model": r.get("model") or name,
        "android": os_name,
        "os": os_name,
        "res": r.get("res") or "",
        "status": r.get("status") or "离线",
        "ver": r.get("ver") or "",
    }


def _package_row(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "pkg": r.get("pkg") or "",
        "ver": r.get("ver") or "",
        "size": r.get("size") or "",
        "note": r.get("note") or "",
        "time": r.get("time") or "",
        "by": r.get("by") or "",
    }


def _script_row(r: dict) -> dict:
    steps = _j(r.get("steps"), [])
    if not isinstance(steps, list):
        steps = []
    return {
        "id": r.get("id"),
        "name": r.get("name") or "",
        "fw": r.get("fw") or "Appium",
        "pkg": r.get("pkg") or "",
        "steps": steps,
        "stepCount": len(steps),
        "last": r.get("last") or "",
        "upd": r.get("upd") or "",
    }


def _pipeline_row(r: dict) -> dict:
    ids = _j(r.get("script_ids"), [])
    if not isinstance(ids, list):
        ids = []
    return {
        "id": r.get("id"),
        "name": r.get("name") or "",
        "scriptIds": ids,
        "scripts": ids,
        "device": r.get("device") or "",
        "failPolicy": r.get("fail_policy") or "失败即中止",
        "createdAt": r.get("created_at") or "",
    }


def _job_row(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "name": r.get("name") or "",
        "scripts": r.get("scripts") or "",
        "device": r.get("device") or "",
        "status": r.get("status") or "",
        "cur": int(r.get("cur") or 0),
        "total": int(r.get("total") or 0),
        "time": r.get("time") or "",
        "by": r.get("by") or "",
    }


def _timer_row(r: dict) -> dict:
    cron = r.get("cron") or ""
    pipeline = r.get("pipeline") or ""
    return {
        "id": r.get("id"),
        "name": r.get("name") or "",
        "expr": cron,
        "cron": cron,
        "target": pipeline,
        "pipeline": pipeline,
        "last": r.get("last") or "尚未触发",
        "status": r.get("status") or "启用",
    }


# ---------------------------------------------------------------------------
# pydantic
# ---------------------------------------------------------------------------


class DeviceCreate(BaseModel):
    id: str = ""
    name: str
    model: str = ""
    os: str = "Android 13"
    res: str = "2400×1080"
    status: str = "在线"
    ver: str = ""


class PackageCreate(BaseModel):
    id: str = ""
    pkg: str
    ver: str
    size: str = "—"
    note: str = ""
    by: str = "wxh"


class ScriptCreate(BaseModel):
    id: str = ""
    name: str
    fw: str = "Appium"
    pkg: str = "com.example.shop"
    steps: List[str] = []
    last: str = "成功"


class ScriptUpdate(BaseModel):
    name: Optional[str] = None
    fw: Optional[str] = None
    pkg: Optional[str] = None
    steps: Optional[List[str]] = None
    last: Optional[str] = None


class PipelineCreate(BaseModel):
    id: str = ""
    name: str
    script_ids: List[str] = []
    device: str = "Xiaomi 12"
    fail_policy: str = "失败即中止"
    run: bool = True


class PipelineUpdate(BaseModel):
    name: Optional[str] = None
    script_ids: Optional[List[str]] = None
    device: Optional[str] = None
    fail_policy: Optional[str] = None


class JobCreate(BaseModel):
    id: str = ""
    name: str
    scripts: str = ""
    device: str = ""
    status: str = "运行中"
    total: int = 1
    by: str = "wxh"


class JobUpdate(BaseModel):
    name: Optional[str] = None
    scripts: Optional[str] = None
    device: Optional[str] = None
    status: Optional[str] = None
    cur: Optional[int] = None
    total: Optional[int] = None
    by: Optional[str] = None


class TimerCreate(BaseModel):
    id: str = ""
    name: str
    cron: str = "0 2 * * *"
    pipeline: str = ""
    status: str = "启用"


class TimerUpdate(BaseModel):
    name: Optional[str] = None
    cron: Optional[str] = None
    pipeline: Optional[str] = None
    status: Optional[str] = None
    last: Optional[str] = None


class AiScriptReq(BaseModel):
    desc: str
    pkg: str = "com.example.shop"


class ElementBody(BaseModel):
    name: str
    element_type: str = "image"
    tags: List[str] = []
    config: Dict[str, Any] = {}


def _element_row(r: dict) -> dict:
    def _loads(raw: Any, default: Any) -> Any:
        if not raw:
            return default
        if isinstance(raw, (list, dict)):
            return raw
        try:
            return json.loads(raw)
        except Exception:
            return default

    return {
        "id": r["id"],
        "name": r["name"],
        "element_type": r["element_type"] or "image",
        "tags": _loads(r.get("tags"), []),
        "config": _loads(r.get("config"), {}),
        "is_active": bool(r.get("is_active", 1)),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# devices
# ---------------------------------------------------------------------------


@router.get("/app-automation/devices")
async def list_devices(
    kw: str = "",
    status: str = "",
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    rows = await db_fetch_all(db, "SELECT * FROM appa_devices ORDER BY id", [])
    out = [_device_row(r) for r in rows]
    if kw:
        k = kw.lower()
        out = [d for d in out if k in (d["name"] + d["id"]).lower()]
    if status:
        out = [d for d in out if d["status"] == status]
    return out


@router.post("/app-automation/devices", status_code=201)
async def create_device(
    body: DeviceCreate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="设备名称不能为空")
    did = body.id.strip() or f"dev-{random.randint(1000, 9999)}"
    if await db_fetch_one(db, "SELECT id FROM appa_devices WHERE id=?", [did]):
        raise HTTPException(status_code=409, detail="设备已存在")
    await db_insert(
        db,
        "appa_devices",
        {
            "id": did,
            "name": body.name.strip(),
            "model": body.model or body.name,
            "os": body.os,
            "res": body.res,
            "status": body.status,
            "ver": body.ver,
            "created_at": _now(),
        },
    )
    row = await db_fetch_one(db, "SELECT * FROM appa_devices WHERE id=?", [did])
    return _device_row(row)


@router.delete("/app-automation/devices/{did}")
async def delete_device(
    did: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    row = await db_fetch_one(db, "SELECT id FROM appa_devices WHERE id=?", [did])
    if not row:
        raise HTTPException(status_code=404, detail="设备不存在")
    await db_execute(db, "DELETE FROM appa_devices WHERE id=?", [did])
    await db_commit(db)
    return {"ok": True, "id": did}


# ---------------------------------------------------------------------------
# packages
# ---------------------------------------------------------------------------


_PKG_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){2,}$")
_VER_RE = re.compile(r"^\d+\.\d+(?:\.\d+){0,2}(?:[-+][0-9A-Za-z.\-]+)?$")


def _axml_strings(data: bytes) -> List[str]:
    """Read the string pool of an Android binary XML (AndroidManifest.xml).

    The pool stores plain UTF-16LE / UTF-8 text, so package & versionName can be
    recovered without a full AXML attribute walker.
    """
    out: List[str] = []
    try:
        if len(data) < 36:
            return out
        ftype = struct.unpack_from("<H", data, 0)[0]
        if ftype != 0x0003:  # RES_XML_TYPE
            return out
        off = 8  # xml chunk header size
        ctype, cheader, csize = struct.unpack_from("<HHI", data, off)
        if (
            ctype != 0x0001 or csize <= 0 or off + csize > len(data)
        ):  # RES_STRING_POOL_TYPE
            return out
        str_count, _style_count, flags, strings_start, _styles_start = (
            struct.unpack_from("<IIIII", data, off + 8)
        )
        if not (0 < str_count <= 200000):
            return out
        utf8 = bool(flags & 0x100)
        base = off
        limit = base + csize
        data_start = base + strings_start
        for i in range(str_count):
            ipos = base + cheader + i * 4
            if ipos + 4 > limit:
                break
            sp = data_start + struct.unpack_from("<I", data, ipos)[0]
            if sp >= limit:
                continue
            if utf8:
                p = sp
                if p + 2 > limit:
                    continue
                b = data[p]
                if b & 0x80:
                    p += 1
                    b = ((b & 0x7F) << 8) | data[p]
                p += 1  # char length consumed
                if p >= limit:
                    continue
                blen = data[p]
                if blen & 0x80:
                    p += 1
                    blen = ((blen & 0x7F) << 8) | data[p]
                p += 1
                end = p + blen
                if end <= limit:
                    out.append(data[p:end].decode("utf-8", errors="replace"))
            else:
                p = sp
                if p + 2 > limit:
                    continue
                n = struct.unpack_from("<H", data, p)[0]
                p += 2
                if n & 0x8000:
                    if p + 2 > limit:
                        continue
                    n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", data, p)[0]
                    p += 2
                end = p + n * 2
                if end <= limit:
                    out.append(data[p:end].decode("utf-16-le", errors="replace"))
    except Exception:
        return []
    return out


def _analyze_apk(raw: bytes, filename: str) -> Dict[str, Any]:
    """Real APK/AAB inspection: zip layout + AndroidManifest string pool."""
    ext = (filename or "").lower().rsplit(".", 1)[-1] if "." in (filename or "") else ""
    if ext not in ("apk", "aab", "zip", "xapk"):
        raise HTTPException(status_code=400, detail="仅支持 APK / AAB 文件")
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except Exception:
        raise HTTPException(status_code=400, detail="文件不是有效的 APK/AAB（ZIP）包")
    with zf:
        names = zf.namelist()
        if not names:
            raise HTTPException(status_code=400, detail="应用包内没有任何文件")
        dex = [n for n in names if n.endswith(".dex")]
        abis = sorted(
            {
                n.split("/")[1]
                for n in names
                if n.startswith("lib/") and n.count("/") >= 2
            }
        )
        assets = [n for n in names if n.startswith("assets/")]
        has_res = any(n.startswith("res/") for n in names)
        strs: List[str] = []
        pkg = ""
        ver = ""
        try:
            mf = zf.read("AndroidManifest.xml")
        except KeyError:
            raise HTTPException(
                status_code=400, detail="包内缺少 AndroidManifest.xml，不是合法 APK"
            )
        strs = _axml_strings(mf)
        if not strs:
            # fallback: printable ASCII runs from raw manifest bytes
            strs = [
                s.decode("utf-8", errors="ignore")
                for s in re.findall(rb"[\x20-\x7e]{4,80}", mf[:65536])
            ]
        pkg = next((s for s in strs if _PKG_RE.match(s.strip())), "")
        vers = [
            s.strip()
            for s in strs
            if _VER_RE.match(s.strip()) and "." in s.strip() and len(s.strip()) > 2
        ]
        ver = vers[0] if vers else ""

    # filename fallback keeps the old UX when manifest strings are unavailable
    parsed_from = "manifest" if pkg else "filename"
    base = re.sub(r"\.(apk|aab|zip|xapk)$", "", filename or "", flags=re.I)
    m = re.match(r"^(.+)[-_]v?(\d+(?:\.\d+)*)$", base or "", flags=re.I)
    if not pkg and m:
        pkg = m.group(1).replace("-", ".")
    if not ver and m:
        ver = m.group(2)
    if not pkg:
        pkg = "com.example.app"
    if not ver:
        ver = "1.0.0"

    kb = len(raw) / 1024
    size = ("%.1fMB" % (kb / 1024)) if kb >= 1024 else ("%.0fKB" % kb)

    return {
        "pkg": pkg,
        "ver": ver,
        "size": size,
        "file": filename,
        "files": len(names),
        "dex": len(dex),
        "abis": abis,
        "assets": len(assets),
        "has_res": has_res,
        "manifest_strings": len(strs),
        "parsed_from": parsed_from,
    }


@router.post("/app-automation/packages/upload", status_code=201)
async def upload_package(
    file: UploadFile = File(...),
    note: str = Form(""),
    dry_run: bool = Form(False),
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    """真实上传 APK/AAB → 解析 manifest 得到包名/版本 → 落库。

    dry_run=true 只解析不落库（用于选择文件后的实时预览）。
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(raw) > 500 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="应用包超过 500MB 限制")
    info = _analyze_apk(raw, file.filename or "")
    if dry_run:
        return info
    await _ready(db)
    pid = "%s@%s" % (info["pkg"], info["ver"])
    if await db_fetch_one(db, "SELECT id FROM appa_packages WHERE id=?", [pid]):
        raise HTTPException(status_code=409, detail="应用包已存在: %s" % pid)
    await db_insert(
        db,
        "appa_packages",
        {
            "id": pid,
            "pkg": info["pkg"],
            "ver": info["ver"],
            "size": info["size"],
            "note": note or ("上传解析自 " + (file.filename or "")),
            "time": _today(),
            "by": (current_user or {}).get("name") or "wxh",
            "created_at": _now(),
        },
    )
    row = await db_fetch_one(db, "SELECT * FROM appa_packages WHERE id=?", [pid])
    info["record"] = _package_row(row)
    return info


@router.get("/app-automation/packages")
async def list_packages(db: SyncDB = Depends(get_db)):
    await _ready(db)
    rows = await db_fetch_all(db, "SELECT * FROM appa_packages ORDER BY time DESC", [])
    return [_package_row(r) for r in rows]


@router.post("/app-automation/packages", status_code=201)
async def create_package(
    body: PackageCreate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    if not body.pkg.strip() or not body.ver.strip():
        raise HTTPException(status_code=400, detail="包名与版本不能为空")
    pid = f"{body.pkg.strip()}@{body.ver.strip()}"
    if await db_fetch_one(db, "SELECT id FROM appa_packages WHERE id=?", [pid]):
        raise HTTPException(status_code=409, detail="应用包已存在")
    await db_insert(
        db,
        "appa_packages",
        {
            "id": pid,
            "pkg": body.pkg.strip(),
            "ver": body.ver.strip(),
            "size": body.size,
            "note": body.note or "—",
            "time": _today(),
            "by": body.by or "wxh",
            "created_at": _now(),
        },
    )
    row = await db_fetch_one(db, "SELECT * FROM appa_packages WHERE id=?", [pid])
    return _package_row(row)


@router.delete("/app-automation/packages/{pid:path}")
async def delete_package(
    pid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    row = await db_fetch_one(db, "SELECT id FROM appa_packages WHERE id=?", [pid])
    if not row:
        raise HTTPException(status_code=404, detail="应用包不存在")
    await db_execute(db, "DELETE FROM appa_packages WHERE id=?", [pid])
    await db_commit(db)
    return {"ok": True, "id": pid}


# ---------------------------------------------------------------------------
# scripts
# ---------------------------------------------------------------------------


@router.get("/app-automation/scripts")
async def list_scripts(
    kw: str = "",
    fw: str = "",
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    rows = await db_fetch_all(db, "SELECT * FROM appa_scripts ORDER BY id DESC", [])
    out = [_script_row(r) for r in rows]
    if kw:
        k = kw.lower()
        out = [s for s in out if k in s["name"].lower()]
    if fw:
        out = [s for s in out if s["fw"] == fw]
    return out


@router.get("/app-automation/scripts/{sid}")
async def get_script(sid: str, db: SyncDB = Depends(get_db)):
    await _ready(db)
    row = await db_fetch_one(db, "SELECT * FROM appa_scripts WHERE id=?", [sid])
    if not row:
        raise HTTPException(status_code=404, detail="脚本不存在")
    return _script_row(row)


@router.post("/app-automation/scripts", status_code=201)
async def create_script(
    body: ScriptCreate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="脚本名称不能为空")
    sid = body.id.strip() or await _next_id(db, "appa_scripts", "AS-")
    if await db_fetch_one(db, "SELECT id FROM appa_scripts WHERE id=?", [sid]):
        raise HTTPException(status_code=409, detail="脚本 ID 已存在")
    steps = body.steps or _DEFAULT_SCRIPT_STEPS
    await db_insert(
        db,
        "appa_scripts",
        {
            "id": sid,
            "name": body.name.strip(),
            "fw": body.fw or "Appium",
            "pkg": body.pkg,
            "steps": json.dumps(steps, ensure_ascii=False),
            "last": body.last or "成功",
            "upd": _today(),
            "created_at": _now(),
        },
    )
    row = await db_fetch_one(db, "SELECT * FROM appa_scripts WHERE id=?", [sid])
    return _script_row(row)


@router.put("/app-automation/scripts/{sid}")
async def update_script(
    sid: str,
    body: ScriptUpdate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    row = await db_fetch_one(db, "SELECT * FROM appa_scripts WHERE id=?", [sid])
    if not row:
        raise HTTPException(status_code=404, detail="脚本不存在")
    data: Dict[str, Any] = {"upd": _today()}
    if body.name is not None:
        data["name"] = body.name.strip()
    if body.fw is not None:
        data["fw"] = body.fw
    if body.pkg is not None:
        data["pkg"] = body.pkg
    if body.steps is not None:
        data["steps"] = json.dumps(body.steps, ensure_ascii=False)
    if body.last is not None:
        data["last"] = body.last
    await db_update(db, "appa_scripts", data, "id=?", [sid])
    row = await db_fetch_one(db, "SELECT * FROM appa_scripts WHERE id=?", [sid])
    return _script_row(row)


@router.delete("/app-automation/scripts/{sid}")
async def delete_script(
    sid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    row = await db_fetch_one(db, "SELECT id FROM appa_scripts WHERE id=?", [sid])
    if not row:
        raise HTTPException(status_code=404, detail="脚本不存在")
    await db_execute(db, "DELETE FROM appa_scripts WHERE id=?", [sid])
    await db_commit(db)
    return {"ok": True, "id": sid}


# ---------------------------------------------------------------------------
# pipelines
# ---------------------------------------------------------------------------


@router.get("/app-automation/pipelines")
async def list_pipelines(db: SyncDB = Depends(get_db)):
    await _ready(db)
    rows = await db_fetch_all(db, "SELECT * FROM appa_pipelines ORDER BY id DESC", [])
    return [_pipeline_row(r) for r in rows]


@router.post("/app-automation/pipelines", status_code=201)
async def create_pipeline(
    body: PipelineCreate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="流水线名称不能为空")
    if not body.script_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个脚本")
    pid = body.id.strip() or await _next_id(db, "appa_pipelines", "PJ-")
    if await db_fetch_one(db, "SELECT id FROM appa_pipelines WHERE id=?", [pid]):
        raise HTTPException(status_code=409, detail="流水线 ID 已存在")
    # 校验设备在线
    if body.device:
        dev = await db_fetch_one(
            db,
            "SELECT * FROM appa_devices WHERE name=? OR id=?",
            [body.device, body.device],
        )
        if dev and (dev.get("status") or "") == "离线":
            raise HTTPException(status_code=400, detail="该设备离线，请选择在线设备")
    await db_insert(
        db,
        "appa_pipelines",
        {
            "id": pid,
            "name": body.name.strip(),
            "script_ids": json.dumps(body.script_ids, ensure_ascii=False),
            "device": body.device,
            "fail_policy": body.fail_policy or "失败即中止",
            "created_at": _today(),
        },
    )
    job = None
    if body.run:
        total = len(body.script_ids)
        # 脚本名摘要
        names = []
        for sid in body.script_ids:
            s = await db_fetch_one(
                db, "SELECT name FROM appa_scripts WHERE id=?", [sid]
            )
            names.append(s["name"] if s else sid)
        scripts_desc = "、".join(names) if names else f"{total} 个脚本"
        user = (current_user or {}).get("username") or "wxh"
        await db_insert(
            db,
            "appa_jobs",
            {
                "id": pid,
                "name": body.name.strip(),
                "scripts": scripts_desc,
                "device": body.device,
                "status": "运行中",
                "cur": 0,
                "total": total,
                "time": "刚刚",
                "by": user,
                "created_at": _now(),
            },
        )
        job = await db_fetch_one(db, "SELECT * FROM appa_jobs WHERE id=?", [pid])
    row = await db_fetch_one(db, "SELECT * FROM appa_pipelines WHERE id=?", [pid])
    return {
        "pipeline": _pipeline_row(row),
        "job": _job_row(job) if job else None,
    }


@router.put("/app-automation/pipelines/{pid}")
async def update_pipeline(
    pid: str,
    body: PipelineUpdate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    row = await db_fetch_one(db, "SELECT * FROM appa_pipelines WHERE id=?", [pid])
    if not row:
        raise HTTPException(status_code=404, detail="流水线不存在")
    data: Dict[str, Any] = {}
    if body.name is not None:
        data["name"] = body.name.strip()
    if body.script_ids is not None:
        data["script_ids"] = json.dumps(body.script_ids, ensure_ascii=False)
    if body.device is not None:
        data["device"] = body.device
    if body.fail_policy is not None:
        data["fail_policy"] = body.fail_policy
    if data:
        await db_update(db, "appa_pipelines", data, "id=?", [pid])
    row = await db_fetch_one(db, "SELECT * FROM appa_pipelines WHERE id=?", [pid])
    return _pipeline_row(row)


@router.delete("/app-automation/pipelines/{pid}")
async def delete_pipeline(
    pid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    row = await db_fetch_one(db, "SELECT id FROM appa_pipelines WHERE id=?", [pid])
    if not row:
        raise HTTPException(status_code=404, detail="流水线不存在")
    await db_execute(db, "DELETE FROM appa_pipelines WHERE id=?", [pid])
    await db_commit(db)
    return {"ok": True, "id": pid}


# ---------------------------------------------------------------------------
# jobs（执行流水线）
# ---------------------------------------------------------------------------


@router.get("/app-automation/jobs")
async def list_jobs(db: SyncDB = Depends(get_db)):
    await _ready(db)
    rows = await db_fetch_all(db, "SELECT * FROM appa_jobs ORDER BY id DESC", [])
    return [_job_row(r) for r in rows]


@router.get("/app-automation/jobs/{jid}")
async def get_job(jid: str, db: SyncDB = Depends(get_db)):
    await _ready(db)
    row = await db_fetch_one(db, "SELECT * FROM appa_jobs WHERE id=?", [jid])
    if not row:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    return _job_row(row)


@router.post("/app-automation/jobs", status_code=201)
async def create_job(
    body: JobCreate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="任务名称不能为空")
    jid = body.id.strip() or await _next_id(db, "appa_jobs", "PJ-")
    if await db_fetch_one(db, "SELECT id FROM appa_jobs WHERE id=?", [jid]):
        raise HTTPException(status_code=409, detail="任务 ID 已存在")
    user = (current_user or {}).get("username") or body.by or "wxh"
    await db_insert(
        db,
        "appa_jobs",
        {
            "id": jid,
            "name": body.name.strip(),
            "scripts": body.scripts,
            "device": body.device,
            "status": body.status or "运行中",
            "cur": 0,
            "total": max(1, int(body.total or 1)),
            "time": "刚刚",
            "by": user,
            "created_at": _now(),
        },
    )
    row = await db_fetch_one(db, "SELECT * FROM appa_jobs WHERE id=?", [jid])
    return _job_row(row)


@router.put("/app-automation/jobs/{jid}")
async def update_job(
    jid: str,
    body: JobUpdate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    row = await db_fetch_one(db, "SELECT * FROM appa_jobs WHERE id=?", [jid])
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    data: Dict[str, Any] = {"time": _now()}
    if body.name is not None:
        data["name"] = body.name.strip()
    if body.scripts is not None:
        data["scripts"] = body.scripts
    if body.device is not None:
        data["device"] = body.device
    if body.status is not None:
        data["status"] = body.status
    if body.cur is not None:
        data["cur"] = int(body.cur)
    if body.total is not None:
        data["total"] = int(body.total)
    if body.by is not None:
        data["by"] = body.by
    await db_update(db, "appa_jobs", data, "id=?", [jid])
    row = await db_fetch_one(db, "SELECT * FROM appa_jobs WHERE id=?", [jid])
    return _job_row(row)


@router.post("/app-automation/jobs/{jid}/stop")
async def stop_job(
    jid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    row = await db_fetch_one(db, "SELECT * FROM appa_jobs WHERE id=?", [jid])
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    if (row.get("status") or "") not in ("运行中", "排队中"):
        raise HTTPException(status_code=400, detail="仅运行中的任务可停止")
    await db_update(
        db,
        "appa_jobs",
        {"status": "失败", "time": _now()},
        "id=?",
        [jid],
    )
    row = await db_fetch_one(db, "SELECT * FROM appa_jobs WHERE id=?", [jid])
    return {"ok": True, "job": _job_row(row), "message": "流水线已停止"}


@router.delete("/app-automation/jobs/{jid}")
async def delete_job(
    jid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    row = await db_fetch_one(db, "SELECT id FROM appa_jobs WHERE id=?", [jid])
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    await db_execute(db, "DELETE FROM appa_jobs WHERE id=?", [jid])
    await db_commit(db)
    return {"ok": True, "id": jid}


# ---------------------------------------------------------------------------
# timers
# ---------------------------------------------------------------------------


@router.get("/app-automation/timers")
async def list_timers(db: SyncDB = Depends(get_db)):
    await _ready(db)
    rows = await db_fetch_all(db, "SELECT * FROM appa_timers ORDER BY id DESC", [])
    return [_timer_row(r) for r in rows]


@router.post("/app-automation/timers", status_code=201)
async def create_timer(
    body: TimerCreate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="任务名称不能为空")
    expr = (body.cron or "").strip()
    if not expr:
        raise HTTPException(status_code=400, detail="Cron 表达式不能为空")
    # 轻量格式校验（完整语义交给 crontab 解析接口）
    import re

    if not re.match(r"^[\d\*\/\,\-\s]+$", expr):
        raise HTTPException(status_code=400, detail="Cron 表达式格式不正确")
    tid = body.id.strip() or await _next_id(db, "appa_timers", "TM-")
    if await db_fetch_one(db, "SELECT id FROM appa_timers WHERE id=?", [tid]):
        raise HTTPException(status_code=409, detail="定时任务 ID 已存在")
    await db_insert(
        db,
        "appa_timers",
        {
            "id": tid,
            "name": body.name.strip(),
            "cron": expr,
            "pipeline": body.pipeline,
            "last": "尚未触发",
            "status": body.status or "启用",
            "created_at": _now(),
        },
    )
    row = await db_fetch_one(db, "SELECT * FROM appa_timers WHERE id=?", [tid])
    return _timer_row(row)


@router.put("/app-automation/timers/{tid}")
async def update_timer(
    tid: str,
    body: TimerUpdate,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    row = await db_fetch_one(db, "SELECT * FROM appa_timers WHERE id=?", [tid])
    if not row:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    data: Dict[str, Any] = {}
    if body.name is not None:
        data["name"] = body.name.strip()
    if body.cron is not None:
        data["cron"] = body.cron.strip()
    if body.pipeline is not None:
        data["pipeline"] = body.pipeline
    if body.status is not None:
        data["status"] = body.status
    if body.last is not None:
        data["last"] = body.last
    if data:
        await db_update(db, "appa_timers", data, "id=?", [tid])
    row = await db_fetch_one(db, "SELECT * FROM appa_timers WHERE id=?", [tid])
    return _timer_row(row)


@router.delete("/app-automation/timers/{tid}")
async def delete_timer(
    tid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    row = await db_fetch_one(db, "SELECT id FROM appa_timers WHERE id=?", [tid])
    if not row:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    await db_execute(db, "DELETE FROM appa_timers WHERE id=?", [tid])
    await db_commit(db)
    return {"ok": True, "id": tid}


# ---------------------------------------------------------------------------
# AI 生成脚本步骤
# ---------------------------------------------------------------------------


@router.post("/app-automation/ai-script")
async def ai_script(
    body: AiScriptReq,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    desc = (body.desc or "").strip()
    if not desc:
        raise HTTPException(status_code=400, detail="desc 不能为空")
    try:
        data = await ai_svc.chat_json(
            db,
            [
                {
                    "role": "user",
                    "content": (
                        "你是 Android 自动化测试助手。根据描述生成 Appium/ADB 脚本步骤，"
                        "只输出 JSON 数组（不要解释），每项为一行可执行步骤字符串。\n"
                        f"目标包：{body.pkg}\n描述：{desc}"
                    ),
                }
            ],
            module="APP自动化",
        )
        if isinstance(data, dict):
            data = data.get("steps") or data.get("items") or []
        if isinstance(data, list) and data:
            steps = [str(x) for x in data[:30] if str(x).strip()]
            if steps:
                return {
                    "steps": steps,
                    "text": "\n".join(steps),
                    "count": len(steps),
                    "source": "ai",
                }
    except Exception:
        pass
    steps = list(_DEFAULT_SCRIPT_STEPS)
    return {
        "steps": steps,
        "text": "\n".join(steps),
        "count": len(steps),
        "source": "local",
    }


# ---------------------------------------------------------------------------
# 元素库(元素截图模板登记)— SyncDB 版,替代 api_core 中依赖 async ORM 的实现
# ---------------------------------------------------------------------------


@router.get("/app-automation/elements")
async def list_elements(q: str = "", db: SyncDB = Depends(get_db)):
    await _ready(db)
    rows = await db_fetch_all(
        db,
        "SELECT * FROM appa_elements WHERE is_active = 1 ORDER BY updated_at DESC, id DESC",
        [],
    )
    out = [_element_row(r) for r in rows]
    if q:
        ql = q.lower()
        out = [
            e
            for e in out
            if ql in (e["name"] or "").lower() or any(q in (t or "") for t in e["tags"])
        ]
    return out


@router.post("/app-automation/elements", status_code=201)
async def create_element(
    body: ElementBody,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="元素名称不能为空")
    exists = await db_fetch_one(
        db, "SELECT id FROM appa_elements WHERE name = ? AND is_active = 1", [name]
    )
    if exists:
        raise HTTPException(status_code=400, detail=f"元素名称已存在: {name}")
    eid = await _next_id(db, "appa_elements", "EL-")
    now = _today()
    await db_insert(
        db,
        "appa_elements",
        {
            "id": eid,
            "name": name,
            "element_type": (body.element_type or "image").strip(),
            "tags": json.dumps(body.tags or [], ensure_ascii=False),
            "config": json.dumps(body.config or {}, ensure_ascii=False),
            "is_active": 1,
            "created_at": now,
            "updated_at": now,
        },
    )
    await db_commit(db)
    row = await db_fetch_one(db, "SELECT * FROM appa_elements WHERE id = ?", [eid])
    return _element_row(row) if row else {"success": True, "id": eid}


@router.delete("/app-automation/elements/{eid}")
async def delete_element(
    eid: str,
    current_user: dict = Depends(get_current_user),
    db: SyncDB = Depends(get_db),
):
    await _ready(db)
    row = await db_fetch_one(
        db, "SELECT id FROM appa_elements WHERE id = ? AND is_active = 1", [eid]
    )
    if not row:
        raise HTTPException(status_code=404, detail="元素不存在")
    await db_execute(
        db,
        "UPDATE appa_elements SET is_active = 0, updated_at = ? WHERE id = ?",
        [_today(), eid],
    )
    await db_commit(db)
    return {"success": True}
