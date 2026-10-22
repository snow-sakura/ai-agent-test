"""根因分析（Root Cause）— /api/root-cause/*。

表前缀 rc_：rc_cases(id,title,symptom,log,err,env,firstSeen,sev,status,
hypothesis,evidence,fix,created_at)

- GET    /root-cause/cases             列表（先于 /{id} 注册）
- GET    /root-cause/cases/{id} 与 /root-cause/{id}   详情
- DELETE /root-cause/cases/{id} 与 /root-cause/{id}
- POST   /root-case/analyze → 实际路径 /root-cause/analyze
    body {symptom, log, err?, env?, save?, title?}
    → {hypothesis, evidence:[], fix, confidence, ...}（AI chat_json，失败回退 simple/本地）
- POST   /root-cause/cases/{id}/confirm  更新 status/fix

seed 2 条历史 case（UI/tool-root-cause.html 示例）。列表不鉴权；写操作鉴权。
"""
import json
import re
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.database import (
    SyncDB,
    get_db,
    db_commit,
    db_delete,
    db_execute,
    db_fetch_all,
    db_fetch_one,
    db_insert,
    db_update,
)
from app.core.deps import get_current_user
from app.services import ai

router = APIRouter(tags=["root-cause"])


class AnalyzeReq(BaseModel):
    symptom: str
    log: str = ""
    err: str = ""
    env: str = ""
    save: bool = False
    title: str = ""
    sev: str = ""


class ConfirmReq(BaseModel):
    status: str = "已确认"
    fix: str = ""


