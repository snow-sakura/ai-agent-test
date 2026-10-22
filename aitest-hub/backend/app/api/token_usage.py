"""Token 消费记录（Token Usage）— /api/token-usage/*

字段对齐 UI/tool-token-usage.html 的 records 字面量：
id,time,module,model,content,input,output,hit,dur,logId
计费：费用 = 输入×单价 + 输出×单价 + 命中×单价×0.2（命中按 2 折）。
"""

from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.core.database import (
    SyncDB,
    db_commit,
    db_fetch_all,
    db_fetch_one,
    db_insert,
    get_db,
)
from app.services.telemetry import ensure_schema

router = APIRouter(tags=["token-usage"])

# 模型单价（¥ / 千 Token）：in / out / hit（hit 为原价，计费时再乘 0.2）
_PRICE = {
    "DeepSeek-V3": {"in": 0.002, "out": 0.008, "hit": 0.0004},
    "通义千问-Max": {"in": 0.004, "out": 0.012, "hit": 0.0008},
    "硅基流动 · GLM-4": {"in": 0.001, "out": 0.004, "hit": 0.0002},
}
_DEFAULT_PRICE = _PRICE["DeepSeek-V3"]

# UI 内联种子（近 7 天），表空时灌入
_SEED = [
    (
        "TU-3121",
        "2026-09-22 16:42:18",
        "技能中心",
        "DeepSeek-V3",
        "调用技能「失败日志根因分析」生成分析结论",
        1240,
        868,
        320,
        4,
        1288,
    ),
    (
        "TU-3120",
        "2026-09-22 15:31:22",
        "Agent 中心",
        "DeepSeek-V3",
        "AT-11 用例生成官：为退款功能生成 20 条测试用例",
        2140,
        3610,
        860,
        42,
        1287,
    ),
    (
        "TU-3119",
        "2026-09-22 14:20:05",
        "AI 报告中心",
        "DeepSeek-V3",
        "生成「9 月第 3 周回归测试报告」汇总结论",
        3120,
        940,
        1240,
        35,
        1285,
    ),
    (
        "TU-3118",
        "2026-09-22 11:08:47",
        "去 AI 味中心",
        "通义千问-Max",
        "试运行对比「口语化人味」策略润色效果",
        680,
        720,
        0,
        3,
        1284,
    ),
    (
        "TU-3117",
        "2026-09-22 09:12:33",
        "AI 问答助手",
        "DeepSeek-V3",
        "咨询：秒杀场景压测方案怎么定 QPS（RAG 引用知识库 3 条）",
        1560,
        1180,
        640,
        7,
        1283,
    ),
    (
        "TU-3116",
        "2026-09-21 17:45:12",
        "根因分析",
        "DeepSeek-V3",
        "RC-31 App 冒烟步骤 4 元素未找到——根因定位",
        2480,
        1120,
        980,
        24,
        1282,
    ),
    (
        "TU-3115",
        "2026-09-21 16:02:19",
        "需求管理",
        "DeepSeek-V3",
        "解析 PRD《退款模块 v2.1》输出结构化测试点",
        4820,
        2210,
        1620,
        19,
        1281,
    ),
    (
        "TU-3114",
        "2026-09-21 10:30:08",
        "AI 用例工作台",
        "DeepSeek-V3",
        "流式生成退款功能用例集（会话第 3 轮精修）",
        1960,
        3240,
        520,
        12,
        1279,
    ),
    (
        "TU-3113",
        "2026-09-20 15:22:41",
        "Agent 中心",
        "通义千问-Max",
        "AT-10 接口巡检员：核心接口巡检 12 个（定时触发）",
        1420,
        860,
        380,
        72,
        1278,
    ),
    (
        "TU-3112",
        "2026-09-20 09:45:27",
        "技能中心",
        "硅基流动 · GLM-4",
        "调用技能「接口断言生成技能」生成 /v1/pay 断言",
        740,
        520,
        180,
        3,
        1277,
    ),
    (
        "TU-3111",
        "2026-09-19 11:02:56",
        "根因分析",
        "通义千问-Max",
        "RC-29 退款说明 200 字截断——缺陷溯源分析",
        1680,
        760,
        540,
        19,
        1275,
    ),
    (
        "TU-3110",
        "2026-09-19 04:10:33",
        "AI 报告中心",
        "DeepSeek-V3",
        "生成「支付模块安全周报」基线扫描结论",
        2240,
        1080,
        890,
        38,
        1274,
    ),
    # 补足约 30 条、覆盖近 7 天
    (
        "TU-3109",
        "2026-09-19 16:28:11",
        "AI 用例工作台",
        "DeepSeek-V3",
        "为登录模块补充边界值用例 15 条",
        1320,
        2450,
        410,
        15,
        1273,
    ),
    (
        "TU-3108",
        "2026-09-19 10:14:02",
        "需求管理",
        "DeepSeek-V3",
        "解析《会员积分规则》提取测试要点",
        3560,
        1420,
        980,
        21,
        1272,
    ),
    (
        "TU-3107",
        "2026-09-18 18:41:55",
        "技能中心",
        "DeepSeek-V3",
        "调用技能「回归集智能筛选」挑选 P0 回归集",
        890,
        640,
        260,
        5,
        1271,
    ),
    (
        "TU-3106",
        "2026-09-18 15:03:27",
        "AI 问答助手",
        "通义千问-Max",
        "咨询：Mock 服务如何模拟超时与半开连接",
        1180,
        960,
        320,
        6,
        1270,
    ),
    (
        "TU-3105",
        "2026-09-18 11:22:40",
        "Agent 中心",
        "DeepSeek-V3",
        "AT-09 报告撰写员：生成周度质量简报",
        2680,
        1540,
        720,
        28,
        1269,
    ),
    (
        "TU-3104",
        "2026-09-18 09:05:18",
        "去 AI 味中心",
        "通义千问-Max",
        "对「简报压缩」策略做 A/B 对比试验",
        540,
        480,
        0,
        2,
        1268,
    ),
    (
        "TU-3103",
        "2026-09-17 16:50:09",
        "根因分析",
        "DeepSeek-V3",
        "RC-27 支付回调重复——链路日志归因",
        3210,
        1360,
        1120,
        31,
        1267,
    ),
    (
        "TU-3102",
        "2026-09-17 14:11:33",
        "AI 报告中心",
        "DeepSeek-V3",
        "汇总「8 月线上缺陷复盘」章节结论",
        2860,
        1120,
        940,
        33,
        1266,
    ),
    (
        "TU-3101",
        "2026-09-17 10:38:44",
        "技能中心",
        "硅基流动 · GLM-4",
        "调用技能「SQL 造数」生成订单测试数据",
        620,
        780,
        140,
        4,
        1265,
    ),
    (
        "TU-3100",
        "2026-09-17 08:22:16",
        "AI 用例工作台",
        "DeepSeek-V3",
        "接口回归失败用例智能重排优先级",
        1480,
        860,
        420,
        9,
        1264,
    ),
    (
        "TU-3099",
        "2026-09-16 17:44:51",
        "需求管理",
        "DeepSeek-V3",
        "PRD《购物车改版》冲突点识别",
        4120,
        1680,
        1340,
        26,
        1263,
    ),
    (
        "TU-3098",
        "2026-09-16 15:19:07",
        "Agent 中心",
        "通义千问-Max",
        "AT-08 巡检摘要：夜间任务失败归并",
        980,
        720,
        280,
        8,
        1262,
    ),
    (
        "TU-3097",
        "2026-09-16 13:02:29",
        "AI 问答助手",
        "DeepSeek-V3",
        "咨询：Playwright trace 如何定位 flaky",
        1340,
        1040,
        360,
        7,
        1261,
    ),
    (
        "TU-3096",
        "2026-09-16 11:47:15",
        "去 AI 味中心",
        "通义千问-Max",
        "缺陷描述客观化策略试运行",
        760,
        680,
        0,
        3,
        1260,
    ),
    (
        "TU-3095",
        "2026-09-16 09:31:02",
        "技能中心",
        "DeepSeek-V3",
        "调用技能「日志错误聚类」梳理夜间告警",
        2140,
        980,
        760,
        18,
        1259,
    ),
    (
        "TU-3094",
        "2026-09-16 08:15:48",
        "AI 报告中心",
        "DeepSeek-V3",
        "生成「发布门禁通过率」周环比说明",
        1760,
        840,
        620,
        22,
        1258,
    ),
]


