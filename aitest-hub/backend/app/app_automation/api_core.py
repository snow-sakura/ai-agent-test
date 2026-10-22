# -*- coding: utf-8 -*-
"""APP自动化核心路由:项目/配置/仪表盘/设备/元素/组件/包名"""

import os
import shutil
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import User
from app.app_automation.engine.adb_manager import AdbManager
from app.app_automation.engine import mock_device
from app.app_automation.models import (
    AppComponent,
    AppComponentPackage,
    AppCustomComponent,
    AppDevice,
    AppElement,
    AppPackage,
    AppProject,
    AppTestConfig,
    AppTestCase,
    AppTestExecution,
    AppTestSuite,
    DeviceStatus,
)

router = APIRouter(prefix="/app-automation", tags=["app-automation"])


# ============ helpers ============


async def _get_config(db: AsyncSession) -> AppTestConfig:
    result = await db.execute(select(AppTestConfig).limit(1))
    cfg = result.scalar_one_or_none()
    if not cfg:
        cfg = AppTestConfig()
        db.add(cfg)
        await db.commit()
        await db.refresh(cfg)
    return cfg


def _device_dict(d: AppDevice) -> Dict[str, Any]:
    return {
        "id": d.id,
        "device_id": d.device_id,
        "name": d.name,
        "status": d.status,
        "android_version": d.android_version,
        "connection_type": d.connection_type,
        "ip_address": d.ip_address,
        "port": d.port,
        "locked_by": d.locked_by_id,
        "locked_at": d.locked_at.isoformat() if d.locked_at else None,
        "max_allocation_time": d.max_allocation_time,
        "device_specs": d.device_specs or {},
        "description": d.description,
        "location": d.location,
        "is_mock": d.is_mock,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _element_dict(e: AppElement) -> Dict[str, Any]:
    return {
        "id": e.id,
        "project_id": e.project_id,
        "name": e.name,
        "element_type": e.element_type,
        "tags": e.tags or [],
        "config": e.config or {},
        "resolution_configs": e.resolution_configs or {},
        "usage_count": e.usage_count,
        "last_used_at": e.last_used_at.isoformat() if e.last_used_at else None,
        "is_active": e.is_active,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "updated_at": e.updated_at.isoformat() if e.updated_at else None,
    }


# ============ 项目 ============


class ProjectBody(BaseModel):
    name: str
    description: str = ""
    status: str = "IN_PROGRESS"
    start_date: Optional[str] = None
    end_date: Optional[str] = None


@router.get("/projects")
async def list_projects(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(AppProject).order_by(AppProject.created_at.desc()))
    rows = result.scalars().all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "status": p.status,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in rows
    ]


