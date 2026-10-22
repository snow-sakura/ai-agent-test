"""生成序列调度 API — /api/gen-queue/*

免费模型=单任务序列，付费模型=并行序列。前端「序列生成」页签的后端。
写操作与 case-generator 保持一致：演示可匿名（created_by 记游客）。
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.database import SyncDB, get_db
from app.services import gen_queue

router = APIRouter(tags=["gen-queue"])


class SeqItemIn(BaseModel):
    requirement: str
    name: Optional[str] = None
    project_type: str = "web"
    test_type: str = "functional"


class SeqCreateReq(BaseModel):
    title: Optional[str] = None
    model_id: Optional[int] = None
    concurrency: Optional[int] = None
    items: List[SeqItemIn]
    created_by: Optional[str] = "guest"


class SchedSettingsReq(BaseModel):
    paid_concurrency: Optional[int] = None
    free_concurrency: Optional[int] = None


async def _ready(db: SyncDB) -> None:
    await gen_queue.ensure_ready(db)


@router.get("/gen-queue/scheduling-preview")
async def preview_schedule(
    model_id: Optional[int] = Query(None),
    task_count: int = Query(2, ge=1, le=50),
    db: SyncDB = Depends(get_db),
):
    """选定模型后的实时调度预览：免费→单任务序列；付费→并行N路。"""
    await _ready(db)
    return await gen_queue.scheduling_preview(db, model_id, task_count)


@router.get("/gen-queue/settings")
async def get_settings(db: SyncDB = Depends(get_db)):
    await _ready(db)
    return await gen_queue.get_scheduler_settings(db)


@router.put("/gen-queue/settings")
async def put_settings(body: SchedSettingsReq, db: SyncDB = Depends(get_db)):
    await _ready(db)
    return await gen_queue.save_scheduler_settings(
        db, body.paid_concurrency, body.free_concurrency
    )


@router.post("/gen-queue/sequences")
async def submit_sequence(body: SeqCreateReq, db: SyncDB = Depends(get_db)):
    await _ready(db)
    items: List[Dict[str, Any]] = [it.model_dump() for it in body.items]
    items = [it for it in items if str(it.get("requirement") or "").strip()]
    if not items:
        raise HTTPException(status_code=400, detail="请至少填写一条任务需求")
    if len(items) > 20:
        raise HTTPException(status_code=400, detail="单序列最多 20 个任务")
    seq = await gen_queue.create_sequence(
        db,
        title=body.title or "生成序列",
        items=items,
        model_id=body.model_id,
        concurrency_override=body.concurrency,
        user=body.created_by or "guest",
    )
    if not seq:
        raise HTTPException(status_code=500, detail="序列创建失败")
    gen_queue.start_sequence(seq["id"])
    return seq


@router.get("/gen-queue/sequences")
async def list_sequences(
    limit: int = Query(30, ge=1, le=100), db: SyncDB = Depends(get_db)
):
    await _ready(db)
    return await gen_queue.list_sequences(db, limit)


@router.get("/gen-queue/sequences/{sid}")
async def get_sequence(sid: str, db: SyncDB = Depends(get_db)):
    await _ready(db)
    seq = await gen_queue.get_sequence(db, sid)
    if not seq:
        raise HTTPException(status_code=404, detail="序列不存在")
    return seq


@router.post("/gen-queue/sequences/{sid}/cancel")
async def cancel_sequence(sid: str, db: SyncDB = Depends(get_db)):
    await _ready(db)
    seq = await gen_queue.cancel_sequence(db, sid)
    if not seq:
        raise HTTPException(status_code=404, detail="序列不存在")
    return seq


@router.post("/gen-queue/sequences/{sid}/retry-failed")
async def retry_failed(sid: str, db: SyncDB = Depends(get_db)):
    await _ready(db)
    seq = await gen_queue.retry_failed(db, sid)
    if not seq:
        raise HTTPException(status_code=404, detail="序列不存在")
    return seq