class _ListResp(BaseModel):
    items: List[dict]
    total: int
    page: int
    size: int


def _price(model: str) -> dict:
    return _PRICE.get(model or "", _DEFAULT_PRICE)


def _cost(model: str, input_t: int, output_t: int, hit_t: int) -> float:
    p = _price(model)
    return (
        input_t / 1000.0 * p["in"]
        + output_t / 1000.0 * p["out"]
        + hit_t / 1000.0 * p["hit"] * 0.2
    )


def _row(r: dict) -> dict:
    """映射 DB 行 → UI 字段（dur 秒、logId 指向 system_logs）。"""
    input_t = int(r.get("input") or 0)
    output_t = int(r.get("output") or 0)
    hit_t = int(r.get("hit") or 0)
    model = r.get("model") or ""
    log_id = r.get("log_id")
    return {
        "id": r.get("id") or "",
        "time": r.get("time") or "",
        "module": r.get("module") or "",
        "model": model,
        "content": r.get("content") or "",
        "input": input_t,
        "output": output_t,
        "hit": hit_t,
        "dur": int(r.get("dur") or 0),
        "logId": f"OP-{log_id}" if log_id else "",
        "cost": round(_cost(model, input_t, output_t, hit_t), 6),
        "price": _price(model),
    }


async def _init(db: SyncDB):
    """幂等建表（telemetry）+ 空库灌入种子。"""
    await ensure_schema(db)
    row = await db_fetch_one(db, "SELECT COUNT(*) AS c FROM token_usage", [])
    if row and row.get("c"):
        return
    for s in _SEED:
        await db_insert(
            db,
            "token_usage",
            {
                "id": s[0],
                "time": s[1],
                "module": s[2],
                "model": s[3],
                "content": s[4],
                "input": s[5],
                "output": s[6],
                "hit": s[7],
                "dur": s[8],
                "log_id": s[9],
            },
        )
    await db_commit(db)