_SEED = [
    {
        "id": "RC-31",
        "title": "App 冒烟步骤 4 元素未找到",
        "symptom": "UI 冒烟「登录-浏览-下单」步骤 4 点击支付按钮失败，EX-906 执行中断",
        "log": "waiting for locator 'button.pay' timeout 30000ms\n  at CheckoutPage.clickPay (checkout.ts:88)",
        "err": "TimeoutError: locator not found",
        "env": "Android 13 · Xiaomi 12 · v2.4.0 · Appium 2.6",
        "firstSeen": "2026-09-22", "sev": "中危", "status": "已完成",
        "hypothesis": "前端 v2.4 改版将支付按钮由 button.pay 改为 data-testid=pay-btn，定位脚本未同步更新",
        "evidence": json.dumps([
            "变更记录：frontend #4821 改版提交",
            "失败截图 failure-step4.png 中按钮 class 已变为 pay-btn",
            "近 7 日同一失败模式占比 100%（3/3 次）",
        ], ensure_ascii=False),
        "fix": "1. 脚本改用 getByTestId 定位\n2. UI 自动化接入「定位策略降级」：testid → role → text\n3. 前端改版流程增加「选择器变更通知测试组」检查项",
        "created_at": "2026-09-22 03:10",
    },
    {
        "id": "RC-30",
        "title": "秒杀链路 4500 QPS 错误率抬升",
        "symptom": "阶梯压测 500→6000 QPS，实测 4500 后错误率升至 3.2%，目标 6000 未达成",
        "log": "HikariPool-1 - Connection is not available, request timed out after 30000ms\nslow log: INSERT INTO orders ... 1240ms",
        "err": "SQLTransientConnectionException: connection timeout",
        "env": "压测环境 · 4×8C · MySQL 8.0 · 连接池上限 100",
        "firstSeen": "2026-09-20", "sev": "高危", "status": "已完成",
        "hypothesis": "DB 连接池上限 100 打满，获取连接等待超时导致错误率 3.2%",
        "evidence": json.dumps([
            "监控：connection_wait_time P99 4.2s",
            "慢日志全部指向 order insert",
            "扩池前错误日志与连接等待峰值时间完全重合",
        ], ensure_ascii=False),
        "fix": "1. 连接池扩容至 200\n2. 开启读写分离分流查询\n3. 热点接口增加本地缓存（库存预扣）",
        "created_at": "2026-09-20 18:40",
    },
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


async def ensure_schema(db: SyncDB) -> None:
    await db_execute(
        db,
        """
    CREATE TABLE IF NOT EXISTS rc_cases (
        id TEXT PRIMARY KEY, title TEXT, symptom TEXT, log TEXT, err TEXT,
        env TEXT, firstSeen TEXT, sev TEXT, status TEXT, hypothesis TEXT,
        evidence TEXT, fix TEXT, created_at TEXT
    )""",
    )
    await db_commit(db)


async def seed_if_empty(db: SyncDB) -> None:
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM rc_cases", [])
    if row and row["c"]:
        return
    for c in _SEED:
        await db_insert(db, "rc_cases", dict(c))
    await db_commit(db)


async def _prepare(db: SyncDB) -> None:
    await ensure_schema(db)
    await seed_if_empty(db)


def _row(r: dict) -> dict:
    ev = r.get("evidence") or "[]"
    if isinstance(ev, str):
        try:
            ev = json.loads(ev)
        except Exception:
            ev = [x for x in ev.split("\n") if x.strip()]
    if not isinstance(ev, list):
        ev = [str(ev)]
    return {
        "id": r.get("id"), "title": r.get("title") or "",
        "symptom": r.get("symptom") or "", "log": r.get("log") or "",
        "err": r.get("err") or "", "env": r.get("env") or "",
        "firstSeen": r.get("firstSeen") or "", "sev": r.get("sev") or "中危",
        "status": r.get("status") or "分析中",
        "hypothesis": r.get("hypothesis") or "", "evidence": ev,
        "fix": r.get("fix") or "", "createdAt": r.get("created_at") or "",
        "created_at": r.get("created_at") or "",
    }


async def _load(db: SyncDB, cid: str) -> dict:
    row = await db_fetch_one(db, "SELECT * FROM rc_cases WHERE id=?", [cid])
    if not row:
        raise HTTPException(status_code=404, detail="case not found")
    return row


async def _next_id(db: SyncDB) -> str:
    rows = await db_fetch_all(db, "SELECT id FROM rc_cases WHERE id LIKE 'RC-%'", [])
    best = 0
    for r in rows:
        try:
            best = max(best, int(str(r["id"]).split("-")[-1]))
        except Exception:
            pass
    return "RC-%02d" % (best + 1)


# ---------------------------------------------------------------------------
# 列表 / 详情 / 删除
# ---------------------------------------------------------------------------

@router.get("/root-cause/cases")
async def list_cases(db: SyncDB = Depends(get_db)):
    await _prepare(db)
    rows = await db_fetch_all(db, "SELECT * FROM rc_cases ORDER BY id DESC", [])
    return [_row(r) for r in rows]


@router.get("/root-cause/cases/{cid}")
async def get_case(cid: str, db: SyncDB = Depends(get_db)):
    await _prepare(db)
    return _row(await _load(db, cid))


@router.get("/root-cause/{cid}")
async def get_case_alias(cid: str, db: SyncDB = Depends(get_db)):
    await _prepare(db)
    return _row(await _load(db, cid))


@router.delete("/root-cause/cases/{cid}")
async def delete_case(cid: str, db: SyncDB = Depends(get_db),
                      current_user: dict = Depends(get_current_user)):
    await _prepare(db)
    await _load(db, cid)
    await db_delete(db, "rc_cases", "id=?", [cid])
    return {"ok": True, "id": cid}


@router.delete("/root-cause/{cid}")
async def delete_case_alias(cid: str, db: SyncDB = Depends(get_db),
                            current_user: dict = Depends(get_current_user)):
    await _prepare(db)
    await _load(db, cid)
    await db_delete(db, "rc_cases", "id=?", [cid])
    return {"ok": True, "id": cid}


# ---------------------------------------------------------------------------
# 分析
# ---------------------------------------------------------------------------

_FALLBACK_HINTS = [
    (["元素", "locator", "定位", "not found", "未找到"],
     ("定位脚本与页面结构不一致（疑似前端改版未同步选择器）",
      ["失败日志中定位器与当前 DOM 不匹配", "同一失败模式重复出现"],
      "改用 data-testid 优先定位并接入定位策略降级；前端改版通知测试组")),
    (["qps", "压测", "错误率", "连接池", "超时", "timeout", "并发"],
     ("资源瓶颈（连接池/线程池打满）导致请求排队超时",
      ["错误日志与资源水位峰值时间重合", "慢日志集中在写路径"],
      "扩容连接池并开启读写分离；热点写路径增加缓冲/批量；补齐水位监控告警")),
    (["npe", "空指针", "崩溃", "堆栈", "crash"],
     ("异步回调发生在组件销毁后，或上游数据为空未兜底",
      ["堆栈顶帧位于生命周期回调", "崩溃集中在特定机型/场景"],
      "回调前校验 isDestroyed / 空值兜底；网络层统一 try-catch 上报")),
    (["双扣", "重复", "幂等", "回调"],
     ("回调/重试链路缺少幂等键，导致重复入账",
      ["错误时间戳与重复流水一致", "存在客户端重试记录"],
      "按业务单号加唯一键去重；回调处理器实现幂等表")),
]


def _local_analyze(symptom: str, log: str, err: str) -> dict:
    text = f"{symptom}\n{log}\n{err}".lower()
    for kws, (hyp, evidence, fix) in _FALLBACK_HINTS:
        if any(k.lower() in text for k in kws):
            return {"hypothesis": hyp, "evidence": list(evidence), "fix": fix,
                    "confidence": 0.62}
    return {
        "hypothesis": "信息不足，先按「环境差异 → 数据状态 → 代码变更」三步排查",
        "evidence": ["已收集现象与日志，未命中已知模式"],
        "fix": "补充复现步骤、影响范围与最近变更记录后重新分析；必要时开启更详细日志复跑。",
        "confidence": 0.4,
    }


def _coerce(data: dict) -> dict:
    hyp = str(data.get("hypothesis") or data.get("cause") or "").strip()
    fix = str(data.get("fix") or data.get("suggest") or data.get("solution") or "").strip()
    ev = data.get("evidence") or []
    if isinstance(ev, str):
        ev = [x for x in re.split(r"[\n·]|(?<=\d)\.\s", ev) if x.strip()]
    if not isinstance(ev, list):
        ev = [str(ev)]
    ev = [str(x).strip() for x in ev if str(x).strip()][:8]
    try:
        conf = float(data.get("confidence") or data.get("conf") or 0.6)
    except (TypeError, ValueError):
        conf = 0.6
    conf = max(0.0, min(1.0, conf))
    if conf > 1:  # 百分比输入
        conf = conf / 100.0
    return {"hypothesis": hyp, "evidence": ev, "fix": fix,
            "confidence": round(conf, 2)}


@router.post("/root-cause/analyze")
async def analyze(body: AnalyzeReq, db: SyncDB = Depends(get_db)):
    await _prepare(db)
    symptom = (body.symptom or "").strip()
    if not symptom:
        raise HTTPException(status_code=400, detail="symptom required")
    log = body.log or ""
    err = body.err or ""
    env = body.env or ""

    sys_prompt = (
        "你是测试平台根因分析专家。根据现象/日志/错误输出严格 JSON：\n"
        "{\"hypothesis\": \"一句话根因假设\", "
        "\"evidence\": [\"证据1\", \"证据2\"], "
        "\"fix\": \"可执行修复建议（可多行编号）\", "
        "\"confidence\": 0.0到1.0的置信度}\n"
        "只输出 JSON，不要 markdown 代码块。"
    )
    user_prompt = (
        f"现象：{symptom}\n日志：\n{log[:3000]}\n"
        f"错误：{err}\n环境：{env}"
    )

    result = None
    try:
        data = await ai.chat_json(
            db,
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": user_prompt}],
            module="根因分析",
        )
        if isinstance(data, dict):
            result = _coerce(data)
            if not result["hypothesis"]:
                result = None
    except Exception:
        result = None

    if result is None:
        # 二次尝试：simple 后尽力解析
        try:
            text = await ai.simple(db, user_prompt, system=sys_prompt,
                                   module="根因分析")
            m = re.search(r"\{.*\}", text or "", re.S)
            if m:
                result = _coerce(json.loads(m.group(0)))
        except Exception:
            result = None
    if result is None:
        result = _local_analyze(symptom, log, err)

    out = {
        "ok": True,
        "symptom": symptom,
        "hypothesis": result["hypothesis"],
        "evidence": result["evidence"],
        "fix": result["fix"],
        "confidence": result["confidence"],
    }

    if body.save:
        cid = await _next_id(db)
        title = (body.title or symptom)[:60]
        await db_insert(db, "rc_cases", {
            "id": cid, "title": title, "symptom": symptom, "log": log[:4000],
            "err": err, "env": env, "firstSeen": _now().split(" ")[0],
            "sev": body.sev or "中危", "status": "已完成",
            "hypothesis": result["hypothesis"],
            "evidence": json.dumps(result["evidence"], ensure_ascii=False),
            "fix": result["fix"], "created_at": _now(),
        })
        out["caseId"] = cid
    return out


@router.post("/root-cause/cases/{cid}/confirm")
async def confirm_case(cid: str, body: ConfirmReq, db: SyncDB = Depends(get_db),
                       current_user: dict = Depends(get_current_user)):
    await _prepare(db)
    row = await _load(db, cid)
    data = {"status": body.status or "已确认"}
    if body.fix.strip():
        data["fix"] = body.fix.strip()
    await db_update(db, "rc_cases", data, "id=?", [cid])
    return _row(await _load(db, cid))
