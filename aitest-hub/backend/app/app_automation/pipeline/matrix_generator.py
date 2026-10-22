# -*- coding: utf-8 -*-
"""测试意图与用例矩阵生成(读取画像 → LLM 生成;无 AI 配置时规则模板降级)。"""
import json
import logging
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import AIConfig

logger = logging.getLogger(__name__)

MATRIX_SYSTEM_PROMPT = (
    "你是 APP 自动化测试设计专家。基于控件画像和需求,生成测试意图与用例矩阵。"
    "输出 JSON 数组,每项: {case_id, title, priority, steps: [{action: tap/input/assert/swipe, target: 业务控件语义, value: 可选}]}。"
    "步骤中 target 使用业务语义(如 '搜索好友入口'),不要写 XPath/坐标。只输出 JSON。"
)


def _profiles_summary(profiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {"control_id": p["control_id"], "role": p["role"], "page": p["page"],
         "actions": p["actions"], "risk": p["risk"]}
        for p in profiles
    ]


def _fallback_matrix(requirement: str, profiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """规则降级:按页面与可交互控件生成基础用例矩阵"""
    by_page: Dict[str, List[Dict[str, Any]]] = {}
    for p in profiles:
        by_page.setdefault(p["page"], []).append(p)
    cases = []
    seq = 0
    for page, plist in by_page.items():
        interactive = [p for p in plist if "tap" in p["actions"] or "input_text" in p["actions"]]
        for p in interactive:
            seq += 1
            steps = []
            if "input_text" in p["actions"]:
                steps.append({"action": "input", "target": p["control_id"], "value": "${test_value}"})
                steps.append({"action": "tap", "target": p["control_id"]})
            else:
                steps.append({"action": "tap", "target": p["control_id"]})
            steps.append({"action": "assert", "target": "页面指纹变化", "value": "changed"})
            cases.append({
                "case_id": f"{page.upper()[:4]}-{seq:03d}",
                "title": f"{p['role']} 操作验证({page})",
                "priority": "P1" if p["risk"] == "low" else "P2",
                "steps": steps,
            })
        if len(cases) >= 10:
            break
    return cases


async def generate_matrix(db: AsyncSession, requirement: str,
                          profiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = await db.execute(select(AIConfig).order_by(AIConfig.is_default.desc(), AIConfig.id.asc()))
    config = result.scalars().first()
    if not config or not config.api_key:
        return _fallback_matrix(requirement, profiles)

    base_url = (config.base_url or "https://api.openai.com/v1").rstrip("/")
    url = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                url,
                json={
                    "model": config.model_name or "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": MATRIX_SYSTEM_PROMPT},
                        {"role": "user", "content":
                            f"需求:\n{requirement or '(未提供,按控件画像推导)'}\n\n控件画像:\n"
                            + json.dumps(_profiles_summary(profiles), ensure_ascii=False)},
                    ],
                    "temperature": 0.3,
                },
                headers={"Authorization": f"Bearer {config.api_key}"},
            )
        if resp.status_code != 200:
            return _fallback_matrix(requirement, profiles)
        content = resp.json()["choices"][0]["message"]["content"]
        start, end = content.find("["), content.rfind("]")
        if start >= 0 and end > start:
            return json.loads(content[start:end + 1])
    except Exception as e:
        logger.warning(f"用例矩阵生成失败,规则降级: {e}")
    return _fallback_matrix(requirement, profiles)