def _in_range(t: str, start: str, end: str) -> bool:
    d = (t or "")[:10]
    if start and d and d < start:
        return False
    if end and d and d > end:
        return False
    return True


@router.get("/token-usage")
async def list_token_usage(
    q: str = Query("", description="调用内容/记录 ID 关键词"),
    module: str = Query("", description="来源模块"),
    model: str = Query("", description="模型"),
    start: str = Query("", description="起始日期 YYYY-MM-DD"),
    end: str = Query("", description="结束日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: SyncDB = Depends(get_db),
):
    """消费明细列表（只读，无需鉴权），按时间倒序分页。"""
    await _init(db)
    rows = await db_fetch_all(db, "SELECT * FROM token_usage ORDER BY time DESC", [])
    ql = (q or "").lower()
    items = []
    for r in rows:
        item = _row(r)
        if module and item["module"] != module:
            continue
        if model and item["model"] != model:
            continue
        if not _in_range(item["time"], start, end):
            continue
        if ql and ql not in (item["content"] + item["id"]).lower():
            continue
        items.append(item)
    total = len(items)
    page = max(1, page)
    start_i = (page - 1) * size
    return {
        "items": items[start_i : start_i + size],
        "total": total,
        "page": page,
        "size": size,
    }


@router.get("/token-usage/stats")
async def token_usage_stats(
    start: str = Query("", description="起始日期"),
    end: str = Query("", description="结束日期"),
    db: SyncDB = Depends(get_db),
):
    """汇总统计：总输入/输出/命中 Token、总费用、按模块/按天聚合。"""
    await _init(db)
    rows = await db_fetch_all(db, "SELECT * FROM token_usage", [])
    total_in = total_out = total_hit = 0
    total_cost = 0.0
    reqs = 0
    by_module: dict = {}
    by_day: dict = {}
    for r in rows:
        t = r.get("time") or ""
        if not _in_range(t, start, end):
            continue
        item = _row(r)
        total_in += item["input"]
        total_out += item["output"]
        total_hit += item["hit"]
        total_cost += item["cost"]
        reqs += 1
        m = item["module"]
        if m not in by_module:
            by_module[m] = {
                "module": m,
                "input": 0,
                "output": 0,
                "hit": 0,
                "cost": 0.0,
                "count": 0,
            }
        by_module[m]["input"] += item["input"]
        by_module[m]["output"] += item["output"]
        by_module[m]["hit"] += item["hit"]
        by_module[m]["cost"] += item["cost"]
        by_module[m]["count"] += 1
        day = t[:10]
        if day:
            if day not in by_day:
                by_day[day] = {
                    "day": day,
                    "cost": 0.0,
                    "count": 0,
                    "input": 0,
                    "output": 0,
                }
            by_day[day]["cost"] += item["cost"]
            by_day[day]["count"] += 1
            by_day[day]["input"] += item["input"]
            by_day[day]["output"] += item["output"]
    # 命中按 2 折，节省 = 命中×输入单价×0.8
    p = _price("DeepSeek-V3")
    saved = total_hit / 1000.0 * p["in"] * 0.8
    for v in by_module.values():
        v["cost"] = round(v["cost"], 6)
    for v in by_day.values():
        v["cost"] = round(v["cost"], 6)
    return {
        "totalCost": round(total_cost, 4),
        "totalIn": total_in,
        "totalOut": total_out,
        "totalHit": total_hit,
        "requests": reqs,
        "saved": round(saved, 4),
        "byModule": sorted(by_module.values(), key=lambda x: -x["cost"]),
        "byDay": sorted(by_day.values(), key=lambda x: x["day"]),
    }