@router.post("/projects")
async def create_project(
    body: ProjectBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    p = AppProject(
        name=body.name,
        description=body.description,
        status=body.status,
        owner_id=user.id,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return {"id": p.id, "name": p.name}


@router.put("/projects/{pid}")
async def update_project(
    pid: int,
    body: ProjectBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(AppProject).where(AppProject.id == pid))
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "项目不存在")
    p.name, p.description, p.status = body.name, body.description, body.status
    await db.commit()
    return {"id": p.id, "name": p.name}


@router.delete("/projects/{pid}")
async def delete_project(
    pid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    r = await db.execute(select(AppProject).where(AppProject.id == pid))
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "项目不存在")
    await db.delete(p)
    await db.commit()
    return {"message": "deleted"}


# ============ 配置 ============


class ConfigBody(BaseModel):
    adb_path: str = "adb"
    mock_mode: bool = True
    mock_device_count: int = 2


@router.get("/config/current")
async def get_config(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    cfg = await _get_config(db)
    return {
        "adb_path": cfg.adb_path,
        "mock_mode": cfg.mock_mode,
        "mock_device_count": cfg.mock_device_count,
    }


@router.post("/config/save")
async def save_config(
    body: ConfigBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cfg = await _get_config(db)
    cfg.adb_path = body.adb_path
    cfg.mock_mode = body.mock_mode
    cfg.mock_device_count = max(0, min(5, body.mock_device_count))
    await db.commit()
    return {"success": True}


# ============ 仪表盘 ============


@router.get("/dashboard/statistics")
async def dashboard_statistics(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    devices = (await db.execute(select(AppDevice))).scalars().all()
    cases = (await db.execute(select(AppTestCase))).scalars().all()
    execs = (await db.execute(select(AppTestExecution))).scalars().all()
    sessions = (await db.execute(select(AppPackage))).scalars().all()
    total = len(execs)
    passed = len([e for e in execs if e.result == "passed"])
    failed = len([e for e in execs if e.result == "failed"])
    return {
        "devices": {
            "total": len(devices),
            "online": len(
                [
                    d
                    for d in devices
                    if d.status in (DeviceStatus.ONLINE, DeviceStatus.AVAILABLE)
                ]
            ),
            "locked": len([d for d in devices if d.status == DeviceStatus.LOCKED]),
        },
        "test_cases": {"total": len(cases)},
        "packages": {"total": len(sessions)},
        "executions": {
            "total": total,
            "success": passed,
            "failed": failed,
            "pass_rate": round(passed / total * 100, 1) if total else 0,
            "running": len([e for e in execs if e.status == "running"]),
        },
    }


# ============ 设备 ============


class ConnectBody(BaseModel):
    ip_address: str
    port: int = 5555
    connection_type: str = "remote_emulator"


@router.get("/devices")
async def device_list(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(AppDevice).order_by(AppDevice.updated_at.desc()))
    return [_device_dict(d) for d in result.scalars().all()]


@router.post("/devices/discover")
async def devices_discover(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    cfg = await _get_config(db)
    mgr = AdbManager(adb_path=cfg.adb_path, mock_mode=cfg.mock_mode)
    discovered = mgr.list_devices()
    existing = (await db.execute(select(AppDevice))).scalars().all()
    existing_ids = {d.device_id for d in existing}
    added = []
    for dev in discovered.get("devices", []):
        if dev["device_id"] in existing_ids:
            continue
        d = AppDevice(
            device_id=dev["device_id"],
            name=dev.get("name", ""),
            status=DeviceStatus.AVAILABLE
            if dev.get("state") == "device"
            else DeviceStatus.OFFLINE,
            android_version=dev.get("android_version", ""),
            connection_type=dev.get("connection_type", "emulator"),
            device_specs={"model": dev.get("name", ""), "screen": "1080x2400"},
            is_mock=bool(dev.get("is_mock", False)),
        )
        db.add(d)
        added.append(dev["device_id"])
    await db.commit()
    return {
        "success": True,
        "message": f"发现 {len(discovered.get('devices', []))} 个设备,新增 {len(added)} 个",
        "added": added,
    }


@router.post("/devices/connect")
async def devices_connect(
    body: ConnectBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cfg = await _get_config(db)
    mgr = AdbManager(adb_path=cfg.adb_path, mock_mode=cfg.mock_mode)
    r = mgr.connect_device(body.ip_address, body.port)
    if r.get("success"):
        dev_id = r["device_id"]
        existing = (
            await db.execute(select(AppDevice).where(AppDevice.device_id == dev_id))
        ).scalar_one_or_none()
        if not existing:
            db.add(
                AppDevice(
                    device_id=dev_id,
                    name=f"{body.ip_address}:{body.port}",
                    status=DeviceStatus.AVAILABLE,
                    connection_type=body.connection_type,
                    ip_address=body.ip_address,
                    port=body.port,
                    is_mock=dev_id.startswith("mock"),
                )
            )
            await db.commit()
    return r


class DeviceActionBody(BaseModel):
    pass


@router.post("/devices/{device_pk}/lock")
async def device_lock(
    device_pk: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(AppDevice).where(AppDevice.id == device_pk))
    d = r.scalar_one_or_none()
    if not d:
        raise HTTPException(404, "设备不存在")
    if d.status == DeviceStatus.LOCKED and d.locked_by_id not in (None, user.id):
        raise HTTPException(400, "设备已被其他用户锁定")
    d.locked_by_id = user.id
    d.locked_at = datetime.utcnow()
    d.status = DeviceStatus.LOCKED
    await db.commit()
    return {"success": True, "message": f"设备 {d.device_id} 已锁定"}


@router.post("/devices/{device_pk}/unlock")
async def device_unlock(
    device_pk: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(AppDevice).where(AppDevice.id == device_pk))
    d = r.scalar_one_or_none()
    if not d:
        raise HTTPException(404, "设备不存在")
    d.locked_by_id = None
    d.locked_at = None
    d.status = DeviceStatus.AVAILABLE
    await db.commit()
    return {"success": True, "message": f"设备 {d.device_id} 已释放"}


@router.post("/devices/{device_pk}/disconnect")
async def device_disconnect(
    device_pk: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(AppDevice).where(AppDevice.id == device_pk))
    d = r.scalar_one_or_none()
    if not d:
        raise HTTPException(404, "设备不存在")
    cfg = await _get_config(db)
    mgr = AdbManager(adb_path=cfg.adb_path, mock_mode=cfg.mock_mode)
    result = mgr.disconnect_device(d.device_id)
    d.status = DeviceStatus.OFFLINE
    await db.commit()
    return result


@router.get("/devices/{device_pk}/screenshot")
async def device_screenshot(
    device_pk: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(AppDevice).where(AppDevice.id == device_pk))
    d = r.scalar_one_or_none()
    if not d:
        raise HTTPException(404, "设备不存在")
    cfg = await _get_config(db)
    mgr = AdbManager(adb_path=cfg.adb_path, mock_mode=cfg.mock_mode)
    path = os.path.join(
        mock_device.SCREENSHOT_DIR,
        f"{d.device_id}_live_{datetime.utcnow().strftime('%H%M%S%f')}.png",
    )
    result = mgr.screenshot(d.device_id, path)
    if not result.get("success"):
        raise HTTPException(500, result.get("message", "截图失败"))
    return {
        "success": True,
        "screenshot_url": "/api/app-automation/media?path=" + result["path"],
        "fingerprint": mock_device.get_mock_session(d.device_id).fingerprint()
        if d.is_mock
        else {},
    }


@router.get("/devices/{device_pk}/info")
async def device_info(
    device_pk: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(AppDevice).where(AppDevice.id == device_pk))
    d = r.scalar_one_or_none()
    if not d:
        raise HTTPException(404, "设备不存在")
    cfg = await _get_config(db)
    mgr = AdbManager(adb_path=cfg.adb_path, mock_mode=cfg.mock_mode)
    return mgr.get_device_info(d.device_id)


@router.delete("/devices/{device_pk}")
async def device_delete(
    device_pk: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(AppDevice).where(AppDevice.id == device_pk))
    d = r.scalar_one_or_none()
    if not d:
        raise HTTPException(404, "设备不存在")
    await db.delete(d)
    await db.commit()
    return {"success": True}


@router.get("/media")
async def media_file(path: str):
    """媒体文件访问(截图/元素图片),限定 uploads/app-automation 目录。

    匿名只读:列表缩略图等以 <img src> 直链访问,无法携带 Authorization header;
    路径已强制约束在 UPLOAD_BASE 内(403 防穿越),文件名为内容 hash,无敏感数据。
    """
    base = os.path.abspath(mock_device.UPLOAD_BASE)
    full = os.path.abspath(path)
    if not full.startswith(base):
        raise HTTPException(403, "非法路径")
    if not os.path.exists(full):
        raise HTTPException(404, "文件不存在")
    from fastapi.responses import FileResponse

    return FileResponse(full)


# ============ 元素 ============


class ElementBody(BaseModel):
    name: str
    element_type: str = "image"
    project_id: Optional[int] = None
    tags: List[str] = []
    config: Dict[str, Any] = {}
    resolution_configs: Dict[str, Any] = {}


@router.get("/elements")
async def element_list(
    q: str = "",
    element_type: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(AppElement)
        .where(AppElement.is_active == True)
        .order_by(AppElement.updated_at.desc())
    )  # noqa: E712
    rows = (await db.execute(stmt)).scalars().all()
    if q:
        rows = [
            r
            for r in rows
            if q.lower() in r.name.lower()
            or any(q in (t or "") for t in (r.tags or []))
        ]
    if element_type:
        rows = [r for r in rows if r.element_type == element_type]
    return [_element_dict(e) for e in rows]


@router.post("/elements")
async def element_create(
    body: ElementBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    exists = (
        await db.execute(select(AppElement).where(AppElement.name == body.name))
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(400, f"元素名称已存在: {body.name}")
    e = AppElement(
        name=body.name,
        element_type=body.element_type,
        project_id=body.project_id,
        tags=body.tags,
        config=body.config,
        resolution_configs=body.resolution_configs,
        created_by_id=user.id,
    )
    db.add(e)
    await db.commit()
    await db.refresh(e)
    return _element_dict(e)


@router.put("/elements/{eid}")
async def element_update(
    eid: int,
    body: ElementBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(AppElement).where(AppElement.id == eid))
    e = r.scalar_one_or_none()
    if not e:
        raise HTTPException(404, "元素不存在")
    e.name, e.element_type, e.tags, e.config = (
        body.name,
        body.element_type,
        body.tags,
        body.config,
    )
    e.resolution_configs = body.resolution_configs
    e.project_id = body.project_id
    await db.commit()
    return _element_dict(e)


@router.delete("/elements/{eid}")
async def element_delete(
    eid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    r = await db.execute(select(AppElement).where(AppElement.id == eid))
    e = r.scalar_one_or_none()
    if not e:
        raise HTTPException(404, "元素不存在")
    e.is_active = False
    await db.commit()
    return {"success": True}


@router.post("/elements/batch-delete")
async def element_batch_delete(
    body: Dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ids = body.get("ids", [])
    if not ids:
        return {"success": True, "deleted": 0}
    rows = (
        (await db.execute(select(AppElement).where(AppElement.id.in_(ids))))
        .scalars()
        .all()
    )
    for e in rows:
        e.is_active = False
    await db.commit()
    return {"success": True, "deleted": len(rows)}


@router.post("/elements/upload")
async def element_upload(
    category: str = Form("common"),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """上传元素截图模板(image 类元素)"""
    import hashlib

    cat_dir = os.path.join(mock_device.TEMPLATE_DIR, category)
    os.makedirs(cat_dir, exist_ok=True)
    content = await file.read()
    file_hash = hashlib.md5(content).hexdigest()[:12]
    filename = f"{file_hash}_{file.filename}"
    path = os.path.join(cat_dir, filename)
    with open(path, "wb") as f:
        f.write(content)
    return {
        "success": True,
        "image_category": category,
        "image_path": f"{category}/{filename}",
        "file_hash": file_hash,
        "url": "/api/app-automation/media?path=" + path,
    }


@router.get("/elements/image-categories")
async def image_categories(user: User = Depends(get_current_user)):
    base = mock_device.TEMPLATE_DIR
    cats = []
    if os.path.isdir(base):
        for name in sorted(os.listdir(base)):
            full = os.path.join(base, name)
            if os.path.isdir(full):
                count = len(
                    [f for f in os.listdir(full) if f.endswith((".png", ".jpg"))]
                )
                cats.append({"name": name, "image_count": count})
    if not cats:
        cats = [{"name": "common", "image_count": 0}]
    return cats


@router.post("/elements/image-categories/create")
async def image_category_create(
    body: Dict[str, Any], user: User = Depends(get_current_user)
):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "分类名不能为空")
    os.makedirs(os.path.join(mock_device.TEMPLATE_DIR, name), exist_ok=True)
    return {"success": True, "name": name}


@router.delete("/elements/image-categories/{name}")
async def image_category_delete(name: str, user: User = Depends(get_current_user)):
    full = os.path.join(mock_device.TEMPLATE_DIR, name)
    if os.path.isdir(full) and name != "common":
        shutil.rmtree(full)
    return {"success": True}


# ============ 组件 / 自定义组件 / 组件包 ============


class ComponentBody(BaseModel):
    name: str
    type: str = "click"
    description: str = ""
    config: Dict[str, Any] = {}
    enabled: bool = True
    sort_order: int = 0


def _comp_dict(c) -> Dict[str, Any]:
    return {
        "id": c.id,
        "name": c.name,
        "type": c.type,
        "description": c.description,
        "config": c.config or {},
        "enabled": c.enabled,
        "sort_order": c.sort_order,
    }


@router.get("/components")
async def component_list(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    rows = (
        (await db.execute(select(AppComponent).order_by(AppComponent.sort_order)))
        .scalars()
        .all()
    )
    if not rows:  # 初始化基础组件
        base_defs = [
            ("点击", "click", {"selector_type": "text"}),
            ("双击", "double_click", {"selector_type": "text"}),
            ("滑动", "swipe", {}),
            ("等待元素", "wait", {"timeout": 5}),
            ("休眠", "sleep", {"duration": 1}),
            ("检查存在", "exists", {}),
            ("截图", "snapshot", {}),
            ("输入文本", "text", {}),
            ("设置变量", "set_variable", {}),
            ("断言", "assert", {}),
            ("返回", "back", {}),
        ]
        for i, (n, t, cfg) in enumerate(base_defs):
            db.add(AppComponent(name=n, type=t, config=cfg, sort_order=i))
        await db.commit()
        rows = (
            (await db.execute(select(AppComponent).order_by(AppComponent.sort_order)))
            .scalars()
            .all()
        )
    return [_comp_dict(c) for c in rows]


@router.post("/components")
async def component_create(
    body: ComponentBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    c = AppComponent(
        name=body.name,
        type=body.type,
        description=body.description,
        config=body.config,
        enabled=body.enabled,
        sort_order=body.sort_order,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return _comp_dict(c)


@router.put("/components/{cid}")
async def component_update(
    cid: int,
    body: ComponentBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(AppComponent).where(AppComponent.id == cid))
    c = r.scalar_one_or_none()
    if not c:
        raise HTTPException(404, "组件不存在")
    c.name, c.type, c.description, c.config, c.enabled, c.sort_order = (
        body.name,
        body.type,
        body.description,
        body.config,
        body.enabled,
        body.sort_order,
    )
    await db.commit()
    return _comp_dict(c)


@router.delete("/components/{cid}")
async def component_delete(
    cid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    r = await db.execute(select(AppComponent).where(AppComponent.id == cid))
    c = r.scalar_one_or_none()
    if not c:
        raise HTTPException(404, "组件不存在")
    await db.delete(c)
    await db.commit()
    return {"success": True}


@router.get("/custom-components")
async def custom_component_list(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    rows = (
        (
            await db.execute(
                select(AppCustomComponent).order_by(AppCustomComponent.sort_order)
            )
        )
        .scalars()
        .all()
    )
    return [
        _comp_dict(c)
        | {
            "schema": c.schema,
            "default_config": c.default_config,
            "steps": c.steps or [],
        }
        for c in rows
    ]


@router.post("/custom-components")
async def custom_component_create(
    body: Dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    c = AppCustomComponent(
        name=body.get("name", ""),
        type=body.get("type", "composite"),
        description=body.get("description", ""),
        schema=body.get("schema", {}),
        default_config=body.get("default_config", {}),
        steps=body.get("steps", []),
        sort_order=body.get("sort_order", 0),
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return {"id": c.id, "name": c.name}


@router.put("/custom-components/{cid}")
async def custom_component_update(
    cid: int,
    body: Dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(AppCustomComponent).where(AppCustomComponent.id == cid))
    c = r.scalar_one_or_none()
    if not c:
        raise HTTPException(404, "自定义组件不存在")
    for k in (
        "name",
        "type",
        "description",
        "schema",
        "default_config",
        "steps",
        "enabled",
        "sort_order",
    ):
        if k in body:
            setattr(c, k, body[k])
    await db.commit()
    return {"id": c.id, "name": c.name}


@router.delete("/custom-components/{cid}")
async def custom_component_delete(
    cid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    r = await db.execute(select(AppCustomComponent).where(AppCustomComponent.id == cid))
    c = r.scalar_one_or_none()
    if not c:
        raise HTTPException(404, "自定义组件不存在")
    await db.delete(c)
    await db.commit()
    return {"success": True}


@router.get("/component-packages")
async def component_package_list(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    rows = (
        (
            await db.execute(
                select(AppComponentPackage).order_by(
                    AppComponentPackage.updated_at.desc()
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": p.id,
            "name": p.name,
            "version": p.version,
            "description": p.description,
            "author": p.author,
            "source": p.source,
            "manifest": p.manifest or {},
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in rows
    ]


@router.post("/component-packages")
async def component_package_create(
    body: Dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    p = AppComponentPackage(
        name=body.get("name", ""),
        version=body.get("version", ""),
        description=body.get("description", ""),
        author=body.get("author", ""),
        source=body.get("source", "upload"),
        manifest=body.get("manifest", {}),
        created_by_id=user.id,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return {"id": p.id, "name": p.name}


@router.post("/component-packages/{pid}/install")
async def component_package_install(
    pid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """安装组件包:将 manifest 中的组件写入组件表"""
    r = await db.execute(
        select(AppComponentPackage).where(AppComponentPackage.id == pid)
    )
    pkg = r.scalar_one_or_none()
    if not pkg:
        raise HTTPException(404, "组件包不存在")
    manifest = pkg.manifest or {}
    installed = 0
    for comp in manifest.get("components", []):
        c = AppComponent(
            name=comp.get("name", ""),
            type=comp.get("type", "click"),
            description=comp.get("description", ""),
            config=comp.get("config", {}),
            sort_order=comp.get("sort_order", 99),
        )
        db.add(c)
        installed += 1
    for comp in manifest.get("custom_components", []):
        c = AppCustomComponent(
            name=comp.get("name", ""),
            type=comp.get("type", "composite"),
            description=comp.get("description", ""),
            schema=comp.get("schema", {}),
            default_config=comp.get("default_config", {}),
            steps=comp.get("steps", []),
        )
        db.add(c)
        installed += 1
    await db.commit()
    return {"success": True, "installed": installed}


@router.delete("/component-packages/{pid}")
async def component_package_delete(
    pid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    r = await db.execute(
        select(AppComponentPackage).where(AppComponentPackage.id == pid)
    )
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "组件包不存在")
    await db.delete(p)
    await db.commit()
    return {"success": True}


# ============ 应用包名 ============


class PackageBody(BaseModel):
    name: str
    package_name: str


@router.get("/packages")
async def package_list(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    rows = (
        (await db.execute(select(AppPackage).order_by(AppPackage.name))).scalars().all()
    )
    return [
        {
            "id": p.id,
            "name": p.name,
            "package_name": p.package_name,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in rows
    ]


@router.post("/packages")
async def package_create(
    body: PackageBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    exists = (
        await db.execute(
            select(AppPackage).where(AppPackage.package_name == body.package_name)
        )
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(400, f"包名已存在: {body.package_name}")
    p = AppPackage(
        name=body.name, package_name=body.package_name, created_by_id=user.id
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return {"id": p.id, "name": p.name, "package_name": p.package_name}


@router.put("/packages/{pid}")
async def package_update(
    pid: int,
    body: PackageBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(AppPackage).where(AppPackage.id == pid))
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "应用包不存在")
    p.name, p.package_name = body.name, body.package_name
    await db.commit()
    return {"id": p.id}


@router.delete("/packages/{pid}")
async def package_delete(
    pid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    r = await db.execute(select(AppPackage).where(AppPackage.id == pid))
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "应用包不存在")
    await db.delete(p)
    await db.commit()
    return {"success": True}
